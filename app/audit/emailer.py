"""SMTP emailer for prompt-quality training notices (logs when SMTP unset)."""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from typing import List, Optional

from app.config import get_settings

logger = logging.getLogger(__name__)


def send_email(*, to: str, subject: str, body: str) -> bool:
    """Send via SMTP when configured; otherwise log the body (dev-safe)."""
    settings = get_settings()
    host = (settings.smtp_host or "").strip()
    if not host:
        logger.info(
            "SMTP unset — training email to=%s subject=%s\n%s",
            to,
            subject,
            body,
        )
        return False

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from or "helpdesk@ampcus.com"
    msg["To"] = to
    msg.set_content(body)

    try:
        with smtplib.SMTP(host, int(settings.smtp_port or 587), timeout=20) as smtp:
            smtp.starttls()
            if settings.smtp_user:
                smtp.login(settings.smtp_user, settings.smtp_password or "")
            smtp.send_message(msg)
        logger.info("Sent training email to=%s", to)
        return True
    except Exception as exc:
        logger.warning("SMTP send failed to=%s: %s — logging body instead", to, exc)
        logger.info("Email body:\n%s", body)
        return False


def build_training_email(
    *,
    user_email: str,
    bad_queries: List[dict],
    training_url: str,
) -> tuple[str, str]:
    lines = [
        f"Hello,",
        "",
        "Your recent Ampcus Helpdesk prompts scored below our quality threshold.",
        "Please complete a short training module to keep unrestricted access:",
        "",
        training_url,
        "",
        "Examples from your recent queries:",
        "",
    ]
    for i, q in enumerate(bad_queries[:5], 1):
        issues = q.get("issues") or []
        issue_txt = "; ".join(str(x) for x in issues) if issues else "needs clarity"
        lines.append(f"{i}. Score {q.get('score')}: {q.get('query')}")
        lines.append(f"   Issues: {issue_txt}")
        if q.get("improved_query"):
            lines.append(f"   Try: {q.get('improved_query')}")
        lines.append("")
    lines.extend(
        [
            "After you finish the training page, click “Mark complete” to restore full access.",
            "",
            "— Ampcus Helpdesk",
        ]
    )
    return (
        "Ampcus Helpdesk — prompt quality training required",
        "\n".join(lines),
    )
