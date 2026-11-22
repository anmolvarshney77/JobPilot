from __future__ import annotations

import logging

from jobpilot.config import Settings
from jobpilot.notify.smtp_sender import send_email
from jobpilot.notify.telegram_sender import send_telegram

logger = logging.getLogger(__name__)


def send_digest(text: str, settings: Settings) -> tuple[bool, str]:
    """Try Telegram first, fall back to SMTP. Never raises."""
    if settings.telegram_bot_token and settings.telegram_chat_id:
        try:
            ok = send_telegram(text, settings.telegram_bot_token, settings.telegram_chat_id)
            if ok:
                return True, "telegram"
        except Exception as exc:
            logger.error("Telegram digest failed: %s", exc)

    if settings.smtp_host and settings.smtp_to:
        try:
            ok = send_email("JobPilot Daily Digest", text, settings)
            if ok:
                return True, "smtp"
        except Exception as exc:
            logger.error("SMTP digest failed: %s", exc)

    if not settings.telegram_bot_token and not settings.smtp_host:
        logger.info("No notification channels configured; digest skipped.")
        return True, "none"

    logger.error("All notification channels failed.")
    return False, "both_failed"
