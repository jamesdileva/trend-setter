/**
 * Preload bridge (implementation.md §11).
 *
 * Context isolation is enabled and Node integration is disabled in the
 * renderer; only these narrow, typed methods cross the boundary. Secrets
 * pass through exactly once on connect (renderer → main → engine) and are
 * never stored renderer-side; the session token never crosses at all.
 */

import { contextBridge, ipcRenderer } from "electron";

const api = {
  getEngineStatus: () => ipcRenderer.invoke("engine:get-status"),
  startEngine: () => ipcRenderer.invoke("engine:start"),
  stopEngine: () => ipcRenderer.invoke("engine:stop"),
  getCoinbaseStatus: () => ipcRenderer.invoke("coinbase:get-status"),
  connectCoinbase: (keyName: string, privateKeyPem: string) =>
    ipcRenderer.invoke("coinbase:connect", { keyName, privateKeyPem }),
  testCoinbase: () => ipcRenderer.invoke("coinbase:test"),
  disconnectCoinbase: () => ipcRenderer.invoke("coinbase:disconnect"),
  openExternal: (url: string) => ipcRenderer.invoke("shell:open-external", url),
};

contextBridge.exposeInMainWorld("desktop", api);
