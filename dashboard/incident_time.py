"""Tatzeit und Tatdatum aus Meldungstext extrahieren."""

from __future__ import annotations

import re
from collections import Counter
from datetime import date, datetime, timedelta

from scraper.config import ARCHIV_START_YEAR

from dashboard.helpers import MONTH_NAMES, SEASON_NAMES, WEEKDAY_NAMES, _fill_month_gaps, _fill_week_gaps

WEEKDAY_DE = {
    "montag": 0, "dienstag": 1, "mittwoch": 2, "donnerstag": 3,
    "freitag": 4, "samstag": 5, "sonntag": 6,
}
WEEKDAY_LABELS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]

MONTH_DE = {
    "januar": 1, "februar": 2, "märz": 3, "maerz": 3, "april": 4,
    "mai": 5, "juni": 6, "juli": 7, "august": 8, "september": 9,
    "oktober": 10, "november": 11, "dezember": 12,
}

INCIDENT_AGAINST_RE = re.compile(
    r"\bgegen\s+(\d{1,2})(?:[:.](\d{2}))?\s*Uhr\b",
    re.IGNORECASE,
)
WEEKDAY_IN_TEXT_RE = re.compile(
    r"\b(am\s+)?(Montag|Dienstag|Mittwoch|Donnerstag|Freitag|Samstag|Sonntag)\b",
    re.IGNORECASE,
)
GESTERN_RE = re.compile(r"\bgestern\b", re.IGNORECASE)
HEUTE_RE = re.compile(r"\bheute\b", re.IGNORECASE)
DATE_DOTTED_RE = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b")
DATE_GERMAN_RE = re.compile(
    r"\b(\d{1,2})\.\s*"
    r"(Januar|Februar|März|Maerz|April|Mai|Juni|Juli|August|September|Oktober|November|Dezember)"
    r"(?:\s+(\d{4}))?\b",
    re.IGNORECASE,
)


def _reference_date(published_at: str | None, meldung_date: str | None) -> datetime | None:
    raw = published_at or (f"{meldung_date}T12:00:00" if meldung_date else None)
    if not raw or len(raw) < 10:
        return None
    try:
        return datetime.fromisoformat(raw[:19])
    except ValueError:
        return None


def _weekday_before(ref: datetime, target_dow: int) -> date:
    d = ref.date()
    for _ in range(7):
        if d.weekday() == target_dow:
            return d
        d -= timedelta(days=1)
    return ref.date()


def extract_incident_date(
    body: str | None,
    published_at: str | None,
    meldung_date: str | None,
) -> date | None:
    """Tatdatum aus Text; Referenz nur für „gestern/heute/Wochentag“."""
    if not body:
        return None

    m = DATE_DOTTED_RE.search(body)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return date(y, mo, d)
        except ValueError:
            pass

    m = DATE_GERMAN_RE.search(body)
    if m:
        d = int(m.group(1))
        mo = MONTH_DE.get(m.group(2).lower().replace("ä", "a").replace("ö", "o"))
        ref = _reference_date(published_at, meldung_date)
        y = int(m.group(3)) if m.group(3) else (ref.year if ref else None)
        if mo and y:
            try:
                return date(y, mo, d)
            except ValueError:
                pass

    ref = _reference_date(published_at, meldung_date)
    if not ref:
        return None
    if GESTERN_RE.search(body):
        return (ref - timedelta(days=1)).date()
    if HEUTE_RE.search(body):
        return ref.date()

    m = WEEKDAY_IN_TEXT_RE.search(body)
    if m:
        wd = WEEKDAY_DE.get(m.group(2).lower())
        if wd is not None:
            return _weekday_before(ref, wd)
    return None


def extract_incident_hour(body: str | None) -> int | None:
    if not body:
        return None
    m = INCIDENT_AGAINST_RE.search(body)
    if not m:
        return None
    h = int(m.group(1))
    return h if 0 <= h <= 23 else None


def _fetch_rows(conn, where: str, params: list) -> list:
    if where:
        sql = f"""
            SELECT body_text, published_at, meldung_date
            FROM meldungen {where}
              AND body_text IS NOT NULL AND length(body_text) > 30
        """
    else:
        sql = """
            SELECT body_text, published_at, meldung_date
            FROM meldungen
            WHERE body_text IS NOT NULL AND length(body_text) > 30
        """
    return conn.execute(sql, params).fetchall()


def _parse_rows(rows: list) -> tuple[list[date], dict]:
    """Returns (incident_dates, stats)."""
    dates: list[date] = []
    for row in rows:
        d = extract_incident_date(row["body_text"], row["published_at"], row["meldung_date"])
        if d:
            dates.append(d)
    return dates, {
        "total": len(rows),
        "parsed": len(dates),
        "coverage_pct": round(100 * len(dates) / len(rows), 1) if rows else 0,
    }


def build_incident_hour_rhythm(conn, where: str = "", params: list | None = None) -> dict:
    params = params or []
    rows = _fetch_rows(conn, where, params)
    total = len(rows)
    hours: Counter[int] = Counter()
    for row in rows:
        h = extract_incident_hour(row["body_text"])
        if h is not None:
            hours[h] += 1

    parsed = sum(hours.values())
    peak = max(hours, key=hours.get) if hours else None
    max_c = hours[peak] if peak is not None else 1
    evening = sum(hours.get(h, 0) for h in range(18, 24))

    bars = [
        {
            "hour": h,
            "label": f"{h:02d}",
            "count": hours.get(h, 0),
            "height_pct": round(100 * hours.get(h, 0) / max_c, 1) if max_c else 0,
            "is_peak": peak == h,
            "is_evening": 18 <= h <= 23,
        }
        for h in range(24)
    ]

    return {
        "bars": bars,
        "peak": {"hour": peak, "label": f"{peak:02d}"} if peak is not None else None,
        "parsed": parsed,
        "total": total,
        "coverage_pct": round(100 * parsed / total, 1) if total else 0,
        "evening_pct": round(100 * evening / parsed, 1) if parsed else 0,
    }


def build_incident_weekday(conn, where: str = "", params: list | None = None) -> dict:
    params = params or []
    rows = _fetch_rows(conn, where, params)
    total = len(rows)
    days: Counter[int] = Counter()
    for row in rows:
        d = extract_incident_date(row["body_text"], row["published_at"], row["meldung_date"])
        if d:
            days[d.weekday()] += 1

    parsed = sum(days.values())
    peak = max(days, key=days.get) if days else None
    max_c = days[peak] if peak is not None else 1
    bars = [
        {
            "dow": d,
            "label": WEEKDAY_LABELS[d],
            "count": days.get(d, 0),
            "height_pct": round(100 * days.get(d, 0) / max_c, 1) if max_c else 0,
            "is_peak": peak == d,
        }
        for d in range(7)
    ]
    weekend = days.get(5, 0) + days.get(6, 0)
    return {
        "bars": bars,
        "peak": {"dow": peak, "label": WEEKDAY_LABELS[peak]} if peak is not None else None,
        "parsed": parsed,
        "total": total,
        "coverage_pct": round(100 * parsed / total, 1) if total else 0,
        "weekend_pct": round(100 * weekend / parsed, 1) if parsed else 0,
    }


def build_incident_heatmap(conn, where: str = "", params: list | None = None) -> dict:
    params = params or []
    rows = _fetch_rows(conn, where, params)
    dates, stats = _parse_rows(rows)
    grid: Counter[tuple[int, int]] = Counter()
    for d in dates:
        grid[(d.year, d.month)] += 1

    end_year = datetime.now().year
    years = list(range(ARCHIV_START_YEAR, end_year + 1))
    max_count = max(grid.values()) if grid else 0
    cells: list[dict] = []
    heat_rows: list[dict] = []
    for y in years:
        months_row = []
        for m in range(1, 13):
            c = grid.get((y, m), 0)
            cell = {
                "year": y,
                "month": m,
                "label": MONTH_NAMES[m - 1],
                "count": c,
                "intensity": round(c / max_count, 3) if max_count else 0,
            }
            cells.append(cell)
            months_row.append(cell)
        heat_rows.append({"year": y, "months": months_row})

    peak = max(cells, key=lambda x: x["count"]) if cells and max_count else None
    return {
        "years": years,
        "months": MONTH_NAMES,
        "rows": heat_rows,
        "max_count": max_count,
        "peak": peak,
        **stats,
    }


def build_incident_timeline(
    conn,
    granularity: str,
    where: str = "",
    params: list | None = None,
) -> tuple[list[dict], dict]:
    """Zeitreihe nach Tatdatum aus Text."""
    params = params or []
    rows = _fetch_rows(conn, where, params)
    dates, stats = _parse_rows(rows)
    meta: dict = {
        "granularity": granularity,
        "coverage_pct": stats["coverage_pct"],
        "parsed": stats["parsed"],
        "total": stats["total"],
    }

    if not dates:
        meta.update({"label": "Keine Tatdaten im Text erkannt", "max_count": 1, "total_in_chart": 0})
        return [], meta

    if granularity == "month":
        counts: Counter[str] = Counter()
        for d in dates:
            counts[f"{d.year:04d}-{d.month:02d}"] += 1
        bars = _fill_month_gaps([{"period": p, "count": c} for p, c in sorted(counts.items())])
        meta["label"] = "Tatdatum — Monate"
        meta["bar_width"] = 10

    elif granularity == "week":
        counts = Counter()
        for d in dates:
            y, w, _ = d.isocalendar()
            counts[f"{y:04d}-W{w:02d}"] += 1
        bars = _fill_week_gaps([{"period": p, "count": c} for p, c in sorted(counts.items())])
        meta["label"] = "Tatdatum — Kalenderwochen"
        meta["bar_width"] = 4

    elif granularity == "season":
        season_counts: Counter[str] = Counter()
        for d in dates:
            m = d.month
            if m in (12, 1, 2):
                season_counts["Winter"] += 1
            elif m in (3, 4, 5):
                season_counts["Frühling"] += 1
            elif m in (6, 7, 8):
                season_counts["Sommer"] += 1
            else:
                season_counts["Herbst"] += 1
        order = {s: i for i, s in enumerate(SEASON_NAMES)}
        bars = sorted(
            [{"period": s, "label": s, "count": season_counts[s]} for s in SEASON_NAMES if season_counts[s]],
            key=lambda x: order[x["period"]],
        )
        meta["label"] = "Tatdatum — Jahreszeiten"
        meta["bar_width"] = 48

    elif granularity == "weekday":
        dow_counts: Counter[int] = Counter(d.weekday() for d in dates)
        bars = [
            {"period": str(i), "label": WEEKDAY_NAMES[i], "count": dow_counts.get(i, 0)}
            for i in range(7)
        ]
        meta["label"] = "Tatdatum — Wochentag"
        meta["bar_width"] = 40

    elif granularity == "month_of_year":
        month_counts: Counter[int] = Counter(d.month for d in dates)
        bars = [
            {"period": f"{m:02d}", "label": MONTH_NAMES[m - 1], "count": month_counts.get(m, 0)}
            for m in range(1, 13)
        ]
        meta["label"] = "Tatdatum — Monat im Jahr (Jan–Dez)"
        meta["bar_width"] = 36

    else:
        return build_incident_timeline(conn, "month", where, params)

    peak = max(bars, key=lambda b: b["count"])
    meta["peak"] = peak
    meta["max_count"] = peak["count"] or 1
    meta["total_in_chart"] = sum(b["count"] for b in bars)
    for b in bars:
        b["height_pct"] = round(100 * b["count"] / meta["max_count"], 1)

    return bars, meta


def build_incident_yoy(conn, where: str = "", params: list | None = None, n_years: int = 4) -> dict:
    params = params or []
    rows = _fetch_rows(conn, where, params)
    dates, _ = _parse_rows(rows)
    end_year = datetime.now().year - 1
    start_year = end_year - n_years + 1
    grid: Counter[tuple[int, int]] = Counter()
    for d in dates:
        if start_year <= d.year <= end_year:
            grid[(d.year, d.month)] += 1

    colors = ["#1e4d8c", "#b45309", "#059669", "#7c3aed"]
    global_max = 1
    series = []
    for i, y in enumerate(range(start_year, end_year + 1)):
        pts = []
        for m in range(1, 13):
            c = grid.get((y, m), 0)
            global_max = max(global_max, c)
            pts.append({"month": m, "label": MONTH_NAMES[m - 1], "count": c})
        series.append({"year": y, "points": pts, "color": colors[i % len(colors)]})

    for s in series:
        for p in s["points"]:
            p["height_pct"] = round(100 * p["count"] / global_max, 1)

    return {"series": series, "max_count": global_max, "years_label": f"{start_year}–{end_year}"}


def incident_highlights(
    conn,
    where: str = "",
    params: list | None = None,
    incident_hour: dict | None = None,
    incident_weekday: dict | None = None,
) -> list[dict]:
    """Rekord-Kacheln nur für Tatzeit/-datum."""
    params = params or []
    rows = _fetch_rows(conn, where, params)
    dates, date_stats = _parse_rows(rows)

    cards: list[dict] = []
    if dates:
        month_counts: Counter[str] = Counter(f"{d.year:04d}-{d.month:02d}" for d in dates)
        peak_ym = month_counts.most_common(1)[0]
        y, m = peak_ym[0].split("-")
        cards.append({
            "kind": "peak",
            "label": "Stärkster Monat (Tat)",
            "value": f"{MONTH_NAMES[int(m) - 1]} {y}",
            "detail": f"{peak_ym[1]} Taten mit erkanntem Datum",
            "icon": "📈",
        })
        day_counts: Counter[str] = Counter(d.isoformat() for d in dates)
        peak_day = day_counts.most_common(1)[0]
        d = peak_day[0]
        cards.append({
            "kind": "day",
            "label": "Stärkster Tag (Tat)",
            "value": f"{d[8:10]}.{d[5:7]}.{d[:4]}",
            "detail": f"{peak_day[1]} Taten an einem Tag",
            "icon": "🔥",
        })

    incident_h = incident_hour or build_incident_hour_rhythm(conn, where, params)
    if incident_h.get("peak"):
        cards.append({
            "kind": "incident-hour",
            "label": "Häufigste Tatzeit",
            "value": f"{incident_h['peak']['label']}:00",
            "detail": f"„gegen … Uhr“ in {incident_h['coverage_pct']}% der Texte",
            "icon": "🕐",
        })

    incident_wd = incident_weekday or build_incident_weekday(conn, where, params)
    if incident_wd.get("parsed"):
        cards.append({
            "kind": "weekend",
            "label": "Tat am Wochenende",
            "value": f"{incident_wd['weekend_pct']}%",
            "detail": f"Sa/So ({incident_wd['coverage_pct']}% mit Tatdatum)",
            "icon": "📅",
        })

    if date_stats["parsed"]:
        cards.append({
            "kind": "coverage",
            "label": "Tatdatum erkannt",
            "value": f"{date_stats['coverage_pct']}%",
            "detail": f"{date_stats['parsed']} von {date_stats['total']} Meldungstexten",
            "icon": "📋",
        })

    return cards
