import aiohttp
import asyncio
import logging
import time
from urllib.parse import quote
from config import IMAGE_ENABLED

logger = logging.getLogger(__name__)

POLLINATIONS_BASE = "https://image.pollinations.ai/prompt/{prompt}?width=768&height=432&nologo=true&seed={seed}&model=flux&referrer=rpgbot"

# Lock criado de forma lazy para evitar problemas com event loop no arranque
_request_lock: asyncio.Lock | None = None
_last_request_time: float = 0.0
_MIN_INTERVAL = 3.0


def _get_lock() -> asyncio.Lock:
    """Cria o lock de forma lazy dentro do event loop correto."""
    global _request_lock
    if _request_lock is None:
        _request_lock = asyncio.Lock()
    return _request_lock


# Prefixo fixo para garantir estilo fantasy RPG em todas as imagens de cena
FANTASY_STYLE_PREFIX = (
    "epic magical medieval scene, medieval fantasy art style, "
    "digital painting, dramatic lighting, highly detailed, "
    "no modern elements, no contemporary buildings, no technology, "
)

# Sufixo para reforçar o estilo
FANTASY_STYLE_SUFFIX = (
    ", fantasy oil painting, artstation quality, "
    "epic composition, magical atmosphere"
)


async def generate_image(prompt: str, seed: int = 42, force_fantasy: bool = True) -> bytes | None:
    if not IMAGE_ENABLED:
        return None
    
    # Força estilo fantasy em imagens de cena (não em avatares que já têm o seu próprio prompt)
    if force_fantasy:
        prompt = FANTASY_STYLE_PREFIX + prompt + FANTASY_STYLE_SUFFIX

    global _last_request_time

    async with _get_lock():
        now = time.monotonic()
        elapsed = now - _last_request_time
        if elapsed < _MIN_INTERVAL:
            await asyncio.sleep(_MIN_INTERVAL - elapsed)

        encoded = quote(prompt[:250])
        url = POLLINATIONS_BASE.format(prompt=encoded, seed=abs(seed) % 99999)

        for tentativa in range(3):
            try:
                _last_request_time = time.monotonic()
                timeout = aiohttp.ClientTimeout(total=60, connect=15)
                headers = {"User-Agent": "RPGBot/1.0"}
                async with aiohttp.ClientSession(headers=headers) as session:
                    async with session.get(url, timeout=timeout) as resp:
                        if resp.status == 200:
                            data = await resp.read()
                            if len(data) > 5000:
                                return data
                            logger.warning("Pollinations: resposta pequena (%d bytes)", len(data))
                            return None
                        elif resp.status == 429:
                            wait = 15 * (tentativa + 1)
                            logger.warning("Pollinations 429 — aguardar %ds", wait)
                            await asyncio.sleep(wait)
                            continue
                        else:
                            logger.warning("Pollinations status %s", resp.status)
                            return None
            except asyncio.TimeoutError:
                logger.warning("Pollinations timeout (tentativa %d/3)", tentativa + 1)
                await asyncio.sleep(5)
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
    return await generate_image(prompt, seed=telegram_id % 99999, force_fantasy=False)
