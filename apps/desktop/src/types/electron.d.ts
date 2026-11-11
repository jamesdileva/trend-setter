export interface EngineHealth {
  status: string;
  engine_version: string;
  utc_time?: string;
}

export interface EngineStatus {
  state: "stopped" | "starting" | "running" | "stopping" | "crashed";
  health: EngineHealth | null;
  lastError: string | null;
}

export interface DesktopApi {
  getEngineStatus(): Promise<EngineStatus | null>;
  startEngine(): Promise<EngineStatus | null>;
  stopEngine(): Promise<EngineStatus | null>;
}

declare global {
  interface Window {
    desktop: DesktopApi;
  }
}

export {};
