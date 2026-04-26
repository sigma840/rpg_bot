import logging
import asyncio
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, filters, JobQueue
)

from config import BOT_TOKEN, OWNER_ID
from db.database import init_db

from handlers.player_handlers import (
    cmd_start, cmd_create_character, cmd_status, cmd_inventory,
    cmd_skills, cmd_companions, cmd_profile, cmd_titles,
    cmd_achievements, cmd_leaderboard, cmd_help,
    received_name, received_race, received_class, received_avatar,
    cancel_creation, callback_set_title,
    CHOOSE_NAME, CHOOSE_RACE, CHOOSE_CLASS, CHOOSE_AVATAR
)
from handlers.game_handlers import (
    cmd_new_game, cmd_join, cmd_begin, cmd_revive, cmd_alliance,
    cmd_betray, cmd_history, cmd_weather,
    callback_difficulty, callback_action, callback_combat,
    callback_levelup, callback_skill_accept, callback_skill_reject,
    callback_spell_accept, callback_spell_reject,
    callback_tame, callback_tame_ignore,
)
from handlers.admin_handlers import (
    cmd_end_game, cmd_announce, cmd_set_event, cmd_reset_player,
    cmd_events, cmd_gold, cmd_auction, cmd_bid, cmd_auctions,
    cmd_forge, callback_forge_weapon, callback_forge_material,
    cmd_guild, cmd_guild_create, cmd_guild_chest,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def finalize_auctions_job(context):
    """Job periódico para finalizar leilões expirados."""
    from db.database import db_all
    from game.economy import finalize_auction
    from datetime import datetime

    now = datetime.now().isoformat()
    expired = db_all(
        "SELECT id, chat_id FROM auctions WHERE status='active' AND ends_at <= ?",
        (now,)
    )
    for auction in expired:
        result = finalize_auction(auction["id"])
        if result.get("sold"):
            try:
                await context.bot.send_message(
                    auction["chat_id"],
                    f"🔨 Leilão terminado! <b>{result['item_name']}</b> vendido por 💰 {result['price']} ouro!",
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.error("Erro ao notificar fim de leilão: %s", e)


async def post_init(application: Application):
    """Executa após o bot iniciar."""
    logger.info("Bot iniciado. Owner ID: %s", OWNER_ID)
    # Notifica o owner
    try:
        await application.bot.send_message(
            OWNER_ID,
            "✅ <b>Bot Fantasy RPG online!</b>\n\nAdiciona-me a um grupo e usa /new_game para começar.",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.warning("Não foi possível notificar o owner: %s", e)


def main():
    init_db()

    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    # ─── ConversationHandler para criação de personagem ───────────────────────
    char_creation = ConversationHandler(
        entry_points=[
            CommandHandler("create_character", cmd_create_character),
            CallbackQueryHandler(cmd_create_character, pattern="^create_char$"),
        ],
        states={
            CHOOSE_NAME:   [MessageHandler(filters.TEXT & ~filters.COMMAND, received_name)],
            CHOOSE_RACE:   [CallbackQueryHandler(received_race, pattern="^race_")],
            CHOOSE_CLASS:  [CallbackQueryHandler(received_class, pattern="^class_")],
            CHOOSE_AVATAR: [MessageHandler(filters.TEXT & ~filters.COMMAND, received_avatar)],
        },
        fallbacks=[CommandHandler("cancel", cancel_creation)],
        per_user=True,
        per_chat=False,
    )

    # ─── Handlers de Personagem ───────────────────────────────────────────────
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(char_creation)
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("inventory", cmd_inventory))
    app.add_handler(CommandHandler("skills", cmd_skills))
    app.add_handler(CommandHandler("companions", cmd_companions))
    app.add_handler(CommandHandler("profile", cmd_profile))
    app.add_handler(CommandHandler("titles", cmd_titles))
    app.add_handler(CommandHandler("achievements", cmd_achievements))
    app.add_handler(CommandHandler("leaderboard", cmd_leaderboard))
    app.add_handler(CommandHandler("help", cmd_help))

    # ─── Handlers de Jogo ─────────────────────────────────────────────────────
    app.add_handler(CommandHandler("new_game", cmd_new_game))
    app.add_handler(CommandHandler("join", cmd_join))
    app.add_handler(CommandHandler("begin", cmd_begin))
    app.add_handler(CommandHandler("revive", cmd_revive))
    app.add_handler(CommandHandler("alliance", cmd_alliance))
    app.add_handler(CommandHandler("betray", cmd_betray))
    app.add_handler(CommandHandler("history", cmd_history))
    app.add_handler(CommandHandler("weather", cmd_weather))

    # ─── Handlers de Admin ────────────────────────────────────────────────────
    app.add_handler(CommandHandler("end_game", cmd_end_game))
    app.add_handler(CommandHandler("announce", cmd_announce))
    app.add_handler(CommandHandler("set_event", cmd_set_event))
    app.add_handler(CommandHandler("reset_player", cmd_reset_player))

    # ─── Handlers de Economia ─────────────────────────────────────────────────
    app.add_handler(CommandHandler("events", cmd_events))
    app.add_handler(CommandHandler("gold", cmd_gold))
    app.add_handler(CommandHandler("auction", cmd_auction))
    app.add_handler(CommandHandler("bid", cmd_bid))
    app.add_handler(CommandHandler("auctions", cmd_auctions))

    # ─── Handlers de Forja ────────────────────────────────────────────────────
    app.add_handler(CommandHandler("forge", cmd_forge))

    # ─── Handlers de Guilda ───────────────────────────────────────────────────
    app.add_handler(CommandHandler("guild", cmd_guild))
    app.add_handler(CommandHandler("guild_create", cmd_guild_create))
    app.add_handler(CommandHandler("guild_chest", cmd_guild_chest))

    # ─── Callbacks Inline ─────────────────────────────────────────────────────
    app.add_handler(CallbackQueryHandler(callback_difficulty,    pattern="^diff_"))
    app.add_handler(CallbackQueryHandler(callback_action,        pattern="^action_"))
    app.add_handler(CallbackQueryHandler(callback_combat,        pattern="^combat_"))
    app.add_handler(CallbackQueryHandler(callback_levelup,       pattern="^levelup_"))
    app.add_handler(CallbackQueryHandler(callback_skill_accept,  pattern="^skill_accept_"))
    app.add_handler(CallbackQueryHandler(callback_skill_reject,  pattern="^skill_reject$"))
    app.add_handler(CallbackQueryHandler(callback_spell_accept,  pattern="^spell_accept_"))
    app.add_handler(CallbackQueryHandler(callback_spell_reject,  pattern="^spell_reject$"))
    app.add_handler(CallbackQueryHandler(callback_tame,          pattern="^tame_\\d+$"))
    app.add_handler(CallbackQueryHandler(callback_tame_ignore,   pattern="^tame_ignore$"))
    app.add_handler(CallbackQueryHandler(callback_set_title,     pattern="^settitle_"))
    app.add_handler(CallbackQueryHandler(callback_forge_weapon,  pattern="^forge_w_"))
    app.add_handler(CallbackQueryHandler(callback_forge_material,pattern="^forge_m_"))
    app.add_handler(CallbackQueryHandler(cmd_start,              pattern="^my_profile$"))
    app.add_handler(CallbackQueryHandler(
        lambda u, c: cmd_leaderboard(u, c),                      pattern="^leaderboard$"))
    app.add_handler(CallbackQueryHandler(
        lambda u, c: cmd_help(u, c),                             pattern="^help$"))

    # ─── Job periódico: finalizar leilões ─────────────────────────────────────
    app.job_queue.run_repeating(finalize_auctions_job, interval=60, first=10)

    logger.info("Fantasy RPG Bot a arrancar...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
