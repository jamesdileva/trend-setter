"""trendbot — the trading engine for the Coinbase Automated Trend-Follower.

Package layout and module ownership are defined in ``implementation.md``.
The engine is paper-first: live execution requires explicit arming and every
order intent passes the risk manager (see ``architecture.md`` sections 5,
9, and 10).
"""

__version__ = "0.1.0"
