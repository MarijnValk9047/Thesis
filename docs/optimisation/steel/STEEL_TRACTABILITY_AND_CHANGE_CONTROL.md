# Steel Tractability And Change Control

## Purpose

This document freezes the tractability and change-control rules for future steel implementation work.

It exists to stop complexity growth from outrunning explanation, validation, and thesis usability.

## Start-Small Rules

Default escalation order:

1. one day before one week;
2. hourly before quarter-hour;
3. deterministic before stochastic;
4. `DA_only` before `mFRR`;
5. continuous LP before binaries;
6. `S2` before `S3`;
7. `S3` before `S4` and beyond.

If a smaller case is not explainable, do not expand to a larger case.

## Methodological Vs Engineering Changes

### Engineering Changes

Engineering changes improve mechanics without changing the mathematical question.

Examples:

- caching;
- profiling;
- benchmark reuse;
- skipping completed runs;
- minimal outputs;
- logging cleanup;
- report-generation ergonomics.

These do not change thesis claims by themselves.

### Methodological Changes

Methodological changes alter the question, the physics, or the comparison logic.

Examples:

- scenario reduction;
- looser MIP gap used to change results;
- reduced bid grid;
- relaxed binaries;
- shortened horizon;
- changed production policy;
- changed non-anticipativity;
- changed tariff or carbon policy;
- changed market scope;
- changed granularity;
- changed reserve logic;
- changed risk treatment.

These require explicit labelling and documentation.

## Methodological Change Control

Any methodological change must be:

- declared explicitly in the run metadata;
- disclosed in thesis-facing reporting;
- cross-checked against `STEEL_IMPLEMENTATION_FREEZE_V1.md`;
- reflected in the relevant assumption and policy docs if it changes the frozen plan.

Silent methodological change is not acceptable.

## Model-Size Escalation Limits

Escalate model size only after the previous size has:

- stable solver status;
- explainable outputs;
- acceptable runtimes;
- useful diagnostics when failing.

Typical escalation path:

- one configuration before multiple configurations;
- few periods before many periods;
- few scenarios before many scenarios;
- no binaries before binaries where possible.

## When To Stop And Diagnose

Stop adding complexity and diagnose instead when:

- balances fail at small scale;
- runtime explodes before behaviour is understood;
- infeasibility cannot be classified;
- reserve or market layers appear to create value that cannot be traced physically;
- changing two or more major axes at once would make interpretation ambiguous.

## Big-M Rule

Do not use loose `Big_M` values unless justified explicitly.

If a `Big_M` is required later:

- document the derivation;
- document the unit basis;
- show why a tighter bound was not available.

## Output And Run-Folder Requirements

Every meaningful future run must satisfy the repository run-folder contract.

Minimum expectations:

- resolved configuration;
- input manifest;
- solver settings;
- model-size metrics;
- solver log;
- solution outputs;
- metrics summary;
- run-level README with limitations and warnings.

## Required Diagnostic Minimum

Every meaningful run must record:

- solver status;
- objective value;
- runtime;
- MIP gap if applicable;
- variable count;
- binary count;
- constraint count;
- infeasibility diagnostics if failed.

## Allowed Engineering Improvements

Allowed without changing the methodological claim:

- caching and memoisation;
- profiling and performance instrumentation;
- skip-completed-run logic;
- benchmark reuse where the benchmark definition is unchanged;
- minimal-output mode when lineage and diagnostics remain adequate;
- internal refactoring that preserves behaviour.

## Methodological Changes Requiring Explicit Label

The following always require explicit label:

- scenario reduction;
- looser MIP gap used for reported results;
- relaxed binaries;
- reduced bid grid;
- shortened horizon;
- changed production policy;
- changed non-anticipativity;
- changed tariff policy;
- changed carbon policy;
- changed reserve policy;
- changed risk treatment;
- changed granularity or horizon in a comparison study.

## Stop Condition Before Complexity Increase

Do not increase complexity if:

- the current stage is not yet thesis-reportable;
- diagnostics are missing;
- assumptions are drifting;
- proxy values are being mistaken for approved inputs;
- the run contract is not being met.
