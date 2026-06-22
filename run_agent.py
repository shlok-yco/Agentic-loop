# run_terminal.py

import uuid
from pprint import pprint

from config import settings
from src.graph.state import BIState
from src.graph.workflow import app_graph
import logging

logging.basicConfig(
    level=logging.DEBUG,
    filename = "logs/visualizationtool.log",
    filemode = 'w'
)


def main():

    run_id = f"RUN-{uuid.uuid4().hex[:8].upper()}"

    initial_state: BIState = {
        "run_id": run_id,
        "user_query": "Which channel creates the best balance between customer acquisition, revenue generation, and profitability?",
        "intent_class": "",
        "pipeline_stage": "INIT",
        "active_division": None,
        "current_work_order_id": None,
        "artifact_paths": {
            "input": "/home/shlok.koirala/denzing/my_experiments/agentic/CSVs/Retail data 1.csv"
        },
        "work_orders": {},
        "qa_retry_counts": {
            "engineering": 0,
            "analytics": 0,
            "science": 0,
        },
        "checkpoints": {},
        "error_state": None,
        "project_log": [],
    }

    config = {
        "configurable": {
            "thread_id": run_id,
        },
        "recursion_limit": settings.langgraph_recursion_limit,
    }

    logging.info(f"\n=== Starting {run_id} ===\n")

    for event in app_graph.stream(
        initial_state,
        config=config,
        stream_mode="updates",
    ):
        logging.info("\n" + "=" * 80)
        logging.info(event)

    logging.info("\n=== COMPLETE ===")


if __name__ == "__main__":
    main()