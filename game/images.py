import aiohttp
import asyncio
import logging
import time
from urllib.parse import quote
from config import IMAGE_ENABLED

logger = logging.getLogger(__name__)

# Modelo flux é mais rápido e estável no Pollinations
POLLINATIONS_BASE = "https://image.pollinations.ai/prompt/{prompt}?width=768&height=432&nologo=true&seed={seed}&model=flux&enhance=false"

# Rate limiting simples — guarda o timestamp do último pedido
_last_request_time: float = 0.0
_MIN_INTERVAL = 4.0  # segundos entre pedidos para não dar 429


async def generate_image(prompt: str, seed: int = 42) -> bytes | None:
    """Gera imagem via Pollinations.AI com rate limiting."""
    if not IMAGE_ENABLED:
        return None

    global _last_request_time

    # Espera se necessário para respeitar o rate limit
    now = time.monotonic()
    elapsed = now - _last_request_time
    if elapsed < _MIN_INTERVAL:
        await asyncio.sleep(_MIN_INTERVAL - elapsed)

    encoded = quote(prompt[:300])
    url = POLLINATIONS_BASE.format(prompt=encoded, seed=seed % 99999)

    try:
        _last_request_time = time.monotonic()
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=45)) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    if len(data) > 1000:  # verifica que é uma imagem real
                        return data
                    logger.warning("Pollinations devolveu resposta vazia")
                    return None
                elif resp.status == 429:
                    logger.warning("Pollinations 429 — rate limit atingido, a aguardar...")
                    await asyncio.sleep(8)
                    return None
                else:
                    logger.warning("Pollinations devolveu status %s", resp.status)
                    return None
    except asyncio.TimeoutError:
        logger.warning("Timeout ao gerar imagem Pollinations")
        return None
    except Exception as e:
        logger.error("Erro ao gerar imagem: %s", e)
        return None


async def generate_avatar_image(description: str, race: str, char_class: str, telegram_id: int) -> bytes | None:
    prompt = (
        f"fantasy RPG character portrait, {description}, "
        f"{race} race, {char_class} class, "
        "detailed fantasy equipment, dramatic lighting, epic art style, "
        "high quality digital painting, vibrant colors, hero pose"
    )
    return await generate_image(prompt, seed=telegram_id % 99999)
