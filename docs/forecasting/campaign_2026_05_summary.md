# May 2026 Forecasting Campaign Summary

## Purpose

This document summarises the bounded forecasting and audit work grouped under the May 2026 campaign bundle.

It is not the canonical forecasting runner surface. It records why this campaign still matters methodologically even though many of its scripts were intentionally separated from the top-level canonical runners.

This summary is based on the existing repository docs, runner classification, and compact audit reports. It does not claim full rerun inspection of every campaign artifact.

## What The Campaign Covered

The campaign appears to have concentrated several related tasks:

- Lago-style six-year benchmark work;
- LEAR Strict support and quarter-hour anchor export work;
- D-only versus `D_plus_4` applicability checks;
- scenario calibration and coverage diagnostics;
- forecasting support/routing audits that later affected optimisation readiness.

The source bundle currently lives under:

- `scripts/Data/02_Forecasting/01_DA_prices/one_off/2026-05_campaign/`

The bundle README explicitly frames it as an organisational grouping for bounded experiments and audits rather than the canonical runner surface.

## Why This Campaign Matters

### 1. It explains why some scripts left the canonical top-level surface

The campaign bundle is not merely a dump of leftovers. It reflects a repo discipline decision:

- canonical hourly and quarter-hour deterministic runners stay in the main forecasting surface;
- bounded experiments and audits move into a named one-off bundle instead of cluttering the active runner set.

### 2. It preserves the Lago / LEAR Strict branch

The campaign contains the main staging area for:

- Lago benchmark import and cleaning helpers;
- LEAR Strict-related benchmark and export logic;
- associated diagnostics around support and routing.

This matters because LEAR Strict became important for later quarter-hour and optimisation support work, even though it is not the canonical default forecasting path.

### 3. It documents D+4 and support questions

The campaign includes D+4 applicability and support-related checks. Even where those checks are not now the active default path, they remain part of the methodological record for:

- what was considered;
- what was found to be limited or non-default;
- why the current hardened optimisation path remains hourly, `D_only`, and selected-week based.

### 4. It captures scenario calibration and undercoverage work

The campaign includes the hourly scenario calibration and tail-diagnostic branch that now underpins the repository's cautious stance on scenario quality.

That matters because later optimisation interpretation depends on this point:

- stochastic inputs exist and are usable;
- they are still caveated for final robust-risk claims.

### 5. It explains quarter-hour anchor and routing work

The campaign is closely connected to the compact root-level reports around:

- LEAR Strict quarter-hour anchor feasibility;
- backbone routing;
- support mismatches;
- input extension and residual-coverage diagnosis.

Those audits helped explain why quarter-hour comparability and support became important beyond standard point-forecast accuracy reporting.

## Relationship To The Canonical Forecasting Path

The campaign is not the canonical current path.

The canonical current path still runs through:

- the standard hourly DA package;
- canonical hourly runners;
- quarter-hour canonical observed/counterfactual split;
- compact scenario-quality docs;
- later hydrogen optimisation integration.

The campaign should instead be treated as:

- a bounded methodological branch;
- an audit and comparison layer;
- a historical explanation for later repository decisions.

## Cleanup And Retention Implication

This campaign should not be treated as junk automatically.

What should be preserved:

- the campaign README;
- the existence of the campaign source bundle;
- compact markdown summaries that explain what the branch discovered;
- the connection between LEAR Strict / Lago / scenario diagnostics and later optimisation support questions.

What should not be kept in Git by default:

- large run folders;
- staged export/output trees;
- generated result tables that are only local support material.

## Recommended Interpretation

When future work encounters this branch, the correct reading is:

- these scripts are not random one-offs;
- they are the recorded audit/comparison campaign that explains several later forecasting and optimisation governance choices;
- the source-level branch should remain understandable even if most generated outputs stay outside Git.
