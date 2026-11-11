"""Pure indicator functions, independently tested against reference fixtures.

Conventions (implementation.md §8): calculations run on floats after
validated Decimal conversion; every function returns one output per input
value, with ``None`` for the warm-up window; the same conventions apply in
backtest, paper, and live.
"""
