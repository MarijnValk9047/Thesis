from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[4]
ROOT = PROJECT_ROOT / 'data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity'
ENDOGENOUS_INPUT = ROOT / 'nl_ir_capacity_features_endogenous_daily_direction.csv'
EXOGENOUS_INPUT = ROOT / 'nl_ir_capacity_features_exogenous_small_daily_direction.csv'
TARGET_INPUT = ROOT / 'nl_ir_capacity_target_daily_direction.csv'
ENDOGENOUS_OUTPUT = ROOT / 'nl_ir_capacity_features_endogenous_da_aligned_daily_direction.csv'
EXOGENOUS_OUTPUT = ROOT / 'nl_ir_capacity_features_exogenous_small_da_aligned_daily_direction.csv'

TRAIN_START = pd.Timestamp('2022-01-01')
TRAIN_END = pd.Timestamp('2023-09-30')
VALIDATION_START = pd.Timestamp('2023-10-01')
VALIDATION_END = pd.Timestamp('2024-09-30')
TEST_START = pd.Timestamp('2024-10-01')
TEST_END = pd.Timestamp('2025-09-30')
EXPECTED_TOTAL_ROWS = 2738
EXPECTED_SPLIT_COUNTS = {'train': 1276, 'validation': 732, 'test': 730}
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
EXOGENOUS_REQUIRED_COLUMNS = [
    'nl_da_price_daily_avg_lag_1d',
    'nl_da_price_daily_avg_lag_7d',
    'nl_week_ahead_load_daily_mean',
    'nl_week_ahead_load_daily_peak',
    'exogenous_feature_source',
    'exogenous_known_at_rule',
    'exogenous_quality_flags',
]


def load_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    if 'delivery_date_local' not in df.columns:
        raise ValueError(f'{path.name} missing delivery_date_local')
    df['delivery_date_local'] = pd.to_datetime(df['delivery_date_local'])
    return df


def assign_split(date_value: pd.Timestamp) -> str:
    if TRAIN_START <= date_value <= TRAIN_END:
        return 'train'
    if VALIDATION_START <= date_value <= VALIDATION_END:
        return 'validation'
    if TEST_START <= date_value <= TEST_END:
        return 'test'
    raise ValueError(f'Date outside DA-aligned horizon: {date_value}')


def trim_and_relabel(df: pd.DataFrame) -> pd.DataFrame:
    trimmed = df[(df['delivery_date_local'] >= TRAIN_START) & (df['delivery_date_local'] <= TEST_END)].copy()
    trimmed['dataset_split'] = trimmed['delivery_date_local'].apply(assign_split)
    return trimmed


def validate_identity_against_target(df: pd.DataFrame, target_df: pd.DataFrame, label: str) -> None:
    key_cols = ['delivery_date_local', 'direction']
    merged = df.merge(
        target_df[key_cols + ['target_average_procurement_price']],
        on=key_cols,
        how='left',
        suffixes=('', '_target_anchor'),
    )
    if merged['target_average_procurement_price_target_anchor'].isna().any():
        raise ValueError(f'{label}: missing target anchor rows after trim')
    if not merged['target_average_procurement_price'].equals(merged['target_average_procurement_price_target_anchor']):
        raise ValueError(f'{label}: target_average_procurement_price changed for retained rows')


def rows_match_after_trim(original_trimmed: pd.DataFrame, output_df: pd.DataFrame) -> bool:
    for column in original_trimmed.columns:
        left = original_trimmed[column]
        right = output_df[column]
        if pd.api.types.is_numeric_dtype(left) and pd.api.types.is_numeric_dtype(right):
            if not pd.Series(left).fillna(0).sub(pd.Series(right).fillna(0)).abs().le(1e-12).all():
                null_match = left.isna().equals(right.isna())
                if not null_match:
                    return False
                non_null = ~(left.isna() | right.isna())
                if not (left[non_null].astype(float) - right[non_null].astype(float)).abs().le(1e-12).all():
                    return False
        else:
            if not left.fillna('__NA__').equals(right.fillna('__NA__')):
                return False
    return True


def validate_output(
    df: pd.DataFrame,
    original_df: pd.DataFrame,
    target_df: pd.DataFrame,
    label: str,
    expected_columns: list[str],
) -> dict[str, Any]:
    issues: list[str] = []
    if df.columns.tolist() != expected_columns:
        issues.append('column_set_changed')
    if len(df) != EXPECTED_TOTAL_ROWS:
        issues.append('unexpected_row_count')
    duplicate_keys = int(df.duplicated(['delivery_date_local', 'direction']).sum())
    if duplicate_keys:
        issues.append('duplicate_keys')
    if sorted(df['direction'].dropna().unique().tolist()) != ['Down', 'Up']:
        issues.append('unexpected_directions')
    split_counts = df['dataset_split'].value_counts().to_dict()
    if split_counts != EXPECTED_SPLIT_COUNTS:
        issues.append('unexpected_split_counts')
    if pd.to_datetime(df['delivery_date_local']).min() != TRAIN_START:
        issues.append('unexpected_min_date')
    if pd.to_datetime(df['delivery_date_local']).max() != TEST_END:
        issues.append('unexpected_max_date')
    if (pd.to_datetime(df['delivery_date_local']) > TEST_END).any():
        issues.append('rows_after_test_end')
    if sorted(df['delivery_block_id'].dropna().unique().tolist()) != ['daily_full_day']:
        issues.append('unexpected_delivery_block_id')
    if sorted(df['granularity'].dropna().unique().tolist()) != ['daily']:
        issues.append('unexpected_granularity')
    if sorted(df['market_design_regime'].dropna().unique().tolist()) != ['nl_ir_daily_capacity_v1']:
        issues.append('unexpected_market_design_regime')
    bad_columns = [col for col in df.columns if any(token in col.lower() for token in FORBIDDEN_TOKENS)]
    if bad_columns:
        issues.append('forbidden_columns_present')
    validate_identity_against_target(df, target_df, label)

    original_trimmed = trim_and_relabel(original_df)
    if not rows_match_after_trim(original_trimmed.drop(columns=['dataset_split']), df.drop(columns=['dataset_split'])):
        issues.append('values_changed_beyond_split_and_trim')

    return {
        'issues': issues,
        'row_count': int(len(df)),
        'duplicate_key_count': duplicate_keys,
        'split_counts': split_counts,
        'date_range': (
            pd.to_datetime(df['delivery_date_local']).min().strftime('%Y-%m-%d'),
            pd.to_datetime(df['delivery_date_local']).max().strftime('%Y-%m-%d'),
        ),
        'directions': df['direction'].value_counts().to_dict(),
    }


def validate_exogenous_missingness(df: pd.DataFrame) -> dict[str, Any]:
    missing_counts = df[
        [
            'nl_da_price_daily_avg_lag_1d',
            'nl_da_price_daily_avg_lag_7d',
            'nl_week_ahead_load_daily_mean',
            'nl_week_ahead_load_daily_peak',
        ]
    ].isna().sum().astype(int).to_dict()

    validation_test = df[df['dataset_split'].isin(['validation', 'test'])].copy()
    da_lag_missing_val_test = int(
        validation_test[['nl_da_price_daily_avg_lag_1d', 'nl_da_price_daily_avg_lag_7d']].isna().any(axis=1).sum()
    )
    week_ahead_missing_any = int(
        df[['nl_week_ahead_load_daily_mean', 'nl_week_ahead_load_daily_peak']].isna().any(axis=1).sum()
    )
    if da_lag_missing_val_test:
        raise ValueError('DA-lag missingness remains in validation/test after DA alignment.')
    if week_ahead_missing_any:
        raise ValueError('Week-ahead load missingness remains after DA alignment.')

    return {
        'missing_counts': missing_counts,
        'validation_test_da_lag_missing_rows': da_lag_missing_val_test,
        'all_split_week_ahead_missing_rows': week_ahead_missing_any,
    }


def build_outputs() -> dict[str, Any]:
    endogenous = load_csv(ENDOGENOUS_INPUT)
    exogenous = load_csv(EXOGENOUS_INPUT)
    target = load_csv(TARGET_INPUT)

    for df, name in [(endogenous, 'endogenous'), (exogenous, 'exogenous')]:
        if 'dataset_split' not in df.columns:
            raise ValueError(f'{name} input missing dataset_split')
    for col in EXOGENOUS_REQUIRED_COLUMNS:
        if col not in exogenous.columns:
            raise ValueError(f'exogenous input missing required column: {col}')

    target_anchor = target[['delivery_date_local', 'direction', 'average_procurement_price']].copy()
    target_anchor = target_anchor.rename(columns={'average_procurement_price': 'target_average_procurement_price'})

    endogenous_out = trim_and_relabel(endogenous)
    exogenous_out = trim_and_relabel(exogenous)

    end_validation = validate_output(endogenous_out, endogenous, target_anchor, 'endogenous', endogenous.columns.tolist())
    exog_validation = validate_output(exogenous_out, exogenous, target_anchor, 'exogenous', exogenous.columns.tolist())
    exog_missingness = validate_exogenous_missingness(exogenous_out)

    if end_validation['issues']:
        raise ValueError(f'Endogenous DA-aligned validation failed: {end_validation}')
    if exog_validation['issues']:
        raise ValueError(f'Exogenous DA-aligned validation failed: {exog_validation}')

    ENDOGENOUS_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    endogenous_out.to_csv(ENDOGENOUS_OUTPUT, index=False)
    exogenous_out.to_csv(EXOGENOUS_OUTPUT, index=False)

    return {
        'old_endogenous_range': (
            endogenous['delivery_date_local'].min().strftime('%Y-%m-%d'),
            endogenous['delivery_date_local'].max().strftime('%Y-%m-%d'),
            int(len(endogenous)),
        ),
        'old_exogenous_range': (
            exogenous['delivery_date_local'].min().strftime('%Y-%m-%d'),
            exogenous['delivery_date_local'].max().strftime('%Y-%m-%d'),
            int(len(exogenous)),
        ),
        'new_endogenous': end_validation,
        'new_exogenous': exog_validation,
        'exogenous_missingness': exog_missingness,
    }


def main() -> None:
    summary = build_outputs()
    print(summary)


if __name__ == '__main__':
    main()
