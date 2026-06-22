"""
main.py — FastAPI application entry point.

Exposes:
    POST /upload    — upload a CSV file, returns its saved path
    POST /run       — trigger a full pipeline run
    GET  /status/{run_id}  — poll run state
    GET  /health    — liveness check
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import uvicorn
import shutil
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from schemas.models import RunRequest, RunResponse
from config import settings
from src.graph.state import BIState
from src.graph.workflow import app_graph

# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title=settings.app_title,
    description=settings.app_description,
    version=settings.app_version,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Routes ────────────────────────────────────────────────────────────────────


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok", "version": settings.app_version}


@app.post("/upload", tags=["pipeline"])
async def upload_file(file: UploadFile = File(...)):
    """
    Accept a CSV file from the frontend, persist it to the tmp directory,
    and return its absolute path for use in subsequent /run calls.
    """
    if not (file.filename or "").endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are supported.")

    dest_dir = Path(settings.tmp_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / (file.filename or "upload.csv")

    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    return {"file_path": str(dest.resolve()), "filename": file.filename}


@app.post("/run", response_model=RunResponse, tags=["pipeline"])
def run_pipeline(request: RunRequest) -> RunResponse:
    """
    Trigger a full agentic pipeline run.

    The graph runs to completion (or HITL pause) and returns the final state
    including any generated ECharts option JSONs under `echarts_options`.
    """
    run_id = f"RUN-{uuid.uuid4().hex[:8].upper()}"

    initial_state: BIState = {
        "run_id": run_id,
        "user_query": request.user_query,
        "intent_class": "",
        "pipeline_stage": "INIT",
        "active_division": None,
        "current_work_order_id": None,
        "artifact_paths": {"input": request.data_path},
        "work_orders": {},
        "qa_retry_counts": {"engineering": 0, "analytics": 0, "science": 0},
        "checkpoints": {},
        "error_state": None,
        "project_log": [],
    }

    config = {
        "configurable": {"thread_id": run_id},
        "recursion_limit": settings.langgraph_recursion_limit,
    }

    try:
        final_state: dict[str, Any] = app_graph.invoke(initial_state, config=config)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    # Extract ECharts options stored by the analyst/scientist nodes
    artifact_paths: dict[str, str] = final_state.get("artifact_paths", {})
    echarts_options: dict[str, Any] = {}
    for key, val in artifact_paths.items():
        if key.startswith("echarts_"):
            try:
                echarts_options[key.removeprefix("echarts_")] = json.loads(val)
            except (json.JSONDecodeError, TypeError):
                echarts_options[key.removeprefix("echarts_")] = val

    # Pull insights from the last analytics log entry
    insights: list[str] = []
    for entry in reversed(final_state.get("project_log", [])):
        if (
            entry.get("division") == "analytics"
            and entry.get("event_type") == "QA_PASSED"
        ):
            insights = entry.get("insights", [])
            break

    return RunResponse(
        run_id=run_id,
        pipeline_stage=final_state.get("pipeline_stage", "UNKNOWN"),
        active_division=final_state.get("active_division"),
        intent_class=final_state.get("intent_class"),
        artifact_paths={
            k: v for k, v in artifact_paths.items() if not k.startswith("echarts_")
        },
        echarts_options=echarts_options,
        insights=insights,
        user_message=final_state.get(
            "error_state"
        ),  # CTO user-facing message on HITL/clarification
        error=None,
        project_log=final_state.get("project_log", []),
    )


@app.get("/status/{run_id}", tags=["pipeline"])
def get_run_status(run_id: str):
    """Poll the current state snapshot of a run (checkpointer required)."""
    try:
        config = {"configurable": {"thread_id": run_id}}
        snapshot = app_graph.get_state(config)
        if snapshot is None:
            raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found.")
        state = snapshot.values
        return {
            "run_id": run_id,
            "pipeline_stage": state.get("pipeline_stage"),
            "active_division": state.get("active_division"),
            "qa_retry_counts": state.get("qa_retry_counts"),
            "artifact_keys": list(state.get("artifact_paths", {}).keys()),
            "log_entries": len(state.get("project_log", [])),
            "project_log": state.get("project_log", []),
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.api_reload,
        workers=settings.api_workers,
        log_level=settings.log_level,
    )
