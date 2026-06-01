"""Tests for the pgatour.com scraper.

These tests never touch the network. We replace the one function that does I/O
(`_post_graphql`, or `requests.post` underneath it) with a stub returning canned
data, then assert our parsing/merging logic is correct. Run from repo root: pytest

Key pytest tools used:
- monkeypatch.setattr(obj, name, fake): swap a function for a stub, undone after the test.
- We patch names where they are *looked up* (here, on the scrape_pgatour module itself).
"""

import pytest

import src.scrape_pgatour as sp
from src.scrape_pgatour import (
    fetch_event_all_stats,
    fetch_event_stat,
    fetch_season_stat,
    fetch_stat_catalog,
)


# --------------------------------------------------------------------------
# _post_graphql — the only function that actually hits the network.
# We fake requests.post so no real request fires.
# --------------------------------------------------------------------------

class _FakeResponse:
    """Minimal stand-in for requests.Response with the two methods we call."""

    def __init__(self, payload, http_ok=True):
        self._payload = payload
        self._http_ok = http_ok

    def raise_for_status(self):
        if not self._http_ok:
            raise sp.requests.HTTPError("simulated HTTP failure")

    def json(self):
        return self._payload


def test_post_graphql_returns_data_block(monkeypatch):
    monkeypatch.setattr(
        sp.requests, "post", lambda *a, **k: _FakeResponse({"data": {"hi": "there"}})
    )
    assert sp._post_graphql("{ hi }") == {"hi": "there"}


def test_post_graphql_raises_on_graphql_errors(monkeypatch):
    # GraphQL returns HTTP 200 but reports failures in an `errors` array — we must
    # inspect that array and raise, not trust the status code.
    monkeypatch.setattr(
        sp.requests,
        "post",
        lambda *a, **k: _FakeResponse({"errors": [{"message": "bad field"}]}),
    )
    with pytest.raises(RuntimeError, match="GraphQL error"):
        sp._post_graphql("{ nope }")


def test_post_graphql_raises_on_http_error(monkeypatch):
    monkeypatch.setattr(
        sp.requests, "post", lambda *a, **k: _FakeResponse({}, http_ok=False)
    )
    with pytest.raises(sp.requests.HTTPError):
        sp._post_graphql("{ x }")


# --------------------------------------------------------------------------
# fetch_event_stat — flattens nested {stats:[{statName,statValue}]} rows.
# Stub _post_graphql to return canned statDetails.
# --------------------------------------------------------------------------

def _stat_details(rows):
    return {"statDetails": {"rows": rows}}


def test_fetch_event_stat_flattens_players(monkeypatch):
    rows = [
        {
            "__typename": "StatDetailsPlayer",
            "rank": 1,
            "playerName": "Cameron Young",
            "stats": [
                {"statName": "Avg", "statValue": "3.663"},
                {"statName": "Measured Rounds", "statValue": "4"},
            ],
        }
    ]
    monkeypatch.setattr(sp, "_post_graphql", lambda q: _stat_details(rows))
    assert fetch_event_stat("02675", "R2026011") == [
        {"rank": 1, "player": "Cameron Young", "Avg": "3.663", "Measured Rounds": "4"}
    ]


def test_fetch_event_stat_skips_non_player_rows(monkeypatch):
    rows = [
        {"__typename": "StatDetailsSection", "title": "a header row"},  # skip
        {
            "__typename": "StatDetailsPlayer",
            "rank": 1,
            "playerName": "Real Player",
            "stats": [{"statName": "Avg", "statValue": "1.0"}],
        },
    ]
    monkeypatch.setattr(sp, "_post_graphql", lambda q: _stat_details(rows))
    out = fetch_event_stat("02675", "R2026011")
    assert len(out) == 1
    assert out[0]["player"] == "Real Player"


# --------------------------------------------------------------------------
# fetch_season_stat — same flattening, season-long (no event filter).
# --------------------------------------------------------------------------

def test_fetch_season_stat_flattens(monkeypatch):
    rows = [
        {
            "__typename": "StatDetailsPlayer",
            "rank": 1,
            "playerName": "Cameron Champ",
            "stats": [{"statName": "Avg", "statValue": "322.8"}],
        }
    ]
    monkeypatch.setattr(sp, "_post_graphql", lambda q: _stat_details(rows))
    assert fetch_season_stat("101", 2024) == [
        {"rank": 1, "player": "Cameron Champ", "Avg": "322.8"}
    ]


# --------------------------------------------------------------------------
# fetch_event_all_stats — merges the 5 SG tables, one row per player.
# Stub fetch_event_stat to return a different Avg per stat_id.
# --------------------------------------------------------------------------

def test_fetch_event_all_stats_merges_categories(monkeypatch):
    per_stat = {
        "02675": [{"rank": 1, "player": "Cameron Young", "Avg": "3.663",
                   "Measured Rounds": "4"}],            # sg_total carries rank+rounds
        "02567": [{"rank": 1, "player": "Cameron Young", "Avg": "0.767"}],   # sg_ott
        "02568": [{"rank": 1, "player": "Cameron Young", "Avg": "1.770"}],   # sg_app
        "02569": [{"rank": 1, "player": "Cameron Young", "Avg": "-0.078"}],  # sg_arg
        "02564": [{"rank": 1, "player": "Cameron Young", "Avg": "1.203"}],   # sg_putt
    }
    monkeypatch.setattr(sp, "fetch_event_stat", lambda stat_id, *a, **k: per_stat[stat_id])
    assert fetch_event_all_stats("R2026011") == [
        {
            "rank": 1, "player": "Cameron Young", "rounds": "4",
            "sg_total": "3.663", "sg_ott": "0.767", "sg_app": "1.770",
            "sg_arg": "-0.078", "sg_putt": "1.203",
        }
    ]


def test_fetch_event_all_stats_empty_event(monkeypatch):
    # a cancelled event (e.g. 2020) yields no rows from any table -> empty result
    monkeypatch.setattr(sp, "fetch_event_stat", lambda *a, **k: [])
    assert fetch_event_all_stats("R2020011") == []


# --------------------------------------------------------------------------
# fetch_stat_catalog — flattens categories -> subCategories -> stats.
# --------------------------------------------------------------------------

def test_fetch_stat_catalog_flattens(monkeypatch):
    payload = {
        "statOverview": {
            "categories": [
                {
                    "displayName": "Strokes Gained",
                    "subCategories": [{"stats": [{"statId": "02675", "statTitle": "SG: Total"}]}],
                },
                {
                    "displayName": "Off The Tee",
                    "subCategories": [
                        {"stats": [
                            {"statId": "101", "statTitle": "Driving Distance"},
                            {"statId": "102", "statTitle": "Driving Accuracy"},
                        ]}
                    ],
                },
            ]
        }
    }
    monkeypatch.setattr(sp, "_post_graphql", lambda q: payload)
    assert fetch_stat_catalog() == [
        {"category": "Strokes Gained", "stat_id": "02675", "stat_title": "SG: Total"},
        {"category": "Off The Tee", "stat_id": "101", "stat_title": "Driving Distance"},
        {"category": "Off The Tee", "stat_id": "102", "stat_title": "Driving Accuracy"},
    ]
