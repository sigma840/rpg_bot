import asyncio
import time
import json
import logging
import urllib.request
from config import GEMINI_API_KEY, MAX_AI_CALLS_PER_HOUR, AI_CALL_COOLDOWN_SECONDS

logger = logging.getLogger(__name__)

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={key}"

_call_log: dict = {}
_last_call: dict = {}


def _check_rate_limit(chat_id: int) -> bool:
    return True  # Rate limit desativado


def _record_call(chat_id: int):
    now = time.time()
    _call_log.setdefault(chat_id, []).append(now)
    _last_call[chat_id] = now


def _call_gemini(prompt: str, max_tokens: int = 900) -> str | None:
    try:
        url = GEMINI_URL.format(key=GEMINI_API_KEY)
        payload = json.dumps({
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.9}
        }).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        logger.error("Erro Gemini API: %s", e)
        return None


NARRATOR_SYSTEM = """Es o narrador de um jogo RPG de fantasia num grupo Telegram, em Portugues de Portugal.
Estilo epico, imersivo e cinematografico. Responde APENAS com JSON valido, sem mais nada, sem markdown.

Estrutura obrigatoria:
{
  "narration": "texto narrativo ~150 palavras",
  "options": ["opcao 1", "opcao 2", "opcao 3", "opcao 4"],
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
  "image_prompt": "prompt em ingles para imagem da cena"
}

item_found: {"name":"...","type":"consumivel|equipavel|passivo|quest|material","rarity":"comum|incomum|raro|epico|lendario","description":"...","effect":{}}
weapon_found: {"name":"...","rarity":"...","lore":"...","atk_bonus":0,"element":"","special_effect":""}
skill_offered: {"name":"...","description":"...","effect":{}}
spell_offered: {"name":"...","description":"...","mana_cost":10,"element":"","effect":{}}
enemy_spawned: {"name":"...","hp":50,"atk":10,"def":5,"element":"","weakness":"","is_boss":false,"is_miniboss":false,"behaviors":[]}
companion_available: {"name":"...","animal_type":"...","hp":50,"atk":8,"def":4,"special":"...","description":"..."}"""


def _parse_json(raw: str) -> dict | None:
    if not raw:
        return None
    try:
        clean = raw.strip()
        if "```" in clean:
            parts = clean.split("```")
            for part in parts:
                if part.startswith("json"):
                    clean = part[4:].strip()
                    break
                elif "{" in part:
                    clean = part.strip()
                    break
        start = clean.find("{")
        end = clean.rfind("}") + 1
        if start >= 0 and end > start:
            clean = clean[start:end]
        return json.loads(clean)
    except Exception as e:
        logger.error("Erro JSON parse: %s", e)
        return None


async def generate_turn(chat_id: int, session: dict, players: list, action_taken: str, combat_result=None) -> dict | None:
    if not _check_rate_limit(chat_id):
        return None

    players_info = [{"name": p.get("char_name","?"), "race": p.get("race","?"), "class": p.get("class","?"),
                     "hp": f"{p.get('hp_current',0)}/{p.get('hp_max',100)}", "alive": bool(p.get("is_alive",1)),
                     "skills": p.get("skills",[]), "avatar": p.get("avatar_desc","")} for p in players]

    prompt = f"""{NARRATOR_SYSTEM}

TURNO: {session.get('current_turn',1)}/20 | DIFICULDADE: {session.get('difficulty','normal')} | CLIMA: {session.get('weather','sol')} | HORA: {session.get('time_of_day','dia')}
JOGADORES: {json.dumps(players_info, ensure_ascii=False)}
RESUMO: {session.get('story_summary','A aventura comeca agora.')}
ACAO ({players[0].get('char_name','?') if players else '?'}): {action_taken}
{f'COMBATE: {json.dumps(combat_result, ensure_ascii=False)}' if combat_result else ''}
{'ATENCAO: Aproxima-te do climax.' if session.get('current_turn',1) >= 15 else ''}
{'ATENCAO: Prepara o epilogo.' if session.get('current_turn',1) >= 18 else ''}

Responde APENAS com JSON valido."""

    loop = asyncio.get_event_loop()
    raw = await loop.run_in_executor(None, lambda: _call_gemini(prompt))
    _record_call(chat_id)
    return _parse_json(raw)


async def generate_prologue(chat_id: int, session: dict, players: list) -> dict | None:
    if not _check_rate_limit(chat_id):
        return None

    players_info = [f"{p.get('char_name','?')} ({p.get('race','?')} {p.get('class','?')}): {p.get('avatar_desc','')}" for p in players]

    prompt = f"""{NARRATOR_SYSTEM}

Cria o prologo epico de uma nova aventura RPG em Portugues de Portugal.
DIFICULDADE: {session.get('difficulty','normal')}
JOGADORES: {json.dumps(players_info, ensure_ascii=False)}

Responde com JSON onde narration tem ~200 palavras de prologo epico, options tem 3 opcoes para comecar, e image_prompt descreve a cena de abertura em ingles.
events deve ter: {{"weather_change":null,"time_change":"dia","xp_gained":0,"gold_gained":0,"item_found":null,"weapon_found":null,"skill_offered":null,"spell_offered":null,"enemy_spawned":null,"companion_available":null,"dungeon_room":null,"secret_event":null,"npc_met":null}}

Responde APENAS com JSON valido."""

    loop = asyncio.get_event_loop()
    raw = await loop.run_in_executor(None, lambda: _call_gemini(prompt, max_tokens=1000))
    _record_call(chat_id)
    return _parse_json(raw)


async def generate_epilogue(chat_id: int, session: dict, players: list, full_log: list) -> str | None:
    if not _check_rate_limit(chat_id):
        return None

    players_info = [{"name": p.get("char_name","?"), "kills": p.get("session_kills",0),
                     "damage": p.get("session_damage",0), "alive": bool(p.get("is_alive",1))} for p in players]

    prompt = f"""Es um narrador epico de RPG. Escreves epilogos dramaticos em Portugues de Portugal.

Cria um epilogo epico com narração dramatica do fim (~150 palavras) e um paragrafo para cada jogador com o seu momento mais epico.
Usa tags HTML <b> e <i> para formatacao Telegram.

JOGADORES: {json.dumps(players_info, ensure_ascii=False)}
MOMENTOS: {json.dumps(full_log[-5:] if len(full_log) > 5 else full_log, ensure_ascii=False)}"""

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, lambda: _call_gemini(prompt, max_tokens=1000))
    _record_call(chat_id)
    return result


async def validate_forge(chat_id: int, weapon_name: str, material_name: str, material_desc: str) -> dict | None:
    if not _check_rate_limit(chat_id):
        return {"valid": False, "reason": "Sistema ocupado."}

    prompt = f"""Es um mestre ferreiro de fantasia. Responde APENAS com JSON valido.

Fundir: ARMA: {weapon_name} + MATERIAL: {material_name} ({material_desc})
Faz sentido em fantasia medieval?
{{"valid":true,"reason":"...","result_name":"...","new_effect":"...","atk_bonus":0,"element":""}}"""

    loop = asyncio.get_event_loop()
    raw = await loop.run_in_executor(None, lambda: _call_gemini(prompt, max_tokens=200))
    _record_call(chat_id)
    return _parse_json(raw)


async def generate_global_event(chat_id: int) -> dict | None:
    if not _check_rate_limit(chat_id):
        return None

    prompt = """Es o deus de um mundo de fantasia. Responde APENAS com JSON valido.

Gera evento global para o reino (positivo ou negativo):
{"title":"...","description":"anuncio dramatico ~80 palavras","effect":{"hp_mod":0,"mana_mod":0,"xp_mult":1.0,"gold_mult":1.0,"description":"..."},"duration_hours":24}"""

    loop = asyncio.get_event_loop()
    raw = await loop.run_in_executor(None, lambda: _call_gemini(prompt, max_tokens=300))
    _record_call(chat_id)
    return _parse_json(raw)


async def generate_avatar(telegram_id: int, description: str, race: str, char_class: str) -> str:
    prompt = f"fantasy RPG character portrait, {description}, {race} race, {char_class} class, detailed armor, dramatic lighting, epic fantasy art"
    return prompt.replace(" ", "%20")
