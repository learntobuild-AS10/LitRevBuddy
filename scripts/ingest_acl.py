import argparse
import re
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

def get_volume_links(session, year):
    event_url = f"https://aclanthology.org/events/acl-{year}/"
    print(f"\nFetching ACL {year} event page: {event_url}")

    response = session.get(event_url, headers=HEADERS, timeout=30)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "lxml")

    volume_pattern = re.compile(rf"/volumes/{year}\.acl-[a-z0-9-]+/?$")
    paper_pattern = re.compile(rf"/{year}\.acl-[a-z0-9-]+\.\d+/?$")

    volume_links = []
    paper_links = []
    seen_volumes = set()
    seen_papers = set()

    for a in soup.find_all("a"):
        href = a.get("href", "")

        if volume_pattern.match(href):
            url = urljoin(event_url, href)
            if url not in seen_volumes:
                seen_volumes.add(url)
                volume_links.append(url)

        if paper_pattern.match(href):
            paper_id = href.strip("/").split("/")[-1]
            if not paper_id.endswith(".0"):
                url = urljoin(event_url, href)
                if url not in seen_papers:
                    seen_papers.add(url)
                    paper_links.append(url)

    print(f"Found {len(volume_links)} volume pages from ACL {year} event page")

    return volume_links, paper_links

def get_paper_links_from_volume(session, volume_url, year):
    response = session.get(volume_url, headers=HEADERS, timeout=30)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "lxml")

    pattern = re.compile(rf"/{year}\.acl-[a-z0-9-]+\.\d+/?$")

    links = []
    seen = set()

    for a in soup.find_all("a"):
        href = a.get("href", "")
        title = clean_text(a.get_text(" ", strip=True))

        if not pattern.match(href):
            continue

        paper_id = href.strip("/").split("/")[-1]

        # Skip proceedings/editorial front matter.
        if paper_id.endswith(".0"):
            continue

        paper_url = urljoin(volume_url, href)

        if paper_url in seen:
            continue

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

    h2 = soup.find("h2")
    if h2:
        return clean_text(h2.get_text(" ", strip=True))

    return fallback_title

def extract_authors(soup):
    authors = get_all_meta_content(soup, "citation_author")
    if authors:
        return ", ".join(authors)

    for tag in soup.find_all(["p", "div"]):
        cls = " ".join(tag.get("class", []))
        if "authors" in cls.lower():
            return clean_text(tag.get_text(" ", strip=True))

    return None

def extract_abstract(soup):
    abstract = get_meta_content(soup, "description")
    if abstract and len(abstract) > 40:
        return abstract

    for tag in soup.find_all(["h2", "h3", "h4", "h5"]):
        if clean_text(tag.get_text(" ", strip=True)) == "Abstract":
            chunks = []

            for sibling in tag.find_next_siblings():
                if sibling.name in ["h2", "h3", "h4", "h5"]:
                    break

                text = clean_text(sibling.get_text(" ", strip=True))
                if text:
                    chunks.append(text)

            if chunks:
                return clean_text(" ".join(chunks))

    for div in soup.find_all("div"):
        cls = " ".join(div.get("class", []))
        if "abstract" in cls.lower():
            text = clean_text(div.get_text(" ", strip=True))
            if text:
                return text.replace("Abstract", "", 1).strip()

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
        "venue": "ACL",
        "year": year,
        "abstract": extract_abstract(soup),
        "paper_url": paper_url,
        "pdf_url": extract_pdf_url(soup, paper_url),
        "doi": extract_doi(soup),
        "source": "ACL Anthology",
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
        volume_links, direct_paper_links = get_volume_links(session, year)

        paper_links = []
        seen = set()

        for volume_url in volume_links:
            links = get_paper_links_from_volume(session, volume_url, year)

            for title, paper_url in links:
                if paper_url not in seen:
                    seen.add(paper_url)
                    paper_links.append((title, paper_url))

        # Fallback in case event page directly contains paper links.
        for paper_url in direct_paper_links:
            if paper_url not in seen:
                seen.add(paper_url)
                paper_links.append((None, paper_url))

        if args.limit:
            paper_links = paper_links[:args.limit]

        print(f"Processing {len(paper_links)} ACL {year} paper pages")

        before = conn.total_changes
        skipped = 0

        for fallback_title, paper_url in tqdm(paper_links, desc=f"ACL {year}"):
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

        print(f"Inserted new rows for ACL {year}: {inserted}")
        print(f"Skipped rows: {skipped}")

    conn.close()
    print(f"\nDone. Inserted {total_inserted} new ACL rows.")

if __name__ == "__main__":
    main()
