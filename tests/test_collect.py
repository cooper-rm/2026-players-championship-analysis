"""Tests for the bulk collector (season + event).

No network and no real data/ writes: we stub the scraper functions and use the
`tmp_path` fixture (a throwaway temp dir, unique per test) for all file output.

We patch names where collect.py looks them up (on the collect module itself),
not where they are defined in scrape_pgatour.
"""

import json

import src.collect as collect
from src.collect import (
    bulk_pull_event,
    bulk_pull_season,
    players_tournament_id,
    pull_event_stat_to_disk,
    pull_season_stat_to_disk,
)


def test_players_tournament_id():
    # the one magic string, isolated: R<year>011
    assert players_tournament_id(2026) == "R2026011"
    assert players_tournament_id(2022) == "R2022011"


def test_pull_season_stat_writes_then_caches(monkeypatch, tmp_path):
    calls = {"n": 0}

    def fake_fetch(stat_id, year):
        calls["n"] += 1
        return [{"rank": 1, "player": "Cameron Champ", "Avg": "322.8"}]

    monkeypatch.setattr(collect, "fetch_season_stat", fake_fetch)

    status = pull_season_stat_to_disk("101", 2024, "Off The Tee", "Driving Distance", out_root=tmp_path)
    assert status == "ok"

    payload = json.loads((tmp_path / "2024" / "101.json").read_text())
    assert payload["stat_id"] == "101"
    assert payload["rows"][0]["player"] == "Cameron Champ"
    assert "tournament_id" not in payload  # season data has no single event id

    # second call: cached, fetch NOT called again -> resumable
    assert pull_season_stat_to_disk("101", 2024, out_root=tmp_path) == "cached"
    assert calls["n"] == 1


def test_pull_season_stat_empty(monkeypatch, tmp_path):
    monkeypatch.setattr(collect, "fetch_season_stat", lambda *a, **k: [])
    status = pull_season_stat_to_disk("99999", 2024, out_root=tmp_path)
    assert status == "empty"
    assert (tmp_path / "2024" / "99999.json").exists()


def test_pull_event_stat_records_tournament_id(monkeypatch, tmp_path):
    monkeypatch.setattr(
        collect, "fetch_event_stat",
        lambda stat_id, tid, year: [{"rank": 1, "player": "Cameron Young", "Avg": "3.663"}],
    )
    status = pull_event_stat_to_disk("02675", 2026, "Strokes Gained", "SG: Total", out_root=tmp_path)
    assert status == "ok"
    payload = json.loads((tmp_path / "2026" / "02675.json").read_text())
    assert payload["tournament_id"] == "R2026011"  # event payload carries the event id
    assert payload["rows"][0]["player"] == "Cameron Young"


def test_bulk_pull_season_tallies(monkeypatch, tmp_path):
    catalog = [{"category": "Off The Tee", "stat_id": "101", "stat_title": "Driving Distance"}]
    monkeypatch.setattr(collect, "fetch_stat_catalog", lambda year: catalog)

    pulled = []
    monkeypatch.setattr(
        collect, "pull_season_stat_to_disk",
        lambda sid, yr, *a, **k: (pulled.append((sid, yr)) or "ok"),
    )

    result = bulk_pull_season(years=[2024, 2026], out_root=tmp_path, delay=0)
    assert pulled == [("101", 2024), ("101", 2026)]  # no year skipped for season
    assert result["totals"]["ok"] == 2
    assert result["totals"]["error"] == 0


def test_bulk_pull_event_skips_cancelled_year(monkeypatch, tmp_path):
    catalog = [{"category": "SG", "stat_id": "02675", "stat_title": "SG: Total"}]
    monkeypatch.setattr(collect, "fetch_stat_catalog", lambda year: catalog)

    pulled_years = []
    monkeypatch.setattr(
        collect, "pull_event_stat_to_disk",
        lambda sid, yr, *a, **k: (pulled_years.append(yr) or "ok"),
    )

    result = bulk_pull_event(years=[2020, 2026], out_root=tmp_path, delay=0)
    assert pulled_years == [2026]  # 2020 cancelled -> skipped
    assert result["totals"]["ok"] == 1


def test_bulk_survives_per_stat_error(monkeypatch, tmp_path):
    catalog = [{"category": "SG", "stat_id": "BAD", "stat_title": "x"}]
    monkeypatch.setattr(collect, "fetch_stat_catalog", lambda year: catalog)

    def boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(collect, "pull_season_stat_to_disk", boom)

    result = bulk_pull_season(years=[2024], out_root=tmp_path, delay=0)
    assert result["totals"]["error"] == 1
    assert result["errors"][0][1] == "BAD"  # (year, stat_id, message)
