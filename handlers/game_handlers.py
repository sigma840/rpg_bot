import logging
import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from config import OWNER_ID, DIFFICULTIES, REVIVE_GOLD_COST
from game.player import get_character, add_xp, add_gold, increment_stat, update_stats, check_achievements
from game.session import (get_active_session, create_session, add_player_to_session,
                           get_session_players, get_current_player, advance_turn,
                           update_story_summary, start_session, end_session,
                           is_story_over, update_player_hp, revive_player,
                           set_alliance, add_session_stats, get_session_leaderboard,
                           get_past_sessions, update_session_weather)
from game.ai_narrator import generate_turn, generate_prologue, generate_epilogue
from game.images import generate_image
from game.inventory import add_item, add_weapon
from game.progression import add_skill, add_spell, add_companion, level_up_choose, get_skills, get_spells, get_companions
from game.combat import calculate_damage, calculate_enemy_damage, roll_dice, alliance_attack
from game.weather import format_weather_status, get_next_time, apply_weather_to_stats
from game.events import trigger_global_event, get_active_event_effects, generate_secret_objective
from game.guild import add_guild_xp
from db.database import db_get, db_run, db_all

logger = logging.getLogger(__name__)


# ─── /new_game ────────────────────────────────────────────────────────────────
async def cmd_new_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat

    if chat.type == "private":
        await update.message.reply_text("❌ Usa este comando num grupo do Telegram!")
        return

    existing = get_active_session(chat.id)
    if existing:
        await update.message.reply_text("❌ Já há uma história ativa. Usa /end_game primeiro.")
        return

    keyboard = [[InlineKeyboardButton(info["label"], callback_data=f"diff_{key}")]
                for key, info in DIFFICULTIES.items()]
    await update.message.reply_text(
        "⚔️ <b>Nova História</b>\n\nEscolhe a dificuldade:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML
    )


async def callback_difficulty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    difficulty = query.data.replace("diff_", "")
    chat_id = query.message.chat_id

    session = create_session(chat_id, query.from_user.id, difficulty)
    diff_info = DIFFICULTIES[difficulty]

    await query.edit_message_text(
        f"🏰 <b>Nova história criada!</b>\n"
        f"Dificuldade: {diff_info['label']}\n\n"
        f"Jogadores, usem /join para entrar.\n"
        f"Quando todos estiverem prontos, usa /begin para começar!",
        parse_mode=ParseMode.HTML
    )


# ─── /join ────────────────────────────────────────────────────────────────────
async def cmd_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat

    char = get_character(user.id)
    if not char:
        await update.message.reply_text("❌ Não tens personagem! Usa /create_character em privado primeiro.")
        return

    session = get_active_session(chat.id)
    if not session:
        await update.message.reply_text("❌ Não há nenhuma história ativa. Aguarda que alguém use /new_game.")
        return

    sp = db_get(
        "SELECT * FROM session_players WHERE session_id=? AND telegram_id=?",
        (session["id"], user.id)
    )
    if sp and not sp["is_alive"]:
        await update.message.reply_text("☠️ Já morreste nesta história e não podes voltar a entrar.")
        return

    joined = add_player_to_session(session["id"], user.id, char["hp_max"], char["mana_max"])
    if not joined:
        await update.message.reply_text("⚠️ Já estás nesta história!")
        return

    players = get_session_players(session["id"])
    status = "em curso" if session["status"] == "active" else "à espera"
    await update.message.reply_text(
        f"✅ <b>{char['name']}</b> entrou na história ({status})!\n"
        f"Jogadores: {len(players)}",
        parse_mode=ParseMode.HTML
    )


# ─── /begin ───────────────────────────────────────────────────────────────────
async def cmd_begin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat

    session = get_active_session(chat.id)
    if not session or session["status"] != "waiting":
        await update.message.reply_text("❌ Não há sessão à espera.")
        return

    start_session(session["id"])

    char = get_character(user.id)
    if char:
        add_player_to_session(session["id"], user.id, char["hp_max"], char["mana_max"])

    players = get_session_players(session["id"])

    await update.message.reply_text("⏳ A gerar o prólogo da história...")

    result = await generate_prologue(chat.id, session, players)
    if not result:
        from db.database import db_run as _db_run
        _db_run("UPDATE sessions SET status='waiting' WHERE id=?", (session["id"],))
        await update.message.reply_text("❌ Erro ao gerar prólogo. Tenta /begin novamente.")
        return

    events = result.get("events", {})
    if events.get("weather_change"):
        update_session_weather(session["id"], weather=events["weather_change"])
    if events.get("time_change"):
        update_session_weather(session["id"], time_of_day=events["time_change"])

    update_story_summary(session["id"], result["narration"])
    session = db_get("SELECT * FROM sessions WHERE id=?", (session["id"],))

    await _send_narration(update, context, session, result, players, is_prologue=True)


# ─── Callback: escolha de ação ────────────────────────────────────────────────
async def callback_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = query.message.chat_id
    user_id = query.from_user.id

    session = get_active_session(chat_id)
    if not session or session["status"] != "active":
        await query.answer("Não há história ativa.", show_alert=True)
        return

    current = get_current_player(session)
    if not current or current["telegram_id"] != user_id:
        await query.answer("Não é a tua vez!", show_alert=True)
        return

    await query.answer()
    action = query.data.replace("action_", "")

    await query.edit_message_reply_markup(reply_markup=None)

    # Se há inimigo ativo, entra no mini-combate
    enemy_data = context.chat_data.get("current_enemy")
    if enemy_data:
        await query.message.reply_text(
            f"▶️ <b>{query.from_user.first_name}</b> escolheu: <i>{action}</i>",
            parse_mode=ParseMode.HTML
        )
        await _start_mini_combat(query.message, context, session, user_id, enemy_data)
        return

    await query.message.reply_text(
        f"▶️ <b>{query.from_user.first_name}</b> escolheu: <i>{action}</i>",
        parse_mode=ParseMode.HTML
    )

    session = advance_turn(session["id"])
    players = get_session_players(session["id"])

    if is_story_over(session):
        await _finish_story(update, context, session, players, query.message)
        return

    result = await generate_turn(chat_id, session, players, action, None)

    if not result:
        await query.message.reply_text("⚠️ Erro ao gerar turno. A IA está ocupada — tenta novamente com /retry.")
        return

    # XP minimo garantido por turno
    if result.get("events") is not None:
        if not result["events"].get("xp_gained"):
            result["events"]["xp_gained"] = random.randint(5, 15)
    else:
        result["events"] = {"xp_gained": random.randint(5, 15)}

    await _process_events(update, context, session, result, players, query.message)
    update_story_summary(session["id"], result["narration"])
    session = db_get("SELECT * FROM sessions WHERE id=?", (session["id"],))
    await _send_narration_msg(query.message, session, result, players)


# ─── MINI-SISTEMA DE COMBATE ──────────────────────────────────────────────────

def _make_bar(current: int, maximum: int, length: int = 10) -> str:
    if maximum <= 0:
        return "░" * length
    filled = max(0, min(length, int((current / maximum) * length)))
    return "█" * filled + "░" * (length - filled)


def _combat_status_text(user_id: int, session: dict, enemy: dict) -> str:
    char = get_character(user_id)
    sp = db_get(
        "SELECT hp_current, mana_current FROM session_players WHERE session_id=? AND telegram_id=?",
        (session["id"], user_id)
    )
    hp_atual = sp["hp_current"] if sp else char["hp_max"]
    mana_atual = sp["mana_current"] if sp else 0
    enemy_hp = enemy.get("hp", 50)
    enemy_hp_max = enemy.get("hp_max", enemy_hp)

    hp_bar = _make_bar(hp_atual, char["hp_max"], 10)
    enemy_bar = _make_bar(enemy_hp, enemy_hp_max, 10)

    tag = "💀 BOSS" if enemy.get("is_boss") else ("⚠️ Mini-Boss" if enemy.get("is_miniboss") else "👹")
    text = (
        f"⚔️ <b>COMBATE</b>\n\n"
        f"<b>{char['name']}</b>\n"
        f"❤️ {hp_atual}/{char['hp_max']} {hp_bar}\n"
        f"💧 {mana_atual}/{char['mana_max']} MANA\n\n"
        f"{tag} <b>{enemy['name']}</b>\n"
        f"❤️ {enemy_hp}/{enemy_hp_max} {enemy_bar}\n"
        f"⚔️ ATK {enemy['atk']} | 🛡️ DEF {enemy.get('def', 5)}"
    )
    if enemy.get("element"):
        text += f" | 🔥 {enemy['element']}"
    if enemy.get("weakness"):
        text += f"\n🎯 Fraqueza: <i>{enemy['weakness']}</i>"
    return text


def _build_combat_keyboard(user_id: int, enemy: dict, session_id: int) -> InlineKeyboardMarkup:
    char = get_character(user_id)
    skills = get_skills(user_id)
    spells = get_spells(user_id)
    companions = get_companions(user_id)

    sp = db_get("SELECT mana_current FROM session_players WHERE session_id=? AND telegram_id=?", (session_id, user_id))
    mana_atual = sp["mana_current"] if sp else 0

    keyboard = []
    keyboard.append([InlineKeyboardButton("⚔️ Atacar", callback_data="combat_attack")])

    active_skills = [s for s in skills if s.get("is_active")][:3]
    for skill in active_skills:
        keyboard.append([InlineKeyboardButton(
            f"🎯 {skill['name'][:30]}",
            callback_data=f"combat_skill_{skill['id']}"
        )])

    active_spells = [s for s in spells if s.get("is_active") and s.get("mana_cost", 10) <= mana_atual][:3]
    for spell in active_spells:
        keyboard.append([InlineKeyboardButton(
            f"✨ {spell['name'][:25]} ({spell.get('mana_cost', 10)}💧)",
            callback_data=f"combat_spell_{spell['id']}"
        )])

    if companions:
        comp = companions[0]
        keyboard.append([InlineKeyboardButton(
            f"🐾 {comp['name'][:25]} (ataque conjunto)",
            callback_data=f"combat_companion_{comp['id']}"
        )])

    keyboard.append([InlineKeyboardButton("🏃 Fugir", callback_data="combat_flee")])

    return InlineKeyboardMarkup(keyboard)


async def _start_mini_combat(message, context, session, user_id: int, enemy: dict):
    if "hp_max" not in enemy:
        enemy["hp_max"] = enemy.get("hp", 50)
        context.chat_data["current_enemy"] = enemy

    text = _combat_status_text(user_id, session, enemy)
    keyboard = _build_combat_keyboard(user_id, enemy, session["id"])
    await message.reply_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)


async def callback_combat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = query.message.chat_id
    user_id = query.from_user.id

    session = get_active_session(chat_id)
    if not session:
        await query.answer("Não há história ativa.", show_alert=True)
        return

    enemy = context.chat_data.get("current_enemy")
    if not enemy:
        await query.answer("O combate já terminou.", show_alert=True)
        await query.edit_message_reply_markup(reply_markup=None)
        return

    players = get_session_players(session["id"])
    player_ids = [p["telegram_id"] for p in players if p.get("is_alive")]
    if user_id not in player_ids:
        await query.answer("Não és jogador desta história!", show_alert=True)
        return

    await query.answer()

    action = query.data
    char = get_character(user_id)
    sp = db_get(
        "SELECT hp_current, mana_current FROM session_players WHERE session_id=? AND telegram_id=?",
        (session["id"], user_id)
    )
    hp_atual = sp["hp_current"] if sp else char["hp_max"]
    mana_atual = sp["mana_current"] if sp else 0

    stats = apply_weather_to_stats(
        {"atk": char["atk"], "def": char["def"], "agi": char["agi"], "mana": char["mana"]},
        session["weather"], session["time_of_day"], char["race"]
    )

    log_lines = []
    player_dmg = 0
    mana_spent = 0

    # ── Fuga ─────────────────────────────────────────────────────────────────
    if action == "combat_flee":
        if enemy.get("is_boss") or enemy.get("is_miniboss"):
            log_lines.append("❌ Não consegues fugir de um boss!")
            enemy_hit = calculate_enemy_damage(enemy, char, session["current_turn"], session["difficulty"])
            new_hp = hp_atual - enemy_hit["damage"]
            update_player_hp(session["id"], user_id, new_hp, char["hp_max"])
            log_lines.append(f"👹 <b>{enemy['name']}</b> contra-ataca — {enemy_hit['text']}")
            context.chat_data["current_enemy"] = enemy
            if new_hp <= 0:
                await query.edit_message_text(
                    "\n".join(log_lines) + f"\n\n☠️ <b>{char['name']} foi derrotado!</b>",
                    parse_mode=ParseMode.HTML
                )
                increment_stat(user_id, "total_deaths")
                context.chat_data.pop("current_enemy", None)
                return
            text = _combat_status_text(user_id, session, enemy)
            keyboard = _build_combat_keyboard(user_id, enemy, session["id"])
            await query.edit_message_text(
                "\n".join(log_lines) + f"\n\n{text}",
                reply_markup=keyboard, parse_mode=ParseMode.HTML
            )
            return
        else:
            context.chat_data.pop("current_enemy", None)
            await query.edit_message_text(
                f"🏃 <b>{char['name']}</b> fugiu do combate!\n\nA história continua...",
                parse_mode=ParseMode.HTML
            )
            session = advance_turn(session["id"])
            players = get_session_players(session["id"])
            if is_story_over(session):
                await _finish_story(update, context, session, players, query.message)
                return
            result = await generate_turn(chat_id, session, players, f"Fugiu de {enemy['name']}", None)
            if result:
                await _process_events(update, context, session, result, players, query.message)
                update_story_summary(session["id"], result["narration"])
                session = db_get("SELECT * FROM sessions WHERE id=?", (session["id"],))
                await _send_narration_msg(query.message, session, result, players)
            return

    # ── Ataque básico ─────────────────────────────────────────────────────────
    if action == "combat_attack":
        dice = roll_dice()
        result = calculate_damage(stats["atk"], enemy.get("def", 5), dice)
        player_dmg = result["damage"]
        log_lines.append(f"⚔️ <b>{char['name']}</b> ataca — {result['text']}")

    # ── Skill ─────────────────────────────────────────────────────────────────
    elif action.startswith("combat_skill_"):
        skill_id = int(action.replace("combat_skill_", ""))
        skill = db_get("SELECT * FROM skills WHERE id=? AND telegram_id=?", (skill_id, user_id))
        if skill:
            import json as _json
            try:
                effect = _json.loads(skill.get("effect", "{}")) if skill.get("effect") else {}
            except Exception:
                effect = {}
            atk_bonus = effect.get("atk_bonus", int(stats["atk"] * 0.5))
            dice = roll_dice()
            result = calculate_damage(stats["atk"] + atk_bonus, enemy.get("def", 5), dice)
            player_dmg = result["damage"]
            log_lines.append(f"🎯 <b>{char['name']}</b> usa <b>{skill['name']}</b> — {result['text']}")
        else:
            dice = roll_dice()
            result = calculate_damage(stats["atk"], enemy.get("def", 5), dice)
            player_dmg = result["damage"]
            log_lines.append(f"⚔️ <b>{char['name']}</b> ataca — {result['text']}")

    # ── Feitiço ───────────────────────────────────────────────────────────────
    elif action.startswith("combat_spell_"):
        spell_id = int(action.replace("combat_spell_", ""))
        spell = db_get("SELECT * FROM spells WHERE id=? AND telegram_id=?", (spell_id, user_id))
        if spell:
            mana_cost = spell.get("mana_cost", 10)
            if mana_atual < mana_cost:
                await query.answer("Mana insuficiente!", show_alert=True)
                return
            mana_spent = mana_cost
            mana_power = max(stats["atk"], char.get("mana_max", 10) // 5)
            dice = roll_dice()
            result = calculate_damage(mana_power + dice, 0, dice)
            player_dmg = result["damage"]
            log_lines.append(f"✨ <b>{char['name']}</b> conjura <b>{spell['name']}</b> — {result['text']} <i>(ignora DEF!)</i>")
        else:
            await query.answer("Feitiço não encontrado.", show_alert=True)
            return

    # ── Companheiro ───────────────────────────────────────────────────────────
    elif action.startswith("combat_companion_"):
        comp_id = int(action.replace("combat_companion_", ""))
        comp = db_get("SELECT * FROM companions WHERE id=? AND telegram_id=?", (comp_id, user_id))
        if comp:
            dice1, dice2 = roll_dice(), roll_dice()
            dmg1 = max(1, stats["atk"] + dice1 - enemy.get("def", 5))
            dmg2 = max(1, comp["atk"] + dice2 - enemy.get("def", 5))
            player_dmg = int((dmg1 + dmg2) * 1.2)
            log_lines.append(f"🐾 <b>{char['name']}</b> e <b>{comp['name']}</b> atacam juntos — {player_dmg} dano!")
        else:
            await query.answer("Companheiro não encontrado.", show_alert=True)
            return

    # ── Aplica dano ao inimigo ────────────────────────────────────────────────
    enemy["hp"] = max(0, enemy.get("hp", 50) - player_dmg)
    add_session_stats(session["id"], user_id, damage=player_dmg)
    increment_stat(user_id, "total_damage", player_dmg)

    if mana_spent > 0:
        db_run("UPDATE session_players SET mana_current=? WHERE session_id=? AND telegram_id=?",
               (max(0, mana_atual - mana_spent), session["id"], user_id))

    # ── Inimigo derrotado ─────────────────────────────────────────────────────
    if enemy["hp"] <= 0:
        context.chat_data.pop("current_enemy", None)
        increment_stat(user_id, "total_kills")
        add_session_stats(session["id"], user_id, kills=1)
        if enemy.get("is_boss"):
            increment_stat(user_id, "boss_kills")

        diff = DIFFICULTIES.get(session["difficulty"], DIFFICULTIES["normal"])
        xp_reward = int(random.randint(20, 50) * diff["xp_mult"])
        gold_reward = int(random.randint(10, 30) * diff["gold_mult"])
        xp_result = add_xp(user_id, xp_reward)
        add_gold(user_id, gold_reward)
        add_session_stats(session["id"], user_id, xp=xp_reward, gold=gold_reward)

        victory_text = "\n".join(log_lines)
        reward_text = (
            f"\n\n🏆 <b>Vitória!</b> <b>{enemy['name']}</b> derrotado!\n"
            f"✨ +{xp_reward} XP | 💰 +{gold_reward} ouro"
        )

        await query.edit_message_text(f"{victory_text}{reward_text}", parse_mode=ParseMode.HTML)

        if xp_result.get("leveled_up"):
            lvl = xp_result["new_level"]
            keyboard_lvl = [[
                InlineKeyboardButton("❤️ +20 HP", callback_data="levelup_hp"),
                InlineKeyboardButton("⚔️ +3 ATK", callback_data="levelup_atk"),
                InlineKeyboardButton("🛡️ +2 DEF", callback_data="levelup_def"),
                InlineKeyboardButton("⚡ +2 AGI", callback_data="levelup_agi"),
                InlineKeyboardButton("💧 +20 MANA", callback_data="levelup_mana"),
            ]]
            await query.message.reply_text(
                f"⭐ <b>LEVEL UP!</b> Chegaste ao nível {lvl}! Escolhe o teu bónus:",
                reply_markup=InlineKeyboardMarkup(keyboard_lvl),
                parse_mode=ParseMode.HTML
            )

        session = advance_turn(session["id"])
        players = get_session_players(session["id"])
        if is_story_over(session):
            await _finish_story(update, context, session, players, query.message)
            return

        await query.message.reply_text("⏳ A continuar a história...")
        result = await generate_turn(chat_id, session, players, f"Derrotou {enemy['name']}", None)
        if result:
            await _process_events(update, context, session, result, players, query.message)
            update_story_summary(session["id"], result["narration"])
            session = db_get("SELECT * FROM sessions WHERE id=?", (session["id"],))
            await _send_narration_msg(query.message, session, result, players)
        return

    # ── Inimigo contra-ataca ──────────────────────────────────────────────────
    enemy_hit = calculate_enemy_damage(enemy, char, session["current_turn"], session["difficulty"])
    new_hp = hp_atual - enemy_hit["damage"]
    update_player_hp(session["id"], user_id, new_hp, char["hp_max"])

    # Enraivecimento
    hp_pct = enemy["hp"] / max(enemy.get("hp_max", enemy["hp"]), 1)
    if hp_pct <= 0.3 and not enemy.get("enraged"):
        enemy["enraged"] = True
        enemy["atk"] = int(enemy["atk"] * 1.5)
        log_lines.append(f"😡 <b>{enemy['name']}</b> ENFURECEU! ATK aumentado!")
    context.chat_data["current_enemy"] = enemy

    log_lines.append(f"👹 <b>{enemy['name']}</b> contra-ataca — {enemy_hit['text']}")

    # ── Jogador morreu ────────────────────────────────────────────────────────
    if new_hp <= 0:
        await query.edit_message_text(
            "\n".join(log_lines) + f"\n\n☠️ <b>{char['name']} foi derrotado!</b>\nAlguém pode usar /revive.",
            parse_mode=ParseMode.HTML
        )
        increment_stat(user_id, "total_deaths")
        context.chat_data.pop("current_enemy", None)
        return

    # ── Continua combate ──────────────────────────────────────────────────────
    text = _combat_status_text(user_id, session, enemy)
    keyboard = _build_combat_keyboard(user_id, enemy, session["id"])
    await query.edit_message_text(
        "\n".join(log_lines) + f"\n\n{text}",
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML
    )


# ─── Processamento de eventos da IA ──────────────────────────────────────────
async def _process_events(update, context, session, result, players, message):
    events = result.get("events", {})
    if not events:
        return

    current = get_current_player(session)
    if not current:
        return
    tid = current["telegram_id"]

    event_effects = get_active_event_effects()
    if events.get("xp_gained", 0) > 0:
        xp = int(events["xp_gained"] * event_effects["xp_mult"])
        xp_result = add_xp(tid, xp)
        if xp_result.get("leveled_up"):
            lvl = xp_result["new_level"]
            keyboard = [[
                InlineKeyboardButton("❤️ +20 HP", callback_data="levelup_hp"),
                InlineKeyboardButton("⚔️ +3 ATK", callback_data="levelup_atk"),
                InlineKeyboardButton("🛡️ +2 DEF", callback_data="levelup_def"),
                InlineKeyboardButton("⚡ +2 AGI", callback_data="levelup_agi"),
                InlineKeyboardButton("💧 +20 MANA", callback_data="levelup_mana"),
            ]]
            await message.reply_text(
                f"⭐ <b>LEVEL UP!</b> {current.get('char_name','?')} chegou ao nível <b>{lvl}</b>!\nEscolhe o teu bónus:",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.HTML
            )
        add_session_stats(session["id"], tid, xp=xp)

    if events.get("gold_gained", 0) > 0:
        gold = int(events["gold_gained"] * event_effects["gold_mult"])
        add_gold(tid, gold)
        add_session_stats(session["id"], tid, gold=gold)

    if events.get("item_found"):
        item = events["item_found"]
        result_id = add_item(tid, item, session["id"])
        if result_id == -1:
            await message.reply_text(f"💎 Encontraste <b>{item['name']}</b> mas já tens o máximo de itens lendários!")
        else:
            await message.reply_text(
                f"🎁 <b>{current.get('char_name','?')}</b> encontrou: "
                f"<b>{item['name']}</b> ({item.get('rarity','comum')})\n<i>{item.get('description','')[:80]}</i>",
                parse_mode=ParseMode.HTML
            )

    if events.get("weapon_found"):
        weapon = events["weapon_found"]
        add_weapon(tid, weapon, session["id"])
        await message.reply_text(
            f"⚔️ <b>{current.get('char_name','?')}</b> encontrou a arma: <b>{weapon['name']}</b> ({weapon.get('rarity','comum')})\n"
            f"<i>{weapon.get('lore','')[:80]}</i>",
            parse_mode=ParseMode.HTML
        )

    if events.get("skill_offered"):
        skill = events["skill_offered"]
        keyboard = [[
            InlineKeyboardButton("✅ Aceitar", callback_data=f"skill_accept_{tid}"),
            InlineKeyboardButton("❌ Recusar", callback_data="skill_reject"),
        ]]
        context.chat_data[f"pending_skill_{tid}"] = skill
        await message.reply_text(
            f"🎯 <b>{current.get('char_name','?')}</b>, a história oferece-te a skill:\n"
            f"<b>{skill['name']}</b>\n<i>{skill.get('description','')}</i>",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML
        )

    if events.get("spell_offered"):
        spell = events["spell_offered"]
        keyboard = [[
            InlineKeyboardButton("✅ Aceitar", callback_data=f"spell_accept_{tid}"),
            InlineKeyboardButton("❌ Recusar", callback_data="spell_reject"),
        ]]
        context.chat_data[f"pending_spell_{tid}"] = spell
        await message.reply_text(
            f"✨ <b>{current.get('char_name','?')}</b>, a história oferece-te o feitiço:\n"
            f"<b>{spell['name']}</b> ({spell.get('mana_cost',10)} MANA)\n<i>{spell.get('description','')}</i>",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML
        )

    if events.get("enemy_spawned"):
        enemy = events["enemy_spawned"]
        enemy["hp_max"] = enemy["hp"]
        context.chat_data["current_enemy"] = enemy
        tag = "💀 BOSS" if enemy.get("is_boss") else ("⚠️ Mini-Boss" if enemy.get("is_miniboss") else "👹 Inimigo")
        await message.reply_text(
            f"{tag}: <b>{enemy['name']}</b>\n"
            f"❤️ {enemy['hp']} HP | ⚔️ {enemy['atk']} ATK | 🛡️ {enemy['def']} DEF\n"
            f"🔥 Elemento: {enemy.get('element','nenhum')} | 🎯 Fraqueza: {enemy.get('weakness','nenhuma')}\n\n"
            f"⚔️ <i>Escolhe uma ação para iniciar o combate!</i>",
            parse_mode=ParseMode.HTML
        )

    if events.get("companion_available"):
        comp = events["companion_available"]
        keyboard = [[
            InlineKeyboardButton("🐾 Domar", callback_data=f"tame_{tid}"),
            InlineKeyboardButton("❌ Ignorar", callback_data="tame_ignore"),
        ]]
        context.chat_data[f"pending_companion_{tid}"] = comp
        skills_check = db_get("SELECT id FROM skills WHERE telegram_id=? AND name LIKE '%Domar%'", (tid,))
        if skills_check:
            await message.reply_text(
                f"🦁 Apareceu: <b>{comp['name']}</b> ({comp.get('animal_type','animal')})\n"
                f"<i>{comp.get('description','')}</i>\nUsas a skill Domar?",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.HTML
            )

    if events.get("secret_event"):
        sec = events["secret_event"]
        target_id = sec.get("target_player_id")
        if not target_id and players:
            target_id = random.choice(players)["telegram_id"]
        if target_id:
            try:
                await context.bot.send_message(
                    target_id,
                    f"🔮 <b>Evento Secreto</b>\n\n{sec.get('message','')}\n\n"
                    f"<b>Objetivo secreto:</b> <i>{sec.get('secret_objective', generate_secret_objective())}</i>",
                    parse_mode=ParseMode.HTML
                )
            except Exception as e:
                logger.warning("Não foi possível enviar mensagem privada a %s: %s", target_id, e)

    if events.get("weather_change"):
        update_session_weather(session["id"], weather=events["weather_change"])
    if events.get("time_change"):
        update_session_weather(session["id"], time_of_day=events["time_change"])


async def _send_narration(update, context, session, result, players, is_prologue=False):
    msg = update.message
    await _send_narration_msg(msg, session, result, players, is_prologue)


async def _send_narration_msg(message, session, result, players, is_prologue=False):
    narration = result.get("narration", "")
    options = result.get("options", [])
    image_prompt = result.get("image_prompt", "")

    current = get_current_player(session)
    turn_text = f"📖 <b>Turno {session['current_turn']}/20</b>" if not is_prologue else "📖 <b>Prólogo</b>"
    weather_line = format_weather_status(session.get("weather", "sol"), session.get("time_of_day", "dia"))

    full_text = f"{turn_text}\n{weather_line}\n\n{narration}"

    if current and not is_prologue:
        full_text += f"\n\n🎮 É a vez de <b>{current.get('char_name','?')}</b>"

    keyboard = []
    if options and current:
        for opt in options[:4]:
            keyboard.append([InlineKeyboardButton(opt[:64], callback_data=f"action_{opt[:50]}")])

    reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None

    # Imagem separada antes do texto
    if image_prompt:
        try:
            img_bytes = await generate_image(image_prompt, seed=session.get("current_turn", 1))
            if img_bytes:
                await message.reply_photo(photo=img_bytes)
        except Exception as e:
            logger.warning("Erro ao gerar imagem do turno: %s", e)

    try:
        await message.reply_text(full_text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error("Erro ao enviar narração: %s", e)
        await message.reply_text(narration, reply_markup=reply_markup, parse_mode=ParseMode.HTML)


async def _finish_story(update, context, session, players, message):
    end_session(session["id"])

    session_players = get_session_players(session["id"])
    for sp in session_players:
        increment_stat(sp["telegram_id"], "total_stories")

    add_guild_xp(message.chat_id, 50 * len(session_players))

    board = get_session_leaderboard(session["id"])
    board_lines = ["🏆 <b>Resultado Final da História</b>\n"]
    medals = ["🥇", "🥈", "🥉"] + ["🔹"] * 10
    for i, p in enumerate(board):
        board_lines.append(
            f"{medals[i]} <b>{p['char_name']}</b>\n"
            f"   Kills: {p['session_kills']} | Dano: {p['session_damage']} | XP: {p['session_xp']} | Ouro: {p['session_gold']}"
        )

    await message.reply_text("\n".join(board_lines), parse_mode=ParseMode.HTML)
    await message.reply_text("⏳ A gerar o epílogo da história...")

    log_data = []
    try:
        from db.database import json_get
        s = db_get("SELECT full_log FROM sessions WHERE id=?", (session["id"],))
        log_data = json_get(s["full_log"]) if s else []
    except Exception:
        pass

    epilogue = await generate_epilogue(message.chat_id, session, session_players, log_data)
    if epilogue:
        await message.reply_text(f"📜 <b>Epílogo</b>\n\n{epilogue}", parse_mode=ParseMode.HTML)

    await message.reply_text("🎮 A história terminou! Usa /new_game para começar uma nova aventura.")


# ─── Callbacks de level up ────────────────────────────────────────────────────
async def callback_levelup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    choice = query.data.replace("levelup_", "")
    label = level_up_choose(query.from_user.id, choice)
    await query.edit_message_text(f"✅ Bónus aplicado: <b>{label}</b>", parse_mode=ParseMode.HTML)


# ─── Callbacks de skill/spell ─────────────────────────────────────────────────
async def callback_skill_accept(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    tid = int(query.data.replace("skill_accept_", ""))
    skill = context.chat_data.pop(f"pending_skill_{tid}", None)
    if skill:
        session = get_active_session(query.message.chat_id)
        result = add_skill(tid, skill, session["id"] if session else None)
        status = "✅ ativa" if result["active"] else "⏸ inativa (máximo de slots atingido)"
        await query.edit_message_text(f"🎯 Skill <b>{skill['name']}</b> aprendida! ({status})", parse_mode=ParseMode.HTML)


async def callback_skill_reject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("❌ Skill recusada.")


async def callback_spell_accept(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    tid = int(query.data.replace("spell_accept_", ""))
    spell = context.chat_data.pop(f"pending_spell_{tid}", None)
    if spell:
        session = get_active_session(query.message.chat_id)
        result = add_spell(tid, spell, session["id"] if session else None)
        status = "✅ ativo" if result["active"] else "⏸ inativo (grimório cheio)"
        await query.edit_message_text(f"✨ Feitiço <b>{spell['name']}</b> aprendido! ({status})", parse_mode=ParseMode.HTML)


async def callback_spell_reject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("❌ Feitiço recusado.")


async def callback_tame(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    tid = int(query.data.replace("tame_", ""))
    comp = context.chat_data.pop(f"pending_companion_{tid}", None)
    if comp:
        session = get_active_session(query.message.chat_id)
        result = add_companion(tid, comp, session["id"] if session else None)
        if result["success"]:
            await query.edit_message_text(f"🐾 <b>{comp['name']}</b> domado com sucesso!", parse_mode=ParseMode.HTML)
        else:
            await query.edit_message_text(f"❌ {result['reason']}")


async def callback_tame_ignore(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("💨 O animal desapareceu na floresta.")


# ─── /revive ──────────────────────────────────────────────────────────────────
async def cmd_revive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not context.args:
        await update.message.reply_text("Usa: /revive @username")
        return

    char = get_character(user.id)
    if not char or char["gold"] < REVIVE_GOLD_COST:
        await update.message.reply_text(f"❌ Precisas de {REVIVE_GOLD_COST} ouro para reviver alguém.")
        return

    username = context.args[0].lstrip("@")
    target = db_get("SELECT * FROM players WHERE username=?", (username,))
    if not target:
        await update.message.reply_text("❌ Jogador não encontrado.")
        return

    session = get_active_session(update.effective_chat.id)
    if not session:
        await update.message.reply_text("❌ Não há história ativa.")
        return

    db_run("UPDATE characters SET gold=gold-? WHERE telegram_id=?", (REVIVE_GOLD_COST, user.id))
    revive_player(session["id"], target["telegram_id"], hp_restore=30)
    target_char = get_character(target["telegram_id"])

    await update.message.reply_text(
        f"💚 <b>{char['name']}</b> reviveu <b>{target_char['name'] if target_char else username}</b>!\n"
        f"Custou {REVIVE_GOLD_COST} ouro. HP restaurado: 30.",
        parse_mode=ParseMode.HTML
    )


# ─── /alliance ────────────────────────────────────────────────────────────────
async def cmd_alliance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not context.args:
        await update.message.reply_text("Usa: /alliance @username")
        return

    username = context.args[0].lstrip("@")
    target = db_get("SELECT * FROM players WHERE username=?", (username,))
    if not target:
        await update.message.reply_text("❌ Jogador não encontrado.")
        return

    session = get_active_session(update.effective_chat.id)
    if not session:
        return

    set_alliance(session["id"], user.id, target["telegram_id"])
    increment_stat(user.id, "total_alliances")

    char1 = get_character(user.id)
    char2 = get_character(target["telegram_id"])
    await update.message.reply_text(
        f"🤝 Aliança formada entre <b>{char1['name'] if char1 else user.first_name}</b> e <b>{char2['name'] if char2 else username}</b>!\n"
        "Podem agora combinar ataques em combate.",
        parse_mode=ParseMode.HTML
    )


# ─── /betray ──────────────────────────────────────────────────────────────────
async def cmd_betray(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not context.args:
        await update.message.reply_text("Usa: /betray @username")
        return

    username = context.args[0].lstrip("@")
    target = db_get("SELECT * FROM players WHERE username=?", (username,))
    if not target:
        await update.message.reply_text("❌ Jogador não encontrado.")
        return

    char = get_character(user.id)
    target_char = get_character(target["telegram_id"])
    if not char or not target_char:
        return

    session = get_active_session(update.effective_chat.id)
    dmg = {"damage": 0}
    if session:
        db_run(
            "UPDATE session_players SET ally_id=NULL WHERE session_id=? AND telegram_id=?",
            (session["id"], user.id)
        )
        dice = roll_dice()
        dmg = calculate_damage(char["atk"] // 2, target_char["def"], dice)
        sp = db_get("SELECT hp_current FROM session_players WHERE session_id=? AND telegram_id=?",
                    (session["id"], target["telegram_id"]))
        if sp:
            new_hp = sp["hp_current"] - dmg["damage"]
            update_player_hp(session["id"], target["telegram_id"], new_hp, target_char["hp_max"])

    increment_stat(user.id, "total_betrayals")

    await update.message.reply_text(
        f"🗡️ <b>{char['name']}</b> traiu <b>{target_char['name']}</b>!\n"
        f"Dano causado: {dmg['damage']}",
        parse_mode=ParseMode.HTML
    )


# ─── /history ─────────────────────────────────────────────────────────────────
async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sessions = get_past_sessions(update.effective_chat.id, 5)
    if not sessions:
        await update.message.reply_text("📖 Nenhuma história completada neste grupo ainda.")
        return

    lines = ["📖 <b>Histórias Passadas</b>\n"]
    for s in sessions:
        diff = DIFFICULTIES.get(s["difficulty"], {})
        lines.append(
            f"🗓 {s['ended_at'][:10]} — {diff.get('label', s['difficulty'])}\n"
            f"   Turnos: {s['current_turn']}/20"
        )
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


# ─── /weather ─────────────────────────────────────────────────────────────────
async def cmd_weather(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = get_active_session(update.effective_chat.id)
    if not session:
        await update.message.reply_text("❌ Não há história ativa.")
        return
    text = format_weather_status(session.get("weather", "sol"), session.get("time_of_day", "dia"))
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)
