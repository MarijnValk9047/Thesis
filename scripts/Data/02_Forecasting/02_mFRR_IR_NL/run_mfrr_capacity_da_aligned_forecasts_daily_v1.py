from __future__ import annotations

import json
import math
import time
import warnings
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.exceptions import ConvergenceWarning
from sklearn.impute import SimpleImputer
from sklearn.linear_model import ElasticNet, Lasso
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

try:
    from xgboost import XGBRegressor
    XGBOOST_AVAILABLE = True
except Exception:
    XGBRegressor = None
    XGBOOST_AVAILABLE = False


PROJECT_ROOT = Path(__file__).resolve().parents[4]
ROOT = PROJECT_ROOT / 'data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity'
ENDOGENOUS_FEATURES_PATH = ROOT / 'nl_ir_capacity_features_endogenous_da_aligned_daily_direction.csv'
EXOGENOUS_FEATURES_PATH = ROOT / 'nl_ir_capacity_features_exogenous_small_da_aligned_daily_direction.csv'
NAIVE_OUTPUT_PATH = ROOT / 'nl_ir_capacity_forecast_naive7d_da_aligned_daily_direction_long.csv'
LEAR_OUTPUT_PATH = ROOT / 'nl_ir_capacity_forecast_lear_da_aligned_daily_direction_long.csv'
XGB_OUTPUT_PATH = ROOT / 'nl_ir_capacity_forecast_xgboost_da_aligned_daily_direction_long.csv'
EXOG_LEAR_OUTPUT_PATH = ROOT / 'nl_ir_capacity_forecast_lear_exogenous_small_da_aligned_daily_direction_long.csv'

TARGET_NAME = 'average_procurement_price'
ALPHA_GRID = [0.0001, 0.001, 0.01, 0.1, 1.0]
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
    'selected_alpha',
    'selected_model_type',
    'selected_hyperparameters',
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
}
EXOGENOUS_METADATA_COLUMNS = {
    'exogenous_feature_source',
    'exogenous_known_at_rule',
    'exogenous_quality_flags',
}
APPROVED_EXOGENOUS_COLUMNS = [
    'nl_da_price_daily_avg_lag_1d',
    'nl_da_price_daily_avg_lag_7d',
    'nl_week_ahead_load_daily_mean',
    'nl_week_ahead_load_daily_peak',
]
XGB_CONFIGS = [
    {'n_estimators': 200, 'max_depth': 2, 'learning_rate': 0.1, 'min_child_weight': 1},
    {'n_estimators': 300, 'max_depth': 3, 'learning_rate': 0.05, 'min_child_weight': 1},
    {'n_estimators': 400, 'max_depth': 4, 'learning_rate': 0.03, 'min_child_weight': 2},
]
HGB_CONFIGS = [
    {'max_depth': 2, 'learning_rate': 0.1, 'max_iter': 200, 'min_samples_leaf': 20},
    {'max_depth': 3, 'learning_rate': 0.05, 'max_iter': 300, 'min_samples_leaf': 20},
    {'max_depth': 4, 'learning_rate': 0.03, 'max_iter': 400, 'min_samples_leaf': 30},
]


def load_features(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df['delivery_date_local'] = pd.to_datetime(df['delivery_date_local'])
    return df


def get_endogenous_predictors(df: pd.DataFrame) -> list[str]:
    predictors: list[str] = []
    excluded = ENDOGENOUS_EXCLUDED_COLUMNS | EXOGENOUS_METADATA_COLUMNS | set(APPROVED_EXOGENOUS_COLUMNS)
    for column in df.columns:
        if column in excluded:
            continue
        lower = column.lower()
        if any(token in lower for token in FORBIDDEN_TOKENS):
            continue
        predictors.append(column)
    return predictors


def get_exogenous_predictors(df: pd.DataFrame) -> list[str]:
    endogenous = get_endogenous_predictors(df)
    for column in APPROVED_EXOGENOUS_COLUMNS:
        if column not in df.columns:
            raise ValueError(f'Missing approved exogenous column: {column}')
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


def make_linear_pipeline(model_type: str, alpha: float) -> Pipeline:
    if model_type == 'lasso':
        model = Lasso(alpha=alpha, max_iter=20000)
    elif model_type == 'elasticnet':
        model = ElasticNet(alpha=alpha, l1_ratio=0.8, max_iter=20000)
    else:
        raise ValueError(f'Unsupported model_type: {model_type}')
    return Pipeline([
        ('preprocess', build_preprocessor()),
        ('model', model),
    ])


def mae(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.mean(np.abs(y_true - y_pred)))


def fit_linear_model(train_df: pd.DataFrame, validation_df: pd.DataFrame, predictors: list[str]) -> tuple[Pipeline, dict[str, Any], float]:
    x_train = train_df[predictors]
    y_train = train_df['target_average_procurement_price'].to_numpy(dtype=float)
    x_val = validation_df[predictors]
    y_val = validation_df['target_average_procurement_price'].to_numpy(dtype=float)
    total_fit_time = 0.0
    candidates: list[dict[str, Any]] = []

    for alpha in ALPHA_GRID:
        pipe = make_linear_pipeline('lasso', alpha)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always', ConvergenceWarning)
            start = time.monotonic()
            pipe.fit(x_train, y_train)
            elapsed = time.monotonic() - start
        total_fit_time += elapsed
        if any(issubclass(w.category, ConvergenceWarning) for w in caught):
            continue
        val_pred = pipe.predict(x_val)
        candidates.append({
            'pipeline': pipe,
            'selected_alpha': alpha,
            'selected_model_type': 'lasso',
            'validation_mae': mae(y_val, val_pred),
        })

    if not candidates:
        for alpha in ALPHA_GRID:
            pipe = make_linear_pipeline('elasticnet', alpha)
            start = time.monotonic()
            pipe.fit(x_train, y_train)
            elapsed = time.monotonic() - start
            total_fit_time += elapsed
            val_pred = pipe.predict(x_val)
            candidates.append({
                'pipeline': pipe,
                'selected_alpha': alpha,
                'selected_model_type': 'elasticnet',
                'validation_mae': mae(y_val, val_pred),
            })

    best = min(candidates, key=lambda item: item['validation_mae'])
    return best['pipeline'], best, total_fit_time


def fit_xgb_like_model(train_df: pd.DataFrame, validation_df: pd.DataFrame, predictors: list[str]) -> tuple[Pipeline, dict[str, Any], float]:
    x_train = train_df[predictors]
    y_train = train_df['target_average_procurement_price'].to_numpy(dtype=float)
    x_val = validation_df[predictors]
    y_val = validation_df['target_average_procurement_price'].to_numpy(dtype=float)
    total_fit_time = 0.0
    candidates: list[dict[str, Any]] = []

    if XGBOOST_AVAILABLE:
        for config in XGB_CONFIGS:
            model = XGBRegressor(
                objective='reg:squarederror',
                random_state=42,
                n_jobs=1,
                subsample=1.0,
                colsample_bytree=1.0,
                reg_lambda=1.0,
                **config,
            )
            pipe = Pipeline([
                ('preprocess', build_preprocessor()),
                ('model', model),
            ])
            start = time.monotonic()
            pipe.fit(x_train, y_train)
            elapsed = time.monotonic() - start
            total_fit_time += elapsed
            val_pred = pipe.predict(x_val)
            candidates.append({
                'pipeline': pipe,
                'selected_model_type': 'xgboost',
                'selected_hyperparameters': config,
                'validation_mae': mae(y_val, val_pred),
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
            elapsed = time.monotonic() - start
            total_fit_time += elapsed
            val_pred = pipe.predict(x_val)
            candidates.append({
                'pipeline': pipe,
                'selected_model_type': 'hist_gradient_boosting_fallback',
                'selected_hyperparameters': config,
                'validation_mae': mae(y_val, val_pred),
            })

    if not candidates:
        raise ValueError('No XGBoost-like model candidates were available.')

    best = min(candidates, key=lambda item: item['validation_mae'])
    return best['pipeline'], best, total_fit_time


def classify_missing_flag(row: pd.Series, predictors: list[str], start_date: pd.Timestamp) -> str:
    missing_predictors = row[predictors].isna()
    if not missing_predictors.any():
        return 'ok'
    day_offset = int((pd.Timestamp(row['delivery_date_local']) - start_date).days)
    if day_offset <= 6:
        return 'missing_due_to_lag_warmup'
    return 'excluded_due_to_missing_predictors'


def build_base_output(df: pd.DataFrame, model_name: str, feature_source: str) -> pd.DataFrame:
    out = pd.DataFrame({
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
        'selected_alpha': np.nan,
        'selected_model_type': pd.NA,
        'selected_hyperparameters': pd.NA,
    })
    return out


def run_naive(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    start = time.monotonic()
    output = build_base_output(df, 'naive_lag_7d_same_direction', 'endogenous_da_aligned_daily_v1')
    output['point_forecast'] = df['avg_price_lag_7d_same_direction']
    start_date = pd.to_datetime(df['delivery_date_local']).min()
    output['forecast_quality_flags'] = [
        'ok' if pd.notna(value) else ('missing_due_to_lag_warmup' if (pd.Timestamp(date) - start_date).days <= 6 else 'excluded_due_to_missing_predictors')
        for value, date in zip(df['avg_price_lag_7d_same_direction'], df['delivery_date_local'])
    ]
    predict_runtime = time.monotonic() - start
    output['fit_runtime_seconds'] = 0.0
    output['predict_runtime_seconds'] = predict_runtime
    output['total_runtime_seconds'] = predict_runtime
    output['n_predictors'] = 1
    output['model_config_summary'] = 'naive_lag_7d_same_direction'
    return output[COMMON_OUTPUT_COLUMNS], {
        'predictors': ['avg_price_lag_7d_same_direction'],
        'selected_alpha': None,
        'selected_model_type': None,
        'selected_hyperparameters': None,
    }


def run_linear(df: pd.DataFrame, predictors: list[str], model_name: str, feature_source: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    total_start = time.monotonic()
    output = build_base_output(df, model_name, feature_source)
    start_date = pd.to_datetime(df['delivery_date_local']).min()
    complete_mask = build_complete_case_mask(df, predictors)
    output['forecast_quality_flags'] = df.apply(lambda row: classify_missing_flag(row, predictors, start_date), axis=1)

    train_complete = df[(df['dataset_split'] == 'train') & complete_mask].copy()
    validation_complete = df[(df['dataset_split'] == 'validation') & complete_mask].copy()
    if train_complete.empty or validation_complete.empty:
        raise ValueError(f'{model_name}: missing complete-case train or validation rows')

    model, selected, fit_runtime = fit_linear_model(train_complete, validation_complete, predictors)
    predict_start = time.monotonic()
    output.loc[complete_mask, 'point_forecast'] = model.predict(df.loc[complete_mask, predictors])
    predict_runtime = time.monotonic() - predict_start
    total_runtime = time.monotonic() - total_start

    output['fit_runtime_seconds'] = fit_runtime
    output['predict_runtime_seconds'] = predict_runtime
    output['total_runtime_seconds'] = total_runtime
    output['n_predictors'] = len(predictors)
    output['model_config_summary'] = f'pooled_up_down_regularised_linear;alphas={ALPHA_GRID};validation_metric=mae'
    output['selected_alpha'] = float(selected['selected_alpha'])
    output['selected_model_type'] = selected['selected_model_type']
    return output[COMMON_OUTPUT_COLUMNS], {
        'predictors': predictors,
        'selected_alpha': float(selected['selected_alpha']),
        'selected_model_type': selected['selected_model_type'],
        'selected_hyperparameters': None,
    }


def run_xgb(df: pd.DataFrame, predictors: list[str]) -> tuple[pd.DataFrame, dict[str, Any]]:
    total_start = time.monotonic()
    output = build_base_output(df, 'xgboost_endogenous_da_aligned_daily_v1', 'endogenous_da_aligned_daily_v1')
    start_date = pd.to_datetime(df['delivery_date_local']).min()
    complete_mask = build_complete_case_mask(df, predictors)
    output['forecast_quality_flags'] = df.apply(lambda row: classify_missing_flag(row, predictors, start_date), axis=1)

    train_complete = df[(df['dataset_split'] == 'train') & complete_mask].copy()
    validation_complete = df[(df['dataset_split'] == 'validation') & complete_mask].copy()
    if train_complete.empty or validation_complete.empty:
        raise ValueError('xgboost_endogenous_da_aligned_daily_v1: missing complete-case train or validation rows')

    model, selected, fit_runtime = fit_xgb_like_model(train_complete, validation_complete, predictors)
    predict_start = time.monotonic()
    output.loc[complete_mask, 'point_forecast'] = model.predict(df.loc[complete_mask, predictors])
    predict_runtime = time.monotonic() - predict_start
    total_runtime = time.monotonic() - total_start

    output['fit_runtime_seconds'] = fit_runtime
    output['predict_runtime_seconds'] = predict_runtime
    output['total_runtime_seconds'] = total_runtime
    output['n_predictors'] = len(predictors)
    output['model_config_summary'] = 'validation_selected_three_config_tree_boosting'
    output['selected_model_type'] = selected['selected_model_type']
    output['selected_hyperparameters'] = json.dumps(selected['selected_hyperparameters'], sort_keys=True)
    return output[COMMON_OUTPUT_COLUMNS], {
        'predictors': predictors,
        'selected_alpha': None,
        'selected_model_type': selected['selected_model_type'],
        'selected_hyperparameters': selected['selected_hyperparameters'],
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
    truth['delivery_date_local'] = pd.to_datetime(truth['delivery_date_local']).dt.strftime('%Y-%m-%d')
    truth['spike_bucket'] = truth.apply(
        lambda row: 'spike' if row['target_average_procurement_price'] >= thresholds[row['direction']] else 'non_spike',
        axis=1,
    )
    out: dict[str, Any] = {'thresholds': {k: float(v) for k, v in thresholds.items()}, 'metrics': {}}
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
        out['metrics'][model_name] = model_metrics
    return out


def validate_forecast_output(df: pd.DataFrame, feature_df: pd.DataFrame, model_name: str, predictors: list[str], feature_source: str, is_exogenous: bool = False) -> dict[str, Any]:
    issues: list[str] = []
    if len(df) != len(feature_df):
        issues.append('row_count_mismatch')
    dupes = int(df.duplicated(['delivery_date_local', 'direction', 'model_name']).sum())
    if dupes:
        issues.append('duplicate_keys')
    if sorted(df['dataset_split'].dropna().unique().tolist()) != ['test', 'train', 'validation']:
        issues.append('unexpected_dataset_splits')
    if pd.to_datetime(df['delivery_date_local']).min() != TRAIN_START or pd.to_datetime(df['delivery_date_local']).max() != TEST_END:
        issues.append('unexpected_date_range')
    if (pd.to_datetime(df['delivery_date_local']) > TEST_END).any():
        issues.append('rows_after_test_end')
    if not np.allclose(df['y_true'].astype(float).to_numpy(), feature_df['target_average_procurement_price'].astype(float).to_numpy(), equal_nan=True):
        issues.append('y_true_mismatch')
    if any(col for col in df.columns if any(token in col.lower() for token in FORBIDDEN_TOKENS)):
        issues.append('forbidden_columns_present')
    if (df[['fit_runtime_seconds', 'predict_runtime_seconds', 'total_runtime_seconds']] < 0).any().any():
        issues.append('negative_runtime')
    if model_name == 'naive_lag_7d_same_direction':
        sample = df['point_forecast'].fillna(-999999).equals(feature_df['avg_price_lag_7d_same_direction'].fillna(-999999))
        if not sample:
            issues.append('naive_forecast_mismatch')
    if any(any(token in c.lower() for token in FORBIDDEN_TOKENS) for c in predictors):
        issues.append('forbidden_predictors_used')
    if is_exogenous:
        val_test_missing = int(df[df['dataset_split'].isin(['validation', 'test'])]['point_forecast'].isna().sum())
        if val_test_missing:
            issues.append('exogenous_val_test_missing_forecasts')
    if sorted(df['model_name'].dropna().unique().tolist()) != [model_name]:
        issues.append('unexpected_model_name')
    if sorted(df['feature_source'].dropna().unique().tolist()) != [feature_source]:
        issues.append('unexpected_feature_source')
    return {'issues': issues, 'row_count': int(len(df)), 'duplicate_key_count': dupes}


def build_all_forecasts() -> dict[str, Any]:
    endogenous = load_features(ENDOGENOUS_FEATURES_PATH)
    exogenous = load_features(EXOGENOUS_FEATURES_PATH)

    endogenous_predictors = get_endogenous_predictors(endogenous)
    exogenous_predictors = get_exogenous_predictors(exogenous)
    if exogenous_predictors != endogenous_predictors + APPROVED_EXOGENOUS_COLUMNS:
        raise ValueError('Exogenous predictor list is not exactly endogenous predictors plus the four approved exogenous columns.')
    val_test_da_missing = int(exogenous[exogenous['dataset_split'].isin(['validation', 'test'])][APPROVED_EXOGENOUS_COLUMNS[:2]].isna().any(axis=1).sum())
    if val_test_da_missing:
        raise ValueError('Validation/test DA-lag missingness remains in DA-aligned exogenous feature table.')

    naive_df, naive_meta = run_naive(endogenous)
    lear_df, lear_meta = run_linear(endogenous, endogenous_predictors, 'lear_endogenous_da_aligned_daily_v1', 'endogenous_da_aligned_daily_v1')
    xgb_df, xgb_meta = run_xgb(endogenous, endogenous_predictors)
    exog_lear_df, exog_lear_meta = run_linear(exogenous, exogenous_predictors, 'lear_exogenous_small_da_aligned_daily_v1', 'endogenous_plus_small_exogenous_da_aligned_daily_v1')

    naive_df.to_csv(NAIVE_OUTPUT_PATH, index=False)
    lear_df.to_csv(LEAR_OUTPUT_PATH, index=False)
    xgb_df.to_csv(XGB_OUTPUT_PATH, index=False)
    exog_lear_df.to_csv(EXOG_LEAR_OUTPUT_PATH, index=False)

    metrics = {
        'naive7d': summarize_metrics(naive_df, endogenous),
        'endogenous_lear': summarize_metrics(lear_df, endogenous),
        'endogenous_xgboost': summarize_metrics(xgb_df, endogenous),
        'exogenous_lear': summarize_metrics(exog_lear_df, exogenous),
    }
    spike = compute_spike_report(endogenous, {
        'naive7d': naive_df,
        'endogenous_lear': lear_df,
        'endogenous_xgboost': xgb_df,
        'exogenous_lear': exog_lear_df,
    })
    validations = {
        'naive7d': validate_forecast_output(naive_df, endogenous, 'naive_lag_7d_same_direction', naive_meta['predictors'], 'endogenous_da_aligned_daily_v1'),
        'endogenous_lear': validate_forecast_output(lear_df, endogenous, 'lear_endogenous_da_aligned_daily_v1', lear_meta['predictors'], 'endogenous_da_aligned_daily_v1'),
        'endogenous_xgboost': validate_forecast_output(xgb_df, endogenous, 'xgboost_endogenous_da_aligned_daily_v1', xgb_meta['predictors'], 'endogenous_da_aligned_daily_v1'),
        'exogenous_lear': validate_forecast_output(exog_lear_df, exogenous, 'lear_exogenous_small_da_aligned_daily_v1', exog_lear_meta['predictors'], 'endogenous_plus_small_exogenous_da_aligned_daily_v1', is_exogenous=True),
    }

    payload = {
        'predictors': {
            'naive7d': naive_meta['predictors'],
            'endogenous_lear': lear_meta['predictors'],
            'endogenous_xgboost': xgb_meta['predictors'],
            'exogenous_lear': exog_lear_meta['predictors'],
        },
        'selected': {
            'naive7d': naive_meta,
            'endogenous_lear': {k: v for k, v in lear_meta.items() if k != 'predictors'},
            'endogenous_xgboost': {k: v for k, v in xgb_meta.items() if k != 'predictors'},
            'exogenous_lear': {k: v for k, v in exog_lear_meta.items() if k != 'predictors'},
        },
        'validations': validations,
        'runtime_summary': {
            'naive7d_total_runtime_seconds': float(naive_df['total_runtime_seconds'].iloc[0]),
            'endogenous_lear_total_runtime_seconds': float(lear_df['total_runtime_seconds'].iloc[0]),
            'endogenous_xgboost_total_runtime_seconds': float(xgb_df['total_runtime_seconds'].iloc[0]),
            'exogenous_lear_total_runtime_seconds': float(exog_lear_df['total_runtime_seconds'].iloc[0]),
        },
        'metrics': metrics,
        'spike_report': spike,
    }
    return payload


def main() -> None:
    payload = build_all_forecasts()
    print(json.dumps({
        'runtime_summary': payload['runtime_summary'],
        'selected': payload['selected'],
        'validations': payload['validations'],
    }, indent=2))


if __name__ == '__main__':
    main()
