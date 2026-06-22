"""
src/agents/science/tools.py
Tools available to the Lead Data Scientist ReAct agent.

Covers: feature engineering, model training (classification & regression),
evaluation, SHAP explainability, and model persistence.
"""

from __future__ import annotations

import json
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
    return pd.read_parquet(p) if p.suffix == ".parquet" else pd.read_csv(p)


def _save_json(obj: Any, path: str) -> str:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(obj, default=str, indent=2))
    return str(out)


# ── tools ────────────────────────────────────────────────────────────────────


@tool
def engineer_features(
    file_path: str,
    output_path: str,
    lag_columns: list[str] | None = None,
    lag_periods: list[int] | None = None,
    rolling_columns: list[str] | None = None,
    rolling_windows: list[int] | None = None,
    encode_categoricals: bool = True,
    drop_original_dates: bool = True,
) -> str:
    """
    Apply automated feature engineering to a cleaned dataframe.

    Steps:
    - Datetime decomposition (year, month, day, weekday, quarter)
    - Lag features for specified columns
    - Rolling mean features for specified columns
    - One-hot encoding of low-cardinality categoricals (cardinality < 20)

    Args:
        file_path: Input clean parquet/csv.
        output_path: Where to save the feature-engineered parquet.
        lag_columns: Numeric columns to create lag features for.
        lag_periods: Lag periods (e.g. [1, 7, 30]).
        rolling_columns: Numeric columns to create rolling means for.
        rolling_windows: Window sizes (e.g. [7, 30]).
        encode_categoricals: One-hot encode low-cardinality string columns.
        drop_original_dates: Drop original datetime columns after decomposition.
    """
    df = _read(file_path)
    log: list[str] = []

    # Datetime decomposition
    date_cols = df.select_dtypes(include=["datetime64[ns]", "datetime64"]).columns.tolist()
    for col in date_cols:
        df[f"{col}_year"] = df[col].dt.year
        df[f"{col}_month"] = df[col].dt.month
        df[f"{col}_day"] = df[col].dt.day
        df[f"{col}_weekday"] = df[col].dt.weekday
        df[f"{col}_quarter"] = df[col].dt.quarter
        log.append(f"Decomposed datetime column '{col}'.")
        if drop_original_dates:
            df.drop(columns=[col], inplace=True)

    # Lag features
    if lag_columns and lag_periods:
        for col in lag_columns:
            if col in df.columns:
                for lag in lag_periods:
                    df[f"{col}_lag{lag}"] = df[col].shift(lag)
                log.append(f"Created lag features for '{col}': {lag_periods}.")

    # Rolling means
    if rolling_columns and rolling_windows:
        for col in rolling_columns:
            if col in df.columns:
                for win in rolling_windows:
                    df[f"{col}_roll{win}"] = df[col].rolling(window=win, min_periods=1).mean()
                log.append(f"Created rolling mean features for '{col}': {rolling_windows}.")

    # Categorical encoding
    if encode_categoricals:
        cat_cols = [
            c for c in df.select_dtypes(include="object").columns
            if df[c].nunique() < 20
        ]
        if cat_cols:
            df = pd.get_dummies(df, columns=cat_cols, drop_first=False, dtype=int)
            log.append(f"One-hot encoded: {cat_cols}.")

    df.fillna(0, inplace=True)  # fill any NaNs introduced by lag/rolling
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)

    return json.dumps({
        "output_path": str(out),
        "shape": list(df.shape),
        "new_columns": list(df.columns),
        "feature_log": log,
    })


@tool
def train_classifier(
    file_path: str,
    target_column: str,
    model_type: str = "random_forest",
    test_size: float = 0.2,
    output_model_path: str | None = None,
    output_report_path: str | None = None,
) -> str:
    """
    Train a classification model and return evaluation metrics.

    Args:
        file_path: Feature-engineered parquet/csv.
        target_column: Name of the binary/multiclass target column.
        model_type: 'random_forest' | 'gradient_boosting' | 'logistic_regression'.
        test_size: Fraction held out for evaluation (0–1).
        output_model_path: Optional path to pickle the model.
        output_report_path: Optional path to save the metrics JSON report.
    """
    from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import (
        accuracy_score,
        classification_report,
        roc_auc_score,
    )
    from sklearn.model_selection import train_test_split

    df = _read(file_path)
    X = df.drop(columns=[target_column]).select_dtypes(include="number")
    y = df[target_column]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=test_size, random_state=42, stratify=y if y.nunique() < 10 else None
    )

    models = {
        "random_forest": RandomForestClassifier(n_estimators=100, random_state=42, n_jobs=-1),
        "gradient_boosting": GradientBoostingClassifier(n_estimators=100, random_state=42),
        "logistic_regression": LogisticRegression(max_iter=1000, random_state=42),
    }
    model = models.get(model_type, models["random_forest"])
    model.fit(X_train, y_train)

    y_pred = model.predict(X_test)
    acc = round(accuracy_score(y_test, y_pred), 4)
    report = classification_report(y_test, y_pred, output_dict=True)

    auc = None
    if hasattr(model, "predict_proba") and y.nunique() == 2:
        auc = round(float(roc_auc_score(y_test, model.predict_proba(X_test)[:, 1])), 4)

    result: dict[str, Any] = {
        "model_type": model_type,
        "accuracy": acc,
        "roc_auc": auc,
        "classification_report": report,
        "feature_count": X.shape[1],
        "train_rows": len(X_train),
        "test_rows": len(X_test),
        "qa_status": "QA_PASSED" if acc >= 0.70 else "QA_FAILED",
    }

    if output_model_path:
        import pickle
        mp = Path(output_model_path)
        mp.parent.mkdir(parents=True, exist_ok=True)
        mp.write_bytes(pickle.dumps(model))
        result["model_path"] = str(mp)

    if output_report_path:
        _save_json(result, output_report_path)
        result["report_path"] = output_report_path

    return json.dumps(result, default=str)


@tool
def train_regressor(
    file_path: str,
    target_column: str,
    model_type: str = "random_forest",
    test_size: float = 0.2,
    output_model_path: str | None = None,
    output_report_path: str | None = None,
) -> str:
    """
    Train a regression model and return evaluation metrics.

    Args:
        file_path: Feature-engineered parquet/csv.
        target_column: Numeric target column.
        model_type: 'random_forest' | 'gradient_boosting' | 'linear_regression'.
        test_size: Hold-out fraction.
        output_model_path: Optional path to pickle the model.
        output_report_path: Optional path to save the metrics JSON.
    """
    from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
    from sklearn.linear_model import LinearRegression
    from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
    from sklearn.model_selection import train_test_split

    df = _read(file_path)
    X = df.drop(columns=[target_column]).select_dtypes(include="number")
    y = df[target_column]

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=test_size, random_state=42)

    models = {
        "random_forest": RandomForestRegressor(n_estimators=100, random_state=42, n_jobs=-1),
        "gradient_boosting": GradientBoostingRegressor(n_estimators=100, random_state=42),
        "linear_regression": LinearRegression(),
    }
    model = models.get(model_type, models["random_forest"])
    model.fit(X_train, y_train)

    y_pred = model.predict(X_test)
    r2 = round(float(r2_score(y_test, y_pred)), 4)
    mae = round(float(mean_absolute_error(y_test, y_pred)), 4)
    rmse = round(float(np.sqrt(mean_squared_error(y_test, y_pred))), 4)

    result: dict[str, Any] = {
        "model_type": model_type,
        "r2_score": r2,
        "mae": mae,
        "rmse": rmse,
        "feature_count": X.shape[1],
        "train_rows": len(X_train),
        "test_rows": len(X_test),
        "qa_status": "QA_PASSED" if r2 >= 0.70 else "QA_FAILED",
    }

    if output_model_path:
        import pickle
        mp = Path(output_model_path)
        mp.parent.mkdir(parents=True, exist_ok=True)
        mp.write_bytes(pickle.dumps(model))
        result["model_path"] = str(mp)

    if output_report_path:
        _save_json(result, output_report_path)

    return json.dumps(result, default=str)


@tool
def explain_model_shap(
    file_path: str,
    model_path: str,
    target_column: str,
    output_path: str,
    max_samples: int = 500,
) -> str:
    """
    Compute SHAP feature importances for a pickled sklearn model and save results.

    Returns top feature importances as a dict and an ECharts bar chart option
    for rendering SHAP importance in the UI.

    Args:
        file_path: Feature file (same one used for training).
        model_path: Path to the pickled sklearn model.
        target_column: Target column to exclude from features.
        output_path: Where to save the SHAP JSON report.
        max_samples: Max rows to run SHAP on (speed cap).
    """
    import pickle

    import shap

    model = pickle.loads(Path(model_path).read_bytes())
    df = _read(file_path).head(max_samples)
    X = df.drop(columns=[target_column]).select_dtypes(include="number")

    explainer = shap.TreeExplainer(model) if hasattr(model, "feature_importances_") \
        else shap.LinearExplainer(model, X)
    shap_values = explainer.shap_values(X)

    # For multiclass, take absolute mean across classes
    if isinstance(shap_values, list):
        importance = np.abs(np.stack(shap_values, axis=0)).mean(axis=(0, 1))
    else:
        importance = np.abs(shap_values).mean(axis=0)

    feat_imp = dict(sorted(zip(X.columns.tolist(), importance.tolist()),
                            key=lambda x: x[1], reverse=True))
    top_features = list(feat_imp.keys())[:20]
    top_values = [round(feat_imp[f], 6) for f in top_features]

    echarts_option = {
        "title": {"text": "SHAP Feature Importance", "left": "center"},
        "tooltip": {"trigger": "axis"},
        "xAxis": {"type": "value", "name": "Mean |SHAP|"},
        "yAxis": {"type": "category", "data": top_features[::-1]},
        "series": [{"type": "bar", "data": top_values[::-1]}],
        "grid": {"left": "20%", "containLabel": True},
    }

    report = {
        "feature_importances": feat_imp,
        "echarts_option": echarts_option,
    }
    _save_json(report, output_path)
    return json.dumps(report, default=str)


@tool
def compute_feature_importance(file_path: str, target_column: str, model_type: str = "random_forest") -> str:
    """
    Quick feature importance ranking without full model persistence.
    Trains a lightweight model and returns ranked feature importances.

    Args:
        file_path: Feature-engineered parquet/csv.
        target_column: Target column name.
        model_type: 'random_forest' | 'gradient_boosting'.
    """
    from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier

    df = _read(file_path)
    X = df.drop(columns=[target_column]).select_dtypes(include="number")
    y = df[target_column]

    model_cls = GradientBoostingClassifier if model_type == "gradient_boosting" \
        else RandomForestClassifier
    model = model_cls(n_estimators=50, random_state=42)
    model.fit(X, y)

    imp = dict(sorted(
        zip(X.columns.tolist(), model.feature_importances_.tolist()),
        key=lambda x: x[1],
        reverse=True,
    ))
    return json.dumps({"feature_importances": imp})


# Registry
SCIENCE_TOOLS = [
    engineer_features,
    train_classifier,
    train_regressor,
    explain_model_shap,
    compute_feature_importance,
]
