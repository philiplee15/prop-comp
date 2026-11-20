"""PrizePicks edges from a no-vig sportsbook price.

The comparison is the one in the line-comparison method: same player, same
stat, same number. The sportsbook's two prices are turned into a fair chance
by dividing out the vig. A side is usable when that chance clears the
break-even rate of a PrizePicks slip.

FanDuel's published prices are the labeled book. The site key below is the
public key the FanDuel website sends with its own pages. It is not an account
credential, and reading it does not place a bet. ESPN's DraftKings prop feed
stores both prices and does not say which one is the over, so it cannot pick
a side.
"""

from __future__ import annotations

import json
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from propcomp.db import DOCS

ET = ZoneInfo("America/New_York")
PUBLIC_APP_KEY = "FhMFpcPWXMeyZxOx"
BOOK_HOST = "https://sbapi.nj.sportsbook.fanduel.com"
PRIZEPICKS_URL = (
    "https://partner-api.prizepicks.com/projections"
    "?league_id=7&per_page=250&single_stat=true"
)
BROWSER = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}
BOOK_TABS = ("player-points", "player-rebounds", "player-assists", "player-combos", "player-threes")
STAT_LABEL = {
    "pts": "Points",
    "reb": "Rebounds",
    "ast": "Assists",
    "pra": "PRA",
    "fg3m": "Threes",
}
# Total return, including the stake, from PrizePicks' player-pick payout page.
POWER_PAYOUT = {2: 3.0, 3: 6.0, 4: 10.0, 5: 20.0, 6: 37.5}
FLEX_PAYOUT = {
    2: {2: 2.0, 1: 0.5},
    3: {3: 3.0, 2: 1.0},
    4: {4: 6.0, 3: 1.5},
    5: {5: 10.0, 4: 2.0, 3: 0.4},
    6: {6: 25.0, 5: 2.0, 4: 0.4},
}
SLIP_ORDER = ("6-flex", "5-flex", "6-power", "5-power", "3-power", "4-power", "2-power")


def american_implied(price: int) -> float:
    price = int(price)
    if price < 0:
        return abs(price) / (abs(price) + 100)
    if price == 0:
        raise ValueError("a zero American price is not a probability")
    return 100 / (price + 100)


def devig(over_price: int, under_price: int) -> tuple[float, float]:
    """Remove the vig by scaling the two implied chances so they sum to 1."""
    over = american_implied(over_price)
    under = american_implied(under_price)
    total = over + under
    return over / total, under / total


def slip_ev(probs: list[float], pays: dict[int, float]) -> float:
    """Expected total return for a $1 entry. 1.0 is break-even. Legs are independent."""
    count = len(probs)
    expected = 0.0
    for mask in range(1 << count):
        chance = 1.0
        hits = 0
        for index, prob in enumerate(probs):
            if mask & (1 << index):
                chance *= prob
                hits += 1
            else:
                chance *= 1 - prob
        expected += chance * pays.get(hits, 0.0)
    return expected


def break_even(count: int, pays: dict[int, float]) -> float:
    """Fair chance, if every leg is equal, that returns the stake on average."""
    low = 0.45
    high = 0.8
    for _ in range(48):
        mid = (low + high) / 2
        if slip_ev([mid] * count, pays) < 1:
            low = mid
        else:
            high = mid
    return (low + high) / 2


def slip_table() -> list[dict]:
    rows = []
    for count, payout in POWER_PAYOUT.items():
        pays = {count: payout}
        rows.append(
            {
                "id": f"{count}-power",
                "label": f"{count}-pick Power",
                "kind": "power",
                "count": count,
                "payout": f"{payout:g}x",
                "bar": break_even(count, pays),
                "pays": pays,
            }
        )
    for count, pays in FLEX_PAYOUT.items():
        top = pays[count]
        rows.append(
            {
                "id": f"{count}-flex",
                "label": f"{count}-pick Flex",
                "kind": "flex",
                "count": count,
                "payout": f"{top:g}x",
                "bar": break_even(count, pays),
                "pays": pays,
            }
        )
    rows.sort(key=lambda row: SLIP_ORDER.index(row["id"]) if row["id"] in SLIP_ORDER else 99)
    return rows


def check_math() -> None:
    over, under = devig(116, -154)
    if abs(under - 0.567) > 0.004:
        raise RuntimeError(f"no-vig under for +116/-154 was {under:.4f}")
    over, under = devig(-110, -110)
    if abs(over - 0.5) > 0.001 or abs(under - 0.5) > 0.001:
        raise RuntimeError("a -110/-110 line did not devig to a coin flip")
    power = break_even(2, {2: 3.0})
    if abs(power - 3 ** -0.5) > 0.0002:
        raise RuntimeError(f"2-pick power break-even was {power:.4f}")
    flex = break_even(5, FLEX_PAYOUT[5])
    if not 0.53 < flex < 0.56:
        raise RuntimeError(f"5-pick flex break-even was {flex:.4f}")
    if stat_code("Pts + Reb + Ast") != "pra" or stat_code("Points") != "pts":
        raise RuntimeError("stat names did not map")
    if stat_code("Pts + Ast") is not None or stat_code("Rebounds") != "reb":
        raise RuntimeError("combo stats did not stay separate from single stats")


def request_json(url: str, headers: dict, retries: int = 4) -> dict:
    last_error = None
    for attempt in range(retries):
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=40) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            last_error = error
            if error.code in {429, 500, 502, 503, 504}:
                time.sleep(8 * (attempt + 1))
                continue
            raise
        except Exception as error:
            last_error = error
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"failed to fetch {url}") from last_error


def normalize_name(name: str) -> str:
    text = unicodedata.normalize("NFKD", name or "")
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.lower().replace(".", " ")
    cleaned = []
    for char in text:
        cleaned.append(char if char.isalnum() or char.isspace() else " ")
    return " ".join("".join(cleaned).split())


def stat_code(label: str) -> str | None:
    text = " ".join((label or "").lower().replace("+", " ").replace("-", " ").split())
    if any(word in text for word in ("quarter", "half", "period")):
        return None
    tokens = set(text.split())
    has_points = "point" in text or bool(tokens & {"pt", "pts"})
    has_rebounds = "rebound" in text or bool(tokens & {"reb", "rebs"})
    has_assists = "assist" in text or bool(tokens & {"ast", "asts"})
    if has_points and has_rebounds and has_assists:
        return "pra"
    if "three" in text or "3 pt" in text or "3pt" in text:
        return "fg3m"
    if has_points and not has_rebounds and not has_assists:
        return "pts"
    if has_rebounds and not has_points and not has_assists:
        return "reb"
    if has_assists and not has_points and not has_rebounds:
        return "ast"
    return None


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo("UTC"))
    return parsed


def book_events() -> list[dict]:
    url = (
        f"{BOOK_HOST}/api/content-managed-page?page=CUSTOM&customPageId=nba"
        f"&includePrices=true&_ak={PUBLIC_APP_KEY}"
    )
    payload = request_json(url, BROWSER)
    events = (payload.get("attachments") or {}).get("events") or {}
    rows = []
    for event in events.values():
        name = event.get("name") or ""
        if " @ " not in name or "(" in name:
            continue
        start = parse_time(event.get("openDate"))
        if start is None:
            continue
        rows.append({"id": str(event.get("eventId")), "name": name, "start": start})
    return rows


def slate_of(events: list[dict], now: datetime) -> datetime.date:
    upcoming = [event["start"] for event in events if event["start"] >= now - timedelta(hours=3)]
    if not upcoming:
        upcoming = [event["start"] for event in events]
    dates = sorted({moment.astimezone(ET).date() for moment in upcoming})
    today = now.astimezone(ET).date()
    future = [day for day in dates if day >= today]
    return future[0] if future else dates[-1]


def book_lines(events: list[dict]) -> list[dict]:
    lines = []
    seen = set()
    for event in events:
        for tab in BOOK_TABS:
            url = (
                f"{BOOK_HOST}/api/event-page?includePrices=true"
                f"&usePlayerPropsVirtualMarket=true&_ak={PUBLIC_APP_KEY}"
                f"&eventId={event['id']}&tab={tab}"
            )
            try:
                payload = request_json(url, BROWSER)
            except Exception as error:
                print(f"book tab skipped {event['name']} {tab}: {error}", flush=True)
                continue
            markets = (payload.get("attachments") or {}).get("markets") or {}
            for market in markets.values():
                parsed = parse_book_market(market, event)
                for line in parsed:
                    key = (line["name_key"], line["stat"], line["line"], line["event_id"])
                    if key in seen:
                        continue
                    seen.add(key)
                    lines.append(line)
            time.sleep(0.05)
    return lines


def parse_book_market(market: dict, event: dict) -> list[dict]:
    name = market.get("marketName") or ""
    if " - " not in name:
        return []
    player, kind = name.rsplit(" - ", 1)
    code = stat_code(kind)
    if code is None:
        return []
    by_line: dict[float, dict[str, int]] = {}
    for runner in market.get("runners") or []:
        side = runner_side(runner.get("runnerName") or "")
        price = ((runner.get("winRunnerOdds") or {}).get("americanDisplayOdds") or {}).get("americanOdds")
        handicap = runner.get("handicap")
        if side is None or price is None or handicap in (None, ""):
            continue
        try:
            number = round(float(handicap), 1)
            american = int(price)
        except (TypeError, ValueError):
            continue
        by_line.setdefault(number, {})[side] = american
    rows = []
    for number, sides in by_line.items():
        if "over" not in sides or "under" not in sides:
            continue
        rows.append(
            {
                "player": player.strip(),
                "name_key": normalize_name(player),
                "stat": code,
                "line": number,
                "over": sides["over"],
                "under": sides["under"],
                "event_id": event["id"],
                "game": event["name"],
                "start": event["start"],
            }
        )
    return rows


def runner_side(name: str) -> str | None:
    text = name.strip().lower()
    if text == "over" or text.endswith(" over"):
        return "over"
    if text == "under" or text.endswith(" under"):
        return "under"
    return None


def prizepicks_lines(day) -> list[dict]:
    headers = dict(BROWSER)
    headers["Referer"] = "https://app.prizepicks.com/"
    headers["Origin"] = "https://app.prizepicks.com"
    payload = request_json(PRIZEPICKS_URL, headers)
    players = {}
    for row in payload.get("included") or []:
        if row.get("type") == "new_player":
            players[str(row.get("id"))] = row.get("attributes") or {}
    lines = []
    seen = set()
    for row in payload.get("data") or []:
        parsed = parse_prizepick(row, players, day)
        if parsed is None:
            continue
        key = (parsed["name_key"], parsed["stat"], parsed["line"])
        if key in seen:
            continue
        seen.add(key)
        lines.append(parsed)
    return lines


def parse_prizepick(row: dict, players: dict, day) -> dict | None:
    attributes = row.get("attributes") or {}
    if attributes.get("status") != "pre_game":
        return None
    if attributes.get("is_promo") or attributes.get("in_game"):
        return None
    if attributes.get("projection_type") not in (None, "Single Stat"):
        return None
    odds_type = (attributes.get("odds_type") or "standard").lower()
    if odds_type in {"demon", "goblin"}:
        return None
    code = stat_code(attributes.get("stat_type") or attributes.get("stat_display_name") or "")
    if code is None:
        return None
    start = parse_time(attributes.get("start_time"))
    if start is None or start.astimezone(ET).date() != day:
        return None
    try:
        number = round(float(attributes.get("line_score")), 1)
    except (TypeError, ValueError):
        return None
    relation = ((row.get("relationships") or {}).get("new_player") or {}).get("data") or {}
    person = players.get(str(relation.get("id"))) or {}
    name = person.get("name") or person.get("display_name")
    if not name:
        return None
    allowed = attributes.get("allowed_wager_types")
    if isinstance(allowed, list):
        allowed = " ".join(str(item) for item in allowed)
    return {
        "player": name,
        "team": person.get("team") or attributes.get("description") or "",
        "name_key": normalize_name(name),
        "stat": code,
        "line": number,
        "start": start,
        "game_id": attributes.get("game_id") or "",
        "allowed": (allowed or "both").lower(),
    }


def side_allowed(allowed: str, side: str) -> bool:
    text = (allowed or "").lower()
    offers_over = "over" in text
    offers_under = "under" in text
    if offers_over and not offers_under:
        return side == "over"
    if offers_under and not offers_over:
        return side == "under"
    return True


def compare(book: list[dict], picks: list[dict], slips: list[dict]) -> list[dict]:
    floor = min(slip["bar"] for slip in slips)
    by_key = {(line["name_key"], line["stat"], line["line"]): line for line in book}
    legs = []
    for pick in picks:
        priced = by_key.get((pick["name_key"], pick["stat"], pick["line"]))
        if priced is None:
            continue
        fair_over, fair_under = devig(priced["over"], priced["under"])
        if fair_over >= fair_under:
            side, fair = "over", fair_over
        else:
            side, fair = "under", fair_under
        if not side_allowed(pick["allowed"], side):
            continue
        cleared = [slip["id"] for slip in slips if fair + 1e-9 >= slip["bar"]]
        tip = priced["start"].astimezone(ET)
        legs.append(
            {
                "player": pick["player"],
                "team": pick["team"],
                "stat": pick["stat"],
                "stat_label": STAT_LABEL[pick["stat"]],
                "line": pick["line"],
                "side": side,
                "fair": round(fair, 4),
                "over": priced["over"],
                "under": priced["under"],
                "game": priced["game"],
                "event_id": priced["event_id"],
                "tip": tip.strftime("%a %-I:%M %p ET"),
                "clears": cleared,
                "playable": fair + 1e-9 >= floor,
            }
        )
    legs.sort(key=lambda leg: (-leg["fair"], leg["player"]))
    return legs


def one_per_player(legs: list[dict]) -> list[dict]:
    chosen = []
    seen = set()
    for leg in legs:
        key = leg["player"].lower()
        if key in seen:
            continue
        seen.add(key)
        chosen.append(leg)
    return chosen


def build_slip(slip: dict, legs: list[dict]) -> dict | None:
    pool = [leg for leg in one_per_player(legs) if leg["fair"] + 1e-9 >= slip["bar"]]
    if len(pool) < slip["count"]:
        return None
    chosen = []
    used_events = set()
    rest = []
    for leg in pool:
        if leg["event_id"] in used_events:
            rest.append(leg)
            continue
        chosen.append(leg)
        used_events.add(leg["event_id"])
        if len(chosen) == slip["count"]:
            break
    same_game = False
    if len(chosen) < slip["count"]:
        for leg in rest:
            chosen.append(leg)
            same_game = True
            if len(chosen) == slip["count"]:
                break
    if len(chosen) < slip["count"]:
        return None
    probs = [leg["fair"] for leg in chosen]
    return {
        "id": slip["id"],
        "label": slip["label"],
        "payout": slip["payout"],
        "bar": round(slip["bar"], 4),
        "ev": round(slip_ev(probs, slip["pays"]), 3),
        "same_game": same_game,
        "legs": [
            {
                "player": leg["player"],
                "team": leg["team"],
                "stat_label": leg["stat_label"],
                "line": leg["line"],
                "side": leg["side"],
                "fair": leg["fair"],
                "game": leg["game"],
            }
            for leg in chosen
        ],
    }


def board(now: datetime | None = None) -> dict:
    check_math()
    moment = now or datetime.now(ZoneInfo("UTC"))
    events = book_events()
    if not events:
        raise RuntimeError("the sportsbook feed returned no NBA games")
    day = slate_of(events, moment)
    events = [event for event in events if event["start"].astimezone(ET).date() == day]
    print(f"Reading {len(events)} games for {day.isoformat()}", flush=True)
    book = book_lines(events)
    print(f"Sportsbook lines: {len(book)}", flush=True)
    picks = prizepicks_lines(day)
    print(f"PrizePicks lines: {len(picks)}", flush=True)
    slips = slip_table()
    matched = compare(book, picks, slips)
    playable = [leg for leg in matched if leg["playable"]]
    legs = playable if len(playable) >= 12 else matched[:12]
    wanted = [slip for slip in slips if slip["id"] in SLIP_ORDER]
    built = [row for row in (build_slip(slip, playable) for slip in wanted) if row]
    public_slips = [
        {key: value for key, value in slip.items() if key != "pays"}
        for slip in slips
    ]
    return {
        "pulled_at": moment.astimezone(ET).strftime("%a %b %-d, %-I:%M %p ET"),
        "slate": day.isoformat(),
        "book": "FanDuel published prices",
        "counts": {
            "games": len(events),
            "book": len(book),
            "prizepicks": len(picks),
            "matched": len(matched),
            "playable": sum(1 for leg in matched if leg["playable"]),
        },
        "slips": public_slips,
        "cards": built,
        "legs": legs,
    }


def publish(now: datetime | None = None) -> dict:
    payload = board(now)
    path = DOCS / "data" / "edge.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n")
    print(
        f"Edge board: {payload['counts']['playable']} playable lines, "
        f"{len(payload['cards'])} slips, wrote {path}",
        flush=True,
    )
    return payload


def main() -> None:
    publish()


if __name__ == "__main__":
    main()
