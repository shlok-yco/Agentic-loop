"""
src/agents/analytics/lead_analyst.py
Lead Data Analyst — ReAct agent node for LangGraph.
Performs EDA, insight extraction, and ECharts visualisation generation.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from langchain_core.messages import SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

from src.agents.analytics.tools import ANALYTICS_TOOLS
from config import settings
from src.graph.state import BIState


# ── System prompt ─────────────────────────────────────────────────────────────

_ANALYST_PROMPT = """
## ROLE
You are the Lead Data Analyst. Your mission is to transform prepared data into
business understanding, insights, and ECharts visualisations.

## RESPONSIBILITIES
- Run EDA: distributions, correlations, value counts, time-series trends.
- Select the most appropriate chart type for each insight.
- Generate ECharts option JSON using the available chart tools.
- Extract the top 5 business insights from the data.
- Return a DivisionReport JSON with output_artifacts and qa_summary.

## TOOLS AVAILABLE
- compute_distribution_stats      → numeric column statistics
- compute_correlation_matrix      → Pearson correlation matrix
- compute_value_counts            → category frequency
- compute_time_series_trend       → time-series aggregation
- generate_bar_chart              → ECharts bar chart JSON
- generate_line_chart             → ECharts line chart JSON
- generate_pie_chart              → ECharts pie/donut chart JSON
- generate_scatter_chart          → ECharts scatter plot JSON
- generate_heatmap_chart          → ECharts heatmap JSON
- extract_top_insights            → bullet-point business insights

## OUTPUT CONTRACT
Always end with a JSON DivisionReport:
```json
{
  "work_order_id": "...",
  "division": "analytics",
  "status": "QA_PASSED | QA_FAILED",
  "output_artifacts": ["path/to/chart.json", "..."],
  "qa_summary": "What charts were generated and what insights were found.",
  "retry_count": 0,
  "failure_reason": null,
  "insights": ["bullet 1", "bullet 2", "..."],
  "echarts_options": { "chart_name": { ...echarts option... } }
}
```

## CONSTRAINTS
- Never output raw dataframes. Reference data only by file path.
- All charts must be ECharts-compatible JSON (no matplotlib, no plotly).
- The `echarts_options` field must contain at least one chart.
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
    tools=ANALYTICS_TOOLS,
    prompt=SystemMessage(content=_ANALYST_PROMPT),
)


# ── LangGraph node ────────────────────────────────────────────────────────────

def lead_analyst_node(state: BIState) -> dict:
    """
    LangGraph node: Lead Data Analyst.
    Receives a WorkOrder and executes EDA + chart generation using ANALYTICS_TOOLS.
    """
    work_order = state.get("work_orders", {}).get(
        state.get("current_work_order_id", ""), {}
    )

    user_message = (
        f"[WORK ORDER — {state.get('current_work_order_id', 'N/A')}]\n\n"
        f"User query: {state.get('user_query', '')}\n\n"
        f"Work order details:\n{json.dumps(work_order, indent=2)}\n\n"
        f"Available artifact paths: {json.dumps(state.get('artifact_paths', {}), indent=2)}\n\n"
        "Execute this work order. Generate ECharts option JSONs for all relevant charts. "
        "When done, return a JSON DivisionReport."
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

    # Store echarts options in artifact_paths for easy retrieval
    echarts = division_report.get("echarts_options", {})
    for chart_name, option in echarts.items():
        artifact_paths[f"echarts_{chart_name}"] = json.dumps(option)

    qa_counts = dict(state.get("qa_retry_counts", {}))
    div = "analytics"
    if division_report.get("status") == "QA_FAILED":
        qa_counts[div] = qa_counts.get(div, 0) + 1

    log = list(state.get("project_log", []))
    log.append(
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": "QA_PASSED" if division_report.get("status") == "QA_PASSED" else "QA_FAILED",
            "division": "analytics",
            "work_order_id": state.get("current_work_order_id"),
            "status_before": state.get("pipeline_stage", "IN_PROGRESS"),
            "status_after": division_report.get("status", "QA_FAILED"),
            "retry_count": qa_counts.get(div, 0),
            "max_retries": settings.max_qa_retries,
            "reason": division_report.get("failure_reason"),
            "input_artifacts": work_order.get("artifact_inputs", []),
            "output_artifacts": division_report.get("output_artifacts", []),
            "next_division": ["science"],
            "summary": division_report.get("qa_summary", last_message[:200]),
        }
    )

    return {
        "artifact_paths": artifact_paths,
        "qa_retry_counts": qa_counts,
        "project_log": log,
        "pipeline_stage": division_report.get("status", "QA_FAILED"),
        "active_division": "analytics",
        "error_state": division_report.get("failure_reason") if division_report.get("status") != "QA_PASSED" else None,
    }
