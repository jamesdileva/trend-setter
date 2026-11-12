"""Request schemas for the local API."""

from __future__ import annotations

from pydantic import BaseModel, Field


class CredentialRequest(BaseModel):
    """A Coinbase credential as submitted by the connection wizard."""

    key_name: str = Field(
        min_length=1,
        max_length=256,
        description="The CDP key name, e.g. organizations/{org_id}/apiKeys/{key_id}",
    )
    private_key_pem: str = Field(
        min_length=1,
        max_length=20000,
        description="ECDSA (ES256) private key PEM. Never stored outside the OS secret store.",
    )


class StrategyConfigRequest(BaseModel):
    """Baseline strategy parameters (baseline defaults; not recommendations)."""

    product_id: str = Field(description="Product the strategy instance evaluates, e.g. BTC-USD")
    timeframe: str = Field(description="Decision timeframe, e.g. 1h")
    fast_ema_period: int = Field(default=20, ge=2, le=400)
    slow_ema_period: int = Field(default=50, ge=2, le=400)
    rsi_period: int = Field(default=14, ge=2, le=200)
    rsi_entry_ceiling: float = Field(default=70.0, gt=0, lt=100)
    rsi_exit_floor: float | None = Field(default=None, gt=0, lt=100)


class StrategyEvaluateRequest(BaseModel):
    """Evaluate the active config against stored candles (overrides optional)."""

    product_id: str | None = None
    timeframe: str | None = None


class BacktestRunRequest(BaseModel):
    """A labeled historical simulation request (never a live order path)."""

    product_id: str = Field(description="Product to simulate, e.g. BTC-USD")
    timeframe: str = Field(description="Candle timeframe, e.g. 1h")
    start: str | None = Field(default=None, description="ISO start date (UTC)")
    end: str | None = Field(default=None, description="ISO end date (UTC)")
    fast_ema_period: int = Field(default=20, ge=2, le=400)
    slow_ema_period: int = Field(default=50, ge=2, le=400)
    rsi_period: int = Field(default=14, ge=2, le=200)
    rsi_entry_ceiling: float = Field(default=70.0, gt=0, lt=100)
    rsi_exit_floor: float | None = Field(default=None, gt=0, lt=100)
    initial_quote: float = Field(default=1000.0, gt=0)
    position_size_quote: float = Field(default=500.0, gt=0)
    fee_bps: float = Field(default=100.0, ge=0, description="Placeholder per-side fee")
    slippage_bps: float = Field(default=10.0, ge=0, description="Placeholder per-side slippage")
    in_sample_fraction: float = Field(default=0.7, gt=0, lt=1)


class PaperResetRequest(BaseModel):
    """Resetting the paper account wipes simulated history — confirm required."""

    confirm: bool = Field(default=False, description="Must be true to actually reset.")
