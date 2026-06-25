import json
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime

import pandas as pd
from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState
from typing import Annotated


# ── helpers ──────────────────────────────────────────────────────────────────

def _read_df(path: str) -> pd.DataFrame:
    """Read CSV / Parquet / Excel / JSON into a DataFrame."""
    p = Path(path)
    if p.suffix == ".parquet":
        return pd.read_parquet(p)
    if p.suffix in (".xls", ".xlsx"):
        return pd.read_excel(p)
    if p.suffix == ".json":
        return pd.read_json(p)
    return pd.read_csv(p)


# ── tools ────────────────────────────────────────────────────────────────────


@tool
def read_artifact(file_path: str) -> str:
    """
    Read a JSON or text artifact from disk and return its contents.

    Use this to inspect data_profile, data_summary, business_objectives,
    preprocessing_blueprint, or any other artifact produced by earlier steps.

    Args:
        file_path: Path to the artifact file.

    Returns:
        The file contents as a string.
    """
    p = Path(file_path)
    if not p.exists():
        return json.dumps({"status": "ERROR", "message": f"File not found: {file_path}"})

    try:
        content = p.read_text(encoding="utf-8")
        # If it's JSON, validate and return compact form to save tokens
        if p.suffix == ".json":
            data = json.loads(content)
            # Truncate very large artifacts to avoid context overflow
            compact = json.dumps(data, default=str)
            if len(compact) > 15000:
                compact = compact[:15000] + "\n... [TRUNCATED — artifact too large for context]"
            return compact
        return content[:15000]
    except Exception as e:
        return json.dumps({"status": "ERROR", "message": str(e)})


@tool
def write_artifact(
    artifact_type: str,
    artifact_content: str,
    output_path: str,
    state: Annotated[dict, InjectedState] = None,
) -> str:
    """
    Write an analytical artifact (JSON) to disk.

    Use this to persist business_objectives, preprocessing_blueprint,
    approved_insights, approved_visualizations, or any other artifact.

    Args:
        artifact_type: One of 'business_objectives', 'preprocessing_blueprint',
                       'approved_insights', 'approved_visualizations', or
                       a custom artifact name.
        artifact_content: The JSON string to write. Must be valid JSON.
        output_path: Where to save the artifact (e.g. 'artifacts/business_objectives.json').

    Returns:
        JSON with status, artifact_type, and artifact_path.
    """
    if state and state.get("input_artifacts", {}).get("output_dir"):
        output_path = str(Path(state["input_artifacts"]["output_dir"]) / Path(output_path).name)

    p = Path(output_path)
    p.parent.mkdir(parents=True, exist_ok=True)

    try:
        # Validate JSON
        data = json.loads(artifact_content)
        p.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        return json.dumps({
            "status": "ok",
            "artifact_type": artifact_type,
            "artifact_path": str(p),
        })
    except json.JSONDecodeError as e:
        # If the content is not valid JSON, write it as raw text
        p.write_text(artifact_content, encoding="utf-8")
        return json.dumps({
            "status": "ok",
            "artifact_type": artifact_type,
            "artifact_path": str(p),
            "warning": f"Content was not valid JSON: {e}. Saved as raw text.",
        })
    except Exception as e:
        return json.dumps({"status": "ERROR", "message": str(e)})


@tool
def read_dataset_sample(
    file_path: str,
    n_rows: int = 20,
) -> str:
    """
    Read the first N rows of a dataset and return as JSON records.

    Use this to understand the data without loading the full dataset.
    Also returns column types, shape, and null counts.

    Args:
        file_path: Path to the CSV / Parquet / Excel file.
        n_rows: Number of rows to return (default 20, max 50).

    Returns:
        JSON with shape, columns, dtypes, null_counts, and sample_rows.
    """
    n_rows = min(n_rows, 50)
    try:
        df = _read_df(file_path)
        return json.dumps({
            "status": "ok",
            "shape": list(df.shape),
            "columns": list(df.columns),
            "dtypes": df.dtypes.astype(str).to_dict(),
            "null_counts": df.isnull().sum().to_dict(),
            "sample_rows": df.head(n_rows).to_dict(orient="records"),
        }, default=str)
    except Exception as e:
        return json.dumps({"status": "ERROR", "message": str(e)})


@tool
def compute_statistics(
    file_path: str,
    group_by: Optional[List[str]] = None,
    agg_columns: Optional[List[str]] = None,
    agg_functions: Optional[List[str]] = None,
    correlation_columns: Optional[List[str]] = None,
) -> str:
    """
    Compute aggregation statistics and/or correlations on a dataset.

    Use this to generate evidence for insights. You can group by one or more
    columns and aggregate measures, or compute pairwise correlations.

    Args:
        file_path: Path to the dataset.
        group_by: Columns to group by (optional). If None, computes over entire dataset.
        agg_columns: Columns to aggregate (required if group_by is set).
        agg_functions: Aggregation functions to apply: 'sum', 'mean', 'median',
                       'min', 'max', 'count', 'std'. Defaults to ['mean'].
        correlation_columns: Columns to compute pairwise correlation for (optional).

    Returns:
        JSON with aggregation_result and/or correlation_matrix.
    """
    try:
        df = _read_df(file_path)
        result = {}

        # Aggregation
        if group_by:
            agg_fns = agg_functions or ["mean"]
            cols = agg_columns or [
                c for c in df.columns
                if pd.api.types.is_numeric_dtype(df[c]) and c not in group_by
            ]
            if cols:
                agg_dict = {c: agg_fns for c in cols}
                grouped = df.groupby(group_by).agg(agg_dict)
                # Flatten multi-level columns
                grouped.columns = ["_".join(col).strip() for col in grouped.columns]
                grouped = grouped.reset_index()
                # Limit rows to prevent context overflow
                if len(grouped) > 100:
                    grouped = grouped.head(100)
                result["aggregation_result"] = grouped.to_dict(orient="records")
            else:
                result["aggregation_result"] = "No numeric columns found for aggregation."
        elif agg_columns:
            # No group_by — just compute stats on the full dataset
            agg_fns = agg_functions or ["mean"]
            stats = {}
            for col in agg_columns:
                if col in df.columns and pd.api.types.is_numeric_dtype(df[col]):
                    stats[col] = {}
                    for fn in agg_fns:
                        stats[col][fn] = float(df[col].agg(fn))
            result["aggregation_result"] = stats

        # Correlation
        if correlation_columns:
            valid_cols = [
                c for c in correlation_columns
                if c in df.columns and pd.api.types.is_numeric_dtype(df[c])
            ]
            if valid_cols:
                corr = df[valid_cols].corr()
                result["correlation_matrix"] = corr.round(4).to_dict()
            else:
                result["correlation_matrix"] = "No valid numeric columns for correlation."

        # If nothing was requested, return basic describe()
        if not result:
            desc = df.describe().to_dict()
            result["describe"] = desc

        return json.dumps(result, default=str)

    except Exception as e:
        return json.dumps({"status": "ERROR", "message": str(e)})


@tool
def generate_echarts_option(
    visualization_id: str,
    title: str,
    echarts_option: str,
    output_path: str,
    state: Annotated[dict, InjectedState] = None,
) -> str:
    """
    Validate and persist an ECharts option JSON to an artifact file.

    Use this for Step 6 to generate production-ready ECharts configurations.

    Args:
        visualization_id: Unique ID for this visualization (e.g. 'viz_001').
        title: Human-readable chart title.
        echarts_option: The complete ECharts option JSON as a string.
        output_path: Where to save (e.g. 'artifacts/echarts_viz_001.json').

    Returns:
        JSON with status and saved path.
    """
    if state and state.get("input_artifacts", {}).get("output_dir"):
        output_path = str(Path(state["input_artifacts"]["output_dir"]) / Path(output_path).name)

    p = Path(output_path)
    p.parent.mkdir(parents=True, exist_ok=True)

    try:
        option = json.loads(echarts_option)
    except json.JSONDecodeError as e:
        return json.dumps({
            "status": "ERROR",
            "message": f"Invalid ECharts JSON: {e}",
        })

    # Basic structural validation
    warnings = []
    if "series" not in option and "dataset" not in option:
        warnings.append("ECharts option has no 'series' or 'dataset' — may not render.")
    if "title" not in option:
        option["title"] = {"text": title}

    artifact = {
        "visualization_id": visualization_id,
        "title": title,
        "echarts_option": option,
        "generated_at": datetime.utcnow().isoformat(),
        "warnings": warnings,
    }

    p.write_text(json.dumps(artifact, indent=2, default=str), encoding="utf-8")

    return json.dumps({
        "status": "ok",
        "artifact_type": "echarts_visualization",
        "artifact_path": str(p),
        "visualization_id": visualization_id,
        "warnings": warnings,
    })


@tool
def submit_analyst_report(
    execution_summary: str,
    generated_artifacts: Dict[str, str],
    completed_tasks: List[str],
    failed_tasks: list[str],
    response_data: str | None = None,
):
    """
    Final analytics report returned to supervisor.

    Call this when all assigned tasks are complete. This is the official
    handoff mechanism back to the Supervisor.

    Args:
        execution_summary: Summary of all work performed.
        generated_artifacts: Dict mapping artifact names to their file paths.
        completed_tasks: List of task descriptions that were completed.
        failed_tasks: List of task descriptions that failed.
        response_data: A JSON string containing exactly the schema requested by the supervisor's response_format.
    """

    return json.dumps(
        {
            "division": "Analytics",
            "status": ("FAILED" if failed_tasks else "COMPLETED"),
            "analysis_report": execution_summary,
            "generated_artifacts": generated_artifacts,
            "completed_tasks": completed_tasks,
            "failed_tasks": failed_tasks,
            "report_submitted": True,
            "response_data": response_data,
        }
    )


ANALYST_TOOLS = [
    read_artifact,
    write_artifact,
    read_dataset_sample,
    compute_statistics,
    generate_echarts_option,
    submit_analyst_report,
]
