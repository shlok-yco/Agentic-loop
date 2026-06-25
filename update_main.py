import re

with open("main.py", "r") as f:
    content = f.read()

# Add BackgroundTasks
if "from fastapi import FastAPI, File, HTTPException, UploadFile" in content:
    content = content.replace("from fastapi import FastAPI, File, HTTPException, UploadFile", 
                              "from fastapi import FastAPI, File, HTTPException, UploadFile, BackgroundTasks")

# Modify /run to accept BackgroundTasks
run_def = """@app.post("/run", response_model=RunResponse, tags=["pipeline"])
def run_pipeline(request: RunRequest, background_tasks: BackgroundTasks) -> RunResponse:
    \"\"\"
    Trigger a full agentic pipeline run in the background.
    \"\"\"
    run_id = getattr(request, "run_id", None) or f"RUN-{uuid.uuid4().hex[:8].upper()}"

    initial_state = {
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

    def background_job():
        try:
            app_graph.invoke(initial_state, config=config)
        except Exception as e:
            print(f"Background job failed: {e}")

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
"""

content = re.sub(r'@app\.post\("/run".*?def run_pipeline.*?return RunResponse\([^)]+\)', run_def, content, flags=re.DOTALL)

# Add /result/{run_id} endpoint and /artifact endpoint
endpoints = """
@app.get("/result/{run_id}", response_model=RunResponse, tags=["pipeline"])
def get_run_result(run_id: str):
    try:
        config = {"configurable": {"thread_id": run_id}}
        snapshot = app_graph.get_state(config)
        if snapshot is None:
            raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found.")
        final_state = snapshot.values

        artifact_paths = final_state.get("artifact_paths", {})
        echarts_options = {}
        for key, val in artifact_paths.items():
            if key.startswith("echarts_"):
                try:
                    echarts_options[key.removeprefix("echarts_")] = json.loads(val)
                except (json.JSONDecodeError, TypeError):
                    echarts_options[key.removeprefix("echarts_")] = val

        insights = []
        for entry in reversed(final_state.get("project_log", [])):
            if entry.get("division") == "analytics" and entry.get("event_type") == "QA_PASSED":
                insights = entry.get("insights", [])
                break

        return RunResponse(
            run_id=run_id,
            pipeline_stage=final_state.get("pipeline_stage", "UNKNOWN"),
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
        raise HTTPException(status_code=500, detail=str(exc)) from exc

from fastapi.responses import FileResponse
import os

@app.get("/artifact", tags=["meta"])
def get_artifact(path: str):
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Artifact not found")
    return FileResponse(path)

# ── Entry point"""

content = content.replace("# ── Entry point", endpoints)

with open("main.py", "w") as f:
    f.write(content)

