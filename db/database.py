import sqlite3
import json
from config import DB_PATH


def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_conn()
    c = conn.cursor()

    # ─── Players ──────────────────────────────────────────────────────────────
    c.execute("""
    CREATE TABLE IF NOT EXISTS players (
        telegram_id     INTEGER PRIMARY KEY,
        username        TEXT,
        full_name       TEXT,
        created_at      TEXT DEFAULT (datetime('now'))
    )""")

    # ─── Characters ───────────────────────────────────────────────────────────
    c.execute("""
    CREATE TABLE IF NOT EXISTS characters (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_id     INTEGER UNIQUE,
        name            TEXT NOT NULL,
        race            TEXT NOT NULL,
        class           TEXT NOT NULL,
        level           INTEGER DEFAULT 1,
        xp              INTEGER DEFAULT 0,
        hp              INTEGER DEFAULT 100,
        hp_max          INTEGER DEFAULT 100,
        atk             INTEGER DEFAULT 10,
        def             INTEGER DEFAULT 5,
        agi             INTEGER DEFAULT 5,
        mana            INTEGER DEFAULT 0,
        mana_max        INTEGER DEFAULT 0,
        gold            INTEGER DEFAULT 0,
        avatar_desc     TEXT DEFAULT '',
        avatar_url      TEXT DEFAULT '',
        total_kills     INTEGER DEFAULT 0,
        total_damage    INTEGER DEFAULT 0,
        total_deaths    INTEGER DEFAULT 0,
        total_stories   INTEGER DEFAULT 0,
        total_betrayals INTEGER DEFAULT 0,
        total_alliances INTEGER DEFAULT 0,
        total_forges    INTEGER DEFAULT 0,
        total_tamed     INTEGER DEFAULT 0,
        boss_kills      INTEGER DEFAULT 0,
        dungeons_done   INTEGER DEFAULT 0,
        auctions_won    INTEGER DEFAULT 0,
        active_title    TEXT DEFAULT '',
        unlocked_titles TEXT DEFAULT '[]',
        achievements    TEXT DEFAULT '[]',
        FOREIGN KEY (telegram_id) REFERENCES players(telegram_id)
    )""")

    # ─── Sessions ─────────────────────────────────────────────────────────────
    c.execute("""
    CREATE TABLE IF NOT EXISTS sessions (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id         INTEGER NOT NULL,
        status          TEXT DEFAULT 'waiting',
        difficulty      TEXT DEFAULT 'normal',
        current_turn    INTEGER DEFAULT 0,
        current_player_idx INTEGER DEFAULT 0,
        story_summary   TEXT DEFAULT '',
        full_log        TEXT DEFAULT '[]',
        weather         TEXT DEFAULT 'sol',
        time_of_day     TEXT DEFAULT 'dia',
        created_by      INTEGER,
        started_at      TEXT,
        ended_at        TEXT,
        winner_ids      TEXT DEFAULT '[]',
        created_at      TEXT DEFAULT (datetime('now'))
    )""")

    # ─── Session Players ──────────────────────────────────────────────────────
    c.execute("""
    CREATE TABLE IF NOT EXISTS session_players (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id      INTEGER,
        telegram_id     INTEGER,
        hp_current      INTEGER DEFAULT 100,
        mana_current    INTEGER DEFAULT 0,
        is_alive        INTEGER DEFAULT 1,
        is_conscious    INTEGER DEFAULT 1,
        secret_objective TEXT DEFAULT '',
        ally_id         INTEGER DEFAULT NULL,
        session_kills   INTEGER DEFAULT 0,
        session_damage  INTEGER DEFAULT 0,
        session_xp      INTEGER DEFAULT 0,
        session_gold    INTEGER DEFAULT 0,
        status_effects  TEXT DEFAULT '[]',
        FOREIGN KEY (session_id) REFERENCES sessions(id),
        FOREIGN KEY (telegram_id) REFERENCES players(telegram_id)
    )""")

    # ─── Inventory ────────────────────────────────────────────────────────────
    c.execute("""
    CREATE TABLE IF NOT EXISTS inventory (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_id     INTEGER,
        name            TEXT NOT NULL,
        item_type       TEXT NOT NULL,
        rarity          TEXT DEFAULT 'comum',
        description     TEXT DEFAULT '',
        effect          TEXT DEFAULT '{}',
        equipped        INTEGER DEFAULT 0,
        slot            TEXT DEFAULT '',
        quantity        INTEGER DEFAULT 1,
        obtained_in     INTEGER DEFAULT NULL,
        created_at      TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (telegram_id) REFERENCES players(telegram_id)
    )""")

    # ─── Weapons ──────────────────────────────────────────────────────────────
    c.execute("""
    CREATE TABLE IF NOT EXISTS weapons (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_id     INTEGER,
        name            TEXT NOT NULL,
        rarity          TEXT DEFAULT 'comum',
        lore            TEXT DEFAULT '',
        atk_bonus       INTEGER DEFAULT 0,
        def_bonus       INTEGER DEFAULT 0,
        agi_bonus       INTEGER DEFAULT 0,
        mana_bonus      INTEGER DEFAULT 0,
        element         TEXT DEFAULT '',
        special_effect  TEXT DEFAULT '',
        forge_level     INTEGER DEFAULT 0,
        equipped        INTEGER DEFAULT 0,
        slot            TEXT DEFAULT 'main_hand',
        obtained_in     INTEGER DEFAULT NULL,
        created_at      TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (telegram_id) REFERENCES players(telegram_id)
    )""")

    # ─── Skills ───────────────────────────────────────────────────────────────
    c.execute("""
    CREATE TABLE IF NOT EXISTS skills (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_id     INTEGER,
        name            TEXT NOT NULL,
        description     TEXT DEFAULT '',
        effect          TEXT DEFAULT '{}',
        is_active       INTEGER DEFAULT 1,
        obtained_in     INTEGER DEFAULT NULL,
        FOREIGN KEY (telegram_id) REFERENCES players(telegram_id)
    )""")

    # ─── Spells ───────────────────────────────────────────────────────────────
    c.execute("""
    CREATE TABLE IF NOT EXISTS spells (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_id     INTEGER,
        name            TEXT NOT NULL,
        description     TEXT DEFAULT '',
        mana_cost       INTEGER DEFAULT 10,
        effect          TEXT DEFAULT '{}',
        element         TEXT DEFAULT '',
        is_active       INTEGER DEFAULT 1,
        obtained_in     INTEGER DEFAULT NULL,
        FOREIGN KEY (telegram_id) REFERENCES players(telegram_id)
    )""")

    # ─── Companions ───────────────────────────────────────────────────────────
    c.execute("""
    CREATE TABLE IF NOT EXISTS companions (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_id     INTEGER,
        name            TEXT NOT NULL,
        animal_type     TEXT NOT NULL,
        hp              INTEGER DEFAULT 50,
        hp_max          INTEGER DEFAULT 50,
        atk             INTEGER DEFAULT 8,
        def             INTEGER DEFAULT 4,
        special         TEXT DEFAULT '',
        description     TEXT DEFAULT '',
        obtained_in     INTEGER DEFAULT NULL,
        FOREIGN KEY (telegram_id) REFERENCES players(telegram_id)
    )""")

    # ─── Guilds ───────────────────────────────────────────────────────────────
    c.execute("""
    CREATE TABLE IF NOT EXISTS guilds (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id         INTEGER UNIQUE,
        name            TEXT NOT NULL,
        emblem          TEXT DEFAULT '🛡️',
        level           INTEGER DEFAULT 1,
        xp              INTEGER DEFAULT 0,
        chest           TEXT DEFAULT '[]',
        created_at      TEXT DEFAULT (datetime('now'))
    )""")

    # ─── Auctions ─────────────────────────────────────────────────────────────
    c.execute("""
    CREATE TABLE IF NOT EXISTS auctions (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id         INTEGER,
        seller_id       INTEGER,
        item_id         INTEGER,
        item_table      TEXT DEFAULT 'inventory',
        starting_price  INTEGER DEFAULT 10,
        current_bid     INTEGER DEFAULT 0,
        highest_bidder  INTEGER DEFAULT NULL,
        status          TEXT DEFAULT 'active',
        ends_at         TEXT,
        created_at      TEXT DEFAULT (datetime('now'))
    )""")

    # ─── Global Events ────────────────────────────────────────────────────────
    c.execute("""
    CREATE TABLE IF NOT EXISTS global_events (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        title           TEXT NOT NULL,
        description     TEXT NOT NULL,
        effect          TEXT DEFAULT '{}',
        active          INTEGER DEFAULT 1,
        created_at      TEXT DEFAULT (datetime('now')),
        expires_at      TEXT
    )""")

    # ─── Forge History ────────────────────────────────────────────────────────
    c.execute("""
    CREATE TABLE IF NOT EXISTS forge_history (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_id     INTEGER,
        weapon_id       INTEGER,
        material_id     INTEGER,
        result_name     TEXT,
        success         INTEGER DEFAULT 1,
        created_at      TEXT DEFAULT (datetime('now'))
    )""")

    conn.commit()
    conn.close()
    print("✅ Base de dados iniciada com sucesso.")


# ─── Helpers ──────────────────────────────────────────────────────────────────

def db_get(query, params=()):
    conn = get_conn()
    row = conn.execute(query, params).fetchone()
    conn.close()
    return dict(row) if row else None


def db_all(query, params=()):
    conn = get_conn()
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def db_run(query, params=()):
    conn = get_conn()
    c = conn.execute(query, params)
    conn.commit()
    last_id = c.lastrowid
    conn.close()
    return last_id


def json_get(data, default=None):
    if default is None:
        default = []
    try:
        return json.loads(data) if data else default
    except Exception:
        return default


def json_set(data):
    return json.dumps(data, ensure_ascii=False)

