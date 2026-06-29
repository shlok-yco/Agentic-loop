import json
from pathlib import Path
from dotenv import load_dotenv
from typing_extensions import TypedDict
from typing import Annotated, List, Sequence, Dict

from langchain_core.messages import BaseMessage
from langgraph.prebuilt import ToolNode
from langgraph.graph import StateGraph, END
from langchain_core.messages import ToolMessage
from langgraph.graph.message import add_messages

from src.prompts import dataanalyst_prompt
from src.agents.common.model_call import LLMService
from src.agents.analytics.tools import ANALYST_TOOLS
from src.agents.common import setup_logger

load_dotenv()
llm_service = LLMService(tools=ANALYST_TOOLS)
lda_logger = setup_logger("lead_analyst", "logs/lead_analyst.log")

# Maximum number of message pairs to keep in context to avoid blowing the window
MAX_CONTEXT_MESSAGES = 20


def _append_live_log(run_id: str, log_entry: dict):
    if not run_id:
        return
    log_file = Path(f"workspace/{run_id}/live_logs.json")
    try:
        logs = []
        if log_file.exists():
            with open(log_file, "r", encoding="utf-8") as f:
                try:
                    logs = json.load(f)
                except json.JSONDecodeError:
                    pass
        logs.append(log_entry)
        with open(log_file, "w", encoding="utf-8") as f:
            json.dump(logs, f)
    except Exception as e:
        lda_logger.error(f"Failed to append live log: {e}")

class AnalystState(TypedDict):
    run_id: str
    messages: Annotated[Sequence[BaseMessage], add_messages]

    # Input
    task_summary: str

    # Work
    tasks: List[str]
    pending_tasks: List[str]
    completed_tasks: List[str]
    failed_tasks: List[str]

    generated_artifacts: Dict[str, str]

    input_artifacts: Dict[str, str]
    output_artifacts: Dict[str, str]
    response_format: str

    # Output
    execution_summary: str
    business_objectives: Dict
    preprocessing_blueprint: Dict
    approved_insights: Dict
    approved_visualizations: Dict

    report_submitted: bool


############################
#     LDA NODE             #
############################
async def LDA(state: AnalystState):

    # Build context string so the LLM knows what to work with
    context = f"""
    Task Summary: {state.get('task_summary', '')}
    Tasks: {state.get('tasks', [])}
    Input Artifacts: {state.get('input_artifacts', {})}
    Required Output Artifacts: {state.get('output_artifacts', {})}
    Response Format: {state.get('response_format', 'JSON')}
    Completed Tasks: {state.get('completed_tasks', [])}
    Generated Artifacts: {state.get('generated_artifacts', {})}
    """

    # Message truncation: keep system prompt fresh but trim old exchanges safely
    messages = list(state["messages"])
    if len(messages) > MAX_CONTEXT_MESSAGES:
        from langchain_core.messages import trim_messages
        trimmed = trim_messages(
            messages,
            max_tokens=MAX_CONTEXT_MESSAGES,
            strategy="last",
            token_counter=len,
            include_system=True,
            allow_partial=False,
            start_on=["human", "ai"],
        )
        # Ensure the very first original user task is kept for grounding
        if trimmed and getattr(trimmed[0], "content", "") != getattr(messages[0], "content", ""):
            messages = [messages[0]] + trimmed
        else:
            messages = trimmed

    truncated_state = {**state, "messages": messages}

    response = await llm_service.ainvoke_agent(
        state=truncated_state,
        system_prompt=dataanalyst_prompt + f"\nContext: {context}",
    )

    log_entry = {
        "division": "Data Analyst",
        "event_type": "THINKING",
        "content": response.content,
        "tool_calls": [{"name": tc["name"], "args": tc.get("args", {})} for tc in getattr(response, "tool_calls", [])] if getattr(response, "tool_calls", None) else []
    }
    _append_live_log(state.get("run_id", ""), log_entry)

    lda_logger.info(response)

    return {"messages": [response]}


############################
#     Update State Node    #
############################
def update_state(state: AnalystState):

    completed = list(state.get("completed_tasks", []))
    failed = list(state.get("failed_tasks", []))
    artifacts = dict(state.get("generated_artifacts", {}))

    tool_messages = [m for m in state["messages"] if isinstance(m, ToolMessage)]

    if not tool_messages:
        return {}

    latest = tool_messages[-1]

    lda_logger.info(
        f"TOOL MESSAGE: name={getattr(latest, 'name', None)} "
        f"content={str(latest.content)[:500]}"
    )

    try:
        payload = json.loads(latest.content)
    except (json.JSONDecodeError, TypeError):
        try:
            payload = json.loads(str(latest.content).replace("'", '"'))
        except Exception:
            return {}

    # Handle double-encoded JSON: json.loads succeeded but returned a string
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            return {}

    # Final guard: if payload is still not a dict, bail out
    if not isinstance(payload, dict):
        return {}

    log_entry = {
        "division": "Data Analyst",
        "event_type": "ACTION",
        "content": "",
        "tool_result": latest.content
    }
    _append_live_log(state.get("run_id", ""), log_entry)

    # Track artifact creation
    artifact_type = payload.get("artifact_type")
    artifact_path = payload.get("artifact_path")

    if artifact_type and artifact_path:
        artifacts[artifact_type] = artifact_path

    # Track generated_artifacts from report payloads
    if "generated_artifacts" in payload:
        artifacts.update(payload["generated_artifacts"])

    #
    # Final report submitted
    #
    if payload.get("report_submitted") or payload.get("analysis_report"):

        return {
            "completed_tasks": payload.get("completed_tasks", completed),
            "failed_tasks": payload.get("failed_tasks", failed),
            "generated_artifacts": artifacts,
            "execution_summary": payload.get("analysis_report", ""),
            "report_submitted": True,
            "response_data": payload.get("response_data"),
        }

    #
    # Task status tracking
    #
    task_name = state["pending_tasks"][0] if state.get("pending_tasks") else None
    status = payload.get("status")

    if status == "PASSED" and task_name and task_name not in completed:
        completed.append(task_name)
    elif status == "FAILED" and task_name and task_name not in failed:
        failed.append(task_name)

    return {
        "completed_tasks": completed,
        "failed_tasks": failed,
        "generated_artifacts": artifacts,
    }


def should_continue(state):

    if state.get("report_submitted", False):
        return "end"

    if not state.get("pending_tasks"):
        return "end"

    last_message = state["messages"][-1]

    # Only continue to tools if there are actual tool calls
    if getattr(last_message, "tool_calls", None):
        return "continue"

    # No tool calls — loop back to LDA to let it decide what to do next
    # But guard against infinite loops: if we've had too many messages, end
    if len(state["messages"]) > 60:
        return "end"

    return "continue"


###########################
#         GRAPH           #
###########################

graph_build = StateGraph(AnalystState)
graph_build.add_node("lda", LDA)
graph_build.add_node("update_state", update_state)
graph_build.add_node("tools", ToolNode(tools=ANALYST_TOOLS, handle_tool_errors=True))

graph_build.set_entry_point("lda")

graph_build.add_conditional_edges(
    "lda",
    should_continue,
    {
        "continue": "tools",
        "end": END,
    },
)

graph_build.add_edge("tools", "update_state")
graph_build.add_edge("update_state", "lda")

lead_analyst_node = graph_build.compile()
