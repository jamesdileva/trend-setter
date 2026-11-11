/**
 * Preload bridge (implementation.md §11).
 *
 * Context isolation is enabled and Node integration is disabled in the
 * renderer; only these narrow, typed methods cross the boundary. Secrets
 * never pass through this API.
 */

import { contextBridge, ipcRenderer } from "electron";

const api = {
  getEngineStatus: () => ipcRenderer.invoke("engine:get-status"),
  startEngine: () => ipcRenderer.invoke("engine:start"),
  stopEngine: () => ipcRenderer.invoke("engine:stop"),
};

contextBridge.exposeInMainWorld("desktop", api);
