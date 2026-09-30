from __future__ import annotations

import html
import os
from typing import Any

import pandas as pd
import streamlit as st

from components.ui import render_page_header, render_tip
from models.story import PaperSource, PaperStory, ParsedPaper
from services.llm_provider import (
    DEFAULT_CLAUDE_CODE_MODEL,
    DEFAULT_OPENAI_MODEL,
    DEFAULT_OPENROUTER_MODEL,
    ClaudeCodeStoryProvider,
    LLMProviderError,
    OpenAIStoryProvider,
    OpenRouterStoryProvider,
    claude_code_available,
)
from services.paper_fetcher import FetchError, MAX_PDF_BYTES, fetch_page_metadata, fetch_pdf_bytes
from services.paper_parser import PDFParseError, parse_pdf_bytes, parsed_from_abstract
from services.similarity import clean_text, get_related_by_text, get_similar_papers
from services.story_generator import StoryGenerationError, generate_story
from utils.caching import sha256_bytes, sha256_text, story_cache_key
from utils.navigation import queue_state_updates


STORY_CSS = """
<style>
.story-shell { max-width: 560px; margin: 0 auto; }
.story-card {
    min-height: 660px;
    aspect-ratio: 9 / 16;
    max-height: 780px;
    padding: 2.1rem 2rem;
    border: 1px solid rgba(127,127,127,.24);
    border-radius: 28px;
    background: linear-gradient(155deg, rgba(99,102,241,.14), rgba(127,127,127,.035) 58%, rgba(14,165,233,.08));
    box-shadow: 0 18px 55px rgba(0,0,0,.08);
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    overflow: hidden;
}
.story-card[data-type="results"] { background: linear-gradient(155deg, rgba(16,185,129,.16), rgba(127,127,127,.03) 62%, rgba(6,182,212,.08)); }
.story-card[data-type="limitations"] { background: linear-gradient(155deg, rgba(245,158,11,.16), rgba(127,127,127,.03) 62%, rgba(239,68,68,.07)); }
.story-card[data-type="takeaway"] { background: linear-gradient(155deg, rgba(168,85,247,.16), rgba(127,127,127,.03) 62%, rgba(59,130,246,.08)); }
.story-meta { font-size: .82rem; opacity: .72; letter-spacing: .02em; }
.story-eyebrow { margin-top: 2rem; font-size: .78rem; font-weight: 750; text-transform: uppercase; letter-spacing: .12em; opacity: .72; }
.story-headline { font-size: clamp(1.85rem, 4vw, 2.65rem); line-height: 1.06; font-weight: 800; margin: .65rem 0 1.1rem; }
.story-body { font-size: 1.02rem; line-height: 1.55; opacity: .94; }
.story-bullets { margin: 1.1rem 0 0; padding-left: 1.25rem; }
.story-bullets li { margin: .55rem 0; line-height: 1.42; }
.story-footer { display: flex; justify-content: space-between; gap: 1rem; font-size: .78rem; opacity: .65; margin-top: 1.4rem; }
.story-progress { height: 5px; width: 100%; background: rgba(127,127,127,.20); border-radius: 999px; overflow: hidden; margin-bottom: 1rem; }
.story-progress > div { height: 100%; background: currentColor; opacity: .65; }
@media (max-width: 700px) {
  .story-card { min-height: 600px; padding: 1.6rem 1.45rem; border-radius: 22px; }
  .story-headline { font-size: 2rem; }
}
</style>
"""


def library_source_from_row(row: Any) -> dict:
    def value(name, default=""):
        raw = row.get(name, default)
        if pd.isna(raw):
            return default
        return raw

    paper_id = str(value("id", ""))
    year_value = value("year", None)
    return PaperSource(
        paper_id=paper_id,
        title=clean_text(value("title", "")),
        authors=clean_text(value("authors", "")),
        venue=clean_text(value("venue", "")),
        year=int(year_value) if year_value is not None and str(year_value) else None,
        paper_url=clean_text(value("paper_url", "")),
        pdf_url=clean_text(value("pdf_url", "")),
        abstract=clean_text(value("abstract", "")),
        source_kind="library",
    ).model_dump()


def _config(name: str, default: str = "") -> str:
    env_value = os.getenv(name)
    if env_value:
        return env_value
    try:
        value = st.secrets.get(name, default)
        return str(value) if value is not None else default
    except Exception:
        return default


def _init_state() -> None:
    st.session_state.setdefault("story_cache", {})
    st.session_state.setdefault("paper_parse_cache", {})
    st.session_state.setdefault("story_card_index", 0)
    st.session_state.setdefault("active_story", None)
    st.session_state.setdefault("story_source", None)
    st.session_state.setdefault("external_story_source", None)
    st.session_state.setdefault("uploaded_parsed_paper", None)
    st.session_state.setdefault("openrouter_session_key", "")


def _parse_full_paper(source: PaperSource) -> ParsedPaper:
    cache = st.session_state["paper_parse_cache"]
    cache_key = source.pdf_url or source.paper_url
    if cache_key and cache_key in cache:
        return ParsedPaper.model_validate(cache[cache_key])

    if not source.pdf_url:
        raise FetchError("No direct PDF URL is available. Upload the PDF instead.")

    pdf_bytes = fetch_pdf_bytes(source.pdf_url)
    parsed = parse_pdf_bytes(pdf_bytes, source.model_copy(deep=True))
    if cache_key:
        cache[cache_key] = parsed.model_dump()
    return parsed


def _generate(parsed: ParsedPaper) -> None:
    provider_choice = st.session_state.get("story_provider_choice", "Free public · OpenRouter")

    if provider_choice == "Claude subscription (local)":
        model = _config("CLAUDE_CODE_MODEL", DEFAULT_CLAUDE_CODE_MODEL)
        provider_name = "claude_code"
        provider = ClaudeCodeStoryProvider(model=model)
    elif provider_choice == "OpenAI API":
        api_key = _config("OPENAI_API_KEY")
        model = _config("OPENAI_MODEL", DEFAULT_OPENAI_MODEL)
        provider_name = "openai"
        if not api_key:
            st.info("OpenAI API is selected, but OPENAI_API_KEY is not configured.")
            return
        provider = OpenAIStoryProvider(api_key=api_key, model=model)
    else:
        api_key = st.session_state.get("openrouter_session_key", "").strip() or _config("OPENROUTER_API_KEY")
        model = _config("OPENROUTER_MODEL", DEFAULT_OPENROUTER_MODEL)
        provider_name = "openrouter"
        if not api_key:
            st.info(
                "Free public generation needs an OpenRouter key. "
                "Add a free key in Generation settings; it stays only in this browser session."
            )
            return
        provider = OpenRouterStoryProvider(
            api_key=api_key,
            model=model,
            site_url=_config("APP_URL"),
            site_name="LitRevBuddy",
        )

    source_fingerprint = sha256_text(parsed.full_text + "\n" + parsed.source.title)
    key = story_cache_key(
        source_fingerprint=source_fingerprint,
        provider=provider_name,
        model=model,
        mode=parsed.source_quality,
    )

    cache = st.session_state["story_cache"]
    if key in cache:
        story = PaperStory.model_validate(cache[key])
    else:
        with st.spinner(f"Building a source-grounded paper story with {provider_choice}..."):
            story = generate_story(parsed, provider)
        cache[key] = story.model_dump()

    st.session_state["active_story"] = story.model_dump()
    st.session_state["story_card_index"] = 0


def _handle_library_source(source: PaperSource) -> None:
    st.markdown(f"#### {source.title}")
    meta = " · ".join(bit for bit in [source.venue, str(source.year or ""), source.authors] if bit)
    if meta:
        st.caption(meta)

    col_a, col_b = st.columns(2)
    abstract_disabled = not bool(source.abstract.strip())
    if col_a.button("Quick story · abstract", use_container_width=True, disabled=abstract_disabled, key="story_abstract_generate"):
        try:
            _generate(parsed_from_abstract(source.model_copy(deep=True)))
        except (PDFParseError, LLMProviderError, StoryGenerationError) as exc:
            st.error(str(exc))

    full_disabled = not bool(source.pdf_url.strip())
    if col_b.button("Deeper story · full paper", use_container_width=True, disabled=full_disabled, key="story_full_generate"):
        try:
            parsed = _parse_full_paper(source.model_copy(deep=True))
            if parsed.extraction_notes:
                for note in parsed.extraction_notes:
                    st.caption(note)
            _generate(parsed)
        except (FetchError, PDFParseError, LLMProviderError, StoryGenerationError) as exc:
            st.error(str(exc))

    if abstract_disabled and full_disabled:
        st.warning("This record has neither a usable abstract nor a PDF URL. Try the external PDF upload below.")


def _external_source_controls() -> None:
    st.markdown("#### External paper")
    st.caption("Use a paper page, direct PDF, arXiv/OpenReview link, DOI, or upload a PDF. External PDFs are parsed in memory and are not written to the repository.")

    url = st.text_input("Paper URL or DOI", key="external_paper_url", placeholder="https://arxiv.org/abs/... or 10.xxxx/...")
    if st.button("Load external paper", key="load_external_paper"):
        try:
            source = fetch_page_metadata(url)
            st.session_state["external_story_source"] = source.model_dump()
            st.session_state["uploaded_parsed_paper"] = None
        except FetchError as exc:
            st.error(str(exc))

    external = st.session_state.get("external_story_source")
    if external:
        source = PaperSource.model_validate(external)
        st.markdown(f"**Loaded:** {source.title}")
        detail_bits = [source.venue, str(source.year or "")]
        st.caption(" · ".join(bit for bit in detail_bits if bit) or source.paper_url)
        col_a, col_b = st.columns(2)
        if col_a.button("Generate from available abstract", disabled=not bool(source.abstract), use_container_width=True, key="external_abs_generate"):
            try:
                _generate(parsed_from_abstract(source.model_copy(deep=True)))
            except (PDFParseError, LLMProviderError, StoryGenerationError) as exc:
                st.error(str(exc))
        if col_b.button("Fetch PDF and generate", disabled=not bool(source.pdf_url), use_container_width=True, key="external_pdf_generate"):
            try:
                _generate(_parse_full_paper(source.model_copy(deep=True)))
            except (FetchError, PDFParseError, LLMProviderError, StoryGenerationError) as exc:
                st.error(str(exc))
        if not source.abstract and not source.pdf_url:
            st.info("The page did not expose an abstract or direct PDF. Upload the PDF below.")

    uploaded = st.file_uploader("Upload PDF", type=["pdf"], key="story_pdf_upload")
    if uploaded is not None:
        data = uploaded.getvalue()
        if len(data) > MAX_PDF_BYTES:
            st.error(f"Uploaded PDFs are limited to {MAX_PDF_BYTES // (1024 * 1024)} MB.")
        else:
            digest = sha256_bytes(data)
            upload_cache_key = f"upload:{digest}"
            parsed_dump = st.session_state["paper_parse_cache"].get(upload_cache_key)
            if parsed_dump is None:
                source = PaperSource(
                    paper_id=digest,
                    title="Uploaded paper",
                    paper_url="",
                    pdf_url="",
                    source_kind="upload",
                )
                try:
                    parsed = parse_pdf_bytes(data, source)
                    st.session_state["paper_parse_cache"][upload_cache_key] = parsed.model_dump()
                    parsed_dump = parsed.model_dump()
                except PDFParseError as exc:
                    st.error(str(exc))
            if parsed_dump:
                st.session_state["uploaded_parsed_paper"] = parsed_dump
                parsed = ParsedPaper.model_validate(parsed_dump)
                st.markdown(f"**Parsed upload:** {parsed.source.title}")
                st.caption(f"{len(parsed.full_text):,} extracted characters · {len(parsed.sections)} detected sections")
                for note in parsed.extraction_notes:
                    st.caption(note)
                if st.button("Generate story from uploaded PDF", use_container_width=True, key="uploaded_pdf_generate"):
                    try:
                        _generate(parsed)
                    except (LLMProviderError, StoryGenerationError) as exc:
                        st.error(str(exc))


def _render_story_card(story: PaperStory) -> None:
    if not story.cards:
        st.warning("No verified story cards are available.")
        return

    index = min(max(int(st.session_state.get("story_card_index", 0)), 0), len(story.cards) - 1)
    st.session_state["story_card_index"] = index
    card = story.cards[index]
    progress = int(((index + 1) / len(story.cards)) * 100)
    card_type = re_safe(card.card_type)

    bullets = "".join(f"<li>{html.escape(item)}</li>" for item in card.bullets)
    bullets_html = f'<ul class="story-bullets">{bullets}</ul>' if bullets else ""
    venue_year = " · ".join(bit for bit in [story.venue, str(story.year or "")] if bit)

    st.html(STORY_CSS)
    card_html = (
        f'<div class="story-shell">'
        f'<div class="story-progress"><div style="width:{progress}%"></div></div>'
        f'<div class="story-card" data-type="{card_type}">'
        f'<div>'
        f'<div class="story-meta">{html.escape(venue_year)} · {index + 1} / {len(story.cards)}</div>'
        f'<div class="story-eyebrow">{html.escape(card.eyebrow)}</div>'
        f'<div class="story-headline">{html.escape(card.headline)}</div>'
        f'<div class="story-body">{html.escape(clean_text(card.body))}</div>'
        f'{bullets_html}'
        f'</div>'
        f'<div class="story-footer">'
        f'<span>{html.escape(card.claim_basis.replace("_", " "))}</span>'
        f'<span>{html.escape(card.source_section)}</span>'
        f'</div>'
        f'</div>'
        f'</div>'
    )
    st.html(card_html)

    nav_left, nav_mid, nav_right = st.columns([1, 2, 1])
    if nav_left.button("Previous", disabled=index == 0, use_container_width=True, key="story_prev"):
        st.session_state["story_card_index"] = index - 1
        st.rerun()
    nav_mid.caption(f"{story.short_title} · {index + 1} of {len(story.cards)}")
    if nav_right.button("Next", disabled=index == len(story.cards) - 1, use_container_width=True, key="story_next"):
        st.session_state["story_card_index"] = index + 1
        st.rerun()

    with st.expander("Source & provenance"):
        st.markdown(f"**Source section:** {card.source_section}")
        st.markdown(f"**Claim basis:** {card.claim_basis.replace('_', ' ')}")
        st.caption("Verified supporting span")
        st.write(card.evidence)


def re_safe(value: str) -> str:
    cleaned = "".join(ch for ch in (value or "").lower() if ch.isalnum() or ch in {"_", "-"})
    return cleaned or "default"


def _render_study_area(story: PaperStory) -> None:
    with st.expander("Study this paper", expanded=False):
        if story.key_concepts:
            st.markdown("**Key concepts**")
            st.write(" · ".join(story.key_concepts))
        if story.flashcards:
            st.markdown("**Flashcards**")
            for idx, flashcard in enumerate(story.flashcards, start=1):
                with st.expander(f"{idx}. {flashcard.question}"):
                    st.write(flashcard.answer)
                    st.caption(f"Source: {flashcard.source_section}")


def _render_related(story: PaperStory, df, vectorizer, svd, nn, vectors) -> None:
    related = pd.DataFrame()
    if story.paper_id:
        try:
            numeric_id = int(story.paper_id)
            match = df[df["id"] == numeric_id]
            if len(match):
                related = get_similar_papers(df, int(match.iloc[0]["row_idx"]), nn, vectors, top_k=5)
        except (TypeError, ValueError):
            pass

    if related.empty:
        query = f"{story.title} {story.one_line_summary}"
        related = get_related_by_text(df, query, vectorizer, svd, vectors, top_k=5)

    if related.empty:
        return

    st.subheader("Continue exploring")
    columns = [column for column in ["title", "venue", "year", "cluster_label", "similarity", "paper_url", "pdf_url"] if column in related.columns]
    st.dataframe(
        related[columns],
        use_container_width=True,
        hide_index=True,
        column_config={
            "paper_url": st.column_config.LinkColumn("Paper page"),
            "pdf_url": st.column_config.LinkColumn("PDF"),
            "similarity": st.column_config.NumberColumn("Similarity", format="%.3f"),
        },
    )


def render_story_view(df, vectorizer, svd, nn, vectors) -> None:
    _init_state()

    selected_source = st.session_state.get("story_source")
    if selected_source:
        try:
            source_for_back = PaperSource.model_validate(selected_source)
            if source_for_back.source_kind == "library" and source_for_back.paper_id:
                if st.button("← Back to paper", key="story_back_to_paper"):
                    queue_state_updates(
                        selected_paper_id=int(source_for_back.paper_id),
                        search_view="paper",
                        primary_nav="Search",
                    )
        except (TypeError, ValueError):
            pass

    render_page_header(
        "Paper Stories",
        "Turn a dense paper into a study-friendly walkthrough",
        "Choose a paper, decide how much source text to use, then generate verified cards for the problem, method, evidence, limitations, and takeaways.",
    )

    provider_options = ["Free public · OpenRouter"]
    if claude_code_available():
        provider_options.append("Claude subscription (local)")
    if _config("OPENAI_API_KEY"):
        provider_options.append("OpenAI API")

    if st.session_state.get("story_provider_choice") not in provider_options:
        st.session_state["story_provider_choice"] = provider_options[0]

    with st.expander("Generation settings", expanded=False):
        st.radio(
            "Provider",
            provider_options,
            horizontal=True,
            key="story_provider_choice",
        )

        if st.session_state["story_provider_choice"] == "Free public · OpenRouter":
            shared_key = _config("OPENROUTER_API_KEY")
            if shared_key:
                st.caption(
                    "Using LitRevBuddy's shared free OpenRouter quota. If it is temporarily exhausted, "
                    "you can use your own free key below."
                )
                personal_key = st.text_input(
                    "Optional personal OpenRouter key",
                    type="password",
                    key="openrouter_personal_key_input",
                    placeholder="sk-or-v1-…",
                    help="Used only for this browser session and never written to the repository.",
                )
                st.session_state["openrouter_session_key"] = personal_key.strip()
            else:
                st.caption(
                    "OpenRouter offers a free model router. Create a free API key, paste it below, "
                    "and LitRevBuddy will use it only for this browser session."
                )
                personal_key = st.text_input(
                    "OpenRouter API key",
                    type="password",
                    key="openrouter_personal_key_input",
                    placeholder="sk-or-v1-…",
                    help="This value is kept in Streamlit session state only.",
                )
                st.session_state["openrouter_session_key"] = personal_key.strip()
                st.markdown("[Create a free OpenRouter key ↗](https://openrouter.ai/keys)")
        elif st.session_state["story_provider_choice"] == "Claude subscription (local)":
            st.caption(
                "Uses the Claude Code login on this computer. No Anthropic API key is required for local testing."
            )
        else:
            st.caption("Uses the configured OpenAI API key.")

    source_tabs = st.tabs(["From LitRevBuddy", "Bring your own paper"])
    with source_tabs[0]:
        selected = st.session_state.get("story_source")
        if selected:
            st.caption("STEP 1 · SOURCE")
            _handle_library_source(PaperSource.model_validate(selected))
            st.caption("Abstract mode is faster. Full-paper mode can support richer method, result, and limitation cards when a PDF is available.")
        else:
            render_tip("Open a paper from Discover or Paper and choose 'Explain as Story'. You can also load a URL or PDF in the next tab.")
    with source_tabs[1]:
        _external_source_controls()

    active = st.session_state.get("active_story")
    if not active:
        return

    story = PaperStory.model_validate(active)
    st.divider()
    label = "Full-paper summary" if story.source_quality == "full_paper" else "Abstract-based summary"
    st.caption(f"STEP 2 · STORY · {label}")
    st.markdown(f"### {story.title}")
    st.write(story.one_line_summary)
    _render_story_card(story)
    _render_study_area(story)
    st.divider()
    _render_related(story, df, vectorizer, svd, nn, vectors)
