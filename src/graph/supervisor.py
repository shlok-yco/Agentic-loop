import json
import operator
from pathlib import Path
from typing import Any, TypedDict, Annotated, Sequence, List, Dict, Literal
import asyncio
from dotenv import load_dotenv

from langchain_core.tools import tool
from langgraph.prebuilt import ToolNode
from langchain_core.messages import (
    BaseMessage,
    ToolMessage,
    AIMessage,
)
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages


from src.prompts import supervisor_prompt
from src.agents.common.model_call import LLMService
from src.agents.engineering import lead_engineer_node
from src.agents.analytics import lead_analyst_node
from src.agents.common import setup_logger

supervisor_logger = setup_logger(
    "Supervisor",
    "logs/supervisor.log",
)
load_dotenv()

# Maximum number of messages to keep in context for the supervisor
MAX_SUPERVISOR_MESSAGES = 16


# ── Artifact → Step mapping ──────────────────────────────────────────────────

# Maps artifact keys (as they appear in generated_artifacts) to the step
# that should be considered complete when they exist.
ARTIFACT_STEP_MAP = {
    "data_profile": "data_preparation",
    "data_profile.json": "data_preparation",
    "data_summary": "data_preparation",
    "data_summary.json": "data_preparation",
    "clean_dataset": "data_preparation",
    "clean_dataset.csv": "data_preparation",
    "business_objectives": "analytics_and_visualization",
    "business_objectives.json": "analytics_and_visualization",
    "approved_insights": "analytics_and_visualization",
    "approved_insights.json": "analytics_and_visualization",
    "approved_visualizations": "analytics_and_visualization",
    "approved_visualizations.json": "analytics_and_visualization",
}

# Ordered list of steps for progression
STEP_ORDER = [
    "init",
    "data_preparation",
    "analytics_and_visualization",
    "visualization_completed",
]


async def _read_artifact_json(path: str) -> dict:
    """Try to read a JSON artifact from disk asynchronously, return {} on failure."""
    def read_sync():
        try:
            p = Path(path)
            if p.exists():
                content = p.read_text(encoding="utf-8")
                data = json.loads(content)
                return data if isinstance(data, dict) else {}
        except Exception:
            pass
        return {}
    return await asyncio.to_thread(read_sync)


def _next_step(current: str) -> str:
    """Return the next step in the pipeline, or current if at the end."""
    try:
        idx = STEP_ORDER.index(current)
        if idx + 1 < len(STEP_ORDER):
            return STEP_ORDER[idx + 1]
    except ValueError:
        pass
    return current


# ── Sub-agent tool wrappers ──────────────────────────────────────────────────


from langgraph.prebuilt import InjectedState

@tool
async def lead_data_engineer(
    summary: str, 
    tasks: List[str], 
    input_artifacts: Dict[str, str], 
    output_artifacts: Dict[str, str], 
    response_format: str,
    state: Annotated[dict, InjectedState] = None,
):
    """
    Execute the Lead Data Engineer sub-agent workflow.

    Args:
        summary (str): summary of the task to be done in clear NLP
        tasks (List[str]): List of tasks in clear NLP to be executed by the lead data engineer and his team.
        input_artifacts (Dict[str, str]): input artifacts path mapped to their names
        output_artifacts (Dict[str, str]): expected output artifacts name mapped with their description
        response_format (str): format of the response for the lead data engineer to return while calling. Take it from the prompt in each step.
    """
    # Inject workspace dirs into input artifacts so the subagent knows where to write
    if state:
        input_artifacts["output_dir"] = state.get("output_dir", "")
        input_artifacts["scripts_dir"] = state.get("scripts_dir", "")

    subagent_input = {
        "run_id": state.get("run_id", ""),
        "messages": [("user", f"Task Summary: {summary}\n Tasks: {tasks}")],
        "task_summary": summary,
        "tasks": tasks,
        "pending_tasks": tasks,
        "input_artifacts": input_artifacts,
        "output_artifacts": output_artifacts,
        "response_format": response_format,
        "report_submitted": False,
    }
    result = await lead_engineer_node.ainvoke(subagent_input)
    response_data_dict = {}
    if result.get("response_data"):
        try:
            # Handle possible markdown fences in the string
            resp_str = result["response_data"]
            if resp_str.startswith("```json"):
                resp_str = resp_str[7:]
            if resp_str.startswith("```"):
                resp_str = resp_str[3:]
            if resp_str.endswith("```"):
                resp_str = resp_str[:-3]
            response_data_dict = json.loads(resp_str.strip())
        except Exception:
            pass

    logs = []
    for m in result.get("messages", []):
        if isinstance(m, AIMessage) and (m.content or hasattr(m, "tool_calls")):
            logs.append({
                "division": "Data Engineer",
                "event_type": "THINKING",
                "content": m.content,
                "tool_calls": [{"name": tc["name"], "args": tc.get("args", {})} for tc in getattr(m, "tool_calls", [])] if getattr(m, "tool_calls", None) else []
            })
        elif isinstance(m, ToolMessage):
            logs.append({
                "division": "Data Engineer",
                "event_type": "ACTION",
                "content": "",
                "tool_result": m.content
            })

    return {
        "division": "Engineering",
        "status": "completed",
        "engineering_report": result.get("execution_summary"),
        "generated_artifacts": result.get("generated_artifacts", {}),
        "completed_tasks": result.get("completed_tasks", []),
        "failed_tasks": result.get("failed_tasks", []),
        "subagent_logs": logs,
        **response_data_dict,
    }


@tool
async def lead_analyst(
    summary: str,
    tasks: List[str],
    input_artifacts: Dict[str, str],
    output_artifacts: Dict[str, str],
    response_format: str,
    state: Annotated[dict, InjectedState] = None,
):
    """
    Execute the Lead Data Analyst sub-agent workflow.

    Args:
        summary (str):
            Summary of the analytical task in clear NLP.

        tasks (List[str]):
            List of analytical tasks to execute.

        input_artifacts (Dict[str, str]):
            Input artifact paths mapped by artifact name.

        output_artifacts (Dict[str, str]):
            Expected output artifact paths mapped by artifact name.

        response_format (str):
            Required response schema specified by the supervisor.
    """

    if state:
        input_artifacts["output_dir"] = state.get("output_dir", "")
        input_artifacts["scripts_dir"] = state.get("scripts_dir", "")

    subagent_input = {
        "run_id": state.get("run_id", ""),
        "messages": [
            (
                "user",
                f"Task Summary: {summary}\nTasks: {tasks}",
            )
        ],
        "task_summary": summary,
        "tasks": tasks,
        "pending_tasks": tasks,
        "input_artifacts": input_artifacts,
        "output_artifacts": output_artifacts,
        "response_format": response_format,
        "report_submitted": False,
    }

    result = await lead_analyst_node.ainvoke(subagent_input)

    generated = result.get("generated_artifacts", {})

    # Read generated artifacts from disk so the supervisor can see their content
    # instead of always getting empty {} from unset state fields
    artifact_content = {}
    for key, path in generated.items():
        content = await _read_artifact_json(path)
        if content:
            artifact_content[key] = content

    response_data_dict = {}
    if result.get("response_data"):
        try:
            # Handle possible markdown fences in the string
            resp_str = result["response_data"]
            if resp_str.startswith("```json"):
                resp_str = resp_str[7:]
            if resp_str.startswith("```"):
                resp_str = resp_str[3:]
            if resp_str.endswith("```"):
                resp_str = resp_str[:-3]
            response_data_dict = json.loads(resp_str.strip())
        except Exception:
            pass

    logs = []
    for m in result.get("messages", []):
        if isinstance(m, AIMessage) and (m.content or hasattr(m, "tool_calls")):
            logs.append({
                "division": "Data Analyst",
                "event_type": "THINKING",
                "content": m.content,
                "tool_calls": [{"name": tc["name"], "args": tc.get("args", {})} for tc in getattr(m, "tool_calls", [])] if getattr(m, "tool_calls", None) else []
            })
        elif isinstance(m, ToolMessage):
            logs.append({
                "division": "Data Analyst",
                "event_type": "ACTION",
                "content": "",
                "tool_result": m.content
            })

    return {
        "division": "Analytics",
        "status": "completed",
        "analysis_report": result.get("execution_summary"),
        "generated_artifacts": generated,
        "completed_tasks": result.get("completed_tasks", []),
        "failed_tasks": result.get("failed_tasks", []),
        "subagent_logs": logs,
        # Populated from disk artifacts (not empty state fields)
        "business_objectives": artifact_content.get(
            "business_objectives",
            artifact_content.get("business_objectives_path", {}),
        ),
        "preprocessing_blueprint": artifact_content.get(
            "preprocessing_blueprint", {},
        ),
        "approved_insights": artifact_content.get(
            "approved_insights", {},
        ),
        "approved_visualizations": artifact_content.get(
            "approved_visualizations", {},
        ),
        **response_data_dict,
    }


SUPERVISOR_TOOLS = [lead_data_engineer, lead_analyst]

from config import settings
llm = LLMService(tools=SUPERVISOR_TOOLS, model_name=settings.llm_model)


class SupervisorState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    run_id: str

    project_goal: str

    pending_tasks: List[str]

    delegated_tasks: Dict[str, str]

    completed_tasks: Dict[str, Any]

    failed_tasks: Dict[str, str]

    input_artifacts: Dict[str, str]

    output_artifacts: Dict[str, str]

    output_dir: str
    scripts_dir: str

    data_profile: Dict[str, str]
    data_summary: Dict[str, str]
    business_objectives: Dict[str, str]
    preprocessing_blueprint: Dict[str, str]

    cleaned_dt_sm_map_agg_res: Dict[str, str]

    approved_insights: Dict[str, str]
    approved_visualizations: Dict[str, str]

    current_step: Literal[
        "init",
        "data_preparation",
        "analytics_and_visualization",
        "visualization_completed",
    ]

    reports_received: Dict[str, str]

    project_complete: bool

    project_log: Annotated[List[Dict[str, Any]], operator.add]


########################################
# Supervisor Node #
########################################


async def Supervisor(state: SupervisorState) -> SupervisorState:

    # Build rich context for the supervisor
    current_step = state.get("current_step", "init")

    # Build artifact existence flags so the supervisor knows which steps are done
    artifact_flags = {
        "data_profile": bool(state.get("data_profile") or "data_profile" in state.get("output_artifacts", {})),
        "data_summary": bool(state.get("data_summary") or "data_summary" in state.get("output_artifacts", {})),
        "business_objectives": bool(state.get("business_objectives") or "business_objectives" in state.get("output_artifacts", {})),
        "preprocessing_blueprint": bool(state.get("preprocessing_blueprint") or "preprocessing_blueprint" in state.get("output_artifacts", {})),
        "clean_dataset": bool("clean_dataset" in state.get("output_artifacts", {})),
        "semantic_metadata": bool("semantic_metadata" in state.get("output_artifacts", {})),
        "aggregation_results": bool("aggregation_results" in state.get("output_artifacts", {})),
        "approved_insights": bool(state.get("approved_insights") or "approved_insights" in state.get("output_artifacts", {})),
        "approved_visualizations": bool(state.get("approved_visualizations") or "approved_visualizations" in state.get("output_artifacts", {})),
    }

    context_parts = [
        f"Current Step: {current_step}",
        f"Input Artifacts: {state.get('input_artifacts', {})}",
        f"Output Artifacts (produced so far): {state.get('output_artifacts', {})}",
        f"Artifact Existence: {artifact_flags}",
        f"Completed Tasks: {list(state.get('completed_tasks', {}).keys())[:10]}",
    ]
    context = "\n".join(context_parts)

    # Message truncation: keep the first message + last N to avoid context overflow
    messages = list(state["messages"])
    if len(messages) > MAX_SUPERVISOR_MESSAGES:
        # We must not orphan ToolMessages from their AIMessage tool_calls
        # A safer approach: keep the first message, and find a safe index to slice from the end
        safe_idx = len(messages) - (MAX_SUPERVISOR_MESSAGES - 1)
        
        # Ensure we don't split an AIMessage and its ToolMessages
        while safe_idx < len(messages) and getattr(messages[safe_idx], "type", "") == "tool":
            safe_idx -= 1
            
        messages = messages[:1] + messages[safe_idx:]

    truncated_state = {**state, "messages": messages}

    # Truncate large artifacts in state to avoid context overflow and high TTFT
    def _truncate_dict(d: dict, max_items=5) -> dict:
        if not isinstance(d, dict): return d
        res = {}
        for k, v in d.items():
            if isinstance(v, list) and len(v) > max_items:
                res[k] = v[:max_items] + [f"... ({len(v) - max_items} more items truncated)"]
            elif isinstance(v, dict):
                res[k] = _truncate_dict(v, max_items)
            else:
                res[k] = v
        return res

    for key in ["data_profile", "data_summary", "preprocessing_blueprint", "approved_visualizations"]:
        if truncated_state.get(key) and isinstance(truncated_state[key], dict):
            # Only truncate if it's very large
            if len(str(truncated_state[key])) > 2000:
                truncated_state[key] = _truncate_dict(truncated_state[key])

    response = await llm.ainvoke_agent(
        state=truncated_state,
        system_prompt=supervisor_prompt + f"\nContext: {context}",
    )
    supervisor_logger.info(response)

    # Fallback for LLMs that output tool arguments as JSON in content
    if not getattr(response, "tool_calls", None) and getattr(response, "content", ""):
        try:
            content_str = response.content.strip()
            if content_str.startswith("```json"):
                content_str = content_str[7:]
            if content_str.startswith("```"):
                content_str = content_str[3:]
            if content_str.endswith("```"):
                content_str = content_str[:-3]
            
            parsed = json.loads(content_str.strip())
            
            if isinstance(parsed, dict) and "tasks" in parsed:
                import uuid
                tool_name = "lead_data_engineer" if current_step in ["init", "data_preparation"] else "lead_analyst"
                
                tool_call = {
                    "name": tool_name,
                    "args": parsed,
                    "id": f"call_{uuid.uuid4().hex[:16]}"
                }
                
                response = AIMessage(
                    content="",
                    additional_kwargs=response.additional_kwargs,
                    response_metadata=response.response_metadata,
                    id=response.id,
                    tool_calls=[tool_call]
                )
                supervisor_logger.info(f"Synthesized tool call from content: {tool_call}")
        except Exception:
            pass

    log = {
        "division": "Supervisor",
        "event_type": "PLANNING",
        "content": response.content,
        "tool_calls": [{"name": tc["name"], "args": tc.get("args", {})} for tc in getattr(response, "tool_calls", [])] if getattr(response, "tool_calls", None) else []
    }

    return {"messages": [response], "project_log": [log]}


#######################################
# UPDATE PROJECT STATE NODE #
#######################################
def update_project_state(state: SupervisorState):
    tool_messages = [m for m in state["messages"] if isinstance(m, ToolMessage)]
    if not tool_messages:
        return {}

    latest_content = tool_messages[-1].content

    # Resilient JSON parsing — handle double-encoding and string payloads
    try:
        payload = json.loads(latest_content)
    except (json.JSONDecodeError, TypeError):
        try:
            # Sometimes tools return str(dict) instead of json.dumps(dict)
            payload = json.loads(latest_content.replace("'", '"'))
        except Exception:
            supervisor_logger.warning(
                f"Could not parse tool message as JSON: {str(latest_content)[:200]}"
            )
            return {}

    # If the payload itself is a string (double-encoded), parse again
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            return {}

    # ── Update Artifacts ─────────────────────────────────────────────────
    output_artifacts = dict(state.get("output_artifacts", {}))
    generated = payload.get("generated_artifacts", {})
    output_artifacts.update(generated)

    # ── Sync completed tasks ─────────────────────────────────────────────
    completed_input = payload.get("completed_tasks", [])
    completed_tasks = dict(state.get("completed_tasks", {}))
    for task in completed_input:
        completed_tasks[task] = payload.get("division", "unknown")

    # Filter pending
    completed_keys = set(completed_tasks.keys())
    pending_tasks = [
        t for t in state.get("pending_tasks", []) if t not in completed_keys
    ]

    # ── Step advancement and Backtracking ────────────────────────────────
    # Determine the highest step that has been completed based on ACTUAL artifacts
    # and remove any artifacts from state that no longer exist on disk.
    all_artifacts = list(output_artifacts.items()) + list(generated.items())
    valid_artifacts_keys = set()
    achieved_steps = set()

    for artifact_key, path in all_artifacts:
        if path and Path(path).exists():
            valid_artifacts_keys.add(artifact_key)
            # Check both the raw key and the basename
            step = ARTIFACT_STEP_MAP.get(artifact_key)
            if not step:
                basename = artifact_key.rsplit("/", 1)[-1] if "/" in artifact_key else artifact_key
                step = ARTIFACT_STEP_MAP.get(basename)
            if step:
                achieved_steps.add(step)
        else:
            # If it's missing, ensure it's removed from state output_artifacts
            if artifact_key in output_artifacts:
                del output_artifacts[artifact_key]

    # Calculate current step strictly based on highest achieved step
    # This automatically allows backtracking if artifacts were removed or missing
    new_step = "init"
    for step in STEP_ORDER:
        if step in achieved_steps:
            new_step = step
    
    current_step = new_step

    # Check if we've reached the final visualization step
    project_complete = current_step == "analytics_and_visualization" and (
        "approved_visualizations" in valid_artifacts_keys
        or "approved_visualizations.json" in valid_artifacts_keys
        or any("approved_visualizations" in k for k in valid_artifacts_keys)
    )

    if project_complete:
        current_step = "visualization_completed"

    # ── Populate state-level artifact fields from disk ────────────────────
    # These fields let the supervisor's prompt context see what artifacts exist
    state_artifact_updates = {}
    ARTIFACT_STATE_FIELDS = {
        "data_profile": "data_profile",
        "data_summary": "data_summary",
        "business_objectives": "business_objectives",
        "preprocessing_blueprint": "preprocessing_blueprint",
        "approved_insights": "approved_insights",
        "approved_visualizations": "approved_visualizations",
    }
    for artifact_key, state_field in ARTIFACT_STATE_FIELDS.items():
        # Check if this artifact was just generated or already exists
        artifact_path = generated.get(artifact_key) or output_artifacts.get(artifact_key)
        if artifact_path and Path(artifact_path).exists():
            if not state.get(state_field):
                state_artifact_updates[state_field] = {"generated": True, "path": artifact_path}
        else:
            if state.get(state_field):
                state_artifact_updates[state_field] = {}

    subagent_logs = payload.get("subagent_logs", [])

    return {
        "completed_tasks": completed_tasks,
        "output_artifacts": output_artifacts,
        "pending_tasks": pending_tasks,
        "current_step": current_step,
        "project_complete": project_complete,
        "reports_received": {
            **state.get("reports_received", {}),
            payload.get("division", "unknown"): True,
        },
        "project_log": subagent_logs,
        **state_artifact_updates,
    }


def should_continue(state):
    # This MUST be the very first check
    if state.get("project_complete", False):
        return "end"

    last_message = state["messages"][-1]

    if getattr(last_message, "tool_calls", None):
        return "continue"

    return "end"  # Default exit if no more tool calls and project is not complete


graph = StateGraph(SupervisorState)
graph.add_node("Supervisor", Supervisor)

tool_node = ToolNode(tools=SUPERVISOR_TOOLS, handle_tool_errors=True)
graph.add_node("tools", tool_node)

graph.add_node("update_project_state", update_project_state)

graph.set_entry_point("Supervisor")

graph.add_conditional_edges(
    "Supervisor",
    should_continue,
    {
        "continue": "tools",
        "end": END,
    },
)

graph.add_edge(
    "tools",
    "update_project_state",
)

graph.add_edge(
    "update_project_state",
    "Supervisor",
)

from langgraph.checkpoint.memory import MemorySaver
memory = MemorySaver()
app = graph.compile(checkpointer=memory)
