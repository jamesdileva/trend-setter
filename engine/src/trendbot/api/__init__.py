"""Local API: FastAPI routes, schemas, and the loopback boundary.

The API exposes read models and narrowly scoped commands only. Order
submission is never exposed here — only the engine execution path can
trade, after risk approval (architecture.md §15).
"""
