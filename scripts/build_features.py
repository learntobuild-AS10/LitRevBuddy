import json
import sqlite3
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from sklearn.cluster import MiniBatchKMeans
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.neighbors import NearestNeighbors
from sklearn.preprocessing import normalize

DB_PATH = "data/papers.db"
OUT_DIR = Path("artifacts")
OUT_DIR.mkdir(exist_ok=True)

N_COMPONENTS = 128
N_CLUSTERS = 120
MAX_FEATURES = 100_000

def clean_text(x):
    if x is None:
        return ""
    return " ".join(str(x).split())

def make_cluster_labels(X_tfidf, df, feature_names, top_n=7):
    labels = {}

    for cluster_id in sorted(df["cluster_id"].unique()):
        idx = df.index[df["cluster_id"] == cluster_id].to_numpy()

        if len(idx) == 0:
            labels[int(cluster_id)] = f"Cluster {cluster_id}"
            continue

        # Use at most 700 papers per cluster to keep this fast.
        if len(idx) > 700:
            rng = np.random.default_rng(13)
            idx = rng.choice(idx, size=700, replace=False)

        mean_scores = np.asarray(X_tfidf[idx].mean(axis=0)).ravel()
        top_idx = mean_scores.argsort()[::-1][:top_n]

        terms = [
            feature_names[i]
            for i in top_idx
            if mean_scores[i] > 0 and len(feature_names[i]) > 2
        ]

        if terms:
            labels[int(cluster_id)] = ", ".join(terms)
        else:
            labels[int(cluster_id)] = f"Cluster {cluster_id}"

    return labels

def main():
    conn = sqlite3.connect(DB_PATH)

    df = pd.read_sql_query("""
        SELECT
            id,
            title,
            authors,
            venue,
            year,
            abstract,
            paper_url,
            pdf_url,
            doi,
            arxiv_id,
            source
        FROM papers
        WHERE title IS NOT NULL
    """, conn)

    conn.close()

    df = df.reset_index(drop=True)
    df["row_idx"] = np.arange(len(df))

    print(f"Loaded {len(df):,} papers")

    for col in ["title", "authors", "abstract", "venue", "source"]:
        df[col] = df[col].map(clean_text)

    df["search_text"] = (
        df["title"].fillna("") + " " +
        df["abstract"].fillna("") + " " +
        df["authors"].fillna("") + " " +
        df["venue"].fillna("") + " " +
        df["year"].astype(str)
    )

    print("Building TF-IDF matrix...")

    vectorizer = TfidfVectorizer(
        stop_words="english",
        max_features=MAX_FEATURES,
        ngram_range=(1, 2),
        min_df=3,
        max_df=0.65,
        sublinear_tf=True,
    )

    X = vectorizer.fit_transform(df["search_text"])
    feature_names = np.array(vectorizer.get_feature_names_out())

    print(f"TF-IDF shape: {X.shape}")

    print("Building 128-dimensional topic vectors...")

    svd = TruncatedSVD(
        n_components=N_COMPONENTS,
        random_state=13,
    )

    Z = svd.fit_transform(X)
    Z = normalize(Z).astype("float32")

    print(f"Vector shape: {Z.shape}")

    print("Building 2D topic map...")

    svd2 = TruncatedSVD(
        n_components=2,
        random_state=13,
    )

    Z2 = svd2.fit_transform(X)
    df["x"] = Z2[:, 0].astype("float32")
    df["y"] = Z2[:, 1].astype("float32")

    print("Clustering papers...")

    kmeans = MiniBatchKMeans(
        n_clusters=N_CLUSTERS,
        random_state=13,
        batch_size=4096,
        n_init="auto",
    )

    df["cluster_id"] = kmeans.fit_predict(Z)

    print("Creating cluster labels...")

    cluster_labels = make_cluster_labels(X, df, feature_names)
    df["cluster_label"] = df["cluster_id"].map(cluster_labels)

    print("Building nearest-neighbor index...")

    nn = NearestNeighbors(
        n_neighbors=40,
        metric="cosine",
        algorithm="brute",
    )

    nn.fit(Z)

    # Drop search_text before saving because it duplicates title/abstract and makes the artifact larger.
    save_df = df.drop(columns=["search_text"])

    print("Saving artifacts...")

    save_df.to_parquet(
        OUT_DIR / "papers_features.parquet",
        index=False,
        compression="zstd",
    )

    np.savez_compressed(
        OUT_DIR / "paper_vectors.npz",
        vectors=Z,
    )

    joblib.dump(vectorizer, OUT_DIR / "tfidf_vectorizer.joblib", compress=3)
    joblib.dump(svd, OUT_DIR / "svd_model.joblib", compress=3)
    joblib.dump(kmeans, OUT_DIR / "kmeans_model.joblib", compress=3)
    joblib.dump(nn, OUT_DIR / "nearest_neighbors.joblib", compress=3)
    joblib.dump(cluster_labels, OUT_DIR / "cluster_labels.joblib", compress=3)

    summary = {
        "num_papers": int(len(df)),
        "num_clusters": int(N_CLUSTERS),
        "num_components": int(N_COMPONENTS),
        "venues": sorted(df["venue"].dropna().unique().tolist()),
        "years": sorted([int(y) for y in df["year"].dropna().unique().tolist()]),
    }

    with open(OUT_DIR / "summary.json", "w") as f:
        json.dump(summary, f, indent=2)

    print("Done.")
    print(f"Saved: {OUT_DIR / 'papers_features.parquet'}")
    print(f"Saved: {OUT_DIR / 'paper_vectors.npz'}")
    print(f"Summary: {summary}")

if __name__ == "__main__":
    main()
