"""
src/agents/engineering/tools.py
Tools available to the Lead Data Engineer ReAct agent.

Each function is wrapped with @tool so LangChain can bind it.
"""

from __future__ import annotations

import json
import re
import warnings
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from langchain_core.tools import tool

warnings.filterwarnings("ignore")


# ── helpers ──────────────────────────────────────────────────────────────────

def _read(path: str) -> pd.DataFrame:
    p = Path(path)
    if p.suffix == ".parquet":
        return pd.read_parquet(p)
    if p.suffix in (".xls", ".xlsx"):
        return pd.read_excel(p)
    if p.suffix == ".json":
        return pd.read_json(p)
    return pd.read_csv(p)


def _write_parquet(df: pd.DataFrame, path: str) -> str:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    return str(out)


# ── tools ────────────────────────────────────────────────────────────────────


@tool
def ingest_file(file_path: str) -> str:
    """
    Ingest a CSV / Parquet / Excel / JSON file and return a JSON summary
    containing shape, column names, dtypes, and the first 5 rows.

    Args:
        file_path: Absolute or relative path to the source file.
    """
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


@tool
def profile_dataframe(file_path: str) -> str:
    """
    Run a lightweight profiling pass on a file and return per-column statistics
    (dtype, null %, unique count, min/max/mean for numeric columns).

    Args:
        file_path: Path to the data file.
    """
    df = _read(file_path)
    profile: dict[str, Any] = {}
    for col in df.columns:
        s = df[col]
        entry: dict[str, Any] = {
            "dtype": str(s.dtype),
            "null_pct": round(s.isnull().mean() * 100, 2),
            "unique": int(s.nunique(dropna=True)),
        }
        if pd.api.types.is_numeric_dtype(s):
            entry.update(
                {
                    "min": float(s.min()) if not s.empty else None,
                    "max": float(s.max()) if not s.empty else None,
                    "mean": round(float(s.mean()), 4) if not s.empty else None,
                    "std": round(float(s.std()), 4) if not s.empty else None,
                }
            )
        profile[col] = entry
    return json.dumps(profile, default=str)


@tool
def clean_dataframe(
    file_path: str,
    output_path: str,
    drop_duplicates: bool = True,
    normalize_columns: bool = True,
    fill_numeric_strategy: str = "median",
    fill_categorical_strategy: str = "unknown",
    drop_null_threshold: float = 0.9,
) -> str:
    """
    Apply standard cleaning steps to a dataframe and write a parquet output.

    Steps: column normalisation → drop high-null cols → duplicate removal →
    numeric null-fill → categorical null-fill → dtype coercion where safe.

    Args:
        file_path: Input data path.
        output_path: Where to write the cleaned parquet.
        drop_duplicates: Whether to remove exact duplicate rows.
        normalize_columns: Lowercase + underscore column names.
        fill_numeric_strategy: 'median' | 'mean' | 'zero'.
        fill_categorical_strategy: Fill string with this value.
        drop_null_threshold: Drop columns with null fraction > this value (0–1).

    Returns:
        JSON with output_path, shape_before, shape_after, cleaning_log.
    """
    df = _read(file_path)
    log: list[str] = []
    shape_before = list(df.shape)

    # Column normalisation
    if normalize_columns:
        df.columns = (
            df.columns.str.strip()
            .str.lower()
            .str.replace(r"[\s\-\.]+", "_", regex=True)
            .str.replace(r"[^\w]", "", regex=True)
        )
        log.append("Column names normalised.")

    # Drop high-null columns
    null_fracs = df.isnull().mean()
    high_null = null_fracs[null_fracs > drop_null_threshold].index.tolist()
    if high_null:
        df.drop(columns=high_null, inplace=True)
        log.append(f"Dropped high-null columns (>{drop_null_threshold*100:.0f}%): {high_null}")

    # Duplicates
    if drop_duplicates:
        before = len(df)
        df.drop_duplicates(inplace=True)
        removed = before - len(df)
        if removed:
            log.append(f"Removed {removed} duplicate rows.")

    # Numeric null-fill
    num_cols = df.select_dtypes(include="number").columns.tolist()
    for col in num_cols:
        if df[col].isnull().any():
            if fill_numeric_strategy == "median":
                val = df[col].median()
            elif fill_numeric_strategy == "mean":
                val = df[col].mean()
            else:
                val = 0
            df[col].fillna(val, inplace=True)
            log.append(f"Filled '{col}' nulls with {fill_numeric_strategy}={round(val, 4)}.")

    # Categorical null-fill
    cat_cols = df.select_dtypes(exclude="number").columns.tolist()
    for col in cat_cols:
        if df[col].isnull().any():
            df[col].fillna(fill_categorical_strategy, inplace=True)
            log.append(f"Filled '{col}' nulls with '{fill_categorical_strategy}'.")

    out = _write_parquet(df, output_path)
    return json.dumps(
        {
            "output_path": out,
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
def detect_pii_columns(file_path: str) -> str:
    """
    Heuristically detect columns that may contain PII (email, phone, SSN, name).

    Args:
        file_path: Path to the data file.

    Returns:
        JSON list of suspected PII column names with detection reason.
    """
    df = _read(file_path)
    pii_patterns = {
        "email": re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"),
        "phone": re.compile(r"\+?\d[\d\s\-().]{7,}\d"),
        "ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    }
    name_hints = ["name", "firstname", "lastname", "fullname", "customer_name"]
    results: dict[str, str] = {}

    for col in df.select_dtypes(include="object").columns:
        col_lower = col.lower().replace(" ", "_")
        if any(hint in col_lower for hint in name_hints):
            results[col] = "name_keyword_match"
            continue
        sample = df[col].dropna().astype(str).head(100)
        for pii_type, pattern in pii_patterns.items():
            if sample.str.contains(pattern, regex=True).any():
                results[col] = pii_type
                break

    return json.dumps({"pii_columns": results})


@tool
def export_data_summary(file_path: str, output_json_path: str) -> str:
    """
    Export a full data quality summary (shape, dtypes, null counts, sample rows)
    to a JSON file for downstream agents to reference.

    Args:
        file_path: Source data file.
        output_json_path: Where to write the JSON summary.
    """
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


# Registry — used by the agent builder
ENGINEERING_TOOLS = [
    ingest_file,
    profile_dataframe,
    clean_dataframe,
    validate_schema,
    detect_pii_columns,
    export_data_summary,
]
