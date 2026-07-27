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


def test_feedback_email_uses_monatise_contact_by_default(monkeypatch) -> None:
    sent = []
    monkeypatch.setenv("MONATISE_SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("MONATISE_SMTP_FROM", "Monatise <no-reply@example.com>")
    monkeypatch.delenv("MONATISE_FEEDBACK_EMAIL", raising=False)
    monkeypatch.setattr(emailer, "send_email", sent.append)

    recipient = emailer.send_feedback_email(
        feedback_id=42,
        rating=4,
        category="idea",
        message_text="Make the dashboard easier to scan.",
        page="/coinglass-dashboard.html",
        username="trader@example.com",
    )

    assert recipient == "monatiseaesthetics@gmail.com"
    assert len(sent) == 1
    assert sent[0]["To"] == "monatiseaesthetics@gmail.com"
    assert sent[0]["Subject"] == "Monatise feedback #42: 4/5 Idea"
    assert "Make the dashboard easier to scan." in sent[0].get_content()
    assert "trader@example.com" in sent[0].get_content()


def test_safe_error_detail_redacts_credentials() -> None:
    settings = emailer.SmtpSettings(
        host="smtp.resend.com",
        port=587,
        sender="Monatise <onboarding@resend.dev>",
        username="resend",
        password="re_secret",
        use_ssl=False,
        use_starttls=True,
        provider="resend",
        stream="",
    )

    detail = emailer._safe_error_detail(RuntimeError("auth failed for resend using re_secret"), settings)

    assert "re_secret" not in detail
    assert "resend" not in detail
    assert "[redacted]" in detail
