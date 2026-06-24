# S3.3g C1 Gas-Sink Decomposition Diagnostic

## Status

S3.3g is a bounded C1 diagnostic only. It is not an S3.3 freeze, not S4 entry, and not an approved-input promotion.

The diagnostic tests whether the S3.3f C1 mismatch can be reduced by replacing the broad downstream/light-side utility gas term with named Athanasiadis-compatible gas sinks. It does not use residual natural-gas closure, inherited C0 residual gas, Table 9 back-calculation, or arbitrary WAG availability factors.

## Source-Card Review

The Athanasiadis gas-network evidence is recorded in:

`data/03_Optimisation/inputs/assets/steel/S3/s3_candidate_review/s3_3g_athanasiadis_gas_network_source_card_register.csv`

The local thesis PDF was not found in the allowed checked locations during S3.3g. Therefore, the register distinguishes existing human-verified source packets, research-memo context, prompt-provided figure notes, and source-needed numeric items. The figure/caption ambiguity is retained: the uploaded screenshots are described as the main-plants gas controller; extracted text maps that controller to Figure 31, while Figure 32 refers to boiler/steam demand.

## Named Sinks

S3.3g separates:

- `hsm_fuel_substitution_ng`
- `hsm_fuel_substitution_cog`
- `coking_plant_1_bfg`
- `coking_plant_1_cog`
- `pelletizing_firing_ng`
- `pelletizing_firing_cog`
- `pelletizing_grinding_ng`
- `pelletizing_grinding_bofg`
- `boiler_steam_ng`
- `boiler_steam_wag`
- `vattenfall_generator_bfg_equivalent_wag`
- `vattenfall_generator_high_lhv_injection_limit`

Each sink has separate structural support, numeric support, diagnostic eligibility, C1 applicability, and model-use status in:

`data/03_Optimisation/inputs/assets/steel/S3/s3_candidate_review/s3_3g_c1_gas_sink_parameter_eligibility.csv`

Source-needed flows are included in the structural register but are not silently treated as approved numeric values. S3.3g cases set unsupported numeric splits to zero unless a diagnostic-only governed range is explicitly recorded.

## Diagnostic Mechanism

The current model represents the gas-sink decomposition through the existing downstream/light-side utility heat balance:

- explicit NG sinks set the minimum natural-gas heat share;
- WAG sinks increase heat demand that can divert WAG from power to process/boiler use;
- WAG-to-power efficiency stays within the existing public/governed range;
- Vattenfall LHV-limited generation is represented only as a bounded residual-WAG utilisation/interface diagnostic, not as a fitted availability factor.

This is a compact abstraction, not a full gas-network dispatch model.

## Case Set

The deterministic case set compares:

- S3.3f best bounded comparison baseline;
- central explicit gas-sink decomposition;
- low process-NG / high WAG-to-process;
- high process-NG / low WAG-to-power;
- HSM-heavy substitution;
- pelletizing-heavy substitution;
- boiler/steam-heavy substitution;
- Vattenfall LHV-limited generation;
- combined best-source-supported diagnostic.

The cases use BF-BOF shares `0.5033645161` and `0.55` and the retained C0 central, low-WAG, and high-WAG sets. C0 is not retuned.

## Interpretation Rules

S3.3g may support bounded alignment only unless all principal C1 targets are met without residual terms and all active numeric assumptions have approved source cards. Remaining mismatch is classified as structural, numeric-source, or boundary-related in:

`data/03_Optimisation/inputs/assets/steel/S3/s3_candidate_review/s3_3g_c1_remaining_gap_analysis.csv`

No S3.3 freeze or S4 readiness claim follows from this diagnostic.
