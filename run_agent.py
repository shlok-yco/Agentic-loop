from pprint import pprint
from src.graph.supervisor import app

# pyrefly: ignore [missing-import]
from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    ToolMessage,
)


def print_stream(stream):

    print("\n" + "=" * 100)
    print("WORKFLOW STARTED")
    print("=" * 100)

    for event in stream:

        for node_name, state in event.items():

            print("\n")
            print("=" * 100)
            print(f"NODE: {node_name}")
            print("=" * 100)

            messages = state.get("messages", [])

            if not messages:
                continue

            last_message = messages[-1]

            #
            # Human Message
            #
            if isinstance(last_message, HumanMessage):

                print("\n[HUMAN]")
                print(last_message.content)

            #
            # AI Message
            #
            elif isinstance(last_message, AIMessage):

                print("\n[AI]")

                if last_message.content:
                    print(last_message.content)

                if last_message.tool_calls:

                    print("\n[TOOL CALLS]")

                    for tool_call in last_message.tool_calls:

                        print(f"\nTool: {tool_call['name']}")

                        print("Arguments:")
                        pprint(tool_call["args"])

            #
            # Tool Message
            #
            elif isinstance(last_message, ToolMessage):

                print("\n[TOOL RESULT]")

                print(f"Tool Name : {last_message.name}")

                print("\nOutput:")

                try:
                    pprint(last_message.content)

                except Exception:
                    print(last_message.content)

            #
            # Fallback
            #
            else:

                print("\n[MESSAGE]")
                pprint(last_message)

    print("\n")
    print("=" * 100)
    print("WORKFLOW FINISHED")
    print("=" * 100)


def main():

    state = {
        "messages": [
            (
                "user",
                """
                What percentage share of our total squad goals do individual forward archetypes (ST, LW, RW) contribute compared to defensive units?
                """,
            )
        ],
        "input_artifacts": {
            "customer_dataset": "csvs/fifa_player_performance_market_value.csv"
        },
        "output_artifacts": {},
        "current_step": "init",
        "pending_tasks": [],
        "completed_tasks": {},
        "failed_tasks": {},
        "project_complete": False,
        "project_log": [],
        "reports_received": {},
    }
    print_stream(
        app.stream(
            state,
            config={"recursion_limit": 150},
            stream_mode="updates",
        )
    )


if __name__ == "__main__":
    main()
