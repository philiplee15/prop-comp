from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

USER_AGENT = "prop-comp/1.0 (personal research board)"


def get_json(url: str, timeout: int = 45, retries: int = 4):
    last_error = None
    for attempt in range(retries):
        request = urllib.request.Request(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return None
            last_error = error
            if error.code in {429, 500, 502, 503, 504}:
                time.sleep(1.2 * (attempt + 1))
                continue
            raise
        except Exception as error:
            last_error = error
            time.sleep(0.8 * (attempt + 1))
    raise RuntimeError(f"failed to fetch {url}") from last_error


def scoreboard(slate: str) -> dict:
    compact = slate.replace("-", "")
    url = (
        "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
        f"?dates={compact}"
    )
    return get_json(url) or {"events": []}


def teams() -> list[dict]:
    url = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams?limit=50"
    payload = get_json(url) or {}
    leagues = payload.get("sports", [{}])[0].get("leagues", [{}])
    return [item["team"] for item in leagues[0].get("teams", [])]


def depth_chart(team_id: str) -> dict | None:
    url = (
        "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/"
        f"{team_id}/depthcharts"
    )
    return get_json(url)


def roster(team_id: str) -> list[dict]:
    url = (
        "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/"
        f"{team_id}/roster"
    )
    payload = get_json(url) or {}
    return payload.get("athletes") or []


def athlete(player_id: str) -> dict | None:
    url = (
        "https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba/"
        f"seasons/2027/athletes/{player_id}"
    )
    return get_json(url)


def prop_bets(event_id: str) -> list[dict] | None:
    rows: list[dict] = []
    page = 1
    page_count = 1
    while page <= page_count:
        url = (
            "https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba/"
            f"events/{event_id}/competitions/{event_id}/odds/100/propBets"
            f"?limit=500&page={page}"
        )
        payload = get_json(url)
        if payload is None:
            return None if page == 1 else rows
        if page == 1:
            page_count = int(payload.get("pageCount") or 1)
        rows.extend(payload.get("items") or [])
        page += 1
    return rows


def game_odds(event_id: str) -> dict | None:
    url = (
        "https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba/"
        f"events/{event_id}/competitions/{event_id}/odds/100"
    )
    return get_json(url)


def summary(event_id: str) -> dict | None:
    url = (
        "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary"
        f"?event={event_id}"
    )
    return get_json(url, timeout=60)
