from __future__ import annotations

import streamlit as st

from services.similarity import clean_text


def render_paper_card(row) -> None:
    st.markdown(f"### {row['title']}")

    venue = clean_text(row.get("venue", ""))
    year = row.get("year", "")
    cluster_id = row.get("cluster_id", "")
    cluster_label = clean_text(row.get("cluster_label", ""))

    caption_bits = []
    if venue or year:
        caption_bits.append(f"{venue} {int(year) if year == year and str(year) else ''}".strip())
    if str(cluster_id) and cluster_label:
        caption_bits.append(f"Cluster {int(cluster_id)}: {cluster_label}")
    if caption_bits:
        st.caption(" · ".join(caption_bits))

    authors = clean_text(row.get("authors", ""))
    abstract = clean_text(row.get("abstract", ""))

    if authors:
        st.markdown(f"**Authors:** {authors}")
    if abstract:
        st.markdown("**Abstract**")
        st.write(abstract)

    links = []
    paper_url = clean_text(row.get("paper_url", ""))
    pdf_url = clean_text(row.get("pdf_url", ""))
    doi = clean_text(row.get("doi", ""))

    if paper_url:
        links.append(f"[Paper page]({paper_url})")
    if pdf_url:
        links.append(f"[PDF]({pdf_url})")
    if doi:
        links.append(f"DOI: {doi}")
    if links:
        st.markdown(" | ".join(links))
