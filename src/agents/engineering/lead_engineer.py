import json
from typing import Any, TypedDict, Annotated, Sequence, Optional, Dict, List
from dotenv import load_dotenv

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
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages


from .tools import ENGINEERING_TOOLS
from src.agents.common.utils import setup_logger
from src.prompts import dataengineer_prompt
from src.agents.common.model_call import LLMService

load_dotenv()

lde_logger = setup_logger("lead_engineer", "logs/lead_engineer.log")

llm = LLMService(tools=ENGINEERING_TOOLS)


class LdeState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    task_summary: str
    tasks: List[str]
    input_artifacts: Dict[str, str]
    output_artifacts: Dict[str, str]
    summary: str


def LDE(state: LdeState) -> LdeState:
    response = llm.invoke_agent(state=state, system_prompt=dataengineer_prompt)
    lde_logger.info(response)
    return {"messages": [response]}


def should_continue(state: LdeState):
    messages = state["messages"]
    last_message = messages[-1]
    if not last_message.tool_calls:
        return "end"
    else:
        return "continue"


graph = StateGraph(LdeState)
graph.add_node("lde", LDE)

tool_node = ToolNode(tools=ENGINEERING_TOOLS)
graph.add_node("tools", tool_node)

graph.set_entry_point("lde")

graph.add_conditional_edges("lde", should_continue, {"continue": "tools", "end": END})

graph.add_edge("tools", "lde")

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
