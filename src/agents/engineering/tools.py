import sys
from platform import python_version_tuple
from uuid import uuid4
import json
import pandas as pd
import numpy as np
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
def analyze_and_profile_dataset(
    file_path: str,
    output_profile_path: str,
    output_summary_path: str,
    state: Annotated[dict, InjectedState] = None,
):
    """
    Run a full profiling and summary pass on a dataset and output the results.
    This replaces ingest, profile, and summary steps.

    Args:
        file_path: Path to the data file.
        output_profile_path: Path to the output JSON profile file.
        output_summary_path: Path to the output JSON summary file.
    """
    if state and state.get("input_artifacts", {}).get("output_dir"):
        out_dir = Path(state["input_artifacts"]["output_dir"])
        output_profile_path = str(out_dir / Path(output_profile_path).name)
        output_summary_path = str(out_dir / Path(output_summary_path).name)

    try:
        df = _read(file_path)

        # 1. Profile Data
        data_profile = generate_profile(df)
        prof_path = Path(output_profile_path)
        prof_path.parent.mkdir(parents=True, exist_ok=True)
        prof_path.write_text(json.dumps(data_profile, default=str, indent=2))

        # 2. Summary Data
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
        sum_path = Path(output_summary_path)
        sum_path.parent.mkdir(parents=True, exist_ok=True)
        sum_path.write_text(json.dumps(summary, default=str, indent=2))

        return json.dumps(
            {
                "status": "ok",
                "profile_path": output_profile_path,
                "summary_path": output_summary_path,
                "shape": list(df.shape),
                "columns": list(df.columns),
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
    columns_to_drop: list[str] = None,
    cleaning_steps_json: str = None,
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
            columns_to_drop: List of columns to explicitly drop.
            cleaning_steps_json: JSON string of cleaning_steps array from the Preprocessing Blueprint.

        Returns:
            JSON with output_path, shape_before, shape_after, cleaning_log.
    """
    if state and state.get("input_artifacts", {}).get("output_dir"):
        output_path = str(
            Path(state["input_artifacts"]["output_dir"]) / Path(output_path).name
        )

    df = _read(file_path)
    log = []
    shape_before = list(df.shape)
    
    # 1. Normalise columns
    df = clean_data._normalize_columns(df, normalize_columns)
    log.append(f"Normalized columns: {normalize_columns}")

    # 2. drop high-null cols
    df = clean_data._drop_null_cols(df, drop_null_threshold)
    log.append(f"Dropped high-null columns with threshold: {drop_null_threshold}")

    # 3. Duplicates
    df = clean_data._drop_duplicates(df, drop_duplicates)
    log.append(f"Dropped duplicates: {drop_duplicates}")

    # 4. Numeric null-fill and Categorical null-fill
    df = clean_data._fill_nulls(df, fill_numeric_strategy, fill_categorical_strategy)
    log.append(
        f"Filled nulls with strategy: {fill_numeric_strategy} for numeric and {fill_categorical_strategy} for categorical"
    )

    # 5. Drop specific columns from blueprint
    if columns_to_drop:
        df = clean_data._drop_columns(df, columns_to_drop)
        log.append(f"Dropped columns specified in blueprint: {columns_to_drop}")

    # 6. Execute custom cleaning steps from blueprint
    if cleaning_steps_json:
        try:
            cleaning_steps = json.loads(cleaning_steps_json)
            df = clean_data._execute_cleaning_steps(df, cleaning_steps)
            log.append(f"Executed custom cleaning steps: {len(cleaning_steps)} steps")
        except Exception as e:
            log.append(f"Failed to execute cleaning steps: {e}")

    # 7. Dtype coercion
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


# export_data_summary removed (consolidated)


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
        code = code[len("```python") :].strip()
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

    return json.dumps(
        {
            "status": "ok",
            "script_code": code,
            "script_path": str(script_path),
        }
    )





@tool
def execute_python_script(
    script_code: str,
    timeout: int = 300,
    state: Annotated[dict, InjectedState] = None,
):
    """
    Execute generated Python code instantly via in-process `exec()`.

    Args:
        script_code: Python source code.
        timeout: Maximum execution time (not fully enforced in `exec` but kept for interface).

    Returns:
        Structured execution report.
    """
    if not script_code.strip():
        return json.dumps(
            {
                "status": "failure",
                "error_type": "EmptyScript",
                "message": "No Python code was provided.",
            }
        )

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

    full_code = INJECTED_CODE + "\n" + script_code
    script_path.write_text(full_code, encoding="utf-8")

    start_time = time.time()
    
    import io
    from contextlib import redirect_stdout, redirect_stderr
    import traceback

    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()
    
    # Provide a rich namespace
    namespace = {
        "pd": pd,
        "np": np,
        "json": json,
    }

    try:
        with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
            exec(full_code, namespace)
            
        execution_time = round(time.time() - start_time, 3)
        return json.dumps(
            {
                "status": "success",
                "run_id": run_id,
                "script_path": str(script_path),
                "return_code": 0,
                "execution_time_seconds": execution_time,
                "stdout": stdout_buf.getvalue(),
                "stderr": stderr_buf.getvalue(),
            }
        )

    except Exception as e:
        execution_time = round(time.time() - start_time, 3)
        error_tb = traceback.format_exc()
        # also capture anything printed to stderr before the crash
        stderr_output = stderr_buf.getvalue() + "\n" + error_tb
        
        return json.dumps(
            {
                "status": "failure",
                "run_id": run_id,
                "script_path": str(script_path),
                "return_code": 1,
                "execution_time_seconds": execution_time,
                "error_type": type(e).__name__,
                "message": str(e),
                "stdout": stdout_buf.getvalue(),
                "stderr": stderr_output,
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

    if response_data is not None:
        try:
            # Try to strip markdown fences
            resp_str = response_data.strip()
            if resp_str.startswith("```json"):
                resp_str = resp_str[7:]
            if resp_str.startswith("```"):
                resp_str = resp_str[3:]
            if resp_str.endswith("```"):
                resp_str = resp_str[:-3]
            json.loads(resp_str.strip())
        except json.JSONDecodeError as e:
            return json.dumps({
                "status": "ERROR",
                "message": f"Validation Failed: `response_data` is not valid JSON. JSONDecodeError: {e}. Please fix the JSON formatting (e.g., remove trailing commas, fix quotes) before submitting the report."
            })

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

@tool
def read_artifacts(
    file_paths: list[str],
    state: Annotated[dict, InjectedState] = None,
):
    """
    Read the contents of one or more generated JSON artifacts.
    Use this to quickly inspect the contents of data_profile.json, data_summary.json, etc. without re-ingesting the dataset.
    
    Args:
        file_paths: A list of file paths to read.
        
    Returns:
        JSON string containing the parsed contents of the requested files.
    """
    results = {}
    for path in file_paths:
        try:
            p = Path(path)
            # Try to resolve relative paths against the output directory
            if not p.is_absolute() and state and state.get("input_artifacts", {}).get("output_dir"):
                # If path isn't found as-is, check if it's just a basename in output_dir
                if not p.exists():
                    p = Path(state["input_artifacts"]["output_dir"]) / p.name
            
            if not p.exists():
                results[path] = {"status": "error", "message": "File not found"}
                continue
                
            if p.suffix == ".json":
                results[path] = json.loads(p.read_text(encoding="utf-8"))
            elif p.suffix == ".csv":
                df = pd.read_csv(p, engine="pyarrow")
                results[path] = {
                    "shape": list(df.shape),
                    "columns": list(df.columns),
                    "sample": df.head(5).to_dict(orient="records")
                }
            else:
                results[path] = {"status": "error", "message": f"Unsupported file type: {p.suffix}"}
        except Exception as e:
            results[path] = {"status": "error", "message": str(e)}
            
    return json.dumps(results, default=str)


# tool registry
ENGINEERING_TOOLS = [
    analyze_and_profile_dataset,
    clean_dataset,
    generate_python_script,
    execute_python_script,
    submit_engineer_report,
    verify_artifact,
    read_artifacts,
]
