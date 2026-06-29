import argparse
import sqlite3
import time
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from tqdm import tqdm

DB_PATH = "data/papers.db"
YEARS = [2024, 2025]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; local-paper-database/1.0)"
}

BAD_TITLES = {
    "",
    "abstract",
    "paper",
    "bibtex",
    "author information",
    "name change policy",
    "advances in neural information processing systems",
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
        content = clean_text(tag.get("content"))
        if content:
            values.append(content)
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

def get_paper_links(session, year):
    urls = [
        f"https://proceedings.neurips.cc/papers/{year}",
        f"https://proceedings.neurips.cc/paper_files/paper/{year}",
    ]

    expected_fragment = f"/paper_files/paper/{year}/hash/"

    for url in urls:
        print(f"\nFetching NeurIPS {year} list: {url}")

        response = session.get(url, headers=HEADERS, timeout=30)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "lxml")

        links = []
        seen = set()

        for a in soup.find_all("a"):
            href = a.get("href", "")
            title = clean_text(a.get_text(" ", strip=True))

            if not href:
                continue

            if expected_fragment not in href:
                continue

            if not href.endswith(".html"):
                continue

            if not title or title.lower() in BAD_TITLES:
                continue

            paper_url = urljoin(url, href)

            if paper_url in seen:
                continue

            seen.add(paper_url)
            links.append((title, paper_url))

        if links:
            print(f"Found {len(links)} NeurIPS {year} paper pages")
            return links

    raise RuntimeError(f"Could not find paper links for NeurIPS {year}")

def extract_authors(soup):
    authors = get_all_meta_content(soup, "citation_author")
    if authors:
        return ", ".join(authors)

    italic = soup.find("i")
    if italic:
        return clean_text(italic.get_text(" ", strip=True))

    return None

def extract_abstract(soup):
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

    abstract_div = soup.find("div", id="abstract")
    if abstract_div:
        return clean_text(abstract_div.get_text(" ", strip=True))

    return None

def extract_pdf_url(soup, paper_url):
    meta_pdf = get_meta_content(soup, "citation_pdf_url")
    if meta_pdf:
        return urljoin(paper_url, meta_pdf)

    for a in soup.find_all("a"):
        text = clean_text(a.get_text(" ", strip=True)) or ""
        href = a.get("href", "")

        if text.lower() == "paper" or href.lower().endswith(".pdf"):
            return urljoin(paper_url, href)

    return None

def extract_doi(soup):
    for a in soup.find_all("a"):
        href = a.get("href", "")
        text = clean_text(a.get_text(" ", strip=True)) or ""

        if "doi.org" in href:
            return href.split("doi.org/", 1)[-1]

        if text.lower().startswith("doi"):
            return text

    return None

def parse_detail_page(session, year, title_from_list, paper_url):
    response = session.get(paper_url, headers=HEADERS, timeout=30)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "lxml")

    meta_title = get_meta_content(soup, "citation_title")

    title = meta_title or title_from_list
    title = clean_text(title)

    if not title or title.lower() in BAD_TITLES:
        return None

    parsed = urlparse(paper_url)
    source_id = parsed.path.rstrip("/").split("/")[-1].replace(".html", "")

    return {
        "title": title,
        "authors": extract_authors(soup),
        "venue": "NeurIPS",
        "year": year,
        "abstract": extract_abstract(soup),
        "paper_url": paper_url,
        "pdf_url": extract_pdf_url(soup, paper_url),
        "doi": extract_doi(soup),
        "source": "NeurIPS Proceedings",
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

    for year in YEARS:
        links = get_paper_links(session, year)

        if args.limit:
            links = links[:args.limit]

        print(f"Processing {len(links)} NeurIPS {year} paper pages")

        before = conn.total_changes
        skipped = 0

        for title_from_list, paper_url in tqdm(links, desc=f"NeurIPS {year}"):
            try:
                paper = parse_detail_page(session, year, title_from_list, paper_url)

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

        print(f"Inserted new rows for NeurIPS {year}: {inserted}")
        print(f"Skipped rows: {skipped}")

    conn.close()

    print(f"\nDone. Inserted {total_inserted} new NeurIPS rows.")

if __name__ == "__main__":
    main()
