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
from sklearn.exceptions import ConvergenceWarning
from sklearn.impute import SimpleImputer
from sklearn.linear_model import ElasticNet, Lasso
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


PROJECT_ROOT = Path(__file__).resolve().parents[4]
FEATURES_PATH = PROJECT_ROOT / 'data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity/nl_ir_capacity_features_exogenous_small_daily_direction.csv'
NAIVE_PATH = PROJECT_ROOT / 'data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity/nl_ir_capacity_forecast_naive7d_daily_direction_long.csv'
LEAR_ENDOGENOUS_PATH = PROJECT_ROOT / 'data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity/nl_ir_capacity_forecast_lear_daily_direction_long.csv'
XGBOOST_PATH = PROJECT_ROOT / 'data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity/nl_ir_capacity_forecast_xgboost_daily_direction_long.csv'
OUTPUT_PATH = PROJECT_ROOT / 'data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity/nl_ir_capacity_forecast_lear_exogenous_small_daily_direction_long.csv'

MODEL_NAME = 'lear_exogenous_small_daily_v1'
TARGET_NAME = 'average_procurement_price'
FEATURE_SOURCE = 'endogenous_plus_small_exogenous_daily_v1'
ALPHA_GRID = [0.0001, 0.001, 0.01, 0.1, 1.0]
FORBIDDEN_PREDICTOR_TOKENS = [
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
EXCLUDED_PREDICTOR_COLUMNS = {
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
OUTPUT_COLUMNS = [
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
]


def load_features() -> pd.DataFrame:
    df = pd.read_csv(FEATURES_PATH)
    required = {
        'delivery_date_local',
        'direction',
        'dataset_split',
        'target_average_procurement_price',
        'direction_code',
        'nl_da_price_daily_avg_lag_1d',
        'nl_da_price_daily_avg_lag_7d',
        'nl_week_ahead_load_daily_mean',
        'nl_week_ahead_load_daily_peak',
    }
    missing = sorted(required - set(df.columns))
    if missing:
        raise ValueError(f'Missing required feature columns: {missing}')
    df['delivery_date_local'] = pd.to_datetime(df['delivery_date_local'])
    return df


def get_predictor_columns(df: pd.DataFrame) -> list[str]:
    predictors: list[str] = []
    for column in df.columns:
        if column in EXCLUDED_PREDICTOR_COLUMNS:
            continue
        lower = column.lower()
        if any(token in lower for token in FORBIDDEN_PREDICTOR_TOKENS):
            continue
        if column.startswith('exogenous_'):
            continue
        predictors.append(column)
    return predictors


def prefit_missingness_summary(df: pd.DataFrame) -> dict[str, Any]:
    lag_mask = df['nl_da_price_daily_avg_lag_1d'].isna() | df['nl_da_price_daily_avg_lag_7d'].isna()
    lag_dates = df.loc[lag_mask, 'delivery_date_local'].drop_duplicates().sort_values()
    start_date = df['delivery_date_local'].min()
    after_first_7 = bool(((lag_dates - start_date).dt.days > 6).any()) if not lag_dates.empty else False
    late_dates = lag_dates[(lag_dates - start_date).dt.days > 6]
    return {
        'row_count': int(len(df)),
        'feature_columns_present': [
            'nl_da_price_daily_avg_lag_1d',
            'nl_da_price_daily_avg_lag_7d',
            'nl_week_ahead_load_daily_mean',
            'nl_week_ahead_load_daily_peak',
        ],
        'missing_counts': df[
            [
                'nl_da_price_daily_avg_lag_1d',
                'nl_da_price_daily_avg_lag_7d',
                'nl_week_ahead_load_daily_mean',
                'nl_week_ahead_load_daily_peak',
            ]
        ].isna().sum().astype(int).to_dict(),
        'first_missing_da_lag_date': None if lag_dates.empty else lag_dates.min().strftime('%Y-%m-%d'),
        'last_missing_da_lag_date': None if lag_dates.empty else lag_dates.max().strftime('%Y-%m-%d'),
        'missing_da_lag_unique_dates': int(len(lag_dates)),
        'missing_da_lag_only_early_warmup': not after_first_7,
        'missing_da_lag_late_dates_sample': [d.strftime('%Y-%m-%d') for d in late_dates.head(10)],
    }


def build_complete_case_mask(df: pd.DataFrame, predictors: list[str]) -> pd.Series:
    return ~df[predictors].isna().any(axis=1)


def make_pipeline(model_type: str, alpha: float) -> Pipeline:
    if model_type == 'lasso':
        model = Lasso(alpha=alpha, max_iter=20000)
    elif model_type == 'elasticnet':
        model = ElasticNet(alpha=alpha, l1_ratio=0.8, max_iter=20000)
    else:
        raise ValueError(f'Unsupported model_type: {model_type}')
    return Pipeline(
        steps=[
            ('preprocess', ColumnTransformer(
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
            )),
            ('model', model),
        ]
    )


def mae(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.mean(np.abs(y_true - y_pred)))


def evaluate_candidates(
    train_df: pd.DataFrame,
    validation_df: pd.DataFrame,
    predictors: list[str],
) -> tuple[Pipeline, dict[str, Any], float]:
    x_train = train_df[predictors]
    y_train = train_df['target_average_procurement_price'].to_numpy(dtype=float)
    x_val = validation_df[predictors]
    y_val = validation_df['target_average_procurement_price'].to_numpy(dtype=float)

    fit_runtime_seconds = 0.0
    candidates: list[dict[str, Any]] = []
    fallback_needed = False

    for alpha in ALPHA_GRID:
        pipeline = make_pipeline('lasso', alpha)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always', ConvergenceWarning)
            start = time.monotonic()
            pipeline.fit(x_train, y_train)
            fit_elapsed = time.monotonic() - start
        fit_runtime_seconds += fit_elapsed
        convergence_warnings = [w for w in caught if issubclass(w.category, ConvergenceWarning)]
        if convergence_warnings:
            fallback_needed = True
            continue
        val_pred = pipeline.predict(x_val)
        candidates.append({
            'pipeline': pipeline,
            'selected_alpha': alpha,
            'selected_model_type': 'lasso',
            'validation_mae': mae(y_val, val_pred),
        })

    if not candidates:
        for alpha in ALPHA_GRID:
            pipeline = make_pipeline('elasticnet', alpha)
            start = time.monotonic()
            pipeline.fit(x_train, y_train)
            fit_elapsed = time.monotonic() - start
            fit_runtime_seconds += fit_elapsed
            val_pred = pipeline.predict(x_val)
            candidates.append({
                'pipeline': pipeline,
                'selected_alpha': alpha,
                'selected_model_type': 'elasticnet',
                'validation_mae': mae(y_val, val_pred),
            })

    best = min(candidates, key=lambda item: item['validation_mae'])
    best['lasso_convergence_fallback_used'] = fallback_needed and best['selected_model_type'] == 'elasticnet'
    return best['pipeline'], best, fit_runtime_seconds


def build_forecast_artifact() -> tuple[pd.DataFrame, dict[str, Any]]:
    features = load_features()
    predictors = get_predictor_columns(features)
    predictor_lower = [col.lower() for col in predictors]
    forbidden_in_predictors = [
        col for col, lower in zip(predictors, predictor_lower) if any(token in lower for token in FORBIDDEN_PREDICTOR_TOKENS)
    ]
    if forbidden_in_predictors:
        raise ValueError(f'Forbidden predictors detected: {forbidden_in_predictors}')

    missingness = prefit_missingness_summary(features)

    features['complete_predictors'] = build_complete_case_mask(features, predictors)
    train_complete = features[(features['dataset_split'] == 'train') & features['complete_predictors']].copy()
    validation_complete = features[(features['dataset_split'] == 'validation') & features['complete_predictors']].copy()
    if train_complete.empty or validation_complete.empty:
        raise ValueError('Insufficient complete-case train/validation rows for fitting and alpha selection.')

    total_start = time.monotonic()
    model, selected, fit_runtime_seconds = evaluate_candidates(train_complete, validation_complete, predictors)

    predict_start = time.monotonic()
    output = features.copy()
    output['point_forecast'] = np.nan
    complete_mask = output['complete_predictors']
    output.loc[complete_mask, 'point_forecast'] = model.predict(output.loc[complete_mask, predictors])
    predict_runtime_seconds = time.monotonic() - predict_start
    total_runtime_seconds = time.monotonic() - total_start

    output['model_name'] = MODEL_NAME
    output['target_name'] = TARGET_NAME
    output['y_true'] = output['target_average_procurement_price']
    output['feature_source'] = FEATURE_SOURCE
    output['forecast_quality_flags'] = np.where(output['complete_predictors'], 'ok', 'excluded_due_to_missing_predictors')
    output['fit_runtime_seconds'] = fit_runtime_seconds
    output['predict_runtime_seconds'] = predict_runtime_seconds
    output['total_runtime_seconds'] = total_runtime_seconds
    output['n_predictors'] = len(predictors)
    output['model_config_summary'] = (
        f'pooled_up_down_regularised_linear;scaler=StandardScaler;alphas={ALPHA_GRID};'
        f'predictor_exclusion=complete_case_only;validation_metric=mae'
    )
    output['selected_alpha'] = float(selected['selected_alpha'])
    output['selected_model_type'] = selected['selected_model_type']

    artifact = output[OUTPUT_COLUMNS].copy()
    artifact['delivery_date_local'] = pd.to_datetime(artifact['delivery_date_local']).dt.strftime('%Y-%m-%d')

    summary = {
        'predictor_columns': predictors,
        'missingness': missingness,
        'fit_runtime_seconds': fit_runtime_seconds,
        'predict_runtime_seconds': predict_runtime_seconds,
        'total_runtime_seconds': total_runtime_seconds,
        'n_predictors': len(predictors),
        'selected_alpha': float(selected['selected_alpha']),
        'selected_model_type': selected['selected_model_type'],
    }
    return artifact, summary


def load_optional_forecast(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    return pd.read_csv(path)


def compute_iqr_map(feature_df: pd.DataFrame) -> dict[tuple[str, str | None], float]:
    result: dict[tuple[str, str | None], float] = {}
    for split in sorted(feature_df['dataset_split'].dropna().unique()):
        split_values = feature_df.loc[feature_df['dataset_split'] == split, 'target_average_procurement_price'].astype(float)
        result[(split, None)] = float(split_values.quantile(0.75) - split_values.quantile(0.25))
        for direction in sorted(feature_df['direction'].dropna().unique()):
            values = feature_df.loc[
                (feature_df['dataset_split'] == split) & (feature_df['direction'] == direction),
                'target_average_procurement_price',
            ].astype(float)
            result[(split, direction)] = float(values.quantile(0.75) - values.quantile(0.25))
    return result


def metric_record(df: pd.DataFrame, split: str, direction: str | None, iqr_value: float) -> dict[str, Any]:
    subset = df[df['dataset_split'] == split].copy()
    if direction is not None:
        subset = subset[subset['direction'] == direction].copy()
    total = int(len(subset))
    forecastable = subset['point_forecast'].notna() & subset['y_true'].notna()
    scored = subset.loc[forecastable].copy()
    missing = total - int(forecastable.sum())
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
    rmse = math.sqrt(float(np.mean(np.square(errors))))
    return {
        'count_total': total,
        'count_forecastable': int(len(scored)),
        'count_missing_forecast': missing,
        'MAE': float(abs_errors.mean()),
        'RMSE': rmse,
        'bias': float(errors.mean()),
        'median_absolute_error': float(abs_errors.median()),
        'p90_absolute_error': float(abs_errors.quantile(0.9)),
        'mae_div_target_iqr': None if iqr_value == 0 else float(abs_errors.mean() / iqr_value),
    }


def summarize_metrics(forecast_df: pd.DataFrame, feature_df: pd.DataFrame) -> dict[str, Any]:
    iqr_map = compute_iqr_map(feature_df)
    splits = ['train', 'validation', 'test']
    directions = sorted(feature_df['direction'].dropna().unique().tolist())
    by_split = {split: metric_record(forecast_df, split, None, iqr_map[(split, None)]) for split in splits}
    by_split_direction = {
        f'{split}|{direction}': metric_record(forecast_df, split, direction, iqr_map[(split, direction)])
        for split in splits for direction in directions
    }
    return {'by_split': by_split, 'by_split_direction': by_split_direction}


def compare_mae(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, a_metrics in a.items():
        b_metrics = b[key]
        a_mae = a_metrics['MAE']
        b_mae = b_metrics['MAE']
        if a_mae is None or b_mae is None:
            out[key] = {'mae_diff': None, 'mae_pct_improvement': None}
            continue
        diff = float(a_mae - b_mae)
        pct = None if b_mae == 0 else float((b_mae - a_mae) / b_mae * 100.0)
        out[key] = {'mae_diff': diff, 'mae_pct_improvement': pct}
    return out


def compute_spike_report(
    feature_df: pd.DataFrame,
    forecast_map: dict[str, pd.DataFrame],
) -> dict[str, Any]:
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

    report: dict[str, Any] = {'thresholds': {k: float(v) for k, v in thresholds.items()}, 'metrics': {}}
    for model_name, df in forecast_map.items():
        merged = df.merge(truth, on=['delivery_date_local', 'direction', 'dataset_split'], how='left', suffixes=('', '_truth'))
        model_metrics: dict[str, Any] = {}
        for split in ['validation', 'test']:
            for direction in sorted(thresholds):
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

    improvements: dict[str, Any] = {}
    for key, exog_metrics in report['metrics']['exogenous_lear'].items():
        endog_metrics = report['metrics']['endogenous_lear'][key]
        naive_metrics = report['metrics']['naive7d'][key]
        improvements[key] = {
            'vs_endogenous_lear_mae_diff': None if exog_metrics['MAE'] is None or endog_metrics['MAE'] is None else float(exog_metrics['MAE'] - endog_metrics['MAE']),
            'vs_naive7d_mae_diff': None if exog_metrics['MAE'] is None or naive_metrics['MAE'] is None else float(exog_metrics['MAE'] - naive_metrics['MAE']),
        }
    report['improvements'] = improvements
    return report


def validate_artifact(artifact: pd.DataFrame, feature_df: pd.DataFrame, predictors: list[str]) -> dict[str, Any]:
    issues: list[str] = []
    duplicate_key_count = int(artifact.duplicated(['delivery_date_local', 'direction', 'model_name']).sum())
    if duplicate_key_count:
        issues.append('duplicate_keys')
    if sorted(artifact['model_name'].dropna().unique().tolist()) != [MODEL_NAME]:
        issues.append('unexpected_model_name')
    if len(artifact) != len(feature_df):
        issues.append('row_count_mismatch')
    if sorted(artifact['dataset_split'].dropna().unique().tolist()) != ['test', 'train', 'validation']:
        issues.append('unexpected_dataset_splits')
    if pd.to_datetime(artifact['delivery_date_local']).max() > pd.Timestamp('2025-12-31'):
        issues.append('date_range_exceeds_limit')
    if not np.allclose(
        artifact['y_true'].astype(float).to_numpy(),
        feature_df['target_average_procurement_price'].astype(float).to_numpy(),
        equal_nan=True,
    ):
        issues.append('y_true_mismatch')
    if artifact['total_runtime_seconds'].isna().any() or (artifact['total_runtime_seconds'] < 0).any():
        issues.append('invalid_runtime_metadata')
    complete_mask = build_complete_case_mask(feature_df, predictors)
    val_test_complete = complete_mask & feature_df['dataset_split'].isin(['validation', 'test'])
    if artifact.loc[val_test_complete, 'point_forecast'].isna().any():
        issues.append('missing_forecasts_on_complete_val_test_rows')
    forbidden_predictors = [
        col for col in predictors if any(token in col.lower() for token in FORBIDDEN_PREDICTOR_TOKENS)
    ]
    if forbidden_predictors:
        issues.append('forbidden_predictors_used')
    return {
        'issues': issues,
        'duplicate_key_count': duplicate_key_count,
        'row_count': int(len(artifact)),
        'expected_row_count': int(len(feature_df)),
        'dataset_splits': sorted(artifact['dataset_split'].dropna().unique().tolist()),
        'complete_val_test_rows': int(val_test_complete.sum()),
        'complete_val_test_missing_forecasts': int(artifact.loc[val_test_complete, 'point_forecast'].isna().sum()),
    }


def build_comparison_report() -> dict[str, Any]:
    feature_df = load_features()
    artifact = pd.read_csv(OUTPUT_PATH)
    predictors = get_predictor_columns(feature_df)

    naive = pd.read_csv(NAIVE_PATH)
    endogenous_lear = pd.read_csv(LEAR_ENDOGENOUS_PATH)
    exogenous_lear = artifact.copy()
    optional_xgb = load_optional_forecast(XGBOOST_PATH)

    metric_tables = {
        'naive7d': summarize_metrics(naive, feature_df),
        'endogenous_lear': summarize_metrics(endogenous_lear, feature_df),
        'exogenous_lear': summarize_metrics(exogenous_lear, feature_df),
    }
    if optional_xgb is not None:
        metric_tables['endogenous_xgboost'] = summarize_metrics(optional_xgb, feature_df)

    split_comparison_vs_endogenous = compare_mae(metric_tables['exogenous_lear']['by_split_direction'], metric_tables['endogenous_lear']['by_split_direction'])
    split_comparison_vs_naive = compare_mae(metric_tables['exogenous_lear']['by_split_direction'], metric_tables['naive7d']['by_split_direction'])

    runtime_summary = {
        'naive7d_total_runtime_seconds': float(naive['total_runtime_seconds'].dropna().iloc[0]) if 'total_runtime_seconds' in naive.columns and naive['total_runtime_seconds'].dropna().any() else None,
        'endogenous_lear_total_runtime_seconds': float(endogenous_lear['total_runtime_seconds'].dropna().iloc[0]) if endogenous_lear['total_runtime_seconds'].dropna().any() else None,
        'exogenous_lear_total_runtime_seconds': float(exogenous_lear['total_runtime_seconds'].dropna().iloc[0]) if exogenous_lear['total_runtime_seconds'].dropna().any() else None,
        'endogenous_xgboost_total_runtime_seconds': None,
    }
    if optional_xgb is not None and optional_xgb['total_runtime_seconds'].dropna().any():
        runtime_summary['endogenous_xgboost_total_runtime_seconds'] = float(optional_xgb['total_runtime_seconds'].dropna().iloc[0])

    spike_report = compute_spike_report(
        feature_df,
        {
            'naive7d': naive,
            'endogenous_lear': endogenous_lear,
            'exogenous_lear': exogenous_lear,
        },
    )

    validation = validate_artifact(exogenous_lear, feature_df, predictors)
    return {
        'metric_tables': metric_tables,
        'comparison_vs_endogenous_lear_by_split_direction': split_comparison_vs_endogenous,
        'comparison_vs_naive7d_by_split_direction': split_comparison_vs_naive,
        'runtime_summary': runtime_summary,
        'spike_report': spike_report,
        'validation': validation,
    }


def main() -> None:
    artifact, summary = build_forecast_artifact()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    artifact.to_csv(OUTPUT_PATH, index=False)

    report = build_comparison_report()
    payload = {
        'build_summary': summary,
        'validation': report['validation'],
        'runtime_summary': report['runtime_summary'],
    }
    print(json.dumps(payload, indent=2))


if __name__ == '__main__':
    main()
