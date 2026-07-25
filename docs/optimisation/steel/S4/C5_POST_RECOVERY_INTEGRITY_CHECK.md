# C5 Post-Recovery Integrity Check

Diagnostic-only post-recovery rerun. No source/model equations, parameter values, production targets, route shares, or assumptions were changed by this report generation.

## Verdict

The current C5p_a executable baseline is reproducible: sequential tests pass, C5p_a and anchor runners pass, generated artifacts parse, and numeric baseline metrics match the last accepted values within tolerance.

NO-GO for starting boiler/steam implementation until the missing boiler/steam source-card path is restored or explicitly replaced by a governed source card. This is a governance/input blocker for the next implementation layer, not a C5p_a reproduction failure.

## Repo State Before Rerun

- Branch: `feature/steel-next-layer`.
- Targeted `git status --short --branch`: clean before rerun.
- C5 source/generated artifact dirtiness before rerun: none in the requested paths.

## Missing Pre-Read Files

- `docs/optimisation/steel/STEEL_S4_4A_UNIFIED_C0_C1_MODEL_CONTRACT.md` missing at requested path.
- `docs/optimisation/steel/STEEL_S4_4B2_PHYSICAL_MASTER_WORKBOOK.md` missing at requested path.
- `data/03_Optimisation/inputs/assets/steel/source_cards/BOILER_STEAM_CIRCUIT_Parameters.md` missing at requested path.

## Checks Run

- C5f-C5k sequential pytest slice: 45 passed.
- C5l-C5m_f sequential pytest slice: 107 passed, including HSM/WBW C5l regressions.
- C5n-C5p_a plus anchor diagnostics sequential pytest slice: 55 passed.
- C5p_a stage runner: pass.
- Anchor/route/denominator diagnostics runner: pass.
- S2 input governance: pass; candidate/development rows remain non-thesis-grade and no approved executable rows were reported.
- Portable path check: pass.
- `git diff --check`: pass; line-ending normalization warnings only for existing S4 CSVs.
- Parse sanity: pass for C5p_a, anchor diagnostics, and generated comparison CSVs.

## Layer Presence

- Expected implemented layers present: 15.
- Missing/incomplete implemented layers: 0.
- Boiler/steam and generator-interface implementation layers are not present, as expected.

## Metric Comparison

- Metrics compared: 111.
- Numeric metrics changed/missing: 0.
- Status/label differences: 1.
- `c5o_b_eaf_heat_state_mode` / `C1_phase1_BF_BOF_plus_DRP_EAF`: expected `fractional development accounting`, current `fractional_heat_equivalent_accounting` (`changed_status`).

## Red Flags And Caveats

- C5p_a failure counts remain zero for C0/C1.
- C5m_f bounded coke reconciliation remains the active development baseline.
- External/unmodelled coke remains fallback-only.
- Denominator remains unresolved; no EUR/t economics denominator is frozen.
- Boiler/steam, generator interface, residual electricity/NG, and consolidated CO2/economics remain deferred.

## Unexpected Items

- The first parallel pytest attempt is invalid for status purposes because multiple tests regenerate shared artifacts concurrently; sequential reruns are clean and governing.
- `BOILER_STEAM_CIRCUIT_Parameters.md` is missing at the requested path, so the next boiler/steam implementation lacks the named source-card input.

## Artifact Index

- `data/03_Optimisation/inputs/assets/steel/S4/c5_post_recovery_integrity_check/c5_post_recovery_layer_presence_matrix.csv`
- `data/03_Optimisation/inputs/assets/steel/S4/c5_post_recovery_integrity_check/c5_post_recovery_metric_comparison.csv`
- `data/03_Optimisation/inputs/assets/steel/S4/c5_post_recovery_integrity_check/c5_post_recovery_red_flag_comparison.csv`
- `data/03_Optimisation/inputs/assets/steel/S4/c5_post_recovery_integrity_check/c5_post_recovery_test_results.csv`
