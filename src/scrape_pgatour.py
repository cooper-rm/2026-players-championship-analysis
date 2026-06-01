"""PGA Tour stats client — pulls per-event strokes-gained and traditional stats.

The PGA Tour has no public API; its website is served by an undocumented GraphQL
backend at orchestrator.pgatour.com. This module talks to that backend directly so
we can pull per-tournament data (e.g. THE PLAYERS 2026) that Data Golf paywalls.

The x-api-key below is NOT a secret — it's the public key shipped in the PGA Tour's
own website JavaScript, the same one every visitor's browser sends. It is committed
on purpose; this project needs no private credentials to run.

The notebook reads cached files from data/, never this module — so the analysis
stays reproducible offline and we only scrape at pull time.
"""

from __future__ import annotations

import requests

PGATOUR_GRAPHQL_URL = "https://orchestrator.pgatour.com/graphql"
# Public key embedded in pgatour.com's own frontend — not a credential of ours.
PGATOUR_API_KEY = "da2-gsrx5bibzbb4njvhl7t37wqyl4"
# Browser-like UA; some PGA Tour edges reject obviously-scripted clients.
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
# Seconds before we give up on a request, so a hung server can't freeze us.
REQUEST_TIMEOUT = 30

# Strokes-gained stat IDs (the website's own statId values). Swap into the query
# to pull each table; all share the same statDetails shape.
STATS = {
    "sg_total": "02675",
    "sg_ott": "02567",
    "sg_app": "02568",
    "sg_arg": "02569",
    "sg_putt": "02564",
}


def fetch_stat_catalog(year: int = 2026) -> list[dict]:
    """Return the full PGA Tour stat catalog as [{category, stat_id, stat_title}].

    Pulls statOverview (the same catalog the website's stat menu is built from) so
    we never hardcode the ~580 stat IDs. Each entry is enough to drive a per-event
    pull: feed stat_id into fetch_event_stat.
    """
    query = f"""query {{
      statOverview(tourCode: R, year: {year}) {{
        categories {{
          displayName
          subCategories {{ stats {{ statId statTitle }} }}
        }}
      }}
    }}"""
    categories = _post_graphql(query)["statOverview"]["categories"]
    catalog = []
    for category in categories:
        for sub in category["subCategories"]:
            for stat in sub["stats"]:
                catalog.append(
                    {
                        "category": category["displayName"],
                        "stat_id": stat["statId"],
                        "stat_title": stat["statTitle"],
                    }
                )
    return catalog


def _post_graphql(query: str) -> dict:
    """POST a GraphQL query to the PGA Tour orchestrator and return its `data` block.

    Every scrape goes through here so the endpoint, public key, UA, and timeout live
    in one place. GraphQL replies with HTTP 200 even when a query is invalid, putting
    the failure in an `errors` array instead — so we inspect that array and raise,
    rather than trusting the status code and letting bad data through silently.
    """
    response = requests.post(
        PGATOUR_GRAPHQL_URL,
        json={"query": query},
        headers={"x-api-key": PGATOUR_API_KEY, "User-Agent": USER_AGENT},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()  # catch real HTTP failures (5xx, blocked, etc.)
    payload = response.json()
    if payload.get("errors"):
        raise RuntimeError(f"PGA Tour GraphQL error: {payload['errors']}")
    return payload["data"]


def fetch_event_stat(
    stat_id: str,
    tournament_id: str,
    year: int = 2026,
    query_type: str = "EVENT_ONLY",
) -> list[dict]:
    """Pull one stat table for one tournament as a flat list of per-player dicts.

    stat_id is a PGA Tour statId (see STATS), tournament_id is a pill id like
    "R2026011" (THE PLAYERS 2026). query_type is EVENT_ONLY (that week's values) or
    THROUGH_EVENT (season-to-date through it).

    Each player row comes back as {rank, player, <statName>: <value>, ...} so the
    list drops straight into pd.DataFrame(). Stat values stay as strings — the API
    returns "14.653" as text and numeric coercion is a deliberate later step.
    """
    query = f"""query {{
      statDetails(
        tourCode: R, statId: "{stat_id}", year: {year},
        eventQuery: {{tournamentId: "{tournament_id}", queryType: {query_type}}}
      ) {{
        rows {{
          __typename
          ... on StatDetailsPlayer {{
            rank
            playerName
            stats {{ statName statValue }}
          }}
        }}
      }}
    }}"""
    rows = _post_graphql(query)["statDetails"]["rows"]
    players = []
    for row in rows:
        if row.get("__typename") != "StatDetailsPlayer":
            continue  # skip any non-player rows (section headers, etc.)
        flat = {"rank": row["rank"], "player": row["playerName"]}
        for stat in row["stats"]:
            flat[stat["statName"]] = stat["statValue"]
        players.append(flat)
    return players


def fetch_event_all_stats(
    tournament_id: str,
    year: int = 2026,
    query_type: str = "EVENT_ONLY",
) -> list[dict]:
    """Pull all five SG categories for one event, merged to one row per player.

    Each SG table is collapsed to its per-round "Avg" value, renamed to the category
    (sg_total, sg_ott, ...), and merged on player name. We keep `rounds` (from the
    SG-Total table) since it flags who made the cut, and drop the redundant "Total SG"
    columns (Total = Avg x rounds). Values stay as strings — coercion is a later step.

    Returns a list of {rank, player, rounds, sg_total, sg_ott, sg_app, sg_arg, sg_putt},
    or an empty list for an event with no measured rounds (e.g. 2020, cancelled).
    """
    merged: dict[str, dict] = {}
    for category, stat_id in STATS.items():
        for row in fetch_event_stat(stat_id, tournament_id, year, query_type):
            player = row["player"]
            record = merged.setdefault(player, {"player": player})
            record[category] = row["Avg"]  # this table's per-round category value
            if category == "sg_total":  # carry rank + rounds from the SG-Total table
                record["rank"] = row["rank"]
                record["rounds"] = row["Measured Rounds"]
    # order columns predictably; sort by finish-equivalent SG-Total rank
    ordered = sorted(merged.values(), key=lambda r: r.get("rank", 9999))
    columns = ["rank", "player", "rounds", *STATS]
    return [{c: rec.get(c) for c in columns} for rec in ordered]
