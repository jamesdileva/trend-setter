/**
 * Electron main process: window lifecycle and engine control wiring.
 *
 * Security posture (implementation.md §11): context isolation enabled,
 * Node integration disabled, sandbox on, and only the narrow preload API
 * exposed to the renderer. The engine is stopped when the app quits —
 * closing the shell must not leave an unmanaged engine (architecture.md §5;
 * background-running policy is a later, deliberate decision).
 */

import { app, BrowserWindow, ipcMain, shell } from "electron";
import path from "node:path";
import { EngineSupervisor } from "./process-manager";
import { isAllowedExternalUrl } from "./urls";

let mainWindow: BrowserWindow | null = null;
let supervisor: EngineSupervisor | null = null;

const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) {
        mainWindow.restore();
      }
      mainWindow.focus();
    }
  });

  const createWindow = (): void => {
    mainWindow = new BrowserWindow({
      width: 1024,
      height: 720,
      title: "trend-setter",
      webPreferences: {
        contextIsolation: true,
        nodeIntegration: false,
        sandbox: true,
        preload: path.join(__dirname, "preload.js"),
      },
    });
    void mainWindow.loadFile(path.join(__dirname, "../dist/index.html"));
    mainWindow.on("closed", () => {
      mainWindow = null;
    });
  };

  app.whenReady().then(() => {
    supervisor = new EngineSupervisor({
      repoRoot: path.resolve(app.getAppPath(), "..", ".."),
    });

    ipcMain.handle("engine:get-status", () => supervisor?.getStatus() ?? null);
    ipcMain.handle("engine:start", () => supervisor?.start());
    ipcMain.handle("engine:stop", () => supervisor?.stop());

    // Coinbase wizard: the renderer never holds the session token — the
    // main process performs the engine requests on its behalf.
    ipcMain.handle("coinbase:get-status", () => supervisor?.engineRequest("/coinbase/connection"));
    ipcMain.handle("coinbase:connect", (_event, payload: { keyName: string; privateKeyPem: string }) =>
      supervisor?.engineRequest("/coinbase/credentials", "POST", {
        key_name: payload.keyName,
        private_key_pem: payload.privateKeyPem,
      }),
    );
    ipcMain.handle("coinbase:test", () => supervisor?.engineRequest("/coinbase/test-connection", "POST"));
    ipcMain.handle("coinbase:disconnect", () => supervisor?.engineRequest("/coinbase/disconnect", "POST"));
    ipcMain.handle("market-data:get-status", () => supervisor?.engineRequest("/market-data/status"));
    ipcMain.handle("strategy:get-current", () => supervisor?.engineRequest("/strategy/current"));
    ipcMain.handle("strategy:save-config", (_event, payload: Record<string, unknown>) =>
      supervisor?.engineRequest("/strategy/config", "POST", payload),
    );
    ipcMain.handle("strategy:evaluate", (_event, payload: Record<string, unknown>) =>
      supervisor?.engineRequest("/strategy/evaluate", "POST", payload),
    );
    ipcMain.handle("backtest:run", (_event, payload: Record<string, unknown>) =>
      supervisor?.engineRequest("/backtest/run", "POST", payload),
    );
    ipcMain.handle("backtest:runs", () => supervisor?.engineRequest("/backtest/runs"));
    ipcMain.handle("paper:control", (_event, payload: { path: string; body: Record<string, unknown> }) =>
      supervisor?.engineRequest(payload.path, "POST", payload.body),
    );
    ipcMain.handle("paper:status", () => supervisor?.engineRequest("/paper/status"));
    ipcMain.handle("candles:get", (_event, payload: { timeframe: string }) =>
      supervisor?.engineRequest(`/candles?product_id=BTC-USD&timeframe=${payload.timeframe}`),
    );

    ipcMain.handle("shell:open-external", (_event, url: string) => {
      if (!isAllowedExternalUrl(url)) {
        throw new Error("This link is not on the allowed list.");
      }
      return shell.openExternal(url);
    });

    void supervisor.start();
    createWindow();

    app.on("activate", () => {
      if (BrowserWindow.getAllWindows().length === 0) {
        createWindow();
      }
    });
  });

  app.on("window-all-closed", () => {
    app.quit();
  });

  app.on("before-quit", (event) => {
    if (supervisor && supervisor.getStatus().state !== "stopped") {
      event.preventDefault();
      void supervisor.stop().then(() => app.quit());
    }
  });
}
