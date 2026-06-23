import json
import pandas as pd
from pathlib import Path
from langchain_core.tools import tool

from .utils import _read, profile_dataset, CleanData

clean_data = CleanData()


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
def profile_dataset(file_path: str):
    """
    Run a lightweight profiling pass on a file and return per-column statistics
    (dtype, null %, unique count, min/max/mean for numeric columns).

    Args:
        file_path: Path to the data file.
    """
    try:
        df = _read(file_path)
        return profile_dataset(df)
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
):
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
    df.to_parquet(output_path, index=False)
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


# tool registry
ENGINEERING_TOOLS = [
    ingest_dataset,
    profile_dataset,
    clean_dataset,
    validate_schema,
    export_data_summary,
]
