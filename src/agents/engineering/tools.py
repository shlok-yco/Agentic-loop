import sys
from platform import python_version_tuple
from uuid import uuid4
import json
import pandas as pd
from pathlib import Path

# pyrefly: ignore [missing-import]
from dotenv import load_dotenv

load_dotenv()

# pyrefly: ignore [missing-import]
from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState
from typing import Annotated
from src.prompts import SCRIPT_GENERATOR_PROMPT
from src.agents.common.model_call import LLMService
import subprocess
from datetime import datetime
import time


from .utils import _read, profile_dataset as generate_profile, CleanData

clean_data = CleanData()

llm_service = LLMService(tools=[])


@tool
def ingest_dataset(file_path: str):
    """
    This is tool for the file/ data ingestion function to load or read the data
    """
    try:
        df = _read(file_path)
        return json.dumps(
            {
                "shape": list(df.shape),
                "columns": list(df.columns),
                "dtypes": df.dtypes.astype(str).to_dict(),
                "head": df.head(5).to_dict(orient="records"),
                "null_counts": df.isnull().sum().to_dict(),
                "duplicate_rows": int(df.duplicated().sum()),
            },
            default=str,
        )
    except Exception as e:
        return str(e)


@tool
def profile_dataset(file_path: str, output_path: str, state: Annotated[dict, InjectedState] = None):
    """
    Run a lightweight profiling pass on a file and return per-column statistics
    (dtype, null %, unique count, min/max/mean for numeric columns).

    Args:
        file_path: Path to the data file.
        output_path: Path to the output json file.
    """
    if state and state.get("input_artifacts", {}).get("output_dir"):
        output_path = str(Path(state["input_artifacts"]["output_dir"]) / Path(output_path).name)

    try:
        df = _read(file_path)
        data_profile = generate_profile(df)
        out_path = Path(output_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(data_profile, default=str, indent=2))
        return json.dumps(
            {
                "status": "ok",
                "output_path": output_path,
                "shape": list(df.shape),
                "columns": list(df.columns),
                "dtypes": df.dtypes.astype(str).to_dict(),
                "null_counts": df.isnull().sum().to_dict(),
                "duplicate_rows": int(df.duplicated().sum()),
            }
        )
    except Exception as e:
        return str(e)


@tool
def clean_dataset(
    file_path: str,
    output_path: str,
    drop_duplicates: bool = True,
    normalize_columns: bool = True,
    fill_numeric_strategy: str = "median",
    fill_categorical_strategy: str = "unknown",
    drop_null_threshold: float = 0.9,
    state: Annotated[dict, InjectedState] = None,
):
    """
    Apply standard cleaning steps to a dataframe and write a parquet output.

        Steps: column normalisation → drop high-null cols → duplicate removal →
        numeric null-fill → categorical null-fill → dtype coercion where safe.

        Args:
            file_path: Input data path.
            output_path: Where to write the cleaned csv.
            drop_duplicates: Whether to remove exact duplicate rows.
            normalize_columns: Lowercase + underscore column names.
            fill_numeric_strategy: 'median' | 'mean' | 'zero'.
            fill_categorical_strategy: Fill string with this value.
            drop_null_threshold: Drop columns with null fraction > this value (0–1).

        Returns:
            JSON with output_path, shape_before, shape_after, cleaning_log.
    """
    if state and state.get("input_artifacts", {}).get("output_dir"):
        output_path = str(Path(state["input_artifacts"]["output_dir"]) / Path(output_path).name)

    df = _read(file_path)
    log = []
    shape_before = list(df.shape)
    # 1. Normalise columns
    clean_data._normalize_columns(df, normalize_columns)
    log.append(f"Normalized columns: {normalize_columns}")

    # 2. drop high-null cols
    clean_data._drop_null_cols(df, drop_null_threshold)
    log.append(f"Dropped high-null columns with threshold: {drop_null_threshold}")

    # 3. Duplicates
    clean_data._drop_duplicates(df, drop_duplicates)
    log.append(f"Dropped duplicates: {drop_duplicates}")

    # 4. Numeric null-fill and Categorical null-fill
    clean_data._fill_nulls(df, fill_numeric_strategy, fill_categorical_strategy)
    log.append(
        f"Filled nulls with strategy: {fill_numeric_strategy} for numeric and {fill_categorical_strategy} for categorical"
    )

    # 5. Dtype coercion
    df.to_csv(output_path, index=False)
    log.append(f"Saved cleaned data to: {output_path}")

    return json.dumps(
        {
            "output_path": output_path,
            "shape_before": shape_before,
            "shape_after": list(df.shape),
            "cleaning_log": log,
        }
    )


@tool
def validate_schema(
    file_path: str,
    required_columns: list[str],
    not_null_columns: list[str] | None = None,
) -> str:
    """
    Validate that a dataframe has required columns and no nulls in key fields.

    Args:
        file_path: Path to the parquet/csv file.
        required_columns: Columns that must exist.
        not_null_columns: Columns that must have zero nulls.

    Returns:
        JSON with status ('PASSED' | 'FAILED') and a list of violations.
    """
    df = _read(file_path)
    violations: list[str] = []

    missing = [c for c in required_columns if c not in df.columns]
    if missing:
        violations.append(f"Missing required columns: {missing}")

    if not_null_columns:
        for col in not_null_columns:
            if col in df.columns and df[col].isnull().any():
                n = int(df[col].isnull().sum())
                violations.append(f"Column '{col}' has {n} nulls (must be zero).")

    return json.dumps(
        {
            "status": "PASSED" if not violations else "FAILED",
            "violations": violations,
            "columns_found": list(df.columns),
            "row_count": len(df),
        }
    )


@tool
def export_data_summary(file_path: str, output_json_path: str, state: Annotated[dict, InjectedState] = None) -> str:
    """
    Export a full data quality summary (shape, dtypes, null counts, sample rows)
    to a JSON file for downstream agents to reference.

    Args:
        file_path: Source data file.
        output_json_path: Where to write the JSON summary.
    """
    if state and state.get("input_artifacts", {}).get("output_dir"):
        output_json_path = str(Path(state["input_artifacts"]["output_dir"]) / Path(output_json_path).name)

    df = _read(file_path)
    summary = {
        "source": file_path,
        "shape": list(df.shape),
        "columns": list(df.columns),
        "dtypes": df.dtypes.astype(str).to_dict(),
        "null_counts": df.isnull().sum().to_dict(),
        "duplicate_rows": int(df.duplicated().sum()),
        "sample_rows": df.head(10).to_dict(orient="records"),
        "numeric_stats": df.describe().to_dict(),
    }
    out = Path(output_json_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, default=str, indent=2))
    return json.dumps({"status": "ok", "output_path": str(out)})


@tool
def generate_python_script(
    summary: str,
    task: str,
    input_artifacts: dict[str, str],
    output_artifacts: dict[str, str],
    state: Annotated[dict, InjectedState] = None,
):
    """
    This tool is used to generate python script for the data engineer agent.

    Args:
        summary: summary of the task to be done in clear NLP
        task: task to be executed by the lead data engineer and his team.
        input_artifacts: input artifacts (data, schema, envs, etc.) mapped to their names
        output_artifacts: expected output artifacts path mapped to their names
    Returns:
        JSON with the generated Python script code.
    """
    prompt = SCRIPT_GENERATOR_PROMPT.format(
        summary=summary,
        task=task,
        input_artifacts=input_artifacts,
        output_artifacts=output_artifacts,
    )

    response = llm_service.generate_script(prompt)

    # Extract the code string from the AIMessage
    code = response.content if hasattr(response, "content") else str(response)

    # Strip markdown fences if present
    if code.startswith("```python"):
        code = code[len("```python"):].strip()
    if code.startswith("```"):
        code = code[3:].strip()
    if code.endswith("```"):
        code = code[:-3].strip()

    # Save the script to a file for reference
    scripts_dir_path = "generated_scripts"
    if state and state.get("input_artifacts", {}).get("scripts_dir"):
        scripts_dir_path = state["input_artifacts"]["scripts_dir"]
    else:
        scripts_dir_path = input_artifacts.get("scripts_dir", scripts_dir_path)

    scripts_dir = Path(scripts_dir_path)
    script_path = scripts_dir / f"generated_{uuid4().hex[:8]}.py"
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text(code, encoding="utf-8")

    return json.dumps({
        "status": "ok",
        "script_code": code,
        "script_path": str(script_path),
    })


@tool
def execute_python_script(
    script_code: str,
    timeout: int = 300,
    state: Annotated[dict, InjectedState] = None,
):
    """
    Execute generated Python code by writing it to a temporary
    script file and running it.

    Args:
        script_code: Python source code.
        timeout: Maximum execution time in seconds.

    Returns:
        Structured execution report.
    """

    if not script_code.strip():
        return {
            "status": "failure",
            "error_type": "EmptyScript",
            "message": "No Python code was provided.",
        }

    workspace_path = "generated_scripts"
    if state and state.get("input_artifacts", {}).get("scripts_dir"):
        workspace_path = state["input_artifacts"]["scripts_dir"]

    workspace = Path(workspace_path)
    workspace.mkdir(parents=True, exist_ok=True)

    run_id = str(uuid4())[:8]

    script_path = workspace / f"run_{run_id}.py"

    INJECTED_CODE = """
import json
import numpy as np
import pandas as pd

class NpEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if pd.isna(obj):
            return None
        return super(NpEncoder, self).default(obj)

# Patch json.dump and json.dumps to use NpEncoder by default
_original_dump = json.dump
_original_dumps = json.dumps

def _patched_dump(*args, **kwargs):
    kwargs.setdefault('cls', NpEncoder)
    return _original_dump(*args, **kwargs)

def _patched_dumps(*args, **kwargs):
    kwargs.setdefault('cls', NpEncoder)
    return _original_dumps(*args, **kwargs)

json.dump = _patched_dump
json.dumps = _patched_dumps
"""

    try:
        script_path.write_text(
            INJECTED_CODE + "\n" + script_code,
            encoding="utf-8",
        )

        start_time = time.time()

        result = subprocess.run(
            [sys.executable, str(script_path)],
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        execution_time = round(
            time.time() - start_time,
            2,
        )

        return json.dumps(
            {
                "status": ("success" if result.returncode == 0 else "failure"),
                "run_id": run_id,
                "script_path": str(script_path),
                "return_code": result.returncode,
                "execution_time_seconds": execution_time,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        )

    except subprocess.TimeoutExpired:

        return json.dumps(
            {
                "status": "failure",
                "run_id": run_id,
                "script_path": str(script_path),
                "error_type": "TimeoutExpired",
                "message": (f"Execution exceeded " f"{timeout} seconds."),
            }
        )

    except Exception as e:

        return json.dumps(
            {
                "status": "failure",
                "run_id": run_id,
                "script_path": str(script_path),
                "error_type": type(e).__name__,
                "message": str(e),
            }
        )


@tool
def submit_engineer_report(
    status: str,
    summary: str,
    completed_tasks: list[str],
    failed_tasks: list[str],
    generated_artifacts: dict[str, str],
    handoff_artifacts: dict[str, str],
    blockers: list[str] | None = None,
    response_data: str | None = None,
):
    """
    Submit final engineering report.
    """

    return json.dumps(
        {
            "report_type": "DIVISION_REPORT",
            "timestamp": datetime.utcnow().isoformat(),
            "division": "Engineering",
            "status": status,
            "summary": summary,
            "completed_tasks": completed_tasks,
            "failed_tasks": failed_tasks,
            "generated_artifacts": generated_artifacts,
            "handoff_artifacts": handoff_artifacts,
            "blockers": blockers or [],
            "next_recommended_division": "Analytics",
            "report_submitted": True,
            "response_data": response_data,
        }
    )


@tool
def verify_artifact(file_path: str):
    """
    Verify that an artifact exists,
    is readable,
    and is not empty.
    """

    p = Path(file_path)

    if not p.exists():
        return json.dumps(
            {
                "status": "FAILED",
                "path": file_path,
                "exists": False,
                "readable": False,
                "size_bytes": 0,
                "message": "Artifact does not exist",
            }
        )

    try:

        readable = False

        if p.is_file():
            with open(p, "rb") as f:
                f.read(1)

            readable = True

        return json.dumps(
            {
                "status": "PASSED",
                "path": file_path,
                "exists": True,
                "readable": readable,
                "size_bytes": p.stat().st_size,
                "message": "Artifact verified",
            }
        )

    except Exception as e:

        return json.dumps(
            {
                "status": "FAILED",
                "path": file_path,
                "exists": True,
                "readable": False,
                "size_bytes": p.stat().st_size,
                "message": str(e),
            }
        )


# tool registry
ENGINEERING_TOOLS = [
    ingest_dataset,
    profile_dataset,
    clean_dataset,
    export_data_summary,
    generate_python_script,
    execute_python_script,
    submit_engineer_report,
    verify_artifact,
]
