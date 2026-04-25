import logging
from db.database import db_get, db_run
from game.inventory import get_weapons, get_forgeable_materials, apply_forge_result
from game.ai_narrator import validate_forge
from game.player import increment_stat

logger = logging.getLogger(__name__)


async def attempt_forge(chat_id: int, telegram_id: int, weapon_id: int, material_id: int) -> dict:
    """
    Tenta fundir uma arma com um material.
    Retorna dict com resultado.
    """
    weapon = db_get("SELECT * FROM weapons WHERE id=? AND telegram_id=?", (weapon_id, telegram_id))
    material = db_get("SELECT * FROM inventory WHERE id=? AND telegram_id=? AND item_type='material'", (material_id, telegram_id))

    if not weapon:
        return {"success": False, "reason": "❌ Arma não encontrada no teu inventário."}
    if not material:
        return {"success": False, "reason": "❌ Material não encontrado ou não é um material de forja."}

    # Valida com IA
    result = await validate_forge(chat_id, weapon["name"], material["name"], material.get("description", ""))

    if not result:
        return {"success": False, "reason": "⚙️ Sistema de forja indisponível. Tenta novamente."}

    if not result.get("valid"):
        reason = result.get("reason", "Combinação inválida.")
        return {"success": False, "reason": f"🔨 O ferreiro recusa: *{reason}*"}

    # Aplica resultado
    apply_forge_result(weapon_id, telegram_id, material_id, result)
    increment_stat(telegram_id, "total_forges")

    # Regista histórico
    db_run(
        "INSERT INTO forge_history (telegram_id, weapon_id, material_id, result_name, success) VALUES (?,?,?,?,1)",
        (telegram_id, weapon_id, material_id, result.get("result_name", weapon["name"]))
    )

    return {
        "success": True,
        "result_name": result.get("result_name", weapon["name"]),
        "new_effect": result.get("new_effect", ""),
        "atk_bonus": result.get("atk_bonus", 0),
        "element": result.get("element", ""),
        "reason": result.get("reason", ""),
    }


def format_forge_menu(telegram_id: int) -> tuple[str, list, list]:
    """
    Retorna (texto, lista de armas, lista de materiais) para o menu de forja.
    """
    weapons = get_weapons(telegram_id)
    materials = get_forgeable_materials(telegram_id)

    if not weapons:
        return "❌ Não tens armas para forjar.", [], []
    if not materials:
        return "❌ Não tens materiais de forja. Encontra materiais durante as histórias.", weapons, []

    text_lines = [
        "🔥 <b>Sistema de Forja</b>\n",
        "Combina uma arma com um material para a aprimorar.",
        "A IA valida se a combinação faz sentido.\n",
        "⚔️ <b>As tuas armas:</b>"
    ]
    for i, w in enumerate(weapons, 1):
        forge_info = f" (Forja nível {w['forge_level']})" if w["forge_level"] > 0 else ""
        text_lines.append(f"  {i}. {w['name']}{forge_info} | ATK+{w['atk_bonus']}")

    text_lines.append("\n🧪 <b>Os teus materiais:</b>")
    for i, m in enumerate(materials, 1):
        text_lines.append(f"  {i}. {m['name']} — {m['description'][:50]}")

    text_lines.append("\nUsa os botões abaixo para escolher.")
    return "\n".join(text_lines), weapons, materials
