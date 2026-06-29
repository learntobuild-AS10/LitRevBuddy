from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st
from sklearn.preprocessing import normalize

ARTIFACT_DIR = Path("artifacts")

st.set_page_config(
    page_title="AI Paper Explorer",
    layout="wide",
)

@st.cache_data(show_spinner=False)
def load_papers():
    df = pd.read_parquet(ARTIFACT_DIR / "papers_features.parquet")
    return df

@st.cache_resource(show_spinner=False)
def load_models():
    vectorizer = joblib.load(ARTIFACT_DIR / "tfidf_vectorizer.joblib")
    svd = joblib.load(ARTIFACT_DIR / "svd_model.joblib")
    nn = joblib.load(ARTIFACT_DIR / "nearest_neighbors.joblib")
    vectors = np.load(ARTIFACT_DIR / "paper_vectors.npz")["vectors"]
    return vectorizer, svd, nn, vectors

def clean_text(x):
    if x is None:
        return ""
    return " ".join(str(x).split())

def query_scores(query, vectorizer, svd, vectors):
    query = clean_text(query)

    if not query:
        return np.zeros(vectors.shape[0], dtype=np.float32)

    q_tfidf = vectorizer.transform([query])
    q_vec = svd.transform(q_tfidf)
    q_vec = normalize(q_vec).astype("float32")

    scores = vectors @ q_vec.T
    return scores.ravel()

def make_result_table(df):
    cols = [
        "title",
        "venue",
        "year",
        "cluster_label",
        "score",
        "paper_url",
        "pdf_url",
    ]

    existing = [c for c in cols if c in df.columns]
    return df[existing]

def get_similar_papers(all_df, selected_row_idx, nn, vectors, top_k=12):
    distances, indices = nn.kneighbors(
        vectors[selected_row_idx].reshape(1, -1),
        n_neighbors=top_k + 1,
    )

    rows = []

    for dist, idx in zip(distances[0], indices[0]):
        if idx == selected_row_idx:
            continue

        row = all_df.iloc[idx].copy()
        row["similarity"] = 1.0 - float(dist)
        rows.append(row)

    if not rows:
        return pd.DataFrame()

    return pd.DataFrame(rows)

def render_paper_card(row):
    st.markdown(f"### {row['title']}")
    st.caption(f"{row['venue']} {int(row['year'])} · Cluster {int(row['cluster_id'])}: {row['cluster_label']}")

    authors = clean_text(row.get("authors", ""))
    abstract = clean_text(row.get("abstract", ""))

    if authors:
        st.markdown(f"**Authors:** {authors}")

    if abstract:
        st.markdown("**Abstract**")
        st.write(abstract)

    links = []

    paper_url = clean_text(row.get("paper_url", ""))
    pdf_url = clean_text(row.get("pdf_url", ""))
    doi = clean_text(row.get("doi", ""))

    if paper_url:
        links.append(f"[Paper page]({paper_url})")
    if pdf_url:
        links.append(f"[PDF]({pdf_url})")
    if doi:
        links.append(f"DOI: `{doi}`")

    if links:
        st.markdown(" | ".join(links))

st.title("AI Paper Explorer")
st.caption("Interactive search, clustering, topic maps, and similar-paper discovery across major AI conferences.")

with st.spinner("Loading paper index..."):
    df = load_papers()
    vectorizer, svd, nn, vectors = load_models()

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

total_papers = len(df)
filtered_count = len(working)

metric_cols = st.columns(4)
metric_cols[0].metric("Total papers", f"{total_papers:,}")
metric_cols[1].metric("Current result set", f"{len(results):,}")
metric_cols[2].metric("Matching after filters", f"{filtered_count:,}")
metric_cols[3].metric("Clusters shown", f"{results['cluster_id'].nunique():,}" if len(results) else "0")

tab_search, tab_map, tab_clusters, tab_deep_dive = st.tabs(
    ["Search results", "Topic map", "Clusters", "Paper deep dive"]
)

with tab_search:
    st.subheader("Search results")

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

with tab_map:
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

with tab_clusters:
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
            cluster_summary[
                ["cluster_id", "cluster_label", "papers", "avg_score", "venues", "years"]
            ],
            use_container_width=True,
            hide_index=True,
            column_config={
                "avg_score": st.column_config.NumberColumn("Avg score", format="%.3f"),
            },
        )

        selected_cluster = st.selectbox(
            "Open a cluster",
            cluster_summary["cluster_id"].tolist(),
            format_func=lambda c: cluster_summary.loc[
                cluster_summary["cluster_id"] == c, "cluster_label"
            ].iloc[0],
        )

        cluster_papers = results[results["cluster_id"] == selected_cluster].copy()

        if query:
            cluster_papers = cluster_papers.sort_values("score", ascending=False)
        else:
            cluster_papers = cluster_papers.sort_values(["year", "title"], ascending=[False, True])

        st.write(f"{len(cluster_papers):,} papers in this cluster under the current filters")

        st.dataframe(
            cluster_papers[
                ["title", "venue", "year", "score", "paper_url", "pdf_url"]
            ],
            use_container_width=True,
            hide_index=True,
            column_config={
                "paper_url": st.column_config.LinkColumn("Paper page"),
                "pdf_url": st.column_config.LinkColumn("PDF"),
                "score": st.column_config.NumberColumn("Score", format="%.3f"),
            },
        )

with tab_deep_dive:
    st.subheader("Paper deep dive")

    if len(results) == 0:
        st.info("No papers available for deep dive.")
    else:
        option_df = results.copy()

        if len(option_df) > 2000:
            option_df = option_df.head(2000)

        id_to_title = dict(zip(option_df["id"], option_df["title"]))

        selected_id = st.selectbox(
            "Select a paper",
            option_df["id"].tolist(),
            format_func=lambda paper_id: id_to_title.get(paper_id, str(paper_id)),
        )

        selected = df[df["id"] == selected_id].iloc[0]
        selected_row_idx = int(selected["row_idx"])

        render_paper_card(selected)

        st.divider()
        st.subheader("Similar papers")

        similar = get_similar_papers(df, selected_row_idx, nn, vectors, top_k=15)

        if len(similar) == 0:
            st.info("No similar papers found.")
        else:
            st.dataframe(
                similar[
                    ["title", "venue", "year", "cluster_label", "similarity", "paper_url", "pdf_url"]
                ],
                use_container_width=True,
                hide_index=True,
                column_config={
                    "paper_url": st.column_config.LinkColumn("Paper page"),
                    "pdf_url": st.column_config.LinkColumn("PDF"),
                    "similarity": st.column_config.NumberColumn("Similarity", format="%.3f"),
                },
            )
