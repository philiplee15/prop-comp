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


def minutes_profile(history: list[dict], count: int = 5) -> dict:
    sample = [game for game in history if (game.get("seconds") or 0) > 0][:count]
    minutes = [(game.get("seconds") or 0) / 60 for game in sample]
    starts = [1 if game.get("starter") else 0 for game in sample]
    return {
        "games": len(sample),
        "minutes": mean(minutes) or 0,
        "floor": min(minutes) if minutes else 0,
        "starter_rate": mean(starts) or 0,
    }


def families(pos: str | None) -> set[str]:
    key = (pos or "").lower()
    if key in {"pg", "g"}:
        return {"guard"}
    if key == "sg":
        return {"guard", "wing"}
    if key in {"sf", "f"}:
        return {"wing"}
    if key == "pf":
        return {"wing", "big"}
    if key == "c":
        return {"big"}
    return set()


def clear_reasons(
    code: str,
    line: float | None,
    history: list[dict],
    avail: dict | None,
    out_teammates: list[dict],
) -> list[str]:
    if line is None or code not in EDGE:
        return []
    if avail and avail.get("status") == "out":
        return []
    recent = recent_values(history, code, 5)
    season = recent_values(history, code, 30)
    if len(recent) < 4:
        return []
    recent_avg = mean(recent) or 0
    season_avg = mean(season) if len(season) >= 8 else None
    profile = minutes_profile(history, 5)
    edge = EDGE[code]
    reasons = []

    if recent_avg >= line + edge:
        reasons.append(
            f"Last 5 average {recent_avg:.1f} clears {line:g} by {recent_avg - line:.1f}."
        )

    secure = (
        profile["games"] >= 4
        and profile["minutes"] >= 30
        and profile["floor"] >= 24
        and profile["starter_rate"] >= 0.8
        and recent_avg >= line + (edge * 0.6)
    )
    if secure:
        reasons.append(
            f"Last 5 average {recent_avg:.1f} against {line:g}, with {profile['minutes']:.0f} minutes a night and none under {profile['floor']:.0f}."
        )

    replaces = (avail or {}).get("replaces") or ""
    new_start = (avail or {}).get("role") == "starter" and profile["starter_rate"] < 0.5
    if new_start and recent_avg >= line + (edge * 0.4):
        who = replaces or "a starter"
        reasons.append(
            f"Projects to start in place of {who}, which should add minutes. Last 5 average {recent_avg:.1f}."
        )
    elif out_teammates and recent_avg >= line:
        spot = ((avail or {}).get("pos") or "").upper()
        shared = [
            mate
            for mate in out_teammates
            if spot and spot == (mate.get("pos") or "").upper() and mate["minutes"] >= 26
        ]
        if shared and profile["minutes"] >= 18 and recent_avg >= line + (edge * 0.5):
            names = ", ".join(mate["name"] for mate in shared[:2])
            if len(shared) == 1:
                reasons.append(
                    f"{names} is out and plays the same spot. Last 5 average {recent_avg:.1f} against {line:g}."
                )
            else:
                reasons.append(
                    f"{names} are out and play the same spot. Last 5 average {recent_avg:.1f} against {line:g}."
                )

    if (
        season_avg is not None
        and recent_avg >= season_avg * 0.85
        and line <= season_avg * 0.88
        and line <= recent_avg - (edge * 1.4)
    ):
        reasons.append(
            f"Line {line:g} is light against a {season_avg:.1f} season average and a {recent_avg:.1f} last-5 average."
        )
    return reasons
