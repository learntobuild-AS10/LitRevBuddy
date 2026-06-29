import argparse
import sqlite3
import time
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from tqdm import tqdm

DB_PATH = "data/papers.db"

def clean_text(text):
    if not text:
        return None
    return " ".join(text.split())

def extract_abstract(soup):
    abstract_div = soup.find("div", id="abstract")
    if abstract_div:
        return clean_text(abstract_div.get_text(" ", strip=True))
    return None

def extract_pdf_url(soup, paper_url):
    for link in soup.find_all("a"):
        text = link.get_text(" ", strip=True).lower()
        href = link.get("href", "")

        if "pdf" in text or href.lower().endswith(".pdf"):
            return urljoin(paper_url, href)

    return None

def enrich(limit=None, sleep=0.15):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    sql = """
    SELECT id, paper_url
    FROM papers
    WHERE source = 'CVF Open Access'
      AND paper_url IS NOT NULL
      AND paper_url != ''
      AND (
          abstract IS NULL OR abstract = ''
          OR pdf_url IS NULL OR pdf_url = ''
      )
    ORDER BY year DESC, venue ASC, id ASC
    """

    if limit:
        sql += f" LIMIT {int(limit)}"

    rows = cur.execute(sql).fetchall()

    print(f"Rows to enrich: {len(rows)}")

    session = requests.Session()
    updated = 0

    for paper_id, paper_url in tqdm(rows):
        try:
            response = session.get(paper_url, timeout=30)

            if response.status_code != 200:
                continue

            soup = BeautifulSoup(response.text, "lxml")

            abstract = extract_abstract(soup)
            pdf_url = extract_pdf_url(soup, paper_url)

            cur.execute("""
                UPDATE papers
                SET
                    abstract = COALESCE(NULLIF(?, ''), abstract),
                    pdf_url = COALESCE(NULLIF(?, ''), pdf_url)
                WHERE id = ?
            """, (abstract, pdf_url, paper_id))

            updated += 1

            if updated % 100 == 0:
                conn.commit()

            time.sleep(sleep)

        except Exception as e:
            print(f"Error on {paper_id}: {paper_url} | {e}")

    conn.commit()
    conn.close()

    print(f"Updated rows: {updated}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--sleep", type=float, default=0.15)
    args = parser.parse_args()

    enrich(limit=args.limit, sleep=args.sleep)
