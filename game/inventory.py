from db.database import db_get, db_all, db_run, json_get, json_set
from config import MAX_LEGENDARY_ITEMS
import json


EQUIPMENT_SLOTS = ["main_hand", "off_hand", "armor", "amulet", "ring1", "ring2"]
SLOT_NAMES = {
    "main_hand": "🗡️ Mão Principal",
    "off_hand": "🛡️ Mão Secundária",
    "armor": "🧥 Armadura",
    "amulet": "📿 Amuleto",
    "ring1": "💍 Anel 1",
    "ring2": "💍 Anel 2",
}


def add_item(telegram_id: int, item: dict, session_id: int = None) -> int:
    # Verifica limite de lendários
    if item.get("rarity") == "lendário":
        count = db_get(
            "SELECT COUNT(*) as cnt FROM inventory WHERE telegram_id=? AND rarity='lendário'",
            (telegram_id,)
        )
        if count and count["cnt"] >= MAX_LEGENDARY_ITEMS:
            return -1  # Limite atingido

    effect = json.dumps(item.get("effect", {}), ensure_ascii=False) if isinstance(item.get("effect"), dict) else item.get("effect", "{}")
    return db_run(
        "INSERT INTO inventory (telegram_id, name, item_type, rarity, description, effect, obtained_in) VALUES (?,?,?,?,?,?,?)",
        (telegram_id, item["name"], item.get("type", "consumível"), item.get("rarity", "comum"),
         item.get("description", ""), effect, session_id)
    )


def add_weapon(telegram_id: int, weapon: dict, session_id: int = None) -> int:
    return db_run(
        "INSERT INTO weapons (telegram_id, name, rarity, lore, atk_bonus, element, special_effect, obtained_in) VALUES (?,?,?,?,?,?,?,?)",
        (telegram_id, weapon["name"], weapon.get("rarity", "comum"), weapon.get("lore", ""),
         weapon.get("atk_bonus", 0), weapon.get("element", ""), weapon.get("special_effect", ""), session_id)
    )


def get_inventory(telegram_id: int) -> list[dict]:
    return db_all("SELECT * FROM inventory WHERE telegram_id=? ORDER BY rarity DESC, created_at DESC", (telegram_id,))


def get_weapons(telegram_id: int) -> list[dict]:
    return db_all("SELECT * FROM weapons WHERE telegram_id=? ORDER BY rarity DESC, forge_level DESC", (telegram_id,))


def get_equipped(telegram_id: int) -> dict:
    equipped = {}
    weapons = db_all("SELECT * FROM weapons WHERE telegram_id=? AND equipped=1", (telegram_id,))
    items = db_all("SELECT * FROM inventory WHERE telegram_id=? AND equipped=1", (telegram_id,))
    for w in weapons:
        equipped[w["slot"]] = w
    for i in items:
        equipped[i["slot"]] = i
    return equipped


def equip_weapon(telegram_id: int, weapon_id: int, slot: str = "main_hand") -> bool:
    if slot not in EQUIPMENT_SLOTS:
        return False
    # Desequipa o slot atual
    db_run("UPDATE weapons SET equipped=0, slot='' WHERE telegram_id=? AND slot=?", (telegram_id, slot))
    db_run("UPDATE inventory SET equipped=0, slot='' WHERE telegram_id=? AND slot=?", (telegram_id, slot))
    # Equipa o novo
    db_run("UPDATE weapons SET equipped=1, slot=? WHERE id=? AND telegram_id=?", (slot, weapon_id, telegram_id))
    return True


def use_item(telegram_id: int, item_id: int) -> dict | None:
    item = db_get("SELECT * FROM inventory WHERE id=? AND telegram_id=?", (item_id, telegram_id))
    if not item:
        return None
    if item["item_type"] == "consumível":
        if item["quantity"] > 1:
            db_run("UPDATE inventory SET quantity=quantity-1 WHERE id=?", (item_id,))
        else:
            db_run("DELETE FROM inventory WHERE id=?", (item_id,))
    effect = json_get(item.get("effect", "{}"), {})
    return {"item": item, "effect": effect}


def remove_item(item_id: int, telegram_id: int):
    db_run("DELETE FROM inventory WHERE id=? AND telegram_id=?", (item_id, telegram_id))


def format_inventory_text(telegram_id: int) -> str:
    items = get_inventory(telegram_id)
    weapons = get_weapons(telegram_id)

    if not items and not weapons:
        return "🎒 Inventário vazio."

    lines = ["🎒 <b>Inventário</b>\n"]

    if weapons:
        lines.append("⚔️ <b>Armas</b>")
        for w in weapons:
            equip = " [✅ EQUIPADA]" if w["equipped"] else ""
            forge = f" +{w['forge_level']}" if w["forge_level"] > 0 else ""
            lines.append(f"  • {rarity_emoji(w['rarity'])} <b>{w['name']}</b>{forge}{equip}")
            if w["lore"]:
                lines.append(f"    <i>{w['lore'][:80]}</i>")
            lines.append(f"    ATK+{w['atk_bonus']} | {w['element'] or 'sem elemento'} | {w['special_effect'] or ''}")

    if items:
        lines.append("\n🎁 <b>Itens</b>")
        by_type: dict[str, list] = {}
        for item in items:
            by_type.setdefault(item["item_type"], []).append(item)
        for itype, its in by_type.items():
            lines.append(f"  <b>{itype.capitalize()}</b>")
            for it in its:
                qty = f" x{it['quantity']}" if it["quantity"] > 1 else ""
                equip = " [✅]" if it["equipped"] else ""
                lines.append(f"    • {rarity_emoji(it['rarity'])} {it['name']}{qty}{equip}")
                if it["description"]:
                    lines.append(f"      <i>{it['description'][:60]}</i>")

    return "\n".join(lines)


def rarity_emoji(rarity: str) -> str:
    return {
        "comum": "⚪",
        "incomum": "🟢",
        "raro": "🔵",
        "épico": "🟣",
        "lendário": "🌟",
    }.get(rarity, "⚪")


def get_forgeable_materials(telegram_id: int) -> list[dict]:
    return db_all(
        "SELECT * FROM inventory WHERE telegram_id=? AND item_type='material'",
        (telegram_id,)
    )


def apply_forge_result(weapon_id: int, telegram_id: int, material_id: int, result: dict):
    db_run(
        "UPDATE weapons SET name=?, special_effect=?, atk_bonus=atk_bonus+?, element=?, forge_level=forge_level+1 WHERE id=? AND telegram_id=?",
        (result["result_name"], result.get("new_effect", ""), result.get("atk_bonus", 0), result.get("element", ""), weapon_id, telegram_id)
    )
    db_run("DELETE FROM inventory WHERE id=? AND telegram_id=?", (material_id, telegram_id))
