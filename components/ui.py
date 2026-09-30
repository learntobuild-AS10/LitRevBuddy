from __future__ import annotations

import html
from typing import Any

import pandas as pd
import streamlit as st

from services.similarity import clean_text


GLOBAL_CSS = """
<style>
:root {
  --lrb-radius: 18px;
  --lrb-border: rgba(127,127,127,.20);
  --lrb-muted: rgba(127,127,127,.82);
}
.block-container {
  max-width: 1380px;
  padding-top: 1.35rem;
  padding-bottom: 4rem;
}
[data-testid="stSidebar"] > div:first-child {
  padding-top: 1.25rem;
}
[data-testid="stSidebar"] hr {
  margin: 1rem 0;
}
.lrb-hero {
  padding: 1.05rem 0 .85rem;
  overflow: visible;
}
.lrb-brand-row {
  display: flex;
  align-items: center;
  gap: .7rem;
  flex-wrap: wrap;
}
.lrb-brand {
  display: inline-block;
  font-size: clamp(2rem, 5vw, 3.35rem);
  font-weight: 800;
  line-height: 1.12;
  letter-spacing: -.04em;
  padding: .08em 0 .12em;
  overflow: visible;
}
.lrb-badge {
  display: inline-flex;
  align-items: center;
  border: 1px solid var(--lrb-border);
  border-radius: 999px;
  padding: .3rem .7rem;
  font-size: .78rem;
  opacity: .78;
}
.lrb-tagline {
  max-width: 760px;
  margin-top: .65rem;
  font-size: 1.02rem;
  line-height: 1.55;
  opacity: .78;
}
.lrb-page-eyebrow {
  margin-top: .35rem;
  font-size: .75rem;
  font-weight: 750;
  text-transform: uppercase;
  letter-spacing: .12em;
  opacity: .58;
}
.lrb-page-title {
  margin: .2rem 0 .3rem;
  font-size: clamp(1.65rem, 3.2vw, 2.25rem);
  font-weight: 800;
  line-height: 1.1;
  letter-spacing: -.025em;
}
.lrb-page-copy {
  max-width: 780px;
  margin-bottom: 1rem;
  line-height: 1.55;
  opacity: .72;
}
.lrb-result-meta {
  font-size: .83rem;
  opacity: .65;
  margin-bottom: .45rem;
}
.lrb-result-title {
  font-size: 1.08rem;
  line-height: 1.28;
  font-weight: 760;
  margin-bottom: .45rem;
}
.lrb-result-abstract {
  font-size: .92rem;
  line-height: 1.5;
  opacity: .82;
}
.lrb-help {
  border: 1px solid var(--lrb-border);
  border-radius: var(--lrb-radius);
  padding: .9rem 1rem;
  margin: .4rem 0 1rem;
  background: rgba(127,127,127,.035);
  line-height: 1.5;
}
div[data-testid="stMetric"] {
  border: 1px solid var(--lrb-border);
  border-radius: 16px;
  padding: .85rem 1rem;
  background: rgba(127,127,127,.025);
}
div[data-testid="stVerticalBlockBorderWrapper"] {
  border-radius: var(--lrb-radius);
}
.stButton > button, .stDownloadButton > button {
  min-height: 2.65rem;
  border-radius: 12px;
}
.st-key-top_nav div[role="radiogroup"] {
  gap: .4rem;
  flex-wrap: wrap;
}
.st-key-top_nav div[role="radiogroup"] label {
  border: 1px solid transparent;
  border-radius: 999px;
  padding: .42rem .78rem;
  transition: background .15s ease, border-color .15s ease;
}
.st-key-top_nav div[role="radiogroup"] label:hover {
  background: rgba(127,127,127,.08);
  border-color: var(--lrb-border);
}
.st-key-top_nav div[role="radiogroup"] label > div:first-child {
  display: none;
}
.st-key-top_nav div[role="radiogroup"] label:has(input:checked) {
  background: rgba(127,127,127,.12);
  border-color: var(--lrb-border);
}
@media (max-width: 760px) {
  .block-container { padding-top: .8rem; }
  .lrb-brand { font-size: 2.15rem; }
  .lrb-tagline { font-size: .95rem; }
}
</style>
"""


def inject_global_styles() -> None:
    st.html(GLOBAL_CSS)


def render_app_header(paper_count: int) -> None:
    title_col, count_col = st.columns([1.35, 4.65], vertical_alignment="center")
    with title_col:
        st.title("LitRevBuddy")
    with count_col:
        st.caption(f"{paper_count:,} indexed papers")

    st.markdown(
        "Search recent AI research, understand where a paper fits, find related work, "
        "and turn dense papers into source-grounded study stories."
    )


def render_page_header(eyebrow: str, title: str, description: str) -> None:
    st.html(
        f"""
        <div class="lrb-page-eyebrow">{html.escape(eyebrow)}</div>
        <div class="lrb-page-title">{html.escape(title)}</div>
        <div class="lrb-page-copy">{html.escape(description)}</div>
        """
    )


def truncate_text(value: Any, max_chars: int = 360) -> str:
    text = clean_text(value)
    if len(text) <= max_chars:
        return text
    shortened = text[: max_chars - 1].rsplit(" ", 1)[0]
    return shortened + "…"


def paper_meta(row: Any, include_cluster: bool = True) -> str:
    bits: list[str] = []
    venue = clean_text(row.get("venue", ""))
    year = row.get("year", "")
    if venue:
        bits.append(venue)
    if year is not None and not pd.isna(year) and str(year):
        bits.append(str(int(year)))
    if include_cluster:
        cluster = clean_text(row.get("cluster_label", ""))
        if cluster:
            bits.append(cluster)
    return " · ".join(bits)


def render_result_preview(row: Any, *, show_score: bool = False) -> None:
    title = clean_text(row.get("title", "Untitled paper"))
    abstract = truncate_text(row.get("abstract", ""), 410)
    meta = paper_meta(row)

    score_text = ""
    score = row.get("score")
    if show_score and score is not None and not pd.isna(score):
        score_text = f" · relevance {float(score):.3f}"

    st.html(
        f"""
        <div class="lrb-result-meta">{html.escape(meta + score_text)}</div>
        <div class="lrb-result-title">{html.escape(title)}</div>
        <div class="lrb-result-abstract">{html.escape(abstract or "Abstract unavailable.")}</div>
        """
    )


def render_tip(text: str) -> None:
    st.html(f'<div class="lrb-help">{html.escape(text)}</div>')
