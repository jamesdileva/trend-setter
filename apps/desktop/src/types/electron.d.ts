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

export interface StrategyConfigView {
  configured: boolean;
  config?: {
    product_id: string;
    timeframe: string;
    fast_ema_period: number;
    slow_ema_period: number;
    rsi_period: number;
    rsi_entry_ceiling: number;
    rsi_exit_floor: number | null;
    config_hash: string;
  };
  recent_signals?: Array<{
    candle_time: string;
    decision: string;
    reason_code: string;
    explanation: string;
  }>;
}

export interface StrategyDecisionView {
  signal: "buy" | "sell" | "hold";
  product_id: string;
  timeframe: string;
  candle_time: string | null;
  reason_code: string;
  explanation: string;
  indicator_values: Record<string, string>;
  strategy_name?: string;
  strategy_version?: string;
  config_hash?: string;
  status?: string;
  message?: string;
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
  getStrategyCurrent(): Promise<EngineResponse | null>;
  saveStrategyConfig(payload: Record<string, unknown>): Promise<EngineResponse | null>;
  evaluateStrategy(payload: Record<string, unknown>): Promise<EngineResponse | null>;
  runBacktest(payload: Record<string, unknown>): Promise<EngineResponse | null>;
  listBacktestRuns(): Promise<EngineResponse | null>;
  openExternal(url: string): Promise<void>;
}

declare global {
  interface Window {
    desktop: DesktopApi;
  }
}

export {};
