"""Bulk-collect PGA Tour stats and cache to disk (resumable).

Two collections feed the two project stages, sharing one engine:
- season -> data/tour_season/<year>/<statId>.json
    full-season Tour-wide stats; the clustering input (how a player plays).
- event  -> data/players_championship/<year>/<statId>.json
    THE PLAYERS only; the scenario-analysis input.

Both go through _bulk(); only the per-stat fetch and the output dir differ. Re-runnable:
already-cached files are skipped, so a run that dies partway just resumes.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from src.scrape_pgatour import fetch_event_stat, fetch_season_stat, fetch_stat_catalog

SEASON_ROOT = Path("data/tour_season")
EVENT_ROOT = Path("data/players_championship")
CANCELLED_YEARS = {2020}  # THE PLAYERS 2020 was cancelled (COVID) — no event stats exist


def players_tournament_id(year: int) -> str:
    """Return THE PLAYERS pgatour tournament id for a given year (e.g. R2026011)."""
    return f"R{year}011"


def _pull_one_to_disk(out_root, year, stat_id, fetch_rows, meta, overwrite) -> str:
    """Cache one stat to out_root/<year>/<stat_id>.json. Returns cached/ok/empty.

    `fetch_rows` is a thunk (zero-arg callable) so the network call only happens on a
    cache miss — that is what makes a re-run resume without re-hitting the site.
    """
    out_dir = out_root / str(year)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{stat_id}.json"
    if path.exists() and not overwrite:
        return "cached"
    rows = fetch_rows()  # only runs when not cached
    payload = {"stat_id": stat_id, "year": year, **meta, "rows": rows}
    path.write_text(json.dumps(payload, indent=2))
    return "ok" if rows else "empty"


def pull_season_stat_to_disk(
    stat_id, year, category="", stat_title="", out_root=SEASON_ROOT, overwrite=False
) -> str:
    """Cache one full-season Tour stat (clustering input)."""
    return _pull_one_to_disk(
        out_root, year, stat_id,
        fetch_rows=lambda: fetch_season_stat(stat_id, year),
        meta={"category": category, "stat_title": stat_title},
        overwrite=overwrite,
    )


def pull_event_stat_to_disk(
    stat_id, year, category="", stat_title="", out_root=EVENT_ROOT, overwrite=False
) -> str:
    """Cache one THE PLAYERS event stat (scenario input)."""
    tournament_id = players_tournament_id(year)
    return _pull_one_to_disk(
        out_root, year, stat_id,
        fetch_rows=lambda: fetch_event_stat(stat_id, tournament_id, year),
        meta={"category": category, "stat_title": stat_title, "tournament_id": tournament_id},
        overwrite=overwrite,
    )


def _bulk(years, pull_one, delay, skip_years=frozenset()) -> dict:
    """Pull the full stat catalog for each year via pull_one, tallying outcomes.

    pull_one(stat_id, year, category, stat_title) -> status string. Per-stat errors are
    logged and counted, never fatal. Sleeps `delay` between live requests (not on cache
    hits). skip_years drops years that have no data (e.g. a cancelled event).
    """
    catalog = fetch_stat_catalog(max(years))
    years = [y for y in years if y not in skip_years]
    totals = {"ok": 0, "empty": 0, "cached": 0, "error": 0}
    errors: list[tuple] = []
    total_jobs = len(catalog) * len(years)
    done = 0

    print(f"catalog: {len(catalog)} stats x {len(years)} years = {total_jobs} jobs")
    for year in years:
        for stat in catalog:
            done += 1
            try:
                status = pull_one(stat["stat_id"], year, stat["category"], stat["stat_title"])
            except Exception as exc:  # noqa: BLE001 — keep the run alive
                status = "error"
                errors.append((year, stat["stat_id"], str(exc)[:100]))
            totals[status] += 1
            if status != "cached":
                time.sleep(delay)
            if done % 100 == 0:
                print(f"[{done}/{total_jobs}] {totals}")

    print(f"DONE {totals}")
    if errors:
        print(f"{len(errors)} errors; first few: {errors[:5]}")
    return {"totals": totals, "errors": errors}


def bulk_pull_season(years, out_root=SEASON_ROOT, delay=0.3, overwrite=False) -> dict:
    """Collect every catalog stat, full-season Tour-wide, for each year."""
    return _bulk(
        years,
        lambda sid, yr, cat, title: pull_season_stat_to_disk(sid, yr, cat, title, out_root, overwrite),
        delay,
    )


def bulk_pull_event(years, out_root=EVENT_ROOT, delay=0.3, overwrite=False) -> dict:
    """Collect every catalog stat at THE PLAYERS for each year (skips cancelled years)."""
    return _bulk(
        years,
        lambda sid, yr, cat, title: pull_event_stat_to_disk(sid, yr, cat, title, out_root, overwrite),
        delay,
        skip_years=CANCELLED_YEARS,
    )


if __name__ == "__main__":
    # Stage 1 input: full-season Tour stats for clustering.
    bulk_pull_season(years=[2022, 2023, 2024, 2025, 2026])
