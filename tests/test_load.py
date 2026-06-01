"""Tests for the data loader.

Numeric coercion is tested directly; the file-loading functions are tested against
a tiny fake data tree built in tmp_path, so no real data/ files are needed.
"""

import json

import numpy as np
import pytest

from src.load import (
    _to_number,
    load_season_stats,
    player_stat_matrix,
    players_at_event,
)


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("322.8", 322.8),
        ("36,794", 36794.0),   # thousands separator
        ("55.5%", 55.5),       # percent sign
        ("+2", 2.0),           # signed
        ("-3", -3.0),
        ("0", 0.0),
    ],
)
def test_to_number_parses_numeric(raw, expected):
    assert _to_number(raw) == expected


@pytest.mark.parametrize("raw", ["-", "", "E", None, "n/a"])
def test_to_number_nan_on_non_numeric(raw):
    assert np.isnan(_to_number(raw))


def _write_stat_file(root, year, stat_id, stat_title, category, rows):
    out_dir = root / str(year)
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "stat_id": stat_id, "year": year, "category": category,
        "stat_title": stat_title, "rows": rows,
    }
    (out_dir / f"{stat_id}.json").write_text(json.dumps(payload))


def test_load_season_stats_long_shape(tmp_path):
    _write_stat_file(
        tmp_path, 2024, "101", "Driving Distance", "Off The Tee",
        [
            {"rank": 1, "player": "Champ", "Avg": "322.8", "Total Distance": "36,794"},
            {"rank": 2, "player": "McIlroy", "Avg": "320.2", "Total Distance": "44,183"},
        ],
    )
    df = load_season_stats(root=tmp_path)

    assert list(df.columns) == ["year", "player", "stat_id", "stat_title", "category", "value"]
    assert len(df) == 2
    # headline = first stat column (Avg), coerced to float
    champ = df[df["player"] == "Champ"].iloc[0]
    assert champ["value"] == 322.8
    assert champ["stat_title"] == "Driving Distance"


def test_load_season_stats_skips_empty_and_filters_years(tmp_path):
    _write_stat_file(tmp_path, 2023, "101", "Driving Distance", "Off The Tee",
                     [{"rank": 1, "player": "A", "Avg": "300.0"}])
    _write_stat_file(tmp_path, 2024, "999", "Empty Stat", "Streaks", [])  # empty -> no rows
    _write_stat_file(tmp_path, 2024, "101", "Driving Distance", "Off The Tee",
                     [{"rank": 1, "player": "A", "Avg": "305.0"}])

    # all years: 2 rows (the empty file contributes nothing)
    assert len(load_season_stats(root=tmp_path)) == 2
    # year filter
    only_2023 = load_season_stats(root=tmp_path, years=[2023])
    assert set(only_2023["year"]) == {2023}
    assert len(only_2023) == 1


def test_players_at_event_unions_across_years(tmp_path):
    # different players each year -> the set is the union
    _write_stat_file(tmp_path, 2024, "02675", "SG: Total", "Strokes Gained",
                     [{"rank": 1, "player": "Young", "Avg": "3.6"},
                      {"rank": 2, "player": "Fitzpatrick", "Avg": "3.4"}])
    _write_stat_file(tmp_path, 2025, "02675", "SG: Total", "Strokes Gained",
                     [{"rank": 1, "player": "McIlroy", "Avg": "3.7"},
                      {"rank": 2, "player": "Young", "Avg": "3.0"}])
    assert players_at_event(root=tmp_path) == {"Young", "Fitzpatrick", "McIlroy"}
    assert players_at_event(root=tmp_path, years=[2024]) == {"Young", "Fitzpatrick"}


def test_player_stat_matrix_pivots_wide(tmp_path):
    _write_stat_file(tmp_path, 2024, "101", "Driving Distance", "Off The Tee",
                     [{"rank": 1, "player": "Champ", "Avg": "322.8"}])
    _write_stat_file(tmp_path, 2024, "102", "Driving Accuracy", "Off The Tee",
                     [{"rank": 1, "player": "Champ", "Avg": "55.5"}])
    long_df = load_season_stats(root=tmp_path)
    wide = player_stat_matrix(long_df, year=2024)

    assert wide.loc["Champ", "Driving Distance"] == 322.8
    assert wide.loc["Champ", "Driving Accuracy"] == 55.5
