#!/usr/bin/env python3
"""Web-Dashboard für Polizeimeldungen Berlin."""

from __future__ import annotations

import sqlite3
from collections import Counter
from math import ceil

from flask import Flask, abort, render_template, request

from dashboard.helpers import enrich_row, format_datetime
from scraper.config import DB_PATH
from scraper.parse import tags_from_json

app = Flask(__name__)
PER_PAGE = 40


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


@app.route("/")
def index():
    conn = get_db()
    if conn is None:
        return render_template("index.html", ready=False)

    q = request.args.get("q", "").strip()
    district = request.args.get("district", "").strip()
    year = request.args.get("year", "").strip()
    tag = request.args.get("tag", "").strip()
    page = max(1, int(request.args.get("page", 1) or 1))

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
        conditions.append("source_year = ?")
        params.append(int(year))
    if tag:
        conditions.append("tags LIKE ?")
        params.append(f'%"{tag}"%')

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    total = conn.execute(
        f"SELECT COUNT(*) FROM meldungen {where}", params
    ).fetchone()[0]
    pages = max(1, ceil(total / PER_PAGE))
    page = min(page, pages)
    offset = (page - 1) * PER_PAGE

    rows = conn.execute(
        f"""
        SELECT id, title, published_at, district, case_number, tags, source_year
        FROM meldungen {where}
        ORDER BY published_at DESC NULLS LAST, id DESC
        LIMIT ? OFFSET ?
        """,
        [*params, PER_PAGE, offset],
    ).fetchall()

    meldungen = [enrich_row(r) for r in rows]

    stats = conn.execute(
        """
        SELECT
            COUNT(*) AS total,
            COUNT(DISTINCT district) AS districts,
            COUNT(DISTINCT source_year) AS years,
            MIN(published_at) AS oldest,
            MAX(published_at) AS newest,
            SUM(CASE WHEN images IS NOT NULL AND images != '[]' THEN 1 ELSE 0 END) AS with_images,
            SUM(CASE WHEN case_number IS NOT NULL AND case_number != '' THEN 1 ELSE 0 END) AS with_case_number,
            SUM(CASE WHEN tags IS NOT NULL AND tags != '[]' THEN 1 ELSE 0 END) AS with_tags,
            ROUND(AVG(LENGTH(body_text))) AS avg_body_len
        FROM meldungen
        """
    ).fetchone()

    filtered_stats = conn.execute(
        f"""
        SELECT COUNT(*) AS total,
               COUNT(DISTINCT district) AS districts
        FROM meldungen {where}
        """,
        params,
    ).fetchone()

    by_year = conn.execute(
        """
        SELECT source_year AS year, COUNT(*) AS count
        FROM meldungen
        WHERE source_year IS NOT NULL
        GROUP BY source_year
        ORDER BY year DESC
        """
    ).fetchall()

    by_district = conn.execute(
        """
        SELECT district, COUNT(*) AS count
        FROM meldungen
        WHERE district IS NOT NULL AND district != ''
        GROUP BY district
        ORDER BY count DESC
        LIMIT 12
        """
    ).fetchall()

    by_month = conn.execute(
        """
        SELECT substr(published_at, 1, 7) AS month, COUNT(*) AS count
        FROM meldungen
        WHERE published_at IS NOT NULL AND length(published_at) >= 7
        GROUP BY month
        ORDER BY month DESC
        LIMIT 18
        """
    ).fetchall()

    popular_tags = _aggregate_tags(conn)

    districts = conn.execute(
        """
        SELECT district, COUNT(*) AS count
        FROM meldungen
        WHERE district IS NOT NULL AND district != ''
        GROUP BY district
        ORDER BY count DESC, district
        """
    ).fetchall()

    years = conn.execute(
        """
        SELECT DISTINCT source_year AS year
        FROM meldungen WHERE source_year IS NOT NULL
        ORDER BY year DESC
        """
    ).fetchall()

    runs = conn.execute(
        "SELECT * FROM scrape_runs ORDER BY id DESC LIMIT 3"
    ).fetchall()

    conn.close()

    max_year_count = max((r["count"] for r in by_year), default=1)
    max_district_count = max((r["count"] for r in by_district), default=1)
    max_month_count = max((r["count"] for r in by_month), default=1)
    max_tag_count = popular_tags[0][1] if popular_tags else 1

    return render_template(
        "index.html",
        ready=True,
        meldungen=meldungen,
        stats=stats,
        filtered_stats=filtered_stats,
        by_year=by_year,
        by_district=by_district,
        by_month=by_month,
        popular_tags=popular_tags,
        districts=districts,
        years=[r["year"] for r in years],
        runs=runs,
        q=q,
        district_filter=district,
        year_filter=year,
        tag_filter=tag,
        page=page,
        pages=pages,
        total=total,
        format_datetime=format_datetime,
        max_year_count=max_year_count,
        max_district_count=max_district_count,
        max_month_count=max_month_count,
        max_tag_count=max_tag_count,
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
    m = enrich_row(row)
    return render_template("detail.html", m=m, format_datetime=format_datetime)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5050, debug=True)
