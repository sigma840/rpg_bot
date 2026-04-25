import json
import logging
from datetime import datetime
from db.database import db_get, db_all, db_run, json_get, json_set
from config import MAX_TURNS, DIFFICULTIES

logger = logging.getLogger(__name__)


def get_active_session(chat_id: int) -> dict | None:
    return db_get(
        "SELECT * FROM sessions WHERE chat_id=? AND status IN ('waiting','active') ORDER BY id DESC LIMIT 1",
        (chat_id,)
    )


def create_session(chat_id: int, created_by: int, difficulty: str = "normal") -> dict:
    sid = db_run(
        "INSERT INTO sessions (chat_id, created_by, difficulty, status) VALUES (?,?,?,'waiting')",
        (chat_id, created_by, difficulty)
    )
    return db_get("SELECT * FROM sessions WHERE id=?", (sid,))


def add_player_to_session(session_id: int, telegram_id: int, hp_max: int, mana_max: int) -> bool:
    existing = db_get(
        "SELECT id FROM session_players WHERE session_id=? AND telegram_id=?",
        (session_id, telegram_id)
    )
    if existing:
        return False
    db_run(
        "INSERT INTO session_players (session_id, telegram_id, hp_current, mana_current) VALUES (?,?,?,?)",
        (session_id, telegram_id, hp_max, mana_max)
    )
    return True


def get_session_players(session_id: int) -> list[dict]:
    """Retorna jogadores com info do personagem incluída."""
    players = db_all(
        "SELECT sp.*, c.name as char_name, c.race, c.class, c.atk, c.def, c.agi, "
        "c.hp_max, c.mana_max, c.avatar_desc, c.level "
        "FROM session_players sp "
        "JOIN characters c ON c.telegram_id = sp.telegram_id "
        "WHERE sp.session_id=?",
        (session_id,)
    )
    # Adiciona skills e companheiros
    for p in players:
        skills = db_all(
            "SELECT name FROM skills WHERE telegram_id=? AND is_active=1",
            (p["telegram_id"],)
        )
        p["skills"] = [s["name"] for s in skills]
        companions = db_all(
            "SELECT name, animal_type FROM companions WHERE telegram_id=?",
            (p["telegram_id"],)
        )
        p["companions"] = [f"{c['name']} ({c['animal_type']})" for c in companions]
    return players


def get_current_player(session: dict) -> dict | None:
    players = get_session_players(session["id"])
    alive = [p for p in players if p.get("is_alive", 1) and p.get("is_conscious", 1)]
    if not alive:
        return None
    idx = session.get("current_player_idx", 0) % len(alive)
    return alive[idx]


def advance_turn(session_id: int) -> dict:
    session = db_get("SELECT * FROM sessions WHERE id=?", (session_id,))
    players = get_session_players(session_id)
    alive = [p for p in players if p.get("is_alive", 1)]

    new_turn = session["current_turn"] + 1
    new_idx = (session["current_player_idx"] + 1) % max(len(alive), 1)

    db_run(
        "UPDATE sessions SET current_turn=?, current_player_idx=? WHERE id=?",
        (new_turn, new_idx, session_id)
    )
    return db_get("SELECT * FROM sessions WHERE id=?", (session_id,))


def update_story_summary(session_id: int, new_narration: str):
    session = db_get("SELECT * FROM sessions WHERE id=?", (session_id,))
    log = json_get(session.get("full_log", "[]"))
    log.append({"turn": session["current_turn"], "text": new_narration[:300]})
    # Resumo: guarda últimos 5 turnos
    summary_parts = [entry["text"] for entry in log[-5:]]
    summary = " | ".join(summary_parts)
    db_run(
        "UPDATE sessions SET story_summary=?, full_log=? WHERE id=?",
        (summary[:2000], json_set(log), session_id)
    )


def update_session_weather(session_id: int, weather: str = None, time_of_day: str = None):
    if weather:
        db_run("UPDATE sessions SET weather=? WHERE id=?", (weather, session_id))
    if time_of_day:
        db_run("UPDATE sessions SET time_of_day=? WHERE id=?", (time_of_day, session_id))


def start_session(session_id: int):
    db_run(
        "UPDATE sessions SET status='active', started_at=? WHERE id=?",
        (datetime.now().isoformat(), session_id)
    )


def end_session(session_id: int):
    db_run(
        "UPDATE sessions SET status='ended', ended_at=? WHERE id=?",
        (datetime.now().isoformat(), session_id)
    )


def is_story_over(session: dict) -> bool:
    return session.get("current_turn", 0) >= MAX_TURNS


def update_player_hp(session_id: int, telegram_id: int, new_hp: int, hp_max: int):
    is_alive = 1 if new_hp > 0 else 0
    is_conscious = 1 if new_hp > 0 else 0
    db_run(
        "UPDATE session_players SET hp_current=?, is_alive=?, is_conscious=? WHERE session_id=? AND telegram_id=?",
        (max(0, new_hp), is_alive, is_conscious, session_id, telegram_id)
    )


def revive_player(session_id: int, telegram_id: int, hp_restore: int = 30):
    db_run(
        "UPDATE session_players SET hp_current=?, is_alive=1, is_conscious=1 WHERE session_id=? AND telegram_id=?",
        (hp_restore, session_id, telegram_id)
    )


def set_alliance(session_id: int, player1_id: int, player2_id: int):
    db_run(
        "UPDATE session_players SET ally_id=? WHERE session_id=? AND telegram_id=?",
        (player2_id, session_id, player1_id)
    )
    db_run(
        "UPDATE session_players SET ally_id=? WHERE session_id=? AND telegram_id=?",
        (player1_id, session_id, player2_id)
    )


def add_session_stats(session_id: int, telegram_id: int, kills: int = 0, damage: int = 0, xp: int = 0, gold: int = 0):
    db_run("""
        UPDATE session_players SET
            session_kills=session_kills+?,
            session_damage=session_damage+?,
            session_xp=session_xp+?,
            session_gold=session_gold+?
        WHERE session_id=? AND telegram_id=?
    """, (kills, damage, xp, gold, session_id, telegram_id))


def get_session_leaderboard(session_id: int) -> list[dict]:
    return db_all("""
        SELECT sp.telegram_id, sp.session_kills, sp.session_damage, sp.session_xp, sp.session_gold,
               sp.is_alive, c.name as char_name, c.race, c.class,
               (sp.session_kills*10 + sp.session_damage + sp.session_xp +
                sp.session_gold + sp.is_alive*50) as score
        FROM session_players sp
        JOIN characters c ON c.telegram_id = sp.telegram_id
        WHERE sp.session_id=?
        ORDER BY score DESC
    """, (session_id,))


def get_past_sessions(chat_id: int, limit: int = 5) -> list[dict]:
    return db_all(
        "SELECT * FROM sessions WHERE chat_id=? AND status='ended' ORDER BY ended_at DESC LIMIT ?",
        (chat_id, limit)
    )
