# AI Paper Explorer

AI Paper Explorer is an interactive Streamlit app for exploring recent papers from major AI conferences.

## Features

- Topic search across paper titles and abstracts
- Venue and year filtering
- Cluster-based browsing
- 2D topic map visualization
- Similar-paper discovery

## Current Database Coverage

The current database contains 59,627 papers from:

- AAAI 2024 to 2026
- ACL 2024 to 2026
- CVPR 2024 to 2026
- ICCV 2025
- ICLR 2024 to 2026
- ICML 2024 to 2025
- NeurIPS 2024 to 2025
- WACV 2024 to 2026

## Example Searches

- lightweight vision language models
- medical image segmentation
- mamba vision
- multimodal fusion
- retrieval augmented generation
- survival prediction
- diffusion restoration
- test time adaptation

## Run Locally

Create and activate a virtual environment:

    python3 -m venv .venv
    source .venv/bin/activate

Install dependencies:

    pip install -r requirements.txt

Run the app:

    streamlit run app.py

## Build Feature Artifacts

After updating the database, rebuild the search and clustering artifacts:

    python scripts/build_features.py

## Project Structure

    paper-database/
      app.py
      requirements.txt
      README.md
      data/
        papers.db
      artifacts/
        papers_features.parquet
        paper_vectors.npz
        tfidf_vectorizer.joblib
        svd_model.joblib
        kmeans_model.joblib
        cluster_labels.joblib
        summary.json
      scripts/
        ingest_cvf.py
        ingest_acl.py
        ingest_aaai.py
        ingest_icml_pmlr.py
        ingest_neurips.py
        build_features.py

## Deployment

This app is designed to run on Streamlit Community Cloud. GitHub Pages only supports static sites, so the Streamlit app itself should be deployed through Streamlit Community Cloud using this repository.

## Notes

The database and derived artifacts are built from public conference and proceedings metadata. The app is intended for literature exploration, topic discovery, and research planning.
