"""Email notifications for trading actions and engine problems.

Design rules (this sprint's doc; architecture.md §14 for secrets):

- SMTP credentials live only in the OS credential store via ``SecretStore``;
  non-secret settings live in ``app_settings`` as JSON. The password is never
  returned by any API or logged.
- ``order_filled`` emails are always sent (fills are rare by design).
- ``problem`` emails are rate-limited: the same problem key is sent at most
  once per 30 minutes and at most 5 times per hour, so a flaky network
  cannot flood the inbox.
- Every send is best-effort: failures are logged as engine events and never
  propagate into trading code.
"""

from __future__ import annotations

import json
import smtplib
import socket
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage

from trendbot.database.repositories import EngineEventRepository, SettingsRepository
from trendbot.database.session import Database
from trendbot.security.secret_store import SecretStore

SETTINGS_KEY = "notifications_email"
PASSWORD_SECRET_KEY = "notifications.smtp_password"
PROBLEM_COOLDOWN = timedelta(minutes=30)
PROBLEM_HOURLY_LIMIT = 5
SMTP_TIMEOUT_SECONDS = 15
VALID_SECURITY = ("ssl", "starttls")


class NotificationConfigError(ValueError):
    """Raised for invalid notification settings; message is plain-language."""


@dataclass(frozen=True)
class EmailSettings:
    enabled: bool = False
    smtp_host: str = ""
    smtp_port: int = 465
    security: str = "ssl"
    username: str = ""
    recipient: str = ""
    # Never persisted in app_settings; lives in the OS credential store.
    password: str | None = None


def _validate(settings: EmailSettings) -> None:
    if not settings.enabled:
        return
    if not settings.smtp_host.strip():
        raise NotificationConfigError("Choose an email server (SMTP host) first.")
    if settings.security not in VALID_SECURITY:
        raise NotificationConfigError("Security must be either ssl or starttls.")
    if not 1 <= settings.smtp_port <= 65535:
        raise NotificationConfigError("The SMTP port must be between 1 and 65535.")
    if "@" not in settings.recipient or settings.recipient.strip().startswith("@"):
        raise NotificationConfigError("Enter a valid destination email address.")


class NotificationService:
    """Sends plain-language notification emails; never raises to callers."""

    def __init__(
        self,
        database: Database,
        secret_store: SecretStore,
        *,
        sender: Callable[[EmailSettings, EmailMessage], None] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._settings = SettingsRepository(database)
        self._events = EngineEventRepository(database)
        self._secret_store = secret_store
        self._sender = sender or _smtp_send
        self._clock = clock or (lambda: datetime.now(UTC))
        self._problem_sends: dict[str, deque[datetime]] = {}

    # -- settings ------------------------------------------------------

    def load_settings(self) -> EmailSettings:
        raw = self._settings.get(SETTINGS_KEY)
        if not raw:
            return EmailSettings()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return EmailSettings()
        known = {k: data[k] for k in EmailSettings.__annotations__ if k in data and k != "password"}
        return EmailSettings(**known)

    def save_settings(self, settings: EmailSettings) -> EmailSettings:
        """Persist settings. ``password=None`` keeps the stored password."""
        current_password = self._secret_store.get_secret(PASSWORD_SECRET_KEY)
        if settings.password:
            self._secret_store.set_secret(PASSWORD_SECRET_KEY, settings.password)
        elif settings.enabled and not current_password:
            raise NotificationConfigError(
                "Enter the email account's app-password — the saved one is empty."
            )
        _validate(replace(settings, password=None))
        stored = replace(settings, password=None)
        payload = {k: getattr(stored, k) for k in EmailSettings.__annotations__ if k != "password"}
        self._settings.set(SETTINGS_KEY, json.dumps(payload))
        return stored

    def has_password(self) -> bool:
        return bool(self._secret_store.get_secret(PASSWORD_SECRET_KEY))

    # -- notifications -------------------------------------------------

    def order_filled(
        self,
        *,
        mode: str,
        side: str,
        product_id: str,
        base_size: str,
        price: str,
        fee: str,
        cash_after: str,
    ) -> None:
        subject = f"trend-setter: {side.upper()} filled ({mode} mode)"
        body = (
            f"A {side.upper()} order filled in {mode} mode.\n\n"
            f"Product: {product_id}\n"
            f"Size: {base_size}\n"
            f"Fill price: ${price}\n"
            f"Fee: ${fee}\n"
            f"Cash left: ${cash_after}\n\n"
            + (
                "This was a simulated paper trade — no real money moved."
                if mode == "paper"
                else "This was a LIVE trade with real funds."
            )
        )
        self._try_send(subject, body, problem_key=None)

    def problem(self, key: str, message: str) -> None:
        """Rate-limited engine-problem alert (same key: 1 per 30 min, 5/hour)."""
        now = self._clock()
        sends = self._problem_sends.setdefault(key, deque())
        while sends and now - sends[0] > timedelta(hours=1):
            sends.popleft()
        if sends and now - sends[-1] < PROBLEM_COOLDOWN:
            return
        if len(sends) >= PROBLEM_HOURLY_LIMIT:
            return
        sends.append(now)
        self._try_send(
            f"trend-setter problem: {key}", f"{message}\n\n(This alert is rate-limited.)",
            problem_key=None,
        )

    def send_test(self) -> None:
        """Send a test email. Raises NotificationConfigError/sending errors with
        plain-language messages so the API can show them to the user."""
        settings = self.load_settings()
        if not settings.smtp_host:
            raise NotificationConfigError(
                "Save the email settings first — there is no server to test yet."
            )
        if not settings.enabled:
            raise NotificationConfigError("Email notifications are turned off.")
        self._send_or_raise(
            "trend-setter test email",
            "This is a test email from trend-setter. If you can read this, "
            "trade and problem alerts will reach this address.",
            settings,
        )

    # -- internals -----------------------------------------------------

    def _try_send(self, subject: str, body: str, *, problem_key: str | None) -> None:
        try:
            settings = self.load_settings()
            if not settings.enabled or not settings.smtp_host:
                return
            self._send_or_raise(subject, body, settings)
        except Exception as exc:  # noqa: BLE001 - notifications never break trading
            self._record_failure(subject, exc)

    def _send_or_raise(self, subject: str, body: str, settings: EmailSettings) -> None:
        password = self._secret_store.get_secret(PASSWORD_SECRET_KEY)
        if not password:
            raise NotificationConfigError("No app-password saved for the email account.")
        effective = replace(settings, password=password)
        message = EmailMessage()
        message["From"] = settings.username or settings.recipient
        message["To"] = settings.recipient
        message["Subject"] = subject
        message.set_content(body)
        self._sender(effective, message)

    def _record_failure(self, subject: str, exc: Exception) -> None:
        try:
            self._events.append(
                event_type="notification_failed",
                component="notifications",
                message=f"Could not send '{subject}': {exc}",
            )
        except Exception:  # noqa: BLE001 - even event logging must not raise
            pass


def _smtp_send(settings: EmailSettings, message: EmailMessage) -> None:
    """Deliver one email over SMTP. Raises smtplib/OSError on failure."""
    host = settings.smtp_host.strip()
    port = settings.smtp_port
    try:
        if settings.security == "ssl":
            with smtplib.SMTP_SSL(host, port, timeout=SMTP_TIMEOUT_SECONDS) as server:
                server.login(settings.username, settings.password or "")
                server.send_message(message)
        else:
            with smtplib.SMTP(host, port, timeout=SMTP_TIMEOUT_SECONDS) as server:
                server.starttls()
                server.login(settings.username, settings.password or "")
                server.send_message(message)
    except smtplib.SMTPAuthenticationError as exc:
        raise NotificationConfigError(
            "The email server rejected the username or app-password. "
            "Check both, and make sure you use an app-password (not your normal password)."
        ) from exc
    except socket.gaierror as exc:
        raise NotificationConfigError(
            f"Could not reach the email server '{host}'. Check the server name spelling."
        ) from exc
    except TimeoutError as exc:
        raise NotificationConfigError(
            f"The email server '{host}' did not answer within {SMTP_TIMEOUT_SECONDS} seconds."
        ) from exc
