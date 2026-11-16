"""The automated paper-trading loop (Sprint 15).

This is the wiring that makes the engine trade on its own: an asyncio task
that, every cycle —

1. derives newly completed ONE_HOUR candles from the 5-minute feed, so any
   saved timeframe has data to evaluate;
2. reads the active strategy config and (re)builds a ``PaperTradingEngine``
   whenever the config changes — account state lives in the database and
   ``recover()`` adopts it, so a rebuild is restart-safe;
3. calls ``process_once()``, which evaluates the newest completed candle and
   runs the full pipeline (risk gate → order intent → simulated fill).

Trading modes (normal/paused/stopped/emergency) gate inside the engine per
candle; the loop itself always runs so equity tracking continues.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime

from trendbot.application.strategy_engine import StrategyEngine
from trendbot.database.session import Database
from trendbot.exchange.fake import FakeExchangeAdapter
from trendbot.market_data.rollup import HourlyRollupService
from trendbot.notifications import NotificationService
from trendbot.paper.engine import PaperStatus, PaperTradingEngine


class PaperLoopRunner:
    """Drives the paper pipeline on an interval; rebuilds on config changes."""

    def __init__(
        self,
        database: Database,
        *,
        status: PaperStatus | None = None,
        notifier: NotificationService | None = None,
        products: tuple[str, ...] = ("BTC-USD", "ETH-USD"),
        poll_seconds: float = 2.0,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self._database = database
        self._strategy_engine = StrategyEngine(database)
        self._rollup = HourlyRollupService(database)
        self._notifier = notifier
        self._products = products
        self._poll_seconds = poll_seconds
        # Injectable clock for tests; production uses the real UTC clock via
        # engine.process_once()'s own default.
        self._now_provider = now_provider
        self.status = status or PaperStatus()
        self._engine: PaperTradingEngine | None = None
        self._stop_requested = False

    async def run(self) -> None:
        self._stop_requested = False
        try:
            while not self._stop_requested:
                await asyncio.sleep(self._poll_seconds)
                try:
                    self.cycle()
                except Exception as exc:  # noqa: BLE001 - the loop must survive
                    self.status.details["last_error"] = str(exc)
                    if self._notifier is not None:
                        self._notifier.problem(
                            "paper_loop_error",
                            f"The paper trading loop hit an error: {exc}",
                        )
        finally:
            self.status.running = False

    def stop(self) -> None:
        self._stop_requested = True

    def cycle(self) -> str | None:
        """One unit of work: rollup + config sync + candle processing."""
        for product_id in self._products:
            self._rollup.rollup(product_id)

        config = self._strategy_engine.current_config()
        if config is None:
            self.status.running = False
            return None

        current_hash = self._engine.config.config_hash() if self._engine else None
        if current_hash != config.config_hash():
            # A new/changed strategy: discard the old in-memory window and
            # rebuild. Positions and cash persist in the database; the new
            # engine's recover() cancels any in-flight intents from the old
            # configuration instead of acting on them.
            self._engine = PaperTradingEngine(
                self._database,
                FakeExchangeAdapter(),
                product_id=config.product_id,
                timeframe=config.timeframe,
                config=config,
                status=self.status,
                notifier=self._notifier,
                signal_recorder=self._strategy_engine.record_decision,
            )
            self._engine.recover()
            self.status.details["last_config_change"] = (
                f"strategy config {config.config_hash()[:12]}… active"
            )

        assert self._engine is not None
        self.status.running = True
        return self._engine.process_once(
            now=self._now_provider() if self._now_provider else None
        )
