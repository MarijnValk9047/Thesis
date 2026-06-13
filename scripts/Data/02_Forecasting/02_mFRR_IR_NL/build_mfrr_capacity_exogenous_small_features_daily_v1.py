from __future__ import annotations

from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[4]
ENDOGENOUS_PATH = PROJECT_ROOT / 'data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity/nl_ir_capacity_features_endogenous_daily_direction.csv'
DA_PRICE_PATH = PROJECT_ROOT / 'data/01_cleaned/Day_ahead_prices/DA_prices/hourly/da_prices_NL_hourly.csv'
WEEK_AHEAD_LOAD_PATH = PROJECT_ROOT / 'data/01_cleaned/Load/week_ahead_total_load_forecast/hourly/week_ahead_total_load_forecast_hourly_long.csv'
OUTPUT_PATH = PROJECT_ROOT / 'data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity/nl_ir_capacity_features_exogenous_small_daily_direction.csv'

AMSTERDAM = ZoneInfo('Europe/Amsterdam')
UTC = ZoneInfo('UTC')
OUTPUT_SOURCE = 'da_price_lagged_realised_plus_week_ahead_load_forecast_v1'
OUTPUT_KNOWN_AT_RULE = 'lagged_da_prices_strictly_historical_and_week_ahead_load_known_before_mfrr_cutoff'
FORBIDDEN_COLUMN_TOKENS = [
    'same_day_da_price',
    'da_forecast_summary',
    'day_ahead_load_forecast',
    'generation_forecast',
    'wind_forecast',
    'solar_forecast',
    'residual_load',
    'actual_load',
    'actual_generation',
    'procured_mw',
    'procured_capacity',
    '12_3_f',
    'threshold_price',
    'max_accepted_price',
    'activation',
]


def _require_columns(df: pd.DataFrame, required: list[str], label: str) -> None:
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(f'{label} missing required columns: {missing}')


def _build_da_lag_features() -> pd.DataFrame:
    df = pd.read_csv(DA_PRICE_PATH, usecols=['region', 'timestamp_utc', 'price_eur_per_mwh'])
    _require_columns(df, ['region', 'timestamp_utc', 'price_eur_per_mwh'], 'DA price input')

    df = df[df['region'] == 'NL'].copy()
    if df.empty:
        raise ValueError('DA price input contains no NL rows.')

    df['timestamp_utc'] = pd.to_datetime(df['timestamp_utc'], utc=True)
    df['delivery_date_local'] = df['timestamp_utc'].dt.tz_convert(AMSTERDAM).dt.date

    daily = (
        df.groupby('delivery_date_local', as_index=False)['price_eur_per_mwh']
        .mean()
        .rename(columns={'price_eur_per_mwh': 'nl_da_price_daily_avg'})
    )
    daily['delivery_date_local'] = pd.to_datetime(daily['delivery_date_local'])

    lag_1 = daily[['delivery_date_local', 'nl_da_price_daily_avg']].copy()
    lag_1['delivery_date_local'] = lag_1['delivery_date_local'] + pd.Timedelta(days=1)
    lag_1 = lag_1.rename(columns={'nl_da_price_daily_avg': 'nl_da_price_daily_avg_lag_1d'})

    lag_7 = daily[['delivery_date_local', 'nl_da_price_daily_avg']].copy()
    lag_7['delivery_date_local'] = lag_7['delivery_date_local'] + pd.Timedelta(days=7)
    lag_7 = lag_7.rename(columns={'nl_da_price_daily_avg': 'nl_da_price_daily_avg_lag_7d'})

    return lag_1.merge(lag_7, on='delivery_date_local', how='outer').sort_values('delivery_date_local')


def _build_week_ahead_features() -> pd.DataFrame:
    usecols = [
        'market',
        'timestamp_utc',
        'value_mw',
        'target_delivery_local_date',
        'target_hour_local',
        'known_at_utc',
        'known_at_rule',
    ]
    df = pd.read_csv(WEEK_AHEAD_LOAD_PATH, usecols=usecols)
    _require_columns(df, usecols, 'Week-ahead load input')

    df = df[df['market'] == 'NL'].copy()
    if df.empty:
        raise ValueError('Week-ahead load input contains no NL rows.')

    df['timestamp_utc'] = pd.to_datetime(df['timestamp_utc'], utc=True)
    df['known_at_utc'] = pd.to_datetime(df['known_at_utc'], utc=True)
    if df['known_at_utc'].isna().any():
        raise ValueError('Week-ahead load input contains missing known_at_utc values.')

    df['delivery_date_local'] = pd.to_datetime(df['target_delivery_local_date'])
    df['cutoff_local'] = df['delivery_date_local'].apply(
        lambda d: pd.Timestamp(d.date() - pd.Timedelta(days=1), tz=AMSTERDAM) + pd.Timedelta(hours=9)
    )
    df['cutoff_utc'] = df['cutoff_local'].dt.tz_convert(UTC)
    df['is_safe_known_at'] = df['known_at_utc'] <= df['cutoff_utc']

    hourly_total = (
        df.groupby(['delivery_date_local', 'timestamp_utc'], as_index=False)
        .agg(total_rows=('value_mw', 'size'), any_unsafe=('is_safe_known_at', lambda s: bool((~s).any())))
    )

    safe = df[df['is_safe_known_at']].copy()
    if safe.empty:
        raise ValueError('Week-ahead load input contains no safe NL rows after known_at filtering.')

    safe = safe.sort_values(['delivery_date_local', 'timestamp_utc', 'known_at_utc'])
    selected = safe.groupby(['delivery_date_local', 'timestamp_utc'], as_index=False).tail(1)

    violations = selected['known_at_utc'] > selected['cutoff_utc']
    if violations.any():
        raise ValueError('Selected week-ahead rows violate the D-1 09:00 Europe/Amsterdam cutoff.')

    daily = (
        selected.groupby('delivery_date_local', as_index=False)
        .agg(
            nl_week_ahead_load_daily_mean=('value_mw', 'mean'),
            nl_week_ahead_load_daily_peak=('value_mw', 'max'),
            selected_hour_count=('timestamp_utc', 'size'),
        )
    )

    known_at_daily = (
        hourly_total.groupby('delivery_date_local', as_index=False)
        .agg(
            total_target_hours=('timestamp_utc', 'size'),
            unsafe_target_hours=('any_unsafe', 'sum'),
        )
    )

    out = daily.merge(known_at_daily, on='delivery_date_local', how='left')
    out['week_ahead_missing_hours'] = out['total_target_hours'] - out['selected_hour_count']
    return out.sort_values('delivery_date_local')


def _compose_quality_flags(df: pd.DataFrame) -> pd.Series:
    flags = []
    for row in df.itertuples(index=False):
        row_flags: list[str] = []
        if pd.isna(row.nl_da_price_daily_avg_lag_1d) or pd.isna(row.nl_da_price_daily_avg_lag_7d):
            row_flags.append('missing_da_lag_warmup')
        if pd.isna(row.nl_week_ahead_load_daily_mean) or pd.isna(row.nl_week_ahead_load_daily_peak):
            row_flags.append('missing_week_ahead_load')
        if (
            pd.notna(row.unsafe_target_hours)
            and row.unsafe_target_hours > 0
            or pd.notna(row.week_ahead_missing_hours)
            and row.week_ahead_missing_hours > 0
        ):
            row_flags.append('known_at_filtered')
        flags.append('|'.join(row_flags) if row_flags else 'ok')
    return pd.Series(flags, index=df.index, dtype='string')


def build_feature_table() -> pd.DataFrame:
    endogenous = pd.read_csv(ENDOGENOUS_PATH)
    _require_columns(
        endogenous,
        [
            'delivery_date_local',
            'direction',
            'dataset_split',
            'target_average_procurement_price',
            'delivery_block_id',
            'granularity',
            'market_design_regime',
        ],
        'Endogenous feature table',
    )

    endogenous['delivery_date_local'] = pd.to_datetime(endogenous['delivery_date_local'])
    original_columns = endogenous.columns.tolist()

    da_features = _build_da_lag_features()
    week_ahead_features = _build_week_ahead_features()

    output = endogenous.merge(da_features, on='delivery_date_local', how='left')
    output = output.merge(week_ahead_features, on='delivery_date_local', how='left')

    output['exogenous_feature_source'] = OUTPUT_SOURCE
    output['exogenous_known_at_rule'] = OUTPUT_KNOWN_AT_RULE
    output['exogenous_quality_flags'] = _compose_quality_flags(output)

    output = output[original_columns + [
        'nl_da_price_daily_avg_lag_1d',
        'nl_da_price_daily_avg_lag_7d',
        'nl_week_ahead_load_daily_mean',
        'nl_week_ahead_load_daily_peak',
        'exogenous_feature_source',
        'exogenous_known_at_rule',
        'exogenous_quality_flags',
    ]]
    return output


def validate_output(output: pd.DataFrame) -> dict[str, object]:
    endogenous = pd.read_csv(ENDOGENOUS_PATH)
    endogenous_predictor_columns = [c for c in endogenous.columns if c != 'target_average_procurement_price']

    row_count_ok = len(output) == len(endogenous)
    duplicate_keys = int(output.duplicated(['delivery_date_local', 'direction']).sum())
    forbidden_columns = [
        column for column in output.columns if any(token in column.lower() for token in FORBIDDEN_COLUMN_TOKENS)
    ]
    missing_predictors = [col for col in endogenous_predictor_columns if col not in output.columns]

    dataset_splits = sorted(output['dataset_split'].dropna().unique().tolist())
    directions = sorted(output['direction'].dropna().unique().tolist())
    max_date = pd.to_datetime(output['delivery_date_local']).max()

    da_daily = pd.read_csv(DA_PRICE_PATH, usecols=['region', 'timestamp_utc', 'price_eur_per_mwh'])
    da_daily = da_daily[da_daily['region'] == 'NL'].copy()
    da_daily['timestamp_utc'] = pd.to_datetime(da_daily['timestamp_utc'], utc=True)
    da_daily['delivery_date_local'] = da_daily['timestamp_utc'].dt.tz_convert(AMSTERDAM).dt.date
    da_daily = da_daily.groupby('delivery_date_local', as_index=False)['price_eur_per_mwh'].mean()
    da_daily['delivery_date_local'] = pd.to_datetime(da_daily['delivery_date_local'])
    da_daily = da_daily.rename(columns={'price_eur_per_mwh': 'daily_avg'})

    sample_row = output[output['nl_da_price_daily_avg_lag_1d'].notna() & output['nl_da_price_daily_avg_lag_7d'].notna()].iloc[0]
    sample_date = pd.Timestamp(sample_row['delivery_date_local'])
    expected_lag_1 = da_daily.loc[da_daily['delivery_date_local'] == sample_date - pd.Timedelta(days=1), 'daily_avg'].iloc[0]
    expected_lag_7 = da_daily.loc[da_daily['delivery_date_local'] == sample_date - pd.Timedelta(days=7), 'daily_avg'].iloc[0]

    week = pd.read_csv(WEEK_AHEAD_LOAD_PATH, usecols=['market', 'timestamp_utc', 'value_mw', 'target_delivery_local_date', 'known_at_utc'])
    week = week[week['market'] == 'NL'].copy()
    week['timestamp_utc'] = pd.to_datetime(week['timestamp_utc'], utc=True)
    week['known_at_utc'] = pd.to_datetime(week['known_at_utc'], utc=True)
    week['delivery_date_local'] = pd.to_datetime(week['target_delivery_local_date'])
    week['cutoff_local'] = week['delivery_date_local'].apply(
        lambda d: pd.Timestamp(d.date() - pd.Timedelta(days=1), tz=AMSTERDAM) + pd.Timedelta(hours=10)
    )
    week['cutoff_utc'] = week['cutoff_local'].dt.tz_convert(UTC)
    safe_week = week[week['known_at_utc'] <= week['cutoff_utc']].copy()
    latest_safe = safe_week.sort_values(['delivery_date_local', 'timestamp_utc', 'known_at_utc']).groupby(
        ['delivery_date_local', 'timestamp_utc'], as_index=False
    ).tail(1)

    week_missing_mean = int(output['nl_week_ahead_load_daily_mean'].isna().sum())
    week_missing_peak = int(output['nl_week_ahead_load_daily_peak'].isna().sum())
    non_null_week = output[output['nl_week_ahead_load_daily_mean'].notna()]

    issues: list[str] = []
    if not row_count_ok:
        issues.append('row_count_mismatch')
    if duplicate_keys:
        issues.append('duplicate_delivery_date_direction_keys')
    if directions != ['Down', 'Up']:
        issues.append('unexpected_directions')
    if dataset_splits != ['test', 'train', 'validation']:
        issues.append('unexpected_dataset_splits')
    if max_date > pd.Timestamp('2025-12-31'):
        issues.append('date_range_exceeds_limit')
    if forbidden_columns:
        issues.append('forbidden_columns_present')
    if missing_predictors:
        issues.append('endogenous_predictors_missing')
    if 'same_day_da_price' in ''.join(output.columns.str.lower().tolist()):
        issues.append('same_day_da_column_present')
    if abs(float(sample_row['nl_da_price_daily_avg_lag_1d']) - float(expected_lag_1)) > 1e-9:
        issues.append('lag_1_validation_failed')
    if abs(float(sample_row['nl_da_price_daily_avg_lag_7d']) - float(expected_lag_7)) > 1e-9:
        issues.append('lag_7_validation_failed')
    if (latest_safe['known_at_utc'] > latest_safe['cutoff_utc']).any():
        issues.append('week_ahead_cutoff_validation_failed')
    if output['exogenous_quality_flags'].isna().any() or (output['exogenous_quality_flags'].astype(str).str.len() == 0).any():
        issues.append('quality_flags_invalid')

    return {
        'row_count': int(len(output)),
        'endogenous_row_count': int(len(endogenous)),
        'duplicate_key_count': duplicate_keys,
        'directions': directions,
        'dataset_splits': dataset_splits,
        'max_delivery_date_local': max_date.strftime('%Y-%m-%d'),
        'forbidden_columns': forbidden_columns,
        'missing_endogenous_predictors': missing_predictors,
        'week_ahead_missing_mean': week_missing_mean,
        'week_ahead_missing_peak': week_missing_peak,
        'week_ahead_non_null_start': None if non_null_week.empty else pd.to_datetime(non_null_week['delivery_date_local']).min().strftime('%Y-%m-%d'),
        'week_ahead_non_null_end': None if non_null_week.empty else pd.to_datetime(non_null_week['delivery_date_local']).max().strftime('%Y-%m-%d'),
        'da_lag_sample_date': sample_date.strftime('%Y-%m-%d'),
        'da_lag_sample_expected_1d': float(expected_lag_1),
        'da_lag_sample_actual_1d': float(sample_row['nl_da_price_daily_avg_lag_1d']),
        'da_lag_sample_expected_7d': float(expected_lag_7),
        'da_lag_sample_actual_7d': float(sample_row['nl_da_price_daily_avg_lag_7d']),
        'quality_flag_counts': output['exogenous_quality_flags'].value_counts(dropna=False).to_dict(),
        'issues': issues,
    }


def main() -> None:
    output = build_feature_table()
    validation = validate_output(output)
    if validation['issues']:
        raise ValueError(f'Validation failed: {validation}')

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(OUTPUT_PATH, index=False)

    print(f'WROTE {OUTPUT_PATH}')
    print(f"ROW_COUNT {validation['row_count']}")
    print(f"WEEK_AHEAD_NON_NULL_RANGE {validation['week_ahead_non_null_start']} {validation['week_ahead_non_null_end']}")
    print(f"MISSING_WEEK_AHEAD mean={validation['week_ahead_missing_mean']} peak={validation['week_ahead_missing_peak']}")
    print(f"QUALITY_FLAGS {validation['quality_flag_counts']}")


if __name__ == '__main__':
    main()
