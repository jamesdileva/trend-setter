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

export function resolveEngineSpawnConfig(options: {
  repoRoot: string;
  platform?: NodeJS.Platform;
  port?: number;
  token: string;
}): EngineSpawnConfig {
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

  constructor(options: { repoRoot: string; platform?: NodeJS.Platform; port?: number }) {
    this.port = options.port ?? DEFAULT_PORT;
    this.baseUrl = `http://127.0.0.1:${this.port}`;
    this.spawnConfig = resolveEngineSpawnConfig({ ...options, port: this.port, token: this.token });
  }

  getStatus(): EngineStatus {
    return this.status;
  }

  async start(): Promise<EngineStatus> {
    if (this.child) {
      return this.status; // duplicate-instance guard: one engine at a time
    }
    this.status = { state: "starting", health: null, lastError: null };
    const child = spawn(this.spawnConfig.command, this.spawnConfig.args, {
      env: this.spawnConfig.env,
      stdio: ["ignore", "pipe", "pipe"],
    });
    this.child = child;
    child.on("error", (err: Error) => {
      this.child = null;
      this.stopPolling();
      this.status = { state: "crashed", health: null, lastError: `engine failed to start: ${err.message}` };
    });
    child.on("exit", (code: number | null) => {
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
          lastError: `engine exited unexpectedly (code ${code ?? "unknown"})`,
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
        this.status = { state: "running", health, lastError: null };
      }
    } catch (err) {
      // Engine not ready yet (starting) or just lost. The exit handler
      // surfaces real crashes; here we only reflect the lost heartbeat.
      if (this.child && this.status.state === "running") {
        const message = err instanceof Error ? err.message : String(err);
        this.status = { state: "starting", health: null, lastError: `health check failed: ${message}` };
      }
    }
  }
}
