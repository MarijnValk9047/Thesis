## Purpose

Bounded one-off audit runner for ENTSO-E `12_3_f_nl_ir` monthly availability from `2022-01` through `2025-12`.

This exists because the shared `API_GETS.py` runner paginates correctly but only exposes year-based CLI controls. The audit needs:

- bounded monthly `periodStart` / `periodEnd` requests;
- full pagination handling per month;
- compact availability classification;
- a governed manifest for later hybrid `17.1_BC + 12.3_F` method checks.

## Output Location

- raw monthly responses:
  `data/00_Raw/ENTSOE/12_3_F_NL_IR/probes/monthly_scan_2022_2025/`
- compact manifest:
  `data/02_intermediate/Balancing/IR_Capacity/12_3_f_nl_ir_availability_manifest.csv`

## Why One-Off

The logic is campaign-specific and should not widen the stable downloader CLI until bounded-period retrieval becomes a broader repository need.

## Review Condition

If bounded-period ENTSO-E retrieval becomes a standard requirement across datasets, migrate the period-bound options into the canonical downloader surface and retire this one-off runner.
