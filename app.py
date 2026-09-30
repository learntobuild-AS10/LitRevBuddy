from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st

from components.paper_view import render_paper_card
from components.story_view import library_source_from_row, render_story_view
from services.similarity import get_similar_papers, make_result_table, query_scores


ARTIFACT_DIR = Path("artifacts")

st.set_page_config(
    page_title="LitRevBuddy",
    page_icon="📚",
    layout="wide",
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


st.title("LitRevBuddy")
st.caption("Discover AI papers, map research topics, find related work, and turn papers into source-grounded visual stories.")

with st.spinner("Loading paper index..."):
    df = load_papers()
    vectorizer, svd, nn, vectors = load_models()

pending_nav = st.session_state.pop("pending_nav", None)
if pending_nav:
    st.session_state["primary_nav"] = pending_nav
if "primary_nav" not in st.session_state:
    st.session_state["primary_nav"] = "Discover"

navigation = st.radio(
    "Navigation",
    ["Discover", "Topic map", "Clusters", "Paper", "Stories"],
    horizontal=True,
    label_visibility="collapsed",
    key="primary_nav",
)

with st.sidebar:
    st.header("Search controls")

    query = st.text_input(
        "Topic search",
        placeholder="Example: lightweight vision language models",
    )

    venues = sorted(df["venue"].dropna().unique().tolist())
    selected_venues = st.multiselect(
        "Venue",
        venues,
        default=venues,
    )

    years = sorted(df["year"].dropna().astype(int).unique().tolist(), reverse=True)
    selected_years = st.multiselect(
        "Year",
        years,
        default=years,
    )

    top_k = st.slider(
        "Max papers to show",
        min_value=100,
        max_value=5000,
        value=1000,
        step=100,
    )

    min_score = st.slider(
        "Minimum relevance score",
        min_value=0.0,
        max_value=1.0,
        value=0.0,
        step=0.01,
    )

scores = query_scores(query, vectorizer, svd, vectors)
working = df.copy()
working["score"] = scores

mask = (
    working["venue"].isin(selected_venues)
    & working["year"].astype(int).isin(selected_years)
)
working = working[mask].copy()

if query:
    working = working[working["score"] >= min_score]
    working = working.sort_values("score", ascending=False)
else:
    working = working.sort_values(["year", "venue", "title"], ascending=[False, True, True])

results = working.head(top_k).copy()

if navigation != "Stories":
    metric_cols = st.columns(4)
    metric_cols[0].metric("Total papers", f"{len(df):,}")
    metric_cols[1].metric("Current result set", f"{len(results):,}")
    metric_cols[2].metric("Matching after filters", f"{len(working):,}")
    metric_cols[3].metric("Clusters shown", f"{results['cluster_id'].nunique():,}" if len(results) else "0")

if navigation == "Discover":
    st.subheader("Discover")
    if len(results) == 0:
        st.info("No papers matched the current filters.")
    else:
        st.dataframe(
            make_result_table(results),
            use_container_width=True,
            hide_index=True,
            column_config={
                "paper_url": st.column_config.LinkColumn("Paper page"),
                "pdf_url": st.column_config.LinkColumn("PDF"),
                "score": st.column_config.NumberColumn("Score", format="%.3f"),
            },
        )

elif navigation == "Topic map":
    st.subheader("2D topic map")
    if len(results) == 0:
        st.info("No papers to plot.")
    else:
        plot_df = results.copy()
        if len(plot_df) > 5000:
            plot_df = plot_df.sample(5000, random_state=13)

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
            height=750,
        )
        fig.update_traces(marker=dict(size=5, opacity=0.75))
        fig.update_layout(
            margin=dict(l=0, r=0, t=20, b=0),
            xaxis_title=None,
            yaxis_title=None,
        )
        st.plotly_chart(fig, use_container_width=True)

elif navigation == "Clusters":
    st.subheader("Cluster browser")
    if len(results) == 0:
        st.info("No clusters to show.")
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
            + " to "
            + cluster_summary["year_max"].astype(int).astype(str)
        )

        st.dataframe(
            cluster_summary[["cluster_id", "cluster_label", "papers", "avg_score", "venues", "years"]],
            use_container_width=True,
            hide_index=True,
            column_config={
                "avg_score": st.column_config.NumberColumn("Avg score", format="%.3f"),
            },
        )

        selected_cluster = st.selectbox(
            "Open a cluster",
            cluster_summary["cluster_id"].tolist(),
            format_func=lambda cluster_id: cluster_summary.loc[
                cluster_summary["cluster_id"] == cluster_id, "cluster_label"
            ].iloc[0],
        )

        cluster_papers = results[results["cluster_id"] == selected_cluster].copy()
        if query:
            cluster_papers = cluster_papers.sort_values("score", ascending=False)
        else:
            cluster_papers = cluster_papers.sort_values(["year", "title"], ascending=[False, True])

        st.write(f"{len(cluster_papers):,} papers in this cluster under the current filters")
        st.dataframe(
            cluster_papers[["title", "venue", "year", "score", "paper_url", "pdf_url"]],
            use_container_width=True,
            hide_index=True,
            column_config={
                "paper_url": st.column_config.LinkColumn("Paper page"),
                "pdf_url": st.column_config.LinkColumn("PDF"),
                "score": st.column_config.NumberColumn("Score", format="%.3f"),
            },
        )

elif navigation == "Paper":
    st.subheader("Paper deep dive")
    if len(results) == 0:
        st.info("No papers available for deep dive.")
    else:
        option_df = results.head(2000).copy()
        id_to_title = dict(zip(option_df["id"], option_df["title"]))

        selected_id = st.selectbox(
            "Select a paper",
            option_df["id"].tolist(),
            format_func=lambda paper_id: id_to_title.get(paper_id, str(paper_id)),
        )

        selected = df[df["id"] == selected_id].iloc[0]
        selected_row_idx = int(selected["row_idx"])
        render_paper_card(selected)

        action_col, _ = st.columns([1, 2])
        if action_col.button("Explain as Story", type="primary", use_container_width=True):
            st.session_state["story_source"] = library_source_from_row(selected)
            st.session_state["active_story"] = None
            st.session_state["story_card_index"] = 0
            st.session_state["pending_nav"] = "Stories"
            st.rerun()

        st.divider()
        st.subheader("Similar papers")
        similar = get_similar_papers(df, selected_row_idx, nn, vectors, top_k=15)
        if len(similar) == 0:
            st.info("No similar papers found.")
        else:
            st.dataframe(
                similar[["title", "venue", "year", "cluster_label", "similarity", "paper_url", "pdf_url"]],
                use_container_width=True,
                hide_index=True,
                column_config={
                    "paper_url": st.column_config.LinkColumn("Paper page"),
                    "pdf_url": st.column_config.LinkColumn("PDF"),
                    "similarity": st.column_config.NumberColumn("Similarity", format="%.3f"),
                },
            )

elif navigation == "Stories":
    render_story_view(df, vectorizer, svd, nn, vectors)
