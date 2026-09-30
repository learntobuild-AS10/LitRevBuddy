from __future__ import annotations

import argparse
import json
import os
import re
import time
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
            time.sleep(3)
            return self.match_title(title)
        response.raise_for_status()
        time.sleep(self.delay)
        data = response.json().get("data") or []
        return data[0] if data else None

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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a LitRevBuddy citation graph from Semantic Scholar references."
    )
    parser.add_argument("--catalog", default="artifacts/papers_features.parquet")
    parser.add_argument("--ids", default=",".join(map(str, DEFAULT_IDS)))
    parser.add_argument("--output", default="web/data/citation-graph/graph.json")
    parser.add_argument("--min-title-similarity", type=float, default=0.82)
    parser.add_argument("--delay", type=float, default=1.1)
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
        source_year = int(row["year"]) if pd.notna(row["year"]) else None
        target_year = candidate.get("year")
        year_ok = (
            source_year is None
            or target_year is None
            or abs(source_year - int(target_year)) <= 1
        )
        if similarity < args.min_title_similarity or not year_ok:
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
            "semantic_scholar": candidate,
            "catalog": row.to_dict(),
        }
        print(f"  {lr_id}: {similarity:.3f}  {row['title']}")

    s2_to_lr = {entry["paperId"]: lr_id for lr_id, entry in resolved.items()}
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
                "venue": str(row.get("venue") or ""),
                "year": int(row["year"]) if pd.notna(row.get("year")) else None,
                "cluster": int(row["cluster_id"]) if pd.notna(row.get("cluster_id")) else None,
                "cluster_label": str(row.get("cluster_label") or ""),
                "paper_url": str(row.get("paper_url") or ""),
                "semantic_scholar_id": entry["paperId"],
                "semantic_scholar_url": str(s2.get("url") or ""),
                "citation_count": int(s2.get("citationCount") or 0),
                "reference_count": int(s2.get("referenceCount") or 0),
                "match_similarity": entry["match_similarity"],
            }
        )

    edges = []
    seen = set()
    print("Fetching references and keeping edges inside the selected LitRevBuddy corpus...")
    for lr_id, entry in sorted(resolved.items()):
        refs = client.references(entry["paperId"])
        for ref in refs:
            cited = ref.get("citedPaper") or {}
            target_lr = s2_to_lr.get(str(cited.get("paperId") or ""))
            if target_lr is None or target_lr == lr_id:
                continue
            key = (lr_id, target_lr)
            if key in seen:
                continue
            seen.add(key)
            edges.append(
                {
                    "source": str(lr_id),
                    "target": str(target_lr),
                    "relation": "cites",
                    "confidence": "BIBLIOGRAPHIC",
                    "confidence_score": 1.0,
                    "weight": 1.0,
                }
            )

    graph = {
        "directed": True,
        "multigraph": False,
        "graph": {
            "generator": "LitRevBuddy + Semantic Scholar",
            "source": "Semantic Scholar Academic Graph API",
            "node_count": len(nodes),
            "edge_count": len(edges),
            "requested_papers": len(wanted),
            "resolved_papers": len(resolved),
            "rejected_matches": rejected,
        },
        "nodes": nodes,
        "edges": edges,
    }
    dump(Path(args.output), graph)

    print(f"Wrote {args.output}")
    print(f"Resolved: {len(resolved)}/{len(wanted)}")
    print(f"Internal citation edges: {len(edges)}")
    if rejected:
        print(f"Rejected/unresolved: {len(rejected)}")


if __name__ == "__main__":
    main()
