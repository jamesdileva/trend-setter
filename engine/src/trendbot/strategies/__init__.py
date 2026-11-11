"""Strategy modules: configuration, indicators, and decisions.

Strategies are deterministic components that produce decisions — they never
place orders and must not import ``trendbot.exchange`` or
``trendbot.execution`` (architecture.md §3 and §8).
"""
