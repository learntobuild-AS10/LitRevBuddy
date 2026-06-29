import argparse
import re
import sqlite3
import time
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from tqdm import tqdm

DB_PATH = "data/papers.db"

PROCEEDINGS = {
    2024: "https://aaai.org/proceeding/aaai-38-2024/",
    2025: "https://aaai.org/proceeding/aaai-39-2025/",
    2026: "https://aaai.org/proceeding/aaai-40-2026/",
}

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

def get_issue_links(session, year, proceedings_url):
    print(f"\nFetching AAAI {year} proceedings page: {proceedings_url}")

    response = session.get(proceedings_url, headers=HEADERS, timeout=30)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "lxml")

    links = []
    seen = set()

    for a in soup.find_all("a"):
        href = a.get("href", "")
        text = clean_text(a.get_text(" ", strip=True)) or ""

        if "/index.php/AAAI/issue/view/" not in href and "ojs.aaai.org/index.php/AAAI/issue/view/" not in href:
            continue

        # Keep only issue pages for the target volume/year page.
        issue_url = urljoin(proceedings_url, href)

        if issue_url not in seen:
            seen.add(issue_url)
            links.append(issue_url)

    print(f"Found {len(links)} AAAI {year} issue pages")
    return links

def is_article_page_url(url):
    parsed = urlparse(url)
    parts = [p for p in parsed.path.split("/") if p]

    # Expected article page:
    # /index.php/AAAI/article/view/27749
    # Exclude PDF/download variants like /article/view/27749/29632
    if len(parts) < 5:
        return False

    try:
        idx = parts.index("article")
    except ValueError:
        return False

    if idx + 2 >= len(parts):
        return False

    if parts[idx + 1] != "view":
        return False

    after_view = parts[idx + 2:]

    return len(after_view) == 1 and after_view[0].isdigit()

def get_paper_links_from_issue(session, issue_url):
    response = session.get(issue_url, headers=HEADERS, timeout=30)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "lxml")

    links = []
    seen = set()

    for a in soup.find_all("a"):
        href = a.get("href", "")
        title = clean_text(a.get_text(" ", strip=True))

        if not href or not title:
            continue

        paper_url = urljoin(issue_url, href)

        if not is_article_page_url(paper_url):
            continue

        if title.lower() in {"pdf", "video/poster", "abstract", "html"}:
            continue

        if paper_url not in seen:
            seen.add(paper_url)
            links.append((title, paper_url))

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

    # OJS fallback: after the Authors heading, names are often in list items.
    text_lines = [
        clean_text(x)
        for x in soup.get_text("\n").splitlines()
        if clean_text(x)
    ]

    if "Authors" in text_lines:
        idx = text_lines.index("Authors")
        candidates = []

        for line in text_lines[idx + 1:]:
            if line in {"DOI:", "Keywords:", "Abstract", "Downloads", "Published", "How to Cite"}:
                break

            # Remove affiliation-heavy lines only if they are obviously not a name.
            if len(line) > 120:
                continue

            candidates.append(line)

        if candidates:
            return ", ".join(candidates)

    return None

def extract_abstract(soup):
    abstract = get_meta_content(soup, "description")
    if abstract and len(abstract) > 40:
        return abstract

    lines = [
        clean_text(x)
        for x in soup.get_text("\n").splitlines()
        if clean_text(x)
    ]

    if "Abstract" in lines:
        idx = lines.index("Abstract")
        chunks = []

        stop_terms = {
            "Downloads",
            "Published",
            "How to Cite",
            "Issue",
            "Section",
            "Information",
            "DOI:",
            "Keywords:",
        }

        for line in lines[idx + 1:]:
            if line in stop_terms:
                break
            chunks.append(line)

        return clean_text(" ".join(chunks))

    return None

def extract_pdf_url(soup, paper_url):
    pdf = get_meta_content(soup, "citation_pdf_url")
    if pdf:
        return urljoin(paper_url, pdf)

    for a in soup.find_all("a"):
        text = clean_text(a.get_text(" ", strip=True)) or ""
        href = a.get("href", "")

        if text.lower() == "pdf" or href.lower().endswith(".pdf"):
            return urljoin(paper_url, href)

    return None

def extract_doi(soup):
    doi = get_meta_content(soup, "citation_doi")
    if doi:
        return doi

    for a in soup.find_all("a"):
        href = a.get("href", "")
        if "doi.org/" in href:
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
        "venue": "AAAI",
        "year": year,
        "abstract": extract_abstract(soup),
        "paper_url": paper_url,
        "pdf_url": extract_pdf_url(soup, paper_url),
        "doi": extract_doi(soup),
        "source": "AAAI OJS",
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

    for year, proceedings_url in PROCEEDINGS.items():
        issue_links = get_issue_links(session, year, proceedings_url)

        paper_links = []
        seen_papers = set()

        for issue_url in issue_links:
            try:
                links = get_paper_links_from_issue(session, issue_url)

                for title, paper_url in links:
                    if paper_url not in seen_papers:
                        seen_papers.add(paper_url)
                        paper_links.append((title, paper_url))

                time.sleep(args.sleep)

            except Exception as e:
                print(f"Error reading issue page: {issue_url} | {e}")

        if args.limit:
            paper_links = paper_links[:args.limit]

        print(f"Processing {len(paper_links)} AAAI {year} paper pages")

        before = conn.total_changes
        skipped = 0

        for fallback_title, paper_url in tqdm(paper_links, desc=f"AAAI {year}"):
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

        print(f"Inserted new rows for AAAI {year}: {inserted}")
        print(f"Skipped rows: {skipped}")

    conn.close()
    print(f"\nDone. Inserted {total_inserted} new AAAI rows.")

if __name__ == "__main__":
    main()
