from sklearn.linear_model import _stochastic_gradient
import json
from pathlib import Path
from typing import Any

import pandas as pd


# -------- INGEST DATA --------------------
def _read(path: str) -> pd.DataFrame:
    p = Path(path)
    if p.suffix == ".parquet":
        return pd.read_parquet(p)
    if p.suffix in (".xls", ".xlsx"):
        return pd.read_excel(p)
    if p.suffix == ".json":
        return pd.read_json(p)
    return pd.read_csv(p)


# -----------PROFILE DATA-----------------
def profile_dataset(df: pd.DataFrame):
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


##########################################
#             CLEAN DATA                #
##########################################


class CleanData:
    def __init__(self):
        pass

    # Column Normalization
    @staticmethod
    def _normalize_columns(df: pd.DataFrame, normalize_columns: bool):
        # Column normalisation
        if normalize_columns:
            df.columns = (
                df.columns.str.strip()
                .str.lower()
                .str.replace(r"[\s\-\.]+", "_", regex=True)
                .str.replace(r"[^\w]", "", regex=True)
            )

    # Drop High-null columns
    @staticmethod
    def _drop_null_cols(df: pd.DataFrame, drop_null_threshold: float):
        mask = df.isnull().mean() <= drop_null_threshold
        df.drop(columns=df.columns[~mask], inplace=True)

    # Drop duplicates
    @staticmethod
    def _drop_duplicates(df: pd.DataFrame, drop_duplicates: bool):
        if drop_duplicates:
            df.drop_duplicates(inplace=True)

    # Fill null values
    @staticmethod
    def _fill_nulls(
        df: pd.DataFrame,
        fill_numeric_strategy: str,
        fill_categorical_strategy: str,
    ):
        for col in df.columns:
            if pd.api.types.is_numeric_dtype(df[col]):
                if fill_numeric_strategy == "median":
                    df[col].fillna(df[col].median(), inplace=True)
                elif fill_numeric_strategy == "mean":
                    df[col].fillna(df[col].mean(), inplace=True)
                elif fill_numeric_strategy == "zero":
                    df[col].fillna(0, inplace=True)
            else:
                df[col].fillna(fill_categorical_strategy, inplace=True)
