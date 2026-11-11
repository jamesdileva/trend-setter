import type { DesktopApi } from "../types/electron";

/**
 * Typed accessor for the preload bridge. Returns null outside Electron
 * (e.g. when the renderer is served in a plain browser for styling work),
 * so callers can degrade gracefully instead of crashing.
 */
export function getDesktopApi(): DesktopApi | null {
  return window.desktop ?? null;
}
