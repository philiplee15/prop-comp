from __future__ import annotations

import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "propcomp.sqlite"
DOCS = ROOT / "docs"

SCHEMA = """
CREATE TABLE IF NOT EXISTS teams (
    id TEXT PRIMARY KEY,
    abbr TEXT NOT NULL,
    name TEXT NOT NULL,
    color TEXT
);

CREATE TABLE IF NOT EXISTS players (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    short_name TEXT,
    team_id TEXT,
    position TEXT
);

CREATE TABLE IF NOT EXISTS games (
    id TEXT PRIMARY KEY,
    slate_date TEXT NOT NULL,
    tip_utc TEXT,
    status TEXT NOT NULL,
    home_id TEXT,
    away_id TEXT,
    home_score INTEGER,
    away_score INTEGER,
    spread TEXT,
    total REAL,
    frozen INTEGER NOT NULL DEFAULT 0,
    props_note TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS player_games (
    game_id TEXT NOT NULL,
    player_id TEXT NOT NULL,
    team_id TEXT,
    minutes TEXT,
    seconds INTEGER,
    starter INTEGER,
    pts INTEGER,
    reb INTEGER,
    ast INTEGER,
    fg3m INTEGER,
    stl INTEGER,
    blk INTEGER,
    tov INTEGER,
    PRIMARY KEY (game_id, player_id)
);

CREATE TABLE IF NOT EXISTS props (
    game_id TEXT NOT NULL,
    player_id TEXT NOT NULL,
    market TEXT NOT NULL,
    code TEXT NOT NULL,
    kind TEXT NOT NULL,
    line TEXT,
    line_num REAL,
    line_open TEXT,
    price_a TEXT,
    price_a_open TEXT,
    price_b TEXT,
    price_b_open TEXT,
    result TEXT,
    actual REAL,
    PRIMARY KEY (game_id, player_id, market, line)
);

CREATE TABLE IF NOT EXISTS line_snapshots (
    game_id TEXT NOT NULL,
    player_id TEXT NOT NULL,
    market TEXT NOT NULL,
    line TEXT,
    price_a TEXT,
    price_b TEXT,
    captured_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_games_date ON games (slate_date);
CREATE INDEX IF NOT EXISTS idx_props_game ON props (game_id);
CREATE INDEX IF NOT EXISTS idx_props_player ON props (player_id);
CREATE INDEX IF NOT EXISTS idx_snapshots_game ON line_snapshots (game_id, player_id, market);
"""


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(SCHEMA)
    return conn
