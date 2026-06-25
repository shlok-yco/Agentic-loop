from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage


class LLMService:
    def __init__(self, tools, model_name="gpt-5.2"):
        self.model = ChatOpenAI(model=model_name).bind_tools(tools)

    def invoke_agent(self, state, system_prompt):
        # 1. Prepare messages (inject system prompt at the start)
        messages = [SystemMessage(content=system_prompt)] + state["messages"]

        # 2. Centralized execution
        response = self.model.invoke(messages)

        # 3. Return formatted state update
        return response

    def generate_script(self, prompt, model_name="gpt-4o-mini"):
        coding_llm = ChatOpenAI(model=model_name)
        response = coding_llm.invoke(prompt)
        return response
