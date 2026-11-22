from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

MAX_TELEGRAM_LENGTH = 4096
_API_BASE = "https://api.telegram.org/bot{token}/sendMessage"


def send_telegram(text: str, bot_token: str, chat_id: str) -> bool:
    """POST to Telegram Bot API, splitting text into chunks if needed. Never raises."""
    import httpx

    url = _API_BASE.format(token=bot_token)
    chunks = _split(text, MAX_TELEGRAM_LENGTH)
    client = httpx.Client(timeout=15)
    try:
        for chunk in chunks:
            resp = client.post(url, json={"chat_id": chat_id, "text": chunk, "parse_mode": "Markdown"})
            if not resp.is_success:
                logger.error("Telegram API error %s: %s", resp.status_code, resp.text[:200])
                return False
        return True
    except Exception as exc:
        logger.error("Telegram send failed: %s", exc)
        return False
    finally:
        client.close()


def _split(text: str, max_len: int) -> list[str]:
    if len(text) <= max_len:
        return [text]
    chunks: list[str] = []
    while text:
        chunks.append(text[:max_len])
        text = text[max_len:]
    return chunks
