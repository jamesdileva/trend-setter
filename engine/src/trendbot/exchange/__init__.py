"""Exchange adapters: the Coinbase adapter, normalized types, and the fake adapter.

Strategies must never import from this package (architecture.md §3): a
strategy produces a decision; only the execution layer touches an adapter.
"""
