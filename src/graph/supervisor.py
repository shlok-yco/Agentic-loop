"""
src/graph/supervisor.py
CTO / Supervisor node — orchestrates routing between divisions.
"""

from __future__ import annotations

import json
import uuid
import logging
from datetime import datetime, timezone

from langchain_core.messages import SystemMessage
from langchain_openai import ChatOpenAI

from prompts.supervisor import supervisor as SUPERVISOR_PROMPT
from config import settings
from src.graph.state import BIState

logging.basicConfig(level=logging.DEBUG, filename='logs/supervisor.log', filemode='w')
logger = logging.getLogger(__name__)

# ── LLM (no tools — the CTO only reasons and routes) ─────────────────────────

_llm = ChatOpenAI(
    model=settings.llm_model,
    temperature=0.0,  # deterministic routing
    api_key=settings.openai_api_key_str,
)

_system = SystemMessage(content=SUPERVISOR_PROMPT)


# ── helpers ───────────────────────────────────────────────────────────────────

def _next_wo_id(state: BIState) -> str:
    run_id = state.get("run_id", "RUN01")
    seq = len(state.get("work_orders", {})) + 1
    return f"WO-{run_id}-{seq:02d}"


def _parse_cto_response(text: str) -> dict:
    try:
        if "```json" in text:
            raw = text.split("```json")[1].split("```")[0].strip()
        elif "{" in text:
            start = text.index("{")
            end = text.rindex("}") + 1
            raw = text[start:end]
        else:
            raw = "{}"
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return {}


# ── supervisor node ───────────────────────────────────────────────────────────

def supervisor_node(state: BIState) -> dict:
    """
    CTO node.  Called at the start of every pipeline turn and after each
    division report.  Decides the next routing target and issues a WorkOrder.
    Returns a BIState delta understood by the graph router.
    """
    # Build context message for the CTO
    context = (
        f"Run ID: {state.get('run_id')}\n"
        f"User query: {state.get('user_query')}\n"
        f"Pipeline stage: {state.get('pipeline_stage', 'INIT')}\n"
        f"Active division: {state.get('active_division', 'none')}\n"
        f"QA retry counts: {json.dumps(state.get('qa_retry_counts', {}))}\n"
        f"Artifact paths: {json.dumps(list(state.get('artifact_paths', {}).keys()))}\n"
        f"Error state: {state.get('error_state')}\n\n"
        f"Last 3 log entries:\n"
        + json.dumps(state.get("project_log", [])[-3:], indent=2)
    )

    messages = [
        _system,
        {"role": "user", "content": context},
    ]

    response = _llm.invoke(messages)
    cto_output = _parse_cto_response(response.content)

    logging.info(cto_output)

    action = cto_output.get("action", {})
    target = action.get("target", "")
    action_type = action.get("type", "ROUTE")
    work_order_raw = action.get("work_order", {})
    log_update = cto_output.get("project_log_update", {})

    # Assign a work-order ID if missing
    wo_id = work_order_raw.get("work_order_id") or _next_wo_id(state)
    work_order_raw["work_order_id"] = wo_id

    # Register the work order in state
    work_orders = dict(state.get("work_orders", {}))
    work_orders[wo_id] = {
        "division": target.replace("lead_", ""),
        "status": "IN_PROGRESS",
        "retry_count": 0,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "artifact_inputs": work_order_raw.get("input_artifacts", []),
        "artifact_outputs": [],
        **work_order_raw,
    }

    # Append CTO log entry
    log = list(state.get("project_log", []))
    log.append(
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": "WORK_ORDER_ISSUED" if action_type == "ROUTE" else action_type,
            "division": "cto",
            "work_order_id": wo_id,
            "status_before": state.get("pipeline_stage", "INIT"),
            "status_after": "IN_PROGRESS",
            "retry_count": 0,
            "max_retries": settings.max_qa_retries,
            "reason": None,
            "input_artifacts": work_order_raw.get("input_artifacts", []),
            "output_artifacts": [],
            "next_division": [target],
            "summary": cto_output.get("cot", {}).get("intent_class", "") + " | " + log_update.get("notes", f"Routing to {target}."),
        }
    )

    return {
        "active_division": target,
        "current_work_order_id": wo_id,
        "work_orders": work_orders,
        "project_log": log,
        "pipeline_stage": action_type,
        # Carry user-facing message so FastAPI can stream it back
        "error_state": action.get("user_message") if action_type in ("REQUEST_CLARIFICATION", "HITL_PAUSE") else state.get("error_state"),
        "intent_class": cto_output.get("cot", {}).get("intent_class", state.get("intent_class", "EXPLORATORY")),
    }
