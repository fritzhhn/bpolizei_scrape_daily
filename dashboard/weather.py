"""Wetterdaten Berlin (Open-Meteo) ↔ Tatdatum."""

from __future__ import annotations

import sqlite3
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

import requests

from scraper.config import DATA_DIR

WEATHER_DB = DATA_DIR / "weather_berlin.db"
BERLIN_LAT, BERLIN_LON = 52.52, 13.405
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

# Schwellen °C (Tagesmaximum)
BIN_LABELS = {
    "heat_wave": "Hitzetag (≥30°C)",
    "hot": "Warm (25–29°C)",
    "mild": "Mild (5–24°C)",
    "cold": "Kalt (0–4°C)",
    "freezing": "Frost (unter 0°C)",
}


def _bin_for_tmax(tmax: float | None) -> str | None:
    if tmax is None:
        return None
    if tmax >= 30:
        return "heat_wave"
    if tmax >= 25:
        return "hot"
    if tmax >= 5:
        return "mild"
    if tmax >= 0:
        return "cold"
    return "freezing"


def init_weather_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(WEATHER_DB)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS daily (
            day TEXT PRIMARY KEY,
            tmax REAL,
            tmin REAL,
            bin TEXT
        )
        """
    )
    conn.commit()
    conn.close()


def fetch_range(start: date, end: date) -> dict[date, dict]:
    """Lädt Tageswetter von Open-Meteo (kostenlos, ohne API-Key)."""
    params = {
        "latitude": BERLIN_LAT,
        "longitude": BERLIN_LON,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "daily": "temperature_2m_max,temperature_2m_min",
        "timezone": "Europe/Berlin",
    }
    r = requests.get(ARCHIVE_URL, params=params, timeout=120)
    r.raise_for_status()
    daily = r.json()["daily"]
    out: dict[date, dict] = {}
    for i, day_s in enumerate(daily["time"]):
        d = date.fromisoformat(day_s)
        tmax = daily["temperature_2m_max"][i]
        tmin = daily["temperature_2m_min"][i]
        out[d] = {"tmax": tmax, "tmin": tmin, "bin": _bin_for_tmax(tmax)}
    return out


def store_weather(days: dict[date, dict]) -> int:
    init_weather_db()
    conn = sqlite3.connect(WEATHER_DB)
    n = 0
    for d, w in days.items():
        conn.execute(
            "INSERT OR REPLACE INTO daily (day, tmax, tmin, bin) VALUES (?, ?, ?, ?)",
            (d.isoformat(), w["tmax"], w["tmin"], w["bin"]),
        )
        n += 1
    conn.commit()
    conn.close()
    return n


def ensure_weather_cached(start: date, end: date) -> None:
    today = date.today()
    end = min(end, today)
    if start > end:
        return
    init_weather_db()
    conn = sqlite3.connect(WEATHER_DB)
    have = {
        date.fromisoformat(row[0])
        for row in conn.execute("SELECT day FROM daily").fetchall()
    }
    conn.close()

    missing_ranges: list[tuple[date, date]] = []
    cur = start
    while cur <= end:
        if cur not in have:
            range_start = cur
            while cur <= end and cur not in have:
                cur += timedelta(days=1)
            missing_ranges.append((range_start, cur - timedelta(days=1)))
        else:
            cur += timedelta(days=1)

    for rs, re in missing_ranges:
        re = min(re, today)
        chunk = rs
        while chunk <= re:
            chunk_end = min(chunk + timedelta(days=365), re, today)
            store_weather(fetch_range(chunk, chunk_end))
            chunk = chunk_end + timedelta(days=1)


def get_weather(day: date) -> dict | None:
    init_weather_db()
    conn = sqlite3.connect(WEATHER_DB)
    row = conn.execute(
        "SELECT tmax, tmin, bin FROM daily WHERE day = ?", (day.isoformat(),)
    ).fetchone()
    conn.close()
    if not row:
        return None
    return {"tmax": row[0], "tmin": row[1], "bin": row[2]}


def build_weather_analysis(incident_dates: list[date]) -> dict:
    """Vergleicht Tat-Häufigkeit nach Wetter-Bins mit Basisrate (Tage im Archiv)."""
    today = date.today()
    incident_dates = [d for d in incident_dates if d <= today]
    if not incident_dates:
        return {"ready": False, "reason": "Keine Tatdaten"}

    start, end = min(incident_dates), max(incident_dates)
    ensure_weather_cached(start, end)

    init_weather_db()
    conn = sqlite3.connect(WEATHER_DB)
    all_days = conn.execute(
        "SELECT day, tmax, tmin, bin FROM daily WHERE day >= ? AND day <= ?",
        (start.isoformat(), end.isoformat()),
    ).fetchall()
    conn.close()

    days_by_bin: Counter[str] = Counter()
    for day_s, tmax, tmin, b in all_days:
        if b:
            days_by_bin[b] += 1

    incidents_by_bin: Counter[str] = Counter()
    matched = 0
    for d in incident_dates:
        w = get_weather(d)
        if w and w["bin"]:
            incidents_by_bin[w["bin"]] += 1
            matched += 1

    if matched < 30:
        return {"ready": False, "reason": "Zu wenig überlappende Wetter-/Tatdaten"}

    bins_out = []
    baseline_days = sum(days_by_bin.values()) or 1
    baseline_rate = matched / baseline_days  # incidents per day average in matched set

    for key in ("freezing", "cold", "mild", "hot", "heat_wave"):
        day_count = days_by_bin.get(key, 0)
        inc_count = incidents_by_bin.get(key, 0)
        if day_count < 5:
            continue
        rate = inc_count / day_count
        rel = round(rate / baseline_rate, 2) if baseline_rate else 1.0
        bins_out.append({
            "bin": key,
            "label": BIN_LABELS[key],
            "incidents": inc_count,
            "days": day_count,
            "rate_per_day": round(rate, 3),
            "relative": rel,
            "height_pct": min(100, round(50 * rel, 1)),
        })

    bins_out.sort(key=lambda x: -x["relative"])
    top = bins_out[0] if bins_out else None
    heat_inc = incidents_by_bin.get("heat_wave", 0) + incidents_by_bin.get("hot", 0)
    cold_inc = incidents_by_bin.get("freezing", 0) + incidents_by_bin.get("cold", 0)
    heat_days = days_by_bin.get("heat_wave", 0) + days_by_bin.get("hot", 0)
    cold_days = days_by_bin.get("freezing", 0) + days_by_bin.get("cold", 0)

    return {
        "ready": True,
        "matched": matched,
        "total_incidents": len(incident_dates),
        "period": f"{start.isoformat()} – {end.isoformat()}",
        "bins": bins_out,
        "top_bin": top,
        "heat": {
            "incidents": heat_inc,
            "days": heat_days,
            "relative": round(
                (heat_inc / heat_days) / baseline_rate, 2
            ) if heat_days and baseline_rate else None,
        },
        "cold": {
            "incidents": cold_inc,
            "days": cold_days,
            "relative": round(
                (cold_inc / cold_days) / baseline_rate, 2
            ) if cold_days and baseline_rate else None,
        },
        "source": "Open-Meteo (Berlin), Tatdatum aus Meldungstext",
    }
