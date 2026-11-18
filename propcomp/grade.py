from __future__ import annotations

import re

OU_FIELDS = {
    "Total Points": ("pts",),
    "Total Rebounds": ("reb",),
    "Total Assists": ("ast",),
    "Total 3-Point Field Goals": ("fg3m",),
    "Total Steals": ("stl",),
    "Total Blocks": ("blk",),
    "Total Turnovers": ("tov",),
    "Total Points and Rebounds": ("pts", "reb"),
    "Total Points and Assists": ("pts", "ast"),
    "Total Assists and Rebounds": ("ast", "reb"),
    "Total Points, Rebounds, and Assists": ("pts", "reb", "ast"),
    "Total Steals and Blocks": ("stl", "blk"),
}

MILESTONE_FIELDS = {
    "Points Milestones": ("pts",),
    "Rebounds Milestones": ("reb",),
    "Assists Milestones": ("ast",),
    "3-Point Field Goals Milestones": ("fg3m",),
    "Steals Milestones": ("stl",),
    "Blocks Milestones": ("blk",),
    "Turnovers Milestones": ("tov",),
    "Points + Rebounds Milestones": ("pts", "reb"),
    "Points + Assists Milestones": ("pts", "ast"),
    "Rebounds + Assists Milestones": ("reb", "ast"),
    "Points + Assists + Rebounds Milestones": ("pts", "reb", "ast"),
    "Steals + Blocks Milestones": ("stl", "blk"),
}

YES_MARKETS = {
    "First Basket": "first",
    "1st Team FG Scorer": "teamfg",
    "1st Team FG Scorer Exact": "teamfg",
    "1st 3PT FG Scorer": "first3",
    "To Record a Double Double": "dd",
    "To Record a Triple Double": "td",
}

CORE_MARKETS = [
    {"code": "pts", "label": "PTS", "name": "Total Points"},
    {"code": "reb", "label": "REB", "name": "Total Rebounds"},
    {"code": "ast", "label": "AST", "name": "Total Assists"},
    {"code": "fg3m", "label": "3PM", "name": "Total 3-Point Field Goals"},
    {"code": "pra", "label": "PRA", "name": "Total Points, Rebounds, and Assists"},
    {"code": "stl", "label": "STL", "name": "Total Steals"},
    {"code": "blk", "label": "BLK", "name": "Total Blocks"},
    {"code": "dd", "label": "DD", "name": "To Record a Double Double"},
    {"code": "first", "label": "1ST", "name": "First Basket"},
]

QUARTER_WORDS = {"1st": 1, "2nd": 2, "3rd": 3, "4th": 4}
QUARTER_STAT = {
    "Points": "pts",
    "Rebounds": "reb",
    "Assists": "ast",
    "Steals": "stl",
    "Blocks": "blk",
    "3-Point Field Goals": "fg3m",
    "Turnovers": "tov",
}
QUARTER_RE = re.compile(
    r"^(Points|Rebounds|Assists|Steals|Blocks|3-Point Field Goals|Turnovers)"
    r"(?: \+ (Rebounds|Assists|Blocks))?"
    r"(?: \+ (Rebounds|Assists))?"
    r" Milestones - (1st|2nd|3rd|4th) Quarter$"
)
QUARTER_TOTAL_RE = re.compile(
    r"^Total (First|Second|Third|Fourth) Quarter "
    r"(Points|Rebounds|Assists|Steals|Blocks|3-Point Field Goals|Turnovers)$"
)
QUARTER_TOTAL_WORD = {"First": 1, "Second": 2, "Third": 3, "Fourth": 4}

COUNTING_CATEGORIES = ("pts", "reb", "ast", "stl", "blk")


def parse_line(display: str | None) -> float | None:
    if not display:
        return None
    cleaned = display.replace("+", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def american_value(price: str | None) -> int:
    if not price:
        return 0
    try:
        return int(str(price).replace("+", ""))
    except ValueError:
        return 0


def kind_for(market: str) -> str:
    if market in OU_FIELDS or quarter_total_spec(market):
        return "ou"
    if market in MILESTONE_FIELDS or "Milestones" in market:
        return "milestone"
    if market in YES_MARKETS:
        return "yesno"
    return "other"


def code_for(market: str) -> str:
    if market in OU_FIELDS:
        return {
            ("pts",): "pts",
            ("reb",): "reb",
            ("ast",): "ast",
            ("fg3m",): "fg3m",
            ("stl",): "stl",
            ("blk",): "blk",
            ("tov",): "tov",
            ("pts", "reb"): "pr",
            ("pts", "ast"): "pa",
            ("ast", "reb"): "ra",
            ("pts", "reb", "ast"): "pra",
            ("stl", "blk"): "sb",
        }[OU_FIELDS[market]]
    if market in MILESTONE_FIELDS:
        return code_for_fields(MILESTONE_FIELDS[market]) + "_ms"
    if market in YES_MARKETS:
        return YES_MARKETS[market]
    quarter = quarter_spec(market) or quarter_total_spec(market)
    if quarter:
        stat, period = quarter
        return f"{stat}_q{period}"
    slug = re.sub(r"[^a-z0-9]+", "_", market.lower()).strip("_")
    return slug[:40] or "other"


def code_for_fields(fields: tuple[str, ...]) -> str:
    return {
        ("pts",): "pts",
        ("reb",): "reb",
        ("ast",): "ast",
        ("fg3m",): "fg3m",
        ("stl",): "stl",
        ("blk",): "blk",
        ("tov",): "tov",
        ("pts", "reb"): "pr",
        ("pts", "ast"): "pa",
        ("reb", "ast"): "ra",
        ("ast", "reb"): "ra",
        ("pts", "reb", "ast"): "pra",
        ("stl", "blk"): "sb",
    }.get(fields, "_".join(fields))


def quarter_total_spec(market: str) -> tuple[str, int] | None:
    match = QUARTER_TOTAL_RE.match(market)
    if not match:
        return None
    return QUARTER_STAT[match.group(2)], QUARTER_TOTAL_WORD[match.group(1)]


def quarter_spec(market: str) -> tuple[str, int] | None:
    match = QUARTER_RE.match(market)
    if not match:
        return None
    names = [part for part in match.groups()[:3] if part]
    period = QUARTER_WORDS[match.group(4)]
    stats = tuple(QUARTER_STAT[name] for name in names)
    return code_for_fields(stats), period


def sum_fields(stats: dict, fields: tuple[str, ...]) -> float | None:
    total = 0
    for field in fields:
        value = stats.get(field)
        if value is None:
            return None
        total += value
    return total


def grade_number(actual: float, line: float, kind: str) -> str:
    if kind == "milestone":
        return "yes" if actual + 1e-9 >= line else "no"
    if actual > line + 1e-9:
        return "over"
    if actual < line - 1e-9:
        return "under"
    return "push"


def double_digit_count(stats: dict) -> int:
    return sum(1 for field in COUNTING_CATEGORIES if (stats.get(field) or 0) >= 10)


def grade_prop(prop: dict, player: dict | None, context: dict | None) -> tuple[str, float | None]:
    """Return result and the actual used to grade it.

    Results: over, under, push, yes, no, void, pending, ungraded.
    """
    if player is None or not player.get("played"):
        return "void", None
    market = prop["market"]
    kind = prop["kind"]
    context = context or {}

    if market == "To Record a Double Double":
        actual = double_digit_count(player)
        return ("yes" if actual >= 2 else "no"), actual
    if market == "To Record a Triple Double":
        actual = double_digit_count(player)
        return ("yes" if actual >= 3 else "no"), actual
    if market == "First Basket":
        hit = context.get("first_basket") == player.get("player_id")
        return ("yes" if hit else "no"), 1 if hit else 0
    if market == "1st 3PT FG Scorer":
        hit = context.get("first_three") == player.get("player_id")
        return ("yes" if hit else "no"), 1 if hit else 0
    if market in {"1st Team FG Scorer", "1st Team FG Scorer Exact"}:
        by_team = context.get("first_team_fg") or {}
        hit = by_team.get(player.get("team_id")) == player.get("player_id")
        return ("yes" if hit else "no"), 1 if hit else 0

    fields = OU_FIELDS.get(market) or MILESTONE_FIELDS.get(market)
    if fields:
        actual = sum_fields(player, fields)
        if actual is None or prop.get("line_num") is None:
            return "ungraded", actual
        return grade_number(actual, prop["line_num"], kind), actual

    quarter = quarter_spec(market) or quarter_total_spec(market)
    if quarter:
        stat_code, period = quarter
        grade_kind = "milestone" if quarter_spec(market) else "ou"
        bucket = (player.get("quarters") or {}).get(period) or empty_quarter()
        fields = fields_for_code(stat_code)
        if not fields:
            return "ungraded", None
        actual = sum_fields(bucket, fields)
        if actual is None or prop.get("line_num") is None:
            return "ungraded", actual
        return grade_number(actual, prop["line_num"], grade_kind), actual

    return "ungraded", None


def fields_for_code(code: str) -> tuple[str, ...] | None:
    return {
        "pts": ("pts",),
        "reb": ("reb",),
        "ast": ("ast",),
        "fg3m": ("fg3m",),
        "stl": ("stl",),
        "blk": ("blk",),
        "tov": ("tov",),
        "pr": ("pts", "reb"),
        "pa": ("pts", "ast"),
        "ra": ("reb", "ast"),
        "pra": ("pts", "reb", "ast"),
        "sb": ("stl", "blk"),
    }.get(code)


def parse_box_stats(labels: list[str], values: list[str]) -> dict:
    indexed = {label: value for label, value in zip(labels, values)}

    def whole(label: str) -> int:
        raw = indexed.get(label) or "0"
        head = str(raw).split("-")[0]
        try:
            return int(head)
        except ValueError:
            return 0

    def made(label: str) -> int:
        raw = indexed.get(label) or "0-0"
        head = str(raw).split("-")[0]
        try:
            return int(head)
        except ValueError:
            return 0

    def pair(label: str) -> tuple[int | None, int | None]:
        raw = indexed.get(label)
        if raw is None:
            return None, None
        parts = str(raw).split("-")
        if len(parts) < 2:
            return None, None
        try:
            return int(parts[0]), int(parts[1])
        except ValueError:
            return None, None

    def plus_minus(label: str) -> int | None:
        raw = indexed.get(label)
        if raw is None:
            return None
        text = str(raw).strip().replace("+", "")
        if not any(character.isdigit() for character in text):
            return None
        try:
            return int(text)
        except ValueError:
            return None

    fgm, fga = pair("FG")
    fg3m, fg3a = pair("3PT")
    ftm, fta = pair("FT")
    minutes = str(indexed.get("MIN") or "")
    return {
        "minutes": minutes,
        "seconds": minutes_to_seconds(minutes),
        "pts": whole("PTS"),
        "reb": whole("REB"),
        "ast": whole("AST"),
        "fg3m": fg3m if fg3m is not None else made("3PT"),
        "fg3a": fg3a,
        "fgm": fgm,
        "fga": fga,
        "ftm": ftm,
        "fta": fta,
        "oreb": whole("OREB") if "OREB" in indexed else None,
        "plus_minus": plus_minus("+/-"),
        "stl": whole("STL"),
        "blk": whole("BLK"),
        "tov": whole("TO"),
    }


def minutes_to_seconds(minutes: str) -> int:
    text = (minutes or "").strip()
    if not text or any(character.isalpha() for character in text):
        return 0
    if ":" in text:
        parts = text.split(":")
        try:
            return int(parts[0]) * 60 + int(parts[1])
        except ValueError:
            return 0
    try:
        return int(float(text) * 60)
    except ValueError:
        return 0


def empty_quarter() -> dict:
    return {"pts": 0, "reb": 0, "ast": 0, "fg3m": 0, "stl": 0, "blk": 0, "tov": 0}


def consume_play(play: dict, quarters: dict[str, dict[int, dict]]) -> None:
    text = play.get("text") or ""
    type_text = (play.get("type") or {}).get("text") or ""
    period = int((play.get("period") or {}).get("number") or 0)
    if period < 1:
        return
    participants = [
        str((item.get("athlete") or {}).get("id"))
        for item in (play.get("participants") or [])
        if (item.get("athlete") or {}).get("id")
    ]
    if not participants:
        return

    def bucket(player_id: str) -> dict:
        player_quarters = quarters.setdefault(player_id, {})
        row = player_quarters.get(period)
        if row is None:
            row = empty_quarter()
            player_quarters[period] = row
        return row

    lowered = text.lower()
    if play.get("scoringPlay"):
        points = int(play.get("scoreValue") or 0)
        bucket(participants[0])["pts"] += points
        if "three point" in lowered:
            bucket(participants[0])["fg3m"] += 1
        if "assist" in lowered and len(participants) > 1:
            bucket(participants[1])["ast"] += 1
    if "rebound" in type_text.lower():
        bucket(participants[0])["reb"] += 1
    if "steals" in lowered and len(participants) > 1:
        bucket(participants[1])["stl"] += 1
    if "block" in lowered and len(participants) > 1:
        bucket(participants[1])["blk"] += 1
    if "turnover" in lowered and "steals" not in lowered:
        bucket(participants[0])["tov"] += 1


def first_three(plays: list[dict]) -> str | None:
    ordered = sorted(plays, key=lambda play: int(play.get("sequenceNumber") or 0))
    for play in ordered:
        if not play.get("scoringPlay"):
            continue
        text = (play.get("text") or "").lower()
        if "three point" not in text and "3-pt" not in text and "3pt" not in text:
            continue
        participants = play.get("participants") or []
        if not participants:
            continue
        player_id = str((participants[0].get("athlete") or {}).get("id") or "")
        if player_id:
            return player_id
    return None


def first_baskets(plays: list[dict]) -> tuple[str | None, dict[str, str]]:
    first_player = None
    by_team: dict[str, str] = {}
    ordered = sorted(plays, key=lambda play: int(play.get("sequenceNumber") or 0))
    for play in ordered:
        if not play.get("scoringPlay"):
            continue
        type_text = ((play.get("type") or {}).get("text") or "").lower()
        if "free throw" in type_text:
            continue
        participants = play.get("participants") or []
        if not participants:
            continue
        player_id = str((participants[0].get("athlete") or {}).get("id") or "")
        team_id = str((play.get("team") or {}).get("id") or "")
        if not player_id:
            continue
        if first_player is None:
            first_player = player_id
        if team_id and team_id not in by_team:
            by_team[team_id] = player_id
        if first_player and len(by_team) >= 2:
            break
    return first_player, by_team
