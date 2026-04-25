from db.database import db_get, db_all, db_run
from config import MAX_SKILLS, MAX_SPELLS, MAX_COMPANIONS
import json


def add_skill(telegram_id: int, skill: dict, session_id: int = None) -> dict:
    count = db_get("SELECT COUNT(*) as cnt FROM skills WHERE telegram_id=? AND is_active=1", (telegram_id,))
    active_count = count["cnt"] if count else 0

    is_active = 1 if active_count < MAX_SKILLS else 0
    skill_id = db_run(
        "INSERT INTO skills (telegram_id, name, description, effect, is_active, obtained_in) VALUES (?,?,?,?,?,?)",
        (telegram_id, skill["name"], skill.get("description", ""),
         json.dumps(skill.get("effect", {}), ensure_ascii=False), is_active, session_id)
    )
    return {"id": skill_id, "active": bool(is_active), "name": skill["name"]}


def add_spell(telegram_id: int, spell: dict, session_id: int = None) -> dict:
    count = db_get("SELECT COUNT(*) as cnt FROM spells WHERE telegram_id=? AND is_active=1", (telegram_id,))
    active_count = count["cnt"] if count else 0

    is_active = 1 if active_count < MAX_SPELLS else 0
    spell_id = db_run(
        "INSERT INTO spells (telegram_id, name, description, mana_cost, element, effect, is_active, obtained_in) VALUES (?,?,?,?,?,?,?,?)",
        (telegram_id, spell["name"], spell.get("description", ""), spell.get("mana_cost", 10),
         spell.get("element", ""), json.dumps(spell.get("effect", {}), ensure_ascii=False), is_active, session_id)
    )
    return {"id": spell_id, "active": bool(is_active), "name": spell["name"]}


def add_companion(telegram_id: int, companion: dict, session_id: int = None) -> dict:
    count = db_get("SELECT COUNT(*) as cnt FROM companions WHERE telegram_id=?", (telegram_id,))
    if count and count["cnt"] >= MAX_COMPANIONS:
        return {"success": False, "reason": f"Já tens {MAX_COMPANIONS} companheiros. Liberta um primeiro com /companions."}

    cid = db_run(
        "INSERT INTO companions (telegram_id, name, animal_type, hp, hp_max, atk, def, special, description, obtained_in) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (telegram_id, companion["name"], companion.get("animal_type", "animal"),
         companion.get("hp", 50), companion.get("hp", 50),
         companion.get("atk", 8), companion.get("def", 4),
         companion.get("special", ""), companion.get("description", ""), session_id)
    )
    from game.player import increment_stat
    increment_stat(telegram_id, "total_tamed")
    return {"success": True, "id": cid, "name": companion["name"]}


def get_skills(telegram_id: int) -> list[dict]:
    return db_all("SELECT * FROM skills WHERE telegram_id=? ORDER BY is_active DESC, id ASC", (telegram_id,))


def get_spells(telegram_id: int) -> list[dict]:
    return db_all("SELECT * FROM spells WHERE telegram_id=? ORDER BY is_active DESC, id ASC", (telegram_id,))


def get_companions(telegram_id: int) -> list[dict]:
    return db_all("SELECT * FROM companions WHERE telegram_id=?", (telegram_id,))


def release_companion(telegram_id: int, companion_id: int) -> bool:
    c = db_get("SELECT * FROM companions WHERE id=? AND telegram_id=?", (companion_id, telegram_id))
    if not c:
        return False
    db_run("DELETE FROM companions WHERE id=?", (companion_id,))
    return True


def toggle_skill(telegram_id: int, skill_id: int) -> bool:
    skill = db_get("SELECT * FROM skills WHERE id=? AND telegram_id=?", (skill_id, telegram_id))
    if not skill:
        return False
    if skill["is_active"]:
        db_run("UPDATE skills SET is_active=0 WHERE id=?", (skill_id,))
    else:
        count = db_get("SELECT COUNT(*) as cnt FROM skills WHERE telegram_id=? AND is_active=1", (telegram_id,))
        if count and count["cnt"] >= MAX_SKILLS:
            return False
        db_run("UPDATE skills SET is_active=1 WHERE id=?", (skill_id,))
    return True


def toggle_spell(telegram_id: int, spell_id: int) -> bool:
    spell = db_get("SELECT * FROM spells WHERE id=? AND telegram_id=?", (spell_id, telegram_id))
    if not spell:
        return False
    if spell["is_active"]:
        db_run("UPDATE spells SET is_active=0 WHERE id=?", (spell_id,))
    else:
        count = db_get("SELECT COUNT(*) as cnt FROM spells WHERE telegram_id=? AND is_active=1", (telegram_id,))
        if count and count["cnt"] >= MAX_SPELLS else False:
            return False
        db_run("UPDATE spells SET is_active=1 WHERE id=?", (spell_id,))
    return True


def format_skills_text(telegram_id: int) -> str:
    skills = get_skills(telegram_id)
    spells = get_spells(telegram_id)

    lines = []

    if skills:
        active = [s for s in skills if s["is_active"]]
        inactive = [s for s in skills if not s["is_active"]]
        lines.append(f"🎯 <b>Skills ({len(active)}/{MAX_SKILLS} ativas)</b>")
        for s in active:
            lines.append(f"  ✅ <b>{s['name']}</b>")
            lines.append(f"     <i>{s['description'][:80]}</i>")
        if inactive:
            lines.append(f"\n  <i>Inativas ({len(inactive)}):</i>")
            for s in inactive:
                lines.append(f"  ⏸ {s['name']}")
    else:
        lines.append("🎯 Nenhuma skill aprendida ainda.")

    lines.append("")

    if spells:
        active = [s for s in spells if s["is_active"]]
        inactive = [s for s in spells if not s["is_active"]]
        lines.append(f"✨ <b>Feitiços ({len(active)}/{MAX_SPELLS} ativos)</b>")
        for s in active:
            lines.append(f"  ✅ <b>{s['name']}</b> — {s['mana_cost']} MANA {('· ' + s['element']) if s['element'] else ''}")
            lines.append(f"     <i>{s['description'][:80]}</i>")
        if inactive:
            lines.append(f"\n  <i>Inativos ({len(inactive)}):</i>")
            for s in inactive:
                lines.append(f"  ⏸ {s['name']}")
    else:
        lines.append("✨ Nenhum feitiço aprendido ainda.")

    return "\n".join(lines)


def format_companions_text(telegram_id: int) -> str:
    companions = get_companions(telegram_id)
    if not companions:
        return "🐾 Nenhum companheiro. Doma animais durante as histórias com a skill <b>Domar</b>."

    lines = [f"🐾 <b>Companheiros ({len(companions)}/{MAX_COMPANIONS})</b>\n"]
    for c in companions:
        lines.append(f"🦁 <b>{c['name']}</b> ({c['animal_type']})")
        lines.append(f"   ❤️ {c['hp']}/{c['hp_max']} | ⚔️ {c['atk']} | 🛡️ {c['def']}")
        lines.append(f"   ✨ {c['special'] or 'Sem habilidade especial'}")
        if c["description"]:
            lines.append(f"   <i>{c['description'][:80]}</i>")
        lines.append("")

    return "\n".join(lines)


def level_up_choose(telegram_id: int, choice: str) -> str:
    """Aplica o bónus de level up escolhido pelo jogador."""
    bonuses = {
        "hp":   ("hp_max", 20, "❤️ +20 HP máximo"),
        "atk":  ("atk",    3,  "⚔️ +3 ATK"),
        "def":  ("def",    2,  "🛡️ +2 DEF"),
        "agi":  ("agi",    2,  "⚡ +2 AGI"),
        "mana": ("mana_max", 20, "💧 +20 MANA máximo"),
    }
    b = bonuses.get(choice)
    if not b:
        return "❌ Escolha inválida."
    field, amount, label = b
    db_run(f"UPDATE characters SET {field}={field}+? WHERE telegram_id=?", (amount, telegram_id))
    if field == "hp_max":
        db_run("UPDATE characters SET hp=hp+? WHERE telegram_id=?", (amount, telegram_id))
    if field == "mana_max":
        db_run("UPDATE characters SET mana=mana+? WHERE telegram_id=?", (amount, telegram_id))
    return label
