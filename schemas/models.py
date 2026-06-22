"""
schemas/models.py
Pydantic models for FastAPI request / response contracts.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


# ── Request ───────────────────────────────────────────────────────────────────

class RunRequest(BaseModel):
    """POST /run — kick off a pipeline run."""

    user_query: str = Field(..., description="Natural-language question or task.")
    data_path: str = Field(..., description="Absolute path or artifact key of the input file.")

# ── Response ──────────────────────────────────────────────────────────────────

class DivisionReport(BaseModel):
    work_order_id: str
    division: str
    status: Literal["QA_PASSED", "QA_FAILED", "BLOCKED", "ESCALATED"]
    output_artifacts: List[str] = []
    qa_summary: str = ""
    retry_count: int = 0
    failure_reason: Optional[str] = None
    notes: Optional[str] = None


class RunResponse(BaseModel):
    """Response returned after pipeline completion or HITL pause."""

    run_id: str
    pipeline_stage: str
    active_division: Optional[str]
    intent_class: Optional[str]
    artifact_paths: Dict[str, str] = {}
    echarts_options: Dict[str, Any] = {}   # chart_name → ECharts option dict
    insights: List[str] = []
    user_message: Optional[str] = None     # CTO's user-facing message
    error: Optional[str] = None
    project_log: List[Dict[str, Any]] = []


# ── Legacy (kept for backwards compatibility) ─────────────────────────────────

class DataEngineerOutput(BaseModel):
    python_script: str
    data_preview: dict
    schema_status: str
    output_path: str
    pipeline_stage: str
    target_agent: str
    warnings: Optional[list] = None
