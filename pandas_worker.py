import pandas as pd
# pyrefly: ignore [missing-import]
import numpy as np
import json
import re
import logging
import os

def setup_logger(name, log_file, level=logging.INFO):
    """Function to dynamically set up as many loggers as you want."""
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    handler = logging.FileHandler(log_file)        
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s: %(message)s'))

    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.addHandler(handler)
    
    return logger

# llm_logger = setup_logger('llm', 'logs/llm.log', logging.INFO)
pandas_worker_logger = setup_logger('pandas_worker', 'logs/pandas_worker.log', logging.INFO)

# =========================================================
# ORDINAL SORT ORDERS
# =========================================================
# Canonical orderings for common ordinal categories.
# Keys are frozensets of the expected values (lowercased) so
# we can auto-detect which ordering applies to a column.

MONTH_ABBR_ORDER = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

MONTH_FULL_ORDER = ["January", "February", "March", "April", "May", "June",
                    "July", "August", "September", "October", "November", "December"]

DAY_ABBR_ORDER = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

DAY_FULL_ORDER = ["Monday", "Tuesday", "Wednesday", "Thursday",
                  "Friday", "Saturday", "Sunday"]

QUARTER_ORDER = ["Q1", "Q2", "Q3", "Q4"]

# Each entry: (frozenset of lowercased canonical values, ordered list)
_ORDINAL_CATALOGS = [
    (frozenset(v.lower() for v in MONTH_ABBR_ORDER), MONTH_ABBR_ORDER),
    (frozenset(v.lower() for v in MONTH_FULL_ORDER), MONTH_FULL_ORDER),
    (frozenset(v.lower() for v in DAY_ABBR_ORDER), DAY_ABBR_ORDER),
    (frozenset(v.lower() for v in DAY_FULL_ORDER), DAY_FULL_ORDER),
    (frozenset(v.lower() for v in QUARTER_ORDER), QUARTER_ORDER),
]

# Regex for age-band style values like "0-10", "11-20", "21-30", etc.
_AGE_BAND_RE = re.compile(r"^(\d+)\s*[-–]\s*(\d+)$")

#--------------------------------
# AGGREGATION FUNCTION MAP
#--------------------------------
q1 = lambda x: x.quantile(0.25)
q1.__name__ = "q1"

q3 = lambda x: x.quantile(0.75)
q3.__name__ = "q3"

agg_map = {
        "SUM": "sum",
        "sum": "sum",
        "AVERAGE": "mean",
        "average": "mean",
        "MAX": "max",
        "max": "max",
        "MIN": "min",
        "min": "min",
        "COUNT": "count",
        "count": "count",
        "MEDIAN": "median",
        "median": "median",
        "STD": "std",
        "std": "std",
        "VAR": "var",
        "var": "var",
        "Q1": q1,
        "Q3": q3,
    }


def _detect_ordinal_order(series: pd.Series):
    """
    Given a pandas Series, return a list representing the correct
    ordinal sort order if the values match a known ordinal pattern,
    or None if no pattern is detected.
    """
    unique_vals = series.dropna().unique()
    unique_lower = frozenset(str(v).lower() for v in unique_vals)

    # Check against known catalogs (months, days, quarters)
    for catalog_set, catalog_order in _ORDINAL_CATALOGS:
        if unique_lower.issubset(catalog_set):
            # Return only the values that actually appear, in order
            present = [v for v in catalog_order if v.lower() in unique_lower]
            return present

    # Check for age-band / numeric-range patterns (e.g. "0-10", "11-20")
    if all(_AGE_BAND_RE.match(str(v).strip()) for v in unique_vals):
        # Sort by the lower bound of each range
        def _lower_bound(val):
            m = _AGE_BAND_RE.match(str(val).strip())
            return int(m.group(1)) if m else 0
        return sorted(unique_vals, key=_lower_bound)

    return None


class PandasWorker:
    def __init__(self):
        pass

    # =========================================================
    # RADAR CHART DATA PROCESSING
    # =========================================================
    # Radar charts require a fundamentally different data shape
    # than standard x/y charts: an array of "indicator" objects
    # (the spokes) and series where each entry has a "value"
    # array matching those indicators.
    #
    # Two patterns are supported:
    #   1. Single-metric radar: one numeric column aggregated
    #      per category (e.g., avg overall_rating per position).
    #      Categories become the radar spokes.
    #   2. Multi-metric radar: multiple numeric columns each
    #      become a spoke, optionally grouped by a category
    #      for multiple series overlays.
    # =========================================================
    def process_radar_config(self, df, config, chart_type=None):
        """
        Process data specifically for radar charts.

        Returns a dict with:
            - "indicators": list of {"name": str, "max": number}
            - "series_data": list of {"name": str, "value": [numbers]}
            - "group_by": the group_by columns used (for downstream reference)

        This bypasses the standard process_chart_config flow because
        radar data doesn't fit the tabular x/y pattern.
        """
        encodings = config.get("encodings") or {}

        x_config = encodings.get("x_axis OR name") or {}
        y_config = encodings.get("y_axis OR value") or {}

        group_by = (
            encodings.get("granularity") or {}
        ).get("group_by", [])

        # --- Normalize group_by ---
        if not group_by or str(group_by).lower() in ("null", "none"):
            group_by = []
        elif isinstance(group_by, str):
            group_by = [group_by]

        # --- Apply pre-aggregation filtering ---
        # (reuse the same filtering logic as standard charts)
        df = self.apply_pre_aggregation(df, x_config, y_config)

        x_col = x_config.get("column")   # category column (e.g., "position")
        y_col = y_config.get("column")    # metric column (e.g., "overall_rating")
        agg = y_config.get("aggregation")

        # --- Determine indicator columns ---
        # Check for explicit radar_indicators in the encoding
        radar_indicators = encodings.get("radar_indicators", [])
        if isinstance(radar_indicators, str):
            radar_indicators = [radar_indicators]
        # Filter to only columns that actually exist and are numeric
        radar_indicators = [
            c for c in radar_indicators
            if c in df.columns and pd.api.types.is_numeric_dtype(df[c])
        ]

        # --- Determine aggregation method ---
        if isinstance(agg, str) and agg.lower() not in ("null", "none", ""):
            method = agg_map.get(agg, "mean")
        else:
            method = "mean"  # default to mean for radar charts

        # -------------------------------------------------------
        # PATTERN 1: Single-metric radar (categories as spokes)
        # -------------------------------------------------------
        # When we have a category column (x_col) and a single
        # numeric column (y_col), each unique category value
        # becomes a spoke on the radar, and the aggregated
        # metric value fills the data.
        # -------------------------------------------------------
        if not radar_indicators and x_col and y_col and x_col in df.columns and y_col in df.columns:
            pandas_worker_logger.info(
                f"Radar: single-metric pattern — categories={x_col}, metric={y_col}, agg={method}"
            )

            # Group by the category column and aggregate the metric
            grouped = (
                df.groupby(x_col, observed=True, sort=False)[y_col]
                .agg(method)
                .reset_index()
            )

            # --- Apply top_n if specified ---
            top_n = (x_config.get("transformation") or {}).get("top_n")
            if top_n and str(top_n).lower() not in ("null", "none", "") and str(top_n).isdigit():
                grouped = grouped.sort_values(by=y_col, ascending=False).head(int(top_n))

            # Build the indicator list (one per category)
            categories = grouped[x_col].tolist()
            values = grouped[y_col].tolist()

            # Calculate max for each indicator (use a buffer of 10% above max)
            global_max = max(values) if values else 100
            indicator_max = round(global_max * 1.1, 2)

            indicators = [
                {"name": str(cat), "max": indicator_max}
                for cat in categories
            ]

            # Single series with all values
            series_data = [
                {
                    "name": str(y_col),
                    "value": [round(v, 2) if isinstance(v, float) else v for v in values]
                }
            ]

            return {
                "indicators": indicators,
                "series_data": series_data,
                "group_by": group_by
            }

        # -------------------------------------------------------
        # PATTERN 2: Multi-metric radar (columns as spokes)
        # -------------------------------------------------------
        # When radar_indicators lists multiple numeric columns,
        # each column becomes a spoke. If a group_by column is
        # present, each unique group becomes a separate series.
        # -------------------------------------------------------
        if radar_indicators:
            pandas_worker_logger.info(
                f"Radar: multi-metric pattern — indicators={radar_indicators}, group_by={group_by}"
            )

            # Calculate global max for each indicator column
            indicators = []
            for col in radar_indicators:
                col_max = df[col].max()
                indicator_max = round(col_max * 1.1, 2) if pd.notna(col_max) else 100
                indicators.append({"name": col, "max": indicator_max})

            series_data = []
            if group_by:
                # Filter group_by to existing columns
                valid_groups = [c for c in group_by if c in df.columns]
                if valid_groups:
                    for keys, grp in df.groupby(valid_groups, observed=True, sort=False):
                        if not isinstance(keys, tuple):
                            keys = (keys,)
                        series_name = " / ".join(str(k) for k in keys)
                        values = [
                            round(grp[col].agg(method), 2) if pd.api.types.is_numeric_dtype(grp[col]) else 0
                            for col in radar_indicators
                        ]
                        series_data.append({"name": series_name, "value": values})
                else:
                    # No valid group columns: single series
                    values = [
                        round(df[col].agg(method), 2) for col in radar_indicators
                    ]
                    series_data.append({"name": "Overall", "value": values})
            else:
                # No grouping: single series
                values = [
                    round(df[col].agg(method), 2) for col in radar_indicators
                ]
                series_data.append({"name": "Overall", "value": values})

            return {
                "indicators": indicators,
                "series_data": series_data,
                "group_by": group_by
            }

        # -------------------------------------------------------
        # FALLBACK: If we can't determine a radar pattern,
        # fall back to standard chart processing
        # -------------------------------------------------------
        pandas_worker_logger.warning(
            "Radar: could not determine radar pattern, falling back to standard processing."
        )
        return self.process_chart_config(df, config, chart_type=chart_type)


    # --------------------------------------------------
    # Binning (for histograms)
    # --------------------------------------------------
    def apply_binning(self, df, column, binning_spec):
        """
        Bin a numeric column into equal-width intervals.
        binning_spec is expected to be a string like "bins:10".
        Returns a DataFrame with two columns: the bin-label column
        and a 'count' column.
        """
        if not binning_spec or not isinstance(binning_spec, str):
            pandas_worker_logger.warning(f"apply_binning: invalid binning_spec={binning_spec!r}. Skipping binning.")
            return None

        # Normalise LLM quirks
        spec = binning_spec.strip().lower()
        if spec in ("null", "none", ""):
            pandas_worker_logger.info(f"apply_binning: binning_spec={binning_spec!r} treated as no-binning. Skipping binning.")
            return None

        # Parse "bins:N"
        match = re.match(r"bins\s*:\s*(\d+)", spec)
        if not match:
            pandas_worker_logger.warning(f"apply_binning: binning_spec={binning_spec!r} does not match expected format 'bins:N'. Skipping binning.")
            return None

        n_bins = int(match.group(1))
        if n_bins <= 0:
            pandas_worker_logger.warning(f"apply_binning: non-positive number of bins ({n_bins}) specified. Skipping binning.")
            return None

        if column not in df.columns:
            pandas_worker_logger.warning(f"apply_binning: column '{column}' not found. Skipping.")
            return None

        if not pd.api.types.is_numeric_dtype(df[column]):
            pandas_worker_logger.warning(f"apply_binning: column '{column}' is not numeric. Skipping.")
            return None

        col_data = df[column].dropna()
        if col_data.empty:
            pandas_worker_logger.warning(f"apply_binning: column '{column}' has no valid numeric data after dropping NA. Skipping.")
            return None

        # Create equal-width bins
        binned = pd.cut(col_data, bins=n_bins, include_lowest=True)
        counts = binned.value_counts().sort_index()

        # Build a clean DataFrame with string labels like "18-25"
        labels = []
        values = []
        for interval, count in counts.items():
            left = int(interval.left) if interval.left == int(interval.left) else round(interval.left, 1)
            right = int(interval.right) if interval.right == int(interval.right) else round(interval.right, 1)
            labels.append(f"{left}-{right}")
            values.append(int(count))

        return pd.DataFrame({column: labels, "count": values})
   
    # Binning for general use (not just histograms) - adds a new column with binned categories
    def apply_binning_to_columns(self, df, column, binning_spec):
        if not binning_spec or not isinstance(binning_spec, str):
            return df

        # Normalise LLM quirks
        spec = binning_spec.strip().lower()
        if spec in ("null", "none", ""):
            return df

        # Parse "bins:N"
        match = re.match(r"bins\s*:\s*(\d+)", spec)
        if not match:
            return df

        n_bins = int(match.group(1))
        if n_bins <= 0:
            return df

        if column not in df.columns:
            pandas_worker_logger.warning(f"apply_binning: column '{column}' not found. Skipping.")
            return df

        if not pd.api.types.is_numeric_dtype(df[column]):
            pandas_worker_logger.warning(f"apply_binning: column '{column}' is not numeric. Skipping.")
            return df

        col_data = df[column].dropna()
        if col_data.empty:
            pandas_worker_logger.warning(f"apply_binning: column '{column}' has no valid numeric data after dropping NA. Skipping.")
            return df

        # Create equal-width bins
        binned = pd.cut(col_data, bins=n_bins, include_lowest=True)
        # df = df.copy()
        df[f"{column}_binned"] = binned.astype(str)
        return df
    
    # Generic transformation helpers

    def apply_filtering(self, df, expr):
        if expr:
            try:
                return df.query(expr, engine='python')
            except Exception as e:
                pandas_worker_logger.warning(f"apply_filtering failed for expr={expr!r}: {e}")
                return df
        return df

    def apply_missing_value_handling(self, df, column, strategy):
        if not strategy:
            return df

        if strategy == "drop":
            df = df.dropna(subset=[column])

        elif strategy == "fill_mean":
            if pd.api.types.is_numeric_dtype(df[column]):
                df[column] = df[column].fillna(df[column].mean())

        elif strategy == "fill_median":
            if pd.api.types.is_numeric_dtype(df[column]):
                df[column] = df[column].fillna(df[column].median())

        elif strategy == "fill_zero":
            df[column] = df[column].fillna(0)

        return df

    def apply_outlier_filtering(self, df, column, method):
        if not method:
            return df

        if not pd.api.types.is_numeric_dtype(df[column]):
            return df

        if method == "iqr":
            q1 = df[column].quantile(0.25)
            q3 = df[column].quantile(0.75)
            iqr = q3 - q1

            lower = q1 - 1.5 * iqr
            upper = q3 + 1.5 * iqr

            df = df[
                (df[column] >= lower)
                & (df[column] <= upper)
            ]

        elif method == "z_score_3":
            mean = df[column].mean()
            std = df[column].std()

            z = (df[column] - mean) / std

            df = df[np.abs(z) <= 3]

        return df

    def apply_sorting(self, df, column, sorting):
        # Normalise LLM quirks: treat string "null"/"none" as no-sort
        if isinstance(sorting, str) and sorting.lower() in ("null", "none", ""):
            sorting = None

        if column not in df.columns:
            pandas_worker_logger.warning(f"apply_sorting: column '{column}' not found in DataFrame. Skipping sort.")
            return df

        # Always enforce ordinal order for ordinal columns (months, days, quarters, age bands)
        ordinal_order = _detect_ordinal_order(df[column])

        if ordinal_order is not None:
            # Reverse only if explicitly DESC; otherwise default to natural order
            if sorting == "DESC":
                ordinal_order = list(reversed(ordinal_order))
            df[column] = pd.Categorical(
                df[column], categories=ordinal_order, ordered=True
            )
            return df.sort_values(column, ascending=True).reset_index(drop=True)

        # For non-ordinal columns, only sort if an explicit direction was given
        if sorting == "ASC":
            try:
                return df.sort_values(column, ascending=True)
            except TypeError:
                pandas_worker_logger.warning(f"apply_sorting: mixed types in '{column}', falling back to string sort")
                return df.sort_values(column, ascending=True, key=lambda col: col.astype(str))
        elif sorting == "DESC":
            try:
                return df.sort_values(column, ascending=False)
            except TypeError:
                pandas_worker_logger.warning(f"apply_sorting: mixed types in '{column}', falling back to string sort")
                return df.sort_values(column, ascending=False, key=lambda col: col.astype(str))

        return df
    
    '''def process_y_axis(self, df, y_config):
        pass
    def process_x_axis(self, df, x_config):
        pass
    def process_chart_config(self, df, config):
        encodings = config.get("encodings", {})
        group_by = encodings.get("granularity", {}).get("group_by", [])

        y_config = encodings.get("y_axis OR value", {})
        col = y_config.get("column")
        agg = y_config.get("aggregation")

        # 1. Grouping + Aggregation
        if group_by and agg:
            agg_map = {
                "SUM": "sum",
                "AVERAGE": "mean",
                "MAX": "max",
                "MIN": "min",
                "COUNT": "count",
                "MEDIAN": "median",
                "STD": "std",
                "VAR": "var"
            }

            method = agg_map.get(agg, "sum")

            processed = (
                df.groupby(group_by, as_index=False)[col]
                .agg(method)
            )

        elif group_by:
            # Return unique grouped rows as DataFrame
            processed = df[group_by].drop_duplicates().reset_index(drop=True)

        else:
            # No grouping
            processed = df.copy()

        # 2. Sorting
        x_config = encodings.get("x_axis OR name", {})
        x_trans = x_config.get("transformation", {}) or {}
        x_sorting = x_trans.get("sorting")

        x_col = x_config.get("column")

        if x_col and x_col in processed.columns:
            if x_sorting == "DESC":
                processed = processed.sort_values(by=x_col, ascending=False)

            elif x_sorting == "ASC":
                processed = processed.sort_values(by=x_col, ascending=True)

        return processed'''
    # ----------------------------------------------------
    # Combined pre-aggregation transformations
    # ----------------------------------------------------
    def apply_pre_aggregation(self, df, x_config, y_config):
        """
        Apply filtering and missing-value handling from both
        x and y configs in a single pass to avoid conflicts.
        """
        x_trans = x_config.get("transformation", {}) or {}
        y_trans = y_config.get("transformation", {}) or {}

        x_col = x_config.get("column")
        y_col = y_config.get("column")

        # --- combined filtering (deduplicated, joined with 'and') ---
        filters = []
        x_filter = x_trans.get("filtering")
        y_filter = y_trans.get("filtering")

        if x_filter and isinstance(x_filter, str) and x_filter not in ["null", "None", ""]:
            filters.append(f"({x_filter})")
        if y_filter and y_filter != x_filter and isinstance(y_filter, str) and y_filter not in ["null", "None", ""]:
            filters.append(f"({y_filter})")

        if filters:
            combined_expr = " and ".join(filters)
            df = self.apply_filtering(df, combined_expr)

        # --- missing-value handling (per column) ---
        df = self.apply_missing_value_handling(
            df, x_col, x_trans.get("missing_value_handling")
        )
        df = self.apply_missing_value_handling(
            df, y_col, y_trans.get("missing_value_handling")
        )

        return df

    # ----------------------------------------------------
    # Post aggregation transformations
    # ----------------------------------------------------
    def apply_post_aggregation(
        self,
        df,
        y_col,
        transformations
    ):

        # cumulative sum
        # if transformations.get("cumulative_sum") == "true":
        #     df[y_col] = df[y_col].cumsum()

        # rolling average
        # rolling = transformations.get("rolling_average")
        # if rolling:
        #     window = int(rolling.split(":")[1])

        #     df[y_col] = (
        #         df[y_col]
        #         .rolling(window=window, min_periods=1)
        #         .mean()
        #     )

        # moving average
        # moving = transformations.get("moving_average")
        # if moving:
        #     window = int(moving.split(":")[1])

        #     df[y_col] = (
        #         df[y_col]
        #         .rolling(window=window, min_periods=1)
        #         .mean()
        #     )

        # percentage contribution
        # if transformations.get("percentage_contribution") == "true":
        #     total = df[y_col].sum()

        #     if total != 0:
        #         df[y_col] = (
        #             df[y_col] / total
        #         ) * 100

        # normalization
        normalization = transformations.get("normalization")

        if normalization == "min_max":
            min_val = df[y_col].min()
            max_val = df[y_col].max()

            if max_val != min_val:
                df[y_col] = (
                    (df[y_col] - min_val)
                    / (max_val - min_val)
                )

        elif normalization == "z_score":
            mean = df[y_col].mean()
            std = df[y_col].std()

            if std != 0:
                df[y_col] = (
                    (df[y_col] - mean)
                    / std
                )

        return df
    
    # ----------------------------------------------------
    # Main execution
    # ----------------------------------------------------
    def process_chart_config(self, df, config, chart_type=None):

        encodings = config.get("encodings") or {}

        x_config = encodings.get(
            "x_axis OR name"
        ) or {}

        y_config = encodings.get(
            "y_axis OR value"
        ) or {}

        group_by = (
            encodings
            .get("granularity") or {}
        ).get("group_by", [])

        if not group_by or str(group_by).lower() in ("null", "none"):
            group_by = []
        elif isinstance(group_by, str):
            group_by = [group_by]
        # ------------------------------------
        # PRE AGGREGATION TRANSFORMATIONS
        # ------------------------------------

        df = self.apply_pre_aggregation(df, x_config, y_config)

        x_col = x_config.get("column")
        y_col = y_config.get("column")
        agg = y_config.get("aggregation")

        # ------------------------------------
        # BINNING
        # ------------------------------------
        x_binning = (x_config.get("transformation") or {}).get("binning")

        is_histogram = (
            isinstance(chart_type, str)
            and "histogram" in chart_type.lower()
        )

        '''if isinstance(x_binning, str) and x_binning.strip().lower() not in ("null", "none", ""):
            if is_histogram:
                return self.apply_binning(df, x_col, x_binning)

            df = self.apply_binning_to_columns(df, x_col, x_binning)
            original_x_col = x_col

            x_col = f"{x_col}_binned" if f"{x_col}_binned" in df.columns else x_col

            group_by = [
                x_col if col == original_x_col else col
                for col in group_by
            ]'''

        original_x_col = x_col

        if isinstance(x_binning, str) and x_binning.strip().lower() not in ("null", "none", ""):
            if is_histogram:
                if is_histogram:
                    binned_df = self.apply_binning(df, x_col, x_binning)

                    if binned_df is None:
                        binned_df = df.copy()
                        binned_df["count"] = 1

                    return binned_df, x_col, group_by
                # return self.apply_binning(df, x_col, x_binning), x_col, group_by

            df2 = self.apply_binning_to_columns(df, x_col, x_binning)

            # only accept change if column actually exists
            new_col = f"{x_col}_binned"

            if new_col in df2.columns:
                df = df2
                x_col = new_col

                group_by = [
                    x_col if col == original_x_col else col
                    for col in group_by
                ]
                
        group_by = [
            c for c in group_by
            if c in df.columns
        ]
        # ------------------------------------
        # GROUPING
        # ------------------------------------
            
        # =========================================================
        # TOOLTIP, SIZE, AND COLOR COLUMNS AGGREGATION
        # =========================================================
        # To display extra attributes in tooltips, size bubbles,
        # or color series, we must aggregate these columns alongside
        # our primary y-axis column. Otherwise, they would be dropped
        # during the groupby phase.
        # =========================================================
        if group_by and isinstance(agg, str) and agg.lower() != "null":
            method = agg_map[agg]
            
            # Identify tooltip columns from config that need aggregation
            tooltip_cols = []
            tooltip_enc = encodings.get("tooltip", [])
            if isinstance(tooltip_enc, list):
                for t in tooltip_enc:
                    col = t.get("column") if isinstance(t, dict) else t
                    if col and isinstance(col, str) and col.lower() not in ("null", "none", ""):
                        if col not in group_by and col != x_col and col in df.columns:
                            tooltip_cols.append(col)

            # Identify size and color columns from config that need aggregation
            extra_cols = []
            for role in ("size", "symbolSize", "color", "series"):
                role_enc = encodings.get(role, {})
                if isinstance(role_enc, dict):
                    col = role_enc.get("column")
                    if col and isinstance(col, str) and col.lower() not in ("null", "none", ""):
                        if col not in group_by and col != x_col and col in df.columns:
                            extra_cols.append(col)

            # Build aggregation dictionary for all columns
            agg_dict = {y_col: method}
            
            # Combine tooltip and extra columns
            all_cols_to_agg = list(dict.fromkeys(tooltip_cols + extra_cols))
            for col in all_cols_to_agg:
                if col not in agg_dict:
                    # Use same numeric aggregation method for numeric columns,
                    # fallback to 'first' for non-numeric columns.
                    if pd.api.types.is_numeric_dtype(df[col]):
                        agg_dict[col] = method
                    else:
                        agg_dict[col] = 'first'

            # Run the groupby aggregation on all requested columns
            processed = (
                df.groupby(
                    group_by,
                    as_index=False,
                    observed=True,
                    sort=False
                )
                .agg(agg_dict)
            )
        # =========================================================
        # END OF TOOLTIP COLUMNS AGGREGATION
        # =========================================================
        elif agg and (agg != 'null') and type(agg)==list:
            # type(agg) == list is always for boxplot for this version, which requires q1, q3, median, min, max
            methods = [agg_map[a] for a in agg]
            expected_stat_cols = ['min', 'q1', 'median', 'q3', 'max']
            if not group_by:
                # If there's no grouping, aggregate the entire column into a single row
                processed = pd.DataFrame({
                    "Group": ["All"],
                    y_col: [[
                        df[y_col].min(),
                        df[y_col].quantile(.25),
                        df[y_col].median(),
                        df[y_col].quantile(.75),
                        df[y_col].max()
                    ]]
                })
            else:
                try:
                    # Use as_index=True + reset_index to avoid MultiIndex column issues
                    processed = (
                        df.groupby(
                            group_by,
                            observed=True,
                            sort=False
                        )[y_col]
                        .agg(methods)
                        .reset_index()
                    )

                    # Flatten MultiIndex columns if present
                    if isinstance(processed.columns, pd.MultiIndex):
                        processed.columns = [
                            col[-1] if col[-1] != '' else col[0]
                            for col in processed.columns
                        ]

                    pandas_worker_logger.info(f"Boxplot agg columns after groupby: {processed.columns.tolist()}")

                    # Check if expected stats columns exist
                    if all(c in processed.columns for c in expected_stat_cols):
                        processed[y_col] = processed[expected_stat_cols].values.tolist()
                        processed = processed.drop(columns=expected_stat_cols)
                    else:
                        # Fallback: manually compute stats per group
                        pandas_worker_logger.warning(
                            f"Expected boxplot columns {expected_stat_cols} not found in "
                            f"{processed.columns.tolist()}. Falling back to manual computation."
                        )
                        stats_rows = []
                        for keys, grp in df.groupby(group_by, observed=True, sort=False):
                            if not isinstance(keys, tuple):
                                keys = (keys,)
                            row = dict(zip(group_by, keys))
                            row[y_col] = [
                                grp[y_col].min(),
                                grp[y_col].quantile(0.25),
                                grp[y_col].median(),
                                grp[y_col].quantile(0.75),
                                grp[y_col].max(),
                            ]
                            stats_rows.append(row)
                        processed = pd.DataFrame(stats_rows)
                except Exception as e:
                    pandas_worker_logger.error(f"Boxplot grouped aggregation failed: {e}. Falling back to manual computation.")
                    stats_rows = []
                    for keys, grp in df.groupby(group_by, observed=True, sort=False):
                        if not isinstance(keys, tuple):
                            keys = (keys,)
                        row = dict(zip(group_by, keys))
                        row[y_col] = [
                            grp[y_col].min(),
                            grp[y_col].quantile(0.25),
                            grp[y_col].median(),
                            grp[y_col].quantile(0.75),
                            grp[y_col].max(),
                        ]
                        stats_rows.append(row)
                    processed = pd.DataFrame(stats_rows)

            return processed, x_col, group_by

        else:
            processed = df.copy()

        # ------------------------------------
        # POST AGGREGATION
        # ------------------------------------

        processed = self.apply_post_aggregation(
            processed,
            y_col,
            y_config.get("transformation") or {}
        )
        processed.to_csv("outputs/"+str(x_config.get("column"))+ "_"+str(y_config.get("column"))+ ".csv", index=False)

        # ------------------------------------
        # SORTING
        # ------------------------------------

        # x_col = x_config.get("column")

        processed = self.apply_sorting(
            processed,
            x_col,
            (x_config.get("transformation") or {}).get("sorting")
        )

        # ------------------------------------
        # TOP N
        # ------------------------------------

        # --- TEMPORARY FIX: Sort by y_col descending before applying top_n ---
        top_n = (x_config.get("transformation") or {}).get("top_n") or (
            (y_config.get("transformation") or {}).get("top_n")
        )
        if top_n and str(top_n).lower() not in ("null", "none", "") and str(top_n).isdigit():
            if y_col and y_col in processed.columns:
                try:
                    processed = processed.sort_values(by=y_col, ascending=False)
                except TypeError:
                    pandas_worker_logger.warning(f"top_n: mixed types in '{y_col}', falling back to string sort")
                    processed = processed.sort_values(by=y_col, ascending=False, key=lambda col: col.astype(str))
            processed = processed.head(int(top_n))
        # --- END TEMPORARY FIX ---

        return processed, x_col, group_by
if __name__ == "__main__":
    df = pd.read_csv("CSVs/test_retail_dataset.csv")
    worker = PandasWorker(df)
    metadata = worker.metadata_retrieval()
    print(json.dumps(metadata, indent=4))
    config = json.loads(r'''{
            "chart_type": "horizontal_bar_chart",
            "query": "Calculate the total revenue for each product category.\n\nIdentify which product category generates the highest revenue.",
            "encodings": {
                "x_axis OR name": {
                    "column": "Product Category",
                    "aggregation": null,
                    "transformation": {
                        "sorting": "DESC",
                        "filtering": null,
                        "top_n": null,
                        "binning": null,
                        "normalization": null,
                        "percentage_contribution": "false",
                        "rolling_average": null,
                        "moving_average": null,
                        "cumulative_sum": "false",
                        "window_calculations": null,
                        "outlier_filtering": null,
                        "missing_value_handling": null
                    }
                },
                "y_axis OR value": {
                    "column": "Total Amount",
                    "aggregation": "SUM",
                    "transformation": {
                        "sorting": null,
                        "filtering": null,
                        "top_n": null,
                        "binning": null,
                        "normalization": null,
                        "percentage_contribution": "false",
                        "rolling_average": null,
                        "moving_average": null,
                        "cumulative_sum": "false",
                        "window_calculations": null,
                        "outlier_filtering": null,
                        "missing_value_handling": null
                    }
                },
                "tooltip": [
                    {
                        "column": "Product Category"
                    },
                    {
                        "column": "Total Amount"
                    }
                ],
                "granularity": {
                    "group_by": [
                        "Product Category"
                    ],
                    "analytical_grain": "category"
                }
            }
        }''')
    processed_data = worker.process_chart_config(df, config)
    print(processed_data)