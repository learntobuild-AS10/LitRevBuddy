import argparse
import sqlite3
import subprocess
import sys
from pathlib import Path

DB_PATH = Path("data/papers.db")

CURRENT_TARGETS = {
    "icml": [sys.executable, "scripts/ingest_icml_pmlr.py", "--year", "2026"],
    "miccai": [sys.executable, "scripts/ingest_miccai.py", "--year", "2026"],
}


def total_papers():
    if not DB_PATH.exists():
        return 0
    with sqlite3.connect(DB_PATH) as conn:
        return int(conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0])


def counts_by_venue_year():
    if not DB_PATH.exists():
        return []
    with sqlite3.connect(DB_PATH) as conn:
        return conn.execute(
            """
            SELECT venue, year, COUNT(*)
            FROM papers
            GROUP BY venue, year
            ORDER BY year DESC, venue ASC
            """
        ).fetchall()


def run_command(command):
    print("\n$ " + " ".join(command))
    completed = subprocess.run(command, check=False)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def main():
    parser = argparse.ArgumentParser(
        description="Refresh currently publishable LitRevBuddy conference sources."
    )
    parser.add_argument(
        "--venues",
        default="icml,miccai",
        help="Comma-separated current targets. Supported: icml,miccai",
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--sleep", type=float, default=None)
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Rebuild TF-IDF/SVD/clustering/search artifacts after ingestion.",
    )
    args = parser.parse_args()

    venues = [item.strip().lower() for item in args.venues.split(",") if item.strip()]
    unknown = [venue for venue in venues if venue not in CURRENT_TARGETS]
    if unknown:
        parser.error(
            "Unsupported venue(s): "
            + ", ".join(unknown)
            + ". Supported current targets: "
            + ", ".join(sorted(CURRENT_TARGETS))
        )

    before = total_papers()
    print(f"LitRevBuddy database update")
    print(f"Before update: {before:,} papers")

    for venue in venues:
        command = list(CURRENT_TARGETS[venue])
        if args.limit is not None:
            command.extend(["--limit", str(args.limit)])
        if args.sleep is not None:
            command.extend(["--sleep", str(args.sleep)])
        run_command(command)

    after = total_papers()
    print(f"\nAfter update: {after:,} papers")
    print(f"Net new rows: {after - before:,}")

    print("\nCurrent venue/year counts:")
    for venue, year, count in counts_by_venue_year():
        if venue.lower() in venues or (venue == "ICML" and "icml" in venues):
            print(f"  {venue:10} {year}: {count:,}")

    if args.rebuild:
        run_command([sys.executable, "scripts/build_features.py"])
    else:
        print("\nSearch artifacts were NOT rebuilt.")
        print("When the database looks correct, run:")
        print("  python scripts/build_features.py")
        print("or rerun this updater with --rebuild.")


if __name__ == "__main__":
    main()
