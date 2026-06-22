# The TypedDcit schema (The Global Project Log)
from typing import TypedDict, Optional, Literal, List, Dict

PipelineStatus = Literal[
    "IN_PROGRESS", "QA_PASSED", "QA_FAILED", "BLOCKED", "ESCALATED", "COMPLETE"
]


class LogEvent(TypedDict):

    timestamp: str  # ISO8601

    event_type: Literal[
        "PROJECT_INIT",
        "WORK_ORDER_ISSUED",
        "QA_PASSED",
        "QA_FAILED",
        "BLOCKED",
        "ESCALATED",
        "PIVOT",
        "HITL_PAUSE",
        "AMBIGUITY",
        "PROJECT_COMPLETE",
    ]

    division: Literal["engineering", "analytics", "science", "user", "cto"]

    work_order_id: Optional[str]  # "WO-... | null"

    status_before: PipelineStatus

    status_after: PipelineStatus

    retry_count: int  # 0,1,2,3

    max_retries: int  # 3

    reason: Optional[str]  # null if QA_PASSED, otherwise root cause.

    input_artifacts: List[str]  # artifact_path

    output_artifacts: List[str]  # artifact_path

    next_division: List[str]  # "engineering | analytics | science"

    summary: str  # concise note on what happened and why.


class WorkOrderState(TypedDict):
    division: str
    status: str
    retry_count: int
    created_at: str
    artifact_inputs: List[str]
    artifact_outputs: List[str]


class BIState(TypedDict):

    run_id: str

    user_query: str

    intent_class: Literal[
        "DATA_PREP", "EXPLORATORY", "PREDICTIVE", "HYBRID", "AMBIGUOUS"
    ]

    pipeline_stage: str

    active_division: Optional[str]

    current_work_order_id: Optional[str]

    artifact_paths: Dict[str, str]

    work_orders: Dict[str, WorkOrderState]

    qa_retry_counts: Dict[str, int]

    checkpoints: Dict[str, bool]

    error_state: Optional[str]

    project_log: List[LogEvent]
