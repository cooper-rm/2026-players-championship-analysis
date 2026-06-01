"""Bulk-collect THE PLAYERS Championship stats from pgatour.com and cache to disk.

Pulls every stat in the PGA Tour catalog for each requested edition of THE PLAYERS,
saving one JSON file per (year, stat) under data/. Designed to be re-run safely:
already-cached files are skipped, so a run that dies partway just resumes.

THE PLAYERS is PGA Tour tournament 011; its per-year id is "R<year>011"
(e.g. R2026011). 2020 is skipped automatically — that edition was cancelled.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from src.scrape_pgatour import fetch_event_stat, fetch_stat_catalog

DATA_ROOT = Path("data/players_championship")
CANCELLED_YEARS = {2020}  # cancelled after round 1 (COVID) — no event stats exist


def players_tournament_id(year: int) -> str:
    """Return THE PLAYERS pgatour tournament id for a given year (e.g. R2026011)."""
    return f"R{year}011"


def pull_stat_to_disk(
    stat_id: str,
    year: int,
    category: str = "",
    stat_title: str = "",
    out_root: Path = DATA_ROOT,
    overwrite: bool = False,
) -> str:
    """Pull one stat for one PLAYERS edition and cache it to disk.

    Returns a status string: "cached" (already on disk, skipped), "ok" (pulled with
    rows), or "empty" (pulled but the event had no rows for this stat). Raises only on
    a genuine request/parse failure, which the bulk runner catches per-stat.
    """
    out_dir = out_root / str(year)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{stat_id}.json"
    if path.exists() and not overwrite:
        return "cached"

    rows = fetch_event_stat(stat_id, players_tournament_id(year), year)
    payload = {
        "stat_id": stat_id,
        "stat_title": stat_title,
        "category": category,
        "year": year,
        "tournament_id": players_tournament_id(year),
        "rows": rows,
    }
    path.write_text(json.dumps(payload, indent=2))
    return "ok" if rows else "empty"


def bulk_pull(
    years: list[int],
    out_root: Path = DATA_ROOT,
    delay: float = 0.3,
    overwrite: bool = False,
) -> dict:
    """Pull the full stat catalog for each year, caching every (year, stat) to disk.

    Skips cached files (resumable) and cancelled years. Sleeps `delay` seconds between
    live requests to be polite to the site. Per-stat errors are logged and counted,
    never fatal, so one bad stat can't sink a 2,900-request run.
    """
    catalog = fetch_stat_catalog(max(years))
    years = [y for y in years if y not in CANCELLED_YEARS]
    totals = {"ok": 0, "empty": 0, "cached": 0, "error": 0}
    errors: list[tuple] = []
    total_jobs = len(catalog) * len(years)
    done = 0

    print(f"catalog: {len(catalog)} stats x {len(years)} years = {total_jobs} jobs")
    for year in years:
        for stat in catalog:
            done += 1
            try:
                status = pull_stat_to_disk(
                    stat["stat_id"], year, stat["category"],
                    stat["stat_title"], out_root, overwrite,
                )
            except Exception as exc:  # noqa: BLE001 — keep the run alive
                status = "error"
                errors.append((year, stat["stat_id"], str(exc)[:100]))
            totals[status] += 1
            if status != "cached":
                time.sleep(delay)  # only rate-limit real network calls
            if done % 100 == 0:
                print(f"[{done}/{total_jobs}] {totals}")

    print(f"DONE {totals}")
    if errors:
        print(f"{len(errors)} errors; first few: {errors[:5]}")
    return {"totals": totals, "errors": errors}


if __name__ == "__main__":
    bulk_pull(years=[2022, 2023, 2024, 2025, 2026])
