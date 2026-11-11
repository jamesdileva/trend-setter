/**
 * Electron main process: window lifecycle and engine control wiring.
 *
 * Security posture (implementation.md §11): context isolation enabled,
 * Node integration disabled, sandbox on, and only the narrow preload API
 * exposed to the renderer. The engine is stopped when the app quits —
 * closing the shell must not leave an unmanaged engine (architecture.md §5;
 * background-running policy is a later, deliberate decision).
 */

import { app, BrowserWindow, ipcMain } from "electron";
import path from "node:path";
import { EngineSupervisor } from "./process-manager";

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
