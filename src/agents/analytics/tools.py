"""
src/agents/analytics/tools.py
Tools available to the Lead Data Analyst ReAct agent.

Covers: EDA statistics, ECharts JSON generation, column semantics,
insight extraction, and chart audit helpers.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from langchain_core.tools import tool


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


def _write_json(obj: Any, path: str) -> str:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(obj, default=str, indent=2))
    return str(out)


# ── EDA tools ────────────────────────────────────────────────────────────────


@tool
def compute_distribution_stats(file_path: str, columns: list[str] | None = None) -> str:
    """
    Compute distribution statistics (mean, median, std, skewness, kurtosis,
    quartiles) for numeric columns in a dataframe.

    Args:
        file_path: Path to the data file.
        columns: Specific numeric columns to analyse. None = all numeric.
    """
    df = _read(file_path)
    num = df.select_dtypes(include="number")
    if columns:
        num = num[[c for c in columns if c in num.columns]]

    stats: dict[str, Any] = {}
    for col in num.columns:
        s = num[col].dropna()
        stats[col] = {
            "count": int(s.count()),
            "mean": round(float(s.mean()), 4),
            "median": round(float(s.median()), 4),
            "std": round(float(s.std()), 4),
            "skewness": round(float(s.skew()), 4),
            "kurtosis": round(float(s.kurt()), 4),
            "q25": round(float(s.quantile(0.25)), 4),
            "q75": round(float(s.quantile(0.75)), 4),
            "min": round(float(s.min()), 4),
            "max": round(float(s.max()), 4),
        }
    return json.dumps(stats)


@tool
def compute_correlation_matrix(file_path: str, output_json_path: str) -> str:
    """
    Compute Pearson correlation matrix for all numeric columns and save to JSON.

    Args:
        file_path: Path to the data file.
        output_json_path: Where to write the correlation JSON.
    """
    df = _read(file_path)
    corr = df.select_dtypes(include="number").corr().round(4)
    result = corr.to_dict()
    _write_json(result, output_json_path)
    return json.dumps({"status": "ok", "output_path": output_json_path, "matrix": result})


@tool
def compute_value_counts(file_path: str, column: str, top_n: int = 20) -> str:
    """
    Return value frequency counts for a categorical column.

    Args:
        file_path: Path to the data file.
        column: Column name to count.
        top_n: Return only the top N categories.
    """
    df = _read(file_path)
    if column not in df.columns:
        return json.dumps({"error": f"Column '{column}' not found."})
    vc = df[column].value_counts().head(top_n)
    return json.dumps(
        {
            "column": column,
            "total_unique": int(df[column].nunique()),
            "top_values": vc.to_dict(),
        },
        default=str,
    )


@tool
def compute_time_series_trend(
    file_path: str,
    date_column: str,
    value_column: str,
    freq: str = "M",
    output_json_path: str | None = None,
) -> str:
    """
    Aggregate a numeric column by a date column at the given frequency.

    Args:
        file_path: Path to the data file.
        date_column: Name of the datetime column.
        value_column: Numeric column to aggregate (sum).
        freq: Pandas offset alias — 'D' daily, 'W' weekly, 'M' monthly, 'Q' quarterly, 'Y' yearly.
        output_json_path: Optional path to write the resulting JSON.
    """
    df = _read(file_path)
    df[date_column] = pd.to_datetime(df[date_column], errors="coerce")
    ts = (
        df.set_index(date_column)[value_column]
        .resample(freq)
        .sum()
        .reset_index()
        .rename(columns={date_column: "period", value_column: "value"})
    )
    ts["period"] = ts["period"].astype(str)
    result = ts.to_dict(orient="records")
    if output_json_path:
        _write_json(result, output_json_path)
    return json.dumps(result)


# ── ECharts chart generation ─────────────────────────────────────────────────


@tool
def generate_bar_chart(
    file_path: str,
    category_column: str,
    value_column: str,
    title: str = "Bar Chart",
    output_json_path: str | None = None,
) -> str:
    """
    Generate an Apache ECharts bar chart option JSON from a dataframe.

    Args:
        file_path: Path to the data file.
        category_column: Column used as X-axis categories.
        value_column: Numeric column used for bar heights (sum aggregation).
        title: Chart title string.
        output_json_path: Optional path to save the ECharts option JSON.
    """
    df = _read(file_path)
    agg = df.groupby(category_column)[value_column].sum().reset_index()
    categories = agg[category_column].astype(str).tolist()
    values = agg[value_column].round(4).tolist()

    option = {
        "title": {"text": title, "left": "center"},
        "tooltip": {"trigger": "axis"},
        "xAxis": {"type": "category", "data": categories, "axisLabel": {"rotate": 30}},
        "yAxis": {"type": "value"},
        "series": [{"type": "bar", "data": values, "name": value_column}],
        "grid": {"containLabel": True},
    }
    if output_json_path:
        _write_json(option, output_json_path)
    return json.dumps(option)


@tool
def generate_line_chart(
    file_path: str,
    x_column: str,
    y_columns: list[str],
    title: str = "Line Chart",
    output_json_path: str | None = None,
) -> str:
    """
    Generate an ECharts multi-line chart option JSON.

    Args:
        file_path: Path to the data file.
        x_column: Column for the X-axis (date or category).
        y_columns: List of numeric column names to plot as separate lines.
        title: Chart title.
        output_json_path: Optional save path.
    """
    df = _read(file_path)
    df = df[[x_column] + y_columns].dropna(subset=[x_column]).sort_values(x_column)
    x_data = df[x_column].astype(str).tolist()

    series = [
        {
            "name": col,
            "type": "line",
            "data": df[col].round(4).tolist(),
            "smooth": True,
        }
        for col in y_columns
    ]
    option = {
        "title": {"text": title, "left": "center"},
        "tooltip": {"trigger": "axis"},
        "legend": {"data": y_columns, "top": "8%"},
        "xAxis": {"type": "category", "data": x_data},
        "yAxis": {"type": "value"},
        "series": series,
        "grid": {"containLabel": True},
    }
    if output_json_path:
        _write_json(option, output_json_path)
    return json.dumps(option)


@tool
def generate_pie_chart(
    file_path: str,
    category_column: str,
    value_column: str,
    title: str = "Pie Chart",
    top_n: int = 10,
    output_json_path: str | None = None,
) -> str:
    """
    Generate an ECharts pie/donut chart option JSON.

    Args:
        file_path: Path to the data file.
        category_column: Column for slice labels.
        value_column: Numeric column for slice sizes.
        title: Chart title.
        top_n: Keep only top N slices; remainder grouped as 'Other'.
        output_json_path: Optional save path.
    """
    df = _read(file_path)
    agg = df.groupby(category_column)[value_column].sum().reset_index()
    agg = agg.sort_values(value_column, ascending=False)

    if len(agg) > top_n:
        top = agg.head(top_n)
        other_val = agg.iloc[top_n:][value_column].sum()
        other = pd.DataFrame(
            [{category_column: "Other", value_column: other_val}]
        )
        agg = pd.concat([top, other], ignore_index=True)

    pie_data = [
        {"name": str(row[category_column]), "value": round(float(row[value_column]), 4)}
        for _, row in agg.iterrows()
    ]
    option = {
        "title": {"text": title, "left": "center"},
        "tooltip": {"trigger": "item", "formatter": "{b}: {c} ({d}%)"},
        "legend": {"orient": "vertical", "left": "left"},
        "series": [
            {
                "type": "pie",
                "radius": ["40%", "70%"],
                "data": pie_data,
                "label": {"formatter": "{b}: {d}%"},
            }
        ],
    }
    if output_json_path:
        _write_json(option, output_json_path)
    return json.dumps(option)


@tool
def generate_scatter_chart(
    file_path: str,
    x_column: str,
    y_column: str,
    color_column: str | None = None,
    title: str = "Scatter Plot",
    output_json_path: str | None = None,
) -> str:
    """
    Generate an ECharts scatter plot option JSON.

    Args:
        file_path: Path to the data file.
        x_column: Numeric column for X axis.
        y_column: Numeric column for Y axis.
        color_column: Optional categorical column to group series by colour.
        title: Chart title.
        output_json_path: Optional save path.
    """
    df = _read(file_path)
    df = df[[x_column, y_column] + ([color_column] if color_column else [])].dropna()

    if color_column:
        series = []
        for grp, sub in df.groupby(color_column):
            series.append(
                {
                    "name": str(grp),
                    "type": "scatter",
                    "data": sub[[x_column, y_column]].round(4).values.tolist(),
                }
            )
    else:
        series = [
            {
                "type": "scatter",
                "data": df[[x_column, y_column]].round(4).values.tolist(),
            }
        ]

    option = {
        "title": {"text": title, "left": "center"},
        "tooltip": {"trigger": "item"},
        "xAxis": {"name": x_column, "type": "value"},
        "yAxis": {"name": y_column, "type": "value"},
        "series": series,
    }
    if output_json_path:
        _write_json(option, output_json_path)
    return json.dumps(option)


@tool
def generate_heatmap_chart(
    file_path: str,
    x_column: str,
    y_column: str,
    value_column: str,
    title: str = "Heatmap",
    output_json_path: str | None = None,
) -> str:
    """
    Generate an ECharts heatmap option JSON from three columns (x, y, value).

    Args:
        file_path: Path to the data file.
        x_column: Column for X-axis categories.
        y_column: Column for Y-axis categories.
        value_column: Numeric column for cell intensity.
        title: Chart title.
        output_json_path: Optional save path.
    """
    df = _read(file_path)
    pivot = df.groupby([x_column, y_column])[value_column].sum().reset_index()
    x_cats = pivot[x_column].unique().tolist()
    y_cats = pivot[y_column].unique().tolist()
    x_idx = {v: i for i, v in enumerate(x_cats)}
    y_idx = {v: i for i, v in enumerate(y_cats)}

    data = [
        [x_idx[row[x_column]], y_idx[row[y_column]], round(float(row[value_column]), 4)]
        for _, row in pivot.iterrows()
    ]
    option = {
        "title": {"text": title, "left": "center"},
        "tooltip": {"position": "top"},
        "xAxis": {"type": "category", "data": [str(v) for v in x_cats]},
        "yAxis": {"type": "category", "data": [str(v) for v in y_cats]},
        "visualMap": {
            "min": pivot[value_column].min(),
            "max": pivot[value_column].max(),
            "calculable": True,
            "orient": "horizontal",
            "left": "center",
            "bottom": "5%",
        },
        "series": [{"type": "heatmap", "data": data, "label": {"show": False}}],
    }
    if output_json_path:
        _write_json(option, output_json_path)
    return json.dumps(option)


@tool
def extract_top_insights(
    stats_json: str,
    top_n: int = 5,
) -> str:
    """
    Given a JSON string of distribution stats (from compute_distribution_stats),
    extract the top N noteworthy observations as a bullet-point summary.

    Args:
        stats_json: JSON string from compute_distribution_stats.
        top_n: How many insights to surface.
    """
    try:
        stats = json.loads(stats_json)
    except json.JSONDecodeError:
        return json.dumps({"error": "Invalid stats_json input."})

    insights: list[str] = []
    for col, s in stats.items():
        skew = abs(s.get("skewness", 0))
        if skew > 1.5:
            direction = "right" if s["skewness"] > 0 else "left"
            insights.append(
                f"'{col}' is heavily {direction}-skewed (skewness={s['skewness']:.2f})."
            )
        spread = s.get("std", 0)
        mean_val = s.get("mean", 1) or 1
        cv = spread / mean_val if mean_val else 0
        if cv > 1:
            insights.append(
                f"'{col}' has high variability (CV={cv:.2f}), suggesting outliers or multi-modal distribution."
            )
        if s.get("min") is not None and s["min"] < 0 and s.get("mean", 0) > 0:
            insights.append(
                f"'{col}' has negative values (min={s['min']}) — may indicate refunds/corrections."
            )

    return json.dumps({"insights": insights[:top_n]})


# Registry
ANALYTICS_TOOLS = [
    compute_distribution_stats,
    compute_correlation_matrix,
    compute_value_counts,
    compute_time_series_trend,
    generate_bar_chart,
    generate_line_chart,
    generate_pie_chart,
    generate_scatter_chart,
    generate_heatmap_chart,
    extract_top_insights,
]
