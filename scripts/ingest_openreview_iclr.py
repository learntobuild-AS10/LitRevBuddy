import argparse
import sqlite3
import time
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from tqdm import tqdm

DB_PATH = "data/papers.db"

YEARS = [2024, 2025, 2026]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; local-paper-database/1.0)"
}

def clean_text(text):
    if not text:
        return None
    return " ".join(text.split())

def insert_paper(conn, paper):
    cur = conn.cursor()
    cur.execute("""
        INSERT OR IGNORE INTO papers
        (title, authors, venue, year, abstract, paper_url, pdf_url, source, source_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        paper["title"],
        paper["authors"],
        paper["venue"],
        paper["year"],
        paper["abstract"],
        paper["paper_url"],
        paper["pdf_url"],
        paper["source"],
        paper["source_id"],
    ))
    conn.commit()

def get_paper_links(session, year):
    url = f"https://iclr.cc/virtual/{year}/papers.html?filter=titles"
    print(f"\nFetching ICLR {year} list: {url}")

    response = session.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "lxml")

    links = []
    seen = set()

    for a in soup.find_all("a"):
        href = a.get("href", "")
        title = clean_text(a.get_text(" ", strip=True))

        if f"/virtual/{year}/poster/" not in href:
            continue

        paper_url = urljoin(url, href)

        if paper_url in seen:
            continue

        seen.add(paper_url)
        links.append((title, paper_url))

    return links

def extract_openreview_and_pdf(soup):
    openreview_url = None
    pdf_url = None

    for a in soup.find_all("a"):
        text = clean_text(a.get_text(" ", strip=True)) or ""
        href = a.get("href", "")

        if "openreview" in text.lower() or "openreview.net" in href:
            openreview_url = href

            if "id=" in href:
                paper_id = href.split("id=", 1)[1].split("&", 1)[0]
                pdf_url = f"https://openreview.net/pdf?id={paper_id}"

            break

    return openreview_url, pdf_url

def parse_detail_page(session, year, fallback_title, paper_url):
    response = session.get(paper_url, headers=HEADERS, timeout=30)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "lxml")

    h1 = soup.find("h1")
    title = clean_text(h1.get_text(" ", strip=True)) if h1 else fallback_title

    lines = [
        clean_text(x)
        for x in soup.get_text("\n").splitlines()
        if clean_text(x)
    ]

    authors = None
    abstract = None

    if title in lines:
        title_idx = lines.index(title)

        author_candidates = []
        for line in lines[title_idx + 1:]:
            low = line.lower()

            if low == "abstract":
                break

            if low in {"poster", "oral", "spotlight"}:
                continue

            if low.endswith("poster") or low.endswith("oral") or low.endswith("spotlight"):
                continue

            if "openreview" in low or "slides" in low or "poster" == low:
                continue

            author_candidates.append(line)

        if author_candidates:
            authors = author_candidates[0]

    if "Abstract" in lines:
        abs_idx = lines.index("Abstract")
        chunks = []

        stop_words = {
            "show more",
            "video",
            "chat is not available.",
            "successful page load",
            "log in and register to view live content",
        }

        for line in lines[abs_idx + 1:]:
            if line.lower() in stop_words:
                break
            chunks.append(line)

        abstract = clean_text(" ".join(chunks))

    openreview_url, pdf_url = extract_openreview_and_pdf(soup)

    parsed = urlparse(paper_url)
    source_id = parsed.path.rstrip("/").split("/")[-1]

    return {
        "title": title,
        "authors": authors,
        "venue": "ICLR",
        "year": year,
        "abstract": abstract,
        "paper_url": paper_url,
        "pdf_url": pdf_url,
        "source": "ICLR Virtual Site",
        "source_id": source_id,
    }

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--sleep", type=float, default=0.1)
    args = parser.parse_args()

    session = requests.Session()
    conn = sqlite3.connect(DB_PATH)

    total = 0

    for year in YEARS:
        links = get_paper_links(session, year)

        if args.limit:
            links = links[:args.limit]

        print(f"Found {len(links)} ICLR {year} paper pages")

        inserted = 0

        for fallback_title, paper_url in tqdm(links, desc=f"ICLR {year}"):
            try:
                paper = parse_detail_page(session, year, fallback_title, paper_url)

                if paper["title"]:
                    insert_paper(conn, paper)
                    inserted += 1

                time.sleep(args.sleep)

            except Exception as e:
                print(f"Error: {paper_url} | {e}")

        print(f"Inserted/checked {inserted} papers for ICLR {year}")
        total += inserted

    conn.close()

    print(f"\nDone. Processed {total} ICLR papers.")

if __name__ == "__main__":
    main()
