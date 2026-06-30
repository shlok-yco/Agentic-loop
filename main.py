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
        
        workspace_dir = Path("workspace") / run_id
        disk_completed = False
        if workspace_dir.exists():
            if (workspace_dir / "output" / "approved_visualizations.json").exists() or (workspace_dir / "output" / "approved_visualizations").exists():
                disk_completed = True

        state = getattr(snapshot, "values", {}) if snapshot else {}
        
        if not state:
            if not workspace_dir.exists():
                raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found.")
            
            current_step = "COMPLETED" if disk_completed else "UNKNOWN"
            
            live_logs = []
            live_logs_path = workspace_dir / "live_logs.json"
            if live_logs_path.exists():
                try:
                    live_logs = json.loads(live_logs_path.read_text(encoding="utf-8"))
                except Exception:
                    pass
            
            return {
                "run_id": run_id,
                "pipeline_stage": current_step,
                "active_division": None,
                "qa_retry_counts": {},
                "artifact_paths": {},
                "log_entries": len(live_logs),
                "project_log": live_logs,
            }
        
        # Check if graph has finished executing
        is_finished = len(getattr(snapshot, "next", [])) == 0
        current_step = state.get("current_step")
        if is_finished or disk_completed:
            current_step = "COMPLETED"

        supervisor_logs = state.get("project_log") or []
        live_logs = []
        live_logs_path = workspace_dir / "live_logs.json"
        if live_logs_path.exists():
            try:
                live_logs = json.loads(live_logs_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        
        project_log = supervisor_logs + live_logs

        return {
            "run_id": run_id,
            "pipeline_stage": current_step,
            "active_division": state.get("active_division"),
            "qa_retry_counts": state.get("qa_retry_counts", {}),
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
        
        workspace_dir = Path("workspace") / run_id
        if not workspace_dir.exists():
            raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found.")
            
        final_state = getattr(snapshot, "values", {}) if snapshot else {}
        
        if not final_state or not final_state.get("output_artifacts") or not final_state.get("project_log"):
            # Fully reconstruct from disk if state is empty or incomplete
            final_state = {
                "current_step": "COMPLETED",
                "active_division": None,
                "intent_class": None,
                "error_state": None,
                "project_log": [],
                "output_artifacts": {}
            }
            
            output_dir = workspace_dir / "output"
            if output_dir.exists():
                for f in output_dir.iterdir():
                    if f.is_file():
                        final_state["output_artifacts"][f.name] = str(f.resolve())
                        if f.name == "approved_visualizations.json":
                            final_state["approved_visualizations"] = {"path": str(f.resolve())}
                        if f.name == "approved_insights.json":
                            final_state["approved_insights"] = {"path": str(f.resolve())}
            
            live_logs_path = workspace_dir / "live_logs.json"
            if live_logs_path.exists():
                try:
                    final_state["project_log"] = json.loads(live_logs_path.read_text(encoding="utf-8"))
                except Exception:
                    pass
        else:
            # Even if we have some state, inject the output directory artifacts just in case
            output_dir = workspace_dir / "output"
            if "output_artifacts" not in final_state:
                final_state["output_artifacts"] = {}
            if output_dir.exists():
                for f in output_dir.iterdir():
                    if f.is_file():
                        if f.name not in final_state["output_artifacts"]:
                            final_state["output_artifacts"][f.name] = str(f.resolve())
                        if f.name == "approved_visualizations.json" and "approved_visualizations" not in final_state:
                            final_state["approved_visualizations"] = {"path": str(f.resolve())}
                        if f.name == "approved_insights.json" and "approved_insights" not in final_state:
                            final_state["approved_insights"] = {"path": str(f.resolve())}

        artifact_paths = final_state.get("output_artifacts", {})
        echarts_options = {}
        
        # Only parse charts from the official approved_visualizations artifact.
        # Check both state and output_artifacts for the path.
        approved_viz = final_state.get("approved_visualizations", {})
        approved_viz_path = artifact_paths.get("approved_visualizations") or artifact_paths.get("approved_visualizations.json")
        
        if not approved_viz and approved_viz_path:
            approved_viz = {"path": approved_viz_path}

        if isinstance(approved_viz, dict) and "path" in approved_viz:
            try:
                p = Path(approved_viz["path"])
                if p.exists():
                    approved_viz = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                pass

        viz_list = []
        if isinstance(approved_viz, dict) and "visualizations" in approved_viz:
            viz_list = approved_viz["visualizations"]
        elif isinstance(approved_viz, list):
            viz_list = approved_viz

        for i, viz in enumerate(viz_list):
            if isinstance(viz, dict):
                viz_id = viz.get("title", f"viz_{i}")
                if "variations" in viz or "echarts_option" in viz:
                    echarts_options[viz_id] = viz
        
        # Fallback and $ref resolution: also load any individual echarts artifacts
        for key, path in artifact_paths.items():
            if key.startswith("echarts_"):
                try:
                    p = Path(path)
                    if p.exists():
                        loaded_viz = json.loads(p.read_text(encoding="utf-8"))
                        if isinstance(loaded_viz, dict):
                            viz_id = loaded_viz.get("title", key)
                            actual_opt = loaded_viz.get("echarts_option", loaded_viz)
                            
                            if viz_id in echarts_options:
                                # It's already here from approved_visualizations; let's resolve $refs
                                for var in echarts_options[viz_id].get("variations", []):
                                    ref_obj = var.get("echarts_option", {})
                                    if isinstance(ref_obj, dict) and "$ref" in ref_obj:
                                        if ref_obj["$ref"] == key or ref_obj["$ref"] == p.name:
                                            var["echarts_option"] = actual_opt
                                    # also if echarts_option is completely missing, populate it
                                    elif not ref_obj:
                                        var["echarts_option"] = actual_opt
                            else:
                                if "echarts_option" in loaded_viz or "variations" in loaded_viz:
                                    echarts_options[viz_id] = loaded_viz
                except Exception:
                    pass

        approved_insights_data = final_state.get("approved_insights", {})
        if isinstance(approved_insights_data, dict) and "path" in approved_insights_data:
            try:
                p = Path(approved_insights_data["path"])
                if p.exists():
                    approved_insights_data = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                pass

        if isinstance(approved_insights_data, list):
            insights = approved_insights_data
        elif isinstance(approved_insights_data, dict):
            insights = approved_insights_data.get("insights", [])
        else:
            insights = []

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
