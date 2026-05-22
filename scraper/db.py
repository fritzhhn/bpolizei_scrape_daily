import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from scraper.config import DB_PATH, DATA_DIR
from scraper.parse import images_to_json, tags_to_json

TABLES_SQL = """
CREATE TABLE IF NOT EXISTS meldungen (
    id TEXT PRIMARY KEY,
    url TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    published_at TEXT,
    meldung_date TEXT,
    district TEXT,
    body_text TEXT,
    source_year INTEGER,
    first_seen_at TEXT NOT NULL,
    last_scraped_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scrape_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    mode TEXT NOT NULL,
    listings_found INTEGER DEFAULT 0,
    articles_fetched INTEGER DEFAULT 0,
    articles_new INTEGER DEFAULT 0,
    articles_updated INTEGER DEFAULT 0,
    errors INTEGER DEFAULT 0,
    notes TEXT
);
"""

INDEXES_SQL = """
CREATE INDEX IF NOT EXISTS idx_meldungen_published ON meldungen(published_at);
CREATE INDEX IF NOT EXISTS idx_meldungen_district ON meldungen(district);
CREATE INDEX IF NOT EXISTS idx_meldungen_year ON meldungen(source_year);
CREATE INDEX IF NOT EXISTS idx_meldungen_case ON meldungen(case_number);
"""

MIGRATION_COLUMNS = [
    ("summary", "TEXT"),
    ("tags", "TEXT"),
    ("case_number", "TEXT"),
    ("images", "TEXT"),
]

COMPARE_FIELDS = (
    "body_text",
    "title",
    "district",
    "published_at",
    "summary",
    "tags",
    "case_number",
    "images",
)


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _migrate(conn: sqlite3.Connection) -> None:
    existing = {row[1] for row in conn.execute("PRAGMA table_info(meldungen)")}
    for name, col_type in MIGRATION_COLUMNS:
        if name not in existing:
            conn.execute(f"ALTER TABLE meldungen ADD COLUMN {name} {col_type}")


@contextmanager
def connect(db_path: Path | None = None):
    ensure_data_dir()
    path = db_path or DB_PATH
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(TABLES_SQL)
        _migrate(conn)
        conn.executescript(INDEXES_SQL)
        yield conn
        conn.commit()
    finally:
        conn.close()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_db(row: dict) -> tuple:
    return (
        row["id"],
        row["url"],
        row["title"],
        row.get("published_at"),
        row.get("meldung_date"),
        row.get("district"),
        row.get("summary"),
        tags_to_json(row.get("tags")),
        row.get("case_number"),
        row.get("body_text"),
        images_to_json(row.get("images")),
        row.get("source_year"),
    )


def upsert_meldung(conn, row: dict) -> str:
    """Returns 'new', 'updated', or 'unchanged'."""
    existing = conn.execute(
        f"SELECT {', '.join(COMPARE_FIELDS)} FROM meldungen WHERE id = ?",
        (row["id"],),
    ).fetchone()

    now = utc_now()
    db_vals = _row_to_db(row)

    if existing is None:
        conn.execute(
            """
            INSERT INTO meldungen (
                id, url, title, published_at, meldung_date, district,
                summary, tags, case_number, body_text, images, source_year,
                first_seen_at, last_scraped_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (*db_vals, now, now),
        )
        return "new"

    new_tags = tags_to_json(row.get("tags"))
    new_images = images_to_json(row.get("images"))
    changed = (
        existing["body_text"] != row.get("body_text")
        or existing["title"] != row["title"]
        or existing["district"] != row.get("district")
        or existing["published_at"] != row.get("published_at")
        or existing["summary"] != row.get("summary")
        or existing["tags"] != new_tags
        or existing["case_number"] != row.get("case_number")
        or existing["images"] != new_images
    )
    conn.execute(
        """
        UPDATE meldungen SET
            url = ?, title = ?, published_at = ?, meldung_date = ?,
            district = ?, summary = ?, tags = ?, case_number = ?,
            body_text = ?, images = ?, source_year = ?, last_scraped_at = ?
        WHERE id = ?
        """,
        (*db_vals[1:], now, row["id"]),
    )
    return "updated" if changed else "unchanged"
