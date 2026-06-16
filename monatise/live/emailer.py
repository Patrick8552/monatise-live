from __future__ import annotations

import os
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage

from monatise.live.secrets import secret_value


class EmailDeliveryError(RuntimeError):
    pass


@dataclass(frozen=True)
class SmtpSettings:
    host: str
    port: int
    sender: str
    username: str
    password: str
    use_ssl: bool
    use_starttls: bool
    provider: str
    stream: str


def send_password_reset_code(to_email: str, code: str, *, expires_minutes: int = 10) -> None:
    message = EmailMessage()
    message["From"] = smtp_settings().sender
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
    send_email(message)


def send_trading_alert_email(alert: dict) -> int:
    recipients = _alert_recipients()
    if not recipients:
        return 0
    symbol = str(alert.get("symbol") or "UNKNOWN")
    action = str(alert.get("action") or "WAIT")
    confidence = alert.get("confidence", 0)
    message = EmailMessage()
    message["From"] = smtp_settings().sender
    message["To"] = ", ".join(recipients)
    message["Subject"] = f"Monatise alert: {symbol} {action}"
    message.set_content(
        "\n".join(
            [
                f"Symbol: {symbol}",
                f"Action: {action}",
                f"Confidence: {confidence}",
                f"Timeframe: {alert.get('timeframe') or '--'}",
                f"Indicator: {alert.get('indicator') or 'TradingView'}",
                f"Price: {alert.get('price') or '--'}",
                "",
                str(alert.get("message") or "Monatise trading alert received."),
            ]
        )
    )
    send_email(message)
    return len(recipients)


def send_email(message: EmailMessage) -> None:
    settings = smtp_settings()
    _apply_provider_headers(message, settings)

    try:
        if settings.use_ssl:
            with smtplib.SMTP_SSL(settings.host, settings.port, context=ssl.create_default_context(), timeout=15) as smtp:
                _login_if_configured(smtp, settings.username, settings.password)
                smtp.send_message(message)
            return

        with smtplib.SMTP(settings.host, settings.port, timeout=15) as smtp:
            if settings.use_starttls:
                smtp.starttls(context=ssl.create_default_context())
            _login_if_configured(smtp, settings.username, settings.password)
            smtp.send_message(message)
    except (OSError, smtplib.SMTPException) as error:
        raise EmailDeliveryError("email could not be sent") from error


def smtp_settings() -> SmtpSettings:
    provider = secret_value("MONATISE_SMTP_PROVIDER", "").lower()
    host = secret_value("MONATISE_SMTP_HOST", "")
    port = int(secret_value("MONATISE_SMTP_PORT", "587"))
    username = secret_value("MONATISE_SMTP_USERNAME", "")
    password = secret_value("MONATISE_SMTP_PASSWORD", "")
    use_ssl = secret_value("MONATISE_SMTP_SSL", "").lower() == "true"
    use_starttls = secret_value("MONATISE_SMTP_STARTTLS", "true").lower() != "false"
    stream = secret_value("MONATISE_SMTP_STREAM", "")

    if provider == "resend":
        host = host or "smtp.resend.com"
        username = username or "resend"
        if "MONATISE_SMTP_PORT" not in os.environ:
            port = 587
        use_starttls = secret_value("MONATISE_SMTP_STARTTLS", "true").lower() != "false"
    elif provider == "postmark":
        host = host or "smtp.postmarkapp.com"
        if "MONATISE_SMTP_PORT" not in os.environ:
            port = 587
        use_starttls = secret_value("MONATISE_SMTP_STARTTLS", "true").lower() != "false"

    sender = secret_value("MONATISE_SMTP_FROM", "")
    if not host or not sender:
        raise EmailDeliveryError("email is not configured")
    return SmtpSettings(
        host=host,
        port=port,
        sender=sender,
        username=username,
        password=password,
        use_ssl=use_ssl,
        use_starttls=use_starttls,
        provider=provider,
        stream=stream,
    )


def expose_dev_reset_code() -> bool:
    return os.getenv("MONATISE_EXPOSE_DEV_RESET_CODE", "").lower() == "true"


def _apply_provider_headers(message: EmailMessage, settings: SmtpSettings) -> None:
    if settings.provider == "postmark":
        if settings.stream and "X-PM-Message-Stream" not in message:
            message["X-PM-Message-Stream"] = settings.stream
        if "X-PM-Tag" not in message:
            message["X-PM-Tag"] = "monatise"
    elif settings.provider == "resend" and "X-Entity-Ref-ID" not in message:
        message["X-Entity-Ref-ID"] = f"monatise-{os.urandom(8).hex()}"


def _alert_recipients() -> list[str]:
    raw = secret_value("MONATISE_ALERT_EMAILS", "")
    return [email.strip() for email in raw.split(",") if email.strip()]


def _login_if_configured(smtp: smtplib.SMTP, username: str, password: str) -> None:
    if username or password:
        smtp.login(username, password)
