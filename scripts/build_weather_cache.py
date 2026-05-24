#!/usr/bin/env python3
"""Wetter-Cache für Berlin befüllen (Open-Meteo)."""

from datetime import date

from dashboard.weather import ensure_weather_cached

if __name__ == "__main__":
    start = date(2014, 1, 1)
    end = date.today()
    print(f"Lade Wetter {start} – {end} …")
    ensure_weather_cached(start, end)
    print("Fertig:", "data/weather_berlin.db")
