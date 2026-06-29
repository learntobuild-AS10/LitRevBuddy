import sqlite3
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from tqdm import tqdm

DB_PATH = "data/papers.db"

VENUES = [
    ("CVPR", 2024),
    ("CVPR", 2025),
    ("CVPR", 2026),
    ("WACV", 2024),
    ("WACV", 2025),
    ("WACV", 2026),
    ("ICCV", 2025),
]

def insert_paper(conn, paper):
    cur = conn.cursor()
    cur.execute("""
        INSERT OR IGNORE INTO papers
        (title, authors, venue, year, abstract, paper_url, pdf_url, source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        paper["title"],
        paper["authors"],
        paper["venue"],
        paper["year"],
        paper.get("abstract"),
        paper["paper_url"],
        paper["pdf_url"],
        "CVF Open Access",
    ))
    conn.commit()

def ingest_cvf(venue, year):
    base = f"https://openaccess.thecvf.com/{venue}{year}"
    url = base + "?day=all"

    print(f"\nFetching {venue} {year}: {url}")

    response = requests.get(url, timeout=30)
    if response.status_code != 200:
        print(f"Could not fetch {venue} {year}: HTTP {response.status_code}")
        return []

    soup = BeautifulSoup(response.text, "lxml")
    title_nodes = soup.select("dt.ptitle")

    papers = []

    for node in tqdm(title_nodes, desc=f"{venue} {year}"):
        a = node.find("a")
        if not a:
            continue

        title = a.get_text(" ", strip=True)
        paper_url = urljoin(base, a.get("href"))

        dd = node.find_next_sibling("dd")
        authors = None
        pdf_url = None

        if dd:
            authors = dd.get_text(" ", strip=True)

            for link in dd.find_all("a"):
                link_text = link.get_text(" ", strip=True).lower()
                href = link.get("href", "")
                if "pdf" in link_text or href.endswith(".pdf"):
                    pdf_url = urljoin(base, href)
                    break

        papers.append({
            "title": title,
            "authors": authors,
            "venue": venue,
            "year": year,
            "abstract": None,
            "paper_url": paper_url,
            "pdf_url": pdf_url,
        })

    return papers

def main():
    conn = sqlite3.connect(DB_PATH)

    total = 0
    for venue, year in VENUES:
        papers = ingest_cvf(venue, year)

        for paper in papers:
            insert_paper(conn, paper)

        print(f"Inserted/checked {len(papers)} papers for {venue} {year}")
        total += len(papers)

    conn.close()
    print(f"\nDone. Processed {total} CVF papers.")

if __name__ == "__main__":
    main()
