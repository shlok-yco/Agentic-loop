import json
from typing import Any, TypedDict, Annotated, Sequence, Optional
from dotenv import load_dotenv

import pandas as pd

from langchain_core.tools import tool
from langgraph.prebuilt import ToolNode
from langchain_core.messages import (
    BaseMessage,
)  # The foundational class for all message types in LangGraph
from langchain_core.messages import (
    ToolMessage,
)  # Passes data back to LLM after it calls a tool such as the content and the tool call_id
from langchain_core.messages import (
    SystemMessage,
)  # Message for providing instructions to the LLM
from langchain_core.tools import tool
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages


from src.prompts import supervisor_prompt
from src.agents.common.model_call import LLMService
from src.agents.engineering import lead_engineer_node

load_dotenv()


@tool
def lead_data_engineer(summary, tasks, input_artifact, output_artifacts):
    """
    Execute the Lead Data Engineer sub-agent workflow.

    Args:
        summary (str): summary of the task to be done in clear NLP
        tasks (List[str]): List of tasks in clear NLP to be executed by the lead data engineer and his team.
        input_artifacts (Dict[str, str]): input artifacts path mapped to their names
        output_artifacts (Dict[str, str]): expected output artifacts path mapped to their names
    """
    subagent_input = {
        "messages": [("user", f"Task Summary: {summary}\n Tasks: {tasks}")],
        "task_summary": summary,
        "tasks": tasks,
        "input_artifacts": input_artifact,
        "output_artifacts": output_artifacts,
    }
    result = lead_engineer_node.invoke(subagent_input)
    return json.dumps(result["messages"][0].content)


SUPERVISOR_TOOLS = [lead_data_engineer]


llm = LLMService(tools=SUPERVISOR_TOOLS)


class SupervisorState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    task: str
    input_artifact: Optional[str]
    output_artifact: Optional[str]


def Supervisor(state: SupervisorState) -> SupervisorState:
    response = llm.invoke_agent(state=state, system_prompt=supervisor_prompt)
    return {"messages": [response]}


def should_continue(state: SupervisorState):
    messages = state["messages"]
    last_message = messages[-1]
    if not last_message.tool_calls:
        return "end"
    else:
        return "continue"


graph = StateGraph(SupervisorState)
graph.add_node("Supervisor", Supervisor)

tool_node = ToolNode(tools=SUPERVISOR_TOOLS)
graph.add_node("tools", tool_node)

graph.set_entry_point("Supervisor")

graph.add_conditional_edges(
    "Supervisor", should_continue, {"continue": "tools", "end": END}
)

graph.add_edge("tools", "Supervisor")

app = graph.compile()


def print_stream(stream):
    for s in stream:
        message = s["messages"][-1]
        if isinstance(message, tuple):
            print(message)
        else:
            message.pretty_print()


inputs = {"messages": [("user", "Add 3+4")]}

print_stream(app.stream(inputs, stream_node="values"))
