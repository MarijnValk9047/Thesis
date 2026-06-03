# FS3 vs LEAR_STRICT Backbone Comparison

## FS3 QH hourly anchors (referenced models)
- `qh-fs1__lear__hourly_anchor__lear_fs3_combo_promoted` and `qh-fs1__xgboost__hourly_anchor__xgboost_fs3_combo_pruned_candidate` are sourced from phase07 run `20260505_134716_phase07_realistic_track_a` (see phase2.7 `run_summary.json`).
- Phase07 backbone file: `bridged_hourly_target_input_all_regions.csv` built in `phase07._build_hourly_bridge(...)`: pre-cutoff official hourly + post-cutoff hourly mean of complete 4-quarter blocks.

## LEAR_STRICT exporter backbone
- Exporter reads bridge via `run_lago_lear_export_for_qh._resolve_bridge_path(targets_by_origin.parent / hourly_backbone_bridge_input.csv)`.
- For this task: observed run bridge `20260503_174631_observed_market_deterministic_forecast/hourly_backbone_bridge_input.csv`.

## Key finding
- Observed-run bridge post-transition complete local days: 149/223.
- Phase07 bridge (NL) post-transition complete local days: 208/212.
- LEAR_STRICT lag failures are mainly endogenous (`p_base_d_minus_*`, `p_target_d_minus_7`) and align with incomplete hourly day vectors in the observed-run bridge.

## Routing assessment
- LEAR_STRICT is not using the same bridge file as phase07 FS3 anchors.
- This is not a tiny path typo; switching bridge source changes backbone construction basis and should be approved explicitly.

## Recommendation
- Decision: **C**.
- Current strict-matrix overlap estimate: 4455/25920 (17.19%).
- Hypothetical phase07-bridge overlap estimate: 24642/25920 (95.07%).
- No backbone-method patch applied in this diagnostic run.
