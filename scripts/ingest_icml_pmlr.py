import argparse
import sqlite3
import time
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from tqdm import tqdm

DB_PATH = "data/papers.db"

# Official PMLR ICML proceedings:
# 2024: ICML 41, PMLR v235
# 2025: ICML 42, PMLR v267
VOLUMES = [
    (2024, "235"),
    (2025, "267"),
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; local-paper-database/1.0)"
}

def clean_text(text):
    if not text:
        return None
    return " ".join(str(text).split())

def get_meta_content(soup, name):
    tag = soup.find("meta", attrs={"name": name})
    if tag and tag.get("content"):
        return clean_text(tag.get("content"))
    return None

def get_all_meta_content(soup, name):
    values = []
    for tag in soup.find_all("meta", attrs={"name": name}):
        value = clean_text(tag.get("content"))
        if value:
            values.append(value)
    return values

def insert_paper(conn, paper):
    cur = conn.cursor()
    cur.execute("""
        INSERT OR IGNORE INTO papers
        (title, authors, venue, year, abstract, paper_url, pdf_url, doi, source, source_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
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
    ))

def get_paper_links(session, year, volume):
    url = f"https://proceedings.mlr.press/v{volume}/"
    print(f"\nFetching ICML {year} PMLR page: {url}")

    response = session.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "lxml")

    links = []
    seen = set()

    # Main PMLR structure.
    for div in soup.select("div.paper"):
        title_node = div.find("p", class_="title")
        title = clean_text(title_node.get_text(" ", strip=True)) if title_node else None

        abs_link = None
        for a in div.find_all("a"):
            text = clean_text(a.get_text(" ", strip=True)) or ""
            href = a.get("href", "")

            if text.lower() == "abs" and href.endswith(".html"):
                abs_link = urljoin(url, href)
                break

        if title and abs_link and abs_link not in seen:
            seen.add(abs_link)
            links.append((title, abs_link))

    # Fallback for slightly different PMLR HTML.
    if not links:
        for a in soup.find_all("a"):
            href = a.get("href", "")
            if not href.endswith(".html"):
                continue

            paper_url = urljoin(url, href)
            if f"/v{volume}/" not in paper_url:
                continue

            title = clean_text(a.get_text(" ", strip=True))
            if not title or title.lower() in {"abs", "download pdf", "pdf", "openreview", "software"}:
                continue

            if paper_url not in seen:
                seen.add(paper_url)
                links.append((title, paper_url))

    print(f"Found {len(links)} ICML {year} paper pages")
    return links

def extract_title(soup, fallback_title):
    title = get_meta_content(soup, "citation_title")
    if title:
        return title

    h1 = soup.find("h1")
    if h1:
        return clean_text(h1.get_text(" ", strip=True))

    return fallback_title

def extract_authors(soup):
    authors = get_all_meta_content(soup, "citation_author")
    if authors:
        return ", ".join(authors)
    return None

def extract_abstract(soup):
    abstract = get_meta_content(soup, "description")
    if abstract and len(abstract) > 40:
        return abstract

    div = soup.find("div", id="abstract")
    if div:
        return clean_text(div.get_text(" ", strip=True))

    for tag in soup.find_all(["h2", "h3", "h4"]):
        if clean_text(tag.get_text(" ", strip=True)) == "Abstract":
            chunks = []
            for sibling in tag.find_next_siblings():
                if sibling.name in ["h2", "h3", "h4"]:
                    break
                text = clean_text(sibling.get_text(" ", strip=True))
                if text:
                    chunks.append(text)
            return clean_text(" ".join(chunks))

    return None

def extract_pdf_url(soup, paper_url):
    pdf = get_meta_content(soup, "citation_pdf_url")
    if pdf:
        return urljoin(paper_url, pdf)

    for a in soup.find_all("a"):
        text = clean_text(a.get_text(" ", strip=True)) or ""
        href = a.get("href", "")

        if text.lower() in {"download pdf", "pdf"} or href.lower().endswith(".pdf"):
            return urljoin(paper_url, href)

    return None

def extract_doi(soup):
    doi = get_meta_content(soup, "citation_doi")
    if doi:
        return doi

    for a in soup.find_all("a"):
        href = a.get("href", "")
        if "doi.org" in href:
            return href.split("doi.org/", 1)[-1]

    return None

def parse_paper_page(session, year, fallback_title, paper_url):
    response = session.get(paper_url, headers=HEADERS, timeout=30)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "lxml")

    title = extract_title(soup, fallback_title)
    title = clean_text(title)

    if not title:
        return None

    parsed = urlparse(paper_url)
    source_id = parsed.path.strip("/")

    return {
        "title": title,
        "authors": extract_authors(soup),
        "venue": "ICML",
        "year": year,
        "abstract": extract_abstract(soup),
        "paper_url": paper_url,
        "pdf_url": extract_pdf_url(soup, paper_url),
        "doi": extract_doi(soup),
        "source": "PMLR",
        "source_id": source_id,
    }

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--sleep", type=float, default=0.05)
    args = parser.parse_args()

    session = requests.Session()
    conn = sqlite3.connect(DB_PATH)

    total_inserted = 0

    for year, volume in VOLUMES:
        links = get_paper_links(session, year, volume)

        if args.limit:
            links = links[:args.limit]

        print(f"Processing {len(links)} ICML {year} paper pages")

        before = conn.total_changes
        skipped = 0

        for fallback_title, paper_url in tqdm(links, desc=f"ICML {year}"):
            try:
                paper = parse_paper_page(session, year, fallback_title, paper_url)

                if paper is None:
                    skipped += 1
                    continue

                insert_paper(conn, paper)

                if conn.total_changes % 250 == 0:
                    conn.commit()

                time.sleep(args.sleep)

            except Exception as e:
                print(f"Error: {paper_url} | {e}")

        conn.commit()

        inserted = conn.total_changes - before
        total_inserted += inserted

        print(f"Inserted new rows for ICML {year}: {inserted}")
        print(f"Skipped rows: {skipped}")

    conn.close()
    print(f"\nDone. Inserted {total_inserted} new ICML rows.")

if __name__ == "__main__":
    main()
