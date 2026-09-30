# LitRevBuddy

[![Live Site](https://img.shields.io/badge/Open-LitRevBuddy-ff6b57?style=for-the-badge)](https://learntobuild-as10.github.io/LitRevBuddy/)
[![Tests](https://github.com/learntobuild-AS10/LitRevBuddy/actions/workflows/test.yml/badge.svg)](https://github.com/learntobuild-AS10/LitRevBuddy/actions/workflows/test.yml)
[![Deploy](https://github.com/learntobuild-AS10/LitRevBuddy/actions/workflows/pages.yml/badge.svg)](https://github.com/learntobuild-AS10/LitRevBuddy/actions/workflows/pages.yml)

LitRevBuddy is a static-first research discovery app for finding, understanding, and connecting recent AI papers.

**Website:** https://learntobuild-as10.github.io/LitRevBuddy/

The current catalog contains **67,343 papers** across AAAI, ACL, CVPR, ICCV, ICLR, ICML, MICCAI, NeurIPS, and WACV, covering 2024–2026. The research-data pipeline remains Python-based; the public product is plain HTML/CSS/JavaScript deployed through GitHub Pages.

## Product

- Fast browser-side search across titles, abstracts, authors, venues, and topic neighborhoods
- Year and venue filters
- Daily five-paper research stack
- "Surprise me" discovery
- Centered paper detail modal with abstract, original-paper links, and related work
- Topic browser and interactive 2D research map
- Quick Story: richer source-grounded cards from the abstract
- Deep Story: in-browser PDF parsing for method, data, results, ablations, and limitations
- Optional AI Story using a visitor-supplied OpenRouter key
- Temporary saved-paper and reading-trail state for the current page only
- Responsive desktop, tablet, and mobile layout
- Dark/light mode and keyboard navigation
- Privacy and research-use notices included in the public site

## Architecture

```text
data/papers.db (local source of truth)
        |
        v
Python ingestion + feature build
        |
        v
artifacts/papers_features.parquet
        |
        v
scripts/build_web_catalog.py
        |
        v
web/data/*.json
        |
        v
GitHub Pages
```

The public frontend lives in `web/` and does not require a Python web server.

## Privacy model

LitRevBuddy is intentionally stateless with respect to visitors.

- No LitRevBuddy accounts
- No analytics SDK
- No advertising trackers
- No payment or subscription system
- No cookies
- No localStorage, sessionStorage, or IndexedDB for user activity
- Search state, saves, reading history, uploaded PDFs, extracted PDF text, and API keys stay only in current page memory
- Uploaded PDFs are parsed in the browser and are not persisted by LitRevBuddy
- AI Story is optional and requires explicit confirmation before source text is sent directly to OpenRouter

See `web/privacy.html` and `web/terms.html` for the public notices.

## Local development

Create an environment and install the data-pipeline dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Build the browser catalog:

```bash
python scripts/build_web_catalog.py --input artifacts/papers_features.parquet --output web/data
```

Serve the static site:

```bash
python -m http.server 8000 -d web
```

Then open `http://localhost:8000`.

Deep Story uses PDF.js. The GitHub Pages workflow vendors the pinned PDF.js build into the deployment artifact.

## Updating the paper database

The local SQLite database remains the metadata source of truth and is intentionally not committed.

```bash
python scripts/update_database.py
python scripts/update_database.py --limit 5
python scripts/update_database.py --venues icml
python scripts/update_database.py --venues miccai
```

## Rebuilding research artifacts

After validating the database:

```bash
python scripts/build_features.py
```

Or ingest and rebuild together:

```bash
python scripts/update_database.py --rebuild
```

This regenerates the Parquet metadata, TF-IDF model, 128-dimensional SVD vectors, clusters, nearest-neighbor index, and topic-map coordinates.

## Deployment

`.github/workflows/pages.yml` builds the browser catalog, validates the frontend, vendors PDF.js, enforces privacy invariants, and deploys `web/` to GitHub Pages on pushes to `main`.

The former Streamlit implementation is preserved on the `legacy/streamlit-app` branch for rollback/reference. It is no longer the primary application.

## CI

`.github/workflows/test.yml` checks the Python data pipeline, browser catalog, frontend JavaScript, required public files, catalog counts, and privacy invariants.

## Repository structure

```text
LitRevBuddy/
├── artifacts/                 # committed search/clustering artifacts
├── scripts/                   # ingestion, feature building, web catalog build
├── web/                       # production GitHub Pages frontend
├── .github/workflows/         # CI + deployment
├── CONTRIBUTING.md
├── SECURITY.md
├── requirements.txt
└── README.md
```

## Project status

GitHub Pages is the primary application. The previous Streamlit implementation is retained only on `legacy/streamlit-app` for historical reference and rollback.

Issues and feature requests should be opened through the repository templates. Pull requests should target `main` and must pass CI before merge.

## Citation graphs with Graphify

LitRevBuddy can publish a sanitized Graphify knowledge graph into **Explore → Citation graph**.

Graphify itself runs locally, not on GitHub Pages. The recommended workflow is:

```bash
uv tool install graphifyy
graphify install
```

Then, from Claude Code, run Graphify against a local folder containing the papers you want to map:

```text
/graphify /path/to/paper-corpus
```

Graphify writes `graphify-out/graph.json`, `GRAPH_REPORT.md`, and `graph.html`. Do **not** commit the raw output directly because `source_file` fields can contain local paths.

Publish the sanitized graph with:

```bash
python scripts/publish_graphify.py \
  --input /path/to/graphify-out/graph.json \
  --output web/data/citation-graph/graph.json
```

Commit only the sanitized `web/data/citation-graph/graph.json`. The public frontend automatically detects it.

The citation-map UI can also open a local `graph.json` directly. That file remains in browser memory and is not uploaded or persisted by LitRevBuddy.
