from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.preprocessing import normalize


def clean_text(value) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return " ".join(str(value).split())


def query_scores(query, vectorizer, svd, vectors):
    query = clean_text(query)
    if not query:
        return np.zeros(vectors.shape[0], dtype=np.float32)

    q_tfidf = vectorizer.transform([query])
    q_vec = svd.transform(q_tfidf)
    q_vec = normalize(q_vec).astype("float32")
    return (vectors @ q_vec.T).ravel()


def make_result_table(df: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "title",
        "venue",
        "year",
        "cluster_label",
        "score",
        "paper_url",
        "pdf_url",
    ]
    return df[[column for column in columns if column in df.columns]]


def get_similar_papers(all_df, selected_row_idx, nn, vectors, top_k=12):
    distances, indices = nn.kneighbors(
        vectors[selected_row_idx].reshape(1, -1),
        n_neighbors=top_k + 1,
    )

    rows = []
    for distance, idx in zip(distances[0], indices[0]):
        if idx == selected_row_idx:
            continue
        row = all_df.iloc[idx].copy()
        row["similarity"] = 1.0 - float(distance)
        rows.append(row)

    return pd.DataFrame(rows) if rows else pd.DataFrame()


def get_related_by_text(all_df, query, vectorizer, svd, vectors, top_k=5):
    scores = query_scores(query, vectorizer, svd, vectors)
    if not len(scores):
        return pd.DataFrame()

    top_indices = np.argsort(scores)[::-1][:top_k]
    related = all_df.iloc[top_indices].copy()
    related["similarity"] = scores[top_indices]
    return related
