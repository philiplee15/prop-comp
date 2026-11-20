"""Lookup tables that stay beside the board.

The hourly sync rewrites these files. A Google Sheet can pull them with
IMPORTDATA, so the backfill and the later slates stay in one place.
"""

from __future__ import annotations

import csv
import math
import statistics
from collections import defaultdict
from pathlib import Path

from propcomp.db import DOCS, connect

CORE = ("pts", "reb", "ast", "fg3m", "pra", "stl", "blk")
LABELS = {
    "pts": "Points",
    "reb": "Rebounds",
    "ast": "Assists",
    "fg3m": "Threes",
    "pra": "PRA",
    "stl": "Steals",
    "blk": "Blocks",
}
SHEET = DOCS / "data" / "sheet"


def publish(conn) -> None:
    teams = {row["id"]: row["abbr"] for row in conn.execute("SELECT id, abbr FROM teams")}
    names = {row["id"]: row["name"] for row in conn.execute("SELECT id, name FROM players")}
    history = _history(conn, teams)
    days = _days()
    SHEET.mkdir(parents=True, exist_ok=True)
    _write(SHEET / "guide.csv", _guide())
    _write(SHEET / "board.csv", _board_rows(days, history))
    _write(SHEET / "lines.csv", _line_rows(days, history))
    _write(SHEET / "logs.csv", _log_rows(history, names))
    pair_rows = _pair_rows(history, names)
    _write(SHEET / "pairs.csv", pair_rows)
    marked = _marked_pairs(days, pair_rows)
    _write_json(DOCS / "data" / "pairs.json", marked)
    print(
        f"Sheet tables: {len(pair_rows) - 1} teammate pairs, "
        f"{len(list(SHEET.glob('*.csv')))} files"
    )


def _history(conn, teams: dict[str, str]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    rows = conn.execute(
        """
        SELECT pg.player_id, pg.team_id, pg.minutes, pg.seconds, pg.starter,
               pg.pts, pg.reb, pg.ast, pg.fg3m, pg.stl, pg.blk, pg.fgm, pg.fga,
               g.slate_date, g.home_id, g.away_id, g.tip_utc
        FROM player_games pg
        JOIN games g ON g.id = pg.game_id
        WHERE g.status = 'final' AND pg.seconds > 0
        ORDER BY g.slate_date, g.tip_utc, g.id
        """
    )
    for row in rows:
        item = dict(row)
        item["team"] = teams.get(item["team_id"]) or ""
        opponent_id = item["away_id"] if item["team_id"] == item["home_id"] else item["home_id"]
        item["opponent"] = teams.get(opponent_id) or ""
        item["home"] = "home" if item["team_id"] == item["home_id"] else "away"
        item["pra"] = _sum(item["pts"], item["reb"], item["ast"])
        grouped[item["player_id"]].append(item)
    return grouped


def _days() -> list[dict]:
    import json

    found = []
    for path in sorted((DOCS / "data" / "days").glob("*.json")):
        found.append(json.loads(path.read_text(encoding="utf-8")))
    return found


def _guide() -> list[list]:
    return [
        ["Topic", "Meaning", "What to do"],
        [
            "Where this comes from",
            "These tabs are rewritten when the board syncs. Open the tab, filter a column, and the rows match the site.",
            "Use Board for tonight's card. Use Lines to search a player. Use Logs for the box score. Use Pairs before you stack teammates.",
        ],
        [
            "Mean and median",
            "The average is pulled up by a big game. The median is the middle game. The board already requires the last five median to sit over the number.",
            "If the average is above the median, the typical game is quieter than the average. Do not treat the average as the line.",
        ],
        [
            "Skew",
            "Season skew is the average minus the median across games already played. A positive number is a right tail: a few monster games. NBA counting stats usually gap by well under a point. Football yardage gaps are larger.",
            "A gap under a point is ordinary. It does not add a star and it does not cancel one.",
        ],
        [
            "Standard deviation",
            "This is how far a typical last-five game sat from that average. A wide number means the same line can miss on an ordinary night.",
            "Read it next to the cushion. A one-point cushion inside a wide spread is a thin edge.",
        ],
        [
            "Same-game pairs",
            "The correlation is how two teammates' points moved across shared games. Positive means they rose and fell together. Negative means one rose while the other fell. Assists are checked the same way.",
            "Eight to fourteen shared games is a short sample. Use the pair as a stacking check. It is not a star.",
        ],
        [
            "Path calls and stars",
            "A path call is a strong over or a strong under. A clear star is the over side, and the posted number still has to clear every gate.",
            "The Board tab copies those sections. The site remains the place the call is explained.",
        ],
        [
            "Refresh",
            "Google Sheets caches an IMPORTDATA pull. The files themselves update with the board.",
            "If a tab looks old, reload the sheet. A new board sync publishes the next file.",
        ],
    ]


def _board_rows(days: list[dict], history: dict[str, list[dict]]) -> list[list]:
    header = [
        "Date", "Section", "Game", "Team", "Player", "Market", "Line", "Call",
        "Last 5 average", "Last 5 median", "Season skew", "Last 5 spread", "Clear", "Detail",
    ]
    rows = [header]
    for day in days:
        card = day.get("card") or {}
        slate = day["date"]
        for item in card.get("calls") or []:
            shape = _shape(history.get(item.get("id")) or [], slate, _code(item.get("label")))
            rows.append([
                slate, "Path call", item.get("game") or "", item.get("team") or "", item.get("name") or "",
                item.get("label") or "", item.get("line") or "",
                "Under" if item.get("side") == "U" else "Over",
                shape["mean"], shape["median"], shape["skew"], shape["spread"], "",
                item.get("why") or "",
            ])
        for item in card.get("stars") or []:
            shape = _shape(history.get(item.get("id")) or [], slate, item.get("code"))
            rows.append([
                slate, "Clear star", item.get("game") or "", item.get("team") or "", item.get("name") or "",
                item.get("label") or "", item.get("posted") if item.get("posted") is not None else item.get("cap"),
                "Star" if item.get("ready") else "Cap",
                shape["mean"], shape["median"], shape["skew"], shape["spread"],
                _percent(item.get("rate")), item.get("note") or "",
            ])
        for section, key in (
            ("Points paused", "pauses"),
            ("Minute ramp", "ramps"),
            ("Pregame ceiling", "ceilings"),
            ("Held for the spread", "held"),
        ):
            for item in card.get(key) or []:
                rows.append([
                    slate, section, item.get("game") or "", item.get("team") or "", item.get("name") or "",
                    item.get("label") or "", item.get("cap") if item.get("cap") is not None else "",
                    "", "", "", "", "", "", item.get("detail") or "",
                ])
    return rows


def _line_rows(days: list[dict], history: dict[str, list[dict]]) -> list[list]:
    header = [
        "Date", "Game", "Team", "Opponent", "Player", "Pos", "Market", "Line",
        "Result", "Actual", "Last 5 average", "Last 5 median", "Season skew", "Last 5 spread", "Season clear",
    ]
    rows = [header]
    for day in days:
        slate = day["date"]
        for game in day.get("games") or []:
            matchup = f"{game.get('away')} at {game.get('home')}"
            for row in game.get("rows") or []:
                prior = [item for item in history.get(row.get("id")) or [] if item["slate_date"] < slate]
                for prop in row.get("props") or []:
                    if prop.get("k") != "ou" or prop.get("c") not in CORE:
                        continue
                    shape = _shape(prior, slate, prop.get("c"), line=_number(prop.get("line")), already_prior=True)
                    opponent = game.get("home") if row.get("team") == game.get("away") else game.get("away")
                    rows.append([
                        slate, matchup, row.get("team") or "", opponent or "", row.get("name") or "",
                        row.get("pos") or "", LABELS.get(prop.get("c"), prop.get("c")),
                        prop.get("line") or "", prop.get("r") or "", prop.get("act") if prop.get("act") is not None else "",
                        shape["mean"], shape["median"], shape["skew"], shape["spread"], shape["clear"],
                    ])
    return rows


def _log_rows(history: dict[str, list[dict]], names: dict[str, str]) -> list[list]:
    header = [
        "Date", "Team", "Opponent", "Home", "Player", "Minutes", "Points", "Rebounds",
        "Assists", "Threes", "Steals", "Blocks", "FGM", "FGA", "FG%", "PRA",
    ]
    rows = [header]
    for player_id, games in history.items():
        for game in games:
            shots = game.get("fga") or 0
            made = game.get("fgm")
            percent = round(made / shots, 3) if shots and made is not None else ""
            rows.append([
                game["slate_date"], game["team"], game["opponent"], game["home"],
                names.get(player_id) or player_id, _minutes(game),
                _blank(game.get("pts")), _blank(game.get("reb")), _blank(game.get("ast")),
                _blank(game.get("fg3m")), _blank(game.get("stl")), _blank(game.get("blk")),
                _blank(made), _blank(game.get("fga")), percent, _blank(game.get("pra")),
            ])
    rows[1:] = sorted(rows[1:], key=lambda item: (item[0], item[1], item[4]))
    return rows


def _pair_rows(history: dict[str, list[dict]], names: dict[str, str]) -> list[list]:
    header = [
        "Team", "Player A", "Player B", "Shared games", "Points correlation",
        "A points vs B assists", "B points vs A assists", "Read",
    ]
    by_game: dict[tuple, list] = defaultdict(list)
    for player_id, games in history.items():
        for game in games:
            by_game[(game["slate_date"], game["team"])].append((player_id, game))
    series: dict[tuple, dict] = defaultdict(lambda: {"pts": [[], []], "a_ast": [[], []], "b_ast": [[], []]})
    teams: dict[tuple, str] = {}
    for grouped in by_game.values():
        for index, (left_id, left) in enumerate(grouped):
            for right_id, right in grouped[index + 1:]:
                key = tuple(sorted((left_id, right_id)))
                first, second = (left, right) if key[0] == left_id else (right, left)
                bucket = series[key]
                teams[key] = left["team"]
                bucket["pts"][0].append(first.get("pts") or 0)
                bucket["pts"][1].append(second.get("pts") or 0)
                bucket["a_ast"][0].append(first.get("pts") or 0)
                bucket["a_ast"][1].append(second.get("ast") or 0)
                bucket["b_ast"][0].append(second.get("pts") or 0)
                bucket["b_ast"][1].append(first.get("ast") or 0)
    rows = [header]
    for key, bucket in series.items():
        count = len(bucket["pts"][0])
        if count < 8:
            continue
        points = _corr(*bucket["pts"])
        a_ast = _corr(*bucket["a_ast"])
        b_ast = _corr(*bucket["b_ast"])
        rows.append([
            teams.get(key) or "",
            names.get(key[0]) or key[0],
            names.get(key[1]) or key[1],
            count,
            _round(points),
            _round(a_ast),
            _round(b_ast),
            _pair_read(points, a_ast, b_ast, count),
        ])
    rows[1:] = sorted(rows[1:], key=lambda item: (-abs(item[4] or 0), item[0], item[1], item[2]))
    return rows


def _marked_pairs(days: list[dict], pair_rows: list[list]) -> dict:
    by_team: dict[tuple, list] = defaultdict(list)
    for row in pair_rows[1:]:
        by_team[(row[0], row[1])].append(row)
        by_team[(row[0], row[2])].append(row)
    marked = {}
    for day in days:
        card = day.get("card") or {}
        active = {}
        for game in day.get("games") or []:
            for row in game.get("rows") or []:
                if row.get("avail") == "out":
                    continue
                active[(row.get("team"), row.get("name"))] = True
        focus = {}
        for item in card.get("calls") or []:
            focus[(item.get("team"), item.get("name"))] = True
        for item in card.get("stars") or []:
            if item.get("ready"):
                focus[(item.get("team"), item.get("name"))] = True
        notes = []
        seen = set()
        for team, name in focus:
            best = None
            best_strength = 0
            for row in by_team.get((team, name), []):
                other = row[2] if row[1] == name else row[1]
                if not active.get((team, other)):
                    continue
                link = _strongest_link(name, other, row)
                if link and link["strength"] > best_strength:
                    best = link
                    best_strength = link["strength"]
            if not best:
                continue
            key = tuple(sorted((name, best["other"])))
            if key in seen:
                continue
            seen.add(key)
            notes.append(best["note"])
        notes.sort(key=lambda item: -abs(item["points"] or 0))
        if notes:
            marked[day["date"]] = notes[:8]
    return marked


def _strongest_link(name: str, other: str, row: list) -> dict | None:
    candidates = []
    points = row[4] if isinstance(row[4], (int, float)) else None
    a_ast = row[5] if isinstance(row[5], (int, float)) else None
    b_ast = row[6] if isinstance(row[6], (int, float)) else None
    games = row[3]
    if points is not None and abs(points) >= 0.5:
        direction = "rose and fell together" if points > 0 else "moved in opposite directions"
        candidates.append((abs(points), (
            f"{name} and {other} points {direction} across {games} shared games (r {points}). "
            "Pairing check, not a star."
        ), points))
    # Row order is player id, not the focus name. Map each assist column back to names.
    left_name, right_name = row[1], row[2]
    if a_ast is not None and abs(a_ast) >= 0.5:
        direction = "together" if a_ast > 0 else "apart"
        candidates.append((abs(a_ast), (
            f"{left_name} points and {right_name} assists moved {direction} across {games} shared games (r {a_ast}). "
            "Pairing check, not a star."
        ), points))
    if b_ast is not None and abs(b_ast) >= 0.5:
        direction = "together" if b_ast > 0 else "apart"
        candidates.append((abs(b_ast), (
            f"{right_name} points and {left_name} assists moved {direction} across {games} shared games (r {b_ast}). "
            "Pairing check, not a star."
        ), points))
    if not candidates:
        return None
    strength, detail, points_value = max(candidates, key=lambda item: item[0])
    return {
        "strength": strength,
        "other": other,
        "note": {
            "team": row[0],
            "a": name,
            "b": other,
            "games": games,
            "points": points_value if isinstance(points_value, (int, float)) else None,
            "detail": detail,
        },
    }


def _shape(
    games: list[dict],
    slate: str,
    code: str | None,
    line: float | None = None,
    already_prior: bool = False,
) -> dict:
    empty = {"mean": "", "median": "", "skew": "", "spread": "", "clear": ""}
    if not code:
        return empty
    prior = games if already_prior else [game for game in games if game["slate_date"] < slate]
    values = []
    for game in prior:
        value = game.get(code)
        if value is None:
            continue
        values.append(float(value))
    if len(values) < 5:
        return empty
    recent = values[-5:]
    season_mean = statistics.mean(values)
    season_median = statistics.median(values)
    clear = ""
    if line is not None:
        clear = _percent(sum(value > line for value in values) / len(values))
    return {
        "mean": round(statistics.mean(recent), 1),
        "median": statistics.median(recent),
        "skew": round(season_mean - season_median, 1),
        "spread": round(statistics.pstdev(recent), 1),
        "clear": clear,
    }


def _number(value) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _corr(left: list[float], right: list[float]) -> float | None:
    count = len(left)
    if count < 8:
        return None
    mean_left = statistics.mean(left)
    mean_right = statistics.mean(right)
    num = sum((a - mean_left) * (b - mean_right) for a, b in zip(left, right))
    spread_left = math.sqrt(sum((a - mean_left) ** 2 for a in left))
    spread_right = math.sqrt(sum((b - mean_right) ** 2 for b in right))
    if spread_left == 0 or spread_right == 0:
        return None
    return num / (spread_left * spread_right)


def _pair_read(points, a_ast, b_ast, count: int) -> str:
    bits = []
    if points is not None and points >= 0.45:
        bits.append(f"Points moved together (r {_round(points)})")
    elif points is not None and points <= -0.45:
        bits.append(f"Points moved apart (r {_round(points)})")
    if a_ast is not None and abs(a_ast) >= 0.45:
        direction = "together" if a_ast > 0 else "apart"
        bits.append(f"A's points and B's assists moved {direction} (r {_round(a_ast)})")
    if b_ast is not None and abs(b_ast) >= 0.45:
        direction = "together" if b_ast > 0 else "apart"
        bits.append(f"B's points and A's assists moved {direction} (r {_round(b_ast)})")
    if not bits:
        return f"Quiet across {count} shared games"
    return f"{'. '.join(bits)}. {count} shared games, so this is a pairing check and not a star."


def _code(label: str | None) -> str | None:
    for code, name in LABELS.items():
        if name == label:
            return code
    return None


def _percent(rate) -> str:
    if rate is None:
        return ""
    return f"{round(float(rate) * 100)}%"


def _minutes(game: dict) -> float | str:
    seconds = game.get("seconds") or 0
    if seconds <= 0:
        return ""
    return round(seconds / 60, 1)


def _sum(*values):
    if any(value is None for value in values):
        return None
    return sum(values)


def _blank(value):
    return "" if value is None else value


def _round(value):
    if value is None:
        return ""
    return round(value, 2)


def _write(path: Path, rows: list[list]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        csv.writer(handle).writerows(rows)


def _write_json(path: Path, payload) -> None:
    import json

    path.write_text(json.dumps(payload, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")


def main() -> None:
    conn = connect()
    try:
        publish(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
