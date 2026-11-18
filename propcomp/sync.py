from __future__ import annotations

import os
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from propcomp import availability, espn, export
from propcomp.db import connect
from propcomp.grade import (
    american_value,
    code_for,
    consume_play,
    first_baskets,
    first_three,
    grade_prop,
    kind_for,
    parse_box_stats,
    parse_line,
)

SEASON_START = date(2026, 10, 20)
EASTERN = ZoneInfo("America/New_York")

STATUS_MAP = {
    "STATUS_FINAL": "final",
    "STATUS_FULL_TIME": "final",
    "STATUS_FINAL_OT": "final",
    "STATUS_IN_PROGRESS": "live",
    "STATUS_HALFTIME": "live",
    "STATUS_END_PERIOD": "live",
    "STATUS_SCHEDULED": "scheduled",
    "STATUS_PRE": "scheduled",
    "STATUS_POSTPONED": "postponed",
    "STATUS_CANCELED": "canceled",
    "STATUS_CANCELLED": "canceled",
    "STATUS_DELAYED": "delayed",
}


def slate_today() -> date:
    return datetime.now(EASTERN).date()


def iso_now() -> str:
    return datetime.now(EASTERN).isoformat(timespec="seconds")


def refresh_teams(conn) -> None:
    for team in espn.teams():
        color = team.get("color") or "888888"
        if not str(color).startswith("#"):
            color = f"#{color}"
        conn.execute(
            """
            INSERT INTO teams (id, abbr, name, color)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                abbr=excluded.abbr,
                name=excluded.name,
                color=excluded.color
            """,
            (str(team["id"]), team.get("abbreviation"), team.get("displayName"), color),
        )
        for athlete in espn.roster(str(team["id"])):
            position = (athlete.get("position") or {}).get("abbreviation")
            conn.execute(
                """
                INSERT INTO players (id, name, short_name, team_id, position)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    short_name=excluded.short_name,
                    team_id=excluded.team_id,
                    position=excluded.position
                """,
                (
                    str(athlete["id"]),
                    athlete.get("displayName") or athlete.get("fullName"),
                    athlete.get("shortName"),
                    str(team["id"]),
                    position,
                ),
            )


def ensure_player(conn, player_id: str, name: str | None = None, team_id: str | None = None) -> None:
    existing = conn.execute("SELECT id FROM players WHERE id=?", (player_id,)).fetchone()
    if existing and name:
        conn.execute(
            "UPDATE players SET name=COALESCE(?, name), team_id=COALESCE(?, team_id) WHERE id=?",
            (name, team_id, player_id),
        )
        return
    if existing:
        return
    if not name:
        payload = espn.athlete(player_id)
        if payload:
            name = payload.get("displayName")
            team_ref = (payload.get("team") or {}).get("$ref") or ""
            if "/teams/" in team_ref and not team_id:
                team_id = team_ref.split("/teams/")[1].split("?")[0]
    conn.execute(
        """
        INSERT INTO players (id, name, short_name, team_id, position)
        VALUES (?, ?, NULL, ?, NULL)
        ON CONFLICT(id) DO NOTHING
        """,
        (player_id, name or f"Player {player_id}", team_id),
    )


def discover(conn, start: date, end: date) -> int:
    found = 0
    cursor = start
    while cursor <= end:
        slate = cursor.isoformat()
        payload = espn.scoreboard(slate)
        for event in payload.get("events") or []:
            competition = (event.get("competitions") or [{}])[0]
            status_name = ((competition.get("status") or {}).get("type") or {}).get("name")
            status = STATUS_MAP.get(status_name, "scheduled")
            home = away = None
            for competitor in competition.get("competitors") or []:
                side = competitor.get("homeAway")
                team_id = str((competitor.get("team") or {}).get("id") or "")
                raw_score = competitor.get("score")
                score = None
                if status in {"final", "live"} and raw_score not in (None, ""):
                    try:
                        score = int(raw_score)
                    except ValueError:
                        score = None
                if side == "home":
                    home = (team_id, score)
                elif side == "away":
                    away = (team_id, score)
            if not home or not away:
                continue
            existing = conn.execute(
                "SELECT frozen FROM games WHERE id=?",
                (str(event["id"]),),
            ).fetchone()
            if existing and existing["frozen"]:
                continue
            conn.execute(
                """
                INSERT INTO games (
                    id, slate_date, tip_utc, status, home_id, away_id,
                    home_score, away_score, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    slate_date=excluded.slate_date,
                    tip_utc=excluded.tip_utc,
                    status=excluded.status,
                    home_id=excluded.home_id,
                    away_id=excluded.away_id,
                    home_score=excluded.home_score,
                    away_score=excluded.away_score,
                    updated_at=excluded.updated_at
                """,
                (
                    str(event["id"]),
                    slate,
                    event.get("date"),
                    status,
                    home[0],
                    away[0],
                    home[1],
                    away[1],
                    iso_now(),
                ),
            )
            found += 1
        cursor += timedelta(days=1)
    conn.commit()
    return found


def athlete_id(row: dict) -> str:
    athlete = row.get("athlete") or {}
    if athlete.get("id"):
        return str(athlete["id"])
    ref = athlete.get("$ref") or ""
    if "/athletes/" in ref:
        return ref.split("/athletes/")[1].split("?")[0]
    return ""


def collapse_props(rows: list[dict]) -> list[dict]:
    grouped: dict[tuple, dict] = {}
    for row in rows:
        player_id = athlete_id(row)
        if not player_id:
            continue
        market = ((row.get("type") or {}).get("name")) or "Unknown"
        kind = kind_for(market)
        current = ((row.get("current") or {}).get("target") or {})
        opened = ((row.get("open") or {}).get("target") or {})
        odds = row.get("odds") or {}
        line = current.get("displayValue") or (odds.get("total") or {}).get("value") or ""
        line_open = opened.get("displayValue") or (odds.get("total") or {}).get("open") or ""
        price = (odds.get("american") or {}).get("value")
        price_open = (odds.get("american") or {}).get("open")
        line_key = line if kind == "milestone" else ""
        key = (player_id, market, line_key)
        entry = grouped.get(key)
        if entry is None:
            entry = {
                "player_id": player_id,
                "market": market,
                "kind": kind,
                "code": code_for(market),
                "line": line,
                "line_open": line_open,
                "prices": [],
            }
            grouped[key] = entry
        if line:
            entry["line"] = line
        if line_open and not entry["line_open"]:
            entry["line_open"] = line_open
        entry["prices"].append((price, price_open))

    collapsed = []
    for entry in grouped.values():
        prices = sorted(entry["prices"], key=lambda item: american_value(item[0]))
        price_a, price_a_open = prices[0] if prices else (None, None)
        price_b, price_b_open = prices[1] if len(prices) > 1 else (None, None)
        line = entry["line"] or ""
        collapsed.append(
            {
                "player_id": entry["player_id"],
                "market": entry["market"],
                "code": entry["code"],
                "kind": entry["kind"],
                "line": line,
                "line_num": parse_line(line),
                "line_open": entry["line_open"] or "",
                "price_a": price_a,
                "price_a_open": price_a_open,
                "price_b": price_b,
                "price_b_open": price_b_open,
                "result": "pending",
                "actual": None,
            }
        )
    return collapsed


def parse_summary(payload: dict) -> tuple[dict, dict]:
    quarters: dict[str, dict[int, dict]] = {}
    plays = payload.get("plays") or []
    for play in plays:
        consume_play(play, quarters)
    first_player, by_team = first_baskets(plays)
    players: dict[str, dict] = {}
    for team_block in (payload.get("boxscore") or {}).get("players") or []:
        team_id = str((team_block.get("team") or {}).get("id") or "")
        groups = team_block.get("statistics") or []
        if not groups:
            continue
        labels = groups[0].get("labels") or []
        for athlete in groups[0].get("athletes") or []:
            info = athlete.get("athlete") or {}
            player_id = str(info.get("id") or "")
            if not player_id:
                continue
            parsed = parse_box_stats(labels, athlete.get("stats") or [])
            played = (not athlete.get("didNotPlay")) and parsed["seconds"] > 0
            players[player_id] = {
                "player_id": player_id,
                "name": info.get("displayName"),
                "team_id": team_id,
                "starter": 1 if athlete.get("starter") else 0,
                "played": played,
                "quarters": quarters.get(player_id) or {},
                **parsed,
            }
    return players, {
        "first_basket": first_player,
        "first_team_fg": by_team,
        "first_three": first_three(plays),
    }


def spread_bits(payload: dict | None) -> tuple[str | None, float | None]:
    if not payload:
        return None, None
    if "items" in payload:
        items = payload.get("items") or []
        payload = items[0] if items else None
    if not payload:
        return None, None
    total = payload.get("overUnder")
    try:
        total_value = float(total) if total is not None else None
    except (TypeError, ValueError):
        total_value = None
    return payload.get("details"), total_value


def fetch_game(game: dict) -> dict:
    event_id = game["id"]
    try:
        raw_props = espn.prop_bets(event_id)
        odds = spread_bits(espn.game_odds(event_id))
        players = {}
        context = {}
        if game["status"] in {"final", "live"}:
            payload = espn.summary(event_id)
            if not payload:
                return {
                    "id": event_id,
                    "props": None,
                    "players": {},
                    "spread": None,
                    "total": None,
                    "error": "box score unavailable",
                }
            players, context = parse_summary(payload)
        props = None if raw_props is None else collapse_props(raw_props)
        if props is not None and game["status"] == "final":
            for prop in props:
                player = players.get(prop["player_id"])
                result, actual = grade_prop(prop, player, context)
                prop["result"] = result
                prop["actual"] = actual
        return {
            "id": event_id,
            "props": props,
            "players": players,
            "spread": odds[0],
            "total": odds[1],
            "error": None,
        }
    except Exception as error:
        return {
            "id": event_id,
            "props": None,
            "players": {},
            "spread": None,
            "total": None,
            "error": f"{error}\n{traceback.format_exc(limit=2)}",
        }


def store_game(conn, game: dict, fetched: dict) -> None:
    if fetched["error"]:
        conn.execute(
            "UPDATE games SET props_note=?, updated_at=? WHERE id=?",
            (fetched["error"].splitlines()[0][:240], iso_now(), game["id"]),
        )
        return

    props = fetched["props"]
    players = fetched["players"]
    for player_id, player in players.items():
        ensure_player(conn, player_id, player.get("name"), player.get("team_id"))
    if props:
        for prop in props:
            if prop["player_id"] not in players:
                ensure_player(conn, prop["player_id"])

    conn.execute("DELETE FROM player_games WHERE game_id=?", (game["id"],))
    conn.executemany(
        """
        INSERT INTO player_games (
            game_id, player_id, team_id, minutes, seconds, starter,
            pts, reb, ast, fg3m, stl, blk, tov,
            fgm, fga, ftm, fta, fg3a, oreb, plus_minus
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                game["id"],
                player["player_id"],
                player["team_id"],
                player["minutes"],
                player["seconds"],
                player["starter"],
                player["pts"],
                player["reb"],
                player["ast"],
                player["fg3m"],
                player["stl"],
                player["blk"],
                player["tov"],
                player.get("fgm"),
                player.get("fga"),
                player.get("ftm"),
                player.get("fta"),
                player.get("fg3a"),
                player.get("oreb"),
                player.get("plus_minus"),
            )
            for player in players.values()
        ],
    )

    if props is not None:
        if game["status"] == "final":
            keep_milestone_ladder(conn, game["id"], props, players)
        conn.execute("DELETE FROM props WHERE game_id=?", (game["id"],))
        conn.executemany(
            """
            INSERT INTO props (
                game_id, player_id, market, code, kind, line, line_num, line_open,
                price_a, price_a_open, price_b, price_b_open, result, actual
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    game["id"],
                    prop["player_id"],
                    prop["market"],
                    prop["code"],
                    prop["kind"],
                    prop["line"],
                    prop["line_num"],
                    prop["line_open"],
                    prop["price_a"],
                    prop["price_a_open"],
                    prop["price_b"],
                    prop["price_b_open"],
                    prop["result"],
                    prop["actual"],
                )
                for prop in props
            ],
        )
        write_snapshots(conn, game["id"], props)

    freeze = game["status"] == "final" and props is not None
    note = None
    if props is None:
        note = "lines not posted"
    elif game["status"] == "final":
        note = "final"
    conn.execute(
        """
        UPDATE games
        SET spread=COALESCE(?, spread),
            total=COALESCE(?, total),
            frozen=?,
            props_note=?,
            updated_at=?
        WHERE id=?
        """,
        (
            fetched["spread"],
            fetched["total"],
            1 if freeze else 0,
            note,
            iso_now(),
            game["id"],
        ),
    )


def regrade_incomplete(conn) -> None:
    game_ids = [
        row[0]
        for row in conn.execute("SELECT DISTINCT game_id FROM props WHERE result='ungraded'")
    ]
    if not game_ids:
        return
    print(f"Regrading {len(game_ids)} games")
    for game_id in game_ids:
        payload = espn.summary(game_id)
        if not payload:
            continue
        players, context = parse_summary(payload)
        rows = conn.execute(
            "SELECT * FROM props WHERE game_id=? AND result='ungraded'",
            (game_id,),
        ).fetchall()
        for row in rows:
            prop = {
                "market": row["market"],
                "kind": kind_for(row["market"]),
                "line_num": row["line_num"] if row["line_num"] is not None else parse_line(row["line"]),
            }
            result, actual = grade_prop(prop, players.get(row["player_id"]), context)
            conn.execute(
                """
                UPDATE props
                SET kind=?, code=?, line_num=?, result=?, actual=?
                WHERE game_id=? AND player_id=? AND market=? AND line=?
                """,
                (
                    kind_for(row["market"]),
                    code_for(row["market"]),
                    prop["line_num"],
                    result,
                    actual,
                    game_id,
                    row["player_id"],
                    row["market"],
                    row["line"] or "",
                ),
            )
    conn.commit()


def keep_milestone_ladder(conn, game_id: str, props: list[dict], players: dict) -> None:
    """Finished games drop alternate milestones. Keep any ladder already stored."""
    seen = {
        (prop["player_id"], prop["market"], prop["line"] or "")
        for prop in props
        if prop["kind"] == "milestone"
    }
    rows = conn.execute(
        "SELECT * FROM props WHERE game_id=? AND kind='milestone'",
        (game_id,),
    )
    for row in rows:
        key = (row["player_id"], row["market"], row["line"] or "")
        if key in seen:
            continue
        prop = {
            "player_id": row["player_id"],
            "market": row["market"],
            "kind": "milestone",
            "code": row["code"],
            "line": row["line"] or "",
            "line_num": row["line_num"],
            "line_open": row["line_open"] or "",
            "price_a": row["price_a"],
            "price_a_open": row["price_a_open"],
            "price_b": row["price_b"],
            "price_b_open": row["price_b_open"],
        }
        result, actual = grade_prop(prop, players.get(row["player_id"]), {})
        prop["result"] = result
        prop["actual"] = actual
        props.append(prop)


def write_snapshots(conn, game_id: str, props: list[dict]) -> None:
    existing: dict[tuple, tuple] = {}
    rows = conn.execute(
        """
        SELECT player_id, market, line, price_a, price_b, captured_at
        FROM line_snapshots
        WHERE game_id=?
        ORDER BY captured_at
        """,
        (game_id,),
    )
    for row in rows:
        existing[(row["player_id"], row["market"], row["line"] or "")] = (
            row["price_a"],
            row["price_b"],
        )
    captured = iso_now()
    fresh = []
    for prop in props:
        signature = (prop["price_a"], prop["price_b"])
        key = (prop["player_id"], prop["market"], prop["line"] or "")
        if existing.get(key) == signature:
            continue
        fresh.append(
            (
                game_id,
                prop["player_id"],
                prop["market"],
                prop["line"],
                prop["price_a"],
                prop["price_b"],
                captured,
            )
        )
    if fresh:
        conn.executemany(
            """
            INSERT INTO line_snapshots (
                game_id, player_id, market, line, price_a, price_b, captured_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            fresh,
        )


def backfill_shooting(conn) -> None:
    """Final games were stored before field-goal attempts were kept."""
    game_ids = [
        row[0]
        for row in conn.execute(
            """
            SELECT DISTINCT g.id
            FROM games g
            JOIN player_games pg ON pg.game_id = g.id
            WHERE g.status='final' AND pg.seconds > 0 AND pg.fga IS NULL
            """
        )
    ]
    if not game_ids:
        print("Shooting totals already stored")
        return
    workers = int(os.environ.get("PROPCOMP_WORKERS") or "5")
    print(f"Backfilling shooting totals for {len(game_ids)} games")
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        future_map = {pool.submit(espn.summary, game_id): game_id for game_id in game_ids}
        for future in as_completed(future_map):
            game_id = future_map[future]
            done += 1
            try:
                payload = future.result()
            except Exception as error:
                print(f"[{done}/{len(game_ids)}] {game_id} shooting error {error}", flush=True)
                continue
            if not payload:
                print(f"[{done}/{len(game_ids)}] {game_id} shooting missing", flush=True)
                continue
            players, _context = parse_summary(payload)
            conn.executemany(
                """
                UPDATE player_games
                SET fgm=?, fga=?, ftm=?, fta=?, fg3a=?, oreb=?, plus_minus=?
                WHERE game_id=? AND player_id=?
                """,
                [
                    (
                        player.get("fgm"),
                        player.get("fga"),
                        player.get("ftm"),
                        player.get("fta"),
                        player.get("fg3a"),
                        player.get("oreb"),
                        player.get("plus_minus"),
                        game_id,
                        player["player_id"],
                    )
                    for player in players.values()
                ],
            )
            conn.commit()
            print(f"[{done}/{len(game_ids)}] {game_id} shooting stored", flush=True)


def main() -> None:
    today = slate_today()
    end = today + timedelta(days=2)
    limit = int(os.environ.get("PROPCOMP_LIMIT") or "0")
    workers = int(os.environ.get("PROPCOMP_WORKERS") or "5")
    conn = connect()
    print(f"Prop Comp sync {SEASON_START.isoformat()} through {end.isoformat()}")
    print("Refreshing teams and rosters")
    refresh_teams(conn)
    conn.commit()
    print("Reading the slate")
    discover(conn, SEASON_START, end)
    games = [
        dict(row)
        for row in conn.execute(
            """
            SELECT * FROM games
            WHERE frozen=0 AND slate_date<=?
            ORDER BY slate_date, tip_utc
            """,
            (end.isoformat(),),
        )
    ]
    if limit:
        games = games[:limit]
    print(f"Fetching lines for {len(games)} games with {workers} workers")
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        future_map = {pool.submit(fetch_game, game): game for game in games}
        for future in as_completed(future_map):
            game = future_map[future]
            fetched = future.result()
            store_game(conn, game, fetched)
            conn.commit()
            done += 1
            count = len(fetched["props"]) if fetched["props"] is not None else "none"
            status = "error" if fetched["error"] else game["status"]
            print(
                f"[{done}/{len(games)}] {game['slate_date']} {game['id']} {status} props={count}",
                flush=True,
            )
    regrade_incomplete(conn)
    backfill_shooting(conn)
    availability.refresh(conn)
    print("Writing the site")
    export.build(conn)
    conn.close()
    print("Sync finished")


if __name__ == "__main__":
    main()
