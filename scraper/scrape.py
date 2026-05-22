#!/usr/bin/env python3
"""Scraper für Polizeimeldungen Berlin (berlin.de)."""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime

import requests

from scraper.config import (
    ARCHIV_START_YEAR,
    ARCHIV_URL,
    LISTING_URL,
    REQUEST_DELAY_SEC,
    REQUEST_TIMEOUT_SEC,
    USER_AGENT,
)
from scraper.db import connect, upsert_meldung, utc_now
from scraper.parse import (
    build_page_url,
    last_page_number,
    pagination_param_from_html,
    parse_article_page,
    parse_listing_page,
)

log = logging.getLogger(__name__)


class BerlinPolizeiScraper:
    def __init__(self, delay: float = REQUEST_DELAY_SEC):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self.delay = delay

    def fetch(self, url: str) -> str:
        time.sleep(self.delay)
        resp = self.session.get(url, timeout=REQUEST_TIMEOUT_SEC)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding or "utf-8"
        return resp.text

    def collect_listing_urls(self, base_url: str) -> list[dict]:
        """Alle Teaser von einer Übersichtsseite (mit Pagination)."""
        seen_pages: set[str] = set()
        teasers: dict[str, dict] = {}
        url = base_url

        while url and url not in seen_pages:
            seen_pages.add(url)
            log.info("Liste: %s", url)
            html = self.fetch(url)
            items, next_url = parse_listing_page(html)
            for item in items:
                teasers[item["id"]] = item

            if url == base_url:
                page_param = pagination_param_from_html(html)
                if page_param:
                    last_page = last_page_number(html)
                    for page in range(2, last_page + 1):
                        page_url = build_page_url(base_url, page_param, page)
                        if page_url in seen_pages:
                            continue
                        seen_pages.add(page_url)
                        log.info("Liste: %s", page_url)
                        page_html = self.fetch(page_url)
                        page_items, _ = parse_listing_page(page_html)
                        for item in page_items:
                            teasers[item["id"]] = item
                    break

            url = next_url

        return list(teasers.values())

    def scrape_article(self, teaser: dict) -> dict:
        html = self.fetch(teaser["url"])
        return parse_article_page(html, teaser["url"], teaser)

    def run(
        self,
        mode: str = "daily",
        limit: int | None = None,
        skip_existing: bool = False,
    ) -> dict:
        listing_bases = self._listing_urls_for_mode(mode)
        stats = {
            "listings_found": 0,
            "articles_fetched": 0,
            "articles_new": 0,
            "articles_updated": 0,
            "articles_unchanged": 0,
            "errors": 0,
        }

        all_teasers: dict[str, dict] = {}
        for base in listing_bases:
            try:
                for teaser in self.collect_listing_urls(base):
                    all_teasers[teaser["id"]] = teaser
            except Exception as e:
                log.exception("Fehler bei Listing %s: %s", base, e)
                stats["errors"] += 1

        stats["listings_found"] = len(all_teasers)
        log.info("%d Meldungen in Listen gefunden", stats["listings_found"])

        teaser_list = list(all_teasers.values())
        if limit:
            teaser_list = teaser_list[:limit]

        with connect() as conn:
            run_id = conn.execute(
                """
                INSERT INTO scrape_runs (started_at, mode, notes)
                VALUES (?, ?, ?)
                """,
                (utc_now(), mode, f"{len(listing_bases)} listing sources"),
            ).lastrowid

            existing_ids: set[str] = set()
            if skip_existing:
                rows = conn.execute("SELECT id FROM meldungen").fetchall()
                existing_ids = {r["id"] for r in rows}

            for teaser in teaser_list:
                if skip_existing and teaser["id"] in existing_ids:
                    continue
                try:
                    article = self.scrape_article(teaser)
                    result = upsert_meldung(conn, article)
                    stats["articles_fetched"] += 1
                    if result == "new":
                        stats["articles_new"] += 1
                    elif result == "updated":
                        stats["articles_updated"] += 1
                    else:
                        stats["articles_unchanged"] += 1
                except Exception as e:
                    log.exception("Fehler bei %s: %s", teaser["url"], e)
                    stats["errors"] += 1

            conn.execute(
                """
                UPDATE scrape_runs SET
                    finished_at = ?,
                    listings_found = ?,
                    articles_fetched = ?,
                    articles_new = ?,
                    articles_updated = ?,
                    errors = ?
                WHERE id = ?
                """,
                (
                    utc_now(),
                    stats["listings_found"],
                    stats["articles_fetched"],
                    stats["articles_new"],
                    stats["articles_updated"],
                    stats["errors"],
                    run_id,
                ),
            )

        return stats

    def _listing_urls_for_mode(self, mode: str) -> list[str]:
        current_year = datetime.now().year
        if mode == "current":
            return [LISTING_URL]
        if mode == "daily":
            return [
                LISTING_URL,
                f"{ARCHIV_URL}{current_year}/",
            ]
        if mode == "full":
            urls = [LISTING_URL]
            for year in range(ARCHIV_START_YEAR, current_year + 1):
                urls.append(f"{ARCHIV_URL}{year}/")
            return urls
        raise ValueError(f"Unbekannter Modus: {mode}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Polizeimeldungen Berlin scrapen")
    parser.add_argument(
        "--mode",
        choices=["current", "daily", "full"],
        default="daily",
        help="current: letzte ~2 Wochen; daily: aktuelle + laufendes Jahr; full: Archiv 2014–heute",
    )
    parser.add_argument("--limit", type=int, help="Max. Anzahl Artikel (Test)")
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Bereits gespeicherte Artikel nicht erneut laden",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    scraper = BerlinPolizeiScraper()
    stats = scraper.run(
        mode=args.mode,
        limit=args.limit,
        skip_existing=args.skip_existing,
    )
    log.info(
        "Fertig: %d Listen, %d geladen (%d neu, %d aktualisiert, %d unverändert), %d Fehler",
        stats["listings_found"],
        stats["articles_fetched"],
        stats["articles_new"],
        stats["articles_updated"],
        stats["articles_unchanged"],
        stats["errors"],
    )
    return 1 if stats["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
