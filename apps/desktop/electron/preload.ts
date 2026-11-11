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
  getMarketDataStatus: () => ipcRenderer.invoke("market-data:get-status"),
  getStrategyCurrent: () => ipcRenderer.invoke("strategy:get-current"),
  saveStrategyConfig: (payload: Record<string, unknown>) =>
    ipcRenderer.invoke("strategy:save-config", payload),
  evaluateStrategy: (payload: Record<string, unknown>) =>
    ipcRenderer.invoke("strategy:evaluate", payload),
  runBacktest: (payload: Record<string, unknown>) =>
    ipcRenderer.invoke("backtest:run", payload),
  listBacktestRuns: () => ipcRenderer.invoke("backtest:runs"),
  openExternal: (url: string) => ipcRenderer.invoke("shell:open-external", url),
};

contextBridge.exposeInMainWorld("desktop", api);
