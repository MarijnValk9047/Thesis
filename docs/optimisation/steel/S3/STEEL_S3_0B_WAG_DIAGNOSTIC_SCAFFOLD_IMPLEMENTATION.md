# S3.0b-b1 WAG Diagnostic Scaffold Implementation

## Scope

This memo records the fixed-profile WAG diagnostic scaffold implemented for `S3.0b-b1`.

The scaffold is deterministic Python accounting code only. It does not modify the S2 optimisation model, create WAG optimisation, add DA prices, add settlement, create export revenue, or create thesis-grade inputs.

## Modules

- `scripts/Data/04_Steel_Test_Case/steel/wag_diagnostic_inputs.py`
  - loads only `s3_wag_selected_dev_inputs.csv` as the coefficient source;
  - rejects the development selection-review CSV as a loader input;
  - validates fixed activity-profile fixtures against the governed schema fields;
  - rejects generated run-folder paths as canonical profile inputs.

- `scripts/Data/04_Steel_Test_Case/steel/wag_diagnostic.py`
  - implements BFG and BOFG volume-to-energy calculations;
  - implements the accounting-only COG chain with explicit missing-input blocking;
  - implements the fixed process-first allocation hierarchy;
  - implements point-of-oxidation emissions accounting;
  - reports implementation and runtime readiness separately.

- `scripts/Data/04_Steel_Test_Case/steel/wag_diagnostic_runner.py`
  - provides a guarded CLI with `--validate-inputs-only`, `--profile-path`, `--selected-input-path`, and optional `--output-path`;
  - creates no run folder and writes no output unless an explicit output path is supplied;
  - returns success for validation-only checks even when full runtime remains blocked.

## Input Contract

The selected coefficient source is:

- `data/03_Optimisation/inputs/assets/steel/S3/s3_provisional_dev_input/s3_wag_selected_dev_inputs.csv`

The loader accepts only rows that are development-only, accepted for development use, eligible for the S3.0b loader, non-thesis-usable, and not sourced from locator-incomplete `STEEL-SC-0019`.

The loader does not read:

- `s3_wag_dev_input_selection_review.csv`;
- source-card registers;
- approved-input shells;
- generated run folders.

The fixed-profile loader requires UTC timestamps, timestep hours, activity or demand identifiers, activity values and units, source-stage metadata, source artifact provenance, review status, and `thesis_usability=false`.

## Calculation Hierarchy

The only implemented hierarchy is:

1. mandatory carrier-specific process or self-use;
2. shared steam or boiler useful-energy demand;
3. WAG-to-power potential net-import offset;
4. flare, spill, or unused residual.

Shared allocation stages use proportional allocation across eligible residual WAG carrier energy. There is no price signal, no optimisation of carrier choice, and no hierarchy sensitivity.

## Emissions Treatment

The scaffold applies the physical-site point-of-oxidation ledger:

- no emissions are counted at WAG generation;
- WAG emissions are counted once at process use, boiler use, power-interface use, or flare/spill;
- carrier-specific factors are used for BFG, COG, and BOFG/LDG;
- natural-gas emissions remain separate;
- captured CO2 remains a separate reporting flow;
- complete site-emissions and gross ETS cost eligibility remain false unless non-WAG residual process-emissions inputs are supplied later.

## Readiness Flags

The readiness assessment reports:

- `profile_schema_ready`;
- `selected_input_loader_ready`;
- `bfg_generation_ready`;
- `bofg_generation_ready`;
- `cog_generation_ready`;
- `mandatory_process_use_ready`;
- `steam_boiler_allocation_ready`;
- `power_import_offset_ready`;
- `emissions_ready`;
- `full_diagnostic_ready`.

Each blocked flag reports missing inputs, the blocking reason, whether the code scaffold exists, and whether the blocker is numerical evidence, profile availability, or scope policy.

## Current Runtime Blockers

Current canonical inputs make the scaffold implementation-ready but not full-runtime-ready.

The current blockers are:

- missing COG-chain coke rate per tonne hot metal;
- missing dry-coal input per tonne coke;
- missing C0 on-site coking share;
- missing C1 retained on-site coking share;
- missing mandatory COG self or process-use coefficient;
- missing mandatory carrier-specific process-use profile;
- missing throughput-coupled steam or boiler demand profile;
- missing site electricity demand profile for the import-offset cap.

The selected boiler efficiency is available for development-only sensitivity, but it does not create a steam or boiler demand profile.

## Validation Coverage

Synthetic tests cover:

- provisional selected-input loading and rejection of review surfaces;
- rejection of thesis-usable, approved, blocked-source, duplicate-key, missing-unit, and missing-value rows;
- fixed-profile provenance checks and generated-run rejection;
- BFG and BOFG hand calculations;
- COG-chain calculation and missing-input blocking;
- process-first allocation, proportional shared allocation, balance closure, no export, and no revenue;
- point-of-oxidation emissions, flare emissions, no generation emissions, and gross-ETS blocking;
- current scaffold-only readiness;
- validation-only CLI execution with a temporary selected-input fixture.

## Interpretation

Code completeness does not imply plant-diagnostic readiness. The scaffold can validate and calculate when supplied with explicit governed activity and demand profiles, but the current canonical data packet lacks mandatory runtime inputs. Any run before those inputs exist is a scaffold validation, not a meaningful plant diagnostic.
