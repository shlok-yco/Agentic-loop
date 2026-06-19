# pyrefly: ignore [missing-import]
from typing import Sequence
from typing_extension import TypedDict
from langgraph.graph.message import add_messages

class MetaAgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]

    