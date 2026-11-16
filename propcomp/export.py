from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

from propcomp.db import DOCS
from propcomp.grade import CORE_MARKETS

EASTERN = ZoneInfo("America/New_York")
CORE_OU = ["pts", "reb", "ast", "fg3m", "pra", "stl", "blk"]
YES_CODES = ["dd", "first"]
TRACKED = set(CORE_OU + YES_CODES + ["pr", "pa", "ra"])


def build(conn) -> None:
    generated = datetime.now(EASTERN).isoformat(timespec="seconds")
    teams = {row["id"]: dict(row) for row in conn.execute("SELECT * FROM teams")}
    players = {row["id"]: dict(row) for row in conn.execute("SELECT * FROM players")}
    games = [
        dict(row)
        for row in conn.execute("SELECT * FROM games ORDER BY slate_date, tip_utc, id")
    ]
    props_by_game = defaultdict(list)
    for row in conn.execute("SELECT * FROM props"):
        props_by_game[row["game_id"]].append(dict(row))
    stats_by_game = defaultdict(dict)
    for row in conn.execute("SELECT * FROM player_games"):
        stats_by_game[row["game_id"]][row["player_id"]] = dict(row)

    day_dir = DOCS / "data" / "days"
    day_dir.mkdir(parents=True, exist_ok=True)
    for stale in day_dir.glob("*.json"):
        stale.unlink()

    dates = []
    season_players = defaultdict(lambda: defaultdict(lambda: {"o": 0, "u": 0, "p": 0, "y": 0, "n": 0}))
    league = defaultdict(lambda: {"o": 0, "u": 0, "p": 0, "y": 0, "n": 0})
    logs = defaultdict(lambda: defaultdict(list))
    blotter = []

    by_date = defaultdict(list)
    for game in games:
        by_date[game["slate_date"]].append(game)

    for slate, slate_games in by_date.items():
        payload_games = []
        final_games = 0
        for game in slate_games:
            packed = pack_game(
                game,
                props_by_game.get(game["id"], []),
                stats_by_game.get(game["id"], {}),
                teams,
                players,
            )
            payload_games.append(packed)
            if game["status"] == "final":
                final_games += 1
            for row in packed["rows"]:
                for prop in row["props"]:
                    if game["status"] != "final" or prop["k"] == "milestone" or prop["c"] not in TRACKED:
                        continue
                    bucket = season_players[row["id"]][prop["c"]]
                    tally(bucket, prop["r"])
                    tally(league[prop["c"]], prop["r"])
                    if prop["c"] in CORE_OU and prop["r"] in {"over", "under", "push"}:
                        logs[row["id"]][prop["c"]].append(
                            [
                                slate,
                                prop.get("line"),
                                prop.get("open") or None,
                                prop.get("act"),
                                prop["r"][0],
                            ]
                        )
                    elif prop["c"] in YES_CODES and prop["r"] in {"yes", "no"}:
                        logs[row["id"]][prop["c"]].append([slate, prop["r"][0]])
            if game["status"] == "final":
                blotter.append(
                    {
                        "date": slate,
                        "away": abbr(teams, game["away_id"]),
                        "home": abbr(teams, game["home_id"]),
                        "away_score": game["away_score"],
                        "home_score": game["home_score"],
                        "over": ou_game_count(packed, "over"),
                        "under": ou_game_count(packed, "under"),
                    }
                )
        dates.append(
            {
                "date": slate,
                "games": len(slate_games),
                "final": final_games,
                "scheduled": sum(1 for game in slate_games if game["status"] != "final"),
            }
        )
        write_json(day_dir / f"{slate}.json", {"date": slate, "games": payload_games})

    season_rows = []
    for player_id, markets in season_players.items():
        person = players.get(player_id) or {}
        team = teams.get(person.get("team_id") or "", {})
        played = max((sum(item.values()) for item in markets.values()), default=0)
        if played == 0:
            continue
        season_rows.append(
            {
                "id": player_id,
                "name": person.get("name") or f"Player {player_id}",
                "team": team.get("abbr") or "",
                "pos": person.get("position") or "",
                "markets": {code: counts for code, counts in markets.items() if sum(counts.values())},
            }
        )
    season_rows.sort(key=lambda item: item["name"])

    manifest = {
        "name": "Prop Comp",
        "season": "2026-27",
        "generated_at": generated,
        "today": datetime.now(EASTERN).date().isoformat(),
        "source": "DraftKings lines via ESPN, graded from ESPN box scores and play-by-play",
        "core": CORE_MARKETS,
        "dates": dates,
        "teams": [
            {"id": team["id"], "abbr": team["abbr"], "name": team["name"], "color": team["color"]}
            for team in sorted(teams.values(), key=lambda item: item["abbr"] or "")
        ],
        "counts": {
            "games": len(games),
            "final": sum(1 for game in games if game["status"] == "final"),
            "props": sum(len(items) for items in props_by_game.values()),
        },
    }
    write_json(DOCS / "data" / "manifest.json", manifest)
    write_json(
        DOCS / "data" / "season.json",
        {"players": season_rows, "league": {code: dict(counts) for code, counts in league.items()}},
    )
    write_json(DOCS / "data" / "logs.json", logs)
    write_snapshot(manifest, season_rows, league, blotter, by_date, props_by_game, stats_by_game, teams, players)
    print(
        f"Exported {manifest['counts']['games']} games, "
        f"{manifest['counts']['props']} props, {len(dates)} slates"
    )


def tally(bucket: dict, result: str) -> None:
    key = {"over": "o", "under": "u", "push": "p", "yes": "y", "no": "n"}.get(result)
    if key:
        bucket[key] += 1


def ou_game_count(packed: dict, result: str) -> int:
    total = 0
    for row in packed["rows"]:
        for prop in row["props"]:
            if prop["c"] in CORE_OU and prop["r"] == result:
                total += 1
    return total


def pack_game(game, props, stats, teams, players) -> dict:
    grouped = defaultdict(list)
    for prop in props:
        grouped[prop["player_id"]].append(compact_prop(prop))
    rows = []
    for player_id, player_props in grouped.items():
        person = players.get(player_id) or {}
        stat = stats.get(player_id) or {}
        team_id = stat.get("team_id") or person.get("team_id")
        rows.append(
            {
                "id": player_id,
                "name": person.get("name") or f"Player {player_id}",
                "team": abbr(teams, team_id),
                "pos": person.get("position") or "",
                "min": stat.get("minutes") or "",
                "starter": bool(stat.get("starter")),
                "stat": {
                    "pts": stat.get("pts"),
                    "reb": stat.get("reb"),
                    "ast": stat.get("ast"),
                    "fg3m": stat.get("fg3m"),
                    "stl": stat.get("stl"),
                    "blk": stat.get("blk"),
                    "tov": stat.get("tov"),
                }
                if stat
                else None,
                "props": sorted(player_props, key=lambda item: (item["k"], item["m"], item.get("line") or "")),
            }
        )
    rows.sort(key=row_sort_key)
    return {
        "id": game["id"],
        "status": game["status"],
        "tip": game["tip_utc"],
        "away": abbr(teams, game["away_id"]),
        "home": abbr(teams, game["home_id"]),
        "away_score": game["away_score"],
        "home_score": game["home_score"],
        "spread": game["spread"],
        "total": game["total"],
        "note": game["props_note"],
        "rows": rows,
    }


def compact_prop(prop: dict) -> dict:
    actual = prop["actual"]
    if isinstance(actual, float) and actual.is_integer():
        actual = int(actual)
    packed = {
        "m": prop["market"],
        "c": prop["code"],
        "k": prop["kind"],
        "line": prop["line"] or "",
        "r": prop["result"] or "pending",
    }
    if prop["line_open"] and prop["line_open"] != prop["line"]:
        packed["open"] = prop["line_open"]
    if prop["price_a"]:
        packed["a"] = prop["price_a"]
    if prop["price_b"]:
        packed["b"] = prop["price_b"]
    if actual is not None:
        packed["act"] = actual
    return packed


def row_sort_key(row: dict):
    points = next((prop for prop in row["props"] if prop["c"] == "pts"), None)
    line = 0
    if points and points.get("line"):
        try:
            line = float(str(points["line"]).replace("+", ""))
        except ValueError:
            line = 0
    return (-line, row["name"])


def abbr(teams: dict, team_id: str | None) -> str:
    if not team_id:
        return ""
    team = teams.get(str(team_id))
    return team["abbr"] if team else str(team_id)


def write_json(path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")


def rate_style(over: int, under: int) -> str:
    sample = over + under
    if sample < 3:
        return "background:#2c3344;color:#c5ccda"
    rate = over / sample
    red, green, blue = 232, 92, 108
    target = (61, 196, 132)
    mix_r = int(red + (target[0] - red) * rate)
    mix_g = int(green + (target[1] - green) * rate)
    mix_b = int(blue + (target[2] - blue) * rate)
    return f"background:rgb({mix_r},{mix_g},{mix_b});color:#10140f"


def record_text(counts: dict, kind: str) -> str:
    if kind == "yes":
        yes = counts.get("y", 0)
        no = counts.get("n", 0)
        sample = yes + no
        if not sample:
            return ""
        return f"{yes}-{no}"
    over = counts.get("o", 0)
    under = counts.get("u", 0)
    push = counts.get("p", 0)
    sample = over + under + push
    if not sample:
        return ""
    text = f"{over}-{under}"
    if push:
        text += f"-{push}"
    return text


def write_snapshot(manifest, season_rows, league, blotter, by_date, props_by_game, stats_by_game, teams, players) -> None:
    upcoming = [item["date"] for item in manifest["dates"] if item["scheduled"]]
    focus_dates = upcoming[-3:] if upcoming else manifest["dates"][-1:]
    leaders = []
    for row in season_rows:
        counts = row["markets"].get("pts") or {}
        sample = counts.get("o", 0) + counts.get("u", 0)
        if sample < 5:
            continue
        leaders.append((counts.get("o", 0) / sample, sample, row))
    leaders.sort(key=lambda item: (-item[0], -item[1], item[2]["name"]))

    parts = [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "<title>Prop Comp snapshot</title>",
        '<link rel="stylesheet" href="styles.css">',
        "</head>",
        "<body>",
        '<header class="top">',
        '<div><p class="mark">Prop Comp</p><h1>Season snapshot</h1></div>',
        f"<p class=\"meta\">Updated {escape(manifest['generated_at'])} ET<br>{escape(manifest['source'])}</p>",
        "</header>",
        '<p class="jump"><a href="index.html">Open the interactive board</a></p>',
        '<section class="panel">',
        f"<h2>{manifest['counts']['final']} finals, {manifest['counts']['props']} stored props</h2>",
        '<div class="bars">',
    ]
    for market in CORE_MARKETS:
        counts = league.get(market["code"]) or {}
        if market["code"] in YES_CODES:
            yes = counts.get("y", 0)
            no = counts.get("n", 0)
            sample = yes + no
            width = 0 if not sample else round(100 * yes / sample)
            label = f"{yes}-{no}" if sample else "n/a"
        else:
            over = counts.get("o", 0)
            under = counts.get("u", 0)
            sample = over + under
            width = 0 if not sample else round(100 * over / sample)
            label = f"{over}-{under}" if sample else "n/a"
        parts.append(
            "<div class=\"bar-row\">"
            f"<span>{escape(market['label'])}</span>"
            f"<span class=\"track\"><span class=\"fill\" style=\"width:{width}%\"></span></span>"
            f"<span class=\"rec\">{width}% {escape(label)}</span>"
            "</div>"
        )
    parts.append("</div></section>")
    parts.append('<section class="panel"><h2>Points over rate, at least 5 graded games</h2>')
    parts.append(leaders_table(leaders[:40]))
    parts.append("</section>")
    parts.append('<section class="panel"><h2>Every final, main-line overs and unders</h2><div class="blotter">')
    for game in blotter:
        parts.append(
            "<a class=\"game-link\" href=\"index.html#d="
            f"{escape(game['date'])}\">"
            f"<span>{escape(game['date'][5:])}</span>"
            f"<span>{escape(game['away'])} {game['away_score']}</span>"
            f"<span>{escape(game['home'])} {game['home_score']}</span>"
            f"<span>{game['over']}-{game['under']}</span>"
            "</a>"
        )
    parts.append("</div></section>")
    for slate in focus_dates:
        parts.append(f'<section class="panel"><h2>{escape(slate)} lines</h2>')
        for game in by_date.get(slate, []):
            packed = pack_game(
                game,
                props_by_game.get(game["id"], []),
                stats_by_game.get(game["id"], {}),
                teams,
                players,
            )
            parts.append(static_game(packed))
        if not by_date.get(slate):
            parts.append("<p>No games on this slate.</p>")
        parts.append("</section>")
    parts.append(
        '<footer class="foot">Lines are the DraftKings open and current number ESPN still publishes. '
        "The two prices are the two sides of that number. ESPN does not label which price is the over. "
        "A player who did not play is void, not a miss. "
        '<a href="index.html">Interactive board</a></footer></body></html>'
    )
    (DOCS / "snapshot.html").write_text("\n".join(parts), encoding="utf-8")
    (DOCS / ".nojekyll").write_text("", encoding="utf-8")


def leaders_table(leaders) -> str:
    columns = [market for market in CORE_MARKETS if market["code"] in CORE_OU or market["code"] in YES_CODES]
    head = "".join(f"<th>{escape(market['label'])}</th>" for market in columns)
    body = []
    for _rate, _sample, row in leaders:
        cells = [f"<td class=\"name\">{escape(row['team'])} {escape(row['name'])}</td>"]
        for market in columns:
            counts = row["markets"].get(market["code"]) or {}
            kind = "yes" if market["code"] in YES_CODES else "ou"
            text = record_text(counts, kind)
            if kind == "yes":
                style = rate_style(counts.get("y", 0), counts.get("n", 0))
            else:
                style = rate_style(counts.get("o", 0), counts.get("u", 0))
            cells.append(f"<td style=\"{style}\">{escape(text)}</td>" if text else "<td></td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    return (
        '<div class="table-wrap"><table class="heat"><thead><tr><th>Player</th>'
        + head
        + "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table></div>"
    )


def static_game(game: dict) -> str:
    score = ""
    if game["status"] == "final":
        score = f"{game['away_score']}-{game['home_score']} final"
    elif game["status"] == "live":
        score = f"{game['away_score']}-{game['home_score']} live"
    else:
        score = "lines"
    meta = " ".join(
        bit
        for bit in [game.get("spread") or "", f"total {game['total']}" if game.get("total") else ""]
        if bit
    )
    columns = CORE_MARKETS
    head = "".join(f"<th>{escape(market['label'])}</th>" for market in columns)
    body = []
    if not game["rows"]:
        body.append('<tr><td class="name" colspan="10">Lines are not posted yet.</td></tr>')
    for row in game["rows"]:
        cells = [f"<td class=\"name\">{escape(row['team'])} {escape(row['name'])}</td>"]
        indexed = {prop["c"]: prop for prop in row["props"] if prop["k"] != "milestone"}
        for market in columns:
            prop = indexed.get(market["code"])
            cells.append(f"<td>{static_cell(prop)}</td>")
        extras = [prop for prop in row["props"] if prop["c"] not in {market["code"] for market in columns}]
        extra_html = ""
        if extras:
            bits = []
            for prop in extras:
                bits.append(
                    f"<li>{escape(prop['m'])} {escape(prop.get('line') or '')} "
                    f"{escape(result_word(prop['r']))}</li>"
                )
            extra_html = (
                '<tr class="extra"><td colspan="10"><details><summary>'
                f"{len(extras)} more lines</summary><ul>"
                + "".join(bits)
                + "</ul></details></td></tr>"
            )
        body.append("<tr>" + "".join(cells) + "</tr>" + extra_html)
    return (
        '<article class="game">'
        f"<h3>{escape(game['away'])} at {escape(game['home'])}</h3>"
        f"<p class=\"meta\">{escape(score)} {escape(meta)}</p>"
        '<div class="table-wrap"><table><thead><tr><th>Player</th>'
        + head
        + "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table></div></article>"
    )


def static_cell(prop: dict | None) -> str:
    if not prop:
        return ""
    line = escape(prop.get("line") or "")
    result = prop.get("r") or "pending"
    actual = prop.get("act")
    actual_text = "" if actual is None else escape(str(actual))
    word = escape(result_word(result))
    css = {"over": "hit", "yes": "hit", "under": "miss", "no": "miss", "push": "push", "void": "void"}.get(
        result, "wait"
    )
    open_line = f" open {escape(prop['open'])}" if prop.get("open") else ""
    prices = " / ".join(escape(prop[key]) for key in ("a", "b") if prop.get(key))
    price_bit = f"<small>{prices}</small>" if prices else ""
    return f'<span class="cell {css}">{actual_text} <b>{word} {line}</b>{open_line}{price_bit}</span>'


def result_word(result: str) -> str:
    return {
        "over": "o",
        "under": "u",
        "push": "push",
        "yes": "yes",
        "no": "no",
        "void": "void",
        "pending": "line",
        "ungraded": "line",
    }.get(result, result)
