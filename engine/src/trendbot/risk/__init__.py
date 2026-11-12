"""Risk: the mandatory gate between decisions and orders (architecture.md §9).

Every order intent passes the risk manager — no strategy, UI, or code
path can bypass it. Rejections are persisted with reasons.
"""
