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

from fastapi import FastAPI, File, HTTPException, UploadFile, BackgroundTasks
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


from langchain_core.messages import HumanMessage

@app.post("/run", response_model=RunResponse, tags=["pipeline"])
def run_pipeline(request: RunRequest, background_tasks: BackgroundTasks) -> RunResponse:
    """
    Trigger a full agentic pipeline run in the background.
    """
    run_id = getattr(request, "run_id", None) or f"RUN-{uuid.uuid4().hex[:8].upper()}"

    # Setup workspace
    workspace_dir = Path("workspace") / run_id
    input_dir = workspace_dir / "input"
    output_dir = workspace_dir / "output"
    scripts_dir = workspace_dir / "scripts"
    
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    scripts_dir.mkdir(parents=True, exist_ok=True)

    # Move uploaded data
    old_data_path = Path(request.data_path)
    new_data_path = input_dir / old_data_path.name
    
    if old_data_path.exists():
        import shutil
        shutil.copy(old_data_path, new_data_path)

    import time
    metadata_path = workspace_dir / "metadata.json"
    metadata_path.write_text(json.dumps({
        "run_id": run_id,
        "query": request.user_query,
        "timestamp": time.time(),
        "data_path": str(new_data_path.resolve())
    }), encoding="utf-8")

    initial_state = {
        "run_id": run_id,
        "user_query": request.user_query,
        "messages": [HumanMessage(content=request.user_query)],
        "intent_class": "",
        "pipeline_stage": "INIT",
        "active_division": None,
        "current_work_order_id": None,
        "input_artifacts": {"dataset": str(new_data_path.resolve())},
        "output_artifacts": {},
        "output_dir": str(output_dir.resolve()),
        "scripts_dir": str(scripts_dir.resolve()),
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

    async def background_job():
        try:
            print("--- Starting background job for run_id:", run_id, "---")
            await app_graph.ainvoke(initial_state, config=config)
            print("--- Background job completed successfully ---")
        except Exception as e:
            import traceback
            print(f"--- Background job failed: {e} ---")
            traceback.print_exc()

    background_tasks.add_task(background_job)

    return RunResponse(
        run_id=run_id,
        pipeline_stage="INIT",
        active_division=None,
        intent_class=None,
        artifact_paths={},
        echarts_options={},
        insights=[],
        user_message=None,
        error=None,
        project_log=[],
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
        supervisor_logs = state.get("project_log") or []
        live_logs = []
        live_logs_path = Path(f"workspace/{run_id}/live_logs.json")
        if live_logs_path.exists():
            try:
                live_logs = json.loads(live_logs_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        
        project_log = supervisor_logs + live_logs

        return {
            "run_id": run_id,
            "pipeline_stage": state.get("current_step"),
            "active_division": state.get("active_division"),
            "qa_retry_counts": state.get("qa_retry_counts"),
            "artifact_paths": state.get("output_artifacts") or {},
            "log_entries": len(project_log),
            "project_log": project_log,
        }
    except HTTPException:
        raise
    except Exception as exc:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(exc))



@app.get("/result/{run_id}", response_model=RunResponse, tags=["pipeline"])
def get_run_result(run_id: str):
    try:
        config = {"configurable": {"thread_id": run_id}}
        snapshot = app_graph.get_state(config)
        if snapshot is None:
            raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found.")
        final_state = snapshot.values

        artifact_paths = final_state.get("output_artifacts", {})
        echarts_options = {}
        for key, val in artifact_paths.items():
            if key.startswith("echarts_") or "echarts" in key:
                try:
                    p = Path(val)
                    if p.exists():
                        content = p.read_text(encoding="utf-8")
                        echarts_options[key.replace("echarts_", "")] = json.loads(content)
                except Exception:
                    pass

        approved_viz = final_state.get("approved_visualizations", {})
        if isinstance(approved_viz, dict) and "path" in approved_viz:
            try:
                p = Path(approved_viz["path"])
                if p.exists():
                    approved_viz = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                pass

        if isinstance(approved_viz, dict) and "visualizations" in approved_viz:
            for i, viz in enumerate(approved_viz["visualizations"]):
                viz_id = viz.get("title", f"viz_{i}")
                if "variations" in viz:
                    echarts_options[viz_id] = viz

        approved_insights_data = final_state.get("approved_insights", {})
        if isinstance(approved_insights_data, dict) and "path" in approved_insights_data:
            try:
                p = Path(approved_insights_data["path"])
                if p.exists():
                    approved_insights_data = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                pass

        insights = approved_insights_data.get("insights", []) if isinstance(approved_insights_data, dict) else []

        return RunResponse(
            run_id=run_id,
            pipeline_stage=final_state.get("current_step", "UNKNOWN"),
            active_division=final_state.get("active_division"),
            intent_class=final_state.get("intent_class"),
            artifact_paths={k: v for k, v in artifact_paths.items() if not k.startswith("echarts_")},
            echarts_options=echarts_options,
            insights=insights,
            user_message=final_state.get("error_state"),
            error=None,
            project_log=final_state.get("project_log", []),
        )
    except HTTPException:
        raise
    except Exception as exc:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(exc))

from fastapi.responses import FileResponse
import os

@app.get("/artifact", tags=["meta"])
def get_artifact(path: str):
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Artifact not found")
    return FileResponse(path)

@app.get("/history", tags=["pipeline"])
def get_history():
    """Returns a list of past runs sorted by timestamp descending."""
    workspace = Path("workspace")
    runs = []
    if workspace.exists():
        for run_dir in workspace.iterdir():
            if run_dir.is_dir():
                meta_file = run_dir / "metadata.json"
                if meta_file.exists():
                    try:
                        meta = json.loads(meta_file.read_text(encoding="utf-8"))
                        runs.append(meta)
                    except Exception:
                        pass
    runs.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
    return {"history": runs}

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
