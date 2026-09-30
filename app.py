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
from services.similarity import get_similar_papers, make_result_table, query_scores


ARTIFACT_DIR = Path("artifacts")
NAV_OPTIONS = ["Discover", "Topic map", "Clusters", "Paper", "Stories"]
NAV_LABELS = {
    "Discover": "🔎 Discover",
    "Topic map": "🗺️ Topic map",
    "Clusters": "🧭 Clusters",
    "Paper": "📄 Paper",
    "Stories": "✨ Stories",
}

st.set_page_config(
    page_title="LitRevBuddy",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded",
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


def _go_to_paper(paper_id) -> None:
    st.session_state["selected_paper_id"] = int(paper_id)
    st.session_state["paper_picker"] = int(paper_id)
    st.session_state["pending_nav"] = "Paper"
    st.rerun()


def _go_to_story(row) -> None:
    st.session_state["story_source"] = library_source_from_row(row)
    st.session_state["active_story"] = None
    st.session_state["story_card_index"] = 0
    st.session_state["pending_nav"] = "Stories"
    st.rerun()


inject_global_styles()

with st.spinner("Loading the paper library…"):
    df = load_papers()
    vectorizer, svd, nn, vectors = load_models()

render_app_header(len(df))

pending_nav = st.session_state.pop("pending_nav", None)
if pending_nav:
    st.session_state["primary_nav"] = pending_nav
if "primary_nav" not in st.session_state:
    st.session_state["primary_nav"] = "Discover"

navigation = st.radio(
    "Navigation",
    NAV_OPTIONS,
    horizontal=True,
    format_func=lambda value: NAV_LABELS[value],
    label_visibility="collapsed",
    key="primary_nav",
)

venues = sorted(df["venue"].dropna().unique().tolist())
years = sorted(df["year"].dropna().astype(int).unique().tolist(), reverse=True)

st.session_state.setdefault("filter_venues", venues)
st.session_state.setdefault("filter_years", years)
st.session_state.setdefault("result_limit", 250)
st.session_state.setdefault("min_score", 0.0)
st.session_state.setdefault("global_query", "")

if navigation != "Stories":
    query = st.text_input(
        "Search the literature",
        key="global_query",
        placeholder="Search a topic, method, task, author, or phrase — e.g. multimodal survival prediction",
        help="LitRevBuddy ranks papers using the existing TF-IDF + 128-dimensional topic representation.",
    )
else:
    query = st.session_state.get("global_query", "")

with st.sidebar:
    st.markdown("### Library")
    st.caption(f"{len(df):,} papers · {len(venues)} venues · {min(years)}–{max(years)}")

    if navigation != "Stories":
        st.divider()
        st.markdown("### Refine results")

        selected_venues = st.multiselect(
            "Venues",
            venues,
            key="filter_venues",
            help="Leave all selected to search the full library.",
        )

        selected_years = st.multiselect(
            "Years",
            years,
            key="filter_years",
        )

        quick_a, quick_b = st.columns(2)
        if quick_a.button(f"{max(years)} only", use_container_width=True):
            st.session_state["filter_years"] = [max(years)]
            st.rerun()
        if quick_b.button("All years", use_container_width=True):
            st.session_state["filter_years"] = years
            st.rerun()

        result_limit = st.slider(
            "Papers to consider",
            min_value=25,
            max_value=2000,
            value=int(st.session_state.get("result_limit", 250)),
            step=25,
            key="result_limit",
            help="Controls how many ranked papers are shown or used in the current view.",
        )

        with st.expander("Advanced relevance"):
            min_score = st.slider(
                "Minimum relevance score",
                min_value=0.0,
                max_value=1.0,
                value=float(st.session_state.get("min_score", 0.0)),
                step=0.01,
                key="min_score",
                disabled=not bool(query.strip()),
            )
            st.caption("Usually leave this at 0. Increase it only when you want stricter semantic matching.")

        if st.button("Reset search & filters", use_container_width=True):
            st.session_state["global_query"] = ""
            st.session_state["filter_venues"] = venues
            st.session_state["filter_years"] = years
            st.session_state["result_limit"] = 250
            st.session_state["min_score"] = 0.0
            st.rerun()
    else:
        selected_venues = st.session_state.get("filter_venues", venues)
        selected_years = st.session_state.get("filter_years", years)
        result_limit = int(st.session_state.get("result_limit", 250))
        min_score = float(st.session_state.get("min_score", 0.0))
        st.divider()
        st.markdown("### Story workflow")
        st.caption("1. Pick a library paper or load your own PDF.\n\n2. Choose abstract or full-paper mode.\n\n3. Generate and study the verified cards.")

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
    working = working.sort_values(["year", "venue", "title"], ascending=[False, True, True])

results = working.head(result_limit).copy()

if navigation == "Discover":
    render_page_header(
        "Search & browse",
        "Find the papers worth opening",
        "Start broad, then narrow by venue or year. The first results are ranked by topic similarity when you enter a query.",
    )

    metrics = st.columns(4)
    metrics[0].metric("Indexed papers", f"{len(df):,}")
    metrics[1].metric("Matches", f"{len(working):,}")
    metrics[2].metric("Showing", f"{len(results):,}")
    metrics[3].metric("Venues", f"{results['venue'].nunique():,}" if len(results) else "0")

    if not query.strip():
        render_tip("Try a research question rather than a single keyword. For example: 'vision-language models for medical image segmentation'.")

    if len(results) == 0:
        st.info("No papers match this search and filter combination. Broaden the years/venues or lower the relevance threshold.")
    else:
        st.markdown("### Top papers")
        preview_count = min(12, len(results))
        for rank, (_, row) in enumerate(results.head(preview_count).iterrows(), start=1):
            with st.container(border=True):
                left, actions = st.columns([5, 1.35], vertical_alignment="center")
                with left:
                    st.caption(f"#{rank}")
                    render_result_preview(row, show_score=bool(query.strip()))
                with actions:
                    if st.button("Open paper", key=f"open_{int(row['id'])}", use_container_width=True):
                        _go_to_paper(row["id"])
                    if st.button("Explain", key=f"story_{int(row['id'])}", use_container_width=True):
                        _go_to_story(row)
                    links = []
                    if str(row.get("paper_url", "") or "").strip():
                        links.append(f"[Page ↗]({row['paper_url']})")
                    if str(row.get("pdf_url", "") or "").strip():
                        links.append(f"[PDF ↗]({row['pdf_url']})")
                    if links:
                        st.markdown(" · ".join(links))

        if len(results) > preview_count:
            with st.expander(f"Browse all {len(results):,} displayed papers"):
                st.dataframe(
                    make_result_table(results),
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "title": st.column_config.TextColumn("Title", width="large"),
                        "paper_url": st.column_config.LinkColumn("Paper"),
                        "pdf_url": st.column_config.LinkColumn("PDF"),
                        "score": st.column_config.NumberColumn("Relevance", format="%.3f"),
                    },
                )

elif navigation == "Topic map":
    render_page_header(
        "Visual exploration",
        "See how the current papers relate in topic space",
        "Nearby points have similar latent topic representations. Use the search and filters above to focus the map before exploring.",
    )

    if len(results) == 0:
        st.info("No papers are available to plot with the current filters.")
    else:
        plot_df = results.copy()
        if len(plot_df) > 5000:
            plot_df = plot_df.sample(5000, random_state=13)
        st.caption(f"Plotting {len(plot_df):,} papers from the current result set.")

        fig = px.scatter(
            plot_df,
            x="x",
            y="y",
            color="venue",
            hover_name="title",
            hover_data={
                "year": True,
                "cluster_label": True,
                "score": ":.3f",
                "x": False,
                "y": False,
            },
            height=730,
        )
        fig.update_traces(marker=dict(size=6, opacity=0.72))
        fig.update_layout(
            margin=dict(l=0, r=0, t=15, b=0),
            xaxis_title=None,
            yaxis_title=None,
            legend_title_text="Venue",
        )
        st.plotly_chart(fig, use_container_width=True)

        st.info("Tip: hover over a point to see its title and research cluster. Narrow the search first if the map feels crowded.")

elif navigation == "Clusters":
    render_page_header(
        "Theme browser",
        "Move through the literature by research theme",
        "Clusters are automatically derived from the same topic representation used for search. They are navigation aids, not hand-curated taxonomies.",
    )

    if len(results) == 0:
        st.info("No clusters are available with the current filters.")
    else:
        cluster_summary = (
            results.groupby(["cluster_id", "cluster_label"], as_index=False)
            .agg(
                papers=("id", "count"),
                avg_score=("score", "mean"),
                venues=("venue", lambda x: ", ".join(sorted(set(x))[:8])),
                year_min=("year", "min"),
                year_max=("year", "max"),
            )
            .sort_values(["papers", "avg_score"], ascending=[False, False])
        )
        cluster_summary["years"] = (
            cluster_summary["year_min"].astype(int).astype(str)
            + "–"
            + cluster_summary["year_max"].astype(int).astype(str)
        )

        selected_cluster = st.selectbox(
            "Choose a research theme",
            cluster_summary["cluster_id"].tolist(),
            format_func=lambda cluster_id: (
                f"{cluster_summary.loc[cluster_summary['cluster_id'] == cluster_id, 'cluster_label'].iloc[0]}"
                f" · {int(cluster_summary.loc[cluster_summary['cluster_id'] == cluster_id, 'papers'].iloc[0])} papers"
            ),
        )

        cluster_papers = results[results["cluster_id"] == selected_cluster].copy()
        if query.strip():
            cluster_papers = cluster_papers.sort_values("score", ascending=False)
        else:
            cluster_papers = cluster_papers.sort_values(["year", "title"], ascending=[False, True])

        cluster_label = cluster_summary.loc[
            cluster_summary["cluster_id"] == selected_cluster, "cluster_label"
        ].iloc[0]
        st.markdown(f"### {cluster_label}")
        st.caption(f"{len(cluster_papers):,} papers under the current filters")

        preview_count = min(8, len(cluster_papers))
        for _, row in cluster_papers.head(preview_count).iterrows():
            with st.container(border=True):
                left, action = st.columns([5, 1.2], vertical_alignment="center")
                with left:
                    render_result_preview(row, show_score=bool(query.strip()))
                with action:
                    if st.button("Open", key=f"cluster_open_{int(row['id'])}", use_container_width=True):
                        _go_to_paper(row["id"])

        with st.expander("View cluster summary table"):
            st.dataframe(
                cluster_summary[["cluster_label", "papers", "avg_score", "venues", "years"]],
                use_container_width=True,
                hide_index=True,
                column_config={
                    "cluster_label": st.column_config.TextColumn("Theme", width="large"),
                    "avg_score": st.column_config.NumberColumn("Avg relevance", format="%.3f"),
                },
            )

elif navigation == "Paper":
    render_page_header(
        "Deep dive",
        "Read one paper in context",
        "Review the abstract and source links, then jump directly to a source-grounded story or inspect the nearest papers in the index.",
    )

    if len(results) == 0:
        st.info("No papers are available for deep dive with the current search and filters.")
    else:
        option_df = results.head(2000).copy()
        ids = [int(value) for value in option_df["id"].tolist()]
        id_to_title = dict(zip(ids, option_df["title"]))

        preferred = st.session_state.get("selected_paper_id")
        if preferred not in ids:
            preferred = ids[0]
        if st.session_state.get("paper_picker") not in ids:
            st.session_state["paper_picker"] = preferred

        selected_id = st.selectbox(
            "Paper",
            ids,
            format_func=lambda paper_id: id_to_title.get(paper_id, str(paper_id)),
            key="paper_picker",
            help="Start typing a title to search within the current result set.",
        )
        st.session_state["selected_paper_id"] = int(selected_id)

        selected = df[df["id"] == selected_id].iloc[0]
        selected_row_idx = int(selected["row_idx"])
        render_paper_card(selected)

        action_cols = st.columns([1.25, 1.25, 3])
        if action_cols[0].button("✨ Explain as Story", type="primary", use_container_width=True):
            _go_to_story(selected)
        if str(selected.get("pdf_url", "") or "").strip():
            action_cols[1].markdown(f"[Open full PDF ↗]({selected['pdf_url']})")

        st.divider()
        st.markdown("### Related work")
        st.caption("Nearest neighbors in LitRevBuddy's 128-dimensional topic space.")

        similar = get_similar_papers(df, selected_row_idx, nn, vectors, top_k=8)
        if len(similar) == 0:
            st.info("No similar papers were found.")
        else:
            for _, row in similar.iterrows():
                with st.container(border=True):
                    left, action = st.columns([5, 1.2], vertical_alignment="center")
                    with left:
                        st.caption(f"Similarity {float(row['similarity']):.3f}")
                        render_result_preview(row)
                    with action:
                        if st.button("Open", key=f"similar_open_{int(row['id'])}", use_container_width=True):
                            _go_to_paper(row["id"])

elif navigation == "Stories":
    render_story_view(df, vectorizer, svd, nn, vectors)
