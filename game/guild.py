from db.database import db_get, db_all, db_run, json_get, json_set
import json


def get_guild(chat_id: int) -> dict | None:
    return db_get("SELECT * FROM guilds WHERE chat_id=?", (chat_id,))


def create_guild(chat_id: int, name: str, emblem: str = "🛡️") -> dict:
    existing = get_guild(chat_id)
    if existing:
        return {"success": False, "reason": "❌ Este grupo já tem uma guilda."}
    gid = db_run(
        "INSERT INTO guilds (chat_id, name, emblem) VALUES (?,?,?)",
        (chat_id, name, emblem)
    )
    return {"success": True, "id": gid, "name": name}


def add_to_chest(chat_id: int, item_name: str, item_desc: str, donated_by: str) -> bool:
    guild = get_guild(chat_id)
    if not guild:
        return False
    chest = json_get(guild.get("chest", "[]"))
    chest.append({"name": item_name, "desc": item_desc, "donated_by": donated_by})
    db_run("UPDATE guilds SET chest=? WHERE chat_id=?", (json_set(chest), chat_id))
    return True


def add_guild_xp(chat_id: int, amount: int):
    guild = get_guild(chat_id)
    if not guild:
        return
    new_xp = guild["xp"] + amount
    new_level = guild["level"]
    while new_xp >= new_level * 200:
        new_xp -= new_level * 200
        new_level += 1
    db_run("UPDATE guilds SET xp=?, level=? WHERE chat_id=?", (new_xp, new_level, chat_id))


def format_guild_text(chat_id: int) -> str:
    guild = get_guild(chat_id)
    if not guild:
        return "❌ Este grupo não tem guilda. Cria uma com /guild_create <nome> <emoji>"

    chest = json_get(guild.get("chest", "[]"))
    xp_next = guild["level"] * 200
    members = db_all(
        "SELECT c.name, c.level, c.class, c.active_title FROM characters c "
        "JOIN players p ON p.telegram_id = c.telegram_id "
        "ORDER BY c.level DESC LIMIT 10"
    )

    lines = [
        f"{guild['emblem']} <b>Guilda: {guild['name']}</b>",
        f"🏆 Nível {guild['level']} | XP: {guild['xp']}/{xp_next}",
        "",
        f"👥 <b>Membros ({len(members)})</b>",
    ]
    for m in members:
        title = f' "{m["active_title"]}"' if m.get("active_title") else ""
        lines.append(f"  • {m['name']}{title} — Nv.{m['level']} {m['class'].capitalize()}")

    lines.append(f"\n🎒 <b>Baú da Guilda ({len(chest)} itens)</b>")
    if chest:
        for item in chest[-5:]:
            lines.append(f"  • {item['name']} (doado por {item['donated_by']})")
    else:
        lines.append("  Baú vazio.")

    return "\n".join(lines)
