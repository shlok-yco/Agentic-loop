"""
src/agents/science/lead_scientist.py
Lead Data Scientist — ReAct agent node for LangGraph.
Handles feature engineering, model training, evaluation, and SHAP explainability.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from langchain_core.messages import SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

from src.agents.science.tools import SCIENCE_TOOLS
from config import settings
from src.graph.state import BIState


# ── System prompt ─────────────────────────────────────────────────────────────

_SCIENTIST_PROMPT = """
## ROLE
You are the Lead Data Scientist. You are activated only when predictive or
prescriptive outcomes are required. You transform analytical findings into
forecasts, predictions, and machine learning solutions.

## RESPONSIBILITIES
- Engineer features from cleaned data (lag, rolling, encoding, decomposition).
- Select the appropriate model type (classifier or regressor).
- Train, evaluate, and report model performance.
- Run SHAP explainability and produce a feature-importance ECharts chart.
- Return a DivisionReport JSON with model metrics and output artifacts.

## TOOLS AVAILABLE
- engineer_features               → lag/rolling/encoding feature creation
- train_classifier                → sklearn classifier with evaluation metrics
- train_regressor                 → sklearn regressor with evaluation metrics
- explain_model_shap              → SHAP feature importance + ECharts option
- compute_feature_importance      → quick feature ranking (no model saving)

## QA THRESHOLDS
- Classifier: accuracy >= 0.70 → QA_PASSED
- Regressor:  R² >= 0.70       → QA_PASSED
- Below threshold              → QA_FAILED (CTO will decide on retry / HITL)

## OUTPUT CONTRACT
Always end with a JSON DivisionReport:
```json
{
  "work_order_id": "...",
  "division": "science",
  "status": "QA_PASSED | QA_FAILED",
  "output_artifacts": ["path/to/model.pkl", "path/to/report.json"],
  "qa_summary": "Model type, key metrics, threshold comparison.",
  "retry_count": 0,
  "failure_reason": null,
  "model_metrics": { "accuracy": 0.85, "roc_auc": 0.91 },
  "echarts_options": { "shap_importance": { ...echarts option... } }
}
```

## CONSTRAINTS
- Never fabricate metric values — always use actual tool outputs.
- SHAP is required for every model delivered to the CTO.
- All charts must be ECharts-compatible JSON.
"""


# ── LLM ──────────────────────────────────────────────────────────────────────

_llm = ChatOpenAI(
    model=settings.llm_model,
    temperature=settings.llm_temperature,
    api_key=settings.openai_api_key_str,
)

# ── ReAct agent ───────────────────────────────────────────────────────────────

_agent = create_react_agent(
    model=_llm,
    tools=SCIENCE_TOOLS,
    prompt=SystemMessage(content=_SCIENTIST_PROMPT),
)


# ── LangGraph node ────────────────────────────────────────────────────────────

def lead_scientist_node(state: BIState) -> dict:
    """
    LangGraph node: Lead Data Scientist.
    Executes feature engineering + model training/evaluation using SCIENCE_TOOLS.
    """
    work_order = state.get("work_orders", {}).get(
        state.get("current_work_order_id", ""), {}
    )

    user_message = (
        f"[WORK ORDER — {state.get('current_work_order_id', 'N/A')}]\n\n"
        f"User query: {state.get('user_query', '')}\n\n"
        f"Work order details:\n{json.dumps(work_order, indent=2)}\n\n"
        f"Available artifact paths: {json.dumps(state.get('artifact_paths', {}), indent=2)}\n\n"
        "Execute this work order. Train the appropriate model, evaluate it, "
        "run SHAP explainability, and return a JSON DivisionReport."
    )

    response = _agent.invoke({"messages": [{"role": "user", "content": user_message}]})
    last_message = response["messages"][-1].content

    division_report: dict = {}
    try:
        if "```json" in last_message:
            raw = last_message.split("```json")[1].split("```")[0].strip()
        elif "{" in last_message:
            start = last_message.index("{")
            end = last_message.rindex("}") + 1
            raw = last_message[start:end]
        else:
            raw = "{}"
        division_report = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        division_report = {"status": "QA_FAILED", "failure_reason": "Could not parse agent output."}

    artifact_paths = dict(state.get("artifact_paths", {}))
    for art in division_report.get("output_artifacts", []):
        key = art.split("/")[-1].replace(".", "_")
        artifact_paths[key] = art

    echarts = division_report.get("echarts_options", {})
    for chart_name, option in echarts.items():
        artifact_paths[f"echarts_{chart_name}"] = json.dumps(option)

    qa_counts = dict(state.get("qa_retry_counts", {}))
    div = "science"
    if division_report.get("status") == "QA_FAILED":
        qa_counts[div] = qa_counts.get(div, 0) + 1

    log = list(state.get("project_log", []))
    log.append(
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": "QA_PASSED" if division_report.get("status") == "QA_PASSED" else "QA_FAILED",
            "division": "science",
            "work_order_id": state.get("current_work_order_id"),
            "status_before": state.get("pipeline_stage", "IN_PROGRESS"),
            "status_after": division_report.get("status", "QA_FAILED"),
            "retry_count": qa_counts.get(div, 0),
            "max_retries": settings.max_qa_retries,
            "reason": division_report.get("failure_reason"),
            "input_artifacts": work_order.get("artifact_inputs", []),
            "output_artifacts": division_report.get("output_artifacts", []),
            "next_division": [],
            "summary": division_report.get("qa_summary", last_message[:200]),
        }
    )

    return {
        "artifact_paths": artifact_paths,
        "qa_retry_counts": qa_counts,
        "project_log": log,
        "pipeline_stage": division_report.get("status", "QA_FAILED"),
        "active_division": "science",
        "error_state": division_report.get("failure_reason") if division_report.get("status") != "QA_PASSED" else None,
    }
