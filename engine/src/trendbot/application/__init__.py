"""Application layer: use cases, orchestration, lifecycle state.

Module ownership per ``implementation.md`` §2. This layer must not import
from ``exchange/`` or ``execution/`` implementations directly — it works
against interfaces.
"""
