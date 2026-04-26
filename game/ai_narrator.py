import asyncio
import time
import json
import logging
from groq import Groq
from config import GROQ_API_KEY, MAX_AI_CALLS_PER_HOUR, AI_CALL_COOLDOWN_SECONDS

logger = logging.getLogger(__name__)

GROQ_MODEL = "llama-3.3-70b-versatile"
GROQ_MODEL_FAST = "llama-3.1-8b-instant"  # fallback com menos rate limit

_call_log: dict = {}
_last_call: dict = {}
_groq_client = None


def _get_client():
    global _groq_client
    if _groq_client is None:
        _groq_client = Groq(api_key=GROQ_API_KEY)
    return _groq_client


def _check_rate_limit(chat_id: int) -> bool:
    return True


def _record_call(chat_id: int):
    now = time.time()
    _call_log.setdefault(chat_id, []).append(now)
    _last_call[chat_id] = now


def _call_groq(prompt: str, max_tokens: int = 900) -> str | None:
    client = _get_client()
    # Tenta primeiro o modelo principal, depois o fallback
    models_to_try = [GROQ_MODEL, GROQ_MODEL_FAST]
    for model in models_to_try:
        esperas = [8, 20, 45]
        for tentativa in range(3):
            try:
                response = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=max_tokens,
                    temperature=0.9
                )
                return response.choices[0].message.content
            except Exception as e:
                code = getattr(e, 'status_code', None)
                if code == 429:
                    if tentativa < 2:
                        espera = esperas[tentativa]
                        logger.warning("Groq 429 (%s) - Tentativa %d/3. A aguardar %ds...", model, tentativa + 1, espera)
                        time.sleep(espera)
                    else:
                        logger.warning("Groq 429 (%s) - esgotado, a tentar modelo fallback.", model)
                        break  # tenta o próximo modelo
                else:
                    logger.error("Erro Groq API (%s): %s", model, e)
                    return None
    logger.error("Groq falhou em todos os modelos.")
    return None


NARRATOR_SYSTEM = """Es o narrador de um jogo RPG de fantasia num grupo Telegram, em Portugues de Portugal.
Estilo epico, imersivo e cinematografico. Responde APENAS com JSON valido, sem mais nada, sem markdown.

REGRAS CRITICAS DE VARIEDADE — LER COM ATENCAO:
- NUNCA repitas o mesmo tipo de cena duas vezes seguidas. Se o turno anterior foi explorar floresta, o proximo e diferente.
- RODA obrigatoriamente por estes tipos de cena (escolhe baseado no turno e historia):
  * ENCONTRO NPC: mercador ambulante, bardo numa estalagem, feiticeiro ermita, nobre fugitivo, crianca perdida, guarda corrupto, druida misterioso, fantasma de guerreiro, ladrao arrependido
  * LUGAR ESPECIAL: ruinas antigas, torre abandonada, aldeia assombrada, lago encantado, caverna de cristais, altar pagao, cemiterio esquecido, ponte sobre abismo, mercado movimentado, estalagem animada
  * EVENTO ALEATORIO: tempestade repentina, terremoto menor, chuva de estrelas, aparicao de criatura rara, festival de aldeia, conflito entre NPCs, mensageiro com carta urgente, incendio numa casa, fuga de prisioneiro, descoberta de mapa
  * ARMADILHA/PUZZLE: chao que cede, runas que brilham, porta com enigma, espelho magico que mostra o futuro, cofre com mecanismo, labirinto de setos, ilusao magica
  * DESCANSO/SOCIAL: estalagem com historias, conversa reveladora com NPC, sonho profetico, ritual de um povo local, celebracao de aldeia, encontro com velho conhecido
  * DESCOBERTA: tesouro escondido, diario de aventureiro morto, portal dimensional, artefacto misterioso, passagem secreta, vista deslumbrante com pista
  * ANIMAIS/NATUREZA: alcateia de lobos, grifo ferido, unicornio assustado, dragao jovem curioso, rebanho de pegasos, planta carnivora, cogumelos gigantes magicos

- COMPANHEIROS: so aparecem como companion_available quando faz narrativamente sentido (animal ferido que os jogadores salvam, animal magico que escolhe o grupo, cria de fera que ficou orfao). NAO no inicio da historia.
- enemy_spawned MAXIMO 1 em cada 4 turnos — os outros turnos sao eventos, descobertas, NPCs, etc.
- xp_gained SEMPRE entre 5 e 20
- gold_gained entre 0 e 15 ocasionalmente
- options: SEMPRE 3-4 acoes DIFERENTES entre si e relevantes para a cena atual. NUNCA "Seguir em frente" e "Continuar o caminho" juntos — sao a mesma coisa. Cada opcao deve ser unica e interessante: uma pode ser agressiva, outra diplomatica, outra furtiva, outra magica.
- image_prompt: descricao visual da cena em ingles, max 120 palavras. OBRIGATORIO incluir aparencia de cada jogador (raca, classe, avatar_desc/equipamento), companheiros domados se existirem (animal, aparencia), e contexto preciso da cena (local, atmosfera, acao em curso, clima, hora do dia).

Estrutura obrigatoria:
{
  "narration": "texto narrativo ~150 palavras, cinematografico e imersivo",
  "options": ["opcao 1 unica", "opcao 2 diferente", "opcao 3 diferente", "opcao 4 diferente"],
  "events": {
    "item_found": null,
    "weapon_found": null,
    "skill_offered": null,
    "spell_offered": null,
    "enemy_spawned": null,
    "companion_available": null,
    "dungeon_room": null,
    "xp_gained": 10,
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
companion_available: {"name":"...","animal_type":"...","hp":50,"atk":8,"def":4,"special":"...","description":"..."}
npc_met: {"name":"...","role":"...","personality":"...","has_quest":false,"dialogue":"fala inicial do NPC"}
secret_event: {"type":"...","description":"...","effect":{}}"""


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

    from game.progression import get_companions
    players_info = []
    for p in players:
        companions = get_companions(p.get("telegram_id", 0))
        companions_info = [{"name": c["name"], "animal_type": c["animal_type"], "description": c.get("description", "")} for c in companions]
        players_info.append({
            "name": p.get("char_name", "?"),
            "race": p.get("race", "?"),
            "class": p.get("class", "?"),
            "hp": f"{p.get('hp_current', 0)}/{p.get('hp_max', 100)}",
            "alive": bool(p.get("is_alive", 1)),
            "skills": p.get("skills", []),
            "avatar": p.get("avatar_desc", ""),
            "companions": companions_info,
        })

    prompt = f"""{NARRATOR_SYSTEM}

TURNO: {session.get('current_turn',1)}/20 | DIFICULDADE: {session.get('difficulty','normal')} | CLIMA: {session.get('weather','sol')} | HORA: {session.get('time_of_day','dia')}
JOGADORES: {json.dumps(players_info, ensure_ascii=False)}
RESUMO: {session.get('story_summary','A aventura comeca agora.')}
ULTIMO_EVENTO_TIPO: {session.get('last_event_type','nenhum')} — NAO repitas este tipo de evento/cena agora.
ACAO ({players[0].get('char_name','?') if players else '?'}): {action_taken}
{f'COMBATE: {json.dumps(combat_result, ensure_ascii=False)}' if combat_result else ''}
{'ATENCAO: Aproxima-te do climax. Cria tensao maxima.' if session.get('current_turn',1) >= 15 else ''}
{'ATENCAO: Prepara o epilogo. Resolve os fios da historia.' if session.get('current_turn',1) >= 18 else ''}

Responde APENAS com JSON valido."""

    loop = asyncio.get_event_loop()
    raw = await loop.run_in_executor(None, lambda: _call_groq(prompt))
    _record_call(chat_id)
    return _parse_json(raw)


async def generate_prologue(chat_id: int, session: dict, players: list) -> dict | None:
    if not _check_rate_limit(chat_id):
        return None

    # No prologo os jogadores NAO tem companheiros — estes so sao domados durante a historia
    players_info = [f"{p.get('char_name','?')} ({p.get('race','?')} {p.get('class','?')}): {p.get('avatar_desc','')}" for p in players]

    prompt = f"""{NARRATOR_SYSTEM}

Cria o prologo epico de uma nova aventura RPG em Portugues de Portugal.
DIFICULDADE: {session.get('difficulty','normal')}
JOGADORES (SEM companheiros no inicio): {json.dumps(players_info, ensure_ascii=False)}

Narration ~200 palavras: prologo cinematografico que estabelece o mundo, o perigo e o chamado a aventura. Termina com os jogadores numa situacao inicial interessante (NAO apenas "estao na estrada").
Options: 3 primeiras acoes possiveis bem diferentes entre si.
image_prompt: cena de abertura epica com os jogadores descritos.
events: {{"weather_change":null,"time_change":"dia","xp_gained":0,"gold_gained":0,"item_found":null,"weapon_found":null,"skill_offered":null,"spell_offered":null,"enemy_spawned":null,"companion_available":null,"dungeon_room":null,"secret_event":null,"npc_met":null}}

Responde APENAS com JSON valido."""

    loop = asyncio.get_event_loop()
    raw = await loop.run_in_executor(None, lambda: _call_groq(prompt, max_tokens=1000))
    _record_call(chat_id)
    return _parse_json(raw)


async def generate_epilogue(chat_id: int, session: dict, players: list, full_log: list) -> str | None:
    if not _check_rate_limit(chat_id):
        return None

    players_info = [{"name": p.get("char_name","?"), "kills": p.get("session_kills",0),
                     "damage": p.get("session_damage",0), "alive": bool(p.get("is_alive",1))} for p in players]

    prompt = f"""Es um narrador epico de RPG. Escreves epilogos dramaticos em Portugues de Portugal.

Cria um epilogo epico com narracao dramatica do fim (~150 palavras) e um paragrafo para cada jogador com o seu momento mais epico.
Usa tags HTML <b> e <i> para formatacao Telegram.

JOGADORES: {json.dumps(players_info, ensure_ascii=False)}
MOMENTOS: {json.dumps(full_log[-5:] if len(full_log) > 5 else full_log, ensure_ascii=False)}"""

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, lambda: _call_groq(prompt, max_tokens=1000))
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
    raw = await loop.run_in_executor(None, lambda: _call_groq(prompt, max_tokens=200))
    _record_call(chat_id)
    return _parse_json(raw)


async def generate_global_event(chat_id: int) -> dict | None:
    if not _check_rate_limit(chat_id):
        return None

    prompt = """Es o deus de um mundo de fantasia. Responde APENAS com JSON valido.

Gera evento global para o reino (positivo ou negativo):
{"title":"...","description":"anuncio dramatico ~80 palavras","effect":{"hp_mod":0,"mana_mod":0,"xp_mult":1.0,"gold_mult":1.0,"description":"..."},"duration_hours":24}"""

    loop = asyncio.get_event_loop()
    raw = await loop.run_in_executor(None, lambda: _call_groq(prompt, max_tokens=300))
    _record_call(chat_id)
    return _parse_json(raw)


async def generate_avatar(telegram_id: int, description: str, race: str, char_class: str) -> str:
    prompt = f"fantasy RPG character portrait, {description}, {race} race, {char_class} class, detailed armor, dramatic lighting, epic fantasy art"
    return prompt.replace(" ", "%20")
