from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path

import pandas as pd


def text(value) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return " ".join(str(value).split())


def slug(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return value or "unknown"


def compact_paper(row) -> dict:
    abstract = text(row.get("abstract"))
    return {
        "id": int(row["id"]),
        "t": text(row.get("title")),
        "a": text(row.get("authors")),
        "v": text(row.get("venue")),
        "y": int(row["year"]),
        "s": abstract[:520],
        "p": text(row.get("paper_url")),
        "pdf": text(row.get("pdf_url")),
        "c": int(row.get("cluster_id", -1)),
        "cl": text(row.get("cluster_label")),
        "x": round(float(row.get("x", 0.0) or 0.0), 6),
        "z": round(float(row.get("y", 0.0) or 0.0), 6),
    }


def detail_paper(row) -> dict:
    return {
        **compact_paper(row),
        "abstract": text(row.get("abstract")),
        "doi": text(row.get("doi")),
        "arxiv": text(row.get("arxiv_id")),
        "source": text(row.get("source")),
        "row_idx": int(row.get("row_idx", -1)),
    }


def dump(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="artifacts/papers_features.parquet")
    parser.add_argument("--output", default="web/data")
    args = parser.parse_args()

    source = Path(args.input)
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)

    df = pd.read_parquet(source)
    df = df.sort_values(["year", "venue", "title"], ascending=[False, True, True])

    years = sorted([int(v) for v in df["year"].dropna().unique()], reverse=True)
    venues = sorted([text(v) for v in df["venue"].dropna().unique() if text(v)])

    index_files = {}
    for year in years:
        rows = df[df["year"].astype(int) == year]
        payload = [compact_paper(row) for _, row in rows.iterrows()]
        filename = f"index-{year}.json"
        dump(out / filename, payload)
        index_files[str(year)] = filename
        print(f"Wrote {filename}: {len(payload):,} papers")

    detail_files = {}
    for (year, venue), rows in df.groupby(["year", "venue"], dropna=True):
        year = int(year)
        venue = text(venue)
        filename = f"details/{year}/{slug(venue)}.json"
        payload = {str(int(row["id"])): detail_paper(row) for _, row in rows.iterrows()}
        dump(out / filename, payload)
        detail_files[f"{year}:{venue}"] = filename

    cluster_rows = []
    grouped = (
        df.groupby(["cluster_id", "cluster_label"], dropna=False)
        .agg(
            papers=("id", "count"),
            latest_year=("year", "max"),
            venues=("venue", lambda values: sorted(set(text(v) for v in values if text(v)))),
        )
        .reset_index()
        .sort_values("papers", ascending=False)
    )
    for _, row in grouped.iterrows():
        cluster_rows.append(
            {
                "id": int(row["cluster_id"]),
                "label": text(row["cluster_label"]) or f"Cluster {int(row['cluster_id'])}",
                "papers": int(row["papers"]),
                "latest_year": int(row["latest_year"]),
                "venues": list(row["venues"])[:8],
            }
        )
    dump(out / "clusters.json", cluster_rows)

    counts_by_year = {
        str(int(year)): int(count)
        for year, count in df.groupby("year")["id"].count().items()
    }
    counts_by_venue = {
        text(venue): int(count)
        for venue, count in df.groupby("venue")["id"].count().items()
    }

    manifest = {
        "generated_from": source.name,
        "num_papers": int(len(df)),
        "years": years,
        "venues": venues,
        "latest_year": max(years),
        "num_clusters": int(df["cluster_id"].nunique()),
        "counts_by_year": counts_by_year,
        "counts_by_venue": counts_by_venue,
        "index_files": index_files,
        "detail_files": detail_files,
    }
    dump(out / "manifest.json", manifest)
    print(f"Wrote manifest: {len(df):,} papers across {len(years)} years")


if __name__ == "__main__":
    main()
