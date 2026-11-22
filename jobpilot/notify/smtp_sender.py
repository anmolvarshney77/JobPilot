from __future__ import annotations

import logging
import smtplib
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)


def send_email(subject: str, body: str, settings: object) -> bool:
    """Send plaintext email via smtplib. Never raises."""
    try:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = settings.smtp_from  # type: ignore[attr-defined]
        msg["To"] = settings.smtp_to  # type: ignore[attr-defined]

        port = settings.smtp_port  # type: ignore[attr-defined]
        host = settings.smtp_host  # type: ignore[attr-defined]

        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=15) as server:
                if settings.smtp_user:  # type: ignore[attr-defined]
                    server.login(settings.smtp_user, settings.smtp_password)  # type: ignore[attr-defined]
                server.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=15) as server:
                server.ehlo()
                if port == 587:
                    server.starttls()
                    server.ehlo()
                if settings.smtp_user:  # type: ignore[attr-defined]
                    server.login(settings.smtp_user, settings.smtp_password)  # type: ignore[attr-defined]
                server.send_message(msg)
        return True
    except Exception as exc:
        logger.error("SMTP send failed: %s", exc)
        return False
