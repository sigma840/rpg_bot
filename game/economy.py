from datetime import datetime, timedelta
from db.database import db_get, db_all, db_run
from config import AUCTION_DURATION_SECONDS
from game.player import add_gold


def create_auction(chat_id: int, seller_id: int, item_id: int, item_table: str, starting_price: int) -> dict:
    # Verifica se o item existe
    table = "inventory" if item_table == "inventory" else "weapons"
    item = db_get(f"SELECT * FROM {table} WHERE id=? AND telegram_id=?", (item_id, seller_id))
    if not item:
        return {"success": False, "reason": "❌ Item não encontrado."}

    # Verifica se já há leilão ativo para este item
    existing = db_get(
        "SELECT id FROM auctions WHERE seller_id=? AND item_id=? AND item_table=? AND status='active'",
        (seller_id, item_id, item_table)
    )
    if existing:
        return {"success": False, "reason": "❌ Já há um leilão ativo para este item."}

    ends_at = (datetime.now() + timedelta(seconds=AUCTION_DURATION_SECONDS)).isoformat()
    aid = db_run(
        "INSERT INTO auctions (chat_id, seller_id, item_id, item_table, starting_price, current_bid, ends_at) VALUES (?,?,?,?,?,?,?)",
        (chat_id, seller_id, item_id, item_table, starting_price, starting_price, ends_at)
    )
    return {"success": True, "auction_id": aid, "item_name": item["name"], "ends_at": ends_at}


def place_bid(auction_id: int, bidder_id: int, amount: int) -> dict:
    auction = db_get("SELECT * FROM auctions WHERE id=? AND status='active'", (auction_id,))
    if not auction:
        return {"success": False, "reason": "❌ Leilão não encontrado ou já terminou."}

    if datetime.fromisoformat(auction["ends_at"]) < datetime.now():
        db_run("UPDATE auctions SET status='ended' WHERE id=?", (auction_id,))
        return {"success": False, "reason": "❌ Este leilão já terminou."}

    if bidder_id == auction["seller_id"]:
        return {"success": False, "reason": "❌ Não podes licitar no teu próprio leilão."}

    if amount <= auction["current_bid"]:
        return {"success": False, "reason": f"❌ A tua licitação tem de ser superior ao lance atual ({auction['current_bid']} ouro)."}

    # Verifica se o bidder tem ouro suficiente
    char = db_get("SELECT gold FROM characters WHERE telegram_id=?", (bidder_id,))
    if not char or char["gold"] < amount:
        return {"success": False, "reason": "❌ Ouro insuficiente."}

    # Devolve ouro ao licitador anterior
    if auction["highest_bidder"] and auction["highest_bidder"] != bidder_id:
        add_gold(auction["highest_bidder"], auction["current_bid"])

    # Debita ouro do novo licitador
    db_run("UPDATE characters SET gold=gold-? WHERE telegram_id=?", (amount, bidder_id))
    db_run(
        "UPDATE auctions SET current_bid=?, highest_bidder=? WHERE id=?",
        (amount, bidder_id, auction_id)
    )
    return {"success": True, "amount": amount}


def finalize_auction(auction_id: int) -> dict:
    auction = db_get("SELECT * FROM auctions WHERE id=?", (auction_id,))
    if not auction or auction["status"] != "active":
        return {"success": False}

    db_run("UPDATE auctions SET status='ended' WHERE id=?", (auction_id,))

    if not auction["highest_bidder"]:
        return {"success": True, "sold": False, "reason": "Sem licitadores — item devolvido ao vendedor."}

    # Transfere item
    table = auction["item_table"]
    actual_table = "inventory" if table == "inventory" else "weapons"
    db_run(
        f"UPDATE {actual_table} SET telegram_id=? WHERE id=?",
        (auction["highest_bidder"], auction["item_id"])
    )

    # Paga ao vendedor
    add_gold(auction["seller_id"], auction["current_bid"])

    from game.player import increment_stat
    increment_stat(auction["highest_bidder"], "auctions_won")

    item = db_get(f"SELECT name FROM {actual_table} WHERE id=?", (auction["item_id"],))

    return {
        "success": True,
        "sold": True,
        "buyer_id": auction["highest_bidder"],
        "seller_id": auction["seller_id"],
        "price": auction["current_bid"],
        "item_name": item["name"] if item else "item",
    }


def get_active_auctions(chat_id: int) -> list[dict]:
    auctions = db_all(
        "SELECT a.*, p.full_name as seller_name FROM auctions a "
        "JOIN players p ON p.telegram_id = a.seller_id "
        "WHERE a.chat_id=? AND a.status='active' ORDER BY a.ends_at ASC",
        (chat_id,)
    )
    result = []
    for a in auctions:
        table = "inventory" if a["item_table"] == "inventory" else "weapons"
        item = db_get(f"SELECT name, rarity FROM {table} WHERE id=?", (a["item_id"],))
        if item:
            a["item_name"] = item["name"]
            a["item_rarity"] = item.get("rarity", "comum")
        result.append(a)
    return result


def format_auctions_text(chat_id: int) -> str:
    auctions = get_active_auctions(chat_id)
    if not auctions:
        return "🔨 Nenhum leilão ativo neste momento."

    lines = ["🔨 <b>Leilões Ativos</b>\n"]
    for a in auctions:
        ends = datetime.fromisoformat(a["ends_at"])
        remaining = ends - datetime.now()
        mins = int(remaining.total_seconds() / 60)
        lines.append(
            f"📦 <b>{a.get('item_name','?')}</b> ({a.get('item_rarity','?')})\n"
            f"   Vendedor: {a['seller_name']}\n"
            f"   Lance atual: 💰 {a['current_bid']} ouro\n"
            f"   ⏱ Termina em: {mins} minutos\n"
            f"   ID do leilão: <code>{a['id']}</code>\n"
        )
    return "\n".join(lines)
