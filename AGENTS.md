# AGENTS.md

## Codex Credit Discipline

Work in minimal-context mode by default.

- Read this file first. Read other project docs only when they are directly relevant to the task.
- Use compact inspections: headings, targeted searches, short line ranges, counts, and diffs.
- Do not paste full files, large logs, generated tables, or broad directory dumps into chat.
- Keep task scope narrow. Do not turn a small request into a repository-wide audit unless asked.
- For documentation-only tasks, modify only documentation/instruction files.
- Before creating generated outputs or running large pipelines, read `docs/repository/CODEX_OUTPUT_CONTRACT.md` and report the expected output root, approximate size, output policy, run class, and lineage role.
- Preserve the canonical, historical, diagnostic, and generated-artifact distinctions in `docs/RESEARCH_LINEAGE.md`.
- Preserve user work in a dirty tree. Do not revert, delete, regenerate, or reformat unrelated changes.

For more detail on this working style, read `docs/optimisation/CODEX_MINIMAL_CONTEXT.md`.

## Prompt Behaviour

When the user asks for "een prompt", "maak hier een opdracht van", "schrijf een Codex-prompt", or similar, default to writing a compact execution prompt first instead of immediately doing broad work.

That prompt should include:

- goal;
- minimal scope;
- files to read;
- files to modify, if any;
- explicitly out of scope;
- output limit;
- validation or acceptance criteria;
- methodological warnings, if relevant.

Use short task briefings, not new all-encompassing master prompts. If the requested task is broad, first narrow it into a usable prompt. Execute only when the assignment is concrete enough or when the user explicitly asks for direct execution.

## Active Project Priority

The active thesis implementation path is the C0/C1 Tata Steel IJmuiden-inspired steel physical model.

Current priority:

1. S1: rolling-horizon deterministic steel production feasibility.
2. S2: deterministic energy-cost optimisation only after S1 is physically feasible and reportable.
3. S3: DA bidding, stochastic scenarios, CVaR, and later mFRR only after S1/S2 are stable.

Do not add DA, mFRR, stochasticity, CVaR, product revenue, ETS costs, or annual whole-site claims before the rolling deterministic steel model closes production, material, WAG, steam, utility, and residual reporting checks.

Hydrogen remains a historical methodological reference for rolling-deadline quota logic, run reporting, benchmarks, and later market experiments. It is not the active implementation priority and is not a prerequisite for continuing deterministic steel work.

Read the full active scope only when needed:

- `docs/optimisation/steel/S4/C5_MODEL_STATE_AND_DETERMINISTIC_OPTIMISATION_ROADMAP.md` (read first for any C5 task; it is the single active C5 status, handoff, baseline, and next-gate document)
- `docs/optimisation/STEEL_OPTIMISATION_SCOPE.md`
- `docs/optimisation/PROJECT_DECISIONS.md`
- `docs/optimisation/steel/S4/C5_ROLLING_PRODUCTION_FEASIBILITY_OPTIMISER.md`

## Always-On Methodological Rules

- Preserve the sequence: physical feasibility before costs, costs before DA markets, DA before stochastic/CVaR, DA before mFRR.
- Keep BFG, COG, and BOFG as separate physical carriers where the data preserve them. Aggregate WAG is reporting only; mixed gas and Wobbe-quality modelling are out of scope unless explicitly reopened.
- Use eligible WAG before named, explicitly permitted NG backup. Never invent a plant-level WAG/NG split.
- Report electricity and NG residuals. Do not hide them as plugs, calibration variables, costs, or allocations.
- Keep WAG-explicit combustion CO2 separate from aggregate process-counter CO2. Do not claim ETS-ready or whole-site Scope 1 totals from the partial steel boundary.
- For active C0 work, use quota-driven availability and the component ontology. Static fixed C0 hour calendars are historical diagnostics only; do not reuse them as operating policy. Source-classified C0 continuous assets remain on with endogenous bounded, unfixed throughput in the active builder. Gates 1-4, the final pre-economics boundary closure and the fixed-reference represented-procurement-cost path pass. The zero-import C1 case remains a labelled stresscase. The cost baseline `steel_s2_fixed_reference_deterministic_cost_v3_20260716` is retained, but its repeated-first-block +0.5% execution bias is superseded by the cumulative production-progress state. The active rolling response hierarchy is now physical production progress, represented procurement cost, then the non-economic tie-break; cost-first ordering is superseded because it accumulated 343-528 t of C1 credit and broke later rolling feasibility. The bounded VN25 development response remains a 0-to-350-MW upper-bound abstraction with omitted, not invented, minimum-load/start/ramp/outage/CHP features; IJ01 remains non-price-responsive. The governed LEAR/Lago D-D+4 response lineage `steel_s2_deterministic_price_response_anchor_diagnostics_v1_20260720` passes with decision `price_response_valid_anchor_coverage_partial`: 444/444 models are optimal over 4,321 actual timestamp hours, flat parity, identical-state y_pred dominance, oracle regret and all physical guardrails pass, but coverage is `partial_year_not_annual` and neither primary-comparable generator anchor is below 7.5%. This is not `DAM_ready`; only governed deterministic response interpretation is next. Bidding, settlement, revenue, ETS, stochasticity, CVaR and mFRR remain unauthorised. Residual electricity/NG remain reporting-only and excluded from dispatch and cost.
- Use validation-based selection for models, scenarios, and future CVaR settings. Never tune on the final test set.
- Preserve information timing and non-anticipativity: no realised future prices or future states may drive earlier decisions.
- Perfect foresight is an upper-bound benchmark only. Price-insensitive behaviour remains a required benchmark once markets return to scope.
- Scenario probabilities are required for stochastic optimisation and CVaR interpretation.
- If a methodological decision changes, update `docs/optimisation/PROJECT_DECISIONS.md`.

Detailed forecasting, scenario, metric, benchmark, and red-flag rules live in:

- `docs/optimisation/METHODOLOGICAL_GUARDRAILS.md`
- `docs/optimisation/result_table_definitions.md`
- `docs/optimisation/model_equations.md`

## Technical Defaults

- Use Python, Pyomo, and Gurobi for optimisation work.
- Use `scripts/Data/04_Steel_Test_Case/configs/steel_quota_driven_physical_feasibility.yaml` for active S1 C0/C1 feasibility work. `steel_rolling_feasibility.yaml` is a historical fixed-schedule diagnostic config.
- Set `GRB_LICENSE_FILE` from configured local licence paths only at runtime. Never commit licence contents, WLS keys, API keys, or secrets.
- Prefer existing repo patterns, configs, and shared modules over duplicated scripts or hardcoded experiment settings.
- Keep units explicit in models, reports, and constraints.
- Report solver status, objective value, solve time, MIP gap, variable count, binary count, constraint count, and infeasibility diagnostics when a solve fails.

The deterministic steel rolling-feasibility runner is deliberately outside the hydrogen market command centre until DA bidding is in scope. If a task touches command-centre market backends or supported options, read `docs/optimisation/RUN_COMMAND_CENTRE_GUIDE.md` and update `scripts/Data/03_Hydrogen_Test_Case/configs/optimisation_supported_options.yaml`, the guide, validation/doctor checks, tests, and run-contract docs as required.

## Output And Reporting

- Use `output_policy = minimal` unless the user asks for audit/full diagnostics or thesis-ready generated artifacts.
- No root-level generated outputs.
- Do not put generated data or run outputs in Git unless they are explicitly classified as small thesis-critical provenance.
- Every meaningful optimisation run should be reproducible from its run folder, config snapshot, input manifest/fingerprints, solver settings, solver log policy, dispatch/settlement outputs where applicable, metrics, warnings, and README.
- For plots, tables, notebooks, reports, or thesis visuals, read `docs/optimisation/VISUALISATION.md` before creating new recurring visual types.
- For run-folder and artifact expectations, read `docs/optimisation/OPTIMISATION_RUN_CONTRACT.md` and `docs/repository/CODEX_OUTPUT_CONTRACT.md`.

## Code And Documentation Style

- Inspect existing files before creating new ones.
- Do not create another general C5 model-state, handoff, canonical-baseline, or roadmap document. Update `C5_MODEL_STATE_AND_DETERMINISTIC_OPTIMISATION_ROADMAP.md` instead.
- Put reusable logic in shared modules; keep notebooks focused on interpretation.
- Keep functions small and named by modelling role.
- Avoid unused imports and uncontrolled script copies.
- Archive or document outdated artifacts instead of deleting blindly.
- Write beginner-friendly but methodologically strict documentation.
- When writing implementation plans, include goal, files to inspect, files to modify, assumptions, equations or pseudocode where useful, required outputs, validation checks, methodological warnings, and acceptance criteria.
