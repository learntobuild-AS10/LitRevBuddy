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
        description="Export LitRevBuddy seed abstracts + verified citation context as Markdown for Graphify."
    )
    parser.add_argument("--catalog", default="artifacts/papers_features.parquet")
    parser.add_argument(
        "--citation-graph",
        default="web/data/citation-graph/graph.json",
    )
    parser.add_argument("--output", required=True)
    parser.add_argument("--clean-output", action="store_true")
    parser.add_argument(
        "--knowledge-only",
        action="store_true",
        help="Export only paper metadata and the full catalog abstract; omit all citation/reference sections.",
    )
    args = parser.parse_args()

    graph = json.loads(Path(args.citation_graph).read_text(encoding="utf-8"))
    graph_nodes = {str(node["id"]): node for node in graph.get("nodes", [])}

    seed_nodes = [
        node
        for node in graph.get("nodes", [])
        if node.get("litrevbuddy_id") is not None
    ]
    seed_ids = {int(node["litrevbuddy_id"]) for node in seed_nodes}
    graph_id_to_lr = {
        str(node["id"]): int(node["litrevbuddy_id"])
        for node in seed_nodes
    }

    df = pd.read_parquet(args.catalog)
    df["id"] = df["id"].astype(int)
    rows = {
        int(row["id"]): row
        for _, row in df[df["id"].isin(seed_ids)].iterrows()
    }

    seed_citations: dict[int, list[int]] = {paper_id: [] for paper_id in seed_ids}
    seed_cited_by: dict[int, list[int]] = {paper_id: [] for paper_id in seed_ids}
    shared_references: dict[int, list[dict]] = {paper_id: [] for paper_id in seed_ids}

    for edge in graph.get("edges", []):
        if edge.get("relation") != "cites":
            continue

        source_graph_id = str(edge.get("source"))
        target_graph_id = str(edge.get("target"))
        source_lr = graph_id_to_lr.get(source_graph_id)
        if source_lr is None:
            continue

        target_lr = graph_id_to_lr.get(target_graph_id)
        if target_lr is not None:
            seed_citations.setdefault(source_lr, []).append(target_lr)
            seed_cited_by.setdefault(target_lr, []).append(source_lr)
            continue

        target_node = graph_nodes.get(target_graph_id)
        if target_node:
            shared_references.setdefault(source_lr, []).append(target_node)

    out = Path(args.output).expanduser()
    if args.clean_output and out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)

    manifest = []
    for paper_id in sorted(seed_ids):
        row = rows.get(paper_id)
        if row is None:
            continue

        title = clean(row.get("title"))
        filename = f"{paper_id}__{slug(title)}.md"

        direct_refs = [
            f"- [{target}] {clean(rows[target].get('title'))}"
            for target in sorted(set(seed_citations.get(paper_id, [])))
            if target in rows
        ]
        inbound = [
            f"- [{source}] {clean(rows[source].get('title'))}"
            for source in sorted(set(seed_cited_by.get(paper_id, [])))
            if source in rows
        ]

        external_seen = set()
        external_refs = []
        for node in sorted(
            shared_references.get(paper_id, []),
            key=lambda item: (
                -int(item.get("shared_by_seed_count") or 0),
                clean(item.get("label")),
            ),
        ):
            graph_id = str(node.get("id"))
            if not graph_id or graph_id in external_seen:
                continue
            external_seen.add(graph_id)
            label = clean(node.get("label")) or graph_id
            year = node.get("year")
            shared_count = node.get("shared_by_seed_count")
            suffix = []
            if year:
                suffix.append(str(year))
            if shared_count:
                suffix.append(f"cited by {shared_count} seed papers")
            external_refs.append(
                f"- {label}" + (f" ({'; '.join(suffix)})" if suffix else "")
            )

        abstract = clean(row.get("abstract"))
        if args.knowledge_only:
            body = f"""# {title}

LitRevBuddy ID: {paper_id}
Venue: {clean(row.get("venue"))}
Year: {clean(row.get("year"))}
Authors: {clean(row.get("authors"))}
Topic: {clean(row.get("cluster_label"))}

## Abstract

{abstract}
"""
        else:
            body = f"""# {title}

LitRevBuddy ID: {paper_id}
Venue: {clean(row.get("venue"))}
Year: {clean(row.get("year"))}
Authors: {clean(row.get("authors"))}
Topic: {clean(row.get("cluster_label"))}

## Abstract

{abstract}

## Direct citations to other LitRevBuddy seed papers

{chr(10).join(direct_refs) if direct_refs else "- None found within the selected seed corpus."}

## Cited by other LitRevBuddy seed papers

{chr(10).join(inbound) if inbound else "- None found within the selected seed corpus."}

## Shared references in the citation neighborhood

{chr(10).join(external_refs) if external_refs else "- No shared external references passed the citation-neighborhood threshold."}
"""
        (out / filename).write_text(body, encoding="utf-8")
        manifest.append(
            {
                "litrevbuddy_id": paper_id,
                "title": title,
                "venue": clean(row.get("venue")),
                "year": int(row["year"]),
                "filename": filename,
                "direct_seed_citations": len(set(seed_citations.get(paper_id, []))),
                "shared_external_references": len(external_seen),
                "knowledge_only": bool(args.knowledge_only),
                "abstract_chars": len(abstract),
            }
        )

    (out / "corpus_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Wrote {len(manifest)} seed-paper Markdown files to {out}")
    if args.knowledge_only:
        print(
            "Knowledge-only export: paper metadata + full catalog abstract only; "
            "citation/reference sections were omitted."
        )
    else:
        print(
            "Citation context includes direct seed citations plus shared external references; "
            "no PDF text is required."
        )


if __name__ == "__main__":
    main()
