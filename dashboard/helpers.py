from __future__ import annotations

from datetime import datetime

from scraper.config import ARCHIV_START_YEAR
from scraper.parse import images_from_json, tags_from_json

YEAR_SQL = "CAST(substr(COALESCE(published_at, meldung_date || 'T00:00:00'), 1, 4) AS INTEGER)"
YEAR_FILTER_SQL = f"{YEAR_SQL} = ?"

WEEKDAY_NAMES = ["So", "Mo", "Di", "Mi", "Do", "Fr", "Sa"]
SEASON_NAMES = ["Winter", "Frühling", "Sommer", "Herbst"]
MONTH_NAMES = [
    "Jan", "Feb", "Mär", "Apr", "Mai", "Jun",
    "Jul", "Aug", "Sep", "Okt", "Nov", "Dez",
]


def enrich_row(row) -> dict:
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
    start = start or ARCHIV_START_YEAR
    end = end or datetime.now().year
    counts = {int(r["year"]): int(r["count"]) for r in rows}
    return [{"year": y, "count": counts.get(y, 0)} for y in range(end, start - 1, -1)]


def _fill_month_gaps(rows: list[dict]) -> list[dict]:
    if not rows:
        return []
    counts = {r["period"]: r["count"] for r in rows}
    start_y, start_m = map(int, min(counts.keys()).split("-"))
    end_y, end_m = map(int, max(counts.keys()).split("-"))
    y, m = start_y, start_m
    out: list[dict] = []
    while (y, m) <= (end_y, end_m):
        key = f"{y:04d}-{m:02d}"
        out.append({"period": key, "label": key, "count": counts.get(key, 0)})
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return out


def _fill_week_gaps(rows: list[dict]) -> list[dict]:
    if not rows:
        return []
    from datetime import date, timedelta

    counts = {r["period"]: r["count"] for r in rows}

    def _parse_iso_week(p: str) -> date:
        y, w = p.split("-W")
        return date.fromisocalendar(int(y), int(w), 1)

    start = _parse_iso_week(min(counts.keys()))
    end = _parse_iso_week(max(counts.keys()))
    out: list[dict] = []
    cur = start
    while cur <= end:
        y, w, _ = cur.isocalendar()
        key = f"{y:04d}-W{w:02d}"
        out.append(
            {
                "period": key,
                "label": key.replace("-W", " KW "),
                "count": counts.get(key, 0),
            }
        )
        cur += timedelta(days=7)
    return out


def build_timeline(
    conn,
    granularity: str,
    where: str = "",
    params: list | None = None,
) -> tuple[list[dict], dict]:
    """Zeitreihe nach Tatdatum aus Meldungstext."""
    from dashboard.incident_time import build_incident_timeline

    return build_incident_timeline(conn, granularity, where, params)


def early_years_note(conn) -> dict:
    """Hinweis zu spärlichen Jahren 2014–2019 in DB und auf berlin.de."""
    rows = conn.execute(
        f"""
        SELECT {YEAR_SQL} AS y, COUNT(*) AS c
        FROM meldungen
        WHERE COALESCE(published_at, meldung_date) IS NOT NULL
          AND {YEAR_SQL} BETWEEN 2014 AND 2019
        GROUP BY y ORDER BY y
        """
    ).fetchall()
    return {
        "years": [dict(r) for r in rows],
        "total": sum(r["c"] for r in rows),
        "website_limit": True,
    }
