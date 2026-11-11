import { useCallback, useEffect, useState } from "react";
import type { CoinbaseStatus, EngineResponse } from "../types/electron";
import { getDesktopApi } from "../services/desktopApi";

/** Official Coinbase Developer Platform page for Secret API keys (Sprint 0 verified). */
const OFFICIAL_KEY_PAGE_URL = "https://portal.cdp.coinbase.com/api-keys/secret";

/** Format hint for the key textarea (split so it stays placeholder text only). */
const PEM_PLACEHOLDER = "-----BEGIN " + "EC PRIVATE KEY-----";

function shortKeyReference(reference: string | null): string {
  if (!reference) {
    return "";
  }
  return reference.length <= 40 ? reference : `…${reference.slice(-36)}`;
}

function permissionLabel(permissions: string | null): string {
  if (permissions === "view+trade") {
    return "View + trading detected";
  }
  if (permissions === "view") {
    return "View only";
  }
  return "Unknown";
}

function resultMessage(response: EngineResponse | null, fallback: string): { kind: "ok" | "error"; text: string } {
  const body = (response?.body ?? {}) as { status?: string; message?: string; permissions?: string | null };
  if (response?.status === 200) {
    const text =
      body.permissions === "view+trade"
        ? "Connected. Coinbase confirmed View access; trading permission was also detected. Live trading stays off until you deliberately arm it later."
        : "Connected. Coinbase confirmed View access for this key.";
    return { kind: "ok", text };
  }
  return { kind: "error", text: body.message ?? fallback };
}

export function ConnectionCard() {
  const api = getDesktopApi();
  const [status, setStatus] = useState<CoinbaseStatus | null>(null);
  const [keyName, setKeyName] = useState("");
  const [privateKey, setPrivateKey] = useState("");
  const [notice, setNotice] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!api) {
      return;
    }
    let cancelled = false;
    const refresh = (): void => {
      void api
        .getCoinbaseStatus()
        .then((response) => {
          if (!cancelled && response && typeof response.body === "object" && response.body !== null) {
            setStatus(response.body as CoinbaseStatus);
          }
        })
        .catch(() => undefined);
    };
    refresh();
    const timer = setInterval(refresh, 5000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [api]);

  const run = useCallback(
    async (action: () => Promise<EngineResponse | null>, fallback: string, onOk?: () => void) => {
      setBusy(true);
      setNotice(null);
      try {
        const response = await action();
        const result = resultMessage(response, fallback);
        setNotice(result);
        if (result.kind === "ok") {
          onOk?.();
        }
      } catch {
        setNotice({
          kind: "error",
          text: "The engine is not reachable yet. Wait for it to start, then try again.",
        });
      } finally {
        setBusy(false);
      }
    },
    [],
  );

  const handleConnect = (): void => {
    if (!keyName.trim() || !privateKey.trim()) {
      setNotice({ kind: "error", text: "Paste both the key name and the private key first." });
      return;
    }
    void run(
      () => api?.connectCoinbase(keyName.trim(), privateKey) ?? Promise.resolve(null),
      "The connection attempt failed. Try again.",
      () => {
        setKeyName("");
        setPrivateKey("");
      },
    );
  };

  const handleRetest = (): void => {
    void run(() => api?.testCoinbase() ?? Promise.resolve(null), "The connection test failed. Try again.");
  };

  const handleDisconnect = (): void => {
    void run(
      () => api?.disconnectCoinbase() ?? Promise.resolve(null),
      "Disconnecting failed. Try again.",
    );
  };

  const connected = status?.connected === true;

  return (
    <section className="card" aria-live="polite">
      <h2>Coinbase connection</h2>

      {connected ? (
        <>
          <p className="state state-running">Connected</p>
          <p className="meta">
            Key {shortKeyReference(status.key_reference)} · {permissionLabel(status.permissions)}
            {status.last_validated_at ? ` · Last checked ${status.last_validated_at}` : ""}
          </p>
          <div className="controls">
            <button type="button" onClick={handleRetest} disabled={busy}>
              Test connection
            </button>
            <button type="button" className="danger" onClick={handleDisconnect} disabled={busy}>
              Disconnect
            </button>
          </div>
        </>
      ) : (
        <>
          <p className="meta">
            Not connected. Paper trading and backtesting work without connecting — connecting is
            only needed to see your real balances or, much later, to trade live. This app can
            never withdraw or move funds: it never asks for the Transfer permission.
          </p>
          <ol className="wizard-steps">
            <li>
              On the official Coinbase Developer Platform page, create a <b>Secret API key</b>.
              Important: choose <b>ECDSA</b> as the signature algorithm — the newer Ed25519 keys
              do not work with this app.
            </li>
            <li>
              Select only the <b>View</b> permission for now. Trading permission is needed much
              later, for live trading. Never select <b>Transfer</b>.
            </li>
            <li>
              Download the key file, then copy the key name and the private key exactly into the
              fields below. The key is stored in Windows Credential Manager — never in files.
            </li>
          </ol>
          <div className="controls">
            <button
              type="button"
              onClick={() => void api?.openExternal(OFFICIAL_KEY_PAGE_URL)}
              disabled={busy}
            >
              Open the official Coinbase API keys page
            </button>
          </div>
          <form
            className="credential-form"
            onSubmit={(event) => {
              event.preventDefault();
              handleConnect();
            }}
          >
            <label>
              Key name
              <input
                type="text"
                value={keyName}
                onChange={(event) => setKeyName(event.target.value)}
                placeholder="organizations/…/apiKeys/…"
                autoComplete="off"
                spellCheck={false}
              />
            </label>
            <label>
              Private key
              <textarea
                value={privateKey}
                onChange={(event) => setPrivateKey(event.target.value)}
                placeholder={PEM_PLACEHOLDER}
                rows={4}
                spellCheck={false}
                autoComplete="off"
              />
            </label>
            <div className="controls">
              <button type="submit" disabled={busy}>
                Save &amp; test connection
              </button>
            </div>
          </form>
        </>
      )}

      {notice && (
        <p className={notice.kind === "ok" ? "meta" : "error"} role={notice.kind === "error" ? "alert" : undefined}>
          {notice.text}
        </p>
      )}
    </section>
  );
}
