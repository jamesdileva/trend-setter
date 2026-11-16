import { useCallback, useEffect, useState } from "react";
import type { EmailNotificationSettings, EngineResponse } from "../types/electron";
import { getDesktopApi } from "../services/desktopApi";

/**
 * Email notification setup (Sprint 15). The app-password is write-only:
 * the renderer types it once, it goes to the engine's OS credential store,
 * and it is never displayed or returned again.
 */
export function NotificationsCard() {
  const api = getDesktopApi();
  const [settings, setSettings] = useState<EmailNotificationSettings | null>(null);
  const [host, setHost] = useState("");
  const [port, setPort] = useState("465");
  const [security, setSecurity] = useState("ssl");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [recipient, setRecipient] = useState("");
  const [enabled, setEnabled] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  const load = useCallback(() => {
    if (!api) return;
    void api
      .getEmailNotifications()
      .then((response: EngineResponse | null) => {
        if (!response || response.status !== 200) return;
        const body = response.body as EmailNotificationSettings;
        if (!body || body.available === false) return;
        setSettings(body);
        setHost(body.smtp_host);
        setPort(String(body.smtp_port));
        setSecurity(body.security);
        setUsername(body.username);
        setRecipient(body.recipient);
        setEnabled(body.enabled);
      })
      .catch(() => undefined);
  }, [api]);

  useEffect(() => {
    load();
  }, [load]);

  const save = useCallback(async () => {
    if (!api) return;
    setBusy(true);
    setNotice(null);
    try {
      const response = await api.saveEmailNotifications({
        enabled,
        smtp_host: host,
        smtp_port: Number(port) || 465,
        security,
        username,
        recipient,
        password: password ? password : undefined,
      });
      if (response && response.status === 200) {
        setPassword(""); // never keep the secret in the form
        setNotice({ kind: "ok", text: "Email settings saved." });
        load();
      } else {
        const body = (response?.body ?? {}) as { message?: string };
        setNotice({
          kind: "error",
          text: body.message ?? "The settings could not be saved.",
        });
      }
    } catch {
      setNotice({ kind: "error", text: "The engine is not reachable yet." });
    } finally {
      setBusy(false);
    }
  }, [api, enabled, host, port, security, username, recipient, password, load]);

  const sendTest = useCallback(async () => {
    if (!api) return;
    setBusy(true);
    setNotice(null);
    try {
      const response = await api.testEmailNotifications();
      const body = (response?.body ?? {}) as { sent?: boolean; message?: string };
      if (response && response.status === 200 && body.sent) {
        setNotice({ kind: "ok", text: "Test email sent — check your inbox." });
      } else {
        setNotice({
          kind: "error",
          text: body.message ?? "The test email could not be sent.",
        });
      }
    } catch {
      setNotice({ kind: "error", text: "The engine is not reachable yet." });
    } finally {
      setBusy(false);
    }
  }, [api]);

  return (
    <section className="card" aria-live="polite">
      <h2>Email alerts</h2>
      <p className="meta">
        Get an email whenever the app buys or sells, and when something needs attention
        (like the market feed disconnecting). Problem alerts are rate-limited so a bad
        connection cannot flood your inbox.
      </p>

      <label className="checkbox-row">
        <input
          type="checkbox"
          checked={enabled}
          onChange={(event) => setEnabled(event.target.checked)}
        />
        Send me emails about trades and problems
      </label>

      <div className="strategy-fields">
        <label>
          Email server (SMTP host)
          <input
            type="text"
            value={host}
            onChange={(event) => setHost(event.target.value)}
            placeholder="smtp.gmail.com"
          />
        </label>
        <label>
          Security
          <select value={security} onChange={(event) => setSecurity(event.target.value)}>
            <option value="ssl">SSL (port 465)</option>
            <option value="starttls">STARTTLS (port 587)</option>
          </select>
        </label>
        <label>
          Port
          <input
            type="number"
            value={port}
            onChange={(event) => setPort(event.target.value)}
            min={1}
            max={65535}
          />
        </label>
        <label>
          Email account (username)
          <input
            type="text"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            placeholder="you@gmail.com"
          />
        </label>
        <label>
          App-password{" "}
          {settings?.has_password ? "(saved — type only to replace)" : "(never shown again)"}
          <input
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            placeholder={settings?.has_password ? "••••••••" : ""}
            autoComplete="new-password"
          />
        </label>
        <label>
          Send alerts to
          <input
            type="email"
            value={recipient}
            onChange={(event) => setRecipient(event.target.value)}
            placeholder="you@example.com"
          />
        </label>
      </div>

      <details className="strategy-help">
        <summary>How do I get an app-password?</summary>
        <p>
          Most email providers (Gmail, Outlook) don't accept your normal password from
          apps. Create an <b>app-password</b>: for Gmail, turn on 2-step verification, then
          visit myaccount.google.com → Security → App passwords, and create one for
          "Mail". Use that 16-character code here.
        </p>
        <p>
          The app-password is stored only in this computer's credential store — never in
          the app's database, logs, or this window.
        </p>
      </details>

      <div className="controls">
        <button type="button" onClick={() => void save()} disabled={busy}>
          Save
        </button>
        <button type="button" onClick={() => void sendTest()} disabled={busy}>
          Send test email
        </button>
      </div>

      {notice && (
        <p className={notice.kind === "ok" ? "meta" : "error"} role={notice.kind === "error" ? "alert" : undefined}>
          {notice.text}
        </p>
      )}
    </section>
  );
}
