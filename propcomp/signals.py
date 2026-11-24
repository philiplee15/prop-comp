from __future__ import annotations

import math

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

# Clear rate of the gated sample this season. Blocks stayed under a coin flip.
# Remeasured through Nov 22, 2026: the same strict-over shape on blocks cashed 10 of 21.
MARKET_WEIGHT = {
    "reb": 1.0,
    "stl": 0.95,
    "pts": 0.6,
    "pra": 0.4,
    "fg3m": 0.25,
    "ast": 0.25,
    "blk": 0.0,
}

MARKET_LABEL = {
    "pts": "Points",
    "reb": "Rebounds",
    "ast": "Assists",
    "fg3m": "Threes",
    "pra": "PRA",
    "stl": "Steals",
    "blk": "Blocks",
}

STAR_CODES = {code for code, weight in MARKET_WEIGHT.items() if weight > 0}

POSITIONS = ("pg", "sg", "sf", "pf", "c")

CLEAR_RATE = 0.80
CUSHION_MAX = 3.5
MOVE_MAX = 1.0
SPIKE_GAP = 12.0
MAKE_TAX_MAX = 2.0
VOID_RATIO = 0.60
VOID_MINUTES = 12.0
RAMP_MINUTES = 24.0
SCRIPT_SPREAD = -8.0
PRIOR_GAMES = 5


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


def median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[mid])
    return (ordered[mid - 1] + ordered[mid]) / 2


def recent_values(history: list[dict], code: str, count: int = 5) -> list[float]:
    values = []
    for game in reversed(played_rows(history)):
        value = stat_value(game, code)
        if value is None:
            continue
        values.append(value)
        if len(values) >= count:
            break
    return values


def played_rows(history: list[dict]) -> list[dict]:
    rows = [game for game in history if (game.get("seconds") or 0) > 0]
    rows.sort(key=lambda game: (game.get("slate_date") or "", game.get("tip_utc") or "", game.get("game_id") or ""))
    return rows


def earlier_history(history: list[dict], game: dict) -> list[dict]:
    """Games already played before this slate. Later games must not leak into the call."""
    game_id = game.get("id") or game.get("game_id")
    slate = game.get("slate_date") or ""
    tip = game.get("tip_utc") or game.get("tip") or ""
    kept = []
    for item in history or []:
        if game_id and item.get("game_id") == game_id:
            continue
        item_slate = item.get("slate_date") or ""
        item_tip = item.get("tip_utc") or ""
        if slate and item_slate:
            if item_slate < slate:
                kept.append(item)
            continue
        if tip and item_tip and item_tip < tip:
            kept.append(item)
    return kept


def qualifying_stars(
    lines: list[tuple],
    history: list[dict],
    *,
    starter: bool = False,
    spread: str | None = None,
    team: str | None = None,
) -> list[dict]:
    """Posted numbers that pass every clear-star gate."""
    found = []
    for spec in lines:
        code = spec[0]
        line = spec[1]
        open_line = spec[2] if len(spec) > 2 else None
        decision = evaluate_line(
            code,
            line,
            open_line,
            history,
            starter=starter,
            spread=spread,
            team=team,
        )
        if decision and decision["star"]:
            found.append(decision)
    return found


def choose_star(lines: list[tuple], history: list[dict]) -> dict | None:
    found = qualifying_stars(lines, history)
    if not found:
        return None
    return max(found, key=lambda item: (item["weight"], item["rate"], item["margin"]))


def evaluate_line(
    code: str,
    line: float | None,
    open_line: float | None,
    history: list[dict],
    *,
    starter: bool = False,
    spread: str | None = None,
    team: str | None = None,
) -> dict | None:
    if line is None or code not in MARKET_WEIGHT or MARKET_WEIGHT[code] <= 0:
        return None
    rows = played_rows(history)
    profile = _profile(rows, code)
    if profile is None or profile["block"]:
        return None
    if script_blocks(code, starter, spread, team):
        return None
    if _moved(line, open_line) >= MOVE_MAX:
        return None
    # Through Nov 22, 2026 a strict over on threes cashed 19 of 29 at 0.5 and 36 of 72
    # at 1.5 and higher. The higher number is a coin flip, so it does not star.
    # A 0.5 is one make. The 3.5 cushion does not bind on it.
    if code == "fg3m" and line >= 1.5:
        return None
    if not _line_passes(profile, line):
        return None
    margin = profile["avg"] - line
    why = _why(code, line, open_line, profile, margin)
    return {
        "code": code,
        "line": line,
        "avg": profile["avg"],
        "median": profile["median"],
        "margin": margin,
        "clears": profile["clears"],
        "played": profile["played"],
        "rate": profile["rate"],
        "weight": MARKET_WEIGHT[code],
        "star": True,
        "why": [why],
    }


def market_cap(
    history: list[dict],
    code: str,
    *,
    starter: bool = False,
    spread: str | None = None,
    team: str | None = None,
) -> dict | None:
    if code not in MARKET_WEIGHT or MARKET_WEIGHT[code] <= 0:
        return None
    rows = played_rows(history)
    profile = _profile(rows, code)
    if profile is None or profile["block"]:
        return None
    if script_blocks(code, starter, spread, team):
        return None
    cap = _highest_half(profile)
    if code == "fg3m" and cap is not None and cap >= 1.5:
        cap = 0.5 if _line_passes(profile, 0.5) else None
    if cap is None:
        return None
    return {
        "code": code,
        "label": MARKET_LABEL.get(code, code),
        "cap": cap,
        "avg": round(profile["avg"], 2),
        "median": profile["median"],
        "clears": profile["clears"],
        "played": profile["played"],
        "rate": round(profile["rate"], 3),
        "weight": MARKET_WEIGHT[code],
    }


DIP_FLOOR = {"pts": 8, "pra": 10, "reb": 3.5, "ast": 3, "fg3m": 2, "stl": 1.5, "blk": 1.5}


def project_call(
    code: str,
    line: float | None,
    open_line: float | None,
    history: list[dict],
    *,
    starter: bool = False,
    spread: str | None = None,
    team: str | None = None,
) -> dict | None:
    """Project over or under from the pregame paths that actually preceded misses."""
    if line is None or code not in FIELDS:
        return None
    rows = played_rows(history)
    if len(rows) < PRIOR_GAMES:
        return None
    values = [stat_value(game, code) for game in rows]
    if any(value is None for value in values[-PRIOR_GAMES:]):
        return None
    recent = [float(value) for value in values[-PRIOR_GAMES:]]
    season = [float(value) for value in values if value is not None]
    if len(season) < PRIOR_GAMES:
        return None
    average = mean(recent) or 0
    middle = median(recent) or 0
    clears = sum(1 for value in season if value > line)
    rate = clears / len(season)
    # Walk-forward on this season: a minute cut, a three-game minute slide, or a
    # vanished shot diet finishes under about 57 to 59 percent when the number has
    # not come down with the role. Stacking a low clear rate, a half-point gap, a
    # one-point move, or a 12-point spike on their own stays at the 52 percent base.
    # Opponent, rest, and home-road splits were measured and did not beat the line.
    # A tight last-five spread, a line sitting a full season standard deviation
    # under the mean, a 90 percent clear rate, and a cold last-game z-score were
    # walk-forward tested on the same overs through Nov 22, 2026. Each cohort
    # cashed worse than the ungated 272 of 474. Those reads stay off the gate.
    # Shot volume already enters through the attempt void. A cold field-goal
    # night was measured earlier and did not beat the line either.
    # A single short night is not that cut. Points, PRA, threes, and assists came
    # back when the minutes came back, so those markets wait for a second short night.
    # Rebounds and steals can still be under when the number is at least a point
    # above the recent average, because that read does not need the minutes to stay short.
    role: list[tuple[int, str]] = []
    cut = _minute_cut(rows)
    durable = bool(cut) and _cut_is_durable(rows)
    gap = line - average
    # One short night does not tell you the next night's minutes. Points, PRA,
    # threes, and assists stay unmarked on both sides until a second short night.
    if cut and not durable and code in {"pts", "pra", "fg3m", "ast"}:
        return None
    board_night = (
        bool(cut)
        and not durable
        and code in {"reb", "stl"}
        and gap >= 1
        and rate < 0.50
    )
    if cut and durable:
        last_min, base_min = cut
        role.append((
            3,
            f"Minutes fell to {_number(last_min)} from a {_number(base_min)} last-five base, "
            "and more than one of the last three nights was short. "
            "A cut that lasts more than one game has finished under 59% of the time when the number stays up.",
        ))
    elif board_night:
        last_min, base_min = cut
        role.append((
            4,
            f"{_number(line)} is {_number(gap)} above the last five average of {_number(average)}. "
            f"He has cleared {_number(line)} in {clears} of {len(season)} games ({round(rate * 100)}%). "
            f"Last game was {_number(last_min)} minutes against a {_number(base_min)} base. "
            "That was one night, not a new minute base, so this is the board level and not a minute projection.",
        ))
    # A shot void on the same night as a minute cut is the short night counted twice.
    void = code in {"pts", "pra", "fg3m"} and _attempt_void(rows) and not cut
    if void:
        last = rows[-1]
        prior_shots = [game.get("fga") for game in rows[-6:-1] if game.get("fga") is not None]
        base_shots = mean([float(value) for value in prior_shots]) or 0
        role.append((
            2,
            f"Last game was {int(last.get('fga') or 0)} shots after a {_number(base_shots)} attempt base. "
            "The volume vanished while he was on the floor.",
        ))
    slide = _minute_slide(rows)
    if slide and not cut:
        role.append((
            2,
            f"Minutes have stepped down three games in a row, to {_number(slide)}.",
        ))
    price: list[str] = []
    if not board_night and average - line >= CUSHION_MAX:
        price.append(
            f"The last five average of {_number(average)} still sits {_number(average - line)} above {_number(line)}."
        )
    elif not board_night and line > average + 0.5:
        price.append(
            f"{_number(line)} is still {_number(line - average)} above the last five average of {_number(average)}."
        )
    if not board_night and rate < 0.45:
        price.append(
            f"He has cleared {_number(line)} in {clears} of {len(season)} games ({round(rate * 100)}%)."
        )
    spiked = code in {"pts", "pra"} and _last_is_spike(rows, code)
    cushion = average - line
    if (
        not role
        and not spiked
        and middle > line
        and 0 < cushion < CUSHION_MAX
        and rate >= CLEAR_RATE
    ):
        bits = [(
            -3,
            f"{_number(line)} is under the last five median of {_number(middle)} "
            f"and the average of {_number(average)}, cleared in {clears} of {len(season)} games "
            f"({round(rate * 100)}%). The cushion is {_number(cushion)}. "
            "This strict over has cashed 59% of the time.",
        )]
        return _call("O", "strong", bits, rows, code, _rank("O", "strong", rate, cushion, False))
    if not role or not (price or board_night):
        return None
    strength = "strong" if any(weight >= 3 for weight, _text in role) or len(role) >= 2 else "lean"
    bits = list(role) + [(1, text) for text in price]
    return _call("U", strength, bits, rows, code, _rank("U", strength, rate, gap, durable))


def _rank(side: str, strength: str, rate: float, separation: float, durable: bool) -> float:
    """Higher is the call the card should show first."""
    base = 200 if strength == "strong" else 80
    if side == "O":
        return round(base + 40 + rate * 100 + max(separation, 0) * 8, 1)
    durability = 35 if durable else 0
    return round(base + durability + max(separation, 0) * 12 + (0.5 - rate) * 40, 1)


def _call(side: str, strength: str, bits: list[tuple[int, str]], rows: list[dict], code: str, score: float) -> dict:
    word = "Under" if side == "U" else "Over"
    tone = "strong" if strength == "strong" else "a lean"
    ordered = sorted(bits, key=lambda item: -abs(item[0]))
    dips = _recent_dips(rows, code)
    dip_text = ""
    if dips and side == "U":
        shown = "; ".join(
            f"{dip['date'][5:]} finished {_number(dip['actual'])} against a {_number(dip['average'])} average"
            for dip in dips[:2]
        )
        dip_text = f" Recent deep dips on this stat: {shown}."
    why = f"{word}, {tone}. " + " ".join(text for _weight, text in ordered) + dip_text
    return {"s": side, "k": strength, "why": why, "score": score}


def _minute_cut(rows: list[dict]) -> tuple[float, float] | None:
    minutes = _all_minutes(rows)
    if len(minutes) < PRIOR_GAMES:
        return None
    last = minutes[-1]
    base = sum(minutes[-PRIOR_GAMES:]) / PRIOR_GAMES
    if last <= base - 8 and last < 26:
        return last, base
    return None


def _cut_is_durable(rows: list[dict]) -> bool:
    """True when at least two of the last three nights were short, not just the last one."""
    minutes = _all_minutes(rows)
    if len(minutes) < PRIOR_GAMES:
        return False
    shorts = 0
    start = max(PRIOR_GAMES, len(minutes) - 2)
    for end in range(start, len(minutes) + 1):
        window = minutes[end - PRIOR_GAMES:end]
        if len(window) < PRIOR_GAMES:
            continue
        last = window[-1]
        base = sum(window) / PRIOR_GAMES
        if last <= base - 8 and last < 26:
            shorts += 1
    return shorts >= 2


def _minute_slide(rows: list[dict]) -> float | None:
    minutes = _all_minutes(rows)
    if len(minutes) < 3:
        return None
    older, middle, last = minutes[-3:]
    if older > middle > last and last < 28:
        return last
    return None


def _recent_dips(rows: list[dict], code: str) -> list[dict]:
    floor = DIP_FLOOR.get(code, 4)
    found = []
    values = []
    for game in rows:
        value = stat_value(game, code)
        if value is None:
            continue
        if len(values) >= PRIOR_GAMES:
            base = mean(values[-PRIOR_GAMES:]) or 0
            if value <= base - floor:
                found.append({
                    "date": game.get("slate_date") or "",
                    "actual": float(value),
                    "average": base,
                })
        values.append(float(value))
    recent_dates = {(game.get("slate_date") or "") for game in rows[-8:]}
    return [dip for dip in found if dip["date"] in recent_dates]


def points_pause(history: list[dict]) -> str:
    rows = played_rows(history)
    if not rows:
        return ""
    if _last_is_spike(rows, "pts"):
        return (
            "Last points game was 12 or more above the previous last five. "
            "That game is left out of the next average, and the next points star stays off."
        )
    if _attempt_void(rows):
        return (
            "Last game's shots were under 60% of his recent attempts while he was on the floor. "
            "Points star stays off until the shot volume comes back."
        )
    return ""


def ramp_text(history: list[dict], points_line: float | None) -> str:
    rows = played_rows(history)
    if points_pause(rows):
        return ""
    minutes = _recent_minutes(rows, 3)
    if len(minutes) < 3 or not (minutes[0] > minutes[1] > minutes[2] and minutes[0] >= RAMP_MINUTES):
        return ""
    recent = _raw_recent(rows, "pts", 5)
    average = mean(recent)
    path = ", ".join(_number(value) for value in reversed(minutes))
    if points_line is None or average is None:
        return (
            f"Minute ramp {path}. Last game was at least 24 minutes. "
            "This is a lean, not a star, and only if the points number is still above the last five average."
        )
    if not average < points_line:
        return ""
    return (
        f"Minute ramp {path}. Last five points average {_number(average)} is still under {_number(points_line)}. "
        "That cohort cleared 54.5%. It is a lean, not a star."
    )


def ceiling_report(
    history: list[dict],
    *,
    starter: bool,
    vacancy: float,
) -> dict | None:
    """Pregame ceiling from the inputs the box score can support."""
    rows = played_rows(history)
    if len(rows) < 8:
        return None
    minutes_slope = _ratio_slope(_recent_minutes(rows, 3), _all_minutes(rows))
    attempt_slope = _ratio_slope(_recent_numbers(rows, "fga", 3), _all_numbers(rows, "fga"))
    cold_coil = _cold_coil(rows, attempt_slope)
    role_preview = max(_role_preview(rows, "reb"), _role_preview(rows, "ast"))
    last_minutes = _recent_minutes(rows, 1)
    designated = 0.0
    if (not starter) and minutes_slope >= 0.25 and last_minutes and last_minutes[0] >= 20:
        designated = 1.0
    # Skill gap, role uniqueness, and opponent softness need a career line and a scheme tag.
    score = (
        0.16 * minutes_slope
        + 0.12 * attempt_slope
        + 0.16 * vacancy
        + 0.10 * cold_coil
        + 0.08 * role_preview
        + 0.08 * designated
    )
    if score < 0.35:
        return None
    detail = (
        f"Ceiling {_number(score)} from minutes slope {_number(minutes_slope)}, "
        f"attempt slope {_number(attempt_slope)}, vacancy {_number(vacancy)}, "
        f"three-point coil {_number(cold_coil)}, role preview {_number(role_preview)}, "
        f"designated bench {_number(designated)}. "
        "Skill gap, role uniqueness, and opponent softness are not in the feed, so this is the partial ceiling."
    )
    return {"score": round(score, 2), "detail": detail}


def script_blocks(code: str, starter: bool, spread: str | None, team: str | None) -> bool:
    if code != "pts" or not starter:
        return False
    number = team_spread(spread, team)
    if number is None:
        return False
    return number <= SCRIPT_SPREAD


def team_spread(spread: str | None, team: str | None) -> float | None:
    if not spread or not team:
        return None
    parts = str(spread).split()
    if len(parts) < 2:
        return None
    favorite = parts[0]
    try:
        number = float(parts[-1])
    except ValueError:
        return None
    if favorite == team:
        return number
    return -number


def vacancy_mass(missing_points: float, missing_rebounds: float) -> float:
    score = 0.5 * (missing_points / 80) + 0.5 * (missing_rebounds / 40)
    return max(0.0, min(1.0, score))


def slate_card(games: list[dict], history: dict[str, list[dict]]) -> dict:
    stars = []
    pauses = []
    ramps = []
    ceilings = []
    held = []
    for game in games:
        spread = game.get("spread")
        matchup = f"{game.get('away')} at {game.get('home')}"
        missing = _missing_production(game, history)
        for row in game.get("rows") or []:
            if row.get("avail") == "out":
                continue
            player_id = row.get("id")
            prior = earlier_history(history.get(player_id) or [], game)
            starter = bool(row.get("starter") or row.get("role") == "starter")
            team = row.get("team") or ""
            context = {"starter": starter, "spread": spread, "team": team}
            pause = points_pause(prior)
            if pause:
                pauses.append(_person(row, matchup, {"detail": pause}))
            points_line = _posted_line(row, "pts")
            ramp = ramp_text(prior, points_line[0] if points_line else None)
            if ramp:
                ramps.append(_person(row, matchup, {"detail": ramp, "code": "pts"}))
            ceiling = ceiling_report(
                prior,
                starter=starter,
                vacancy=missing.get(team, 0.0),
            )
            if ceiling:
                ceilings.append(_person(row, matchup, ceiling))
            if script_blocks("pts", starter, spread, team):
                ignored = dict(context)
                ignored["spread"] = None
                blocked = market_cap(prior, "pts", **ignored)
                if blocked:
                    number = team_spread(spread, team)
                    held.append(
                        _person(
                            row,
                            matchup,
                            {
                                "code": "pts",
                                "label": "Points",
                                "cap": blocked["cap"],
                                "detail": f"Starter points held. Team spread is {_number(number)}.",
                            },
                        )
                    )
            for code in ("reb", "stl", "pts", "pra", "fg3m", "ast"):
                cap = market_cap(prior, code, **context)
                if not cap:
                    continue
                posted, opened = _posted_line(row, code)
                decision = None
                if posted is not None:
                    decision = evaluate_line(code, posted, opened, prior, **context)
                ready = bool(decision and decision["star"])
                note = _card_note(code, cap, posted, opened, ready, prior)
                if row.get("avail") == "risk" and row.get("avail_note"):
                    label = row.get("avail_label") or "At risk"
                    note = f"{label}: {row['avail_note']}. {note}"
                stars.append(
                    _person(
                        row,
                        matchup,
                        {
                            **cap,
                            "posted": posted,
                            "ready": ready,
                            "note": note,
                        },
                    )
                )
    stars = [item for item in stars if _show_on_card(item)]
    stars.sort(key=lambda item: (not item.get("ready"), -item["weight"], -item["rate"], item["name"], item["code"]))
    pauses.sort(key=lambda item: item["name"])
    ramps.sort(key=lambda item: item["name"])
    ceilings.sort(key=lambda item: (-item["score"], item["name"]))
    held.sort(key=lambda item: item["name"])
    ready = sum(1 for item in stars if item.get("ready"))
    calls = _strong_calls(games)
    return {
        "summary": f"{ready} posted number{'s' if ready != 1 else ''} clear every gate.",
        "stars": stars,
        "calls": calls,
        "pauses": pauses,
        "ramps": ramps,
        "ceilings": ceilings[:12],
        "held": held,
    }


def _strong_calls(games: list[dict]) -> list[dict]:
    found = []
    for game in games:
        matchup = f"{game.get('away')} at {game.get('home')}"
        for row in game.get("rows") or []:
            if row.get("avail") == "out":
                continue
            seen = set()
            for prop in row.get("props") or []:
                code = prop.get("c")
                call = prop.get("call") or {}
                if prop.get("k") == "milestone" or code not in MARKET_LABEL or code in seen or call.get("k") != "strong":
                    continue
                seen.add(code)
                found.append({
                    "id": row.get("id"),
                    "name": row.get("name"),
                    "team": row.get("team"),
                    "game": matchup,
                    "label": MARKET_LABEL.get(code, code),
                    "side": call.get("s"),
                    "line": prop.get("line") or "",
                    "why": call.get("why") or "",
                    "score": call.get("score") or 0,
                })
    found.sort(key=lambda item: (-float(item.get("score") or 0), item.get("name") or "", item.get("label") or ""))
    return found[:40]


def _show_on_card(item: dict) -> bool:
    """The board stars every passing cell. The card keeps the lines worth reading."""
    if item.get("ready"):
        return True
    code = item.get("code")
    cap = item.get("cap") or 0
    if code in {"pts", "pra"}:
        return cap >= 8
    if code == "reb":
        return cap >= 4.5
    if code == "stl":
        return cap >= 1.5
    return False


def _person(row: dict, matchup: str, extra: dict) -> dict:
    payload = {
        "id": row.get("id"),
        "name": row.get("name"),
        "team": row.get("team"),
        "game": matchup,
        "starter": bool(row.get("starter")),
        "avail": row.get("avail") or "",
        "avail_note": row.get("avail_note") or "",
    }
    payload.update(extra)
    return payload


def _posted_line(row: dict, code: str) -> tuple[float | None, float | None]:
    for prop in row.get("props") or []:
        if prop.get("k") == "milestone" or prop.get("c") != code:
            continue
        line = _as_float(prop.get("line_num"))
        if line is None:
            line = _parse_number(prop.get("line"))
        opened = _parse_number(prop.get("open"))
        if opened is None:
            opened = _parse_number(prop.get("line_open"))
        return line, opened
    return None, None


def _card_note(code, cap, posted, opened, ready, history) -> str:
    notes = []
    if ready:
        notes.append("Posted number passes. Star it.")
    elif posted is None:
        notes.append(f"Star it only if the posted number is {_number(cap['cap'])} or lower and has not risen by a point.")
    elif _moved(posted, opened) >= MOVE_MAX:
        notes.append(f"Posted {_number(posted)} rose by a point or more from the open. Leave it.")
    elif posted > cap["cap"]:
        notes.append(f"Posted {_number(posted)} is above the cap.")
    else:
        notes.append(f"Posted {_number(posted)} does not clear every gate.")
    if code == "pts" and cap["avg"] - cap["cap"] < 1:
        notes.append("The cap sits inside a point of the average. Do not stack it. The make is the whole bet.")
    if code == "fg3m" and posted is not None and posted <= 0.5 and ready:
        notes.append(
            "This is one make. The clear rate means he made at least one three. "
            "The 3.5 cushion does not bind on 0.5. This group cashed 19 of 29, so about one in three still miss. "
            "Do not stack it like a rebound."
        )
    if code in {"pts", "pra"}:
        notes.append("One points or PRA leg per team. Do not pair a player's points with his own PRA.")
    return " ".join(notes)


def _missing_production(game: dict, history: dict[str, list[dict]]) -> dict[str, float]:
    totals: dict[str, list[float]] = {}
    for row in game.get("rows") or []:
        if row.get("avail") != "out":
            continue
        team = row.get("team") or ""
        rows = played_rows(history.get(row.get("id")) or [])
        if len(rows) < 3:
            continue
        points = mean([stat_value(item, "pts") or 0 for item in rows]) or 0
        rebounds = mean([stat_value(item, "reb") or 0 for item in rows]) or 0
        bucket = totals.setdefault(team, [0.0, 0.0])
        bucket[0] += points
        bucket[1] += rebounds
    return {team: vacancy_mass(points, rebounds) for team, (points, rebounds) in totals.items()}


def _profile(rows: list[dict], code: str) -> dict | None:
    if len(rows) < PRIOR_GAMES:
        return None
    if code == "pts" and (_last_is_spike(rows, "pts") or _attempt_void(rows)):
        return {"block": points_pause(rows)}
    if _last_is_spike(rows, code):
        return {"block": "spike"}
    spikes = _spike_indexes(rows, code)
    sample = []
    season = []
    for index in range(len(rows) - 1, -1, -1):
        value = stat_value(rows[index], code)
        if value is None:
            continue
        season.append(value)
        if index in spikes:
            continue
        if len(sample) < PRIOR_GAMES:
            sample.append(value)
    if len(sample) < PRIOR_GAMES or len(season) < PRIOR_GAMES:
        return None
    average = mean(sample)
    middle = median(sample)
    if average is None or middle is None:
        return None
    skill = _skill_points(rows) if code == "pts" else None
    return {
        "block": "",
        "avg": average,
        "median": middle,
        "season": season,
        "skill": skill,
    }


def _line_passes(profile: dict, line: float) -> bool:
    average = profile["avg"]
    middle = profile["median"]
    cushion = average - line
    if not (middle > line and 0 < cushion < CUSHION_MAX):
        return False
    skill = profile.get("skill")
    if skill is not None and line - skill > MAKE_TAX_MAX:
        return False
    clears = sum(1 for value in profile["season"] if value > line)
    played = len(profile["season"])
    rate = clears / played
    if rate < CLEAR_RATE:
        return False
    profile["clears"] = clears
    profile["played"] = played
    profile["rate"] = rate
    return True


def _highest_half(profile: dict) -> float | None:
    upper = min(profile["avg"], profile["median"])
    start = math.floor((upper - 1e-9) * 2)
    floor_line = profile["avg"] - CUSHION_MAX
    stop = math.floor(floor_line * 2) + 1
    # Books post 0.5 and up. A negative cap clears every game and is not a number.
    stop = max(stop, 1)
    units = start
    while units >= stop:
        line = units / 2
        if _line_passes(profile, line):
            return line
        units -= 1
    return None


def _why(code: str, line: float, open_line: float | None, profile: dict, margin: float) -> str:
    label = MARKET_LABEL.get(code, code)
    bits = [
        f"{label} clear star, weight {_number(MARKET_WEIGHT[code])}.",
        f"Last 5 median {_number(profile['median'])} is above {_number(line)}.",
        f"Last 5 average {_number(profile['avg'])}, cushion {_number(margin)}.",
        (
            f"Cleared {_number(line)} in {profile['clears']} of {profile['played']} games "
            f"({round(profile['rate'] * 100)}%)."
        ),
    ]
    moved = _moved(line, open_line)
    if open_line is not None and moved > 0:
        bits.append(f"Opened {_number(open_line)} and has not risen by a point.")
    if code == "pts" and margin < 1:
        bits.append("Within a point of his average. Do not stack it. The make is the whole bet.")
    if code in {"pts", "pra"}:
        bits.append("One points or PRA leg per team. Do not pair his points with his own PRA.")
    return " ".join(bits)


def _moved(line: float | None, open_line: float | None) -> float:
    if line is None or open_line is None:
        return 0.0
    return float(line) - float(open_line)


def _last_is_spike(rows: list[dict], code: str) -> bool:
    spikes = _spike_indexes(rows, code)
    return bool(rows) and (len(rows) - 1) in spikes


def _spike_indexes(rows: list[dict], code: str) -> set[int]:
    marks = set()
    for index in range(PRIOR_GAMES, len(rows)):
        prior = []
        for earlier in rows[index - PRIOR_GAMES:index]:
            value = stat_value(earlier, code)
            if value is None:
                prior = []
                break
            prior.append(value)
        current = stat_value(rows[index], code)
        if not prior or current is None or len(prior) < PRIOR_GAMES:
            continue
        if current >= (mean(prior) or 0) + SPIKE_GAP:
            marks.add(index)
    return marks


def _attempt_void(rows: list[dict]) -> bool:
    if len(rows) < 2:
        return False
    last = rows[-1]
    minutes = (last.get("seconds") or 0) / 60
    if minutes < VOID_MINUTES:
        return False
    last_attempts = last.get("fga")
    if last_attempts is None:
        return False
    prior = [game.get("fga") for game in rows[-6:-1] if game.get("fga") is not None]
    if len(prior) < 3:
        return False
    baseline = mean([float(value) for value in prior]) or 0
    if baseline <= 0:
        return False
    return float(last_attempts) < VOID_RATIO * baseline


def _skill_points(rows: list[dict]) -> float | None:
    field_points = 0.0
    attempts = 0.0
    free_makes = 0.0
    free_attempts = 0.0
    recent_attempts = []
    recent_free = []
    for game in rows:
        fga = game.get("fga")
        if fga is None:
            continue
        fga = float(fga)
        ftm = float(game.get("ftm") or 0)
        fta = game.get("fta")
        points = stat_value(game, "pts")
        if points is None:
            continue
        field_points += max(0.0, points - ftm)
        attempts += fga
        if fta is not None:
            free_attempts += float(fta)
            free_makes += ftm
        recent_attempts.append(fga)
        recent_free.append(float(fta or 0))
    if attempts <= 0 or len(recent_attempts) < PRIOR_GAMES:
        return None
    projected_attempts = mean(recent_attempts[-PRIOR_GAMES:]) or 0
    projected_free = mean(recent_free[-PRIOR_GAMES:]) or 0
    free_rate = (free_makes / free_attempts) if free_attempts else 0
    return projected_attempts * (field_points / attempts) + projected_free * free_rate


def _recent_minutes(rows: list[dict], count: int) -> list[float]:
    values = [((game.get("seconds") or 0) / 60) for game in rows]
    return list(reversed(values[-count:]))


def _all_minutes(rows: list[dict]) -> list[float]:
    return [((game.get("seconds") or 0) / 60) for game in rows]


def _recent_numbers(rows: list[dict], key: str, count: int) -> list[float]:
    values = [game.get(key) for game in rows if game.get(key) is not None]
    if len(values) < count:
        return []
    return [float(value) for value in values[-count:]]


def _all_numbers(rows: list[dict], key: str) -> list[float]:
    return [float(game[key]) for game in rows if game.get(key) is not None]


def _raw_recent(rows: list[dict], code: str, count: int) -> list[float]:
    values = []
    for game in reversed(rows):
        value = stat_value(game, code)
        if value is None:
            continue
        values.append(value)
        if len(values) >= count:
            break
    return values


def _ratio_slope(recent: list[float], season: list[float]) -> float:
    if len(recent) < 3 or not season:
        return 0.0
    base = mean(season) or 0
    if base <= 0:
        return 0.0
    slope = (mean(recent) or 0) / base - 1
    return max(0.0, min(1.0, slope))


def _cold_coil(rows: list[dict], attempt_slope: float) -> float:
    if attempt_slope <= 0:
        return 0.0
    made = []
    attempts = []
    for game in rows:
        if game.get("fg3a") is None:
            continue
        made.append(float(game.get("fg3m") or 0))
        attempts.append(float(game.get("fg3a") or 0))
    if len(attempts) < 3 or sum(attempts) <= 0 or sum(attempts[-3:]) <= 0:
        return 0.0
    season_rate = sum(made) / sum(attempts)
    gap = season_rate - (sum(made[-3:]) / sum(attempts[-3:]))
    return max(0.0, min(1.0, gap / 0.15))


def _role_preview(rows: list[dict], code: str) -> float:
    values = [stat_value(game, code) for game in rows]
    values = [value for value in values if value is not None]
    if len(values) < 4:
        return 0.0
    base = mean(values[:-1]) or 0
    if base <= 0:
        return 0.0
    gap = (values[-1] - base) / (base * 1.5)
    return max(0.0, min(1.0, gap))


def _as_float(value) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_number(value) -> float | None:
    if value is None or value == "":
        return None
    text = str(value).replace("+", "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _number(value: float) -> str:
    text = f"{float(value):.1f}"
    if text.endswith(".0"):
        return text[:-2]
    return text


def check() -> None:
    rows = []
    for index, points in enumerate([10, 10, 10, 10, 10, 10, 10, 10, 22, 10]):
        rows.append(
            {
                "game_id": str(index),
                "slate_date": f"2026-10-{20 + index:02d}",
                "seconds": 30 * 60,
                "pts": points,
                "reb": 5,
                "ast": 4,
                "fg3m": 1,
                "stl": 1,
                "blk": 0,
                "fga": 12,
                "ftm": 2,
                "fta": 2,
            }
        )
    cap = market_cap(rows, "pts")
    if not cap or cap["cap"] != 9.5:
        raise SystemExit(f"expected points cap 9.5, got {cap}")
    star = evaluate_line("pts", 9.5, 9.5, rows)
    if not star or not star["star"]:
        raise SystemExit("9.5 should star")
    moved = evaluate_line("pts", 9.5, 8.5, rows)
    if moved:
        raise SystemExit("a number that rose by a point should not star")
    rows[-1]["pts"] = 30
    if market_cap(rows, "pts"):
        raise SystemExit("a 12-point spike should pause the next points star")
    if not points_pause(rows):
        raise SystemExit("spike pause text missing")
    rows[-1]["pts"] = 10
    rows[-1]["fga"] = 4
    if market_cap(rows, "pts"):
        raise SystemExit("an attempt void should pause points")
    rows[-1]["fga"] = 12
    if market_cap(rows, "blk"):
        raise SystemExit("blocks are not starred")
    for game in rows:
        game["stl"] = 0
    if market_cap(rows, "stl"):
        raise SystemExit("a non-positive cap is not a posted number")
    if not script_blocks("pts", True, "PHI -9.5", "PHI"):
        raise SystemExit("a starter on a big favorite should be held")
    rising = []
    for index, minutes in enumerate((18, 22, 26, 30)):
        rising.append(
            {
                "game_id": f"m{index}",
                "slate_date": f"2026-11-0{index + 1}",
                "seconds": int(minutes * 60),
                "pts": 8,
                "reb": 3,
                "ast": 2,
                "fg3m": 1,
                "stl": 0,
                "blk": 0,
            }
        )
    # Four short games do not satisfy five prior games, so the ramp can still be named.
    text = ramp_text(rising, 12.5)
    if "Minute ramp" not in text:
        raise SystemExit(f"ramp missing: {text}")
    if vacancy_mass(40, 25) < 0.55 or vacancy_mass(40, 25) > 0.57:
        raise SystemExit("vacancy mass should be 0.56 for 40 points and 25 rebounds")
    cut_games = []
    for index, minutes in enumerate((32, 33, 31, 34, 30, 14)):
        cut_games.append({
            "game_id": f"c{index}",
            "slate_date": f"2026-11-{index + 1:02d}",
            "seconds": int(minutes * 60),
            "pts": 22 if minutes > 20 else 6,
            "reb": 4,
            "ast": 3,
            "fg3m": 2,
            "stl": 1,
            "blk": 0,
            "fga": 16 if minutes > 20 else 4,
            "fgm": 8 if minutes > 20 else 2,
        })
    one_night_points = project_call("pts", 22.5, None, cut_games)
    if one_night_points:
        raise SystemExit(f"one short night should not mark points, got {one_night_points}")
    one_night_threes = project_call("fg3m", 2.5, None, cut_games)
    if one_night_threes:
        raise SystemExit(f"one short night should not mark threes, got {one_night_threes}")
    board_call = project_call("reb", 5.5, None, cut_games)
    if not board_call or board_call["s"] != "U" or board_call["k"] != "strong":
        raise SystemExit(f"a board number still above the recent average should stay a strong under, got {board_call}")
    if "one night" not in board_call["why"] or "59%" in board_call["why"]:
        raise SystemExit(f"the board under should not read as a minute projection, got {board_call['why']}")
    priced_in = project_call("pts", 16.5, None, cut_games)
    if priced_in:
        raise SystemExit("a minute cut whose number is already under the average should stay unmarked")
    durable_games = []
    for index, minutes in enumerate((32, 33, 31, 34, 18, 15)):
        durable_games.append({
            "game_id": f"d{index}",
            "slate_date": f"2026-11-{index + 10:02d}",
            "seconds": int(minutes * 60),
            "pts": 22 if minutes > 20 else 8,
            "reb": 4,
            "ast": 3,
            "fg3m": 2,
            "stl": 1,
            "blk": 0,
            "fga": 16 if minutes > 20 else 4,
            "fgm": 8 if minutes > 20 else 2,
        })
    durable_call = project_call("pts", 22.5, None, durable_games)
    if not durable_call or durable_call["s"] != "U" or durable_call["k"] != "strong" or "59%" not in durable_call["why"]:
        raise SystemExit(f"a cut across more than one game should stay a strong points under, got {durable_call}")
    steady = []
    for index in range(8):
        steady.append({
            "game_id": f"s{index}",
            "slate_date": f"2026-10-{20 + index:02d}",
            "seconds": 34 * 60,
            "pts": 20,
            "reb": 5,
            "ast": 4,
            "fg3m": 2,
            "stl": 1,
            "blk": 0,
            "fga": 14,
            "fgm": 8,
        })
    over_call = project_call("pts", 17.5, None, steady)
    if not over_call or over_call["s"] != "O" or over_call["k"] != "strong":
        raise SystemExit(f"a number under a steady 80% profile should be a strong over, got {over_call}")
    soft = []
    for index, points in enumerate((20, 20, 20, 20, 12, 20, 12, 20)):
        soft.append({
            "game_id": f"m{index}",
            "slate_date": f"2026-10-{10 + index:02d}",
            "seconds": 34 * 60,
            "pts": points,
            "reb": 5,
            "ast": 4,
            "fg3m": 2,
            "stl": 1,
            "blk": 0,
            "fga": 14,
            "fgm": 8,
        })
    if project_call("pts", 15.0, None, soft):
        raise SystemExit("a 75% clear rate should not get an over mark")
    tossup = project_call("pts", 20.5, None, steady)
    if tossup:
        raise SystemExit("a number a half point over a flat average should stay unmarked")
    spiked = []
    for index, points in enumerate((14, 15, 14, 16, 15, 30)):
        spiked.append({
            "game_id": f"k{index}",
            "slate_date": f"2026-11-{index + 1:02d}",
            "seconds": 34 * 60,
            "pts": points,
            "reb": 4,
            "ast": 3,
            "fg3m": 2,
            "stl": 1,
            "blk": 0,
            "fga": 14,
            "fgm": 6,
        })
    if project_call("pts", 16.5, None, spiked):
        raise SystemExit("a spike by itself should not mark an under")
    made = []
    for index in range(8):
        made.append({
            "game_id": f"t{index}",
            "slate_date": f"2026-10-{20 + index:02d}",
            "seconds": 30 * 60,
            "pts": 12,
            "reb": 3,
            "ast": 2,
            "fg3m": 2,
            "fg3a": 6,
            "stl": 1,
            "blk": 0,
            "fga": 10,
            "fgm": 5,
            "ftm": 1,
            "fta": 1,
        })
    three_cap = market_cap(made, "fg3m")
    if not three_cap or three_cap["cap"] != 0.5:
        raise SystemExit(f"a three cap above 0.5 should come down to one make, got {three_cap}")
    if evaluate_line("fg3m", 1.5, 1.5, made):
        raise SystemExit("a 1.5 three should not star")
    if not evaluate_line("fg3m", 0.5, 0.5, made):
        raise SystemExit("a 0.5 three with a steady make should still star")
