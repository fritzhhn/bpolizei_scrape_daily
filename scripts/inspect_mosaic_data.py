#!/usr/bin/env python3
"""Inspect data coverage for the Berlin Daily Grid mosaic."""

from __future__ import annotations

from dashboard.mosaic_data import inspect_mosaic_inputs


def main() -> None:
    report = inspect_mosaic_inputs()
    weather = report["weather"]

    print("Berlin Daily Grid data inspection")
    print("=" * 39)
    print(f"Total rows in meldungen: {report['total_rows']:,}")
    print(f"First report date: {report['first_date']}")
    print(f"Last report date: {report['last_date']}")
    print(f"Exact distinct report dates: {report['distinct_dates']:,}")
    print(f"Missing dates in full date range: {len(report['missing_dates']):,}")
    if report["missing_dates"]:
        preview = report["missing_dates"][:12]
        tail = report["missing_dates"][-5:]
        print(f"  First missing dates: {', '.join(preview)}")
        if tail != preview[-5:]:
            print(f"  Last missing dates: {', '.join(tail)}")

    print()
    print("Top 10 days by report count")
    for row in report["top_days"]:
        print(f"  {row['date']}: {row['report_count']} reports")

    print()
    print("Weather join")
    print(f"  Available: {weather.get('available')}")
    print(f"  Join works: {weather.get('join_works')}")
    if weather.get("available"):
        print(f"  Weather table: {weather.get('table')}")
        print(f"  Weather range: {weather.get('first_date')} to {weather.get('last_date')}")
        print(f"  Weather rows: {weather.get('rows'):,}")
        print(f"  Matched report dates: {weather.get('matched_days'):,} / {weather.get('police_days'):,} ({weather.get('coverage_pct')}%)")
        fields = ", ".join(f"{f['name']}<-{f['column']}" for f in weather.get("fields", []))
        print(f"  Available fields: {fields or 'none'}")
    else:
        print(f"  Reason: {weather.get('reason')}")

    print()
    print("Exact SQL")
    for name, sql in report["sql"].items():
        print(f"-- {name}")
        print(sql)


if __name__ == "__main__":
    main()
