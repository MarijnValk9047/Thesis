# NL IR Activation Tape Input Contract v1

## Purpose

This contract defines the future optimiser-facing schema for a Dutch incident-reserve / `mFRRda` historical activation tape.

It is an input-contract draft only. It does not integrate activation into the MILP, does not define hydrogen or steel redispatch physics, and does not implement settlement or sanctions.

Current sample artifact:

- `data/02_Forecasting/02_Balancing_mFRR_IR/IR_Activation/nl_ir_activation_tape_isp_sample_v1.csv`

The sample is diagnostic-only until source semantics are verified.

Current volume-only artifact:

- `data/02_Forecasting/02_Balancing_mFRR_IR/IR_Activation/nl_ir_activation_volume_tape_isp_v1.csv`

The volume-only tape is built from the accepted local TenneT Frequency Restoration Reserve Activations CSV by `scripts/Data/02_Forecasting/02_mFRR_IR_NL/build_nl_ir_activation_volume_tape_from_tennet_frr_v1.py`. It provides realised activation moments and volumes only. It does not provide activation price, remuneration, settlement, sanctions, or revenue fields. Rows retain `product_scope_to_verify`.

## Tape Grain

One row per:

```text
delivery_start_utc x direction
```

where `direction` is `Up` or `Down`.

The tape is ISP-long. Duration must be computed from `delivery_end_utc - delivery_start_utc`; do not hardcode `0.25` hours or `96` ISPs per day.

## Required Schema

| column | unit / type | status | meaning |
|---|---|---|---|
| `delivery_start_utc` | UTC timestamp | observed interval key | ISP start. |
| `delivery_end_utc` | UTC timestamp | observed interval key | ISP end. |
| `delivery_start_local` | Europe/Amsterdam timestamp | reporting helper | Local timestamp for reporting only. |
| `delivery_date_local` | local date | reporting helper | Local delivery date. |
| `isp_index_local` | integer | derived | ISP index within local delivery date. |
| `direction` | `Up` / `Down` | observed/source-coded | Activation direction. |
| `activation_flag` | boolean | candidate observed proxy | True when the source-backed candidate volume is positive. |
| `system_activated_volume_mw` | MW | candidate observed proxy | Candidate system activated volume. In the v1 sample this remains `volume_semantics_to_verify`. |
| `activation_price_eur_per_mwh` | EUR/MWh | candidate observed proxy | Candidate activation price. Missing values remain missing. |
| `price_available` | boolean | derived | True when `activation_price_eur_per_mwh` is present. |
| `activation_duration_hours` | hours | derived | Interval duration from timestamps. |
| `activation_volume_source` | string | provenance | Source dataset key/path label for volume. |
| `activation_price_source` | string | provenance | Source dataset key/path label for price. |
| `activation_scope` | string | source-quality label | System-level, bid-level, BSP-level, or `to_verify`. |
| `data_quality_flag` | semicolon-separated string | source-quality label | Required caveats and ambiguity flags. |
| `historical_realised_flag` | boolean | lineage label | True for ex-post historical market tape rows. |
| `usable_for_training` | boolean | governance label | False in diagnostic sample. |
| `usable_for_validation` | boolean | governance label | False in diagnostic sample. |
| `usable_for_test` | boolean | governance label | False in diagnostic sample. |

## Truth And Proxy Status

The v1 sample is a source-audit artifact, not final activation truth.

Current status:

- `activation_flag`: source-backed in the volume-only TenneT FRR tape, derived from positive `Incident Reserve Up/Down` activation energy; still subject to `product_scope_to_verify`.
- `system_activated_volume_mw`: source-backed in the volume-only TenneT FRR tape as `average_activation_mw`, derived from activation energy and actual interval duration; ENTSO-E `12_3_e_nl_ir_a61` remains diagnostic-only.
- `activation_price_eur_per_mwh`: candidate proxy from ENTSO-E `17_1_f_nl_a16_realised`; price concept and product isolation remain to verify.
- `data_quality_flag`: mandatory. Volume-only rows use `accepted_activation_volume_source;product_scope_to_verify;no_activation_price_in_source`. Rows with `diagnostic_only`, `volume_semantics_to_verify`, `price_concept_to_verify`, `product_scope_ambiguous`, or `product_scope_to_verify` must not be used as final joined price/revenue truth.

## Assignment Rules For Later Modelling

The observed tape is asset-neutral. It records historical market conditions only. Plant-specific requested activation is a later assignment assumption.

Allowed future assignment rules:

1. Full call if system activated

```text
if activation_flag:
    requested_activation_mw = accepted_capacity_mw
else:
    requested_activation_mw = 0
```

2. Volume capped historical activation

```text
requested_activation_mw = min(accepted_capacity_mw, system_activated_volume_mw)
```

Use only once `system_activated_volume_mw` is source-backed.

3. Pro-rata assignment

```text
activation_fraction = system_activated_volume_mw / reference_available_volume_mw
requested_activation_mw = accepted_capacity_mw * activation_fraction
```

Use only if `reference_available_volume_mw` is source-backed. Do not infer it from the plant model.

## Revenue Logic For Later Use

First conservative default:

```text
revenue_paid_only_if_delivery_ok = true
```

Future accounting should use:

```text
requested_activation_energy_mwh =
    requested_activation_mw * activation_duration_hours

delivered_activation_energy_mwh =
    delivered_activation_mw * activation_duration_hours

if delivery_ok:
    activation_revenue =
        delivered_activation_energy_mwh * activation_price_eur_per_mwh
else:
    activation_revenue = 0
```

This is not a final settlement rule. Sanctions, imbalance settlement, partial delivery, and direction-specific sign conventions remain later source-backed tasks.

## No-Leakage Rule

The activation tape is realised ex-post market information.

Rules:

- Do not use same-day realised activation fields in capacity bidding, DA bidding, pre-delivery scheduling, scenario calibration, or hyperparameter selection.
- For ex-post evaluation, apply the realised tape only after the corresponding delivery period would have occurred.
- Training/validation/test usability flags must be assigned using chronological split policy, not by outcome performance.
- Do not select activation assignment rules, source variants, or CVaR settings based on final test performance.

## Known Source Caveats

Current source caveats:

- The TenneT FRR volume-only tape is accepted for historical activation moments and volumes, but it has no activation-price field and no explicit specific-vs-standard product column.
- ENTSO-E `12_3_e_nl_ir_a61` uses `documentType=A24` and `processType=A61`; whether `quantity_maw` is realised system activation volume remains to verify.
- Incident-reserve / `mFRRda` isolation from broader directly activated `mFRR` remains to verify.
- `secondary_quantity_maw` and `unavailable_quantity_maw` are not merged into activation or emergency-energy fields without source-backed meaning.
- ENTSO-E `17_1_f_nl_a16_realised` no-market-product-filter rows support the sample price table; `Original_MarketProduct_A02` and `A04` returned no matching data for the July 2025 sample.
- Missing prices are not converted to zero.
- Negative prices must be preserved.
- Load-side Up/Down revenue sign conventions remain later settlement work.

## Asset-Neutral Boundary

The tape contains no hydrogen or steel physics.

It must not include:

- electrolyser, compressor, hydrogen-storage, or steel-process constraints;
- EAF, DRP, BOF, HSM, buffer, or production-shortfall logic;
- reserve deliverability calculations;
- activation redispatch decisions;
- energy-bid merit-order bidding or price strategy.

Those belong in future plant-specific model layers after the historical market tape is source-certified.
