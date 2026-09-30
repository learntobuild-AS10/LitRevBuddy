from __future__ import annotations

import html

import pandas as pd
import streamlit as st

from components.ui import paper_meta
from services.similarity import clean_text


def _safe_year(value) -> str:
    if value is None or pd.isna(value) or not str(value):
        return ""
    return str(int(value))


def render_paper_card(row) -> None:
    title = clean_text(row.get("title", "Untitled paper"))
    venue = clean_text(row.get("venue", ""))
    year = _safe_year(row.get("year", ""))
    cluster_label = clean_text(row.get("cluster_label", ""))
    authors = clean_text(row.get("authors", ""))
    abstract = clean_text(row.get("abstract", ""))

    st.html(
        f"""
        <div style="
            border:1px solid rgba(127,127,127,.20);
            border-radius:20px;
            padding:1.25rem 1.35rem;
            margin:.25rem 0 1rem;
            background:rgba(127,127,127,.025);
        ">
          <div style="font-size:.82rem;opacity:.64;margin-bottom:.55rem;">
            {html.escape(paper_meta(row))}
          </div>
          <div style="font-size:1.55rem;font-weight:800;line-height:1.18;letter-spacing:-.02em;">
            {html.escape(title)}
          </div>
        </div>
        """
    )

    if authors:
        with st.expander("Authors", expanded=False):
            st.write(authors)

    if abstract:
        st.markdown("#### Abstract")
        st.write(abstract)
    else:
        st.info("An abstract is not available for this record.")

    paper_url = clean_text(row.get("paper_url", ""))
    pdf_url = clean_text(row.get("pdf_url", ""))
    doi = clean_text(row.get("doi", ""))

    link_cols = st.columns(3)
    if paper_url:
        link_cols[0].markdown(f"[Open paper page ↗]({paper_url})")
    else:
        link_cols[0].caption("Paper page unavailable")
    if pdf_url:
        link_cols[1].markdown(f"[Open PDF ↗]({pdf_url})")
    else:
        link_cols[1].caption("PDF unavailable")
    if doi:
        link_cols[2].caption(f"DOI: {doi}")
    else:
        link_cols[2].caption("DOI unavailable")
