import sqlite3
from pathlib import Path

DB_PATH = Path("data/papers.db")
DB_PATH.parent.mkdir(exist_ok=True)

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS papers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    authors TEXT,
    venue TEXT NOT NULL,
    year INTEGER NOT NULL,
    abstract TEXT,
    paper_url TEXT,
    pdf_url TEXT,
    doi TEXT,
    arxiv_id TEXT,
    source TEXT,
    source_id TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(title, venue, year)
)
""")

cur.execute("""
CREATE INDEX IF NOT EXISTS idx_papers_venue_year
ON papers(venue, year)
""")

cur.execute("""
CREATE INDEX IF NOT EXISTS idx_papers_title
ON papers(title)
""")

conn.commit()
conn.close()

print("Database initialized at data/papers.db")
