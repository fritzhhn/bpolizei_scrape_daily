#!/usr/bin/env python3
"""Web-Dashboard für Polizeimeldungen Berlin."""

from __future__ import annotations

import sqlite3
from collections import Counter
from datetime import datetime
from math import ceil

from flask import Flask, abort, jsonify, render_template, request

from urllib.parse import urlencode

from dashboard.helpers import (
    YEAR_FILTER_SQL,
    YEAR_SQL,
    build_timeline,
    early_years_note,
    enrich_row,
    fill_years_range,
    format_datetime,
)
from dashboard.insights import build_all_insights
from dashboard.mosaic_data import build_daily_mosaic
from scraper.config import ARCHIV_START_YEAR, DB_PATH
from scraper.parse import tags_from_json

app = Flask(__name__)
PER_PAGE = 40
CURRENT_YEAR = datetime.now().year
TIMELINE_MODES = ("month", "week", "season", "weekday", "month_of_year")


def get_db():
    if not DB_PATH.exists():
        return None
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _aggregate_tags(conn) -> list[tuple[str, int]]:
    counts: Counter[str] = Counter()
    for row in conn.execute(
        "SELECT tags FROM meldungen WHERE tags IS NOT NULL AND tags != '[]'"
    ):
        for tag in tags_from_json(row["tags"]):
            counts[tag] += 1
    return counts.most_common(15)


def _query_params(request_args) -> tuple[str, list, str, str, str, str, str, int]:
    q = request_args.get("q", "").strip()
    district = request_args.get("district", "").strip()
    year = request_args.get("year", "").strip()
    tag = request_args.get("tag", "").strip()
    granularity = request_args.get("granularity", "month").strip()
    if granularity not in TIMELINE_MODES:
        granularity = "month"
    page = max(1, int(request_args.get("page", 1) or 1))

    conditions = []
    params: list = []
    if q:
        conditions.append(
            "(title LIKE ? OR body_text LIKE ? OR summary LIKE ? OR district LIKE ? OR tags LIKE ?)"
        )
        like = f"%{q}%"
        params.extend([like, like, like, like, like])
    if district:
        conditions.append("district = ?")
        params.append(district)
    if year.isdigit():
        conditions.append(YEAR_FILTER_SQL)
        params.append(int(year))
    if tag:
        conditions.append("tags LIKE ?")
        params.append(f'%"{tag}"%')

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    return where, params, q, district, year, tag, granularity, page


@app.route("/")
def index():
    conn = get_db()
    if conn is None:
        return render_template("index.html", ready=False)

    where, params, q, district, year, tag, granularity, page = _query_params(request.args)

    total = conn.execute(
        f"SELECT COUNT(*) FROM meldungen {where}", params
    ).fetchone()[0]
    pages = max(1, ceil(total / PER_PAGE))
    page = min(page, pages)
    offset = (page - 1) * PER_PAGE

    rows = conn.execute(
        f"""
        SELECT id, title, published_at, meldung_date, district, case_number, tags,
               source_year, {YEAR_SQL} AS pub_year
        FROM meldungen {where}
        ORDER BY published_at DESC NULLS LAST, id DESC
        LIMIT ? OFFSET ?
        """,
        [*params, PER_PAGE, offset],
    ).fetchall()

    meldungen = [enrich_row(r) for r in rows]

    stats = conn.execute(
        f"""
        SELECT
            COUNT(*) AS total,
            COUNT(DISTINCT district) AS districts,
            MIN({YEAR_SQL}) AS year_min,
            MAX({YEAR_SQL}) AS year_max,
            MIN(published_at) AS oldest,
            MAX(published_at) AS newest,
            SUM(CASE WHEN images IS NOT NULL AND images != '[]' THEN 1 ELSE 0 END) AS with_images,
            SUM(CASE WHEN case_number IS NOT NULL AND case_number != '' THEN 1 ELSE 0 END) AS with_case_number,
            SUM(CASE WHEN tags IS NOT NULL AND tags != '[]' THEN 1 ELSE 0 END) AS with_tags
        FROM meldungen
        WHERE COALESCE(published_at, meldung_date) IS NOT NULL
        """
    ).fetchone()

    filtered_stats = conn.execute(
        f"""
        SELECT COUNT(*) AS total, COUNT(DISTINCT district) AS districts
        FROM meldungen {where}
        """,
        params,
    ).fetchone()

    by_year_raw = conn.execute(
        f"""
        SELECT {YEAR_SQL} AS year, COUNT(*) AS count
        FROM meldungen
        WHERE COALESCE(published_at, meldung_date) IS NOT NULL
          AND {YEAR_SQL} BETWEEN ? AND ?
        GROUP BY year ORDER BY year DESC
        """,
        (ARCHIV_START_YEAR, CURRENT_YEAR),
    ).fetchall()

    by_year = fill_years_range(by_year_raw, ARCHIV_START_YEAR, CURRENT_YEAR)
    timeline_bars, timeline_meta = build_timeline(conn, granularity, where, params)
    early_note = early_years_note(conn)
    insights = build_all_insights(conn, where, params)
    filter_qs = urlencode(
        {k: v for k, v in [
            ("q", q), ("district", district), ("year", year), ("tag", tag),
            ("granularity", granularity),
        ] if v}
    )

    by_district = conn.execute(
        """
        SELECT district, COUNT(*) AS count
        FROM meldungen
        WHERE district IS NOT NULL AND district != ''
        GROUP BY district ORDER BY count DESC LIMIT 12
        """
    ).fetchall()

    popular_tags = _aggregate_tags(conn)
    districts = conn.execute(
        """
        SELECT district, COUNT(*) AS count
        FROM meldungen
        WHERE district IS NOT NULL AND district != ''
        GROUP BY district ORDER BY count DESC, district
        """
    ).fetchall()

    years = list(range(CURRENT_YEAR, ARCHIV_START_YEAR - 1, -1))
    runs = conn.execute("SELECT * FROM scrape_runs ORDER BY id DESC LIMIT 3").fetchall()
    conn.close()

    return render_template(
        "index.html",
        ready=True,
        meldungen=meldungen,
        stats=stats,
        filtered_stats=filtered_stats,
        by_year=by_year,
        by_district=by_district,
        popular_tags=popular_tags,
        districts=districts,
        years=years,
        runs=runs,
        timeline_bars=timeline_bars,
        timeline_meta=timeline_meta,
        timeline_modes=TIMELINE_MODES,
        granularity=granularity,
        early_note=early_note,
        insights=insights,
        filter_qs=filter_qs,
        q=q,
        district_filter=district,
        year_filter=year,
        tag_filter=tag,
        page=page,
        pages=pages,
        total=total,
        format_datetime=format_datetime,
        max_year_count=max((r["count"] for r in by_year), default=1),
        max_district_count=max((r["count"] for r in by_district), default=1),
        max_tag_count=popular_tags[0][1] if popular_tags else 1,
        year_range=f"{ARCHIV_START_YEAR}–{CURRENT_YEAR}",
    )


@app.route("/meldung/<article_id>")
def detail(article_id: str):
    conn = get_db()
    if conn is None:
        abort(404)
    row = conn.execute("SELECT * FROM meldungen WHERE id = ?", (article_id,)).fetchone()
    conn.close()
    if row is None:
        abort(404)
    return render_template("detail.html", m=enrich_row(row), format_datetime=format_datetime)


@app.route("/mosaic")
def mosaic():
    conn = get_db()
    if conn is None:
        return render_template("mosaic.html", ready=False)
    conn.close()
    return render_template("mosaic.html", ready=True)


@app.route("/api/daily-mosaic")
def daily_mosaic_api():
    conn = get_db()
    if conn is None:
        abort(404)
    try:
        return jsonify(build_daily_mosaic(conn))
    finally:
        conn.close()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5050, debug=True)
