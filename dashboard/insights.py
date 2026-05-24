"""Auffällige Dashboard-Visualisierungen (Tatzeit, Tatdatum, Muster)."""

from __future__ import annotations

from collections import Counter
from datetime import datetime

from scraper.config import ARCHIV_START_YEAR
from scraper.parse import tags_from_json

from dashboard.helpers import MONTH_NAMES, YEAR_SQL, fill_years_range
from dashboard.interpretation import build_interpretation
from dashboard.incident_time import (
    _fetch_rows,
    _parse_rows,
    build_incident_heatmap,
    build_incident_hour_rhythm,
    build_incident_weekday,
    build_incident_yoy,
)
from dashboard.socio_stats import build_socio_findings, build_socio_pack

DATE_EXPR = "COALESCE(published_at, meldung_date || 'T12:00:00')"
DATE_OK = f"{DATE_EXPR} IS NOT NULL AND length(COALESCE(published_at, meldung_date)) >= 10"


def _pct(count: int, total: int) -> float:
    return round(100 * count / total, 1) if total else 0.0


def build_archive_gap(conn) -> dict:
    """Archiv-Lücke auf berlin.de (Metadaten, nicht Tatdatum)."""
    rows = conn.execute(
        f"""
        SELECT {YEAR_SQL} AS year, COUNT(*) AS count
        FROM meldungen
        WHERE COALESCE(published_at, meldung_date) IS NOT NULL
          AND {YEAR_SQL} BETWEEN ? AND ?
        GROUP BY year ORDER BY year
        """,
        (ARCHIV_START_YEAR, datetime.now().year),
    ).fetchall()
    by_year = fill_years_range(rows, ARCHIV_START_YEAR, datetime.now().year)
    early = sum(r["count"] for r in by_year if r["year"] <= 2019)
    modern = [r for r in by_year if r["year"] >= 2020]
    modern_avg = round(sum(r["count"] for r in modern) / len(modern)) if modern else 0
    max_c = max((r["count"] for r in by_year), default=1)
    for r in by_year:
        r["height_pct"] = round(100 * r["count"] / max_c, 1)
        r["era"] = "early" if r["year"] <= 2019 else "modern"
    return {
        "years": by_year,
        "early_total": early,
        "modern_avg": modern_avg,
        "ratio": round(modern_avg / max(early / 6, 1)) if early else modern_avg,
        "max_count": max_c,
    }


def build_tag_bubbles(conn, where: str = "", params: list | None = None, limit: int = 9) -> list[dict]:
    params = params or []
    tags: Counter[str] = Counter()
    if where:
        sql = f"SELECT tags FROM meldungen {where} AND tags IS NOT NULL AND tags != '[]'"
    else:
        sql = "SELECT tags FROM meldungen WHERE tags IS NOT NULL AND tags != '[]'"
    for row in conn.execute(sql, params):
        for t in tags_from_json(row["tags"]):
            tags[t] += 1
    top = tags.most_common(limit)
    if not top:
        return []
    max_c = top[0][1]
    palette = ["#1e4d8c", "#2563eb", "#3b82f6", "#60a5fa", "#93c5fd",
               "#b45309", "#ea580c", "#dc2626", "#7c3aed"]
    return [
        {
            "name": name,
            "count": count,
            "size_px": 44 + round(76 * (count / max_c)),
            "color": palette[i % len(palette)],
            "filter_key": "tag",
            "filter_val": name,
        }
        for i, (name, count) in enumerate(top)
    ]


def build_district_share(conn, where: str = "", params: list | None = None, limit: int = 8) -> dict:
    params = params or []
    if where:
        base = f"FROM meldungen {where} AND district IS NOT NULL AND district != ''"
    else:
        base = "FROM meldungen WHERE district IS NOT NULL AND district != ''"
    rows = conn.execute(
        f"SELECT district, COUNT(*) AS count {base} GROUP BY district ORDER BY count DESC LIMIT ?",
        [*params, limit],
    ).fetchall()
    total_top = sum(r["count"] for r in rows)
    all_count = conn.execute(f"SELECT COUNT(*) {base}", params).fetchone()[0]
    colors = ["#1e4d8c", "#2563eb", "#3b82f6", "#60a5fa", "#93c5fd", "#b45309", "#ea580c", "#dc2626"]
    out = []
    offset = 0.0
    for i, r in enumerate(rows):
        pct = _pct(r["count"], all_count)
        slice_pct = _pct(r["count"], total_top)
        out.append({
            "district": r["district"],
            "count": r["count"],
            "pct_all": pct,
            "slice_pct": slice_pct,
            "color": colors[i % len(colors)],
        })
        offset += slice_pct
    pos = 0.0
    stops = []
    for s in out:
        end = pos + s["slice_pct"]
        stops.append(f"{s['color']} {pos}% {end}%")
        pos = end
    gradient = f"conic-gradient({', '.join(stops)})" if stops else "var(--line)"
    return {"slices": out, "total": all_count, "top_sum": total_top, "gradient": gradient}


def build_all_insights(conn, where: str = "", params: list | None = None) -> dict:
    params = list(params or [])
    rows = _fetch_rows(conn, where, params)
    incident_dates, _ = _parse_rows(rows)

    incident_hour = build_incident_hour_rhythm(conn, where, params)
    incident_weekday = build_incident_weekday(conn, where, params)
    heatmap = build_incident_heatmap(conn, where, params)
    socio = build_socio_pack(conn, where, params, incident_dates=incident_dates)
    interpretation = build_interpretation(
        conn, where, params,
        incident_hour=incident_hour,
        incident_weekday=incident_weekday,
        heatmap=heatmap,
        socio=socio,
    )
    socio_findings = build_socio_findings(socio)
    return {
        "interpretation": interpretation,
        "heatmap": heatmap,
        "incident_hour": incident_hour,
        "incident_weekday": incident_weekday,
        "socio": socio,
        "socio_findings": socio_findings,
        "archive_gap": build_archive_gap(conn),
        "tag_bubbles": build_tag_bubbles(conn, where, params),
        "yoy_months": build_incident_yoy(conn, where, params),
        "district_share": build_district_share(conn, where, params),
    }
