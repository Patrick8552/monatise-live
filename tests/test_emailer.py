from __future__ import annotations

from email.message import EmailMessage

from monatise.live import emailer


def test_resend_smtp_defaults(monkeypatch) -> None:
    monkeypatch.setenv("MONATISE_SMTP_PROVIDER", "resend")
    monkeypatch.setenv("MONATISE_SMTP_FROM", "Monatise <no-reply@example.com>")
    monkeypatch.setenv("MONATISE_SMTP_PASSWORD", "re_test")
    monkeypatch.delenv("MONATISE_SMTP_HOST", raising=False)
    monkeypatch.delenv("MONATISE_SMTP_USERNAME", raising=False)
    monkeypatch.delenv("MONATISE_SMTP_PORT", raising=False)

    settings = emailer.smtp_settings()

    assert settings.host == "smtp.resend.com"
    assert settings.port == 587
    assert settings.username == "resend"
    assert settings.password == "re_test"
    assert settings.use_starttls is True


def test_postmark_smtp_defaults_and_stream_header(monkeypatch) -> None:
    monkeypatch.setenv("MONATISE_SMTP_PROVIDER", "postmark")
    monkeypatch.setenv("MONATISE_SMTP_FROM", "Monatise <no-reply@example.com>")
    monkeypatch.setenv("MONATISE_SMTP_USERNAME", "server-token")
    monkeypatch.setenv("MONATISE_SMTP_PASSWORD", "server-token")
    monkeypatch.setenv("MONATISE_SMTP_STREAM", "outbound")
    monkeypatch.delenv("MONATISE_SMTP_HOST", raising=False)
    monkeypatch.delenv("MONATISE_SMTP_PORT", raising=False)

    settings = emailer.smtp_settings()
    message = EmailMessage()
    emailer._apply_provider_headers(message, settings)

    assert settings.host == "smtp.postmarkapp.com"
    assert settings.port == 587
    assert message["X-PM-Message-Stream"] == "outbound"
    assert message["X-PM-Tag"] == "monatise"


def test_alert_recipients_parse_comma_list(monkeypatch) -> None:
    monkeypatch.setenv("MONATISE_ALERT_EMAILS", "ops@example.com, trader@example.com,, ")

    assert emailer._alert_recipients() == ["ops@example.com", "trader@example.com"]
