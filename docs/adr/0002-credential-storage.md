# 2. Credential storage: Windows Credential Manager via the keyring library

- **Status:** Accepted
- **Date:** 2026-11-11

## Context

Sprint 3 requires storing the Coinbase private key securely. `implementation.md` §12 mandates a platform-neutral `SecretStore` interface and says the Windows implementation should use Credential Manager **or** DPAPI-backed storage, selecting one "after a small prototype verifies packaging and recovery behavior". Requirements: user-scope storage, no plaintext on disk under the app's control, simple delete on disconnect, and no new heavyweight dependencies (architecture.md §4: keep the stack small).

## Decision

We adopt **Windows Credential Manager, accessed through the `keyring` Python library**, as the Windows `SecretStore` implementation:

- `keyring` is a maintained, pure-Python wrapper over the Windows Credential Manager API (no native build steps; PyInstaller-friendly).
- Secrets are stored per Windows user (`service = "trend-setter"`), satisfying the least-privilege and user-scope rules in architecture.md §17–18.
- A platform-neutral `SecretStore` interface (`set_secret`/`get_secret`/`delete_secret`) keeps the choice swappable; a `InMemorySecretStore` serves tests and non-Windows development until the VPS phases need a Linux implementation (vps-deployment.md §8).

DPAPI-file encryption remains the documented fallback if Credential Manager proves problematic in installer testing (e.g. roaming-profile quirks); switching costs one class.

## Consequences

- No private key material ever touches SQLite, config files, or logs — `credential_metadata` stores only a non-secret reference (architecture.md §14).
- Deleting a credential on disconnect is a single store call plus a metadata row delete.
- A reset Windows user profile loses stored credentials; the wizard's replace-key flow recovers (documented in §12 follow-ups).
- `keyring` joins the runtime dependency set; the Windows implementation imports it lazily so Linux CI/tests never load a Windows backend.
- Real-key behavior (store, read after reboot, recovery after profile reset) is verified manually by the user with their own Coinbase account — automated tests only cover the in-memory store and the interfaces.
