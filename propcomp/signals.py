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

STAR_CODES = {"pts", "reb", "ast", "fg3m", "stl", "blk", "pra"}

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


def qualifying_stars(lines: list[tuple[str, float | None]], history: list[dict]) -> list[dict]:
    """Every total whose line sits under the last five average and has cleared more than 70%."""
    scored = []
    for code, line in lines:
        if line is None or code not in STAR_CODES:
            continue
        recent = recent_values(history, code, 5)
        season = recent_values(history, code, 30)
        if len(recent) < 5 or len(season) < 5:
            continue
        recent_avg = mean(recent) or 0
        if not line < recent_avg:
            continue
        clears = sum(1 for value in season if value > line)
        played = len(season)
        rate = clears / played
        if not rate > 0.7:
            continue
        line_text = _number(line)
        why = (
            f"Last 5 average {_number(recent_avg)} is above {line_text}. "
            f"Cleared {line_text} in {clears} of {played} games."
        )
        scored.append(
            {
                "code": code,
                "line": line,
                "avg": recent_avg,
                "margin": recent_avg - line,
                "clears": clears,
                "played": played,
                "rate": rate,
                "why": [why],
            }
        )
    return scored


def choose_star(lines: list[tuple[str, float | None]], history: list[dict]) -> dict | None:
    found = qualifying_stars(lines, history)
    if not found:
        return None
    return max(found, key=lambda item: (item["rate"], item["margin"]))


def _number(value: float) -> str:
    text = f"{value:.1f}"
    if text.endswith(".0"):
        return text[:-2]
    return text
