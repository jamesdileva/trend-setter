"""ES256 JWT construction for Coinbase Advanced Trade (verified Sprint 0).

Every fact here is pinned to the official documentation recorded in
``docs/coinbase-verification-checklist.md`` (item 1):

- signing: ES256 (ECDSA P-256) with an EC PEM private key (SEC1/RFC5915
  format); Ed25519 is not supported by Coinbase App APIs;
- header: ``kid`` = the CDP key name, plus a random hex ``nonce``;
- claims: ``sub`` = key name, ``iss`` = "cdp", ``nbf`` = now,
  ``exp`` = nbf + 120 seconds (JWTs expire after 2 minutes);
- REST-only ``uri`` claim: ``"{METHOD} {host}{path}"`` (include any UUID
  in the path); WebSocket JWTs carry no ``uri``.

A fresh JWT is required per REST request and per WebSocket message.
"""

from __future__ import annotations

import secrets as pysecrets
from datetime import UTC, datetime

import jwt

JWT_LIFETIME_SECONDS = 120
ISSUER = "cdp"

PEM_HEADER = "-----BEGIN EC PRIVATE " + "KEY-----"
PEM_FOOTER = "-----END EC PRIVATE " + "KEY-----"


class JwtBuildError(ValueError):
    """The key material is unusable for ES256 signing."""


def _issued_at(now: datetime | None) -> int:
    timestamp = (now or datetime.now(UTC)).timestamp()
    return int(timestamp)


def normalize_pem(raw: str) -> str:
    """Fix common copy-paste issues with PEM keys.

    CDP key files store the key as a JSON string where newlines are
    literal backslash-n sequences. Windows editors may add CRLF. Users
    often paste surrounding quotes or extra whitespace. This function
    normalizes all of those so PyJWT can parse the key.
    """
    text = raw.strip().strip('"').strip("'")
    # JSON-escaped newlines: literal backslash followed by n → actual newline
    text = text.replace("\\n", "\n")
    # CRLF → LF
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Strip whitespace around each line, drop empties
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    return "\n".join(lines)


def _encode(claims: dict[str, object], key_name: str, private_key_pem: str) -> str:
    headers = {"kid": key_name, "nonce": pysecrets.token_hex(16)}
    try:
        return jwt.encode(claims, private_key_pem, algorithm="ES256", headers=headers)
    except Exception as exc:
        raise JwtBuildError(
            "The private key could not be used for ES256 signing. Coinbase requires "
            "an ECDSA (ES256) key — the portal defaults to Ed25519, which does not "
            "work here."
        ) from exc


def build_rest_jwt(
    key_name: str,
    private_key_pem: str,
    *,
    method: str,
    host: str,
    path: str,
    now: datetime | None = None,
) -> str:
    """Build a one-request REST JWT with the ``uri`` claim."""
    issued = _issued_at(now)
    claims: dict[str, object] = {
        "sub": key_name,
        "iss": ISSUER,
        "nbf": issued,
        "exp": issued + JWT_LIFETIME_SECONDS,
        "uri": f"{method} {host}{path}",
    }
    return _encode(claims, key_name, normalize_pem(private_key_pem))


def build_websocket_jwt(key_name: str, private_key_pem: str, *, now: datetime | None = None) -> str:
    """Build a per-message WebSocket JWT (no ``uri`` claim)."""
    issued = _issued_at(now)
    claims: dict[str, object] = {
        "sub": key_name,
        "iss": ISSUER,
        "nbf": issued,
        "exp": issued + JWT_LIFETIME_SECONDS,
    }
    return _encode(claims, key_name, normalize_pem(private_key_pem))
