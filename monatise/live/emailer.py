from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage

from monatise.live.secrets import secret_value


class EmailDeliveryError(RuntimeError):
    pass


def send_password_reset_code(to_email: str, code: str, *, expires_minutes: int = 10) -> None:
    host = secret_value("MONATISE_SMTP_HOST", "")
    sender = secret_value("MONATISE_SMTP_FROM", "")
    if not host or not sender:
        raise EmailDeliveryError("password reset email is not configured")

    port = int(secret_value("MONATISE_SMTP_PORT", "587"))
    username = secret_value("MONATISE_SMTP_USERNAME", "")
    password = secret_value("MONATISE_SMTP_PASSWORD", "")
    use_ssl = secret_value("MONATISE_SMTP_SSL", "").lower() == "true"
    use_starttls = secret_value("MONATISE_SMTP_STARTTLS", "true").lower() != "false"

    message = EmailMessage()
    message["From"] = sender
    message["To"] = to_email
    message["Subject"] = "Your Monatise password reset code"
    message.set_content(
        "\n".join(
            [
                "Use this code to reset your Monatise password:",
                "",
                code,
                "",
                f"This code expires in {expires_minutes} minutes.",
                "If you did not request this, you can ignore this email.",
            ]
        )
    )

    try:
        if use_ssl:
            with smtplib.SMTP_SSL(host, port, context=ssl.create_default_context(), timeout=15) as smtp:
                _login_if_configured(smtp, username, password)
                smtp.send_message(message)
            return

        with smtplib.SMTP(host, port, timeout=15) as smtp:
            if use_starttls:
                smtp.starttls(context=ssl.create_default_context())
            _login_if_configured(smtp, username, password)
            smtp.send_message(message)
    except (OSError, smtplib.SMTPException) as error:
        raise EmailDeliveryError("password reset email could not be sent") from error


def expose_dev_reset_code() -> bool:
    return os.getenv("MONATISE_EXPOSE_DEV_RESET_CODE", "").lower() == "true"


def _login_if_configured(smtp: smtplib.SMTP, username: str, password: str) -> None:
    if username or password:
        smtp.login(username, password)
