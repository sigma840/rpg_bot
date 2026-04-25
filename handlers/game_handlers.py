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
from game.progression import add_skill, add_spell, add_companion, level_up_choose
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

    # Menu de dificuldade
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

    # Verifica se já morreu nesta sessão
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

    # Junta automaticamente quem usou /begin se ainda não estiver na sessão
    char = get_character(user.id)
    if char:
        add_player_to_session(session["id"], user.id, char["hp_max"], char["mana_max"])

    players = get_session_players(session["id"])

    await update.message.reply_text("⏳ A gerar o prólogo da história...")

    result = await generate_prologue(chat.id, session, players)
    if not result:
        await update.message.reply_text("❌ Erro ao gerar prólogo. Tenta /begin novamente.")
        end_session(session["id"])
        return

    # Atualiza clima/hora
    events = result.get("events", {})
    if events.get("weather_change"):
        update_session_weather(session["id"], weather=events["weather_change"])
    if events.get("time_change"):
        update_session_weather(session["id"], time_of_day=events["time_change"])

    update_story_summary(session["id"], result["narration"])
    session = db_get("SELECT * FROM sessions WHERE id=?", (session["id"],))

    # Envia imagem se disponível
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

    players = get_session_players(session["id"])

    # Verifica se é combate
    combat_result = None
    enemy_data = context.chat_data.get("current_enemy")
    if enemy_data:
        char = get_character(user_id)
        stats = apply_weather_to_stats(
            {"atk": char["atk"], "def": char["def"], "agi": char["agi"], "mana": char["mana"]},
            session["weather"], session["time_of_day"], char["race"]
        )
        dice = roll_dice()
        result = calculate_damage(stats["atk"], enemy_data.get("def", 5), dice)
        combat_result = {"player_damage": result, "action": action}

        # Dano do inimigo ao jogador
        enemy_hit = calculate_enemy_damage(enemy_data, char, session["current_turn"], session["difficulty"])
        combat_result["enemy_damage"] = enemy_hit

        # Aplica dano
        sp = db_get("SELECT * FROM session_players WHERE session_id=? AND telegram_id=?",
                    (session["id"], user_id))
        new_hp = (sp["hp_current"] if sp else char["hp_max"]) - enemy_hit["damage"]
        update_player_hp(session["id"], user_id, new_hp, char["hp_max"])
        add_session_stats(session["id"], user_id, damage=result["damage"])
        increment_stat(user_id, "total_damage", result["damage"])

        if result["damage"] >= enemy_data.get("hp", 50):
            combat_result["enemy_defeated"] = True
            increment_stat(user_id, "total_kills")
            add_session_stats(session["id"], user_id, kills=1)
            if enemy_data.get("is_boss"):
                increment_stat(user_id, "boss_kills")
            context.chat_data.pop("current_enemy", None)

    await query.edit_message_reply_markup(reply_markup=None)
    await query.message.reply_text(f"▶️ <b>{query.from_user.first_name}</b> escolheu: <i>{action}</i>", parse_mode=ParseMode.HTML)

    # Avança turno
    session = advance_turn(session["id"])

    if is_story_over(session):
        await _finish_story(update, context, session, players, query.message)
        return

    # Gera próximo turno
    players = get_session_players(session["id"])
    result = await generate_turn(chat_id, session, players, action, combat_result)

    if not result:
        await query.message.reply_text("⚠️ Erro ao gerar turno. A IA está ocupada — tenta novamente com /retry.")
        return

    # Processa eventos
    await _process_events(update, context, session, result, players, query.message)

    # Atualiza resumo
    update_story_summary(session["id"], result["narration"])
    session = db_get("SELECT * FROM sessions WHERE id=?", (session["id"],))

    # Envia narração
    await _send_narration_msg(query.message, session, result, players)


async def _process_events(update, context, session, result, players, message):
    events = result.get("events", {})
    if not events:
        return

    current = get_current_player(session)
    if not current:
        return
    tid = current["telegram_id"]

    # XP e ouro
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

    # Item encontrado
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

    # Arma encontrada
    if events.get("weapon_found"):
        weapon = events["weapon_found"]
        add_weapon(tid, weapon, session["id"])
        await message.reply_text(
            f"⚔️ <b>{current.get('char_name','?')}</b> encontrou a arma: <b>{weapon['name']}</b> ({weapon.get('rarity','comum')})\n"
            f"<i>{weapon.get('lore','')[:80]}</i>",
            parse_mode=ParseMode.HTML
        )

    # Skill oferecida
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

    # Feitiço oferecido
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

    # Inimigo surgiu
    if events.get("enemy_spawned"):
        enemy = events["enemy_spawned"]
        context.chat_data["current_enemy"] = enemy
        tag = "💀 BOSS" if enemy.get("is_boss") else ("⚠️ Mini-Boss" if enemy.get("is_miniboss") else "👹 Inimigo")
        await message.reply_text(
            f"{tag}: <b>{enemy['name']}</b>\n"
            f"❤️ {enemy['hp']} HP | ⚔️ {enemy['atk']} ATK | 🛡️ {enemy['def']} DEF\n"
            f"🔥 Elemento: {enemy.get('element','nenhum')} | 🎯 Fraqueza: {enemy.get('weakness','nenhuma')}",
            parse_mode=ParseMode.HTML
        )

    # Companheiro disponível
    if events.get("companion_available"):
        comp = events["companion_available"]
        keyboard = [[
            InlineKeyboardButton("🐾 Domar", callback_data=f"tame_{tid}"),
            InlineKeyboardButton("❌ Ignorar", callback_data="tame_ignore"),
        ]]
        context.chat_data[f"pending_companion_{tid}"] = comp
        skills = db_get("SELECT id FROM skills WHERE telegram_id=? AND name LIKE '%Domar%'", (tid,))
        if skills:
            await message.reply_text(
                f"🦁 Apareceu: <b>{comp['name']}</b> ({comp.get('animal_type','animal')})\n"
                f"<i>{comp.get('description','')}</i>\nUsas a skill Domar?",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.HTML
            )

    # Evento secreto (mensagem privada)
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

    # Clima e hora
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

    weather_line = format_weather_status(session.get("weather","sol"), session.get("time_of_day","dia"))

    full_text = f"{turn_text}\n{weather_line}\n\n{narration}"

    if current and not is_prologue:
        full_text += f"\n\n🎮 É a vez de <b>{current.get('char_name','?')}</b>"

    # Botões inline para as opções
    keyboard = []
    if options and current:
        for i, opt in enumerate(options[:4]):
            keyboard.append([InlineKeyboardButton(opt[:64], callback_data=f"action_{opt[:50]}")])

    # Tenta gerar imagem
    img_bytes = None
    if image_prompt:
        try:
            img_bytes = await generate_image(image_prompt, seed=session.get("current_turn", 1))
        except Exception as e:
            logger.warning("Erro ao gerar imagem do turno: %s", e)

    reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None

    try:
        if img_bytes:
            await message.reply_photo(
                photo=img_bytes,
                caption=full_text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML
            )
        else:
            await message.reply_text(full_text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error("Erro ao enviar narração: %s", e)
        await message.reply_text(narration, reply_markup=reply_markup, parse_mode=ParseMode.HTML)


async def _finish_story(update, context, session, players, message):
    end_session(session["id"])

    # Atualiza stats globais
    session_players = get_session_players(session["id"])
    for sp in session_players:
        increment_stat(sp["telegram_id"], "total_stories")

    add_guild_xp(message.chat_id, 50 * len(session_players))

    # Leaderboard da história
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
    from game.player import increment_stat
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

    # Remove aliança e causa dano
    session = get_active_session(update.effective_chat.id)
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
        f"Dano causado: {dmg['damage'] if session else 0}",
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
    text = format_weather_status(session.get("weather","sol"), session.get("time_of_day","dia"))
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)
