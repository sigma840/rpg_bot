import aiohttp
import asyncio
import logging
import time
from urllib.parse import quote
from config import IMAGE_ENABLED

logger = logging.getLogger(__name__)

# Usa o endpoint de API oficial do Pollinations que é mais estável
POLLINATIONS_BASE = "https://image.pollinations.ai/prompt/{prompt}?width=768&height=432&nologo=true&seed={seed}&model=flux"

_request_lock = asyncio.Lock()
_last_request_time: float = 0.0
_MIN_INTERVAL = 6.0  # segundos mínimos entre pedidos


async def generate_image(prompt: str, seed: int = 42) -> bytes | None:
    """Gera imagem via Pollinations.AI com fila serializada para evitar 429."""
    if not IMAGE_ENABLED:
        return None

    global _last_request_time

    async with _request_lock:
        # Espera o intervalo mínimo
        now = time.monotonic()
        elapsed = now - _last_request_time
        if elapsed < _MIN_INTERVAL:
            await asyncio.sleep(_MIN_INTERVAL - elapsed)

        encoded = quote(prompt[:250])
        url = POLLINATIONS_BASE.format(prompt=encoded, seed=abs(seed) % 99999)

        for tentativa in range(2):
            try:
                _last_request_time = time.monotonic()
                timeout = aiohttp.ClientTimeout(total=50, connect=10)
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, timeout=timeout) as resp:
                        if resp.status == 200:
                            data = await resp.read()
                            if len(data) > 5000:  # imagem real tem pelo menos 5KB
                                return data
                            logger.warning("Pollinations: resposta muito pequena (%d bytes)", len(data))
                            return None
                        elif resp.status == 429:
                            logger.warning("Pollinations 429 na tentativa %d", tentativa + 1)
                            await asyncio.sleep(10)
                            continue
                        else:
                            logger.warning("Pollinations status %s", resp.status)
                            return None
            except asyncio.TimeoutError:
                logger.warning("Pollinations timeout (tentativa %d)", tentativa + 1)
                if tentativa == 0:
                    await asyncio.sleep(3)
                continue
            except Exception as e:
                logger.error("Erro ao gerar imagem: %s", e)
                return None

        return None


async def generate_avatar_image(description: str, race: str, char_class: str, telegram_id: int) -> bytes | None:
    prompt = (
        f"fantasy RPG character portrait, {description}, "
        f"{race} race, {char_class} class, "
        "detailed fantasy equipment, dramatic lighting, epic art style, "
        "high quality digital painting, vibrant colors, hero pose"
    )
    return await generate_image(prompt, seed=telegram_id % 99999)
