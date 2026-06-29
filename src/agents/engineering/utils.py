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
    return pd.read_csv(p, engine="pyarrow")


# -----------PROFILE DATA-----------------
def profile_dataset(df: pd.DataFrame):
    profile: dict[str, Any] = {}
    
    if df.empty:
        for col in df.columns:
            profile[col] = {
                "dtype": str(df[col].dtype),
                "null_pct": 0.0,
                "unique": 0,
            }
            if pd.api.types.is_numeric_dtype(df[col]):
                profile[col].update({"min": None, "max": None, "mean": None, "std": None})
        return json.dumps(profile, default=str)
        
    null_pcts = (df.isnull().mean() * 100).round(2)
    n_uniques = df.nunique(dropna=True)
    
    numeric_cols = df.select_dtypes(include='number').columns
    desc = df[numeric_cols].describe() if len(numeric_cols) > 0 else pd.DataFrame()
    
    for col in df.columns:
        entry: dict[str, Any] = {
            "dtype": str(df[col].dtype),
            "null_pct": float(null_pcts[col]),
            "unique": int(n_uniques[col]),
        }
        if col in numeric_cols:
            entry.update({
                "min": float(desc.loc["min", col]) if pd.notna(desc.loc["min", col]) else None,
                "max": float(desc.loc["max", col]) if pd.notna(desc.loc["max", col]) else None,
                "mean": float(desc.loc["mean", col]) if pd.notna(desc.loc["mean", col]) else None,
                "std": float(desc.loc["std", col]) if pd.notna(desc.loc["std", col]) else None,
            })
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
    def _normalize_columns(df: pd.DataFrame, normalize_columns: bool) -> pd.DataFrame:
        if normalize_columns:
            df.columns = (
                df.columns.str.strip()
                .str.lower()
                .str.replace(r"[\s\-\.]+", "_", regex=True)
                .str.replace(r"[^\w]", "", regex=True)
            )
        return df

    # Drop High-null columns
    @staticmethod
    def _drop_null_cols(df: pd.DataFrame, drop_null_threshold: float) -> pd.DataFrame:
        mask = df.isnull().mean() <= drop_null_threshold
        return df.loc[:, mask].copy()

    # Drop duplicates
    @staticmethod
    def _drop_duplicates(df: pd.DataFrame, drop_duplicates: bool) -> pd.DataFrame:
        if drop_duplicates:
            return df.drop_duplicates()
        return df

    # Fill null values
    @staticmethod
    def _fill_nulls(
        df: pd.DataFrame,
        fill_numeric_strategy: str,
        fill_categorical_strategy: str,
    ) -> pd.DataFrame:
        num_cols = df.select_dtypes(include='number').columns
        cat_cols = df.select_dtypes(exclude='number').columns

        if len(num_cols) > 0:
            if fill_numeric_strategy == "median":
                df[num_cols] = df[num_cols].fillna(df[num_cols].median())
            elif fill_numeric_strategy == "mean":
                df[num_cols] = df[num_cols].fillna(df[num_cols].mean())
            elif fill_numeric_strategy == "zero":
                df[num_cols] = df[num_cols].fillna(0)
                
        if len(cat_cols) > 0:
            df[cat_cols] = df[cat_cols].fillna(fill_categorical_strategy)
            
        return df

    # Drop specific columns
    @staticmethod
    def _drop_columns(df: pd.DataFrame, columns_to_drop: list[str] | None) -> pd.DataFrame:
        if not columns_to_drop:
            return df
        cols = [c for c in columns_to_drop if c in df.columns]
        if cols:
            return df.drop(columns=cols)
        return df

    # Execute custom cleaning steps from blueprint
    @staticmethod
    def _execute_cleaning_steps(df: pd.DataFrame, cleaning_steps: list[dict] | None) -> pd.DataFrame:
        if not cleaning_steps:
            return df
        import numpy as np
        for step in cleaning_steps:
            col = step.get("column")
            if not col or col not in df.columns:
                continue
            
            action = str(step.get("action")).lower()
            method = str(step.get("method")).lower()
            
            # Missing value handling
            if "imput" in action or action == "fill":
                if "mean" in method and pd.api.types.is_numeric_dtype(df[col]):
                    df[col] = df[col].fillna(df[col].mean())
                elif "median" in method and pd.api.types.is_numeric_dtype(df[col]):
                    df[col] = df[col].fillna(df[col].median())
                elif "zero" in method or "0" in method:
                    df[col] = df[col].fillna(0)
                elif "mode" in method:
                    mode_val = df[col].mode()
                    if not mode_val.empty:
                        df[col] = df[col].fillna(mode_val[0])
                elif "drop" in method:
                    df = df.dropna(subset=[col])
            
            # Outlier handling
            elif "outlier" in action:
                if pd.api.types.is_numeric_dtype(df[col]):
                    if "iqr" in method:
                        q1 = df[col].quantile(0.25)
                        q3 = df[col].quantile(0.75)
                        iqr = q3 - q1
                        lower = q1 - 1.5 * iqr
                        upper = q3 + 1.5 * iqr
                        # Use boolean masking instead of dropping by index
                        df = df[(df[col] >= lower) & (df[col] <= upper)]
                    elif "z-score" in method or "zscore" in method:
                        mean = df[col].mean()
                        std = df[col].std()
                        if std != 0:
                            z = (df[col] - mean) / std
                            df = df[np.abs(z) <= 3]
                            
            # Explicit column drop within cleaning steps
            elif "drop" in action:
                df = df.drop(columns=[col])

        return df
