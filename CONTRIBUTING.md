# Contributing

Thanks for contributing to LitRevBuddy.

## Development workflow

1. Create a branch from `main`.
2. Keep changes focused and small enough to review.
3. Run the relevant checks locally.
4. Open a pull request against `main`.
5. Wait for CI to pass before merging.

## Local checks

```bash
python -m compileall -q scripts
python scripts/build_web_catalog.py --input artifacts/papers_features.parquet --output web/data
node --check web/app.js
```

Serve the frontend locally with:

```bash
python -m http.server 8000 -d web
```

Then open `http://localhost:8000`.

## Product constraints

Changes to the public frontend should preserve these guarantees unless explicitly discussed first:

- no user accounts
- no analytics or advertising trackers
- no subscriptions or payment SDKs
- no cookies or persistent browser storage for visitor activity
- no hidden persistence of uploaded PDFs, extracted text, search terms, saves, reading history, or API keys
- AI Story remains explicit opt-in and must disclose when source text is sent to a third party

## Data changes

The raw SQLite database is local and is not committed. After ingestion changes, rebuild and validate the feature artifacts before updating the browser catalog.

## Pull requests

Explain:

- what changed
- why it changed
- how it was tested
- any privacy, data, or deployment impact
