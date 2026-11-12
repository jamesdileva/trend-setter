"""Paper trading: simulated funds, real pipeline (architecture.md §12).

Paper mode uses live market data and the exact strategy/risk/execution
pipeline — but every fill is simulated and every balance is isolated
under ``account_kind="paper"``. Nothing in this package touches a real
Coinbase endpoint.
"""
