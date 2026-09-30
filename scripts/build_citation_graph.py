from __future__ import annotations

import argparse
import json
import os
import re
import time
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path

import pandas as pd
import requests


S2_BASE = "https://api.semanticscholar.org/graph/v1"
DEFAULT_IDS = [
    7230, 67619, 58609, 42607, 64888, 3131, 11560, 45858, 5146, 79479,
    5317, 3576, 12393, 12419, 44755, 11813, 14380, 38916, 37773, 60537,
    78575, 78838, 5321, 66468, 66017, 47683, 64861, 61988, 6542, 79034,
]


def norm(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def title_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, norm(a), norm(b)).ratio()


def safe_int(value: object, default: int = 0) -> int:
    try:
        if value is None or pd.isna(value):
            return default
    except (TypeError, ValueError):
        pass
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def semantic_scholar_url(paper_id: str) -> str:
    return f"https://www.semanticscholar.org/paper/{paper_id}" if paper_id else ""


class S2Client:
    def __init__(self, api_key: str | None = None, delay: float = 1.1):
        self.session = requests.Session()
        self.delay = delay if not api_key else min(delay, 0.25)
        if api_key:
            self.session.headers["x-api-key"] = api_key

    def _get(self, path: str, params: dict | None = None) -> requests.Response:
        url = f"{S2_BASE}{path}"
        for attempt in range(6):
            response = self.session.get(url, params=params, timeout=40)
            if response.status_code == 429:
                wait = min(60, (2 ** attempt) * 2)
                print(f"Semantic Scholar rate limit; waiting {wait}s")
                time.sleep(wait)
                continue
            response.raise_for_status()
            time.sleep(self.delay)
            return response
        raise RuntimeError(f"Semantic Scholar rate limit persisted for {url}")

    def match_title(self, title: str) -> dict | None:
        for attempt in range(6):
            response = self.session.get(
                f"{S2_BASE}/paper/search/match",
                params={
                    "query": title,
                    "fields": "title,year,url,externalIds,citationCount,referenceCount",
                },
                timeout=40,
            )
            if response.status_code == 404:
                time.sleep(self.delay)
                return None
            if response.status_code == 429:
                wait = min(60, (2 ** attempt) * 2)
                print(f"Semantic Scholar rate limit during title match; waiting {wait}s")
                time.sleep(wait)
                continue
            response.raise_for_status()
            time.sleep(self.delay)
            data = response.json().get("data") or []
            return data[0] if data else None
        raise RuntimeError("Semantic Scholar rate limit persisted during title matching")

    def references(self, paper_id: str) -> list[dict]:
        offset = 0
        out: list[dict] = []
        while True:
            payload = self._get(
                f"/paper/{paper_id}/references",
                {
                    "offset": offset,
                    "limit": 1000,
                    "fields": "title,year,url,externalIds,citationCount",
                },
            ).json()
            out.extend(payload.get("data") or [])
            next_offset = payload.get("next")
            if next_offset is None:
                break
            offset = int(next_offset)
        return out


def dump(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


def select_shared_references(
    references_by_seed: dict[int, list[dict]],
    seed_s2_ids: set[str],
    min_seed_count: int,
    max_external_nodes: int,
) -> list[dict]:
    by_paper: dict[str, dict] = {}
    citing_seeds: dict[str, set[int]] = defaultdict(set)

    for seed_id, refs in references_by_seed.items():
        for ref in refs:
            cited = ref.get("citedPaper") or {}
            paper_id = str(cited.get("paperId") or "")
            if not paper_id or paper_id in seed_s2_ids:
                continue
            title = str(cited.get("title") or "").strip()
            if not title:
                continue
            by_paper[paper_id] = cited
            citing_seeds[paper_id].add(seed_id)

    eligible = [
        {
            "paper_id": paper_id,
            "paper": by_paper[paper_id],
            "seed_count": len(seed_ids),
            "seed_ids": sorted(seed_ids),
        }
        for paper_id, seed_ids in citing_seeds.items()
        if len(seed_ids) >= min_seed_count
    ]
    eligible.sort(
        key=lambda item: (
            -item["seed_count"],
            -safe_int(item["paper"].get("citationCount")),
            norm(item["paper"].get("title")),
        )
    )
    return eligible[:max_external_nodes]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a LitRevBuddy citation network from Semantic Scholar references."
    )
    parser.add_argument("--catalog", default="artifacts/papers_features.parquet")
    parser.add_argument("--ids", default=",".join(map(str, DEFAULT_IDS)))
    parser.add_argument("--output", default="web/data/citation-graph/graph.json")
    parser.add_argument("--min-title-similarity", type=float, default=0.82)
    parser.add_argument("--delay", type=float, default=1.1)
    parser.add_argument(
        "--mode",
        choices=("core", "expanded"),
        default="expanded",
        help="core keeps only citations among selected LitRevBuddy papers; expanded also adds shared external references.",
    )
    parser.add_argument(
        "--min-shared-reference-seeds",
        type=int,
        default=2,
        help="In expanded mode, keep an external reference only when at least this many seed papers cite it.",
    )
    parser.add_argument(
        "--max-external-nodes",
        type=int,
        default=150,
        help="Maximum shared external reference nodes in expanded mode.",
    )
    args = parser.parse_args()

    wanted = [int(v.strip()) for v in args.ids.split(",") if v.strip()]
    df = pd.read_parquet(args.catalog)
    selected = df[df["id"].astype(int).isin(wanted)].copy()
    selected["id"] = selected["id"].astype(int)

    missing = sorted(set(wanted) - set(selected["id"]))
    if missing:
        raise SystemExit(f"LitRevBuddy IDs missing from catalog: {missing}")

    client = S2Client(os.getenv("S2_API_KEY"), delay=args.delay)
    resolved: dict[int, dict] = {}
    rejected: list[dict] = []

    print(f"Resolving {len(selected)} LitRevBuddy papers against Semantic Scholar...")
    for _, row in selected.sort_values("id").iterrows():
        lr_id = int(row["id"])
        candidate = client.match_title(str(row["title"]))
        if not candidate:
            rejected.append({"litrevbuddy_id": lr_id, "reason": "no_match"})
            continue

        similarity = title_similarity(str(row["title"]), str(candidate.get("title") or ""))
        source_year = safe_int(row.get("year"), default=0) or None
        target_year = safe_int(candidate.get("year"), default=0) or None
        year_ok = (
            source_year is None
            or target_year is None
            or abs(source_year - target_year) <= 1
        )
        exact_title_version_mismatch = similarity >= 0.995 and not year_ok

        if similarity < args.min_title_similarity or (not year_ok and not exact_title_version_mismatch):
            rejected.append(
                {
                    "litrevbuddy_id": lr_id,
                    "reason": "low_confidence_match",
                    "similarity": round(similarity, 4),
                    "catalog_title": str(row["title"]),
                    "matched_title": candidate.get("title"),
                    "catalog_year": source_year,
                    "matched_year": target_year,
                }
            )
            continue

        resolved[lr_id] = {
            "paperId": str(candidate["paperId"]),
            "match_similarity": round(similarity, 4),
            "year_mismatch_exact_title": exact_title_version_mismatch,
            "semantic_scholar": candidate,
            "catalog": row.to_dict(),
        }
        mismatch_note = " [exact-title version year mismatch]" if exact_title_version_mismatch else ""
        print(f"  {lr_id}: {similarity:.3f}  {row['title']}{mismatch_note}")

    s2_to_lr = {entry["paperId"]: lr_id for lr_id, entry in resolved.items()}
    seed_s2_ids = set(s2_to_lr)
    nodes = []

    for lr_id, entry in sorted(resolved.items()):
        row = entry["catalog"]
        s2 = entry["semantic_scholar"]
        nodes.append(
            {
                "id": str(lr_id),
                "litrevbuddy_id": lr_id,
                "label": str(row.get("title") or ""),
                "file_type": "paper",
                "node_kind": "seed",
                "venue": str(row.get("venue") or ""),
                "year": safe_int(row.get("year"), default=0) or None,
                "cluster": safe_int(row.get("cluster_id"), default=-1),
                "cluster_label": str(row.get("cluster_label") or ""),
                "paper_url": str(row.get("paper_url") or ""),
                "source_url": str(s2.get("url") or semantic_scholar_url(entry["paperId"])),
                "semantic_scholar_id": entry["paperId"],
                "citation_count": safe_int(s2.get("citationCount")),
                "reference_count": safe_int(s2.get("referenceCount")),
                "match_similarity": entry["match_similarity"],
                "year_mismatch_exact_title": entry["year_mismatch_exact_title"],
            }
        )

    references_by_seed: dict[int, list[dict]] = {}
    print("Fetching Semantic Scholar references...")
    for lr_id, entry in sorted(resolved.items()):
        references_by_seed[lr_id] = client.references(entry["paperId"])

    edges = []
    seen: set[tuple[str, str]] = set()

    def add_edge(source: str, target: str) -> None:
        key = (source, target)
        if source == target or key in seen:
            return
        seen.add(key)
        edges.append(
            {
                "source": source,
                "target": target,
                "relation": "cites",
                "confidence": "BIBLIOGRAPHIC",
                "confidence_score": 1.0,
                "weight": 1.0,
            }
        )

    for lr_id, refs in references_by_seed.items():
        for ref in refs:
            cited = ref.get("citedPaper") or {}
            target_lr = s2_to_lr.get(str(cited.get("paperId") or ""))
            if target_lr is not None:
                add_edge(str(lr_id), str(target_lr))

    direct_edge_count = len(edges)

    external_refs: list[dict] = []
    if args.mode == "expanded":
        external_refs = select_shared_references(
            references_by_seed,
            seed_s2_ids,
            min_seed_count=max(1, args.min_shared_reference_seeds),
            max_external_nodes=max(0, args.max_external_nodes),
        )
        selected_external_ids = {item["paper_id"] for item in external_refs}

        for item in external_refs:
            paper = item["paper"]
            paper_id = item["paper_id"]
            nodes.append(
                {
                    "id": f"s2:{paper_id}",
                    "litrevbuddy_id": None,
                    "label": str(paper.get("title") or paper_id),
                    "file_type": "paper",
                    "node_kind": "external_reference",
                    "venue": "",
                    "year": safe_int(paper.get("year"), default=0) or None,
                    "cluster": None,
                    "cluster_label": "",
                    "paper_url": "",
                    "source_url": str(paper.get("url") or semantic_scholar_url(paper_id)),
                    "semantic_scholar_id": paper_id,
                    "citation_count": safe_int(paper.get("citationCount")),
                    "reference_count": None,
                    "shared_by_seed_count": item["seed_count"],
                }
            )

        for lr_id, refs in references_by_seed.items():
            for ref in refs:
                cited = ref.get("citedPaper") or {}
                paper_id = str(cited.get("paperId") or "")
                if paper_id in selected_external_ids:
                    add_edge(str(lr_id), f"s2:{paper_id}")

    graph = {
        "directed": True,
        "multigraph": False,
        "graph": {
            "generator": "LitRevBuddy + Semantic Scholar",
            "source": "Semantic Scholar Academic Graph API",
            "mode": args.mode,
            "node_count": len(nodes),
            "seed_node_count": len(resolved),
            "external_reference_node_count": len(external_refs),
            "edge_count": len(edges),
            "direct_seed_citation_edge_count": direct_edge_count,
            "requested_papers": len(wanted),
            "resolved_papers": len(resolved),
            "rejected_matches": rejected,
            "min_shared_reference_seeds": args.min_shared_reference_seeds if args.mode == "expanded" else None,
            "max_external_nodes": args.max_external_nodes if args.mode == "expanded" else None,
        },
        "nodes": nodes,
        "edges": edges,
    }
    dump(Path(args.output), graph)

    print(f"Wrote {args.output}")
    print(f"Resolved: {len(resolved)}/{len(wanted)}")
    print(f"Direct seed-to-seed citations: {direct_edge_count}")
    if args.mode == "expanded":
        print(f"Shared external references: {len(external_refs)}")
        print(f"Total citation edges shown: {len(edges)}")
    if rejected:
        print(f"Rejected/unresolved: {len(rejected)}")


if __name__ == "__main__":
    main()
