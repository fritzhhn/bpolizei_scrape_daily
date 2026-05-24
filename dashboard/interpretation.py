"""Lesbare Erkenntnisse aus Tatzeit- und Tatdatum-Mustern."""

from __future__ import annotations

from collections import Counter
from datetime import datetime

from dashboard.helpers import MONTH_NAMES
from dashboard.incident_time import (
    WEEKDAY_LABELS,
    _fetch_rows,
    _parse_rows,
    extract_incident_hour,
)

EVENING_HOURS = range(18, 24)
NIGHT_HOURS = list(range(22, 24)) + list(range(0, 6))
DAYTIME_HOURS = range(8, 18)


def _pct(part: int, whole: int) -> float:
    return round(100 * part / whole, 1) if whole else 0.0


def _ratio_vs_uniform(observed: int, total: int, buckets: int) -> float:
    """>1 = häufiger als bei gleichmäßiger Verteilung."""
    if not total or buckets <= 0:
        return 1.0
    expected = total / buckets
    return round(observed / expected, 2) if expected else 1.0


def _season_for_month(m: int) -> str:
    if m in (12, 1, 2):
        return "Winter"
    if m in (3, 4, 5):
        return "Frühling"
    if m in (6, 7, 8):
        return "Sommer"
    return "Herbst"


def build_interpretation(
    conn,
    where: str = "",
    params: list | None = None,
    incident_hour: dict | None = None,
    incident_weekday: dict | None = None,
    heatmap: dict | None = None,
    socio: dict | None = None,
) -> dict:
    params = params or []
    rows = _fetch_rows(conn, where, params)
    dates, date_stats = _parse_rows(rows)

    hours: Counter[int] = Counter()
    for row in rows:
        h = extract_incident_hour(row["body_text"])
        if h is not None:
            hours[h] += 1

    hour_parsed = sum(hours.values())
    evening = sum(hours.get(h, 0) for h in EVENING_HOURS)
    night = sum(hours.get(h, 0) for h in NIGHT_HOURS)
    daytime = sum(hours.get(h, 0) for h in DAYTIME_HOURS)
    morning = sum(hours.get(h, 0) for h in range(6, 12))

    dow: Counter[int] = Counter(d.weekday() for d in dates)
    wd_parsed = sum(dow.values())
    weekend = dow.get(5, 0) + dow.get(6, 0)
    weekday = wd_parsed - weekend

    seasons: Counter[str] = Counter(_season_for_month(d.month) for d in dates)
    months: Counter[int] = Counter(d.month for d in dates)

    findings: list[dict] = []
    filtered = bool(where and where.strip().upper().startswith("WHERE"))

    # --- Uhrzeit ---
    if hour_parsed >= 50:
        evening_pct = _pct(evening, hour_parsed)
        night_pct = _pct(night, hour_parsed)
        daytime_pct = _pct(daytime, hour_parsed)
        peak_h = max(hours, key=hours.get)
        evening_factor = _ratio_vs_uniform(evening, hour_parsed, 6)
        night_factor = _ratio_vs_uniform(night, hour_parsed, 8)

        if evening_pct >= 32:
            findings.append({
                "icon": "🌆",
                "title": "Taten häufen sich am Abend",
                "body": (
                    f"Von den Meldungen mit Uhrzeitangabe entfallen <strong>{evening_pct} %</strong> "
                    f"auf 18–23 Uhr — deutlich mehr als an einem gleichmäßig verteilten Tag "
                    f"(Faktor {evening_factor}×). "
                    f"Der häufigste Zeitpunkt liegt gegen <strong>{peak_h:02d} Uhr</strong>. "
                    "Das spricht für viele Vorfälle in Freizeit- und Ausgehzeiten, "
                    "nicht mitten im Büroalltag."
                ),
                "strength": "high" if evening_pct >= 38 else "medium",
            })

        if night_pct >= 18 and night_factor >= 1.3:
            findings.append({
                "icon": "🌙",
                "title": "Nachtstunden sind überproportional betroffen",
                "body": (
                    f"<strong>{night_pct} %</strong> der genannten Taten liegen zwischen 22 und 5 Uhr "
                    f"(≈{night_factor}× gegenüber Gleichverteilung). "
                    "Typisch sind Straftaten und Störungen, wenn weniger Menschen unterwegs sind "
                    "— oder wenn Alkohol eine Rolle spielt."
                ),
                "strength": "medium",
            })

        if daytime_pct < 45 and morning < evening:
            findings.append({
                "icon": "☀️",
                "title": "Tagsüber weniger gemeldete Taten",
                "body": (
                    f"Nur <strong>{daytime_pct} %</strong> zwischen 8 und 17 Uhr — der Abend überwiegt klar. "
                    "Das Muster passt zu Diebstählen, Körperverletzungen und Verkehrsdelikten "
                    "außerhalb der Kernarbeitszeit, nicht zu einem reinen „Bürozeiten“-Effekt."
                ),
                "strength": "medium",
            })

    # --- Wochentag ---
    if wd_parsed >= 50:
        weekend_pct = _pct(weekend, wd_parsed)
        weekend_expected = 2 / 7 * 100  # ~28.6%
        peak_dow = max(dow, key=dow.get)
        peak_label = WEEKDAY_LABELS[peak_dow]
        peak_count = dow[peak_dow]
        peak_factor = _ratio_vs_uniform(peak_count, wd_parsed, 7)

        if weekend_pct > weekend_expected + 5:
            findings.append({
                "icon": "📅",
                "title": "Wochenende überdurchschnittlich",
                "body": (
                    f"<strong>{weekend_pct} %</strong> der Taten mit Datum fallen auf Samstag oder Sonntag "
                    f"(ohne Gleichverteilung wären es ~29 %). "
                    "Freizeit, Feiern und leerere Straßen können mehr Konflikte und Einbrüche begünstigen."
                ),
                "strength": "high" if weekend_pct >= 35 else "medium",
            })
        elif weekend_pct < weekend_expected - 5:
            findings.append({
                "icon": "📅",
                "title": "Werktage dominieren",
                "body": (
                    f"Nur <strong>{weekend_pct} %</strong> am Wochenende — die meisten gemeldeten Taten "
                    f"passieren unter der Woche (<strong>{_pct(weekday, wd_parsed)} %</strong> Mo–Fr). "
                    "Das kann auf Alltagskriminalität, Verkehr oder Ereignisse am Arbeitsort hindeuten."
                ),
                "strength": "medium",
            })

        if peak_factor >= 1.15:
            findings.append({
                "icon": "📌",
                "title": f"{peak_label} ist der häufigste Tat-Tag",
                "body": (
                    f"<strong>{peak_label}</strong> hat mit {peak_count} Fällen den höchsten Anteil "
                    f"(≈{peak_factor}× gegenüber einem gleichmäßigen Wochentag). "
                    "Ob das ein dauerhaftes Muster oder Zufall ist, zeigt sich erst über längere Zeiträume."
                ),
                "strength": "low" if peak_factor < 1.25 else "medium",
            })

    # --- Jahreszeit / Monat ---
    if len(dates) >= 100:
        season_total = sum(seasons.values())
        top_season = seasons.most_common(1)[0]
        top_month = months.most_common(1)[0]
        summer = seasons.get("Sommer", 0)
        winter = seasons.get("Winter", 0)
        summer_pct = _pct(summer, season_total)
        winter_pct = _pct(winter, season_total)

        if top_season[1] / season_total >= 0.28:
            findings.append({
                "icon": "🗓",
                "title": f"{top_season[0]} ist die aktivste Jahreszeit",
                "body": (
                    f"<strong>{_pct(top_season[1], season_total)} %</strong> aller erkannten Tatdaten liegen im "
                    f"{top_season[0]} (häufigster Monat: <strong>{MONTH_NAMES[top_month[0] - 1]}</strong>). "
                    "Längere Tage, mehr Menschen draußen oder saisonale Ereignisse können das verstärken."
                ),
                "strength": "medium",
            })

        if summer_pct - winter_pct >= 8:
            findings.append({
                "icon": "☀️",
                "title": "Sommer vs. Winter",
                "body": (
                    f"Im Sommer <strong>{summer_pct} %</strong>, im Winter <strong>{winter_pct} %</strong> der datierten Taten — "
                    "ein deutlicher Sommer-Schwerpunkt. Kriminalitätsstatistiken kennen das oft "
                    "(Einbrüche, Körperverletzungen, öffentliche Räume)."
                ),
                "strength": "medium",
            })

    # --- Volumen / Filter ---
    if heatmap and heatmap.get("peak") and not filtered:
        p = heatmap["peak"]
        findings.append({
            "icon": "📈",
            "title": "Zeitliche Konzentration",
            "body": (
                f"Besonders viele Taten mit erkanntem Datum in <strong>{p['label']} {p['year']}</strong> "
                f"({p['count']} Fälle). Das kann an einem Ereignis, einer Serie von Taten "
                "oder mehr Meldungen an einem Tag liegen — nicht automatisch an mehr Kriminalität generell."
            ),
            "strength": "low",
        })

    if filtered:
        headline = (
            "Gefilterte Auswahl: Die Muster unten gelten nur für die aktuellen Suchtreffer, "
            "nicht für ganz Berlin."
        )
    elif findings:
        lead = findings[0]
        first_sentence = lead["body"].split(".")[0] + "."
        headline = f"<strong>{lead['title']}</strong> — {first_sentence}"
    else:
        headline = (
            "In den Meldungstexten finden sich zu wenig klare Zeitangaben, "
            "um belastbare Muster zu beschreiben."
        )

    limitations = [
        (
            "Es sind <strong>Pressemitteilungen</strong>, keine vollständige Kriminalstatistik — "
            "nur Taten, die die Polizei öffentlich macht."
        ),
        (
            f"<strong>{date_stats['coverage_pct']}%</strong> der Texte liefern ein Tatdatum, "
            f"<strong>{incident_hour.get('coverage_pct', 0) if incident_hour else 0}%</strong> eine Uhrzeit "
            "(„gegen … Uhr“). Der Rest fehlt in den Auswertungen."
        ),
        (
            "„Gestern“ und „am Montag“ werden aus dem Meldungsdatum abgeleitet — "
            "kleine Fehler sind möglich."
        ),
        (
            "Viele Meldungen sind <strong>Verkehr, Zeugenaufruf oder Ermittlungsstand</strong> — "
            "nicht jede Zeile ist ein klassisches „Verbrechen am Abend“."
        ),
    ]

    if socio:
        from dashboard.socio_stats import build_socio_findings
        socio_cards = build_socio_findings(socio)
        findings = socio_cards + findings

    order = {"high": 0, "medium": 1, "low": 2}
    findings.sort(key=lambda f: order.get(f.get("strength", "low"), 9))

    return {
        "headline": headline,
        "findings": findings[:8],
        "limitations": limitations,
        "stats": {
            "dated": date_stats["parsed"],
            "timed": hour_parsed,
            "date_coverage": date_stats["coverage_pct"],
            "time_coverage": incident_hour.get("coverage_pct", 0) if incident_hour else 0,
        },
    }
