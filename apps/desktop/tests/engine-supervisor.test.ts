import { describe, expect, it } from "vitest";
import path from "node:path";
import {
  EngineSupervisor,
  newSessionToken,
  resolveEngineSpawnConfig,
} from "../electron/process-manager";

describe("resolveEngineSpawnConfig", () => {
  it("spawns the venv engine module on Windows", () => {
    const config = resolveEngineSpawnConfig({
      repoRoot: path.join("C:", "repo"),
      platform: "win32",
      port: 9001,
      token: "tok",
    });
    expect(config.command).toBe(path.join("C:", "repo", ".venv", "Scripts", "python.exe"));
    expect(config.args).toEqual(["-m", "trendbot.main", "--port", "9001"]);
  });

  it("spawns the POSIX venv python elsewhere", () => {
    const config = resolveEngineSpawnConfig({
      repoRoot: "/repo",
      platform: "linux",
      port: 8788,
      token: "tok",
    });
    expect(config.command).toBe(path.join("/repo", ".venv", "bin", "python"));
  });

  it("passes the session token through the environment, never the command line", () => {
    const config = resolveEngineSpawnConfig({
      repoRoot: "/repo",
      platform: "linux",
      port: 8788,
      token: "secret-token-value",
    });
    expect(config.env.TRENDBOT_LOCAL_TOKEN).toBe("secret-token-value");
    expect(JSON.stringify(config.args)).not.toContain("secret-token-value");
    expect(config.command).not.toContain("secret-token-value");
  });
});

describe("newSessionToken", () => {
  it("generates 64-hex-character tokens that do not repeat", () => {
    const first = newSessionToken();
    const second = newSessionToken();
    expect(first).toMatch(/^[0-9a-f]{64}$/);
    expect(second).toMatch(/^[0-9a-f]{64}$/);
    expect(first).not.toBe(second);
  });
});

describe("EngineSupervisor.engineRequest", () => {
  function withStubbedFetch(handler: (url: string, init: RequestInit) => Response): {
    calls: Array<{ url: string; init: RequestInit }>;
    restore: () => void;
  } {
    const calls: Array<{ url: string; init: RequestInit }> = [];
    const originalFetch = globalThis.fetch;
    globalThis.fetch = ((url: RequestInfo | URL, init?: RequestInit) => {
      const record = { url: String(url), init: init ?? {} };
      calls.push(record);
      return Promise.resolve(handler(record.url, record.init));
    }) as typeof fetch;
    return {
      calls,
      restore: () => {
        globalThis.fetch = originalFetch;
      },
    };
  }

  it("sends the session token header and parses JSON bodies", async () => {
    const stub = withStubbedFetch(() => new Response(JSON.stringify({ connected: false }), { status: 200 }));
    try {
      const supervisor = new EngineSupervisor({ repoRoot: path.join("/repo"), port: 8788 });
      const response = await supervisor.engineRequest("/coinbase/connection");
      expect(response.status).toBe(200);
      expect(response.body).toEqual({ connected: false });
      expect(stub.calls[0].url).toBe("http://127.0.0.1:8788/coinbase/connection");
      const headers = new Headers(stub.calls[0].init.headers);
      expect(headers.get("X-Local-Token")).toMatch(/^[0-9a-f]{64}$/);
      expect(stub.calls[0].init.method).toBe("GET");
    } finally {
      stub.restore();
    }
  });

  it("serializes POST bodies as JSON with the token header", async () => {
    let capturedBody: string | undefined;
    const stub = withStubbedFetch((_url, init) => {
      capturedBody = typeof init.body === "string" ? init.body : undefined;
      return new Response(JSON.stringify({ status: "valid" }), { status: 200 });
    });
    try {
      const supervisor = new EngineSupervisor({ repoRoot: path.join("/repo"), port: 8788 });
      const response = await supervisor.engineRequest("/coinbase/credentials", "POST", {
        key_name: "k",
        private_key_pem: "pem",
      });
      expect(response.status).toBe(200);
      expect(stub.calls[0].init.method).toBe("POST");
      expect(capturedBody).toBe(JSON.stringify({ key_name: "k", private_key_pem: "pem" }));
    } finally {
      stub.restore();
    }
  });

  it("passes non-JSON bodies through as text", async () => {
    const stub = withStubbedFetch(() => new Response("<html>gateway</html>", { status: 502 }));
    try {
      const supervisor = new EngineSupervisor({ repoRoot: path.join("/repo"), port: 8788 });
      const response = await supervisor.engineRequest("/coinbase/connection");
      expect(response.status).toBe(502);
      expect(response.body).toBe("<html>gateway</html>");
    } finally {
      stub.restore();
    }
  });
});
