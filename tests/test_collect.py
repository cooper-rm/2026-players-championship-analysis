"""Tests for the bulk collector.

No network and no real data/ writes: we stub the scraper functions and use the
`tmp_path` fixture (a throwaway temp dir, unique per test) for all file output.

Note on patching: collect.py does `from scrape_pgatour import fetch_event_stat`,
so inside collect that name lives at `collect.fetch_event_stat`. We patch it THERE,
where it is looked up — patching scrape_pgatour.fetch_event_stat would not affect
collect's already-imported reference.
"""

import json

import src.collect as collect
from src.collect import bulk_pull, players_tournament_id, pull_stat_to_disk


def test_players_tournament_id():
    # the one magic string, isolated: R<year>011
    assert players_tournament_id(2026) == "R2026011"
    assert players_tournament_id(2022) == "R2022011"


def test_pull_stat_to_disk_writes_then_caches(monkeypatch, tmp_path):
    calls = {"n": 0}

    def fake_fetch(stat_id, tournament_id, year, *a, **k):
        calls["n"] += 1
        return [{"rank": 1, "player": "Cameron Young", "Avg": "3.663"}]

    monkeypatch.setattr(collect, "fetch_event_stat", fake_fetch)

    # first call: pulls and writes
    status = pull_stat_to_disk("02675", 2026, "Strokes Gained", "SG: Total", out_root=tmp_path)
    assert status == "ok"

    path = tmp_path / "2026" / "02675.json"
    assert path.exists()
    payload = json.loads(path.read_text())
    assert payload["stat_id"] == "02675"
    assert payload["tournament_id"] == "R2026011"
    assert payload["rows"][0]["player"] == "Cameron Young"

    # second call: file already there -> cached, and fetch is NOT called again.
    # This is the idempotency that makes the 2,900-request run resumable.
    status_again = pull_stat_to_disk("02675", 2026, out_root=tmp_path)
    assert status_again == "cached"
    assert calls["n"] == 1


def test_pull_stat_to_disk_empty_event(monkeypatch, tmp_path):
    # event with no rows for this stat -> "empty", but still cached so we don't refetch
    monkeypatch.setattr(collect, "fetch_event_stat", lambda *a, **k: [])
    status = pull_stat_to_disk("99999", 2026, out_root=tmp_path)
    assert status == "empty"
    assert (tmp_path / "2026" / "99999.json").exists()


def test_bulk_pull_skips_cancelled_year_and_tallies(monkeypatch, tmp_path):
    catalog = [{"category": "SG", "stat_id": "02675", "stat_title": "SG: Total"}]
    monkeypatch.setattr(collect, "fetch_stat_catalog", lambda year: catalog)

    pulled_years = []

    def fake_pull(stat_id, year, *a, **k):
        pulled_years.append(year)
        return "ok"

    monkeypatch.setattr(collect, "pull_stat_to_disk", fake_pull)

    result = bulk_pull(years=[2020, 2026], out_root=tmp_path, delay=0)

    # 2020 is in CANCELLED_YEARS -> skipped entirely; only 2026 is pulled
    assert pulled_years == [2026]
    assert result["totals"]["ok"] == 1
    assert result["totals"]["error"] == 0


def test_bulk_pull_survives_per_stat_error(monkeypatch, tmp_path):
    catalog = [{"category": "SG", "stat_id": "BAD", "stat_title": "x"}]
    monkeypatch.setattr(collect, "fetch_stat_catalog", lambda year: catalog)

    def boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(collect, "pull_stat_to_disk", boom)

    # one bad stat must be logged and counted, never crash the whole run
    result = bulk_pull(years=[2026], out_root=tmp_path, delay=0)
    assert result["totals"]["error"] == 1
    assert len(result["errors"]) == 1
    assert result["errors"][0][1] == "BAD"  # (year, stat_id, message)
