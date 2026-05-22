from __future__ import annotations

from datetime import datetime

from scraper.config import ARCHIV_START_YEAR
from scraper.parse import images_from_json, tags_from_json

# Kalenderjahr der Meldung (nicht nur URL-Pfad)
YEAR_SQL = "CAST(substr(COALESCE(published_at, meldung_date || 'T00:00:00'), 1, 4) AS INTEGER)"
YEAR_FILTER_SQL = f"{YEAR_SQL} = ?"


def enrich_row(row) -> dict:
    """sqlite3.Row → dict with parsed tags/images and display year."""
    d = dict(row)
    d["tags_list"] = tags_from_json(d.get("tags"))
    d["images_list"] = images_from_json(d.get("images"))
    pub = d.get("published_at") or d.get("meldung_date") or ""
    d["pub_year"] = int(pub[:4]) if len(pub) >= 4 and pub[:4].isdigit() else d.get("source_year")
    return d


def format_datetime(iso: str | None) -> str:
    if not iso:
        return "—"
    return iso[:16].replace("T", " ")


def fill_years_range(rows: list, start: int | None = None, end: int | None = None) -> list[dict]:
    """Alle Jahre von start..end mit count (0 wenn leer)."""
    start = start or ARCHIV_START_YEAR
    end = end or datetime.now().year
    counts = {int(r["year"]): int(r["count"]) for r in rows}
    return [{"year": y, "count": counts.get(y, 0)} for y in range(end, start - 1, -1)]
