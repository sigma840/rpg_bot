import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from config import OWNER_ID
from game.session import get_active_session, end_session
from game.economy import create_auction, place_bid, get_active_auctions, format_auctions_text
from game.guild import get_guild, create_guild, format_guild_text, add_to_chest
from game.events import trigger_global_event, format_events_text
from game.player import get_character
from game.inventory import get_inventory, get_weapons
from db.database import db_get, db_run

logger = logging.getLogger(__name__)


# ─── Admin: /end_game ─────────────────────────────────────────────────────────
async def cmd_end_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ Só o owner pode terminar histórias.")
        return

    from db.database import db_get as _db_get, db_run as _db_run
    session = _db_get("SELECT * FROM sessions WHERE chat_id=? AND status != 'ended' ORDER BY id DESC LIMIT 1", (update.effective_chat.id,))
    if not session:
        await update.message.reply_text("❌ Não há história ativa.")
        return

    _db_run("UPDATE sessions SET status='ended' WHERE id=?", (session["id"],))
    await update.message.reply_text("🛑 História terminada.")


# ─── Admin: /announce ─────────────────────────────────────────────────────────
async def cmd_announce(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    if not context.args:
        await update.message.reply_text("Usa: /announce <mensagem>")
        return
    text = " ".join(context.args)
    await update.message.reply_text(f"📢 <b>Anúncio do Owner</b>\n\n{text}", parse_mode=ParseMode.HTML)


# ─── Admin: /set_event ────────────────────────────────────────────────────────
async def cmd_set_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    await update.message.reply_text("⏳ A gerar evento global via IA...")
    event = await trigger_global_event(update.effective_chat.id)
    if event:
        await update.message.reply_text(
            f"⚡ <b>{event['title']}</b>\n\n{event['description']}",
            parse_mode=ParseMode.HTML
        )
    else:
        await update.message.reply_text("❌ Erro ao gerar evento.")


# ─── Admin: /reset_player ─────────────────────────────────────────────────────
async def cmd_reset_player(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    if not context.args:
        await update.message.reply_text("Usa: /reset_player @username")
        return
    username = context.args[0].lstrip("@")
    player = db_get("SELECT * FROM players WHERE username=?", (username,))
    if not player:
        await update.message.reply_text("❌ Jogador não encontrado.")
        return
    db_run("DELETE FROM characters WHERE telegram_id=?", (player["telegram_id"],))
    await update.message.reply_text(f"✅ Personagem de @{username} removido.")


# ─── /events ──────────────────────────────────────────────────────────────────
async def cmd_events(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = format_events_text()
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


# ─── /gold ────────────────────────────────────────────────────────────────────
async def cmd_gold(update: Update, context: ContextTypes.DEFAULT_TYPE):
    char = get_character(update.effective_user.id)
    if not char:
        await update.message.reply_text("❌ Não tens personagem.")
        return
    await update.message.reply_text(f"💰 Tens <b>{char['gold']} ouro</b>.", parse_mode=ParseMode.HTML)


# ─── /auction ─────────────────────────────────────────────────────────────────
async def cmd_auction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat

    if len(context.args) < 2:
        await update.message.reply_text(
            "Usa: /auction <id_item> <preço_base>\n\nPrimeiro usa /inventory ou /skills para ver os IDs dos teus itens."
        )
        return

    try:
        item_id = int(context.args[0])
        price = int(context.args[1])
    except ValueError:
        await update.message.reply_text("❌ ID e preço devem ser números.")
        return

    if price < 1:
        await update.message.reply_text("❌ Preço mínimo é 1 ouro.")
        return

    # Tenta inventory primeiro, depois weapons
    item = db_get("SELECT id FROM inventory WHERE id=? AND telegram_id=?", (item_id, user.id))
    table = "inventory" if item else "weapons"
    if not item:
        item = db_get("SELECT id FROM weapons WHERE id=? AND telegram_id=?", (item_id, user.id))

    if not item:
        await update.message.reply_text("❌ Item não encontrado no teu inventário.")
        return

    result = create_auction(chat.id, user.id, item_id, table, price)
    if result["success"]:
        await update.message.reply_text(
            f"🔨 Leilão criado para <b>{result['item_name']}</b>!\n"
            f"Preço base: 💰 {price} ouro\nDura 10 minutos. ID: <code>{result['auction_id']}</code>",
            parse_mode=ParseMode.HTML
        )
    else:
        await update.message.reply_text(result["reason"])


# ─── /bid ─────────────────────────────────────────────────────────────────────
async def cmd_bid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if len(context.args) < 2:
        await update.message.reply_text("Usa: /bid <id_leilão> <valor>")
        return
    try:
        auction_id = int(context.args[0])
        amount = int(context.args[1])
    except ValueError:
        await update.message.reply_text("❌ Valores inválidos.")
        return

    result = place_bid(auction_id, user.id, amount)
    if result["success"]:
        await update.message.reply_text(f"✅ Lance de 💰 {amount} ouro registado!")
    else:
        await update.message.reply_text(result["reason"])


# ─── /auctions ────────────────────────────────────────────────────────────────
async def cmd_auctions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = format_auctions_text(update.effective_chat.id)
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


# ─── /forge ───────────────────────────────────────────────────────────────────
async def cmd_forge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from game.forge import format_forge_menu
    user = update.effective_user
    text, weapons, materials = format_forge_menu(user.id)

    if not weapons or not materials:
        await update.message.reply_text(text, parse_mode=ParseMode.HTML)
        return

    # Botões para escolher arma
    keyboard = [[InlineKeyboardButton(f"⚔️ {w['name']}", callback_data=f"forge_w_{w['id']}")] for w in weapons]
    await update.message.reply_text(
        text + "\n\n<b>Escolhe a arma a forjar:</b>",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML
    )


async def callback_forge_weapon(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    weapon_id = int(query.data.replace("forge_w_", ""))
    context.user_data["forge_weapon_id"] = weapon_id

    from game.inventory import get_forgeable_materials, rarity_emoji
    materials = get_forgeable_materials(query.from_user.id)
    if not materials:
        await query.edit_message_text("❌ Não tens materiais de forja.")
        return

    keyboard = [[InlineKeyboardButton(
        f"{rarity_emoji(m['rarity'])} {m['name']}", callback_data=f"forge_m_{m['id']}"
    )] for m in materials]
    await query.edit_message_text(
        "🧪 <b>Escolhe o material:</b>",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML
    )


async def callback_forge_material(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    material_id = int(query.data.replace("forge_m_", ""))
    weapon_id = context.user_data.get("forge_weapon_id")

    if not weapon_id:
        await query.edit_message_text("❌ Erro na forja. Tenta /forge novamente.")
        return

    await query.edit_message_text("⏳ O ferreiro analisa a combinação...")

    from game.forge import attempt_forge
    result = await attempt_forge(query.message.chat_id, query.from_user.id, weapon_id, material_id)

    if result["success"]:
        await query.message.reply_text(
            f"🔥 <b>Forja bem-sucedida!</b>\n\n"
            f"⚔️ <b>{result['result_name']}</b>\n"
            f"✨ Novo efeito: {result['new_effect']}\n"
            f"📈 ATK+{result['atk_bonus']}",
            parse_mode=ParseMode.HTML
        )
    else:
        await query.message.reply_text(result["reason"], parse_mode=ParseMode.HTML)


# ─── /guild ───────────────────────────────────────────────────────────────────
async def cmd_guild(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = format_guild_text(update.effective_chat.id)
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_guild_create(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usa: /guild_create <nome> <emoji>")
        return
    name = context.args[0]
    emblem = context.args[1] if len(context.args) > 1 else "🛡️"
    result = create_guild(update.effective_chat.id, name, emblem)
    if result["success"]:
        await update.message.reply_text(
            f"✅ Guilda <b>{emblem} {name}</b> criada!",
            parse_mode=ParseMode.HTML
        )
    else:
        await update.message.reply_text(result["reason"])


async def cmd_guild_chest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    guild = get_guild(update.effective_chat.id)
    if not guild:
        await update.message.reply_text("❌ Este grupo não tem guilda.")
        return
    from db.database import json_get
    chest = json_get(guild.get("chest", "[]"))
    if not chest:
        await update.message.reply_text("🎒 O baú da guilda está vazio.")
        return
    lines = ["🎒 <b>Baú da Guilda</b>\n"]
    for item in chest:
        lines.append(f"• <b>{item['name']}</b> — <i>{item.get('desc','')[:60]}</i> (doado por {item['donated_by']})")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)
