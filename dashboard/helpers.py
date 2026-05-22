from __future__ import annotations

from scraper.parse import images_from_json, tags_from_json


def enrich_row(row) -> dict:
    """sqlite3.Row → dict with parsed tags/images."""
    d = dict(row)
    d["tags_list"] = tags_from_json(d.get("tags"))
    d["images_list"] = images_from_json(d.get("images"))
    return d


def format_datetime(iso: str | None) -> str:
    if not iso:
        return "—"
    return iso[:16].replace("T", " ")
