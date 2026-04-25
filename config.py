import os

# ─── Tokens & Keys ────────────────────────────────────────────────────────────
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
OWNER_ID = int(os.getenv("OWNER_ID", "8781489520"))

# ─── Jogo ─────────────────────────────────────────────────────────────────────
MAX_TURNS = 20
MIN_PLAYERS = 1
MAX_PLAYERS = 8
MAX_SKILLS = 6
MAX_SPELLS = 12
MAX_COMPANIONS = 2
MAX_LEGENDARY_ITEMS = 1

# ─── Economia ─────────────────────────────────────────────────────────────────
AUCTION_DURATION_SECONDS = 600  # 10 minutos
REVIVE_GOLD_COST = 50

# ─── Imagens ──────────────────────────────────────────────────────────────────
POLLINATIONS_URL = "https://image.pollinations.ai/prompt/{prompt}?width=768&height=432&nologo=true"
IMAGE_ENABLED = True  # Muda para False se quiseres desativar imagens globalmente

# ─── Rate Limiting (Groq) ────────────────────────────────────────────────────
MAX_AI_CALLS_PER_HOUR = 60  # Limite por grupo por hora
AI_CALL_COOLDOWN_SECONDS = 5  # Mínimo entre chamadas

# ─── Base de Dados ────────────────────────────────────────────────────────────
DB_PATH = os.getenv("DB_PATH", "rpg_bot.db")

# ─── Dificuldades ─────────────────────────────────────────────────────────────
DIFFICULTIES = {
    "fácil":     {"enemy_mult": 0.7,  "xp_mult": 0.8,  "gold_mult": 0.8,  "label": "🟢 Fácil"},
    "normal":    {"enemy_mult": 1.0,  "xp_mult": 1.0,  "gold_mult": 1.0,  "label": "🟡 Normal"},
    "difícil":   {"enemy_mult": 1.4,  "xp_mult": 1.3,  "gold_mult": 1.3,  "label": "🔴 Difícil"},
    "pesadelo":  {"enemy_mult": 2.0,  "xp_mult": 1.8,  "gold_mult": 1.8,  "label": "💀 Pesadelo"},
}

# ─── Raças ────────────────────────────────────────────────────────────────────
RACES = {
    "humano":     {"emoji": "👤", "hp": 0,   "atk": 0,  "def": 0,  "agi": 0,  "mana": 0,   "xp_bonus": 0.10, "desc": "+10% XP ganho"},
    "elfo":       {"emoji": "🧝", "hp": 0,   "atk": 0,  "def": 0,  "agi": 2,  "mana": 10,  "xp_bonus": 0,    "desc": "+2 AGI, +10 MANA, visão noturna"},
    "anão":       {"emoji": "⛏️", "hp": 20,  "atk": 0,  "def": 2,  "agi": -1, "mana": 0,   "xp_bonus": 0,    "desc": "+20 HP, +2 DEF, imune a veneno"},
    "orco":       {"emoji": "👹", "hp": 10,  "atk": 4,  "def": -2, "agi": 0,  "mana": 0,   "xp_bonus": 0,    "desc": "+4 ATK, -2 DEF, intimidação"},
    "draconato":  {"emoji": "🐉", "hp": 5,   "atk": 2,  "def": 1,  "agi": 0,  "mana": 20,  "xp_bonus": 0,    "desc": "Sopro elemental 1x/combate"},
    "tiefling":   {"emoji": "😈", "hp": -5,  "atk": 0,  "def": 0,  "agi": 1,  "mana": 15,  "xp_bonus": 0,    "desc": "+15 MANA, resistência fogo"},
    "elemental":  {"emoji": "🌀", "hp": -5,  "atk": 0,  "def": 2,  "agi": 0,  "mana": 25,  "xp_bonus": 0,    "desc": "Imune a 1 elemento, +25 MANA"},
    "meio-elfo":  {"emoji": "🧙", "hp": 5,   "atk": 1,  "def": 1,  "agi": 1,  "mana": 5,   "xp_bonus": 0,    "desc": "+1 a todos os stats"},
    "gnomo":      {"emoji": "🔧", "hp": -10, "atk": 0,  "def": 0,  "agi": 2,  "mana": 10,  "xp_bonus": 0,    "desc": "+2 AGI, desativa armadilhas"},
    "halfling":   {"emoji": "🍀", "hp": 0,   "atk": 0,  "def": 0,  "agi": 3,  "mana": 0,   "xp_bonus": 0,    "desc": "Sorte passiva: relança 1 dado/turno"},
    "licantropo": {"emoji": "🐺", "hp": 15,  "atk": 3,  "def": -1, "agi": 2,  "mana": 0,   "xp_bonus": 0,    "desc": "Forma bestial em combate"},
    "espectro":   {"emoji": "👻", "hp": -15, "atk": 0,  "def": -1, "agi": 3,  "mana": 20,  "xp_bonus": 0,    "desc": "Atravessa armadilhas, invisível à noite"},
}

# ─── Classes ──────────────────────────────────────────────────────────────────
CLASSES = {
    "guerreiro":   {"emoji": "⚔️",  "hp": 120, "atk": 15, "def": 10, "agi": 5,  "mana": 0,   "desc": "Fúria: +50% ATK por 2 turnos"},
    "mago":        {"emoji": "🔮",  "hp": 70,  "atk": 8,  "def": 4,  "agi": 6,  "mana": 100, "desc": "Magia livre contextual ilimitada"},
    "arqueiro":    {"emoji": "🏹",  "hp": 90,  "atk": 12, "def": 6,  "agi": 12, "mana": 30,  "desc": "Tiro certeiro: ignora DEF inimigo"},
    "paladino":    {"emoji": "🛡️",  "hp": 110, "atk": 10, "def": 14, "agi": 4,  "mana": 50,  "desc": "Aura de cura: +5 HP aliados/turno"},
    "assassino":   {"emoji": "🗡️",  "hp": 85,  "atk": 14, "def": 5,  "agi": 15, "mana": 20,  "desc": "Primeiro ataque sempre crítico"},
    "druida":      {"emoji": "🌿",  "hp": 95,  "atk": 9,  "def": 7,  "agi": 8,  "mana": 80,  "desc": "Transformação animal contextual"},
    "necromante":  {"emoji": "💀",  "hp": 75,  "atk": 10, "def": 5,  "agi": 6,  "mana": 90,  "desc": "Invoca inimigos caídos como servos"},
    "bardo":       {"emoji": "🎵",  "hp": 80,  "atk": 8,  "def": 6,  "agi": 10, "mana": 70,  "desc": "Buff/debuff musical +/-10% stats"},
    "berserker":   {"emoji": "🪓",  "hp": 130, "atk": 18, "def": 3,  "agi": 7,  "mana": 0,   "desc": "Quanto menos HP, mais ATK"},
    "xamã":        {"emoji": "🔯",  "hp": 85,  "atk": 9,  "def": 8,  "agi": 6,  "mana": 85,  "desc": "Invoca espíritos elementais"},
}

# ─── Conquistas ───────────────────────────────────────────────────────────────
ACHIEVEMENTS = {
    "first_blood":      {"name": "Primeira Sangria",      "desc": "Mata o primeiro inimigo",             "title": "O Iniciado",          "icon": "🩸"},
    "killer_50":        {"name": "Massacre",              "desc": "Mata 50 inimigos",                    "title": "O Implacável",         "icon": "⚔️"},
    "killer_200":       {"name": "Lenda de Guerra",       "desc": "Mata 200 inimigos",                   "title": "O Exterminador",       "icon": "💀"},
    "stories_10":       {"name": "Veterano",              "desc": "Completa 10 histórias",               "title": "Veterano das Crónicas","icon": "📖"},
    "stories_50":       {"name": "Lenda Viva",            "desc": "Completa 50 histórias",               "title": "A Lenda Viva",         "icon": "🌟"},
    "legendary_3":      {"name": "Caçador de Relíquias",  "desc": "Encontra 3 itens lendários",          "title": "Caçador de Relíquias", "icon": "💎"},
    "deaths_10":        {"name": "Persistente",           "desc": "Morre 10 vezes",                      "title": "O Persistente",        "icon": "☠️"},
    "betrayals_5":      {"name": "Sombra Traiçoeira",     "desc": "Trai 5 aliados",                      "title": "A Sombra Traiçoeira",  "icon": "🗡️"},
    "tamer_10":         {"name": "Senhor das Bestas",     "desc": "Doma 10 animais",                     "title": "Senhor das Bestas",    "icon": "🐾"},
    "forger_20":        {"name": "Mestre Ferreiro",       "desc": "Forja 20 armas",                      "title": "Mestre Ferreiro",      "icon": "🔥"},
    "damage_10000":     {"name": "Força da Natureza",     "desc": "Causa 10.000 de dano total",          "title": "Força da Natureza",    "icon": "💪"},
    "gold_1000":        {"name": "Mercador Astuto",       "desc": "Acumula 1000 de ouro",                "title": "O Mercador",           "icon": "💰"},
    "alliance_10":      {"name": "Irmão de Armas",        "desc": "Forma 10 alianças",                   "title": "Irmão de Armas",       "icon": "🤝"},
    "spells_12":        {"name": "Grimório Completo",     "desc": "Aprende 12 feitiços",                 "title": "Arquimago",            "icon": "📚"},
    "boss_kill_10":     {"name": "Caçador de Bosses",     "desc": "Derrota 10 bosses finais",            "title": "O Caçador",            "icon": "🏆"},
    "no_death_story":   {"name": "Imortal",               "desc": "Completa história sem morrer",        "title": "O Imortal",            "icon": "✨"},
    "dungeon_10":       {"name": "Explorador",            "desc": "Completa 10 salas de tesouro",        "title": "O Explorador",         "icon": "🗺️"},
    "auction_win_10":   {"name": "Leiloeiro",             "desc": "Ganha 10 leilões",                    "title": "O Leiloeiro",          "icon": "🔨"},
    "level_20":         {"name": "Ascendido",             "desc": "Chega ao nível 20",                   "title": "O Ascendido",          "icon": "⭐"},
    "level_50":         {"name": "Transcendido",          "desc": "Chega ao nível 50",                   "title": "O Transcendido",       "icon": "🌠"},
}
