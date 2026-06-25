from typing import TypedDict, Literal


class DivisionReport(TypedDict):

    division: str

    status: Literal[
        "COMPLETED",
        "PARTIAL_SUCCESS",
        "FAILED",
    ]

    summary: str

    completed_tasks: list[str]

    failed_tasks: list[str]

    generated_artifacts: dict[str, str]

    handoff_artifacts: dict[str, str]

    blockers: list[str]

    next_recommended_division: str | None
