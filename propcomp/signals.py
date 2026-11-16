from __future__ import annotations

FIELDS = {
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
}

EDGE = {
    "pts": 3.0,
    "reb": 1.5,
    "ast": 1.2,
    "fg3m": 0.7,
    "stl": 0.4,
    "blk": 0.4,
    "pra": 4.0,
}

POSITIONS = ("pg", "sg", "sf", "pf", "c")


def stat_value(game: dict, code: str) -> float | None:
    fields = FIELDS.get(code)
    if not fields:
        return None
    total = 0.0
    for field in fields:
        value = game.get(field)
        if value is None:
            return None
        total += value
    return total


def mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def recent_values(history: list[dict], code: str, count: int = 5) -> list[float]:
    values = []
    for game in history:
        if (game.get("seconds") or 0) <= 0:
            continue
        value = stat_value(game, code)
        if value is None:
            continue
        values.append(value)
        if len(values) >= count:
            break
    return values


def choose_star(lines: list[tuple[str, float | None]], history: list[dict]) -> dict | None:
    """One total per player: the widest recent gap that is also cleared most often."""
    scored = []
    for code, line in lines:
        if line is None or code not in EDGE:
            continue
        recent = recent_values(history, code, 5)
        season = recent_values(history, code, 30)
        if len(recent) < 4 or len(season) < 4:
            continue
        recent_avg = mean(recent) or 0
        margin = recent_avg - line
        if margin <= 0:
            continue
        clears = sum(1 for value in season if value > line)
        played = len(season)
        rate = clears / played
        if rate < 0.5:
            continue
        scored.append(
            {
                "code": code,
                "line": line,
                "avg": recent_avg,
                "margin": margin,
                "clears": clears,
                "played": played,
                "rate": rate,
            }
        )
    if not scored:
        return None
    margin_order = sorted(range(len(scored)), key=lambda index: scored[index]["margin"], reverse=True)
    rate_order = sorted(
        range(len(scored)),
        key=lambda index: (scored[index]["rate"], scored[index]["clears"], scored[index]["margin"]),
        reverse=True,
    )
    margin_rank = {index: rank for rank, index in enumerate(margin_order)}
    rate_rank = {index: rank for rank, index in enumerate(rate_order)}
    winner_index = min(
        range(len(scored)),
        key=lambda index: (
            margin_rank[index] + rate_rank[index],
            -scored[index]["margin"],
            -scored[index]["rate"],
        ),
    )
    winner = scored[winner_index]
    line_text = _number(winner["line"])
    why = (
        f"Last 5 average {_number(winner['avg'])} clears {line_text} by {_number(winner['margin'])}. "
        f"Cleared {line_text} in {winner['clears']} of {winner['played']} games."
    )
    return {"code": winner["code"], "line": winner["line"], "why": [why]}


def _number(value: float) -> str:
    text = f"{value:.1f}"
    if text.endswith(".0"):
        return text[:-2]
    return text
