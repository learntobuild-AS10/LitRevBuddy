from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from urllib.parse import urlparse


MAX_NODES = 5000
MAX_EDGES = 30000


def _safe_source_file(value: object) -> str:
    if not value:
        return ""
    text = str(value).replace("\\", "/")
    return Path(text).name


def _litrevbuddy_id_from_source(value: object) -> int | None:
    name = _safe_source_file(value)
    match = re.match(r"^(\\d+)__", name)
    return int(match.group(1)) if match else None


def _safe_url(value: object) -> str:
    if not value:
        return ""
    text = str(value).strip()
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"}:
        return ""
    return text


def _node_id(value: object) -> str:
    if isinstance(value, dict):
        value = value.get("id", "")
    return str(value)


def sanitize_graph(raw: dict) -> dict:
    nodes = raw.get("nodes") or []
    edges = raw.get("edges") or raw.get("links") or []

    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise ValueError("Graphify graph must contain list-valued nodes and edges/links.")

    clean_nodes = []
    allowed_ids = set()
    for node in nodes[:MAX_NODES]:
        if not isinstance(node, dict) or not node.get("id"):
            continue
        node_id = str(node["id"])
        allowed_ids.add(node_id)
        community = node.get("community", 0)
        try:
            community = int(community)
        except (TypeError, ValueError):
            community = 0

        clean_nodes.append(
            {
                "id": node_id,
                "label": str(node.get("label") or node_id),
                "file_type": str(node.get("file_type") or node.get("type") or "concept"),
                "source_file": _safe_source_file(node.get("source_file")),
                "litrevbuddy_id": _litrevbuddy_id_from_source(node.get("source_file")),
                "source_location": str(node.get("source_location") or ""),
                "source_url": _safe_url(node.get("source_url")),
                "community": community,
            }
        )

    clean_edges = []
    for edge in edges:
        if len(clean_edges) >= MAX_EDGES:
            break
        if not isinstance(edge, dict):
            continue
        source = _node_id(edge.get("source"))
        target = _node_id(edge.get("target"))
        if source not in allowed_ids or target not in allowed_ids:
            continue
        try:
            score = float(edge.get("confidence_score", edge.get("weight", 0)) or 0)
        except (TypeError, ValueError):
            score = 0.0
        try:
            weight = float(edge.get("weight", 1) or 1)
        except (TypeError, ValueError):
            weight = 1.0

        clean_edges.append(
            {
                "source": source,
                "target": target,
                "relation": str(edge.get("relation") or "related_to"),
                "confidence": str(edge.get("confidence") or ""),
                "confidence_score": score,
                "weight": weight,
                "source_file": _safe_source_file(edge.get("source_file")),
            }
        )

    relation_counts: dict[str, int] = {}
    confidence_counts: dict[str, int] = {}
    for edge in clean_edges:
        relation_counts[edge["relation"]] = relation_counts.get(edge["relation"], 0) + 1
        confidence = edge["confidence"] or "UNLABELLED"
        confidence_counts[confidence] = confidence_counts.get(confidence, 0) + 1

    return {
        "directed": bool(raw.get("directed", False)),
        "multigraph": bool(raw.get("multigraph", False)),
        "graph": {
            "generator": "Graphify",
            "published_for": "LitRevBuddy",
            "node_count": len(clean_nodes),
            "edge_count": len(clean_edges),
            "relation_counts": dict(sorted(relation_counts.items())),
            "confidence_counts": dict(sorted(confidence_counts.items())),
        },
        "nodes": clean_nodes,
        "edges": clean_edges,
    }


def validate_no_local_paths(payload: dict) -> None:
    encoded = json.dumps(payload, ensure_ascii=False)
    forbidden = [
        str(Path.home()),
        "/Users/",
        "/home/",
        "\\Users\\",
    ]
    for marker in forbidden:
        if marker and marker in encoded:
            raise ValueError(f"Refusing to publish local path marker: {marker}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sanitize a Graphify graph.json for public LitRevBuddy citation-map use."
    )
    parser.add_argument("--input", required=True, help="Path to Graphify graph.json")
    parser.add_argument(
        "--output",
        default="web/data/citation-graph/graph.json",
        help="Public sanitized graph output path",
    )
    args = parser.parse_args()

    input_path = Path(args.input).expanduser().resolve()
    output_path = Path(args.output)

    raw = json.loads(input_path.read_text(encoding="utf-8"))
    clean = sanitize_graph(raw)
    validate_no_local_paths(clean)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(clean, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )

    citation_edges = sum(
        1
        for edge in clean["edges"]
        if any(token in edge["relation"].lower() for token in ("cite", "citation", "reference"))
    )
    print(
        f"Published {len(clean['nodes']):,} nodes, {len(clean['edges']):,} edges "
        f"({citation_edges:,} citation/reference edges) to {output_path}"
    )


if __name__ == "__main__":
    main()
