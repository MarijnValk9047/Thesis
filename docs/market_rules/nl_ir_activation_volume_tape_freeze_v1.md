# NL IR Activation Volume Tape Freeze v1

## Purpose

This note freezes the local volume-only activation tape build for Dutch Incident Reserve / `mFRRda` historical activation-volume preparation.

It does not add activation prices, revenue, settlement, sanctions, MARI, merit-order logic, hydrogen physics, steel physics, or MILP integration.

## Source And Builder

| item | path / value |
|---|---|
| source CSV | `data/02_Forecasting/02_Balancing_mFRR_IR/IR_Activation/frequency_restoration_reserve_activations_202412312300_202512312300_CET (1).csv` |
| source family | TenneT Frequency Restoration Reserve Activations |
| builder script | `scripts/Data/02_Forecasting/02_mFRR_IR_NL/build_nl_ir_activation_volume_tape_from_tennet_frr_v1.py` |
| canonical volume output | `data/02_Forecasting/02_Balancing_mFRR_IR/IR_Activation/nl_ir_activation_volume_tape_isp_v1.csv` |
| compact diagnostics output | `data/02_Forecasting/02_Balancing_mFRR_IR/IR_Activation/diagnostics/nl_ir_activation_volume_tape_diagnostics_v1.csv` |
| output policy | `minimal` |
| run class | `source_transform` |
| lineage role | `diagnostic` |
| generated CSV Git eligibility | false by default |

The accepted source file is treated as historical activation moments and activation volumes for a volume-only tape. It remains asset-neutral and source-scoped.

## Canonical Output Meaning

The canonical output is ISP-long with one row per `delivery_start_utc x direction`.

Key transformations:

- source energy values are kept as `activation_energy_kwh`;
- `activation_energy_mwh = activation_energy_kwh / 1000`;
- `average_activation_mw = activation_energy_mwh / activation_duration_hours`;
- `activation_duration_hours` is derived from reconstructed UTC interval timestamps;
- local timestamps preserve Europe/Amsterdam CET/CEST offsets;
- activation clusters are computed separately by direction;
- no price or revenue columns are created.

Quality labels:

```text
accepted_activation_volume_source
product_scope_to_verify
no_activation_price_in_source
```

## Key Diagnostics

| diagnostic | result |
|---|---:|
| canonical tape rows | `70080` |
| source intervals | `35040` |
| diagnostics rows | `2` |
| local normal-day count | `363` |
| spring DST 92-ISP day count | `1` |
| autumn DST 100-ISP day count | `1` |
| duplicate `delivery_start_utc x direction` rows | `0` |
| activation duration | `0.25` hours |

Direction diagnostics:

| direction | nonzero activation intervals | activation frequency | max average activation MW | cluster count | max cluster length |
|---|---:|---:|---:|---:|---:|
| Up | `42` | `0.0011986301369863` | `786.468` | `12` | `7` |
| Down | `0` | `0.0` | `0.0` | `0` | `0` |

The zero Down activation count is reported as an observed source outcome for this file and is not treated as a script error.

## No-Leakage Statement

This tape is realised historical information. It may be used for ex-post evaluation of a delivery day, or for constructing activation scenarios from prior historical periods. It must not be used as known information in the pre-auction capacity-bidding or DA-bidding decision for the same delivery day.

## Remaining Blockers

- Activation price / remuneration source remains unresolved.
- `product_scope_to_verify` remains open because the file has no explicit specific-vs-standard product column.
- The file has no `mFRRsa` / standard-product separation.
- The file has no energy-bid, merit-order, BSP-specific selection, settlement, sanction, or delivery-quality information.
- Down activation is zero in this local file; this should remain visible in diagnostics and should be checked against source documentation or later samples before broad interpretation.

## Model Meaning

The volume-only tape supports this later evaluation chain:

```text
accepted capacity
-> historical activation request
-> plant delivery check
-> activation remuneration only if delivery is successful and a certified price exists
```

It is not an energy-bid strategy and not merit-order modelling.

## Relation To Future Steel Model

This tape is an asset-neutral market tape.

For a future load-side steel model:

- Up activation means the plant is asked to reduce electricity consumption;
- Down activation means the plant is asked to increase electricity consumption;
- activation duration and volume describe the severity of a historical activation request;
- clusters indicate whether repeated activation intervals need recovery and buffer logic.

Steel feasibility remains a later process-model layer and depends on EAF, DRP, BOF, HSM, buffers, grid limits, and production recovery. Do not hardcode hydrogen or steel physics into this tape or builder.

## Decision

Status: `usable_for_activation_volume_sample`.

The canonical volume tape is available for governed, ex-post activation-volume evaluation and future scenario construction from prior historical periods. It is not a final joined activation price/revenue tape.
