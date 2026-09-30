import argparse
import re
import sqlite3
import time
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from tqdm import tqdm

DB_PATH = "data/papers.db"
SUPPORTED_YEARS = {2026}
INDEX_URLS = {
    2026: "https://papers.miccai.org/miccai-2026/",
}
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; LitRevBuddy/1.0; research-paper-indexer)"
}


def clean_text(value):
    if not value:
        return None
    return " ".join(str(value).split())


def paper_exists(conn, *, title, year):
    row = conn.execute(
        "SELECT 1 FROM papers WHERE title = ? AND venue = 'MICCAI' AND year = ? LIMIT 1",
        (title, year),
    ).fetchone()
    return row is not None


def upsert_paper(conn, paper):
    existed = paper_exists(conn, title=paper["title"], year=paper["year"])
    conn.execute(
        """
        INSERT INTO papers
        (title, authors, venue, year, abstract, paper_url, pdf_url, doi, source, source_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(title, venue, year) DO UPDATE SET
            authors = COALESCE(NULLIF(excluded.authors, ''), papers.authors),
            abstract = COALESCE(NULLIF(excluded.abstract, ''), papers.abstract),
            paper_url = COALESCE(NULLIF(excluded.paper_url, ''), papers.paper_url),
            pdf_url = COALESCE(NULLIF(excluded.pdf_url, ''), papers.pdf_url),
            doi = COALESCE(NULLIF(excluded.doi, ''), papers.doi),
            source = COALESCE(NULLIF(excluded.source, ''), papers.source),
            source_id = COALESCE(NULLIF(excluded.source_id, ''), papers.source_id)
        """,
        (
            paper["title"],
            paper["authors"],
            paper["venue"],
            paper["year"],
            paper["abstract"],
            paper["paper_url"],
            paper["pdf_url"],
            paper["doi"],
            paper["source"],
            paper["source_id"],
        ),
    )
    return not existed


def get_paper_links(session, year):
    index_url = INDEX_URLS[year]
    print(f"\nFetching MICCAI {year} paper index: {index_url}")
    response = session.get(index_url, headers=HEADERS, timeout=45)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "lxml")
    pattern = re.compile(r"(?:^|/)\d+-Paper\d+\.html$", re.I)

    links = []
    seen = set()
    for anchor in soup.find_all("a", href=True):
        href = anchor.get("href", "")
        if not pattern.search(href):
            continue
        paper_url = urljoin(index_url, href)
        if paper_url not in seen:
            seen.add(paper_url)
            links.append(paper_url)

    print(f"Found {len(links)} MICCAI {year} paper pages")
    return links


def _section_text(soup, heading_text):
    heading = None
    for tag in soup.find_all(["h1", "h2", "h3", "h4"]):
        if clean_text(tag.get_text(" ", strip=True)) == heading_text:
            heading = tag
            break
    if heading is None:
        return None

    chunks = []
    for sibling in heading.find_next_siblings():
        if sibling.name in {"h1", "h2", "h3", "h4"}:
            break
        text = clean_text(sibling.get_text(" ", strip=True))
        if text:
            chunks.append(text)
    return clean_text(" ".join(chunks))


def extract_authors(soup):
    heading = None
    for tag in soup.find_all(["h1", "h2", "h3", "h4"]):
        text = clean_text(tag.get_text(" ", strip=True))
        if text in {"Author(s):", "Author(s)"}:
            heading = tag
            break
    if heading is None:
        return None

    names = []
    for sibling in heading.find_next_siblings():
        if sibling.name in {"h1", "h2", "h3", "h4", "hr"}:
            break
        for anchor in sibling.find_all("a"):
            name = clean_text(anchor.get_text(" ", strip=True))
            if name and name not in names:
                names.append(name)

    if names:
        return ", ".join(names)

    block = heading.find_next_sibling()
    return clean_text(block.get_text(" ", strip=True)) if block else None


def extract_pdf_url(soup, paper_url):
    for anchor in soup.find_all("a", href=True):
        href = anchor.get("href", "")
        text = clean_text(anchor.get_text(" ", strip=True)) or ""
        if href.lower().endswith(".pdf") and ("/paper/" in href or "main paper" in text.lower()):
            return urljoin(paper_url, href)
    return None


def extract_doi(soup):
    for anchor in soup.find_all("a", href=True):
        href = anchor.get("href", "")
        if "doi.org/" in href:
            return href.split("doi.org/", 1)[-1].strip()
    return None


def parse_paper_page(session, year, paper_url):
    response = session.get(paper_url, headers=HEADERS, timeout=45)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "lxml")

    h1 = soup.find("h1")
    title = clean_text(h1.get_text(" ", strip=True)) if h1 else None
    if not title:
        return None

    source_id = urlparse(paper_url).path.rstrip("/").split("/")[-1].replace(".html", "")

    return {
        "title": title,
        "authors": extract_authors(soup),
        "venue": "MICCAI",
        "year": year,
        "abstract": _section_text(soup, "Abstract"),
        "paper_url": paper_url,
        "pdf_url": extract_pdf_url(soup, paper_url),
        "doi": extract_doi(soup),
        "source": "MICCAI Open Access",
        "source_id": source_id,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--sleep", type=float, default=0.05)
    args = parser.parse_args()

    if args.year not in SUPPORTED_YEARS:
        supported = ", ".join(str(year) for year in sorted(SUPPORTED_YEARS))
        parser.error(f"Unsupported MICCAI year {args.year}. Supported years: {supported}")

    session = requests.Session()
    links = get_paper_links(session, args.year)
    if args.limit:
        links = links[: args.limit]

    conn = sqlite3.connect(DB_PATH)
    new_rows = 0
    refreshed_rows = 0
    failed = 0

    for paper_url in tqdm(links, desc=f"MICCAI {args.year}"):
        try:
            paper = parse_paper_page(session, args.year, paper_url)
            if paper is None:
                failed += 1
                continue
            if upsert_paper(conn, paper):
                new_rows += 1
            else:
                refreshed_rows += 1

            if (new_rows + refreshed_rows) % 100 == 0:
                conn.commit()
            time.sleep(args.sleep)
        except Exception as exc:
            failed += 1
            print(f"Error: {paper_url} | {exc}")

    conn.commit()
    conn.close()

    print(f"\nMICCAI {args.year} complete")
    print(f"New rows: {new_rows}")
    print(f"Refreshed existing rows: {refreshed_rows}")
    print(f"Failed/skipped pages: {failed}")


if __name__ == "__main__":
    main()
