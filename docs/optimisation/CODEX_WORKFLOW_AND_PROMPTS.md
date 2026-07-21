# Codex Workflow And Prompt Use

## Purpose

This document summarises the new working method for Codex tasks in this repository. It is meant as a short guide for writing prompts and keeping future work focused, cheap, and methodologically safe.

Use this alongside:

- `AGENTS.md` for always-on repository instructions;
- `docs/optimisation/CODEX_MINIMAL_CONTEXT.md` for detailed minimal-context discipline;
- `docs/optimisation/STEEL_OPTIMISATION_SCOPE.md` for the active steel optimisation scope.

## New working method

Codex should work in minimal-context mode by default.

That means:

- read `AGENTS.md` first;
- read only the extra files that are directly relevant to the task;
- use compact inspections such as headings, targeted searches, short excerpts, counts, and diffs;
- avoid broad repository discovery unless the task explicitly requires it;
- keep the task scope narrow;
- avoid printing long file contents, logs, generated tables, or large directory listings in chat;
- modify only the requested type of file;
- leave unrelated dirty-tree changes untouched.

The active thesis priority remains:

1. S1 rolling deterministic steel production feasibility;
2. S2 deterministic energy-cost optimisation only after S1 is physically feasible and reportable;
3. S3 DA, stochastic/CVaR, and mFRR only after S1/S2 are stable.

Hydrogen is historical reference only. It should not dominate new prompts unless the task is explicitly about the historical hydrogen workstream.

## How prompts should be used

Prompts should be short task briefings, not new master instructions.

A good prompt tells Codex:

- what the goal is;
- what the smallest useful scope is;
- which files to read first;
- which files may be modified;
- what is explicitly out of scope;
- what output limit to respect;
- which checks or acceptance criteria matter;
- which methodological warnings apply.

Do not paste the old broad project context into every new prompt. The repository instructions now carry the stable context. Add only the task-specific context that Codex cannot infer from `AGENTS.md` and the named files.

## When asking for a prompt

If the request is "write a prompt", "turn this into a Codex task", or similar, Codex should first produce a compact execution prompt. It should not immediately start a broad implementation unless direct execution is explicitly requested.

For broad or uncertain tasks, the prompt should narrow the work before execution.

## Recommended prompt shape

```text
Goal:
<One or two sentences describing the intended result.>

Minimal scope:
<What Codex should do, and how far it should go.>

Read first:
- AGENTS.md
- <specific relevant docs or files>

May modify:
- <specific files or file families>

Out of scope:
- <things Codex must not touch>

Output limit:
<For example: compact final answer only; no long logs; no full file dumps.>

Validation / acceptance criteria:
- <checks to run or evidence to report>

Methodological warnings:
- <only warnings relevant to this task>
```

## Examples of good prompt boundaries

For a documentation-only task:

- allow only markdown instruction/documentation files;
- forbid model code, data, run outputs, and configs;
- ask for a compact diff or summary;
- require a final answer listing changed files and risks.

For a steel S1 diagnostic task:

- state that active priority is rolling deterministic steel feasibility;
- name the specific S4 docs and compact outputs to inspect;
- forbid DA, stochasticity, CVaR, mFRR, product revenue, ETS, and coefficient tuning;
- require residuals and comparability caveats to stay visible.

For a generated-output or run task:

- require `output_policy = minimal` unless audit/full output is explicitly approved;
- state expected output root, approximate size, run class, and lineage role before running;
- forbid root-level outputs and unclassified generated artifacts in Git.

## What to avoid

Avoid prompts that:

- restate the whole thesis history;
- include outdated hydrogen-first instructions for active steel work;
- ask Codex to inspect "everything relevant";
- mix documentation, implementation, run generation, and cleanup in one request;
- require many new artifacts before the diagnostic question is clear;
- specify detailed CSV schemas when a short design note would be enough;
- ask for high reasoning by default when the task is small.

## Final response expectations

For repository tasks, Codex should finish with:

- files changed;
- what changed;
- checks run;
- main risks or caveats;
- recommended next action, only when useful.

It should not include long logs, full tables, or repeated background context unless explicitly requested.
