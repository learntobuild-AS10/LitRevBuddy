# LitRevBuddy

LitRevBuddy is a Streamlit app for discovering recent AI papers and building a fast, technically useful mental model of the work.

The paper index currently contains 59,627 papers across AAAI, ACL, CVPR, ICCV, ICLR, ICML, NeurIPS, and WACV. Coverage varies by venue across 2024–2026. Search and related-paper discovery continue to use the existing TF-IDF → TruncatedSVD → 128-dimensional vector pipeline and nearest-neighbor index.

## Features

- Topic search across paper titles and abstracts
- Venue and year filtering
- Cluster-based browsing
- 2D topic map visualization
- Paper deep dive and nearest-neighbor related papers
- Paper Stories: source-grounded, swipe-style explainers generated from an abstract or parsed full paper
- External paper ingestion from paper URLs, direct PDFs, arXiv/OpenReview links, DOI landing pages where metadata is exposed, and PDF upload
- Compact study area with key concepts and flashcards

## Paper Stories architecture

Paper Stories keeps generation separate from rendering so the same structured content can later drive infographic images or vertical video.

    app.py
    components/
      paper_view.py
      story_view.py
    models/
      story.py
    services/
      similarity.py
      paper_fetcher.py
      paper_parser.py
      llm_provider.py
      story_generator.py
    utils/
      caching.py

The core representation is a typed PaperStory containing StoryCard objects. Each card stores its card type, headline/body/bullets, source section, claim basis, and a short verbatim evidence span. Generation uses structured model output, then LitRevBuddy verifies that the evidence span and any numeric values shown on the card occur in the supplied source context. Cards that fail those checks are discarded.

Stories are labeled as either Abstract-based summary or Full-paper summary. The generator is explicitly allowed to omit unsupported experiment, results, or limitation cards instead of filling gaps.

## PDF ingestion and privacy

- Uploaded PDFs are parsed in memory and are not committed or persisted by the app.
- PDF downloads/uploads are capped at 20 MB.
- Parsed text is bounded before generation.
- Low-text or image-only PDFs fail with an explicit extraction message.
- Network fetching blocks localhost, private, link-local, reserved, and other non-public address ranges, including redirects.
- The same fetched and parsed source is reused during the current Streamlit session.

## LLM configuration

Paper Stories uses a provider abstraction. The initial provider is OpenAI and uses structured outputs through the Responses API.

No key is hardcoded. Configure Streamlit Community Cloud secrets or environment variables:

    OPENAI_API_KEY = "..."
    OPENAI_MODEL = "gpt-6-luna"

OPENAI_MODEL is optional; gpt-6-luna is the default. If OPENAI_API_KEY is absent, search, maps, clusters, paper deep dive, and similarity continue to work. The Stories view shows a configuration message instead of crashing the app.

## Run locally

    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    streamlit run app.py

## Build feature artifacts

After updating the local SQLite database, rebuild the search and clustering artifacts:

    python scripts/build_features.py

The raw database remains local because it exceeds normal GitHub size limits. The deployed app uses the committed precomputed artifacts in artifacts/.

## Tests

Core Story services can be tested without API calls:

    python -m unittest discover -s tests -v
    python -m compileall app.py components models services utils tests

The tests cover URL normalization and PDF resolution, section extraction, provenance and numeric checks, and story cache-key behavior. Full Streamlit integration still depends on the committed paper artifacts and, for live story generation, a configured API key and outbound network access.

## Deployment

The app is designed for Streamlit Community Cloud. Runtime PDFs, generated story caches, and future video exports are ignored by Git and should not be committed.

## Video roadmap

Vertical video is intentionally not part of the Story Cards MVP. The structured PaperStory representation is the boundary for a later renderer:

    PaperStory → card images (Pillow) → optional 1080 × 1920 MP4 renderer

Story quality and provenance should remain the gating requirement before adding video generation.
