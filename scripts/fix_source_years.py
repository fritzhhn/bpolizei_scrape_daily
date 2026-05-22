#!/usr/bin/env python3
"""source_year aus Veröffentlichungsdatum nachziehen."""

from scraper.db import connect

with connect() as conn:
    conn.execute(
        """
        UPDATE meldungen
        SET source_year = CAST(substr(COALESCE(published_at, meldung_date), 1, 4) AS INTEGER)
        WHERE (source_year IS NULL OR source_year != CAST(substr(COALESCE(published_at, meldung_date), 1, 4) AS INTEGER))
          AND COALESCE(published_at, meldung_date) IS NOT NULL
          AND length(COALESCE(published_at, meldung_date)) >= 4
        """
    )
    n = conn.execute("SELECT changes()").fetchone()[0]
    print(f"Aktualisiert: {n} Zeilen")
