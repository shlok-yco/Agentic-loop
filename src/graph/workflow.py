"""
src/graph/workflow.py — Compiled LangGraph application.

Re-exports the compiled supervisor graph as `app_graph` for use
by the FastAPI server (main.py).
"""

from src.graph.supervisor import app as app_graph

__all__ = ["app_graph"]
