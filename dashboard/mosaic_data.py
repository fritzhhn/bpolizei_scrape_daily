"""Daily mosaic aggregation for the Berlin police-report dashboard."""

from __future__ import annotations

import math
import sqlite3
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path
from statistics import mean, pstdev
from typing import Any

from dashboard.weather import WEATHER_DB
from scraper.config import DB_PATH
from scraper.parse import tags_from_json

REPORT_DAY_SQL = "date(COALESCE(published_at, meldung_date))"

TOTAL_ROWS_SQL = "SELECT COUNT(*) AS total_rows FROM meldungen"

DATE_STATS_SQL = f"""
SELECT
    MIN({REPORT_DAY_SQL}) AS first_date,
    MAX({REPORT_DAY_SQL}) AS last_date,
    COUNT(DISTINCT {REPORT_DAY_SQL}) AS distinct_dates
FROM meldungen
WHERE {REPORT_DAY_SQL} IS NOT NULL
"""

DAILY_COUNTS_SQL = f"""
SELECT
    {REPORT_DAY_SQL} AS date,
    COUNT(*) AS report_count
FROM meldungen
WHERE {REPORT_DAY_SQL} IS NOT NULL
GROUP BY date
ORDER BY date
"""

DAILY_REPORTS_SQL = f"""
SELECT
    id,
    url,
    title,
    published_at,
    meldung_date,
    district,
    tags,
    {REPORT_DAY_SQL} AS report_date
FROM meldungen
WHERE {REPORT_DAY_SQL} IS NOT NULL
ORDER BY report_date ASC, (published_at IS NULL), published_at ASC, id ASC
"""

TOP_DAYS_SQL = f"""
SELECT
    {REPORT_DAY_SQL} AS date,
    COUNT(*) AS report_count
FROM meldungen
WHERE {REPORT_DAY_SQL} IS NOT NULL
GROUP BY date
ORDER BY report_count DESC, date
LIMIT ?
"""

WEATHER_JOIN_SQL = f"""
SELECT
    COUNT(DISTINCT {REPORT_DAY_SQL}) AS police_days,
    COUNT(DISTINCT w.day) AS matched_weather_days
FROM meldungen AS m
LEFT JOIN weather.daily AS w
    ON w.day = {REPORT_DAY_SQL}
WHERE {REPORT_DAY_SQL} IS NOT NULL
"""

WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
WEEKDAY_SHORT = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
SEASON_BY_MONTH = {
    12: "winter",
    1: "winter",
    2: "winter",
    3: "spring",
    4: "spring",
    5: "spring",
    6: "summer",
    7: "summer",
    8: "summer",
    9: "autumn",
    10: "autumn",
    11: "autumn",
}

WEATHER_FIELD_CANDIDATES = {
    "temperature_mean": ("tmean", "temperature_2m_mean", "mean_temperature"),
    "temperature_max": ("tmax", "temperature_2m_max", "max_temperature"),
    "temperature_min": ("tmin", "temperature_2m_min", "min_temperature"),
    "precipitation": ("precipitation_sum", "precipitation", "precip"),
    "rain": ("rain_sum", "rain"),
    "snow": ("snowfall_sum", "snowfall", "snow"),
    "wind": ("wind_speed_10m_max", "windspeed_10m_max", "wind_gusts_10m_max", "wind"),
    "sunshine": ("sunshine_duration", "sunshine"),
    "cloud_cover": ("cloud_cover_mean", "cloudcover_mean", "cloud_cover"),
    "condition": ("bin", "weather_code", "condition"),
}


def connect_meldungen(db_path: Path | None = None) -> sqlite3.Connection:
    """Open the police-report database with Row objects enabled."""
    conn = sqlite3.connect(db_path or DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _attach_weather(conn: sqlite3.Connection, weather_db: Path | None = None) -> bool:
    path = weather_db or WEATHER_DB
    if not path.exists():
        return False
    try:
        conn.execute("ATTACH DATABASE ? AS weather", (str(path),))
    except sqlite3.OperationalError as exc:
        if "already in use" not in str(exc):
            return False
    return True


def _weather_columns(conn: sqlite3.Connection) -> list[str]:
    try:
        rows = conn.execute("PRAGMA weather.table_info(daily)").fetchall()
    except sqlite3.DatabaseError:
        return []
    return [row["name"] for row in rows]


def weather_schema(conn: sqlite3.Connection, weather_db: Path | None = None) -> dict[str, Any]:
    attached = _attach_weather(conn, weather_db)
    if not attached:
        return {
            "available": False,
            "join_works": False,
            "reason": "data/weather_berlin.db not found or could not be attached",
            "table": None,
            "columns": [],
            "fields": [],
        }

    columns = _weather_columns(conn)
    if "day" not in columns:
        return {
            "available": False,
            "join_works": False,
            "reason": "weather.daily has no day column",
            "table": "daily",
            "columns": columns,
            "fields": [],
        }

    fields = []
    for public_name, candidates in WEATHER_FIELD_CANDIDATES.items():
        found = next((c for c in candidates if c in columns), None)
        if found:
            fields.append({"name": public_name, "column": found})

    joined = conn.execute(WEATHER_JOIN_SQL).fetchone()
    weather_range = conn.execute(
        "SELECT MIN(day) AS first_date, MAX(day) AS last_date, COUNT(*) AS rows, COUNT(DISTINCT day) AS distinct_days FROM weather.daily"
    ).fetchone()
    matched = int(joined["matched_weather_days"] or 0)
    police_days = int(joined["police_days"] or 0)
    return {
        "available": True,
        "join_works": matched > 0,
        "table": "daily",
        "columns": columns,
        "fields": fields,
        "matched_days": matched,
        "police_days": police_days,
        "coverage_pct": round(100 * matched / police_days, 1) if police_days else 0.0,
        "first_date": weather_range["first_date"],
        "last_date": weather_range["last_date"],
        "rows": weather_range["rows"],
        "distinct_days": weather_range["distinct_days"],
    }


def _weather_field_map(schema: dict[str, Any]) -> dict[str, str]:
    return {field["name"]: field["column"] for field in schema.get("fields", [])}


def _load_weather_by_day(conn: sqlite3.Connection, schema: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if not schema.get("available") or "day" not in schema.get("columns", []):
        return {}

    field_map = _weather_field_map(schema)
    select_columns = ["day", *sorted(set(field_map.values()))]
    sql = f"SELECT {', '.join(select_columns)} FROM weather.daily"
    weather: dict[str, dict[str, Any]] = {}
    for row in conn.execute(sql):
        by_public_name = {name: row[column] for name, column in field_map.items()}
        tmax = by_public_name.get("temperature_max")
        tmin = by_public_name.get("temperature_min")
        tmean = by_public_name.get("temperature_mean")
        if tmean is None and tmax is not None and tmin is not None:
            tmean = round((float(tmax) + float(tmin)) / 2, 1)

        payload = {
            "temperature_mean": _round_or_none(tmean),
            "temperature_max": _round_or_none(tmax),
            "temperature_min": _round_or_none(tmin),
            "precipitation": _round_or_none(by_public_name.get("precipitation")),
            "rain": _round_or_none(by_public_name.get("rain")),
            "snow": _round_or_none(by_public_name.get("snow")),
            "wind": _round_or_none(by_public_name.get("wind")),
            "sunshine": _round_or_none(by_public_name.get("sunshine")),
            "cloud_cover": _round_or_none(by_public_name.get("cloud_cover")),
            "condition": by_public_name.get("condition"),
        }
        payload["summary"] = _weather_summary(payload)
        weather[row["day"]] = payload
    return weather


def _round_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value), 1)
    except (TypeError, ValueError):
        return None


def _weather_summary(weather: dict[str, Any]) -> str | None:
    parts = []
    if weather.get("temperature_mean") is not None:
        parts.append(f"{weather['temperature_mean']}°C mean")
    elif weather.get("temperature_max") is not None and weather.get("temperature_min") is not None:
        parts.append(f"{weather['temperature_min']}–{weather['temperature_max']}°C")
    elif weather.get("temperature_max") is not None:
        parts.append(f"{weather['temperature_max']}°C max")
    if weather.get("condition"):
        parts.append(str(weather["condition"]).replace("_", " "))
    if weather.get("precipitation"):
        parts.append(f"{weather['precipitation']} mm precipitation")
    if weather.get("rain"):
        parts.append(f"{weather['rain']} mm rain")
    if weather.get("snow"):
        parts.append(f"{weather['snow']} mm snow")
    if weather.get("wind"):
        parts.append(f"{weather['wind']} km/h wind")
    if weather.get("sunshine"):
        parts.append(f"{weather['sunshine']} sunshine")
    if weather.get("cloud_cover") is not None:
        parts.append(f"{weather['cloud_cover']}% cloud cover")
    return ", ".join(parts) if parts else None


def _top(counter: Counter[str], limit: int = 5) -> list[dict[str, Any]]:
    return [{"name": name, "count": count} for name, count in counter.most_common(limit)]


def _compute_anomalies(cells: list[dict[str, Any]]) -> None:
    groups: dict[tuple[int, int], list[int]] = defaultdict(list)
    for cell in cells:
        groups[(cell["month"], cell["weekday_index"])].append(cell["report_count"])

    stats = {}
    for key, counts in groups.items():
        avg = mean(counts)
        stddev = pstdev(counts) if len(counts) > 1 else 0.0
        stats[key] = (avg, stddev)

    for cell in cells:
        avg, stddev = stats[(cell["month"], cell["weekday_index"])]
        delta = cell["report_count"] - avg
        score = delta / stddev if stddev > 0 else 0.0
        cell["baseline_count"] = round(avg, 2)
        cell["anomaly_delta"] = round(delta, 2)
        cell["anomaly_score"] = round(score, 2)


def _date_range_missing(first_date: str | None, last_date: str | None, days: set[str]) -> list[str]:
    if not first_date or not last_date:
        return []
    current = date.fromisoformat(first_date)
    end = date.fromisoformat(last_date)
    missing = []
    while current <= end:
        iso = current.isoformat()
        if iso not in days:
            missing.append(iso)
        current += timedelta(days=1)
    return missing


def build_daily_mosaic(conn: sqlite3.Connection, weather_db: Path | None = None) -> dict[str, Any]:
    """Return one aggregate object per distinct police-report date."""
    schema = weather_schema(conn, weather_db)
    weather_by_day = _load_weather_by_day(conn, schema)
    stats = conn.execute(DATE_STATS_SQL).fetchone()
    total_rows = conn.execute(TOTAL_ROWS_SQL).fetchone()["total_rows"]

    by_day: dict[str, dict[str, Any]] = {}
    all_districts: Counter[str] = Counter()
    all_tags: Counter[str] = Counter()

    for row in conn.execute(DAILY_REPORTS_SQL):
        report_date = row["report_date"]
        parsed_date = date.fromisoformat(report_date)
        cell = by_day.setdefault(
            report_date,
            {
                "date": report_date,
                "weekday": WEEKDAY_NAMES[parsed_date.weekday()],
                "weekday_short": WEEKDAY_SHORT[parsed_date.weekday()],
                "weekday_index": parsed_date.weekday(),
                "is_weekend": parsed_date.weekday() >= 5,
                "year": parsed_date.year,
                "month": parsed_date.month,
                "month_label": parsed_date.strftime("%b"),
                "season": SEASON_BY_MONTH[parsed_date.month],
                "report_count": 0,
                "district_counts": {},
                "tag_counts": {},
                "top_districts": [],
                "top_tags": [],
                "reports": [],
                "weather": weather_by_day.get(report_date),
            },
        )

        cell["report_count"] += 1
        district = (row["district"] or "").strip()
        if district:
            cell["district_counts"][district] = cell["district_counts"].get(district, 0) + 1
            all_districts[district] += 1

        for tag in tags_from_json(row["tags"]):
            cell["tag_counts"][tag] = cell["tag_counts"].get(tag, 0) + 1
            all_tags[tag] += 1

        if len(cell["reports"]) < 8:
            cell["reports"].append(
                {
                    "id": row["id"],
                    "title": row["title"],
                    "district": district or None,
                    "published_at": row["published_at"],
                    "detail_url": f"/meldung/{row['id']}",
                    "original_url": row["url"],
                }
            )

    cells = list(by_day.values())
    for cell in cells:
        cell["top_districts"] = _top(Counter(cell["district_counts"]), 5)
        cell["top_tags"] = _top(Counter(cell["tag_counts"]), 5)

    cells.sort(key=lambda item: item["date"])
    _compute_anomalies(cells)

    date_days = {cell["date"] for cell in cells}
    missing = _date_range_missing(stats["first_date"], stats["last_date"], date_days)
    weather_conditions = sorted(
        {
            str(cell["weather"]["condition"])
            for cell in cells
            if cell.get("weather") and cell["weather"].get("condition")
        }
    )

    max_count = max((cell["report_count"] for cell in cells), default=0)
    max_abs_anomaly = max((abs(cell["anomaly_score"]) for cell in cells), default=0.0)
    temperatures = [
        cell["weather"]["temperature_mean"]
        for cell in cells
        if cell.get("weather") and cell["weather"].get("temperature_mean") is not None
    ]

    return {
        "meta": {
            "title": "Berlin Daily Grid",
            "subtitle": "Berlin Crime Weather Mosaic",
            "source_note": "Exploratory visualization of scraped public Berlin police press releases; not official crime statistics.",
            "total_rows": int(total_rows or 0),
            "first_date": stats["first_date"],
            "last_date": stats["last_date"],
            "distinct_dates": int(stats["distinct_dates"] or 0),
            "cell_count": len(cells),
            "missing_dates_in_range": len(missing),
            "max_report_count": max_count,
            "max_abs_anomaly": round(max_abs_anomaly, 2),
            "temperature_min": min(temperatures) if temperatures else None,
            "temperature_max": max(temperatures) if temperatures else None,
            "sql": {
                "total_rows": TOTAL_ROWS_SQL,
                "date_stats": DATE_STATS_SQL.strip(),
                "daily_counts": DAILY_COUNTS_SQL.strip(),
                "daily_reports": DAILY_REPORTS_SQL.strip(),
                "weather_join": WEATHER_JOIN_SQL.strip(),
            },
            "weather": schema,
        },
        "filters": {
            "years": sorted({cell["year"] for cell in cells}, reverse=True),
            "districts": [{"name": name, "count": count} for name, count in all_districts.most_common()],
            "tags": [{"name": name, "count": count} for name, count in all_tags.most_common()],
            "weather_conditions": weather_conditions,
            "weekdays": [{"index": i, "name": name, "short": WEEKDAY_SHORT[i]} for i, name in enumerate(WEEKDAY_NAMES)],
        },
        "days": cells,
    }


def inspect_mosaic_inputs(
    db_path: Path | None = None,
    weather_db: Path | None = None,
    top_limit: int = 10,
) -> dict[str, Any]:
    """Return the data audit needed by scripts/inspect_mosaic_data.py."""
    conn = connect_meldungen(db_path)
    try:
        schema = weather_schema(conn, weather_db)
        stats = conn.execute(DATE_STATS_SQL).fetchone()
        total_rows = conn.execute(TOTAL_ROWS_SQL).fetchone()["total_rows"]
        top_days = [dict(row) for row in conn.execute(TOP_DAYS_SQL, (top_limit,))]
        distinct_days = {
            row["date"]
            for row in conn.execute(
                f"SELECT DISTINCT {REPORT_DAY_SQL} AS date FROM meldungen WHERE {REPORT_DAY_SQL} IS NOT NULL"
            )
        }
        missing = _date_range_missing(stats["first_date"], stats["last_date"], distinct_days)
        return {
            "total_rows": int(total_rows or 0),
            "first_date": stats["first_date"],
            "last_date": stats["last_date"],
            "distinct_dates": int(stats["distinct_dates"] or 0),
            "missing_dates": missing,
            "top_days": top_days,
            "weather": schema,
            "sql": {
                "total_rows": TOTAL_ROWS_SQL,
                "date_stats": DATE_STATS_SQL.strip(),
                "top_days": TOP_DAYS_SQL.strip(),
                "weather_join": WEATHER_JOIN_SQL.strip(),
            },
        }
    finally:
        conn.close()


def nice_number(value: float | int | None) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float) and not math.isfinite(value):
        return "n/a"
    return f"{value:,}"
