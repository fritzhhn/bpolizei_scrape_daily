"""Sozialpolitisch relevante Auswertungen: Gewalt gegen Frauen, Bezirk & Einkommen."""

from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter
from pathlib import Path

from scraper.config import DATA_DIR
from scraper.parse import tags_from_json

SOCIO_JSON = DATA_DIR / "berlin_district_socio.json"

# Heuristik — keine amtliche Femizid-Statistik
FEMICIDE_STRONG = re.compile(
    r"\b(femizid|femicide)\b",
    re.IGNORECASE,
)
FEMICIDE_CONTEXT = re.compile(
    r"\b("
    r"häusliche[r\s]?gewalt|partnerschaftliche[r\s]?gewalt|"
    r"lebensgefährtin|ehefrau|ehemann.*töt|partner.*töt|"
    r"frau.*(?:getötet|ermordet|erstochen|erschossen)|"
    r"(?:getötet|ermordet|erstochen).*frau|"
    r"stalker|stalking|"
    r"gewalt gegen frauen"
    r")\b",
    re.IGNORECASE,
)
FEMALE_VICTIM = re.compile(
    r"\b(frau|weiblich|mutter|tochter|ehefrau|lebensgefährtin|"
    r"jugendliche|mädchen|schülerin)\b",
    re.IGNORECASE,
)
VIOLENCE_TAGS = {"Tötungsdelikte", "Mord", "Kriminalität"}


def _load_district_socio() -> dict:
    if not SOCIO_JSON.exists():
        return {}
    return json.loads(SOCIO_JSON.read_text(encoding="utf-8")).get("districts", {})


def _fetch_for_socio(conn, where: str, params: list) -> list:
    cols = "id, title, body_text, tags, district, published_at, meldung_date"
    if where:
        sql = f"SELECT {cols} FROM meldungen {where} AND body_text IS NOT NULL"
    else:
        sql = f"SELECT {cols} FROM meldungen WHERE body_text IS NOT NULL"
    if conn.row_factory is None:
        conn.row_factory = sqlite3.Row
    return conn.execute(sql, params).fetchall()


def classify_gender_violence(row) -> str | None:
    """Returns 'strong', 'likely', or None."""
    text = f"{row['title'] or ''}\n{row['body_text'] or ''}"
    tags = set(tags_from_json(row["tags"]))
    if FEMICIDE_STRONG.search(text):
        return "strong"
    has_violence_tag = bool(tags & VIOLENCE_TAGS) or "Tötung" in text
    if FEMICIDE_CONTEXT.search(text):
        return "likely"
    if has_violence_tag and FEMALE_VICTIM.search(text):
        if re.search(r"\b(getötet|ermordet|tötungsdelikt|leichent|stich|schuss)\b", text, re.I):
            return "likely"
    return None


def build_gender_violence_stats(conn, where: str = "", params: list | None = None) -> dict:
    params = params or []
    rows = _fetch_for_socio(conn, where, params)
    strong = likely = 0
    by_year: Counter[int] = Counter()
    samples: list[dict] = []

    for row in rows:
        level = classify_gender_violence(row)
        if not level:
            continue
        if level == "strong":
            strong += 1
        else:
            likely += 1
        pub = row["published_at"] or row["meldung_date"] or ""
        if len(pub) >= 4 and pub[:4].isdigit():
            by_year[int(pub[:4])] += 1
        if len(samples) < 3:
            samples.append({"id": row["id"], "title": (row["title"] or "")[:80], "level": level})

    total = strong + likely
    totungs = sum(
        1 for row in rows
        if "Tötungsdelikte" in tags_from_json(row["tags"])
        or (row["title"] and "tötung" in row["title"].lower())
    )

    return {
        "ready": total > 0,
        "strong": strong,
        "likely": likely,
        "total": total,
        "totungs_tags": totungs,
        "share_of_totungs_pct": round(100 * total / totungs, 1) if totungs else 0,
        "by_year": sorted(by_year.items()),
        "samples": samples,
        "caveat": (
            "Heuristik aus Pressemitteilungen — kein offizielles Femizid-Register. "
            "Viele Fälle werden nicht öffentlich oder ohne Geschlechtsbezug gemeldet."
        ),
    }


def build_income_correlation(conn, where: str = "", params: list | None = None) -> dict:
    socio = _load_district_socio()
    if not socio:
        return {"ready": False}

    params = params or []
    if where:
        sql = f"""
            SELECT district, COUNT(*) AS c
            FROM meldungen {where}
              AND district IS NOT NULL AND district != ''
              AND district NOT IN ('bezirksübergreifend', 'berlinweit', 'bundesweit')
            GROUP BY district
        """
    else:
        sql = """
            SELECT district, COUNT(*) AS c
            FROM meldungen
            WHERE district IS NOT NULL AND district != ''
              AND district NOT IN ('bezirksübergreifend', 'berlinweit', 'bundesweit')
            GROUP BY district
        """
    rows = conn.execute(sql, params).fetchall()
    points = []
    for district, count in rows:
        info = socio.get(district)
        if not info:
            continue
        points.append({
            "district": district,
            "count": count,
            "income_index": info["income_index"],
            "unemployment_pct": info["unemployment_pct"],
            "label": info.get("label", ""),
        })

    if len(points) < 4:
        return {"ready": False}

    points.sort(key=lambda p: p["income_index"])
    # Korrelation Pearson (einfach)
    n = len(points)
    xs = [p["income_index"] for p in points]
    ys = [p["count"] for p in points]
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den_x = sum((x - mx) ** 2 for x in xs) ** 0.5
    den_y = sum((y - my) ** 2 for y in ys) ** 0.5
    r = round(num / (den_x * den_y), 2) if den_x and den_y else 0

    low_income = [p for p in points if p["income_index"] < 65]
    high_income = [p for p in points if p["income_index"] >= 80]
    low_avg = round(sum(p["count"] for p in low_income) / len(low_income)) if low_income else 0
    high_avg = round(sum(p["count"] for p in high_income) / len(high_income)) if high_income else 0

    return {
        "ready": True,
        "points": points,
        "correlation_r": r,
        "low_income_avg": low_avg,
        "high_income_avg": high_avg,
        "top_volume": max(points, key=lambda p: p["count"]),
        "poorest_high_volume": min(points, key=lambda p: p["income_index"]),
        "source": SOCIO_JSON.name,
        "caveat": (
            "Öffentliche Bezirks-Kennzahen (Näherung) × Meldungsanzahl — "
            "nicht Kriminalität pro Kopf, da Meldungen ohne Einwohnerzahl normiert sind."
        ),
    }


def build_socio_pack(
    conn,
    where: str = "",
    params: list | None = None,
    incident_dates: list | None = None,
) -> dict:
    from dashboard.weather import build_weather_analysis

    gender = build_gender_violence_stats(conn, where, params)
    income = build_income_correlation(conn, where, params)
    weather = (
        build_weather_analysis(incident_dates)
        if incident_dates
        else {"ready": False, "reason": "Keine Tatdaten"}
    )
    return {"gender_violence": gender, "income": income, "weather": weather}


def build_socio_findings(socio: dict) -> list[dict]:
    """Lesbare Karten für sozialpolitische Auswertungen."""
    findings: list[dict] = []
    w = socio.get("weather", {})
    g = socio.get("gender_violence", {})
    inc = socio.get("income", {})

    if w.get("ready"):
        top = w.get("top_bin")
        heat = w.get("heat", {})
        cold = w.get("cold", {})
        if top and top["relative"] >= 1.1:
            findings.append({
                "icon": "🌡️",
                "title": f"Wetter: {top['label']}",
                "body": (
                    f"An Tagen mit „{top['label']}“ ereignen sich laut Textauswertung "
                    f"<strong>{top['relative']}×</strong> so viele gemeldete Taten pro Tag wie im Durchschnitt "
                    f"({top['incidents']} Taten an {top['days']} solchen Tagen). "
                    "Extreme Temperaturen können Aggression, Alkoholkonsum im Freien oder "
                    "längere Aufenthalte draußen begünstigen — Kausalität ist nicht bewiesen."
                ),
                "strength": "high" if top["relative"] >= 1.25 else "medium",
            })
        if heat.get("relative") and heat["relative"] >= 1.1:
            findings.append({
                "icon": "☀️",
                "title": "Hitze und Meldungen",
                "body": (
                    f"Warme und heiße Tage (≥25°C): <strong>{heat['relative']}×</strong> "
                    f"Taten pro Tag vs. Schnitt "
                    f"({heat['incidents']} Fälle an {heat['days']} Hitzetagen). "
                    "Passt zu Debatten über Sommergewalt und überforderte öffentliche Räume."
                ),
                "strength": "medium",
            })
        if cold.get("relative") and cold["relative"] >= 1.1:
            findings.append({
                "icon": "❄️",
                "title": "Kälte und Meldungen",
                "body": (
                    f"Kalte/Frosttage: <strong>{cold['relative']}×</strong> Taten pro Tag "
                    f"({cold['incidents']} Fälle). Kälte kann Einbrüche, Streit in Wohnungen "
                    "oder Sichtbarkeitspolizeiarbeit beeinflussen."
                ),
                "strength": "medium",
            })

    if g.get("ready") and g["total"] > 0:
        findings.append({
            "icon": "⚠️",
            "title": "Gewalt gegen Frauen in Meldungen",
            "body": (
                f"Etwa <strong>{g['total']}</strong> Meldungen mit Hinweisen auf tödliche "
                f"oder schwere Gewalt gegen Frauen / häusliche Gewalt "
                f"({g['strong']} eindeutig, {g['likely']} wahrscheinlich). "
                f"Das sind grob <strong>{g['share_of_totungs_pct']}%</strong> der Tötungs-Meldungen — "
                f"weit unter realer Dunkelziffer. {g['caveat']}"
            ),
            "strength": "high",
        })

    if inc.get("ready"):
        r = inc["correlation_r"]
        direction = "mehr" if r < -0.2 else ("weniger" if r > 0.2 else "ähnlich viele")
        findings.append({
            "icon": "🏘️",
            "title": "Bezirk und Einkommen (Näherung)",
            "body": (
                f"Bezirke mit niedrigerem Median-Einkommen haben im Schnitt "
                f"<strong>{inc['low_income_avg']}</strong> Meldungen, wohlhabendere "
                f"<strong>{inc['high_income_avg']}</strong> "
                f"(Korrelation r={r}). "
                f"Mehr Meldungen bedeutet nicht automatisch mehr Kriminalität — "
                f"auch Polizeipräsenz und Medieninteresse spielen mit. {inc['caveat']}"
            ),
            "strength": "medium" if abs(r) >= 0.3 else "low",
        })

    return findings
