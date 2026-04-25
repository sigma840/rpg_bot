import anthropic
import asyncio
import time
import json
import logging
from config import ANTHROPIC_API_KEY, ANTHROPIC_MODEL, MAX_AI_CALLS_PER_HOUR, AI_CALL_COOLDOWN_SECONDS

logger = logging.getLogger(__name__)

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# ─── Rate Limiter ─────────────────────────────────────────────────────────────
_call_log: dict[int, list[float]] = {}  # chat_id -> lista de timestamps
_last_call: dict[int, float] = {}


def _check_rate_limit(chat_id: int) -> bool:
    now = time.time()
    calls = _call_log.get(chat_id, [])
    calls = [t for t in calls if now - t < 3600]
    _call_log[chat_id] = calls

    last = _last_call.get(chat_id, 0)
    if now - last < AI_CALL_COOLDOWN_SECONDS:
        return False
    if len(calls) >= MAX_AI_CALLS_PER_HOUR:
        return False
    return True


def _record_call(chat_id: int):
    now = time.time()
    _call_log.setdefault(chat_id, []).append(now)
    _last_call[chat_id] = now


def _call_claude(system: str, user: str, max_tokens: int = 900) -> str | None:
    try:
        msg = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}]
        )
        return msg.content[0].text
    except Exception as e:
        logger.error("Erro Anthropic API: %s", e)
        return None


# ─── Prompt base do narrador ──────────────────────────────────────────────────
NARRATOR_SYSTEM = """És o narrador de um jogo RPG de fantasia a decorrer num grupo Telegram, em Português de Portugal.
O teu estilo é épico, imersivo e cinematográfico. Usas linguagem rica mas acessível.
Cada resposta é um JSON válido e nada mais — sem markdown, sem texto fora do JSON.

Estrutura obrigatória:
{
  "narration": "texto narrativo do turno (~150 palavras, vívido e dramático)",
  "options": ["opção 1", "opção 2", "opção 3", "opção 4"],
  "events": {
    "item_found": null,
    "weapon_found": null,
    "skill_offered": null,
    "spell_offered": null,
    "enemy_spawned": null,
    "companion_available": null,
    "dungeon_room": null,
    "xp_gained": 0,
    "gold_gained": 0,
    "secret_event": null,
    "weather_change": null,
    "time_change": null,
    "npc_met": null
  },
  "image_prompt": "prompt em inglês para gerar imagem da cena (descreve ambiente, personagens presentes, clima, hora do dia, ação principal)"
}

Regras:
- As opções devem ser variadas: combate, fuga, diplomacia, uso de magia/skill, exploração
- item_found: {"name":"...", "type":"consumível|equipável|passivo|quest|material", "rarity":"comum|incomum|raro|épico|lendário", "description":"...", "effect":{}}
- weapon_found: {"name":"...", "rarity":"...", "lore":"...", "atk_bonus":0, "element":"", "special_effect":""}
- skill_offered: {"name":"...", "description":"...", "effect":{}}
- spell_offered: {"name":"...", "description":"...", "mana_cost":10, "element":"", "effect":{}}
- enemy_spawned: {"name":"...", "hp":50, "atk":10, "def":5, "element":"", "weakness":"", "is_boss":false, "is_miniboss":false, "behaviors":[]}
- companion_available: {"name":"...", "animal_type":"...", "hp":50, "atk":8, "def":4, "special":"...", "description":"..."}
- dungeon_room: {"title":"...", "description":"...", "puzzle_type":"choices|riddle|doors", "options":[], "reward_hint":"..."}
- secret_event: {"target_player_id": 0, "message":"mensagem privada para esse jogador", "secret_objective":"..."}
- weather_change: "chuva|neve|tempestade|neblina|sol|eclipse|calor"
- time_change: "dia|noite|amanhecer|crepúsculo"
- image_prompt deve ser detalhado e visual, mencionando os personagens com as suas descrições físicas
"""


async def generate_turn(
    chat_id: int,
    session: dict,
    players: list[dict],
    action_taken: str,
    combat_result: dict | None = None,
) -> dict | None:

    if not _check_rate_limit(chat_id):
        logger.warning("Rate limit atingido para chat %s", chat_id)
        return None

    players_info = []
    for p in players:
        players_info.append({
            "name": p.get("char_name", "?"),
            "race": p.get("race", "?"),
            "class": p.get("class", "?"),
            "hp": f"{p.get('hp_current',0)}/{p.get('hp_max',100)}",
            "mana": f"{p.get('mana_current',0)}/{p.get('mana_max',0)}",
            "avatar": p.get("avatar_desc", ""),
            "alive": bool(p.get("is_alive", 1)),
            "skills": p.get("skills", []),
            "companions": p.get("companions", []),
        })

    user_prompt = f"""
TURNO: {session.get('current_turn', 1)}/20
DIFICULDADE: {session.get('difficulty', 'normal')}
CLIMA: {session.get('weather', 'sol')}
HORA: {session.get('time_of_day', 'dia')}

JOGADORES:
{json.dumps(players_info, ensure_ascii=False)}

RESUMO DA HISTÓRIA ATÉ AGORA:
{session.get('story_summary', 'A aventura começa agora.')}

AÇÃO DO JOGADOR ATUAL ({players[0].get('char_name','?') if players else '?'}):
{action_taken}

{f"RESULTADO DO COMBATE: {json.dumps(combat_result, ensure_ascii=False)}" if combat_result else ""}

Gera o próximo turno da história. Lembra-te que estamos no turno {session.get('current_turn',1)} de 20.
{"ATENÇÃO: Aproxima-te do clímax, a história deve intensificar-se." if session.get('current_turn',1) >= 15 else ""}
{"ATENÇÃO: Este é um dos últimos turnos. Prepara o epílogo." if session.get('current_turn',1) >= 18 else ""}
Responde APENAS com JSON válido.
"""

    loop = asyncio.get_event_loop()
    raw = await loop.run_in_executor(None, lambda: _call_claude(NARRATOR_SYSTEM, user_prompt))
    _record_call(chat_id)

    if not raw:
        return None

    try:
        clean = raw.strip()
        if clean.startswith("```"):
            clean = clean.split("```")[1]
            if clean.startswith("json"):
                clean = clean[4:]
        return json.loads(clean)
    except Exception as e:
        logger.error("Erro ao parsear resposta da IA: %s\nRaw: %s", e, raw[:200])
        return None


async def generate_prologue(chat_id: int, session: dict, players: list[dict]) -> dict | None:
    if not _check_rate_limit(chat_id):
        return None

    players_info = [
        f"{p.get('char_name','?')} ({p.get('race','?')} {p.get('class','?')}): {p.get('avatar_desc','')}"
        for p in players
    ]
    difficulty = session.get("difficulty", "normal")

    user_prompt = f"""
Cria o prólogo épico de uma nova aventura RPG.
DIFICULDADE: {difficulty}
JOGADORES: {json.dumps(players_info, ensure_ascii=False)}

Responde com JSON:
{{
  "narration": "prólogo épico de ~200 palavras que apresenta o mundo, o perigo e chama os heróis à ação",
  "options": ["opção 1 para começar", "opção 2", "opção 3"],
  "events": {{"weather_change": null, "time_change": "dia", "xp_gained": 0, "gold_gained": 0, "item_found": null, "weapon_found": null, "skill_offered": null, "spell_offered": null, "enemy_spawned": null, "companion_available": null, "dungeon_room": null, "secret_event": null, "npc_met": null}},
  "image_prompt": "prompt visual em inglês da cena de abertura"
}}
"""

    loop = asyncio.get_event_loop()
    raw = await loop.run_in_executor(None, lambda: _call_claude(NARRATOR_SYSTEM, user_prompt, max_tokens=1000))
    _record_call(chat_id)

    if not raw:
        return None
    try:
        clean = raw.strip()
        if clean.startswith("```"):
            clean = clean.split("```")[1]
            if clean.startswith("json"):
                clean = clean[4:]
        return json.loads(clean)
    except Exception as e:
        logger.error("Erro prólogo: %s", e)
        return None


async def generate_epilogue(chat_id: int, session: dict, players: list[dict], full_log: list) -> str | None:
    if not _check_rate_limit(chat_id):
        return None

    players_info = [
        {"name": p.get("char_name","?"), "race": p.get("race","?"), "class": p.get("class","?"),
         "kills": p.get("session_kills",0), "damage": p.get("session_damage",0), "alive": bool(p.get("is_alive",1))}
        for p in players
    ]

    # Resumo dos momentos chave (últimas 5 entradas do log)
    key_moments = full_log[-5:] if len(full_log) > 5 else full_log

    user_prompt = f"""
A história terminou. Cria um epílogo épico em português com:
1. Narração dramática do fim (~150 palavras)
2. Um parágrafo personalizado para cada jogador com o seu momento mais épico

JOGADORES: {json.dumps(players_info, ensure_ascii=False)}
MOMENTOS CHAVE: {json.dumps(key_moments, ensure_ascii=False)}

Responde apenas com o texto do epílogo, sem JSON, formatado para Telegram com <b> e <i>.
"""

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, lambda: _call_claude(
        "És um narrador épico de RPG. Escreves epílogos dramáticos e emocionantes em português.",
        user_prompt,
        max_tokens=1000
    ))
    _record_call(chat_id)
    return result


async def validate_forge(chat_id: int, weapon_name: str, material_name: str, material_desc: str) -> dict | None:
    if not _check_rate_limit(chat_id):
        return {"valid": False, "reason": "Sistema ocupado, tenta novamente."}

    user_prompt = f"""
Um ferreiro quer fundir:
- ARMA: {weapon_name}
- MATERIAL: {material_name} ({material_desc})

Isto faz sentido num contexto de fantasia medieval?
Responde com JSON:
{{"valid": true/false, "reason": "motivo breve", "result_name": "nome da arma resultante se válido", "new_effect": "efeito especial ganho se válido", "atk_bonus": 0, "element": ""}}
"""

    loop = asyncio.get_event_loop()
    raw = await loop.run_in_executor(None, lambda: _call_claude(
        "És um mestre ferreiro de fantasia. Decides se combinações de forja fazem sentido. Respondes só com JSON.",
        user_prompt,
        max_tokens=200
    ))
    _record_call(chat_id)

    if not raw:
        return None
    try:
        clean = raw.strip()
        if clean.startswith("```"):
            clean = clean.split("```")[1]
            if clean.startswith("json"):
                clean = clean[4:]
        return json.loads(clean)
    except Exception:
        return None


async def generate_global_event(chat_id: int) -> dict | None:
    if not _check_rate_limit(chat_id):
        return None

    user_prompt = """Gera um evento global para o reino que afeta todos os jogadores deste grupo.
Pode ser positivo ou negativo. Responde com JSON:
{"title": "...", "description": "anúncio dramático ~80 palavras", "effect": {"hp_mod": 0, "mana_mod": 0, "xp_mult": 1.0, "gold_mult": 1.0, "description": "efeito mecânico"}, "duration_hours": 24}
"""

    loop = asyncio.get_event_loop()
    raw = await loop.run_in_executor(None, lambda: _call_claude(
        "És o deus de um mundo de fantasia. Decretas eventos globais dramáticos. Respondes só com JSON.",
        user_prompt,
        max_tokens=300
    ))
    _record_call(chat_id)

    if not raw:
        return None
    try:
        clean = raw.strip()
        if clean.startswith("```"):
            clean = clean.split("```")[1]
            if clean.startswith("json"):
                clean = clean[4:]
        return json.loads(clean)
    except Exception:
        return None


async def generate_avatar(telegram_id: int, description: str, race: str, char_class: str) -> str:
    """Gera prompt para a imagem do avatar."""
    prompt = (
        f"fantasy RPG character portrait, {description}, "
        f"{race} race, {char_class} class, "
        "detailed armor and weapons, dramatic lighting, "
        "epic fantasy art style, high quality, vibrant colors"
    )
    return prompt.replace(" ", "%20")
