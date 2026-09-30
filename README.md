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

## Research graphs

LitRevBuddy separates bibliographic and semantic relationships instead of treating them as the same graph.

### Citation map

The citation map is built from explicit paper references returned by the Semantic Scholar Academic Graph API. For the initial 30-paper multimodal-medical-AI pilot:

```bash
python scripts/build_citation_graph.py
```

The script:

- resolves each selected LitRevBuddy paper against Semantic Scholar using closest-title matching
- rejects low-confidence title/year matches
- fetches references for each resolved paper
- keeps citation edges whose source and target are both in the selected LitRevBuddy corpus
- writes `web/data/citation-graph/graph.json`

Set `S2_API_KEY` if you have a Semantic Scholar API key. The script can run without one, but intentionally uses a slower request cadence and retries rate limits.

### Knowledge map with Graphify

Graphify is reserved for the semantic layer: concepts, methods, datasets, tasks, and other relationships that are not ordinary bibliographic citation edges.

No PDFs are required for the default workflow. Export the selected LitRevBuddy records as Markdown containing title, authors, venue/year, abstract, topic, and verified citations:

```bash
python scripts/export_graphify_corpus.py \
  --citation-graph web/data/citation-graph/graph.json \
  --output "$HOME/Documents/LitRevBuddy-Graphify-Corpus" \
  --clean-output
```

Then run Graphify locally through Claude Code on that external folder:

```text
/graphify ~/Documents/LitRevBuddy-Graphify-Corpus
```

The corpus remains outside Git. Raw Graphify output should not be committed. Once the first real output has been validated, it can be sanitized and published as the separate **Explore → Knowledge map** dataset.

This produces three distinct research-navigation views:

- **Topics**: cluster-level themes learned by LitRevBuddy
- **Topic map**: semantic similarity between papers
- **Citation map**: explicit bibliographic dependencies
- **Knowledge map**: Graphify semantic relationships
