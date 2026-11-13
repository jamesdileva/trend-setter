/**
 * Engine supervisor (roadmap Sprint 1, task 5; implementation.md §11).
 *
 * Owns the engine process lifecycle: start, health monitoring, graceful
 * stop with escalation, and duplicate-instance prevention. The engine must
 * never depend on the UI being open, and the shell must never leave an
 * unmanaged engine behind.
 *
 * This module deliberately imports nothing from Electron so it stays
 * unit-testable with plain Node.
 */

import { spawn, type ChildProcess } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import { randomBytes } from "node:crypto";
import path from "node:path";

export type EngineState = "stopped" | "starting" | "running" | "stopping" | "crashed";

export interface EngineHealth {
  status: string;
  engine_version: string;
  utc_time?: string;
}

export interface EngineStatus {
  state: EngineState;
  health: EngineHealth | null;
  lastError: string | null;
}

export interface EngineSpawnConfig {
  command: string;
  args: string[];
  env: NodeJS.ProcessEnv;
}

const DEFAULT_PORT = 8788;
const POLL_INTERVAL_MS = 2000;
const HEALTH_TIMEOUT_MS = 1500;
const STOP_TIMEOUT_MS = 10_000;
const ENGINE_REQUEST_TIMEOUT_MS = 10_000;
// The engine pipes stdout/stderr; an undrained pipe buffer fills after
// ~20 minutes of request logging and blocks the engine's event loop, so
// output is drained into a bounded tail and surfaced in error messages.
const OUTPUT_TAIL_CHARS = 4000;
const TAIL_IN_ERROR_CHARS = 600;
// How long start() may take to first healthy response (PyInstaller cold
// start plus first-run migrations on a fresh machine), and how many
// consecutive missed health checks while running mark the engine unresponsive.
const START_DEADLINE_MS = 90_000;
const MAX_MISSED_HEALTH_CHECKS = 3;

/**
 * Keeps the last `limit` characters of a stream so drained engine output can
 * be included in crash diagnostics without growing without bound.
 */
export class OutputTail {
  private value = "";

  constructor(private readonly limit: number = OUTPUT_TAIL_CHARS) {}

  append(chunk: string | Buffer): void {
    const text = typeof chunk === "string" ? chunk : chunk.toString("utf8");
    this.value = (this.value + text).slice(-this.limit);
  }

  tail(limit: number = this.limit): string {
    const trimmed = this.value.trim();
    return trimmed.length > limit ? `…${trimmed.slice(-limit)}` : trimmed;
  }
}

export interface EngineResponse {
  status: number;
  body: unknown;
}

export function resolveEngineSpawnConfig(options: {
  repoRoot: string;
  platform?: NodeJS.Platform;
  port?: number;
  token: string;
  packagedEnginePath?: string;
}): EngineSpawnConfig {
  // Packaged builds run the bundled PyInstaller engine directly; the venv
  // Python only exists in a development checkout (Sprint 12 packaging).
  if (options.packagedEnginePath) {
    return {
      command: options.packagedEnginePath,
      args: ["--port", String(options.port ?? DEFAULT_PORT)],
      // The session token must never travel on the command line (implementation.md §12).
      env: { ...process.env, TRENDBOT_LOCAL_TOKEN: options.token },
    };
  }
  const platform = options.platform ?? process.platform;
  const pythonRelative =
    platform === "win32"
      ? path.join(".venv", "Scripts", "python.exe")
      : path.join(".venv", "bin", "python");
  return {
    command: path.join(options.repoRoot, pythonRelative),
    args: ["-m", "trendbot.main", "--port", String(options.port ?? DEFAULT_PORT)],
    // The session token must never travel on the command line (implementation.md §12).
    env: { ...process.env, TRENDBOT_LOCAL_TOKEN: options.token },
  };
}

export function newSessionToken(): string {
  return randomBytes(32).toString("hex");
}

export class EngineSupervisor {
  private child: ChildProcess | null = null;
  private stopping = false;
  private readonly token = newSessionToken();
  private readonly port: number;
  private readonly baseUrl: string;
  private readonly spawnConfig: EngineSpawnConfig;
  private pollTimer: ReturnType<typeof setInterval> | null = null;
  private status: EngineStatus = { state: "stopped", health: null, lastError: null };
  private startedAt = 0;
  private lastHealthyAt: number | null = null;
  private missedHealthChecks = 0;
  private stdoutTail = new OutputTail();
  private stderrTail = new OutputTail();

  constructor(options: {
    repoRoot: string;
    platform?: NodeJS.Platform;
    port?: number;
    packagedEnginePath?: string;
  }) {
    this.port = options.port ?? DEFAULT_PORT;
    this.baseUrl = `http://127.0.0.1:${this.port}`;
    this.spawnConfig = resolveEngineSpawnConfig({ ...options, port: this.port, token: this.token });
    // Diagnostic: log the spawn config for debugging packaged builds
    try {
      const diagPath = path.join(os.tmpdir(), "trend-setter-spawn-config.json");
      fs.writeFileSync(
        diagPath,
        JSON.stringify(
          {
            timestamp: new Date().toISOString(),
            packagedEnginePath: options.packagedEnginePath ?? "not provided",
            command: this.spawnConfig.command,
            args: this.spawnConfig.args,
          },
          null,
          2,
        ),
      );
    } catch {
      // diagnostic write is best effort
    }
  }

  getStatus(): EngineStatus {
    return this.status;
  }

  /**
   * Authenticated request to the engine's local API, on behalf of the UI.
   * The session token stays in this (main) process — it never reaches the
   * renderer, and responses are passed through unchanged.
   */
  async engineRequest(
    path: string,
    method: "GET" | "POST" = "GET",
    body?: unknown,
  ): Promise<EngineResponse> {
    const response = await fetch(`${this.baseUrl}${path}`, {
      method,
      headers: {
        "X-Local-Token": this.token,
        "Content-Type": "application/json",
      },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: AbortSignal.timeout(ENGINE_REQUEST_TIMEOUT_MS),
    });
    const text = await response.text();
    let parsed: unknown = null;
    if (text) {
      try {
        parsed = JSON.parse(text);
      } catch {
        parsed = text;
      }
    }
    return { status: response.status, body: parsed };
  }

  async start(): Promise<EngineStatus> {
    if (this.child) {
      return this.status; // duplicate-instance guard: one engine at a time
    }
    this.status = { state: "starting", health: null, lastError: null };
    this.startedAt = Date.now();
    this.lastHealthyAt = null;
    this.missedHealthChecks = 0;
    this.stdoutTail = new OutputTail();
    this.stderrTail = new OutputTail();
    const child = spawn(this.spawnConfig.command, this.spawnConfig.args, {
      env: this.spawnConfig.env,
      stdio: ["ignore", "pipe", "pipe"],
    });
    this.child = child;
    // Drain the engine's output streams. Without readers the OS pipe buffer
    // fills and the engine blocks forever on its next write (frozen API).
    child.stdout?.on("data", (chunk: Buffer) => this.stdoutTail?.append(chunk));
    child.stderr?.on("data", (chunk: Buffer) => this.stderrTail?.append(chunk));
    child.on("error", (err: Error) => {
      if (this.child !== child) {
        return; // stale event from an already-replaced child
      }
      this.child = null;
      this.stopPolling();
      this.status = {
        state: "crashed",
        health: null,
        lastError: `engine failed to start: ${err.message} [command: ${this.spawnConfig.command}]`,
      };
    });
    child.on("exit", (code: number | null) => {
      if (this.child !== child) {
        return; // stale event from an already-replaced child
      }
      this.stopPolling();
      const wasStopping = this.stopping;
      this.stopping = false;
      this.child = null;
      if (wasStopping) {
        this.status = { state: "stopped", health: null, lastError: null };
      } else {
        this.status = {
          state: "crashed",
          health: null,
          lastError: `engine exited unexpectedly (code ${code ?? "unknown"}) [command: ${this.spawnConfig.command}]${this.describeOutputTail()}`,
        };
      }
    });
    this.startPolling();
    return this.status;
  }

  async stop(): Promise<EngineStatus> {
    const child = this.child;
    if (!child) {
      this.status = { state: "stopped", health: null, lastError: null };
      return this.status;
    }
    this.stopping = true;
    this.status = { state: "stopping", health: null, lastError: null };
    await new Promise<void>((resolve) => {
      const escalation = setTimeout(() => {
        try {
          child.kill("SIGKILL");
        } catch {
          // already gone
        }
        resolve();
      }, STOP_TIMEOUT_MS);
      child.once("exit", () => {
        clearTimeout(escalation);
        resolve();
      });
      child.kill();
    });
    this.child = null;
    this.stopPolling();
    this.status = { state: "stopped", health: null, lastError: null };
    return this.status;
  }

  private startPolling(): void {
    this.stopPolling();
    this.pollTimer = setInterval(() => void this.pollHealth(), POLL_INTERVAL_MS);
    void this.pollHealth();
  }

  private stopPolling(): void {
    if (this.pollTimer) {
      clearInterval(this.pollTimer);
      this.pollTimer = null;
    }
  }

  private async pollHealth(): Promise<void> {
    if (!this.child) {
      return;
    }
    try {
      const response = await fetch(`${this.baseUrl}/health`, {
        signal: AbortSignal.timeout(HEALTH_TIMEOUT_MS),
      });
      if (!response.ok) {
        throw new Error(`health endpoint returned ${response.status}`);
      }
      const health = (await response.json()) as EngineHealth;
      if (this.child) {
        this.lastHealthyAt = Date.now();
        this.missedHealthChecks = 0;
        this.status = { state: "running", health, lastError: null };
      }
    } catch (err) {
      // Engine not ready yet (starting) or just lost. The exit handler
      // surfaces real crashes; here we escalate when the engine stays
      // unreachable — a frozen engine never exits on its own.
      if (!this.child) {
        return;
      }
      this.missedHealthChecks += 1;
      const message = err instanceof Error ? err.message : String(err);
      if (this.lastHealthyAt === null) {
        // Never healthy since start(): give cold starts the full deadline.
        if (Date.now() - this.startedAt > START_DEADLINE_MS) {
          this.failUnresponsive(
            `engine did not become healthy within ${Math.round(START_DEADLINE_MS / 1000)} seconds ` +
              `(last check: ${message}). Stop the engine, then start it again.`,
          );
        }
        return;
      }
      // Was running: a few consecutive misses mean the engine stopped responding.
      if (this.missedHealthChecks >= MAX_MISSED_HEALTH_CHECKS) {
        this.failUnresponsive(
          `engine stopped responding (health check: ${message}). ` +
            "Stop the engine, then start it again to recover.",
        );
        return;
      }
      if (this.status.state === "running") {
        this.status = {
          state: "starting",
          health: null,
          lastError: `health check failed: ${message}`,
        };
      }
    }
  }

  /**
   * Mark the engine as failed and detach+kill the (still alive but
   * unresponsive) child so the user can start again without a manual stop.
   * The child is detached before killing so its exit event is ignored as
   * stale and does not overwrite the diagnostic status.
   */
  private failUnresponsive(message: string): void {
    this.status = { state: "crashed", health: null, lastError: `${message}${this.describeOutputTail()}` };
    const child = this.child;
    this.child = null;
    this.stopPolling();
    if (child) {
      try {
        child.kill("SIGKILL");
      } catch {
        // already gone
      }
    }
  }

  private describeOutputTail(): string {
    const tail = this.stderrTail.tail(TAIL_IN_ERROR_CHARS);
    return tail ? ` — engine output: ${tail}` : "";
  }
}
