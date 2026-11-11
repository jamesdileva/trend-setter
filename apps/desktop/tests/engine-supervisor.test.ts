import { describe, expect, it } from "vitest";
import path from "node:path";
import { newSessionToken, resolveEngineSpawnConfig } from "../electron/process-manager";

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
