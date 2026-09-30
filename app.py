from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st

from components.paper_view import render_paper_card
from components.story_view import library_source_from_row, render_story_view
from components.ui import (
    inject_global_styles,
    render_app_header,
    render_page_header,
    render_result_preview,
    render_tip,
)
from services.similarity import get_similar_papers, query_scores
from utils.navigation import apply_pending_state_updates, queue_state_updates


ARTIFACT_DIR = Path("artifacts")
NAV_OPTIONS = ["Search", "Explore", "Stories", "About"]
NAV_LABELS = {
    "Search": "🔎 Search",
    "Explore": "🧭 Explore",
    "Stories": "✨ Stories",
    "About": "About",
}

st.set_page_config(
    page_title="LitRevBuddy",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="collapsed",
)


@st.cache_data(show_spinner=False)
def load_papers():
    return pd.read_parquet(ARTIFACT_DIR / "papers_features.parquet")


@st.cache_resource(show_spinner=False)
def load_models():
    vectorizer = joblib.load(ARTIFACT_DIR / "tfidf_vectorizer.joblib")
    svd = joblib.load(ARTIFACT_DIR / "svd_model.joblib")
    nn = joblib.load(ARTIFACT_DIR / "nearest_neighbors.joblib")
    vectors = np.load(ARTIFACT_DIR / "paper_vectors.npz")["vectors"]
    return vectorizer, svd, nn, vectors


def _reset_paper_detail() -> None:
    st.session_state["selected_paper_id"] = None
    st.session_state["search_view"] = "results"


def _open_paper(paper_id) -> None:
    queue_state_updates(
        selected_paper_id=int(paper_id),
        search_view="paper",
        primary_nav="Search",
    )


def _open_story(row) -> None:
    queue_state_updates(
        story_source=library_source_from_row(row),
        active_story=None,
        story_card_index=0,
        primary_nav="Stories",
    )


def _filter_papers(df, query, selected_venues, selected_years, min_score, vectorizer, svd, vectors):
    scores = query_scores(query, vectorizer, svd, vectors)
    working = df.copy()
    working["score"] = scores

    mask = (
        working["venue"].isin(selected_venues)
        & working["year"].astype(int).isin(selected_years)
    )
    working = working[mask].copy()

    if query.strip():
        working = working[working["score"] >= min_score]
        working = working.sort_values("score", ascending=False)
    else:
        working = working.sort_values(
            ["year", "venue", "title"],
            ascending=[False, True, True],
        )
    return working


inject_global_styles()

with st.spinner("Loading the paper library…"):
    df = load_papers()
    vectorizer, svd, nn, vectors = load_models()

venues = sorted(df["venue"].dropna().unique().tolist())
years = sorted(df["year"].dropna().astype(int).unique().tolist(), reverse=True)

st.session_state.setdefault("primary_nav", "Search")
st.session_state.setdefault("global_query", "")
st.session_state.setdefault("filter_venues", venues)
st.session_state.setdefault("filter_years", years)
st.session_state.setdefault("result_limit", 15)
st.session_state.setdefault("min_score", 0.0)
st.session_state.setdefault("selected_paper_id", None)
st.session_state.setdefault("search_view", "results")

apply_pending_state_updates()

render_app_header(len(df))

navigation = st.radio(
    "Navigation",
    NAV_OPTIONS,
    horizontal=True,
    format_func=lambda value: NAV_LABELS[value],
    label_visibility="collapsed",
    key="primary_nav",
)

if navigation == "Search":
    if st.session_state.get("search_view") == "paper" and st.session_state.get("selected_paper_id"):
        selected_id = int(st.session_state["selected_paper_id"])
        match = df[df["id"] == selected_id]

        if match.empty:
            _reset_paper_detail()
            st.rerun()

        selected = match.iloc[0]

        if st.button("← Back to search results"):
            _reset_paper_detail()
            st.rerun()

        render_paper_card(selected)

        action_a, action_b, action_c = st.columns([1.35, 1.1, 3])
        if action_a.button("✨ Understand this paper", type="primary", use_container_width=True):
            _open_story(selected)
        pdf_url = str(selected.get("pdf_url", "") or "").strip()
        if pdf_url:
            action_b.markdown(f"[Open PDF ↗]({pdf_url})")

        st.divider()
        render_page_header(
            "Related work",
            "Continue from this paper",
            "These papers are nearest neighbors in LitRevBuddy's 128-dimensional topic representation.",
        )

        similar = get_similar_papers(
            df,
            int(selected["row_idx"]),
            nn,
            vectors,
            top_k=8,
        )
        if similar.empty:
            st.info("No related papers were found.")
        else:
            for _, row in similar.iterrows():
                with st.container(border=True):
                    left, right = st.columns([5, 1.1], vertical_alignment="center")
                    with left:
                        st.caption(f"Similarity {float(row['similarity']):.3f}")
                        render_result_preview(row)
                    with right:
                        if st.button(
                            "Open",
                            key=f"related_{int(row['id'])}",
                            use_container_width=True,
                        ):
                            _open_paper(row["id"])
        st.stop()

    render_page_header(
        "Literature search",
        "Find the research that matters",
        "Search recent AI papers by topic, method, task, author, or phrase. Open a paper to read it in context or turn it into a source-grounded story.",
    )

    query = st.text_input(
        "Search 67,343 papers",
        key="global_query",
        placeholder="e.g. multimodal glioblastoma survival prediction",
        label_visibility="collapsed",
    )

    with st.expander("Filters", expanded=False):
        filter_a, filter_b = st.columns(2)
        with filter_a:
            selected_venues = st.multiselect(
                "Venues",
                venues,
                key="filter_venues",
            )
        with filter_b:
            selected_years = st.multiselect(
                "Years",
                years,
                key="filter_years",
            )

        control_a, control_b, control_c = st.columns([1, 1, 2])
        if control_a.button(f"{max(years)} only", use_container_width=True):
            queue_state_updates(filter_years=[max(years)])
        if control_b.button("Reset filters", use_container_width=True):
            queue_state_updates(
                filter_venues=venues,
                filter_years=years,
                min_score=0.0,
            )
        with control_c:
            min_score = st.slider(
                "Minimum relevance",
                0.0,
                1.0,
                step=0.01,
                key="min_score",
                disabled=not bool(query.strip()),
                help="Advanced control. Most searches work best at 0.",
            )

    selected_venues = st.session_state.get("filter_venues", venues)
    selected_years = st.session_state.get("filter_years", years)
    min_score = float(st.session_state.get("min_score", 0.0))

    working = _filter_papers(
        df,
        query,
        selected_venues,
        selected_years,
        min_score,
        vectorizer,
        svd,
        vectors,
    )

    if not query.strip():
        render_tip(
            "Try a research question, not just a keyword — for example: "
            "'vision-language models for medical image segmentation'."
        )

    if working.empty:
        st.info("No papers match the current search and filters. Try broadening the venue/year selection.")
    else:
        visible_count = min(int(st.session_state.get("result_limit", 15)), len(working))
        st.caption(f"{len(working):,} matches · showing {visible_count:,}")

        for rank, (_, row) in enumerate(working.head(visible_count).iterrows(), start=1):
            with st.container(border=True):
                left, right = st.columns([5, 1.3], vertical_alignment="center")
                with left:
                    st.caption(f"#{rank}")
                    render_result_preview(row, show_score=bool(query.strip()))
                with right:
                    if st.button(
                        "Read paper",
                        key=f"search_open_{int(row['id'])}",
                        use_container_width=True,
                    ):
                        _open_paper(row["id"])
                    if st.button(
                        "✨ Explain",
                        key=f"search_story_{int(row['id'])}",
                        use_container_width=True,
                    ):
                        _open_story(row)

                    links = []
                    paper_url = str(row.get("paper_url", "") or "").strip()
                    pdf_url = str(row.get("pdf_url", "") or "").strip()
                    if paper_url:
                        links.append(f"[Page ↗]({paper_url})")
                    if pdf_url:
                        links.append(f"[PDF ↗]({pdf_url})")
                    if links:
                        st.markdown(" · ".join(links))

        if visible_count < len(working):
            more_col, _ = st.columns([1, 4])
            if more_col.button("Load 15 more", use_container_width=True):
                st.session_state["result_limit"] = min(visible_count + 15, 120)
                st.rerun()

elif navigation == "Explore":
    render_page_header(
        "Research landscape",
        "Explore the literature by theme",
        "Browse automatically discovered research themes or switch to the topic map to see how papers sit near one another.",
    )

    if "explore_query" not in st.session_state:
        st.session_state["explore_query"] = st.session_state.get("global_query", "")
    if "explore_venues" not in st.session_state:
        st.session_state["explore_venues"] = st.session_state.get("filter_venues", venues)
    if "explore_years" not in st.session_state:
        st.session_state["explore_years"] = st.session_state.get("filter_years", years)

    explore_query = st.text_input(
        "Search within Explore",
        placeholder="Focus Explore on a topic, or leave blank for the full recent library",
        key="explore_query",
    )

    explore_filters = st.expander("Scope Explore", expanded=False)
    with explore_filters:
        explore_a, explore_b = st.columns(2)
        explore_venues = explore_a.multiselect(
            "Venues",
            venues,
            key="explore_venues",
        )
        explore_years = explore_b.multiselect(
            "Years",
            years,
            key="explore_years",
        )

    explore_df = _filter_papers(
        df,
        explore_query,
        explore_venues,
        explore_years,
        0.0,
        vectorizer,
        svd,
        vectors,
    ).head(3000)

    topic_tab, map_tab = st.tabs(["Topics", "Map"])

    with topic_tab:
        if explore_df.empty:
            st.info("Nothing to explore with the current scope.")
        else:
            cluster_summary = (
                explore_df.groupby(["cluster_id", "cluster_label"], as_index=False)
                .agg(
                    papers=("id", "count"),
                    avg_score=("score", "mean"),
                    latest_year=("year", "max"),
                )
                .sort_values(
                    ["papers", "avg_score"],
                    ascending=[False, False],
                )
            )

            selected_cluster = st.selectbox(
                "Research theme",
                cluster_summary["cluster_id"].tolist(),
                format_func=lambda cluster_id: (
                    f"{cluster_summary.loc[cluster_summary['cluster_id'] == cluster_id, 'cluster_label'].iloc[0]}"
                    f" · {int(cluster_summary.loc[cluster_summary['cluster_id'] == cluster_id, 'papers'].iloc[0])} papers"
                ),
                label_visibility="collapsed",
            )

            cluster_rows = explore_df[explore_df["cluster_id"] == selected_cluster].copy()
            cluster_name = cluster_summary.loc[
                cluster_summary["cluster_id"] == selected_cluster,
                "cluster_label",
            ].iloc[0]

            st.markdown(f"### {cluster_name}")
            st.caption(f"{len(cluster_rows):,} papers in this view")

            for _, row in cluster_rows.head(10).iterrows():
                with st.container(border=True):
                    left, right = st.columns([5, 1.1], vertical_alignment="center")
                    with left:
                        render_result_preview(row, show_score=bool(explore_query.strip()))
                    with right:
                        if st.button(
                            "Open",
                            key=f"topic_open_{int(row['id'])}",
                            use_container_width=True,
                        ):
                            _open_paper(row["id"])

    with map_tab:
        if explore_df.empty:
            st.info("Nothing to plot with the current scope.")
        else:
            plot_df = explore_df
            if len(plot_df) > 2500:
                plot_df = plot_df.sample(2500, random_state=13)

            fig = px.scatter(
                plot_df,
                x="x",
                y="y",
                color="venue",
                hover_name="title",
                hover_data={
                    "year": True,
                    "cluster_label": True,
                    "x": False,
                    "y": False,
                },
                height=720,
            )
            fig.update_traces(marker=dict(size=6, opacity=0.72))
            fig.update_layout(
                margin=dict(l=0, r=0, t=10, b=0),
                xaxis_title=None,
                yaxis_title=None,
                legend_title_text="Venue",
            )
            st.plotly_chart(fig, use_container_width=True)
            st.caption(
                "Nearby points have similar topic representations. "
                "Use Topics when you want a cleaner, list-based way to browse."
            )

elif navigation == "Stories":
    render_story_view(df, vectorizer, svd, nn, vectors)

elif navigation == "About":
    render_page_header(
        "About LitRevBuddy",
        "A research discovery and paper-understanding workspace",
        "LitRevBuddy combines a curated recent-paper index with lightweight semantic retrieval, topic exploration, related-work discovery, and source-grounded AI explanations.",
    )

    stats = st.columns(4)
    stats[0].metric("Papers", f"{len(df):,}")
    stats[1].metric("Venues", f"{df['venue'].nunique():,}")
    stats[2].metric("Years", f"{df['year'].nunique():,}")
    stats[3].metric("Research themes", f"{df['cluster_id'].nunique():,}")

    st.markdown("### What you can do")
    col_a, col_b, col_c = st.columns(3)
    with col_a:
        st.markdown("#### Search")
        st.write("Find relevant papers across recent major AI and medical-AI venues.")
    with col_b:
        st.markdown("#### Understand")
        st.write("Convert an abstract or full paper into source-grounded explanation cards and study aids.")
    with col_c:
        st.markdown("#### Connect")
        st.write("Move from one paper to related work, neighboring themes, and the broader research landscape.")

    st.markdown("### How search works")
    st.write(
        "LitRevBuddy uses TF-IDF features followed by a 128-dimensional TruncatedSVD topic representation. "
        "The same representation powers query ranking, related-paper retrieval, clustering, and the 2D exploration map."
    )

    st.markdown("### Current coverage")
    coverage = (
        df.groupby(["venue", "year"])
        .size()
        .reset_index(name="papers")
        .sort_values(["year", "venue"], ascending=[False, True])
    )
    st.dataframe(
        coverage,
        use_container_width=True,
        hide_index=True,
        column_config={
            "venue": "Venue",
            "year": "Year",
            "papers": st.column_config.NumberColumn("Papers", format="%d"),
        },
    )

    st.caption(
        "AI-generated stories are designed as study aids, not substitutes for reading the source paper. "
        "Every displayed story card is checked against a supporting source span before it is shown."
    )
