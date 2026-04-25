from db.database import db_get, db_all, db_run, json_get, json_set
from config import RACES, CLASSES, ACHIEVEMENTS


def get_or_create_player(telegram_id: int, username: str, full_name: str):
    player = db_get("SELECT * FROM players WHERE telegram_id=?", (telegram_id,))
    if not player:
        db_run(
            "INSERT INTO players (telegram_id, username, full_name) VALUES (?,?,?)",
            (telegram_id, username, full_name)
        )
    return db_get("SELECT * FROM players WHERE telegram_id=?", (telegram_id,))


def get_character(telegram_id: int):
    return db_get("SELECT * FROM characters WHERE telegram_id=?", (telegram_id,))


def create_character(telegram_id: int, name: str, race: str, char_class: str, avatar_desc: str = ""):
    r = RACES[race]
    cl = CLASSES[char_class]

    hp_max = cl["hp"] + r["hp"]
    atk = cl["atk"] + r["atk"]
    defense = cl["def"] + r["def"]
    agi = cl["agi"] + r["agi"]
    mana_max = cl["mana"] + r["mana"]

    existing = get_character(telegram_id)
    if existing:
        # Mantém XP, nível, ouro, itens — só atualiza raça/classe/stats base
        db_run("""
            UPDATE characters SET
                name=?, race=?, class=?,
                hp=?, hp_max=?, atk=?, def=?, agi=?, mana=?, mana_max=?,
                avatar_desc=?, avatar_url=''
            WHERE telegram_id=?
        """, (name, race, char_class, hp_max, hp_max, atk, defense, agi, mana_max, mana_max, avatar_desc, telegram_id))
    else:
        db_run("""
            INSERT INTO characters
                (telegram_id, name, race, class, hp, hp_max, atk, def, agi, mana, mana_max, avatar_desc)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """, (telegram_id, name, race, char_class, hp_max, hp_max, atk, defense, agi, mana_max, mana_max, avatar_desc))

    return get_character(telegram_id)


def update_avatar_url(telegram_id: int, url: str):
    db_run("UPDATE characters SET avatar_url=? WHERE telegram_id=?", (url, telegram_id))


def get_character_sheet(telegram_id: int) -> str:
    char = get_character(telegram_id)
    if not char:
        return "❌ Não tens personagem criado. Usa /create_character"

    race_info = RACES.get(char["race"], {})
    class_info = CLASSES.get(char["class"], {})
    title = f' "{char["active_title"]}"' if char.get("active_title") else ""
    xp_next = char["level"] * 100

    lines = [
        f"{class_info.get('emoji','⚔️')} <b>{char['name']}{title}</b>",
        f"{race_info.get('emoji','👤')} {char['race'].capitalize()} · {char['class'].capitalize()} · Nível {char['level']}",
        f"",
        f"❤️ HP: {char['hp']}/{char['hp_max']}",
        f"💧 MANA: {char['mana']}/{char['mana_max']}",
        f"⚔️ ATK: {char['atk']}  🛡️ DEF: {char['def']}  ⚡ AGI: {char['agi']}",
        f"⭐ XP: {char['xp']}/{xp_next}  💰 Ouro: {char['gold']}",
        f"",
        f"📊 <b>Estatísticas Globais</b>",
        f"💀 Inimigos mortos: {char['total_kills']}",
        f"🩸 Dano total: {char['total_damage']}",
        f"☠️ Mortes: {char['total_deaths']}",
        f"📖 Histórias: {char['total_stories']}",
    ]
    return "\n".join(lines)


def add_xp(telegram_id: int, amount: int) -> dict:
    """Adiciona XP e faz level up se necessário. Retorna dict com info do level up."""
    char = get_character(telegram_id)
    if not char:
        return {}

    # Bónus de raça
    race_info = RACES.get(char["race"], {})
    xp_bonus = race_info.get("xp_bonus", 0)
    total_xp = int(amount * (1 + xp_bonus))

    new_xp = char["xp"] + total_xp
    new_level = char["level"]
    leveled_up = False

    while new_xp >= new_level * 100:
        new_xp -= new_level * 100
        new_level += 1
        leveled_up = True

    db_run(
        "UPDATE characters SET xp=?, level=? WHERE telegram_id=?",
        (new_xp, new_level, telegram_id)
    )

    check_achievements(telegram_id)
    return {"leveled_up": leveled_up, "new_level": new_level, "xp_gained": total_xp}


def add_gold(telegram_id: int, amount: int):
    db_run("UPDATE characters SET gold=gold+? WHERE telegram_id=?", (amount, telegram_id))
    check_achievements(telegram_id)


def update_stats(telegram_id: int, **kwargs):
    """Atualiza stats arbitrários do personagem."""
    allowed = {"hp", "hp_max", "mana", "mana_max", "atk", "def", "agi",
               "total_kills", "total_damage", "total_deaths", "total_stories",
               "total_betrayals", "total_alliances", "total_forges", "total_tamed",
               "boss_kills", "dungeons_done", "auctions_won"}
    sets = []
    vals = []
    for k, v in kwargs.items():
        if k in allowed:
            sets.append(f"{k}=?")
            vals.append(v)
    if sets:
        vals.append(telegram_id)
        db_run(f"UPDATE characters SET {', '.join(sets)} WHERE telegram_id=?", tuple(vals))
    check_achievements(telegram_id)


def increment_stat(telegram_id: int, field: str, amount: int = 1):
    allowed = {"total_kills", "total_damage", "total_deaths", "total_stories",
               "total_betrayals", "total_alliances", "total_forges", "total_tamed",
               "boss_kills", "dungeons_done", "auctions_won"}
    if field in allowed:
        db_run(f"UPDATE characters SET {field}={field}+? WHERE telegram_id=?", (amount, telegram_id))
    check_achievements(telegram_id)


def check_achievements(telegram_id: int):
    """Verifica e desbloqueia conquistas."""
    char = get_character(telegram_id)
    if not char:
        return []

    unlocked = json_get(char["achievements"])
    new_unlocked = []

    checks = {
        "first_blood":    char["total_kills"] >= 1,
        "killer_50":      char["total_kills"] >= 50,
        "killer_200":     char["total_kills"] >= 200,
        "stories_10":     char["total_stories"] >= 10,
        "stories_50":     char["total_stories"] >= 50,
        "legendary_3":    _count_legendary(telegram_id) >= 3,
        "deaths_10":      char["total_deaths"] >= 10,
        "betrayals_5":    char["total_betrayals"] >= 5,
        "tamer_10":       char["total_tamed"] >= 10,
        "forger_20":      char["total_forges"] >= 20,
        "damage_10000":   char["total_damage"] >= 10000,
        "gold_1000":      char["gold"] >= 1000,
        "alliance_10":    char["total_alliances"] >= 10,
        "boss_kill_10":   char["boss_kills"] >= 10,
        "dungeon_10":     char["dungeons_done"] >= 10,
        "auction_win_10": char["auctions_won"] >= 10,
        "level_20":       char["level"] >= 20,
        "level_50":       char["level"] >= 50,
    }

    # spells_12 verificado separadamente
    spell_count = db_get("SELECT COUNT(*) as cnt FROM spells WHERE telegram_id=? AND is_active=1", (telegram_id,))
    if spell_count and spell_count["cnt"] >= 12:
        checks["spells_12"] = True

    for key, condition in checks.items():
        if condition and key not in unlocked:
            unlocked.append(key)
            new_unlocked.append(key)
            # Atribui título automaticamente
            ach = ACHIEVEMENTS.get(key, {})
            if ach.get("title"):
                titles = json_get(char.get("unlocked_titles", "[]"))
                if ach["title"] not in titles:
                    titles.append(ach["title"])
                    db_run(
                        "UPDATE characters SET unlocked_titles=? WHERE telegram_id=?",
                        (json_set(titles), telegram_id)
                    )

    if new_unlocked:
        db_run(
            "UPDATE characters SET achievements=? WHERE telegram_id=?",
            (json_set(unlocked), telegram_id)
        )

    return new_unlocked


def _count_legendary(telegram_id: int) -> int:
    inv = db_get("SELECT COUNT(*) as cnt FROM inventory WHERE telegram_id=? AND rarity='lendário'", (telegram_id,))
    weap = db_get("SELECT COUNT(*) as cnt FROM weapons WHERE telegram_id=? AND rarity='lendário'", (telegram_id,))
    return (inv["cnt"] if inv else 0) + (weap["cnt"] if weap else 0)


def set_active_title(telegram_id: int, title: str) -> bool:
    char = get_character(telegram_id)
    if not char:
        return False
    titles = json_get(char.get("unlocked_titles", "[]"))
    if title not in titles and title != "":
        return False
    db_run("UPDATE characters SET active_title=? WHERE telegram_id=?", (title, telegram_id))
    return True


def get_leaderboard_global(limit: int = 10):
    return db_all("""
        SELECT c.name, c.race, c.class, c.level, c.total_kills, c.total_stories,
               c.total_damage, c.total_deaths, c.boss_kills, c.gold, c.active_title,
               (c.xp + c.level*100 + c.total_kills*10 + c.total_stories*50 +
                c.total_damage + c.boss_kills*30 - c.total_deaths*20) as score
        FROM characters c
        ORDER BY score DESC
        LIMIT ?
    """, (limit,))
