import { describe, expect, it } from "vitest";
import path from "node:path";
import {
  EngineSupervisor,
  OutputTail,
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

  it("spawns the bundled engine exe directly in packaged mode", () => {
    const config = resolveEngineSpawnConfig({
      repoRoot: path.join("C:", "repo"),
      platform: "win32",
      port: 9002,
      token: "tok",
      packagedEnginePath: path.join("C:", "app", "resources", "engine", "trendbot-engine.exe"),
    });
    // Packaged builds must run the bundled PyInstaller engine, never a venv
    // Python (regression: packaged app spawned .venv python and crashed with ENOENT).
    expect(config.command).toBe(path.join("C:", "app", "resources", "engine", "trendbot-engine.exe"));
    expect(config.args).toEqual(["--port", "9002"]);
    expect(config.env.TRENDBOT_LOCAL_TOKEN).toBe("tok");
    expect(JSON.stringify(config.args)).not.toContain("trendbot.main");
  });

  it("still falls back to the venv python when no packaged engine exists", () => {
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

describe("OutputTail", () => {
  it("keeps only the last `limit` characters", () => {
    const tail = new OutputTail(10);
    tail.append("0123456789");
    tail.append("abcdefghij");
    expect(tail.tail()).toBe("abcdefghij");
  });

  it("truncates long output with a leading ellipsis", () => {
    const tail = new OutputTail(100);
    tail.append("x".repeat(50));
    expect(tail.tail(10).length).toBe(11);
    expect(tail.tail(10)).toBe(`…${"x".repeat(10)}`);
  });

  it("returns an empty string when nothing was written", () => {
    expect(new OutputTail().tail()).toBe("");
  });
});

describe("EngineSupervisor health escalation", () => {
  function supervisorWithFailingHealth(): EngineSupervisor & { restoreFetch: () => void } {
    const supervisor = new EngineSupervisor({ repoRoot: path.join("/repo"), port: 8788 });
    const originalFetch = globalThis.fetch;
    globalThis.fetch = (() =>
      Promise.reject(new Error("The operation was aborted due to timeout"))) as typeof fetch;
    // Simulate a spawned child without launching one; pollHealth only needs
    // the reference to be non-null (and kill() to exist for escalation).
    const fakeChild = { kill: () => true } as unknown as import("node:child_process").ChildProcess;
    (supervisor as unknown as { child: unknown }).child = fakeChild;
    (supervisor as unknown as { stdoutTail: OutputTail }).stdoutTail = new OutputTail();
    (supervisor as unknown as { stderrTail: OutputTail }).stderrTail = new OutputTail();
    return Object.assign(supervisor, {
      restoreFetch: () => {
        globalThis.fetch = originalFetch;
      },
    });
  }

  it("stays in starting during the cold-start grace window", async () => {
    const supervisor = supervisorWithFailingHealth();
    try {
      (supervisor as unknown as { startedAt: number }).startedAt = Date.now();
      (supervisor as unknown as { lastHealthyAt: number | null }).lastHealthyAt = null;
      (supervisor as unknown as { status: { state: string } }).status.state = "starting";
      const poll = (
        supervisor as unknown as { pollHealth: () => Promise<void> }
      ).pollHealth.bind(supervisor);
      await poll();
      await poll();
      expect(supervisor.getStatus().state).toBe("starting");
    } finally {
      (supervisor as unknown as { restoreFetch: () => void }).restoreFetch();
    }
  });

  it("marks a never-healthy engine failed once the start deadline passes", async () => {
    const supervisor = supervisorWithFailingHealth();
    try {
      (supervisor as unknown as { startedAt: number }).startedAt = Date.now() - 91_000;
      (supervisor as unknown as { lastHealthyAt: number | null }).lastHealthyAt = null;
      const poll = (
        supervisor as unknown as { pollHealth: () => Promise<void> }
      ).pollHealth.bind(supervisor);
      await poll();
      const status = supervisor.getStatus();
      expect(status.state).toBe("crashed");
      expect(status.lastError).toContain("did not become healthy within 90 seconds");
      expect(status.lastError).toContain("Stop the engine, then start it again");
      // The frozen child is detached so Start works without a manual stop.
      expect((supervisor as unknown as { child: unknown }).child).toBeNull();
    } finally {
      (supervisor as unknown as { restoreFetch: () => void }).restoreFetch();
    }
  });

  it("escalates to engine error after three consecutive missed checks while running", async () => {
    const supervisor = supervisorWithFailingHealth();
    try {
      const internal = supervisor as unknown as {
        startedAt: number;
        lastHealthyAt: number | null;
        missedHealthChecks: number;
        pollHealth: () => Promise<void>;
      };
      internal.startedAt = Date.now();
      internal.lastHealthyAt = Date.now() - 60_000; // was healthy, then went quiet
      (supervisor as unknown as { status: { state: string } }).status.state = "running";
      const poll = internal.pollHealth.bind(supervisor);
      await poll();
      expect(supervisor.getStatus().state).toBe("starting"); // grace window
      await poll();
      expect(supervisor.getStatus().state).toBe("starting");
      await poll();
      const status = supervisor.getStatus();
      expect(status.state).toBe("crashed");
      expect(status.lastError).toContain("engine stopped responding");
      expect(status.lastError).toContain("Stop the engine, then start it again");
      expect((supervisor as unknown as { child: unknown }).child).toBeNull();
    } finally {
      (supervisor as unknown as { restoreFetch: () => void }).restoreFetch();
    }
  });

  it("clears the miss counter and returns to running on a successful check", async () => {
    const supervisor = supervisorWithFailingHealth();
    try {
      globalThis.fetch = (() =>
        Promise.resolve(
          new Response(JSON.stringify({ status: "ok", engine_version: "0.1.0" }), { status: 200 }),
        )) as typeof fetch;
      const internal = supervisor as unknown as {
        startedAt: number;
        lastHealthyAt: number | null;
        missedHealthChecks: number;
        pollHealth: () => Promise<void>;
      };
      internal.startedAt = Date.now();
      internal.lastHealthyAt = Date.now() - 60_000;
      internal.missedHealthChecks = 2; // one more miss would escalate
      await internal.pollHealth.bind(supervisor)();
      expect(supervisor.getStatus().state).toBe("running");
      expect(internal.missedHealthChecks).toBe(0);
      expect(supervisor.getStatus().lastError).toBeNull();
    } finally {
      (supervisor as unknown as { restoreFetch: () => void }).restoreFetch();
    }
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
