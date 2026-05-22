#!/usr/bin/env python3
"""Web-Dashboard für Polizeimeldungen Berlin."""

from __future__ import annotations

import sqlite3
from math import ceil

from flask import Flask, abort, render_template, request

from dashboard.helpers import enrich_row, format_datetime
from scraper.config import DB_PATH

app = Flask(__name__)
PER_PAGE = 20


def get_db():
    if not DB_PATH.exists():
        return None
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


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
        SELECT *
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
            MIN(published_at) AS oldest,
            MAX(published_at) AS newest,
            SUM(CASE WHEN images IS NOT NULL AND images != '[]' THEN 1 ELSE 0 END) AS with_images
        FROM meldungen
        """
    ).fetchone()

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

    all_tags_rows = conn.execute(
        "SELECT tags FROM meldungen WHERE tags IS NOT NULL AND tags != '[]'"
    ).fetchall()
    tag_counts: dict[str, int] = {}
    for r in all_tags_rows:
        for t in enrich_row({"tags": r["tags"]})["tags_list"]:
            tag_counts[t] = tag_counts.get(t, 0) + 1
    popular_tags = sorted(tag_counts.items(), key=lambda x: (-x[1], x[0]))[:20]

    runs = conn.execute(
        "SELECT * FROM scrape_runs ORDER BY id DESC LIMIT 5"
    ).fetchall()

    conn.close()

    return render_template(
        "index.html",
        ready=True,
        meldungen=meldungen,
        stats=stats,
        districts=districts,
        years=[r["year"] for r in years],
        popular_tags=popular_tags,
        runs=runs,
        q=q,
        district_filter=district,
        year_filter=year,
        tag_filter=tag,
        page=page,
        pages=pages,
        total=total,
        format_datetime=format_datetime,
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
