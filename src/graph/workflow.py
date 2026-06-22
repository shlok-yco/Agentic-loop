"""
src/graph/workflow.py
LangGraph StateGraph assembly — wires the CTO and three division agents.

Graph topology:
    START → supervisor → {lead_engineer | lead_analyst | lead_scientist | END}
              ↑______________________|
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from src.agents.analytics.lead_analyst import lead_analyst_node
from src.agents.engineering.lead_engineer import lead_engineer_node
from src.agents.science.lead_scientist import lead_scientist_node
from config import settings
from src.graph.state import BIState
from src.graph.supervisor import supervisor_node


# ── routing function ──────────────────────────────────────────────────────────

def _route(state: BIState) -> str:
    """
    Conditional edge: read `active_division` set by the supervisor node and
    return the name of the next node to execute.
    """
    stage = state.get("pipeline_stage", "")
    target = state.get("active_division", "")

    # Terminal conditions
    if stage in ("PROJECT_COMPLETE", "HITL_PAUSE"):
        return END

    # Max-retry circuit-breaker per division
    qa_counts = state.get("qa_retry_counts", {})
    div = target.replace("lead_", "")
    if qa_counts.get(div, 0) >= settings.max_qa_retries:
        return END  # CTO will surface HITL on next call

    node_map = {
        "lead_engineer": "lead_engineer",
        "lead_analyst": "lead_analyst",
        "lead_scientist": "lead_scientist",
    }
    return node_map.get(target, END)


# ── graph assembly ────────────────────────────────────────────────────────────

def build_graph() -> StateGraph:
    graph = StateGraph(BIState)

    # Register nodes
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("lead_engineer", lead_engineer_node)
    graph.add_node("lead_analyst", lead_analyst_node)
    graph.add_node("lead_scientist", lead_scientist_node)

    # Entry point
    graph.add_edge(START, "supervisor")

    # Conditional routing from supervisor
    graph.add_conditional_edges(
        "supervisor",
        _route,
        {
            "lead_engineer": "lead_engineer",
            "lead_analyst": "lead_analyst",
            "lead_scientist": "lead_scientist",
            END: END,
        },
    )

    # All division agents report back to the supervisor
    graph.add_edge("lead_engineer", "supervisor")
    graph.add_edge("lead_analyst", "supervisor")
    graph.add_edge("lead_scientist", "supervisor")

    return graph


def compile_graph():
    """
    Return a compiled, runnable LangGraph app.
    Uses an in-memory checkpointer (swap for SqliteSaver for persistence).
    """
    from langgraph.checkpoint.memory import MemorySaver

    graph = build_graph()
    checkpointer = MemorySaver()
    return graph.compile(checkpointer=checkpointer)


# Singleton compiled graph — import this in FastAPI / Streamlit
app_graph = compile_graph()
