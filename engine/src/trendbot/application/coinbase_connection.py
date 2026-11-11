"""Connection service: secure Coinbase credential lifecycle (Sprint 3).

Coordinates the secret store (OS credential manager) and the
``credential_metadata`` table (reference and status only — never key
material). One active credential per provider; connecting replaces any
previous one.

The result classifications carry plain-language messages that the wizard
shows verbatim (implementation.md §16). This layer never logs and never
returns secret material.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import delete, select
from sqlalchemy.engine import CursorResult

from trendbot.database.models import CredentialMetadata
from trendbot.database.session import Database
from trendbot.exchange.coinbase_rest import (
    CoinbaseRestClient,
    CoinbaseValidationError,
)
from trendbot.security.secret_store import SecretStore

PROVIDER = "coinbase"
SECRET_KEY = "coinbase:advanced-trade-primary"


@dataclass(frozen=True)
class ConnectionResult:
    """Outcome of connect/retest for the API layer."""

    ok: bool
    permissions: str | None = None
    trade_access: bool | None = None
    error_kind: str | None = None
    message: str | None = None


@dataclass(frozen=True)
class ConnectionStatus:
    """Non-secret connection summary for the UI and diagnostics."""

    connected: bool
    key_reference: str | None = None
    permissions: str | None = None
    last_validated_at: str | None = None


class CoinbaseConnectionService:
    """Owns connect/status/retest/disconnect for the Coinbase provider."""

    def __init__(
        self,
        database: Database,
        secret_store: SecretStore,
        client_factory: Callable[[str, str], CoinbaseRestClient],
    ) -> None:
        self._db = database
        self._secrets = secret_store
        self._client_factory = client_factory

    def connect(self, key_name: str, private_key_pem: str) -> ConnectionResult:
        """Validate and store a new credential, replacing any previous one."""
        client = self._client_factory(key_name, private_key_pem)
        try:
            client.validate_credentials()
        except CoinbaseValidationError as exc:
            self._record_metadata(key_name, status=str(exc.kind))
            return ConnectionResult(ok=False, error_kind=exc.kind, message=exc.message)

        trade_access = client.detect_trade_permission()
        permissions = "view" if trade_access is not True else "view+trade"

        # Only store the secret once validation passed; the OS store holds
        # the key material — never SQLite, never logs.
        self._secrets.set_secret(SECRET_KEY, private_key_pem)
        self._record_metadata(key_name, status="valid", permissions=permissions)
        return ConnectionResult(
            ok=True,
            permissions=permissions,
            trade_access=trade_access,
        )

    def status(self) -> ConnectionStatus:
        """Current non-secret connection summary."""
        metadata = self._active_metadata()
        if metadata is None:
            return ConnectionStatus(connected=False)
        stored = self._secrets.get_secret(SECRET_KEY) is not None
        return ConnectionStatus(
            connected=stored and metadata.status == "valid",
            key_reference=metadata.key_reference,
            permissions=metadata.permissions,
            last_validated_at=_iso(metadata.last_validated_at),
        )

    def retest(self) -> ConnectionResult:
        """Re-validate the stored credential against Coinbase."""
        private_key = self._secrets.get_secret(SECRET_KEY)
        metadata = self._active_metadata()
        if private_key is None or metadata is None:
            return ConnectionResult(
                ok=False,
                error_kind="not_connected",
                message=(
                    "Coinbase is not connected yet. Paper and backtest modes work "
                    "without connecting."
                ),
            )
        client = self._client_factory(metadata.key_reference, private_key)
        try:
            client.validate_credentials()
        except CoinbaseValidationError as exc:
            self._record_metadata(metadata.key_reference, status=str(exc.kind))
            return ConnectionResult(ok=False, error_kind=exc.kind, message=exc.message)
        trade_access = client.detect_trade_permission()
        permissions = "view" if trade_access is not True else "view+trade"
        self._record_metadata(metadata.key_reference, status="valid", permissions=permissions)
        return ConnectionResult(ok=True, permissions=permissions, trade_access=trade_access)

    def disconnect(self) -> bool:
        """Remove the stored secret and the credential reference."""
        removed_secret = self._secrets.delete_secret(SECRET_KEY)
        with self._db.session() as session:
            deleted = cast(
                "CursorResult[Any]",
                session.execute(
                    delete(CredentialMetadata).where(CredentialMetadata.provider == PROVIDER)
                ),
            ).rowcount
        return removed_secret or int(deleted or 0) > 0

    def _active_metadata(self) -> CredentialMetadata | None:
        with self._db.session() as session:
            return session.scalars(
                select(CredentialMetadata)
                .where(CredentialMetadata.provider == PROVIDER)
                .order_by(CredentialMetadata.updated_at.desc())
                .limit(1)
            ).first()

    def _record_metadata(
        self, key_name: str, *, status: str, permissions: str | None = None
    ) -> None:
        now = datetime.now(UTC)
        validated = now if status == "valid" else None
        with self._db.session() as session:
            session.execute(
                delete(CredentialMetadata).where(CredentialMetadata.provider == PROVIDER)
            )
            session.add(
                CredentialMetadata(
                    provider=PROVIDER,
                    key_reference=key_name,
                    status=status,
                    permissions=permissions,
                    last_validated_at=validated,
                )
            )


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.strftime("%Y-%m-%dT%H:%M:%SZ")


def default_client_factory(transport: Any = None) -> Callable[[str, str], CoinbaseRestClient]:
    """Build a client factory for the real Coinbase REST API."""

    def factory(key_name: str, private_key_pem: str) -> CoinbaseRestClient:
        return CoinbaseRestClient(
            key_name=key_name,
            private_key_pem=private_key_pem,
            transport=transport,
        )

    return factory
