"""Operational alert emails, sent over SMTP with STARTTLS to the sending account itself.

Point ALERT_SMTP_HOST, ALERT_EMAIL_USER and ALERT_EMAIL_PASSWORD at a dedicated alert account
(for example a mail account with an app password), not your personal one.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage

from app.config import settings

logger = logging.getLogger(__name__)

SMTP_TIMEOUT_SECONDS = 20


def send_alert(subject: str, body: str) -> bool:
    """Send an alert email to the configured address; returns whether it was sent.

    Alerts are best-effort: when ALERT_SMTP_HOST, ALERT_EMAIL_USER or ALERT_EMAIL_PASSWORD is unset
    the alert is logged and skipped so the calling task still succeeds.
    """
    email_user = settings.alert_email_user
    email_password = settings.alert_email_password
    if not settings.alert_smtp_host or not email_user or not email_password:
        logger.warning("Alert email skipped (ALERT_SMTP_HOST/ALERT_EMAIL_USER/ALERT_EMAIL_PASSWORD unset): %s", subject)
        return False

    message = EmailMessage()
    message["From"] = email_user
    message["To"] = email_user
    message["Subject"] = subject
    message.set_content(body)

    with smtplib.SMTP(settings.alert_smtp_host, settings.alert_smtp_port, timeout=SMTP_TIMEOUT_SECONDS) as smtp:
        smtp.starttls(context=ssl.create_default_context())
        smtp.login(email_user, email_password)
        smtp.send_message(message)
    logger.info("Alert email sent: %s", subject)
    return True
