#!/usr/bin/env python3
"""Statische GitHub-Pages aus meldungen.db erzeugen."""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from pathlib import Path

from scraper.config import ARCHIV_START_YEAR, DB_PATH
from scraper.parse import tags_from_json

YEAR_SQL = "CAST(substr(COALESCE(published_at, meldung_date || 'T00:00:00'), 1, 4) AS INTEGER)"

DOCS = Path(__file__).resolve().parent.parent / "docs"
RECENT_LIMIT = 80


def main() -> None:
    if not DB_PATH.exists():
        raise SystemExit(f"Keine Datenbank: {DB_PATH}")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    stats = dict(
        conn.execute(
            """
            SELECT COUNT(*) AS total,
                   COUNT(DISTINCT district) AS districts,
                   MIN(published_at) AS oldest,
                   MAX(published_at) AS newest,
                   SUM(CASE WHEN images IS NOT NULL AND images != '[]' THEN 1 ELSE 0 END) AS with_images
            FROM meldungen
            """
        ).fetchone()
    )

    from datetime import datetime

    end_year = datetime.now().year
    by_year_rows = {
        int(r["year"]): int(r["count"])
        for r in conn.execute(
            f"""
            SELECT {YEAR_SQL} AS year, COUNT(*) AS count
            FROM meldungen
            WHERE COALESCE(published_at, meldung_date) IS NOT NULL
              AND {YEAR_SQL} BETWEEN ? AND ?
            GROUP BY year
            """,
            (ARCHIV_START_YEAR, end_year),
        )
    }
    by_year = [
        {"year": y, "count": by_year_rows.get(y, 0)}
        for y in range(end_year, ARCHIV_START_YEAR - 1, -1)
    ]

    by_district = [
        dict(r)
        for r in conn.execute(
            """
            SELECT district, COUNT(*) AS count
            FROM meldungen WHERE district IS NOT NULL AND district != ''
            GROUP BY district ORDER BY count DESC LIMIT 14
            """
        )
    ]

    tag_counts: Counter[str] = Counter()
    for row in conn.execute("SELECT tags FROM meldungen WHERE tags IS NOT NULL"):
        for t in tags_from_json(row["tags"]):
            tag_counts[t] += 1
    by_tag = [{"tag": t, "count": c} for t, c in tag_counts.most_common(12)]

    recent = [
        {
            "id": r["id"],
            "title": r["title"],
            "published_at": (r["published_at"] or "")[:16].replace("T", " "),
            "district": r["district"],
            "case_number": r["case_number"],
            "summary": r["summary"],
            "url": r["url"],
            "tags": tags_from_json(r["tags"]),
        }
        for r in conn.execute(
            """
            SELECT id, title, published_at, district, case_number, summary, url, tags
            FROM meldungen
            ORDER BY published_at DESC NULLS LAST, id DESC
            LIMIT ?
            """,
            (RECENT_LIMIT,),
        )
    ]

    conn.close()

    payload = {
        "stats": stats,
        "by_year": by_year,
        "by_district": by_district,
        "by_tag": by_tag,
        "recent": recent,
    }

    DOCS.mkdir(parents=True, exist_ok=True)
    data_js = json.dumps(payload, ensure_ascii=False)
    html = HTML_TEMPLATE.replace("/*__DATA__*/", data_js)
    (DOCS / "index.html").write_text(html, encoding="utf-8")
    print(f"Geschrieben: {DOCS / 'index.html'} ({stats['total']} Meldungen)")


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Polizeimeldungen Berlin · Archiv</title>
  <link href="https://fonts.googleapis.com/css2?family=Source+Sans+3:wght@400;600&display=swap" rel="stylesheet">
  <style>
    :root { --bg:#f4f1eb; --paper:#fffdf9; --ink:#1a1f26; --muted:#5c6573; --line:#d8d2c8; --accent:#1e4d8c; }
    * { box-sizing:border-box; }
    body { margin:0; font-family:"Source Sans 3",system-ui,sans-serif; background:var(--bg); color:var(--ink); line-height:1.5; }
    .wrap { max-width:1100px; margin:0 auto; padding:1.25rem 1.5rem 3rem; }
    header { border-bottom:2px solid var(--ink); padding-bottom:1rem; margin-bottom:1.25rem; }
    h1 { margin:0; font-size:1.5rem; }
    .sub { color:var(--muted); font-size:0.9rem; margin-top:0.35rem; }
    .stats { display:grid; grid-template-columns:repeat(auto-fill,minmax(120px,1fr)); gap:0.5rem; margin-bottom:1rem; }
    .stat { background:var(--paper); border:1px solid var(--line); padding:0.6rem; text-align:center; border-radius:4px; }
    .stat b { display:block; font-size:1.25rem; }
    .stat span { font-size:0.7rem; color:var(--muted); text-transform:uppercase; }
    .grid { display:grid; grid-template-columns:260px 1fr; gap:1rem; }
    @media(max-width:800px){ .grid { grid-template-columns:1fr; } }
    .card { background:var(--paper); border:1px solid var(--line); border-radius:4px; padding:0.85rem 1rem; margin-bottom:0.75rem; }
    .card h2 { margin:0 0 0.5rem; font-size:0.75rem; text-transform:uppercase; color:var(--muted); }
    .bar { display:grid; grid-template-columns:70px 1fr 32px; gap:0.3rem; font-size:0.78rem; margin-bottom:0.3rem; align-items:center; }
    .track { height:5px; background:var(--line); border-radius:2px; overflow:hidden; }
    .fill { height:100%; background:var(--accent); }
    table { width:100%; border-collapse:collapse; font-size:0.84rem; }
    th { text-align:left; font-size:0.7rem; text-transform:uppercase; color:var(--muted); padding:0.35rem 0.4rem; border-bottom:2px solid var(--line); }
    td { padding:0.4rem; border-bottom:1px solid var(--line); vertical-align:top; }
    tr:hover { background:#e8f0fa; }
    a { color:var(--accent); }
    .tag { font-size:0.68rem; color:var(--muted); margin-right:0.3rem; }
    .col-date { white-space:nowrap; color:var(--muted); width:115px; }
    .col-nr { text-align:right; color:var(--muted); width:42px; }
    footer { margin-top:1.5rem; font-size:0.8rem; color:var(--muted); }
  </style>
</head>
<body>
  <div class="wrap">
    <header>
      <h1>Polizeimeldungen Berlin</h1>
      <p class="sub">Archiv · <a href="https://github.com/fritzhhn/bpolizei_scrape_daily">bpolizei_scrape_daily</a> · Daten von <a href="https://www.berlin.de/polizei/polizeimeldungen/">berlin.de</a></p>
    </header>
    <div class="stats" id="stats"></div>
    <div class="grid">
      <div id="sidebar"></div>
      <div class="card">
        <h2>Neueste Meldungen</h2>
        <table><thead><tr><th>Datum</th><th>Meldung</th><th>Bezirk</th><th>Nr.</th></tr></thead><tbody id="recent"></tbody></table>
      </div>
    </div>
    <footer>Vollständige SQLite-Datenbank im Repository unter <code>data/meldungen.db</code>. Täglich aktualisiert per GitHub Actions.</footer>
  </div>
  <script>
    const DATA = /*__DATA__*/;
    const max = (arr, k) => Math.max(...arr.map(x => x[k]), 1);
    document.getElementById('stats').innerHTML = [
      ['total','Meldungen'], ['districts','Bezirke'],
      ['with_images','mit Bildern'], ['newest','Neueste'], ['oldest','Älteste']
    ].map(([k,l]) => {
      let v = DATA.stats[k] || '—';
      if (k === 'newest' || k === 'oldest') v = (v||'').slice(0,10);
      return `<div class="stat"><b>${v}</b><span>${l}</span></div>`;
    }).join('');
    const bar = (items, labelKey, countKey, cls='') => items.map(i => `
      <div class="bar"><span>${i[labelKey]}</span><span class="track"><span class="fill ${cls}" style="width:${(i[countKey]/max(items,countKey))*100}%"></span></span><span>${i[countKey]}</span></div>
    `).join('');
    document.getElementById('sidebar').innerHTML = `
      <div class="card"><h2>Nach Jahr (2014–heute)</h2>${bar(DATA.by_year,'year','count')}</div>
      <div class="card"><h2>Top Bezirke</h2>${bar(DATA.by_district,'district','count','d')}</div>
      <div class="card"><h2>Kategorien</h2>${bar(DATA.by_tag,'tag','count','t')}</div>`;
    document.getElementById('recent').innerHTML = DATA.recent.map(m => `
      <tr>
        <td class="col-date">${m.published_at||'—'}</td>
        <td><a href="${m.url}" target="_blank" rel="noopener">${m.title}</a>
          ${(m.tags||[]).slice(0,2).map(t=>`<span class="tag">${t}</span>`).join('')}
          ${m.summary ? `<br><small style="color:var(--muted)">${m.summary.slice(0,120)}…</small>` : ''}</td>
        <td>${m.district||'—'}</td>
        <td class="col-nr">${m.case_number||'—'}</td>
      </tr>`).join('');
  </script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
