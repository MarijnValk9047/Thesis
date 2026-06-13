from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

try:
    from xgboost import XGBRegressor
    XGBOOST_AVAILABLE = True
except Exception:
    XGBRegressor = None
    XGBOOST_AVAILABLE = False

try:
    from statsmodels.tsa.statespace.sarimax import SARIMAX
    STATSMODELS_AVAILABLE = True
except Exception:
    SARIMAX = None
    STATSMODELS_AVAILABLE = False


PROJECT_ROOT = Path(__file__).resolve().parents[4]
ROOT = PROJECT_ROOT / 'data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity'
FEATURES_PATH = ROOT / 'nl_ir_capacity_features_exogenous_small_da_aligned_daily_direction.csv'
NAIVE_PATH = ROOT / 'nl_ir_capacity_forecast_naive7d_da_aligned_daily_direction_long.csv'
LEAR_PATH = ROOT / 'nl_ir_capacity_forecast_lear_da_aligned_daily_direction_long.csv'
XGB_ENDOG_PATH = ROOT / 'nl_ir_capacity_forecast_xgboost_da_aligned_daily_direction_long.csv'
LEAR_EXOG_PATH = ROOT / 'nl_ir_capacity_forecast_lear_exogenous_small_da_aligned_daily_direction_long.csv'
XGB_EXOG_OUTPUT_PATH = ROOT / 'nl_ir_capacity_forecast_xgboost_exogenous_small_da_aligned_daily_direction_long.csv'
ARIMAX_OUTPUT_PATH = ROOT / 'nl_ir_capacity_forecast_arimax_load_da_aligned_daily_direction_long.csv'

TARGET_NAME = 'average_procurement_price'
TRAIN_START = pd.Timestamp('2022-01-01')
TRAIN_END = pd.Timestamp('2023-09-30')
VALIDATION_START = pd.Timestamp('2023-10-01')
VALIDATION_END = pd.Timestamp('2024-09-30')
TEST_START = pd.Timestamp('2024-10-01')
TEST_END = pd.Timestamp('2025-09-30')
FORBIDDEN_TOKENS = [
    'procured_mw',
    'procured_capacity',
    '12_3_f',
    'threshold_price',
    'max_accepted_price',
    'activation',
    'same_day_da_price',
    'da_forecast_summary',
    'day_ahead_load_forecast',
    'generation_forecast',
    'wind_forecast',
    'solar_forecast',
    'residual_load',
    'actual_load',
    'actual_generation',
]
APPROVED_EXOGENOUS_COLUMNS = [
    'nl_da_price_daily_avg_lag_1d',
    'nl_da_price_daily_avg_lag_7d',
    'nl_week_ahead_load_daily_mean',
    'nl_week_ahead_load_daily_peak',
]
ARIMAX_EXOG_COLUMNS = [
    'nl_week_ahead_load_daily_mean',
    'nl_week_ahead_load_daily_peak',
]
ENDOGENOUS_EXCLUDED_COLUMNS = {
    'forecast_origin_utc',
    'forecast_origin_local',
    'known_at_cutoff_utc',
    'delivery_date_local',
    'delivery_start_utc',
    'delivery_end_utc',
    'delivery_block_id',
    'direction',
    'average_procurement_price',
    'average_procurement_price_unit',
    'granularity',
    'market_design_regime',
    'source_dataset',
    'source_data_version',
    'quality_flags',
    'known_at_assumption',
    'dataset_split',
    'target_average_procurement_price',
    'exogenous_feature_source',
    'exogenous_known_at_rule',
    'exogenous_quality_flags',
}
COMMON_OUTPUT_COLUMNS = [
    'forecast_origin_utc',
    'forecast_origin_local',
    'known_at_cutoff_utc',
    'delivery_start_utc',
    'delivery_end_utc',
    'delivery_date_local',
    'delivery_block_id',
    'direction',
    'model_name',
    'target_name',
    'y_true',
    'point_forecast',
    'average_procurement_price_unit',
    'dataset_split',
    'granularity',
    'market_design_regime',
    'source_data_version',
    'quality_flags',
    'feature_source',
    'forecast_quality_flags',
    'fit_runtime_seconds',
    'predict_runtime_seconds',
    'total_runtime_seconds',
    'n_predictors',
    'model_config_summary',
    'selected_model_type',
    'selected_hyperparameters',
    'selected_order',
]
XGB_CONFIGS = [
    {
        'n_estimators': 100,
        'max_depth': 2,
        'learning_rate': 0.05,
        'subsample': 0.9,
        'colsample_bytree': 0.9,
        'reg_lambda': 1.0,
        'objective': 'reg:squarederror',
        'random_state': 42,
    },
    {
        'n_estimators': 200,
        'max_depth': 2,
        'learning_rate': 0.05,
        'subsample': 0.9,
        'colsample_bytree': 0.9,
        'reg_lambda': 2.0,
        'objective': 'reg:squarederror',
        'random_state': 42,
    },
    {
        'n_estimators': 200,
        'max_depth': 2,
        'learning_rate': 0.1,
        'min_child_weight': 1,
        'subsample': 0.9,
        'colsample_bytree': 0.9,
        'reg_lambda': 2.0,
        'objective': 'reg:squarederror',
        'random_state': 42,
    },
]
HGB_CONFIGS = [
    {'max_depth': 2, 'learning_rate': 0.05, 'max_iter': 100, 'min_samples_leaf': 20},
    {'max_depth': 2, 'learning_rate': 0.05, 'max_iter': 200, 'min_samples_leaf': 20},
    {'max_depth': 2, 'learning_rate': 0.1, 'max_iter': 200, 'min_samples_leaf': 20},
]
ARIMAX_ORDER_CANDIDATES = [(1, 0, 0), (1, 0, 1), (2, 0, 0)]


def load_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    if 'delivery_date_local' in df.columns:
        df['delivery_date_local'] = pd.to_datetime(df['delivery_date_local'])
    return df


def get_endogenous_predictors(df: pd.DataFrame) -> list[str]:
    predictors: list[str] = []
    excluded = ENDOGENOUS_EXCLUDED_COLUMNS | set(APPROVED_EXOGENOUS_COLUMNS)
    for column in df.columns:
        if column in excluded:
            continue
        lower = column.lower()
        if any(token in lower for token in FORBIDDEN_TOKENS):
            continue
        predictors.append(column)
    return predictors


def get_xgb_exogenous_predictors(df: pd.DataFrame) -> list[str]:
    endogenous = get_endogenous_predictors(df)
    for col in APPROVED_EXOGENOUS_COLUMNS:
        if col not in df.columns:
            raise ValueError(f'Missing approved exogenous column: {col}')
    return endogenous + APPROVED_EXOGENOUS_COLUMNS


def build_complete_case_mask(df: pd.DataFrame, predictors: list[str]) -> pd.Series:
    return ~df[predictors].isna().any(axis=1)


def build_preprocessor() -> ColumnTransformer:
    return ColumnTransformer(
        transformers=[
            (
                'numeric',
                Pipeline([
                    ('imputer', SimpleImputer(strategy='median')),
                    ('scaler', StandardScaler()),
                ]),
                slice(0, None),
            )
        ],
        remainder='drop',
        verbose_feature_names_out=False,
    )


def mae(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.mean(np.abs(y_true - y_pred)))


def build_base_output(df: pd.DataFrame, model_name: str, feature_source: str) -> pd.DataFrame:
    return pd.DataFrame({
        'forecast_origin_utc': df['forecast_origin_utc'],
        'forecast_origin_local': df['forecast_origin_local'],
        'known_at_cutoff_utc': df['known_at_cutoff_utc'],
        'delivery_start_utc': df['delivery_start_utc'],
        'delivery_end_utc': df['delivery_end_utc'],
        'delivery_date_local': pd.to_datetime(df['delivery_date_local']).dt.strftime('%Y-%m-%d'),
        'delivery_block_id': df['delivery_block_id'],
        'direction': df['direction'],
        'model_name': model_name,
        'target_name': TARGET_NAME,
        'y_true': df['target_average_procurement_price'],
        'point_forecast': np.nan,
        'average_procurement_price_unit': df['average_procurement_price_unit'],
        'dataset_split': df['dataset_split'],
        'granularity': df['granularity'],
        'market_design_regime': df['market_design_regime'],
        'source_data_version': df['source_data_version'],
        'quality_flags': df['quality_flags'],
        'feature_source': feature_source,
        'forecast_quality_flags': 'ok',
        'fit_runtime_seconds': 0.0,
        'predict_runtime_seconds': 0.0,
        'total_runtime_seconds': 0.0,
        'n_predictors': 0,
        'model_config_summary': '',
        'selected_model_type': pd.NA,
        'selected_hyperparameters': pd.NA,
        'selected_order': pd.NA,
    })


def classify_missing_flag(date_value: pd.Timestamp, has_missing: bool) -> str:
    if not has_missing:
        return 'ok'
    if int((pd.Timestamp(date_value) - TRAIN_START).days) <= 6:
        return 'missing_due_to_lag_warmup'
    return 'excluded_due_to_missing_predictors'


def fit_xgb_like_model(train_df: pd.DataFrame, validation_df: pd.DataFrame, predictors: list[str]) -> tuple[Pipeline, dict[str, Any], float]:
    x_train = train_df[predictors]
    y_train = train_df['target_average_procurement_price'].to_numpy(dtype=float)
    x_val = validation_df[predictors]
    y_val = validation_df['target_average_procurement_price'].to_numpy(dtype=float)
    total_fit = 0.0
    candidates: list[dict[str, Any]] = []

    if XGBOOST_AVAILABLE:
        for config in XGB_CONFIGS:
            model = XGBRegressor(n_jobs=1, **config)
            pipe = Pipeline([
                ('preprocess', build_preprocessor()),
                ('model', model),
            ])
            start = time.monotonic()
            pipe.fit(x_train, y_train)
            total_fit += time.monotonic() - start
            pred = pipe.predict(x_val)
            candidates.append({
                'pipeline': pipe,
                'selected_model_type': 'xgboost',
                'selected_hyperparameters': config,
                'validation_mae': mae(y_val, pred),
            })
    else:
        for config in HGB_CONFIGS:
            model = HistGradientBoostingRegressor(loss='squared_error', random_state=42, **config)
            pipe = Pipeline([
                ('preprocess', build_preprocessor()),
                ('model', model),
            ])
            start = time.monotonic()
            pipe.fit(x_train, y_train)
            total_fit += time.monotonic() - start
            pred = pipe.predict(x_val)
            candidates.append({
                'pipeline': pipe,
                'selected_model_type': 'hist_gradient_boosting_fallback',
                'selected_hyperparameters': config,
                'validation_mae': mae(y_val, pred),
            })
    if not candidates:
        raise ValueError('No XGBoost or fallback model candidates available.')
    best = min(candidates, key=lambda item: item['validation_mae'])
    return best['pipeline'], best, total_fit


def run_xgb_exogenous(df: pd.DataFrame, predictors: list[str]) -> tuple[pd.DataFrame, dict[str, Any]]:
    total_start = time.monotonic()
    out = build_base_output(df, 'xgboost_exogenous_small_da_aligned_daily_v1', 'endogenous_plus_small_exogenous_da_aligned_daily_v1')
    complete_mask = build_complete_case_mask(df, predictors)
    out['forecast_quality_flags'] = [
        classify_missing_flag(date_value, not is_complete)
        for date_value, is_complete in zip(df['delivery_date_local'], complete_mask)
    ]

    train_complete = df[(df['dataset_split'] == 'train') & complete_mask].copy()
    validation_complete = df[(df['dataset_split'] == 'validation') & complete_mask].copy()
    if train_complete.empty or validation_complete.empty:
        raise ValueError('Exogenous XGBoost: missing complete-case train or validation rows.')

    model, selected, fit_runtime = fit_xgb_like_model(train_complete, validation_complete, predictors)
    predict_start = time.monotonic()
    out.loc[complete_mask, 'point_forecast'] = model.predict(df.loc[complete_mask, predictors])
    predict_runtime = time.monotonic() - predict_start
    total_runtime = time.monotonic() - total_start

    out['fit_runtime_seconds'] = fit_runtime
    out['predict_runtime_seconds'] = predict_runtime
    out['total_runtime_seconds'] = total_runtime
    out['n_predictors'] = len(predictors)
    out['model_config_summary'] = 'validation_selected_three_config_exogenous_xgboost'
    out['selected_model_type'] = selected['selected_model_type']
    out['selected_hyperparameters'] = json.dumps(selected['selected_hyperparameters'], sort_keys=True)
    return out[COMMON_OUTPUT_COLUMNS], {
        'predictors': predictors,
        'selected_model_type': selected['selected_model_type'],
        'selected_hyperparameters': selected['selected_hyperparameters'],
    }


def fit_sarimax(train_y: pd.Series, train_exog: pd.DataFrame, order: tuple[int, int, int]):
    train_y = train_y.astype(float).copy()
    train_exog = train_exog.astype(float).copy()
    model = SARIMAX(
        train_y,
        exog=train_exog,
        order=order,
        trend='c',
        seasonal_order=(0, 0, 0, 0),
        enforce_stationarity=False,
        enforce_invertibility=False,
    )
    return model.fit(disp=False)


def append_result(results, actual_value: float, exog_row: pd.DataFrame):
    actual_series = pd.Series([actual_value], index=exog_row.index, dtype=float)
    if hasattr(results, 'append'):
        return results.append(endog=actual_series, exog=exog_row.astype(float), refit=False)
    if hasattr(results, 'extend'):
        return results.extend(endog=actual_series, exog=exog_row.astype(float))
    raise ValueError('SARIMAX results object does not support append/extend for recursive forecasting.')


def rolling_forecast(results, eval_df: pd.DataFrame, exog_cols: list[str]) -> tuple[list[float], Any]:
    predictions: list[float] = []
    current = results
    for _, row in eval_df.iterrows():
        row_index = pd.DatetimeIndex([pd.Timestamp(row['delivery_date_local'])])
        row_exog = pd.DataFrame([row[exog_cols].astype(float).to_dict()], index=row_index)
        forecast = current.forecast(steps=1, exog=row_exog)
        predictions.append(float(np.asarray(forecast)[0]))
        current = append_result(current, float(row['target_average_procurement_price']), row_exog)
    return predictions, current


def evaluate_arimax_order(df: pd.DataFrame, order: tuple[int, int, int], exog_cols: list[str]) -> tuple[float, float]:
    fit_runtime = 0.0
    maes: list[float] = []
    for direction in ['Down', 'Up']:
        dir_df = df[df['direction'] == direction].sort_values('delivery_date_local').copy()
        train_df = dir_df[dir_df['dataset_split'] == 'train'].copy()
        validation_df = dir_df[dir_df['dataset_split'] == 'validation'].copy()
        train_y = pd.Series(train_df['target_average_procurement_price'].astype(float).to_numpy(), index=pd.DatetimeIndex(train_df['delivery_date_local']))
        train_exog = train_df[exog_cols].astype(float).copy()
        train_exog.index = pd.DatetimeIndex(train_df['delivery_date_local'])
        start = time.monotonic()
        results = fit_sarimax(train_y, train_exog, order)
        fit_runtime += time.monotonic() - start
        val_pred, _ = rolling_forecast(results, validation_df, exog_cols)
        maes.append(mae(validation_df['target_average_procurement_price'].to_numpy(dtype=float), np.array(val_pred, dtype=float)))
    return float(np.mean(maes)), fit_runtime


def run_arimax(df: pd.DataFrame, exog_cols: list[str]) -> tuple[pd.DataFrame, dict[str, Any]]:
    if not STATSMODELS_AVAILABLE:
        raise ValueError('statsmodels is unavailable; stopping rather than implementing custom ARIMAX.')
    total_start = time.monotonic()
    out = build_base_output(df, 'arimax_load_da_aligned_daily_v1', 'week_ahead_load_only_da_aligned_daily_v1')
    complete_mask = build_complete_case_mask(df, exog_cols)
    out['forecast_quality_flags'] = [
        classify_missing_flag(date_value, not is_complete)
        for date_value, is_complete in zip(df['delivery_date_local'], complete_mask)
    ]

    val_test_missing = int(df[df['dataset_split'].isin(['validation', 'test'])][exog_cols].isna().any(axis=1).sum())
    if val_test_missing:
        raise ValueError('ARIMAX validation/test exogenous missingness present; stopping.')

    selection_fit_runtime = 0.0
    candidate_scores: list[dict[str, Any]] = []
    for order in ARIMAX_ORDER_CANDIDATES:
        val_mae, fit_time = evaluate_arimax_order(df[complete_mask].copy(), order, exog_cols)
        selection_fit_runtime += fit_time
        candidate_scores.append({'order': order, 'validation_mae': val_mae})
    selected = min(candidate_scores, key=lambda item: item['validation_mae'])
    selected_order = selected['order']

    predict_start = time.monotonic()
    final_fit_runtime = 0.0
    for direction in ['Down', 'Up']:
        dir_df = df[df['direction'] == direction].sort_values('delivery_date_local').copy()
        train_df = dir_df[(dir_df['dataset_split'] == 'train') & complete_mask.loc[dir_df.index]].copy()
        validation_df = dir_df[(dir_df['dataset_split'] == 'validation') & complete_mask.loc[dir_df.index]].copy()
        test_df = dir_df[(dir_df['dataset_split'] == 'test') & complete_mask.loc[dir_df.index]].copy()

        train_y = pd.Series(train_df['target_average_procurement_price'].astype(float).to_numpy(), index=pd.DatetimeIndex(train_df['delivery_date_local']))
        train_exog = train_df[exog_cols].astype(float).copy()
        train_exog.index = pd.DatetimeIndex(train_df['delivery_date_local'])
        start = time.monotonic()
        train_results = fit_sarimax(train_y, train_exog, selected_order)
        final_fit_runtime += time.monotonic() - start
        train_pred = np.asarray(train_results.fittedvalues, dtype=float)
        out.loc[train_df.index, 'point_forecast'] = train_pred

        val_pred, _ = rolling_forecast(train_results, validation_df, exog_cols)
        out.loc[validation_df.index, 'point_forecast'] = np.array(val_pred, dtype=float)

        train_val_df = pd.concat([train_df, validation_df], axis=0)
        train_val_y = pd.Series(train_val_df['target_average_procurement_price'].astype(float).to_numpy(), index=pd.DatetimeIndex(train_val_df['delivery_date_local']))
        train_val_exog = train_val_df[exog_cols].astype(float).copy()
        train_val_exog.index = pd.DatetimeIndex(train_val_df['delivery_date_local'])
        start = time.monotonic()
        test_results = fit_sarimax(train_val_y, train_val_exog, selected_order)
        final_fit_runtime += time.monotonic() - start
        test_pred, _ = rolling_forecast(test_results, test_df, exog_cols)
        out.loc[test_df.index, 'point_forecast'] = np.array(test_pred, dtype=float)

    predict_runtime = time.monotonic() - predict_start
    total_runtime = time.monotonic() - total_start

    out['fit_runtime_seconds'] = selection_fit_runtime + final_fit_runtime
    out['predict_runtime_seconds'] = predict_runtime
    out['total_runtime_seconds'] = total_runtime
    out['n_predictors'] = len(exog_cols)
    out['model_config_summary'] = 'directional_sarimax_train_validation_order_selection_recursive_forecasts'
    out['selected_model_type'] = 'sarimax'
    out['selected_order'] = str(selected_order)
    return out[COMMON_OUTPUT_COLUMNS], {
        'predictors': exog_cols,
        'selected_model_type': 'sarimax',
        'selected_order': selected_order,
        'candidate_scores': candidate_scores,
    }


def metric_record(df: pd.DataFrame, split: str, direction: str | None, iqr_value: float) -> dict[str, Any]:
    subset = df[df['dataset_split'] == split].copy()
    if direction is not None:
        subset = subset[subset['direction'] == direction].copy()
    total = int(len(subset))
    scored = subset[subset['point_forecast'].notna() & subset['y_true'].notna()].copy()
    missing = total - int(len(scored))
    if scored.empty:
        return {
            'count_total': total,
            'count_forecastable': 0,
            'count_missing_forecast': missing,
            'MAE': None,
            'RMSE': None,
            'bias': None,
            'median_absolute_error': None,
            'p90_absolute_error': None,
            'mae_div_target_iqr': None,
        }
    errors = scored['point_forecast'].astype(float) - scored['y_true'].astype(float)
    abs_errors = errors.abs()
    return {
        'count_total': total,
        'count_forecastable': int(len(scored)),
        'count_missing_forecast': missing,
        'MAE': float(abs_errors.mean()),
        'RMSE': math.sqrt(float(np.mean(np.square(errors)))),
        'bias': float(errors.mean()),
        'median_absolute_error': float(abs_errors.median()),
        'p90_absolute_error': float(abs_errors.quantile(0.9)),
        'mae_div_target_iqr': None if iqr_value == 0 else float(abs_errors.mean() / iqr_value),
    }


def compute_iqr_map(feature_df: pd.DataFrame) -> dict[tuple[str, str | None], float]:
    out: dict[tuple[str, str | None], float] = {}
    for split in ['train', 'validation', 'test']:
        vals = feature_df.loc[feature_df['dataset_split'] == split, 'target_average_procurement_price'].astype(float)
        out[(split, None)] = float(vals.quantile(0.75) - vals.quantile(0.25))
        for direction in ['Down', 'Up']:
            dvals = feature_df.loc[(feature_df['dataset_split'] == split) & (feature_df['direction'] == direction), 'target_average_procurement_price'].astype(float)
            out[(split, direction)] = float(dvals.quantile(0.75) - dvals.quantile(0.25))
    return out


def summarize_metrics(forecast_df: pd.DataFrame, feature_df: pd.DataFrame) -> dict[str, Any]:
    iqr_map = compute_iqr_map(feature_df)
    return {
        'by_split': {split: metric_record(forecast_df, split, None, iqr_map[(split, None)]) for split in ['train', 'validation', 'test']},
        'by_split_direction': {
            f'{split}|{direction}': metric_record(forecast_df, split, direction, iqr_map[(split, direction)])
            for split in ['train', 'validation', 'test'] for direction in ['Down', 'Up']
        },
    }


def compute_spike_report(feature_df: pd.DataFrame, forecasts: dict[str, pd.DataFrame]) -> dict[str, Any]:
    thresholds = (
        feature_df[feature_df['dataset_split'] == 'train']
        .groupby('direction')['target_average_procurement_price']
        .quantile(0.95)
        .to_dict()
    )
    truth = feature_df[['delivery_date_local', 'direction', 'dataset_split', 'target_average_procurement_price']].copy()
    truth['delivery_date_local'] = pd.to_datetime(truth['delivery_date_local'])
    truth['spike_bucket'] = truth.apply(
        lambda row: 'spike' if row['target_average_procurement_price'] >= thresholds[row['direction']] else 'non_spike',
        axis=1,
    )
    report: dict[str, Any] = {'thresholds': {k: float(v) for k, v in thresholds.items()}, 'metrics': {}}
    for model_name, df in forecasts.items():
        merged = df.merge(truth, on=['delivery_date_local', 'direction', 'dataset_split'], how='left')
        model_metrics: dict[str, Any] = {}
        for split in ['validation', 'test']:
            for direction in ['Down', 'Up']:
                for bucket in ['spike', 'non_spike']:
                    subset = merged[
                        (merged['dataset_split'] == split)
                        & (merged['direction'] == direction)
                        & (merged['spike_bucket'] == bucket)
                        & merged['point_forecast'].notna()
                    ].copy()
                    key = f'{split}|{direction}|{bucket}'
                    if subset.empty:
                        model_metrics[key] = {'count': 0, 'MAE': None}
                    else:
                        model_metrics[key] = {
                            'count': int(len(subset)),
                            'MAE': float((subset['point_forecast'].astype(float) - subset['y_true'].astype(float)).abs().mean()),
                        }
        report['metrics'][model_name] = model_metrics
    return report


def compare_mae(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, a_metrics in a.items():
        b_metrics = b[key]
        a_mae = a_metrics['MAE']
        b_mae = b_metrics['MAE']
        if a_mae is None or b_mae is None:
            out[key] = {'mae_diff': None, 'mae_pct_improvement': None}
        else:
            out[key] = {
                'mae_diff': float(a_mae - b_mae),
                'mae_pct_improvement': None if b_mae == 0 else float((b_mae - a_mae) / b_mae * 100.0),
            }
    return out


def validate_output(df: pd.DataFrame, feature_df: pd.DataFrame, expected_model_name: str, expected_feature_source: str, predictors: list[str], check_exog_val_test_complete: bool = False, arimax: bool = False) -> dict[str, Any]:
    issues: list[str] = []
    if len(df) != len(feature_df):
        issues.append('row_count_mismatch')
    dupes = int(df.duplicated(['delivery_date_local', 'direction', 'model_name']).sum())
    if dupes:
        issues.append('duplicate_keys')
    if sorted(df['model_name'].dropna().unique().tolist()) != [expected_model_name]:
        issues.append('unexpected_model_name')
    if sorted(df['feature_source'].dropna().unique().tolist()) != [expected_feature_source]:
        issues.append('unexpected_feature_source')
    if sorted(df['dataset_split'].dropna().unique().tolist()) != ['test', 'train', 'validation']:
        issues.append('unexpected_dataset_splits')
    if pd.to_datetime(df['delivery_date_local']).min() != TRAIN_START or pd.to_datetime(df['delivery_date_local']).max() != TEST_END:
        issues.append('unexpected_date_range')
    if (pd.to_datetime(df['delivery_date_local']) > TEST_END).any():
        issues.append('rows_after_test_end')
    if not np.allclose(df['y_true'].astype(float).to_numpy(), feature_df['target_average_procurement_price'].astype(float).to_numpy(), equal_nan=True):
        issues.append('y_true_mismatch')
    if any(any(token in c.lower() for token in FORBIDDEN_TOKENS) for c in df.columns):
        issues.append('forbidden_output_columns')
    if any(any(token in c.lower() for token in FORBIDDEN_TOKENS) for c in predictors):
        issues.append('forbidden_predictors_used')
    if (df[['fit_runtime_seconds', 'predict_runtime_seconds', 'total_runtime_seconds']] < 0).any().any():
        issues.append('negative_runtime')
    if check_exog_val_test_complete:
        missing = int(df[df['dataset_split'].isin(['validation', 'test'])]['point_forecast'].isna().sum())
        if missing:
            issues.append('validation_test_missing_forecasts')
    if arimax:
        if predictors != ARIMAX_EXOG_COLUMNS:
            issues.append('unexpected_arimax_predictor_list')
        if df['selected_order'].isna().any():
            issues.append('missing_selected_order')
    return {'issues': issues, 'row_count': int(len(df)), 'duplicate_key_count': dupes}


def run_and_write() -> dict[str, Any]:
    feature_df = load_csv(FEATURES_PATH)
    if not STATSMODELS_AVAILABLE:
        raise ValueError('statsmodels is unavailable; stopping before any leakage-prone workaround.')
    val_test_da_lag_missing = int(feature_df[feature_df['dataset_split'].isin(['validation', 'test'])][['nl_da_price_daily_avg_lag_1d', 'nl_da_price_daily_avg_lag_7d']].isna().any(axis=1).sum())
    if val_test_da_lag_missing:
        raise ValueError('Validation/test missingness appears in exogenous feature table; stopping.')

    xgb_predictors = get_xgb_exogenous_predictors(feature_df)
    arimax_predictors = ARIMAX_EXOG_COLUMNS.copy()

    xgb_df, xgb_meta = run_xgb_exogenous(feature_df, xgb_predictors)
    arimax_df, arimax_meta = run_arimax(feature_df, arimax_predictors)

    xgb_df.to_csv(XGB_EXOG_OUTPUT_PATH, index=False)
    arimax_df.to_csv(ARIMAX_OUTPUT_PATH, index=False)

    return {
        'xgb_meta': xgb_meta,
        'arimax_meta': arimax_meta,
        'xgb_validation': validate_output(xgb_df, feature_df, 'xgboost_exogenous_small_da_aligned_daily_v1', 'endogenous_plus_small_exogenous_da_aligned_daily_v1', xgb_predictors, check_exog_val_test_complete=True),
        'arimax_validation': validate_output(arimax_df, feature_df, 'arimax_load_da_aligned_daily_v1', 'week_ahead_load_only_da_aligned_daily_v1', arimax_predictors, check_exog_val_test_complete=True, arimax=True),
        'xgb_runtime_seconds': float(xgb_df['total_runtime_seconds'].iloc[0]),
        'arimax_runtime_seconds': float(arimax_df['total_runtime_seconds'].iloc[0]),
    }


def report_from_artifacts() -> dict[str, Any]:
    feature_df = load_csv(FEATURES_PATH)
    naive_df = load_csv(NAIVE_PATH)
    lear_df = load_csv(LEAR_PATH)
    xgb_endog_df = load_csv(XGB_ENDOG_PATH)
    lear_exog_df = load_csv(LEAR_EXOG_PATH)
    xgb_exog_df = load_csv(XGB_EXOG_OUTPUT_PATH)
    arimax_df = load_csv(ARIMAX_OUTPUT_PATH)

    metrics = {
        'naive7d': summarize_metrics(naive_df, feature_df),
        'endogenous_lear': summarize_metrics(lear_df, feature_df),
        'endogenous_xgboost': summarize_metrics(xgb_endog_df, feature_df),
        'exogenous_lear': summarize_metrics(lear_exog_df, feature_df),
        'exogenous_xgboost': summarize_metrics(xgb_exog_df, feature_df),
        'arimax_load': summarize_metrics(arimax_df, feature_df),
    }
    comparisons = {
        'exogenous_xgboost_vs_endogenous_xgboost': compare_mae(metrics['exogenous_xgboost']['by_split_direction'], metrics['endogenous_xgboost']['by_split_direction']),
        'arimax_load_vs_naive7d': compare_mae(metrics['arimax_load']['by_split_direction'], metrics['naive7d']['by_split_direction']),
    }
    spike_report = compute_spike_report(feature_df, {
        'naive7d': naive_df,
        'endogenous_lear': lear_df,
        'endogenous_xgboost': xgb_endog_df,
        'exogenous_lear': lear_exog_df,
        'exogenous_xgboost': xgb_exog_df,
        'arimax_load': arimax_df,
    })
    forecastable = {}
    for name, df in {
        'exogenous_xgboost': xgb_exog_df,
        'arimax_load': arimax_df,
    }.items():
        forecastable[name] = {
            split: {
                'count_total': int(len(df[df['dataset_split'] == split])),
                'count_forecastable': int(df[(df['dataset_split'] == split) & df['point_forecast'].notna()].shape[0]),
                'count_missing_forecast': int(df[(df['dataset_split'] == split) & df['point_forecast'].isna()].shape[0]),
            }
            for split in ['train', 'validation', 'test']
        }
    runtime_summary = {
        'naive7d_total_runtime_seconds': float(naive_df['total_runtime_seconds'].dropna().iloc[0]),
        'endogenous_lear_total_runtime_seconds': float(lear_df['total_runtime_seconds'].dropna().iloc[0]),
        'endogenous_xgboost_total_runtime_seconds': float(xgb_endog_df['total_runtime_seconds'].dropna().iloc[0]),
        'exogenous_lear_total_runtime_seconds': float(lear_exog_df['total_runtime_seconds'].dropna().iloc[0]),
        'exogenous_xgboost_total_runtime_seconds': float(xgb_exog_df['total_runtime_seconds'].dropna().iloc[0]),
        'arimax_load_total_runtime_seconds': float(arimax_df['total_runtime_seconds'].dropna().iloc[0]),
    }
    validations = {
        'xgb_exog': validate_output(xgb_exog_df, feature_df, 'xgboost_exogenous_small_da_aligned_daily_v1', 'endogenous_plus_small_exogenous_da_aligned_daily_v1', get_xgb_exogenous_predictors(feature_df), check_exog_val_test_complete=True),
        'arimax_load': validate_output(arimax_df, feature_df, 'arimax_load_da_aligned_daily_v1', 'week_ahead_load_only_da_aligned_daily_v1', ARIMAX_EXOG_COLUMNS.copy(), check_exog_val_test_complete=True, arimax=True),
    }
    return {
        'metrics': metrics,
        'comparisons': comparisons,
        'spike_report': spike_report,
        'forecastable': forecastable,
        'runtime_summary': runtime_summary,
        'validations': validations,
    }


def main() -> None:
    summary = run_and_write()
    print(json.dumps(summary, indent=2, default=str))


if __name__ == '__main__':
    main()
