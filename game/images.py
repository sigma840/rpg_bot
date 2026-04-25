import aiohttp
import asyncio
import logging
from urllib.parse import quote
from config import IMAGE_ENABLED

logger = logging.getLogger(__name__)

POLLINATIONS_BASE = "https://image.pollinations.ai/prompt/{prompt}?width=768&height=432&nologo=true&seed={seed}"


async def generate_image(prompt: str, seed: int = 42) -> bytes | None:
    """Gera imagem via Pollinations.AI (gratuito, sem key).
    Retorna bytes da imagem ou None se falhar.
    """
    if not IMAGE_ENABLED:
        return None

    encoded = quote(prompt[:400])  # Limita tamanho do prompt
    url = POLLINATIONS_BASE.format(prompt=encoded, seed=seed)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status == 200:
                    return await resp.read()
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
    return await generate_image(prompt, seed=telegram_id % 10000)
