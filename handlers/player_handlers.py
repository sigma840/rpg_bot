import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import ContextTypes, ConversationHandler
from telegram.constants import ParseMode

from config import RACES, CLASSES, ACHIEVEMENTS, OWNER_ID
from db.database import db_get, db_all
from game.player import (get_or_create_player, get_character, create_character,
                          get_character_sheet, get_leaderboard_global, set_active_title,
                          check_achievements)
from game.inventory import format_inventory_text, get_weapons
from game.progression import format_skills_text, format_companions_text, get_skills, get_spells
from game.images import generate_avatar_image
from game.weather import format_weather_status
from game.events import format_events_text

logger = logging.getLogger(__name__)

# Estados da conversa de criação de personagem
CHOOSE_NAME, CHOOSE_RACE, CHOOSE_CLASS, CHOOSE_AVATAR = range(4)


# ─── /start ───────────────────────────────────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    get_or_create_player(user.id, user.username or "", user.full_name or "")
    char = get_character(user.id)

    keyboard = [
        [InlineKeyboardButton("⚔️ Criar Personagem", callback_data="create_char")],
        [InlineKeyboardButton("📊 O meu Perfil", callback_data="my_profile"),
         InlineKeyboardButton("🏆 Leaderboard", callback_data="leaderboard")],
        [InlineKeyboardButton("📖 Ajuda", callback_data="help")],
    ]

    text = (
        f"🏰 <b>Bem-vindo ao Fantasy RPG!</b>\n\n"
        f"Olá, <b>{user.first_name}</b>!\n\n"
    )
    if char:
        text += f"O teu personagem <b>{char['name']}</b> aguarda a próxima aventura.\n"
        text += "Usa /new_game num grupo para iniciar uma história!"
    else:
        text += "Ainda não tens personagem. Cria um para começares a jogar!"

    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)


# ─── /create_character ────────────────────────────────────────────────────────
async def cmd_create_character(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    get_or_create_player(user.id, user.username or "", user.full_name or "")
    char = get_character(user.id)

    if char:
        await update.message.reply_text(
            f"⚠️ Já tens o personagem <b>{char['name']}</b>.\n"
            "Se continuares, manterás XP, nível, ouro e itens mas mudarás raça, classe e avatar.\n\n"
            "Escreve o <b>novo nome</b> do teu personagem para continuar, ou /cancel para desistir.",
            parse_mode=ParseMode.HTML
        )
    else:
        await update.message.reply_text(
            "⚔️ <b>Criação de Personagem</b>\n\nEscreve o <b>nome</b> do teu personagem:",
            parse_mode=ParseMode.HTML
        )
    return CHOOSE_NAME


async def received_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    if len(name) < 2 or len(name) > 30:
        await update.message.reply_text("❌ Nome deve ter entre 2 e 30 caracteres. Tenta novamente:")
        return CHOOSE_NAME

    context.user_data["char_name"] = name

    # Menu de raças
    keyboard = []
    row = []
    for race, info in RACES.items():
        row.append(InlineKeyboardButton(f"{info['emoji']} {race.capitalize()}", callback_data=f"race_{race}"))
        if len(row) == 3:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    await update.message.reply_text(
        f"✨ Personagem: <b>{name}</b>\n\nEscolhe a tua <b>raça</b>:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML
    )
    return CHOOSE_RACE


async def received_race(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    race = query.data.replace("race_", "")
    context.user_data["char_race"] = race
    race_info = RACES[race]

    # Menu de classes
    keyboard = []
    row = []
    for cls, info in CLASSES.items():
        row.append(InlineKeyboardButton(f"{info['emoji']} {cls.capitalize()}", callback_data=f"class_{cls}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    await query.edit_message_text(
        f"🧬 Raça: <b>{race_info['emoji']} {race.capitalize()}</b>\n"
        f"<i>{race_info['desc']}</i>\n\nEscolhe a tua <b>classe</b>:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML
    )
    return CHOOSE_CLASS


async def received_class(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    char_class = query.data.replace("class_", "")
    context.user_data["char_class"] = char_class
    class_info = CLASSES[char_class]

    await query.edit_message_text(
        f"⚔️ Classe: <b>{class_info['emoji']} {char_class.capitalize()}</b>\n"
        f"<i>{class_info['desc']}</i>\n\n"
        "Descreve o <b>aspeto visual</b> do teu personagem para gerar o avatar:\n"
        "<i>(ex: 'elfo alto de cabelo prateado com armadura negra e olhos vermelhos')</i>",
        parse_mode=ParseMode.HTML
    )
    return CHOOSE_AVATAR


async def received_avatar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    avatar_desc = update.message.text.strip()
    user = update.effective_user

    name = context.user_data["char_name"]
    race = context.user_data["char_race"]
    char_class = context.user_data["char_class"]

    await update.message.reply_text("⏳ A criar o teu personagem e gerar o avatar...")

    # Cria personagem
    char = create_character(user.id, name, race, char_class, avatar_desc)

    # Gera avatar
    try:
        img_bytes = await generate_avatar_image(avatar_desc, race, char_class, user.id)
        if img_bytes:
            msg = await update.message.reply_photo(
                photo=img_bytes,
                caption=_char_created_text(char),
                parse_mode=ParseMode.HTML
            )
        else:
            await update.message.reply_text(_char_created_text(char), parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error("Erro ao gerar avatar: %s", e)
        await update.message.reply_text(_char_created_text(char), parse_mode=ParseMode.HTML)

    return ConversationHandler.END


def _char_created_text(char: dict) -> str:
    race_info = RACES.get(char["race"], {})
    class_info = CLASSES.get(char["class"], {})
    return (
        f"✅ <b>Personagem criado!</b>\n\n"
        f"{class_info.get('emoji','⚔️')} <b>{char['name']}</b>\n"
        f"{race_info.get('emoji','👤')} {char['race'].capitalize()} · {char['class'].capitalize()}\n\n"
        f"❤️ HP: {char['hp_max']}  💧 MANA: {char['mana_max']}\n"
        f"⚔️ ATK: {char['atk']}  🛡️ DEF: {char['def']}  ⚡ AGI: {char['agi']}\n\n"
        f"Entra num grupo e usa /new_game para jogar!"
    )


async def cancel_creation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Criação de personagem cancelada.")
    return ConversationHandler.END


# ─── /status ──────────────────────────────────────────────────────────────────
async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    sheet = get_character_sheet(user.id)
    char = get_character(user.id)

    if char and char.get("avatar_url"):
        await update.message.reply_photo(photo=char["avatar_url"], caption=sheet, parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text(sheet, parse_mode=ParseMode.HTML)


# ─── /inventory ───────────────────────────────────────────────────────────────
async def cmd_inventory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = format_inventory_text(update.effective_user.id)
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


# ─── /skills ──────────────────────────────────────────────────────────────────
async def cmd_skills(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = format_skills_text(update.effective_user.id)
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


# ─── /companions ──────────────────────────────────────────────────────────────
async def cmd_companions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = format_companions_text(update.effective_user.id)
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


# ─── /profile ─────────────────────────────────────────────────────────────────
async def cmd_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args:
        # Perfil de outro jogador por username
        username = context.args[0].lstrip("@")
        player = db_get("SELECT * FROM players WHERE username=?", (username,))
        if not player:
            await update.message.reply_text("❌ Jogador não encontrado.")
            return
        tid = player["telegram_id"]
    else:
        tid = update.effective_user.id

    char = get_character(tid)
    if not char:
        await update.message.reply_text("❌ Este jogador não tem personagem.")
        return

    from game.player import RACES, CLASSES
    race_info = RACES.get(char["race"], {})
    class_info = CLASSES.get(char["class"], {})
    achievements = db_get("SELECT achievements, unlocked_titles FROM characters WHERE telegram_id=?", (tid,))
    ach_list = len(db_all("SELECT id FROM characters WHERE telegram_id=?", (tid,)))

    from db.database import json_get
    unlocked_titles = json_get(char.get("unlocked_titles", "[]"))
    achievements_done = json_get(char.get("achievements", "[]"))

    xp_next = char["level"] * 100
    title = f' "{char["active_title"]}"' if char.get("active_title") else ""

    text = (
        f"{class_info.get('emoji','⚔️')} <b>{char['name']}{title}</b>\n"
        f"{race_info.get('emoji','👤')} {char['race'].capitalize()} · {char['class'].capitalize()} · Nível {char['level']}\n\n"
        f"❤️ {char['hp_max']} HP  💧 {char['mana_max']} MANA\n"
        f"⚔️ {char['atk']} ATK  🛡️ {char['def']} DEF  ⚡ {char['agi']} AGI\n"
        f"💰 {char['gold']} ouro\n\n"
        f"📊 <b>Histórico</b>\n"
        f"⭐ XP Total: {char['xp'] + char['level']*100}\n"
        f"💀 Inimigos: {char['total_kills']}  ☠️ Mortes: {char['total_deaths']}\n"
        f"📖 Histórias: {char['total_stories']}  🏆 Bosses: {char['boss_kills']}\n"
        f"🔥 Forjas: {char['total_forges']}  🐾 Domados: {char['total_tamed']}\n\n"
        f"🎖️ <b>Conquistas: {len(achievements_done)}</b>\n"
        f"🏅 <b>Títulos: {len(unlocked_titles)}</b>"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


# ─── /titles ──────────────────────────────────────────────────────────────────
async def cmd_titles(update: Update, context: ContextTypes.DEFAULT_TYPE):
    char = get_character(update.effective_user.id)
    if not char:
        await update.message.reply_text("❌ Não tens personagem.")
        return

    from db.database import json_get
    titles = json_get(char.get("unlocked_titles", "[]"))
    if not titles:
        await update.message.reply_text("🏅 Ainda não desbloqueaste nenhum título. Completa conquistas!")
        return

    keyboard = [[InlineKeyboardButton(t, callback_data=f"settitle_{t}")] for t in titles]
    keyboard.append([InlineKeyboardButton("❌ Sem título", callback_data="settitle_")])
    await update.message.reply_text(
        f"🏅 <b>Os teus títulos ({len(titles)})</b>\nAtual: <b>{char.get('active_title') or 'nenhum'}</b>\n\nEscolhe:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML
    )


async def callback_set_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    title = query.data.replace("settitle_", "")
    success = set_active_title(query.from_user.id, title)
    if success:
        label = f'"{title}"' if title else "nenhum"
        await query.edit_message_text(f"✅ Título definido: <b>{label}</b>", parse_mode=ParseMode.HTML)
    else:
        await query.edit_message_text("❌ Título inválido.")


# ─── /achievements ────────────────────────────────────────────────────────────
async def cmd_achievements(update: Update, context: ContextTypes.DEFAULT_TYPE):
    char = get_character(update.effective_user.id)
    if not char:
        await update.message.reply_text("❌ Não tens personagem.")
        return

    from db.database import json_get
    done = json_get(char.get("achievements", "[]"))
    lines = [f"🎖️ <b>Conquistas ({len(done)}/{len(ACHIEVEMENTS)})</b>\n"]

    for key, ach in ACHIEVEMENTS.items():
        if key in done:
            lines.append(f"✅ {ach['icon']} <b>{ach['name']}</b> → Título: <i>{ach['title']}</i>")
        else:
            lines.append(f"🔒 {ach['icon']} {ach['name']} — <i>{ach['desc']}</i>")

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


# ─── /leaderboard ─────────────────────────────────────────────────────────────
async def cmd_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    board = get_leaderboard_global(10)
    if not board:
        await update.message.reply_text("🏆 Leaderboard vazio. Joguem uma história primeiro!")
        return

    lines = ["🏆 <b>Leaderboard Global</b>\n"]
    medals = ["🥇", "🥈", "🥉"] + ["🔹"] * 7
    for i, p in enumerate(board):
        title = f' "{p["active_title"]}"' if p.get("active_title") else ""
        lines.append(
            f"{medals[i]} <b>{p['name']}{title}</b> — Nv.{p['level']}\n"
            f"   Score: {p['score']} | Kills: {p['total_kills']} | Histórias: {p['total_stories']}"
        )
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


# ─── /help ────────────────────────────────────────────────────────────────────
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📖 <b>Comandos do Fantasy RPG</b>\n\n"
        "<b>Personagem</b>\n"
        "/create_character — Cria ou muda de personagem\n"
        "/status — Ver HP, stats e informação\n"
        "/profile [@user] — Perfil detalhado\n"
        "/inventory — Ver itens e armas\n"
        "/skills — Ver skills e feitiços\n"
        "/companions — Ver animais domados\n"
        "/titles — Gerir títulos\n"
        "/achievements — Ver conquistas\n\n"
        "<b>Jogo (em grupos)</b>\n"
        "/new_game — Iniciar nova história\n"
        "/join — Entrar na história\n"
        "/begin — Começar a narração\n"
        "/forge — Forjar armas\n"
        "/revive @user — Reviver jogador (50 ouro)\n"
        "/alliance @user — Formar aliança\n"
        "/betray @user — Trair aliado\n\n"
        "<b>Economia</b>\n"
        "/auction [id_item] [preço] — Leiloar item\n"
        "/bid [id_leilão] [valor] — Fazer lance\n"
        "/auctions — Ver leilões ativos\n"
        "/gold — Ver o teu ouro\n\n"
        "<b>Guilda</b>\n"
        "/guild — Info da guilda\n"
        "/guild_create [nome] [emoji] — Criar guilda\n"
        "/guild_chest — Ver baú da guilda\n\n"
        "<b>Rankings & Info</b>\n"
        "/leaderboard — Top global\n"
        "/history — Histórias passadas\n"
        "/events — Eventos globais ativos\n"
        "/weather — Clima e hora do dia atuais"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)
