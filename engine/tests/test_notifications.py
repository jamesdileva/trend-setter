"""Email notification service tests (Sprint 15).

The SMTP transport is stubbed out; credentials go through an in-memory
secret store so nothing real is sent or stored. The rate limiter uses an
injectable clock so tests do not sleep.
"""

from datetime import UTC, datetime, timedelta
from email.message import EmailMessage

import pytest

from trendbot.database import Database, upgrade_to_head
from trendbot.notifications import (
    EmailSettings,
    NotificationConfigError,
    NotificationService,
)
from trendbot.security.secret_store import InMemorySecretStore


@pytest.fixture()
def db(tmp_path):
    database = Database(tmp_path / "notifications.db")
    upgrade_to_head(database)
    return database


class RecordingSender:
    def __init__(self) -> None:
        self.sent: list[EmailMessage] = []
        self.error: Exception | None = None

    def __call__(self, settings: EmailSettings, message: EmailMessage) -> None:
        if self.error is not None:
            raise self.error
        self.sent.append(message)


class FixedClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, minutes: int) -> None:
        self.now = self.now + timedelta(minutes=minutes)


@pytest.fixture()
def sender() -> RecordingSender:
    return RecordingSender()


@pytest.fixture()
def clock() -> FixedClock:
    return FixedClock()


def make_service(db, sender: RecordingSender, clock: FixedClock) -> NotificationService:
    return NotificationService(db, InMemorySecretStore(), sender=sender, clock=clock)


def valid_settings(**overrides) -> EmailSettings:
    values = dict(
        enabled=True,
        smtp_host="smtp.example.com",
        smtp_port=465,
        security="ssl",
        username="alerter@example.com",
        recipient="me@example.com",
        password="app-password-1",
    )
    values.update(overrides)
    return EmailSettings(**values)


class TestSettings:
    def test_save_and_load_roundtrip_without_password(self, db, sender, clock):
        service = make_service(db, sender, clock)
        service.save_settings(valid_settings())
        settings = service.load_settings()
        assert settings.enabled is True
        assert settings.smtp_host == "smtp.example.com"
        assert settings.recipient == "me@example.com"
        assert settings.password is None  # never part of stored settings

    def test_password_lives_in_secret_store_not_database(self, db, sender, clock):
        store = InMemorySecretStore()
        service = NotificationService(db, store, sender=sender, clock=clock)
        service.save_settings(valid_settings())
        assert store.get_secret("notifications.smtp_password") == "app-password-1"
        # The settings JSON must not contain the password.
        from trendbot.database.repositories import SettingsRepository

        raw = SettingsRepository(db).get("notifications_email")
        assert raw is not None and "app-password-1" not in raw

    def test_enabled_without_password_is_rejected(self, db, sender, clock):
        service = make_service(db, sender, clock)
        with pytest.raises(NotificationConfigError):
            service.save_settings(valid_settings(password=None))

    def test_invalid_recipient_rejected(self, db, sender, clock):
        service = make_service(db, sender, clock)
        with pytest.raises(NotificationConfigError):
            service.save_settings(valid_settings(recipient="not-an-email"))

    def test_disabled_settings_need_no_host_or_password(self, db, sender, clock):
        service = make_service(db, sender, clock)
        stored = service.save_settings(EmailSettings())  # everything default/off
        assert stored.enabled is False

    def test_omitted_password_keeps_stored_one(self, db, sender, clock):
        service = make_service(db, sender, clock)
        service.save_settings(valid_settings())
        service.save_settings(valid_settings(password=None))
        assert service.has_password() is True


class TestFillNotifications:
    def test_order_filled_sends_plain_language_email(self, db, sender, clock):
        service = make_service(db, sender, clock)
        service.save_settings(valid_settings())
        service.order_filled(
            mode="paper",
            side="buy",
            product_id="BTC-USD",
            base_size="2.5",
            price="201",
            fee="5.025",
            cash_after="492.475",
        )
        assert len(sender.sent) == 1
        message = sender.sent[0]
        assert message["To"] == "me@example.com"
        assert "BUY" in message["Subject"]
        body = message.get_content()
        assert "simulated paper trade" in body
        assert "201" in body and "5.025" in body

    def test_disabled_settings_send_nothing(self, db, sender, clock):
        service = make_service(db, sender, clock)
        service.save_settings(EmailSettings())  # disabled
        service.order_filled(
            mode="paper", side="buy", product_id="BTC-USD",
            base_size="1", price="1", fee="0", cash_after="999",
        )
        assert sender.sent == []

    def test_send_failure_is_swallowed_and_logged(self, db, sender, clock):
        sender.error = RuntimeError("connection refused")
        service = make_service(db, sender, clock)
        service.save_settings(valid_settings())
        # Must not raise even though the sender fails.
        service.order_filled(
            mode="paper", side="sell", product_id="BTC-USD",
            base_size="1", price="1", fee="0", cash_after="999",
        )


class TestProblemRateLimit:
    def test_same_problem_key_is_cooldown_limited(self, db, sender, clock):
        service = make_service(db, sender, clock)
        service.save_settings(valid_settings())
        service.problem("ws_disconnected", "feed dropped")
        service.problem("ws_disconnected", "feed dropped again")
        assert len(sender.sent) == 1  # 30-minute cooldown swallowed the second

    def test_cooldown_expiry_allows_next_alert(self, db, sender, clock):
        service = make_service(db, sender, clock)
        service.save_settings(valid_settings())
        service.problem("ws_disconnected", "first")
        clock.advance(31)
        service.problem("ws_disconnected", "second")
        assert len(sender.sent) == 2

    def test_different_keys_independent(self, db, sender, clock):
        service = make_service(db, sender, clock)
        service.save_settings(valid_settings())
        service.problem("ws_disconnected", "feed")
        service.problem("paper_loop_error", "loop")
        assert len(sender.sent) == 2

    def test_hourly_cap(self, db, sender, clock, monkeypatch):
        # With the normal 30-minute cooldown the cap is unreachable, so
        # shrink the cooldown to exercise the hourly ceiling directly.
        import trendbot.notifications as notifications

        monkeypatch.setattr(notifications, "PROBLEM_COOLDOWN", timedelta(0))
        service = make_service(db, sender, clock)
        service.save_settings(valid_settings())
        for _ in range(6):
            service.problem("ws_disconnected", "again")
        assert len(sender.sent) == 5  # hourly limit


class TestSendTest:
    def test_requires_password(self, db, sender, clock):
        store = InMemorySecretStore()
        service = NotificationService(db, store, sender=sender, clock=clock)
        service.save_settings(valid_settings())
        store.delete_secret("notifications.smtp_password")
        with pytest.raises(NotificationConfigError):
            service.send_test()

    def test_sends_when_configured(self, db, sender, clock):
        service = make_service(db, sender, clock)
        service.save_settings(valid_settings())
        service.send_test()
        assert len(sender.sent) == 1
        assert "test" in sender.sent[0]["Subject"].lower()


class TestPlainLanguageErrors:
    def test_dns_failure_maps_to_plain_message(self, db, sender, clock, monkeypatch):
        import socket

        import trendbot.notifications as notifications

        def refuse(*args, **kwargs):
            raise socket.gaierror()

        monkeypatch.setattr(notifications.smtplib, "SMTP_SSL", refuse)
        monkeypatch.setattr(notifications.smtplib, "SMTP", refuse)
        service = NotificationService(db, InMemorySecretStore(), clock=clock)
        service.save_settings(valid_settings())
        with pytest.raises(NotificationConfigError, match="Could not reach the email server"):
            service.send_test()
