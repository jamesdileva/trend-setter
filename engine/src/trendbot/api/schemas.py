"""Request schemas for the local API."""

from __future__ import annotations

from pydantic import BaseModel, Field


class CredentialRequest(BaseModel):
    """A Coinbase credential as submitted by the connection wizard."""

    key_name: str = Field(
        min_length=1,
        max_length=256,
        description="The CDP key name, e.g. organizations/{org_id}/apiKeys/{key_id}",
    )
    private_key_pem: str = Field(
        min_length=1,
        max_length=20000,
        description="ECDSA (ES256) private key PEM. Never stored outside the OS secret store.",
    )
