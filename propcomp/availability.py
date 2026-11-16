from __future__ import annotations

from propcomp import espn
from propcomp.signals import POSITIONS

STATUS_RANK = {"active": 0, "risk": 1, "out": 2}


def injury_bucket(status: str | None, fantasy: str | None = None) -> tuple[str, str]:
    label = (status or fantasy or "").strip()
    text = f"{status or ''} {fantasy or ''}".lower()
    if "out" in text and "day" not in text:
        return "out", label or "Out"
    if any(word in text for word in ("doubt", "question", "day-to-day", "day to day", "gtd")):
        return "risk", label or "At risk"
    return "active", label


def blocks_lineup(bucket: str, label: str) -> bool:
    text = (label or "").lower()
    return bucket == "out" or "doubt" in text


def parse_depth(payload: dict | None) -> dict[str, list[dict]]:
    positions = {pos: [] for pos in POSITIONS}
    if not payload:
        return positions
    charts = payload.get("depthchart") or []
    if not charts:
        return positions
    raw = charts[0].get("positions") or {}
    for pos in POSITIONS:
        for athlete in (raw.get(pos) or {}).get("athletes") or []:
            player_id = str(athlete.get("id") or "")
            if not player_id:
                continue
            injury = (athlete.get("injuries") or [None])[0] or {}
            bucket, label = injury_bucket(injury.get("status"))
            positions[pos].append(
                {
                    "player_id": player_id,
                    "name": athlete.get("displayName") or "",
                    "pos": pos.upper(),
                    "bucket": bucket,
                    "label": label if bucket != "active" else "",
                    "detail": "",
                }
            )
    return positions


def parse_game_injuries(payload: dict | None) -> dict[str, dict]:
    found = {}
    if not payload:
        return found
    for team in payload.get("injuries") or []:
        team_id = str((team.get("team") or {}).get("id") or "")
        for row in team.get("injuries") or []:
            athlete = row.get("athlete") or {}
            player_id = str(athlete.get("id") or "")
            if not player_id:
                continue
            details = row.get("details") or {}
            fantasy = (details.get("fantasyStatus") or {}).get("description")
            bucket, label = injury_bucket(row.get("status"), fantasy)
            detail = details.get("type") or ""
            if details.get("location") and details.get("location") != "Other":
                detail = f"{detail} {details.get('location')}".strip()
            found[player_id] = {
                "player_id": player_id,
                "name": athlete.get("displayName") or "",
                "team_id": team_id,
                "pos": ((athlete.get("position") or {}).get("abbreviation") or "").upper(),
                "bucket": bucket,
                "label": label,
                "detail": detail.strip(),
            }
    return found


def project_team(depth: dict[str, list[dict]], injuries: dict[str, dict], team_id: str) -> list[dict]:
    def state_for(player: dict) -> dict:
        report = injuries.get(player["player_id"])
        if report:
            return report
        return player

    used = set()
    rows = []
    for index, pos in enumerate(POSITIONS):
        skipped = []
        chosen = None
        for athlete in depth.get(pos) or []:
            if athlete["player_id"] in used:
                continue
            current = state_for(athlete)
            if blocks_lineup(current["bucket"], current.get("label") or ""):
                skipped.append(current.get("name") or athlete.get("name"))
                continue
            chosen = current
            chosen["pos"] = pos.upper()
            break
        if not chosen:
            continue
        used.add(chosen["player_id"])
        rows.append(
            {
                "player_id": chosen["player_id"],
                "team_id": team_id,
                "name": chosen.get("name") or "",
                "pos": pos.upper(),
                "role": "starter",
                "rank": index,
                "status": chosen["bucket"] if chosen["bucket"] != "out" else "risk",
                "label": chosen.get("label") or "",
                "detail": chosen.get("detail") or "",
                "replaces": ", ".join(name for name in skipped if name),
            }
        )

    rotation_rank = 10
    seen = set(used)
    for pos in POSITIONS:
        for athlete in depth.get(pos) or []:
            if athlete["player_id"] in seen:
                continue
            current = state_for(athlete)
            if blocks_lineup(current["bucket"], current.get("label") or ""):
                continue
            seen.add(athlete["player_id"])
            rows.append(
                {
                    "player_id": athlete["player_id"],
                    "team_id": team_id,
                    "name": current.get("name") or athlete.get("name") or "",
                    "pos": (current.get("pos") or pos).upper(),
                    "role": "rotation",
                    "rank": rotation_rank,
                    "status": current["bucket"],
                    "label": current.get("label") or "",
                    "detail": current.get("detail") or "",
                    "replaces": "",
                }
            )
            rotation_rank += 1

    for player_id, report in injuries.items():
        if player_id in seen or report.get("team_id") not in {team_id, ""}:
            continue
        if report.get("team_id") and report["team_id"] != team_id:
            continue
        seen.add(player_id)
        rows.append(
            {
                "player_id": player_id,
                "team_id": team_id,
                "name": report.get("name") or "",
                "pos": report.get("pos") or "",
                "role": "rotation",
                "rank": 180 if report["bucket"] == "out" else 160,
                "status": report["bucket"],
                "label": report.get("label") or "",
                "detail": report.get("detail") or "",
                "replaces": "",
            }
        )
    for athlete in [item for pos in POSITIONS for item in depth.get(pos) or []]:
        if athlete["player_id"] in seen:
            continue
        current = state_for(athlete)
        if current["bucket"] != "out" and not blocks_lineup(current["bucket"], current.get("label") or ""):
            continue
        seen.add(athlete["player_id"])
        rows.append(
            {
                "player_id": athlete["player_id"],
                "team_id": team_id,
                "name": current.get("name") or athlete.get("name") or "",
                "pos": (current.get("pos") or athlete.get("pos") or "").upper(),
                "role": "rotation",
                "rank": 200,
                "status": "out" if current["bucket"] == "out" else "risk",
                "label": current.get("label") or "Out",
                "detail": current.get("detail") or "",
                "replaces": "",
            }
        )
    return rows


def refresh(conn) -> None:
    games = [
        dict(row)
        for row in conn.execute(
            "SELECT * FROM games WHERE status!='final' ORDER BY slate_date, tip_utc"
        )
    ]
    if not games:
        return
    team_ids = sorted({game["home_id"] for game in games} | {game["away_id"] for game in games})
    charts = {}
    for team_id in team_ids:
        if not team_id:
            continue
        charts[team_id] = parse_depth(espn.depth_chart(team_id))
    print(f"Lineups and injuries for {len(games)} upcoming games")
    for game in games:
        payload = espn.summary(game["id"])
        injuries = parse_game_injuries(payload)
        rows = []
        rows.extend(project_team(charts.get(game["home_id"]) or {}, injuries, game["home_id"]))
        rows.extend(project_team(charts.get(game["away_id"]) or {}, injuries, game["away_id"]))
        conn.execute("DELETE FROM availability WHERE game_id=?", (game["id"],))
        conn.executemany(
            """
            INSERT INTO availability (
                game_id, player_id, team_id, pos, role, rank, status, label, detail, replaces
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    game["id"],
                    row["player_id"],
                    row["team_id"],
                    row["pos"],
                    row["role"],
                    row["rank"],
                    row["status"],
                    row["label"],
                    row["detail"],
                    row["replaces"],
                )
                for row in rows
            ],
        )
        for row in rows:
            if row["name"]:
                conn.execute(
                    """
                    INSERT INTO players (id, name, short_name, team_id, position)
                    VALUES (?, ?, NULL, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        name=excluded.name,
                        team_id=COALESCE(excluded.team_id, players.team_id),
                        position=COALESCE(players.position, excluded.position)
                    """,
                    (row["player_id"], row["name"], row["team_id"], row["pos"]),
                )
    conn.commit()
