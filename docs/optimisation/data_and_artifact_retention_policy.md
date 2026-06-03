# Data And Artifact Retention Policy

## Purpose

This file records the repository's current retention policy so cleanup does not erase thesis lineage or confuse source-level progress with generated output.

It is a policy document, not a deletion instruction.

## 1. Keep In Git

The following belong in Git by default:

- source code;
- reusable configs;
- tests;
- compact methodology docs;
- governance and run-contract docs;
- selected-week policy and registry artifacts that act as stable reference material;
- compact audit summaries that preserve an important thesis decision, blocker, or methodology note.

In this repository, that includes the canonical path:

- cleaning pipelines;
- standard hourly forecasting package;
- quarter-hour canonical code and docs;
- scenario-generation source and compact audit docs;
- hydrogen optimisation code/config/tests;
- command-centre governance docs.

## 2. Keep Outside Git

Large generated artifacts should stay outside Git, even if they are valuable locally.

Typical examples:

- run folders;
- solver logs;
- parquet outputs;
- figure directories;
- large CSV result tables;
- export bundles;
- notebook artifact dumps;
- scenario-evaluation run outputs.

These are useful for local recovery and evidence, but they are not Git-first artifacts.

## 3. Summarise Important Attempts Before Cleanup

Some branches are not the canonical current path but still matter methodologically. These should be summarised before their scattered artifacts are ignored or archived.

Current examples:

- May 2026 forecasting campaign;
- Lago / LEAR Strict branch;
- quarter-hour phase workflow;
- scenario calibration and undercoverage audits;
- hydrogen support/readiness diagnostics;
- CVaR validation and anomaly work.

The repository should preserve the lesson of those branches even if it does not keep every generated artifact in Git.

## 4. `data/01_cleaned/` Is A Separate Policy Problem

Tracked cleaned-data modifications must not be treated as ordinary untracked cleanup.

Reason:

`data/01_cleaned/` currently mixes:

- baseline input candidates;
- generated derivatives;
- diagnostics;
- possible accidental regeneration churn.

That tree requires a separate tracked-data review policy before any destructive cleanup is even considered.

## 5. Root-Level Report Cluster

The repository still contains root-level reports and support diagnostics that carry unique thesis knowledge.

Policy:

- compact markdown reports should be promoted or summarised into stable docs before they are treated as cleanup candidates;
- machine-readable support tables and next-action JSONs are not Git-first artifacts unless they are the only record of a still-active decision trail.

## 6. `workspace_triage/` Is Local, Not Thesis-Final Evidence

`workspace_triage/` is useful for local cleanup planning and audit history, but it is not the long-term thesis documentation surface.

Policy:

- keep it local and ignored;
- promote durable conclusions from triage into stable docs under `docs/`;
- do not rely on `workspace_triage/` as the only place where repository intent is recorded.

## 7. Visual Policy Placement

The visual reporting policy is currently active at:

- `VISUALISATION.md`

Long-term, it may be relocated or duplicated under `docs/optimisation/`, but it should not be removed until the central governance doc layer is fully settled.

## 8. Cleanup Principle

The cleanup goal in this repository is not "remove junk quickly".

The goal is:

- preserve the red line of the thesis;
- keep code/config/docs/test surfaces understandable;
- keep generated bulk out of Git;
- keep methodologically important historical attempts discoverable through stable summaries.
