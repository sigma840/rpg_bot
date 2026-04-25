import random
import logging
from config import DIFFICULTIES

logger = logging.getLogger(__name__)


def roll_dice(sides: int = 10) -> int:
    return random.randint(1, sides)


def calculate_damage(atk: int, defense: int, dice_roll: int = None, ignore_def: bool = False) -> dict:
    if dice_roll is None:
        dice_roll = roll_dice()

    is_critical = dice_roll >= 9
    is_miss = dice_roll == 1

    if is_miss:
        return {"damage": 0, "dice": dice_roll, "critical": False, "miss": True, "text": "💨 Errou!"}

    effective_def = 0 if ignore_def else defense
    base_damage = max(1, atk + dice_roll - effective_def)

    if is_critical:
        base_damage *= 2
        return {"damage": base_damage, "dice": dice_roll, "critical": True, "miss": False, "text": f"💥 CRÍTICO! {base_damage} dano"}

    return {"damage": base_damage, "dice": dice_roll, "critical": False, "miss": False, "text": f"⚔️ {base_damage} dano"}


def calculate_enemy_damage(enemy: dict, player: dict, turn: int, difficulty: str = "normal") -> dict:
    """Inimigo ataca jogador. Escala com turnos e dificuldade."""
    diff = DIFFICULTIES.get(difficulty, DIFFICULTIES["normal"])
    scale = 1 + (turn * 0.05)  # +5% por turno
    base_atk = int(enemy.get("atk", 10) * diff["enemy_mult"] * scale)

    dice = roll_dice()
    return calculate_damage(base_atk, player.get("def", 5), dice)


def apply_class_special(char_class: str, combat_state: dict) -> dict:
    """Aplica habilidade especial da classe se disponível."""
    specials = {
        "guerreiro": _fury,
        "assassino": _first_strike,
        "berserker": _berserker_rage,
        "arqueiro":  _precise_shot,
    }
    fn = specials.get(char_class)
    if fn:
        return fn(combat_state)
    return combat_state


def _fury(state: dict) -> dict:
    if not state.get("fury_used"):
        state["atk_modifier"] = int(state.get("atk", 10) * 0.5)
        state["fury_turns"] = 2
        state["fury_used"] = True
        state["special_text"] = "😤 FÚRIA ATIVADA! +50% ATK por 2 turnos!"
    return state


def _first_strike(state: dict) -> dict:
    if not state.get("first_strike_done"):
        state["force_critical"] = True
        state["first_strike_done"] = True
        state["special_text"] = "🗡️ Golpe Furtivo — ataque crítico garantido!"
    return state


def _berserker_rage(state: dict) -> dict:
    hp_pct = state.get("hp_current", 100) / max(state.get("hp_max", 100), 1)
    bonus = int((1 - hp_pct) * state.get("atk", 10))
    state["atk_modifier"] = bonus
    if bonus > 0:
        state["special_text"] = f"🪓 Berserker: +{bonus} ATK pela dor!"
    return state


def _precise_shot(state: dict) -> dict:
    state["ignore_def"] = True
    state["special_text"] = "🏹 Tiro Certeiro — ignora DEF!"
    return state


def alliance_attack(attacker1: dict, attacker2: dict, enemy_def: int) -> dict:
    """Ataque combinado de aliança — dano somado + bónus 20%."""
    roll1 = roll_dice()
    roll2 = roll_dice()

    dmg1 = max(1, attacker1["atk"] + roll1 - enemy_def)
    dmg2 = max(1, attacker2["atk"] + roll2 - enemy_def)
    total = int((dmg1 + dmg2) * 1.2)

    return {
        "damage": total,
        "text": f"🤝 Ataque em Aliança! {attacker1['name']} + {attacker2['name']} = {total} dano!",
        "dice": [roll1, roll2],
        "critical": roll1 >= 9 or roll2 >= 9,
        "miss": False,
    }


def halfling_reroll(original_roll: int) -> int:
    """Sorte do Halfling — relança 1 dado por turno."""
    new_roll = roll_dice()
    return max(original_roll, new_roll)


def get_enemy_enrage_text(enemy: dict, hp_pct: float) -> str | None:
    if hp_pct <= 0.3 and not enemy.get("enraged"):
        return f"😡 {enemy.get('name','Inimigo')} ENFURECEU! Dano dobrado!"
    return None


def format_combat_log(result: dict, attacker_name: str, target_name: str) -> str:
    if result["miss"]:
        return f"💨 {attacker_name} errou o ataque em {target_name}!"
    if result["critical"]:
        return f"💥 {attacker_name} acertou um CRÍTICO em {target_name}! ({result['damage']} dano)"
    return f"⚔️ {attacker_name} causou {result['damage']} dano em {target_name}."
