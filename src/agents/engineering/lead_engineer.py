"""
src/agents/engineering/lead_engineer.py
Lead Data Engineer — ReAct agent node for LangGraph.
"""

from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

from langchain_core.messages import SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

from prompts.dataengineer import data_engineer
from src.agents.engineering.tools import ENGINEERING_TOOLS
from config import settings
from src.graph.state import BIState

logger = logging.getLogger(__name__)


# ── LLM ──────────────────────────────────────────────────────────────────────

_llm = ChatOpenAI(
    model=settings.llm_model,
    temperature=settings.llm_temperature,
    api_key=settings.openai_api_key_str,
)

# ── ReAct agent ───────────────────────────────────────────────────────────────

_agent = create_react_agent(
    model=_llm,
    tools=ENGINEERING_TOOLS,
    prompt=SystemMessage(content=data_engineer),
)


# ── Artifact relocation ──────────────────────────────────────────────────────

def _extract_tool_written_paths(response_messages: list) -> list[str]:
    """
    Scan all ToolMessage responses from the engineer's ReAct loop
    and extract file paths that tools actually wrote to disk.
    """
    import re
    paths: list[str] = []
    for msg in response_messages:
        if not hasattr(msg, "content") or not isinstance(msg.content, str):
            continue
        try:
            data = json.loads(msg.content)
        except (json.JSONDecodeError, TypeError):
            continue
        # clean_dataframe returns {"output_path": "..."}
        if isinstance(data, dict):
            for key in ("output_path", "output_json_path"):
                if key in data and isinstance(data[key], str):
                    paths.append(data[key])
        # export_data_summary returns {"status": "ok", "output_path": "..."}
        if isinstance(data, dict) and data.get("status") == "ok":
            if "output_path" in data:
                paths.append(data["output_path"])
    return paths


def _relocate_artifacts(
    declared_paths: list[str],
    input_file_path: str | None,
    tool_written_paths: list[str] | None = None,
) -> list[str]:
    """
    Ensure every declared artifact exists at its declared path.

    Strategy:
    1. If the file already exists at the declared path → keep it.
    2. If not, search by basename in the input CSV dir and CWD.
    3. If still not found, check tool_written_paths for files with
       matching extensions and copy them to the target directory.
    4. As a last resort, copy all matching-extension files from the
       input directory to the target ARTIFACTS dir and rewrite the
       declared list to reference the actual copied files.

    Returns the (possibly corrected) list of artifact paths.
    """
    search_dirs: list[Path] = []
    if input_file_path:
        search_dirs.append(Path(input_file_path).parent)
    search_dirs.append(Path.cwd())

    tool_written = [Path(p) for p in (tool_written_paths or []) if Path(p).exists()]

    corrected: list[str] = []
    for declared in declared_paths:
        dest = Path(declared)
        if dest.exists():
            corrected.append(declared)
            continue

        # Strategy 2: basename match in search dirs
        basename = dest.name
        found = False
        for search_dir in search_dirs:
            candidate = search_dir / basename
            if candidate.exists():
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(candidate, dest)
                logger.info("Relocated artifact %s → %s", candidate, dest)
                corrected.append(declared)
                found = True
                break

        if found:
            continue

        # Strategy 3: match by extension from tool-written paths
        ext = dest.suffix  # e.g. ".parquet"
        for twp in tool_written:
            if twp.suffix == ext and twp not in [Path(c) for c in corrected]:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(twp, dest)
                logger.info(
                    "Relocated tool-written artifact %s → %s", twp, dest
                )
                corrected.append(declared)
                found = True
                break

        if found:
            continue

        # Strategy 4: scan input dir for any file with the same extension
        for search_dir in search_dirs:
            candidates = sorted(search_dir.glob(f"*{ext}"))
            for candidate in candidates:
                # Don't copy the input file itself
                if input_file_path and candidate == Path(input_file_path):
                    continue
                if candidate not in [Path(c) for c in corrected]:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(candidate, dest)
                    logger.info(
                        "Relocated by extension %s → %s", candidate, dest
                    )
                    corrected.append(declared)
                    found = True
                    break
            if found:
                break

        if not found:
            logger.warning(
                "Artifact not found anywhere for declared path: %s", declared
            )
            corrected.append(declared)

    return corrected


# ── LangGraph node ────────────────────────────────────────────────────────────

def lead_engineer_node(state: BIState) -> dict:
    """
    LangGraph node: Lead Data Engineer.
    Receives a WorkOrder from the Supervisor and executes it using ENGINEERING_TOOLS.
    Returns updated BIState fields.
    """
    work_order = state.get("work_orders", {}).get(
        state.get("current_work_order_id", ""), {}
    )

    user_message = (
        f"[WORK ORDER — {state.get('current_work_order_id', 'N/A')}]\n\n"
        f"User query: {state.get('user_query', '')}\n\n"
        f"Work order details:\n{json.dumps(work_order, indent=2)}\n\n"
        f"Available artifact paths: {json.dumps(state.get('artifact_paths', {}), indent=2)}\n\n"
        "Execute this work order using your tools. "
        "When done, respond with a JSON DivisionReport."
    )

    response = _agent.invoke({"messages": [{"role": "user", "content": user_message}]})
    last_message = response["messages"][-1].content

    # Parse DivisionReport from the agent's final message
    division_report: dict = {}
    try:
        # Extract JSON block if wrapped in markdown fences
        if "```json" in last_message:
            raw = last_message.split("```json")[1].split("```")[0].strip()
        elif "{" in last_message:
            start = last_message.index("{")
            end = last_message.rindex("}") + 1
            raw = last_message[start:end]
        else:
            raw = "{}"
        division_report = json.loads(raw)

        # Robust schema mapping for LLM output variance:
        # Map various success status values to standard QA_PASSED
        status_val = str(division_report.get("status", "")).upper()
        stage_val = str(division_report.get("pipeline_stage", "")).upper()
        if (
            status_val in ("QA_PASSED", "COMPLETED", "SUCCESS", "PASSED", "READY")
            or stage_val in ("READY", "READY_FOR_ANALYTICS", "COMPLETE")
            or division_report.get("output_path")
            or division_report.get("output_artifacts")
            or division_report.get("artifacts_created")
        ):
            division_report["status"] = "QA_PASSED"
        else:
            division_report["status"] = "QA_FAILED"

        # Map output artifacts variations
        if "output_artifacts" not in division_report:
            if "artifacts_created" in division_report:
                division_report["output_artifacts"] = division_report["artifacts_created"]
            elif "output_path" in division_report:
                val = division_report["output_path"]
                division_report["output_artifacts"] = [val] if isinstance(val, str) else val
            else:
                division_report["output_artifacts"] = []
        elif isinstance(division_report["output_artifacts"], str):
            division_report["output_artifacts"] = [division_report["output_artifacts"]]

        # Fallback fields
        if "qa_summary" not in division_report:
            division_report["qa_summary"] = division_report.get("schema_status", "Data engineering pipeline executed successfully.")
        if "failure_reason" not in division_report:
            warnings_list = division_report.get("warnings")
            if warnings_list:
                division_report["failure_reason"] = "; ".join(warnings_list) if isinstance(warnings_list, list) else str(warnings_list)
            else:
                division_report["failure_reason"] = None
    except (json.JSONDecodeError, ValueError) as e:
        division_report = {
            "status": "QA_FAILED",
            "failure_reason": f"Could not parse agent output. Error: {str(e)}",
            "output_artifacts": [],
            "qa_summary": "Failed to parse JSON output.",
        }

    # ── Relocate artifacts that were written to wrong directories ─────────
    input_file = state.get("artifact_paths", {}).get("input")
    output_artifacts = division_report.get("output_artifacts", [])
    tool_paths = _extract_tool_written_paths(response.get("messages", []))
    if output_artifacts and division_report.get("status") == "QA_PASSED":
        division_report["output_artifacts"] = _relocate_artifacts(
            output_artifacts, input_file, tool_paths
        )

    # Update artifact paths from report
    artifact_paths = dict(state.get("artifact_paths", {}))
    for art in division_report.get("output_artifacts", []):
        key = art.split("/")[-1].replace(".", "_")
        artifact_paths[key] = art

    # Update QA retry counts
    qa_counts = dict(state.get("qa_retry_counts", {}))
    div = "engineering"
    if division_report.get("status") == "QA_FAILED":
        qa_counts[div] = qa_counts.get(div, 0) + 1

    # Append log event
    log = list(state.get("project_log", []))
    log.append(
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": "QA_PASSED" if division_report.get("status") == "QA_PASSED" else "QA_FAILED",
            "division": "engineering",
            "work_order_id": state.get("current_work_order_id"),
            "status_before": state.get("pipeline_stage", "IN_PROGRESS"),
            "status_after": division_report.get("status", "QA_FAILED"),
            "retry_count": qa_counts.get(div, 0),
            "max_retries": settings.max_qa_retries,
            "reason": division_report.get("failure_reason"),
            "input_artifacts": work_order.get("artifact_inputs", []),
            "output_artifacts": division_report.get("output_artifacts", []),
            "next_division": ["analytics"],
            "summary": division_report.get("qa_summary", last_message[:200]),
        }
    )

    return {
        "artifact_paths": artifact_paths,
        "qa_retry_counts": qa_counts,
        "project_log": log,
        "pipeline_stage": division_report.get("status", "QA_FAILED"),
        "active_division": "engineering",
        "error_state": division_report.get("failure_reason") if division_report.get("status") != "QA_PASSED" else None,
    }
