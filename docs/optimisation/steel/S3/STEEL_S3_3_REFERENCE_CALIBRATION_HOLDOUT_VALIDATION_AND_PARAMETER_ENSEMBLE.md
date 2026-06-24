# S3.3 Reference Calibration, Holdout Validation, And Parameter Ensemble

Date: 2026-06-20

## Scope

S3.3 adds a governed production-scale calibration layer on top of the frozen S2.13/S3.2 steel-site model. It does not add DA prices, bidding, settlement, stochastic logic, CVaR, mFRR, product revenue, export revenue, or new route topology.

The S3.3 calibration scale is `6,200,000 t_final_product/year`, equal to `707.7625571 t/h`, `16,986.3013699 t/24h`, and `118,904.1095890 t/168h`. The previous S2.13/S3.2 development baseline remains available at about `2.975 Mt/year` and was not overwritten.

## Fixed Physical Decisions

- Cold slab yard capacity: `25,000 t`.
- Initial cold slab inventory: preserved at `1,630.13544 t`.
- Terminal cold inventory: equals initial.
- Hot-metal buffer capacity: `500 t`.
- Existing hot-metal initial inventory: `159.8172 t`, so no conflict with the `500 t` cap.
- Unrestricted slab-store reference: about `68,000 t`, used only as behavioural context.
- Badarinath-aligned `6.75 Mt/year` scale remains an external stress case, not the calibration base.

## Target Packet

The target register is `data/03_Optimisation/inputs/assets/steel/S3/s3_candidate_review/s3_3_visual_and_written_target_register.csv`.

C0 calibration targets:

- Gross electricity: `3.17 TWh/year`.
- WAG electricity: `2.74 TWh/year`.
- Natural gas: `33,243.63 m3/h`.
- Direct CO2 proxy: `13,365,216.16 t/year`.
- Figure 96 total primary-energy proxy: `102.6289 PJ/year`.
- Normal-operation flare: preferred `<=2%`, admissible `<=5%` of generated WAG energy.

C1 holdout targets:

- Gross electricity: `4.89 TWh/year`.
- WAG electricity: `1.23 TWh/year`.
- Natural gas: `151,673.52 m3/h`.
- Direct CO2 proxy: `9,107,793.17 t/year`.
- Figure 104 total primary-energy proxy: `102.1941 PJ/year`.

## Boundary Decisions

Figure 96 and Table 8 are inconsistent for C0 electricity. Figure 96's `9.3%` electricity share implies about `2.651 TWh/year`, while Table 8 reports `3.17 TWh/year`.

S3.3 therefore uses two interpretations:

- `c0_figure96_reported`: keeps the reported 79.3 / 9.3 / 11.4 carrier shares for soft audit only.
- `c0_table8_primary`: uses Table 8 gross electricity, WAG electricity, natural gas, and CO2 for calibration.

WAG is not double-counted in primary-energy accounting. The adapter reports external coal-origin energy, internal WAG generation and allocation, gross electricity, WAG electricity generation, net grid import, and a separate Athanasiadis-compatible proxy. WAG fuel energy is internal conversion energy and is not added again as an extra primary input.

## Screening

The deterministic OAT screen used the 24h C0 calibration anchor and varied all eligible parameter groups low/central/high. The retained influence ranking was:

| Rank | Parameter | Max normalised effect |
|---:|---|---:|
| 1 | residual auxiliary electricity scale | 10.9876 |
| 2 | WAG residual utilisation/interface limit | 10.4775 |
| 3 | residual C0 natural-gas demand | 10.0000 |
| 4 | coal/coke primary-energy factor | 3.3641 |
| 5 | BF-BOF aggregate direct-CO2 factor | 2.5777 |
| 6 | steam/process-heat demand scale | 2.4368 |
| 7 | downstream electricity scale | 2.2247 |
| 8 | BFG generation yield | 2.2154 |
| 9 | WAG LHV scale | 1.4265 |
| 10 | WAG-to-power efficiency | 1.2795 |
| 11 | COG generation yield | 0.9995 |
| 12 | BOFG generation yield | 0.5103 |

Prices, production target, storage capacities, topology, and DA/stochastic/risk parameters were excluded from physical calibration.

## Candidate Calibration

Candidate design:

- seed: `202503`;
- candidates: `64`;
- design: deterministic source-central row, calibrated anchor/envelope rows, and Latin-hypercube rows;
- 24h C0 feasible/accepted sets: `5`;
- 168h C0 confirmed and retained sets: `5`.

Selected ensemble:

| Role | Candidate | Gross electricity error | WAG electricity error | NG error | CO2 error | Primary proxy error |
|---|---|---:|---:|---:|---:|---:|
| central calibrated set | `S33_CAND_001_CALIBRATION_ANCHOR` | -0.554% | +3.535% | ~0.000% | ~0.000% | +0.282% |
| lower energy/WAG envelope | `S33_CAND_002_LOW_WAG_ENVELOPE` | -0.555% | -1.382% | ~0.000% | ~0.000% | +0.282% |
| higher energy/WAG envelope | `S33_CAND_003_HIGH_WAG_ENVELOPE` | -0.554% | +8.778% | ~0.000% | ~0.000% | +0.282% |

Central calibrated inputs include residual auxiliary electricity scale `3.85`, residual C0 NG demand `46.97 m3/t_final_product`, WAG residual utilisation fraction `0.95`, coal primary-energy factor `44.0 GJ/t_dry_coal`, and BF-BOF aggregate direct CO2 `2.15568 tCO2/t_BOF_liquid_steel`.

## C1 Holdout

The retained C0 parameter sets were applied unchanged to C1 BF-BOF route-share scenarios `0.55`, `0.61`, and `0.68`. No C1 holdout case passed all principal targets.

Average holdout errors across retained C0 sets:

| BF-BOF share | Gross electricity | WAG electricity | NG flow | Direct CO2 |
|---:|---:|---:|---:|---:|
| 0.55 | +4.22% | +27.57% | -19.84% | +2.50% |
| 0.61 | -1.07% | +41.49% | -27.60% | +8.40% |
| 0.68 | -7.25% | +57.73% | -36.66% | +15.28% |

Interpretation: the C0 fit is not a defensible cross-configuration calibration. The current C1 representation loses too little WAG electricity and gains too little natural-gas exposure relative to Athanasiadis Phase 1 Table 9, while retained BF-BOF share increases worsen the WAG electricity error.

## Behavioural Validation

For the best three retained sets:

- normal WAG operation solved;
- WAG-generator/interface outage solved and increased flare materially, with average flare increase about `0.641` of generated WAG energy;
- unrestricted slab-yard diagnostic solved but did not approach the `68,000 t` behavioural reference; max cold slab remained `1,630.13544 t`;
- DSP, HSM, and slab-storage relaxation diagnostics solved but showed near-zero objective effect under the static fixed-output objective;
- hot-metal storage relaxation was blocked because hot-metal storage is governed at `500 t` but is not an active store in the S2.13 integrated downstream schedule.

The Table 7 comparison is therefore only partially supported: WAG outage direction is reproduced, but storage/flexibility ranking is not validated under the current static, no-price objective.

## Scale Stress

The optional `6.75 Mt/year` stress used the central C0-calibrated set without recalibration and solved optimally for 168h:

- annualised product: `6,750,000 t/year`;
- gross electricity: `3.4321 TWh/year`;
- WAG electricity: `3.0885 TWh/year`;
- natural gas: `36,192.64 m3/h`;
- direct CO2: `14,550,840 t/year`;
- max cold slab inventory: `1,630.13544 t`;
- terminal cold residual: `0.0 t`.

## Identifiability

- Well identified against single targets: residual C0 NG demand, BF-BOF aggregate direct-CO2 factor.
- Weakly identified: residual auxiliary electricity scale, WAG residual utilisation, WAG yields, LHVs, power efficiency, coal primary-energy factor, downstream electricity scale, heat-demand scale.
- Non-identifiable in this static C0 calibration: individual downstream electricity components and separate BFG/COG/BOFG contributions when similar WAG electricity totals can be produced by multiple combinations.

## Stage Gate

S3.3 is blocked for freeze and S4 entry.

Passed:

- separate `6.2 Mt/year` overlay exists;
- legacy development scale remains available;
- storage capacities and terminal policies are governed;
- Figure 96/Table 8 conflict is recorded;
- C0 168h retained at least three calibrated sets;
- behavioural diagnostics were run;
- no DA, stochastic, CVaR, mFRR, bidding, or settlement logic was introduced.

Blocked:

- C1 holdout validation has zero pass cases.
- The current S2.13/S3.2 C1 energy structure cannot reproduce Phase 1 NG and WAG electricity targets without a C1-specific review of DRP NG intensity, retained WAG generation, WAG-to-power interface, or Phase 1 boundary interpretation.

No `STEEL_S3_3_CALIBRATION_VALIDATION_FREEZE_AND_S4_ENTRY.md` freeze record is created.

## Next Action

Do not start S4. Review the C1 holdout boundary and C1-only physical assumptions, especially DRP natural-gas intensity, retained coking/WAG scaling, WAG-to-power interpretation, and whether Athanasiadis Table 9 includes additional natural-gas-consuming site components absent from the current S2.13/S3.2 model.
