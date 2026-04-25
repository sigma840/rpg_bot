from datetime import datetime
from db.database import db_get, db_all, db_run, json_get, json_set
from game.ai_narrator import generate_global_event
import json
import random


async def trigger_global_event(chat_id: int) -> dict | None:
    """Gera e ativa um evento global via IA."""
    event = await generate_global_event(chat_id)
    if not event:
        return None

    expires_at = None
    if event.get("duration_hours"):
        from datetime import timedelta
        expires_at = (datetime.now() + timedelta(hours=event["duration_hours"])).isoformat()

    eid = db_run(
        "INSERT INTO global_events (title, description, effect, active, expires_at) VALUES (?,?,?,1,?)",
        (event["title"], event["description"],
         json.dumps(event.get("effect", {}), ensure_ascii=False), expires_at)
    )
    event["id"] = eid
    return event


def get_active_global_events() -> list[dict]:
    now = datetime.now().isoformat()
    return db_all(
        "SELECT * FROM global_events WHERE active=1 AND (expires_at IS NULL OR expires_at > ?)",
        (now,)
    )


def expire_old_events():
    now = datetime.now().isoformat()
    db_run("UPDATE global_events SET active=0 WHERE expires_at IS NOT NULL AND expires_at <= ?", (now,))


def get_active_event_effects() -> dict:
    """Retorna efeitos combinados de todos os eventos ativos."""
    events = get_active_global_events()
    combined = {"hp_mod": 0, "mana_mod": 0, "xp_mult": 1.0, "gold_mult": 1.0}
    for event in events:
        effect = json_get(event.get("effect", "{}"), {})
        combined["hp_mod"] += effect.get("hp_mod", 0)
        combined["mana_mod"] += effect.get("mana_mod", 0)
        combined["xp_mult"] *= effect.get("xp_mult", 1.0)
        combined["gold_mult"] *= effect.get("gold_mult", 1.0)
    return combined


def format_events_text() -> str:
    events = get_active_global_events()
    if not events:
        return "🌍 Nenhum evento global ativo."
    lines = ["🌍 <b>Eventos Globais Ativos</b>\n"]
    for e in events:
        lines.append(f"⚡ <b>{e['title']}</b>")
        lines.append(f"<i>{e['description'][:150]}</i>")
        if e.get("expires_at"):
            ends = datetime.fromisoformat(e["expires_at"])
            remaining = ends - datetime.now()
            hours = int(remaining.total_seconds() / 3600)
            lines.append(f"⏱ Expira em {hours}h")
        lines.append("")
    return "\n".join(lines)


def generate_secret_objective() -> str:
    """Gera um objetivo secreto aleatório para um jogador."""
    objectives = [
        "Garante que o jogador com mais HP morre antes do turno 15.",
        "Encontra um item lendário sem que nenhum aliado saiba.",
        "Trai um aliado em combate sem seres apanhado.",
        "Faz o grupo escolher a opção mais perigosa pelo menos 3 vezes.",
        "Sobrevive até ao fim sem usar nenhum item de cura.",
        "Acumula mais ouro do que qualquer outro jogador nesta história.",
        "Impede que um boss seja derrotado antes do turno 16.",
        "Mata mais inimigos do que qualquer outro jogador.",
    ]
    return random.choice(objectives)
