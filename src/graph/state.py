"""
src/graph/state.py — Shared state definitions for the LangGraph pipeline.

Provides BIState (used by the FastAPI layer in main.py) as an alias
for the canonical SupervisorState.
"""

from src.graph.supervisor import SupervisorState

# Alias used by main.py / FastAPI endpoints
BIState = SupervisorState

__all__ = ["BIState"]
