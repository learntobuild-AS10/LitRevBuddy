from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path

import pandas as pd


def clean(value: object) -> str:
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
    return value[:80] or "paper"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export LitRevBuddy abstracts + known citations as Markdown for Graphify."
    )
    parser.add_argument("--catalog", default="artifacts/papers_features.parquet")
    parser.add_argument(
        "--citation-graph",
        default="web/data/citation-graph/graph.json",
    )
    parser.add_argument("--output", required=True)
    parser.add_argument("--clean-output", action="store_true")
    args = parser.parse_args()

    graph = json.loads(Path(args.citation_graph).read_text(encoding="utf-8"))
    ids = {int(node["litrevbuddy_id"]) for node in graph.get("nodes", []) if node.get("litrevbuddy_id")}

    df = pd.read_parquet(args.catalog)
    df["id"] = df["id"].astype(int)
    rows = {int(row["id"]): row for _, row in df[df["id"].isin(ids)].iterrows()}

    citations: dict[int, list[int]] = {paper_id: [] for paper_id in ids}
    cited_by: dict[int, list[int]] = {paper_id: [] for paper_id in ids}
    for edge in graph.get("edges", []):
        if edge.get("relation") != "cites":
            continue
        source = int(edge["source"])
        target = int(edge["target"])
        citations.setdefault(source, []).append(target)
        cited_by.setdefault(target, []).append(source)

    out = Path(args.output).expanduser()
    if args.clean_output and out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)

    manifest = []
    for paper_id in sorted(ids):
        row = rows.get(paper_id)
        if row is None:
            continue
        title = clean(row.get("title"))
        filename = f"{paper_id}__{slug(title)}.md"

        refs = [
            f"- [{target}] {clean(rows[target].get('title'))}"
            for target in sorted(set(citations.get(paper_id, [])))
            if target in rows
        ]
        inbound = [
            f"- [{source}] {clean(rows[source].get('title'))}"
            for source in sorted(set(cited_by.get(paper_id, [])))
            if source in rows
        ]

        body = f"""# {title}

LitRevBuddy ID: {paper_id}
Venue: {clean(row.get("venue"))}
Year: {clean(row.get("year"))}
Authors: {clean(row.get("authors"))}
Topic: {clean(row.get("cluster_label"))}

## Abstract

{clean(row.get("abstract"))}

## Citations within this corpus

{chr(10).join(refs) if refs else "- None found within the selected corpus."}

## Cited by within this corpus

{chr(10).join(inbound) if inbound else "- None found within the selected corpus."}
"""
        (out / filename).write_text(body, encoding="utf-8")
        manifest.append(
            {
                "litrevbuddy_id": paper_id,
                "title": title,
                "venue": clean(row.get("venue")),
                "year": int(row["year"]),
                "filename": filename,
            }
        )

    (out / "corpus_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Wrote {len(manifest)} Markdown papers to {out}")


if __name__ == "__main__":
    main()
