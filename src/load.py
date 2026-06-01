"""Load cached PGA Tour stat JSON into tidy pandas DataFrames.

The collector (collect.py) writes one JSON file per (year, stat). This module reads
those back into analysis-ready frames and does the numeric coercion deliberately
deferred at scrape time (the API returns every value as a string).

Notebooks should import from here rather than parse JSON themselves, so the parsing
logic stays in one tested place.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

SEASON_ROOT = Path("data/tour_season")
EVENT_ROOT = Path("data/players_championship")

# Keys present on every flattened row that are not stat values.
_NON_STAT_KEYS = {"rank", "player"}


def _to_number(value) -> float:
    """Coerce a raw PGA Tour stat string to a float, or NaN if it isn't numeric.

    Handles the real shapes the API returns: thousands separators ("36,794"),
    percent signs ("55.5%"), signed values ("+2", "-3"), and the non-numeric
    placeholders ("-", "", "E", None) that would otherwise crash float().
    """
    if value is None:
        return np.nan
    text = str(value).strip().replace(",", "").replace("%", "")
    if text in ("", "-", "E"):
        return np.nan
    try:
        return float(text)
    except ValueError:
        return np.nan


def load_season_stats(root: Path = SEASON_ROOT, years: list[int] | None = None) -> pd.DataFrame:
    """Load cached season stats into a long tidy frame.

    Returns columns [year, player, stat_id, stat_title, category, value], one row per
    (year, player, stat). `value` is the stat's headline number — the first stat column
    after rank/player (e.g. Avg for driving distance) — coerced to float. Empty stat
    files (season-only blanks) are skipped. Pass `years` to restrict which to load.
    """
    records = []
    for year_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        year = int(year_dir.name)
        if years is not None and year not in years:
            continue
        for path in sorted(year_dir.glob("*.json")):
            payload = json.loads(path.read_text())
            for row in payload["rows"]:
                stat_keys = [k for k in row if k not in _NON_STAT_KEYS]
                headline = row[stat_keys[0]] if stat_keys else None
                records.append(
                    {
                        "year": year,
                        "player": row["player"],
                        "stat_id": payload["stat_id"],
                        "stat_title": payload["stat_title"],
                        "category": payload["category"],
                        "value": _to_number(headline),
                    }
                )
    return pd.DataFrame(records)


def players_at_event(root: Path = EVENT_ROOT, years: list[int] | None = None) -> set[str]:
    """Return the set of players who teed up at THE PLAYERS in the cached event years.

    Reads the event-stat files and unions every player who appears in any of them — so
    a player counts if they recorded any stat at THE PLAYERS at least once. Player names
    come from the same API field as the season data, so they match exactly (no fuzzy
    matching needed). Use this set to subset the season data to tournament attendees.
    """
    players: set[str] = set()
    for year_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        year = int(year_dir.name)
        if years is not None and year not in years:
            continue
        for path in year_dir.glob("*.json"):
            payload = json.loads(path.read_text())
            for row in payload["rows"]:
                players.add(row["player"])
    return players


def player_stat_matrix(long_df: pd.DataFrame, year: int | None = None) -> pd.DataFrame:
    """Pivot the long frame to a wide player x stat matrix of headline values.

    Index is player (or (year, player) when multiple years are present); columns are
    stat_title; cells are the headline value. Missing (player, stat) combinations
    become NaN — which is exactly what the missingness analysis inspects.
    """
    df = long_df if year is None else long_df[long_df["year"] == year]
    index = "player" if df["year"].nunique() <= 1 else ["year", "player"]
    return df.pivot_table(index=index, columns="stat_title", values="value")
