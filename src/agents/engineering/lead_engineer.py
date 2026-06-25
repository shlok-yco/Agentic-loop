import json
from pathlib import Path
from typing import TypedDict, Annotated, Sequence, Dict, List
from dotenv import load_dotenv

from langgraph.prebuilt import ToolNode
from langchain_core.messages import (
    BaseMessage,
)  # The foundational class for all message types in LangGraph
from langchain_core.messages import (
    ToolMessage,
)  # Passes data back to LLM after it calls a tool such as the content and the tool call_id
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages


from .tools import ENGINEERING_TOOLS
from src.agents.common.utils import setup_logger
from src.prompts import dataengineer_prompt
from src.agents.common.model_call import LLMService

load_dotenv()

lde_logger = setup_logger("lead_engineer", "logs/lead_engineer.log")

llm = LLMService(tools=ENGINEERING_TOOLS)

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
        lde_logger.error(f"Failed to append live log: {e}")

class LdeState(TypedDict):
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
    # Output
    execution_summary: str
    report_submitted: bool


######################################
#              LDE NODE              #
######################################


def LDE(state: LdeState) -> LdeState:
    context = f"""
    Current Tasks: {state['tasks']}
    Input Artifacts: {state['input_artifacts']}
    Required Output Artifacts: {state['output_artifacts']}
    """
    state["messages"].append(("user", context))
    response = llm.invoke_agent(state=state, system_prompt=dataengineer_prompt+ f"\nContext: {context}")
    
    log_entry = {
        "division": "Data Engineer",
        "event_type": "THINKING",
        "content": response.content,
        "tool_calls": [{"name": tc["name"], "args": tc.get("args", {})} for tc in getattr(response, "tool_calls", [])] if getattr(response, "tool_calls", None) else []
    }
    _append_live_log(state.get("run_id", ""), log_entry)

    lde_logger.info(response)
    return {"messages": [response]}


#####################################
#       State Updater Node          #
#####################################


def update_state(state: LdeState):

    completed = state.get("completed_tasks", [])
    failed = state.get("failed_tasks", [])
    generated_artifacts = state.get("generated_artifacts", {})

    tool_messages = [
        m for m in state["messages"]
        if isinstance(m, ToolMessage)
    ]

    if not tool_messages:
        return {}

    latest = tool_messages[-1]

    lde_logger.info(
        f"""
        TOOL MESSAGE
        tool_call_id={latest.tool_call_id}
        name={getattr(latest, 'name', None)}
        content={latest.content}
        """
    )

    # Try to parse the tool output as JSON
    content_str = latest.content if isinstance(latest.content, str) else str(latest.content)
    try:
        payload = json.loads(content_str)
    except (json.JSONDecodeError, TypeError, ValueError):
        # Not JSON — this can happen with tools that return raw text (e.g. code)
        lde_logger.warning(
            f"Non-JSON tool output from '{getattr(latest, 'name', '?')}' "
            f"(len={len(content_str)}). Skipping state update for this message."
        )
        return {}

    # Handle double-encoded JSON: json.loads succeeded but returned a string
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            return {}

    if not isinstance(payload, dict):
        return {}

    log_entry = {
        "division": "Data Engineer",
        "event_type": "ACTION",
        "content": "",
        "tool_result": latest.content
    }
    _append_live_log(state.get("run_id", ""), log_entry)

    #
    # Artifact tracking
    #
    generated_artifacts.update(
        payload.get("generated_artifacts", {})
    )

    if "output_path" in payload:
        artifact_name = Path(payload["output_path"]).name
        generated_artifacts[artifact_name] = payload["output_path"]

    #
    # Final engineer report submitted
    #
    if getattr(latest, "name", None) == "submit_engineer_report":

        return {
            "execution_summary": payload.get("summary", ""),
            "completed_tasks": payload.get(
                "completed_tasks",
                completed,
            ),
            "failed_tasks": payload.get(
                "failed_tasks",
                failed,
            ),
            "generated_artifacts": generated_artifacts,
            "pending_tasks": [],
            "report_submitted": True,
            "response_data": payload.get("response_data"),
        }

    #
    # Validation tracking
    #
    status = payload.get("status")

    if status == "PASSED":
        task_name = (
            state["pending_tasks"][0]
            if state["pending_tasks"]
            else None
        )

        if task_name and task_name not in completed:
            completed.append(task_name)

    elif status == "FAILED":
        task_name = (
            state["pending_tasks"][0]
            if state["pending_tasks"]
            else None
        )

        if task_name and task_name not in failed:
            failed.append(task_name)

    return {
        "completed_tasks": completed,
        "failed_tasks": failed,
        "generated_artifacts": generated_artifacts,
    }


######################################
#      SHOULD_CONTINUE NODE          #
######################################


def should_continue(state):
    if state.get("report_submitted", False):
        return "end"

    if not state.get("pending_tasks"):
        return "end"
    last_message = state["messages"][-1]

    if last_message.tool_calls:
        return "continue"

    tool_messages = [m for m in state["messages"] if isinstance(m, ToolMessage)]

    report_submitted = any(
        "ENGINEERING_REPORT" in str(m.content) for m in tool_messages
    )

    return "end" if report_submitted else "continue"


graph = StateGraph(LdeState)
graph.add_node("lde", LDE)
graph.add_node(
    "update_state",
    update_state,
)

tool_node = ToolNode(tools=ENGINEERING_TOOLS)
graph.add_node("tools", tool_node)

graph.set_entry_point("lde")

graph.add_conditional_edges("lde", should_continue, {"continue": "tools", "end": END})

# graph.add_edge("tools", "lde")
graph.add_edge(
    "tools",
    "update_state",
)

graph.add_edge(
    "update_state",
    "lde",
)

lead_engineer_node = graph.compile()

"""
def print_stream(stream):
    for s in stream:
        message = s["messages"][-1]
        if isinstance(message, tuple):
            print(message)
        else:
            message.pretty_print()


inputs = {"messages": [("user", "Add 3+4")]}

print_stream(lead_engineer_node.stream(inputs, stream_node="values"))
"""
