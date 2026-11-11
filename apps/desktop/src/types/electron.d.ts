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

export interface EngineResponse {
  status: number;
  body: unknown;
}

export interface CoinbaseStatus {
  connected: boolean;
  key_reference: string | null;
  permissions: string | null;
  last_validated_at: string | null;
}

export interface MarketDataStatus {
  running: boolean;
  state?: string;
  last_message_at?: string | null;
  last_heartbeat_at?: string | null;
  last_complete?: Record<string, string>;
  last_error?: string | null;
  reconnects?: number;
}

export interface DesktopApi {
  getEngineStatus(): Promise<EngineStatus | null>;
  startEngine(): Promise<EngineStatus | null>;
  stopEngine(): Promise<EngineStatus | null>;
  getCoinbaseStatus(): Promise<EngineResponse | null>;
  connectCoinbase(keyName: string, privateKeyPem: string): Promise<EngineResponse | null>;
  testCoinbase(): Promise<EngineResponse | null>;
  disconnectCoinbase(): Promise<EngineResponse | null>;
  getMarketDataStatus(): Promise<EngineResponse | null>;
  openExternal(url: string): Promise<void>;
}

declare global {
  interface Window {
    desktop: DesktopApi;
  }
}

export {};
