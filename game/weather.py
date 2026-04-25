import random

WEATHER_EFFECTS = {
    "sol":        {"emoji": "☀️",  "atk": 0,   "def": 0,  "agi": 0,  "mana": 0,   "desc": "Sem efeitos especiais."},
    "chuva":      {"emoji": "🌧️",  "atk": 0,   "def": 0,  "agi": -2, "mana": 5,   "desc": "-2 AGI para todos. +5 MANA (magia da chuva)."},
    "tempestade": {"emoji": "⛈️",  "atk": -2,  "def": -1, "agi": -3, "mana": 10,  "desc": "-2 ATK, -1 DEF, -3 AGI. +10 MANA. Ataques de raio amplificados."},
    "neve":       {"emoji": "❄️",  "atk": 0,   "def": 2,  "agi": -3, "mana": -5,  "desc": "-3 AGI, +2 DEF, -5 MANA. Fogo amplificado."},
    "neblina":    {"emoji": "🌫️",  "atk": -2,  "def": 0,  "agi": 2,  "mana": 0,   "desc": "-2 ATK (visibilidade). +2 AGI (furtividade). Assassinos beneficiam."},
    "calor":      {"emoji": "🔥",  "atk": 2,   "def": -2, "agi": 0,  "mana": -10, "desc": "+2 ATK, -2 DEF, -10 MANA. Ataques de gelo amplificados."},
    "eclipse":    {"emoji": "🌑",  "atk": 0,   "def": 0,  "agi": 0,  "mana": 20,  "desc": "+20 MANA. Magias de trevas e luz amplificadas. Mortos-vivos mais fortes."},
}

TIME_EFFECTS = {
    "dia":        {"emoji": "🌤️",  "desc": "Condições normais."},
    "noite":      {"emoji": "🌙",  "desc": "Espectros invisíveis. Inimigos noturnos emergem. Elfos revelam eventos ocultos."},
    "amanhecer":  {"emoji": "🌅",  "desc": "+5 HP a todos os jogadores vivos. Moral elevado."},
    "crepúsculo": {"emoji": "🌆",  "desc": "Inimigos ficam mais agressivos. Босses ganham +10% ATK."},
}


def get_weather_effect(weather: str) -> dict:
    return WEATHER_EFFECTS.get(weather, WEATHER_EFFECTS["sol"])


def get_time_effect(time_of_day: str) -> dict:
    return TIME_EFFECTS.get(time_of_day, TIME_EFFECTS["dia"])


def apply_weather_to_stats(base_stats: dict, weather: str, time_of_day: str, race: str = "") -> dict:
    stats = base_stats.copy()
    w = get_weather_effect(weather)
    stats["atk"] = max(1, stats.get("atk", 10) + w["atk"])
    stats["def"] = max(0, stats.get("def", 5) + w["def"])
    stats["agi"] = max(0, stats.get("agi", 5) + w["agi"])
    stats["mana"] = max(0, stats.get("mana", 0) + w["mana"])

    # Bónus de raça com clima
    if race == "espectro" and time_of_day == "noite":
        stats["agi"] += 3  # invisibilidade
    if race == "elfo" and time_of_day == "noite":
        stats["agi"] += 1
    if race == "elemental" and weather == "tempestade":
        stats["mana"] += 10

    return stats


def format_weather_status(weather: str, time_of_day: str) -> str:
    w = WEATHER_EFFECTS.get(weather, WEATHER_EFFECTS["sol"])
    t = TIME_EFFECTS.get(time_of_day, TIME_EFFECTS["dia"])
    return (
        f"{w['emoji']} <b>{weather.capitalize()}</b> · {t['emoji']} <b>{time_of_day.capitalize()}</b>\n"
        f"<i>{w['desc']}</i>\n"
        f"<i>{t['desc']}</i>"
    )


def get_next_time(current: str) -> str:
    cycle = ["amanhecer", "dia", "crepúsculo", "noite"]
    idx = cycle.index(current) if current in cycle else 1
    return cycle[(idx + 1) % len(cycle)]
