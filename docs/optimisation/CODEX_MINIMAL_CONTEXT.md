# Codex Minimal Context Workflow

## Purpose

This document keeps Codex work cheap, targeted, and reproducible. It expands the short always-on rules in `AGENTS.md`.

## Default workflow

1. Start with `AGENTS.md`.
2. Identify the smallest relevant document set.
3. Inspect by headings, targeted searches, short line ranges, counts, and compact diffs.
4. Change only the files needed for the user's requested scope.
5. Verify with the lightest check that proves the change.
6. Report only changed files, what changed, validation, and remaining risks.

## Context budget rules

- Prefer `rg`, file counts, headings, and short excerpts over full-file reads.
- Do not dump full markdowns, large logs, CSVs, solver output, generated reports, or run folders into chat.
- Do not inspect forecasting, hydrogen, steel S4, command-centre, run-output, or visualisation docs unless the task touches that area.
- If a task is documentation-only, do not inspect or edit model code, data, run outputs, or configs unless the user explicitly asks.
- If a task is implementation work, first inspect local patterns and the nearest tests before designing new structure.

## Dirty tree discipline

- Assume existing modifications belong to the user or another active workstream.
- Do not revert unrelated changes.
- If a file is already modified and the task requires editing it, make a narrow compatible edit.
- If unrelated dirty files appear in status, mention them only if they affect risk or acceptance.

## Generated-output discipline

Before running commands that create many files or large outputs, follow `docs/repository/CODEX_OUTPUT_CONTRACT.md`.

Default posture:

- `output_policy = minimal`;
- no root-level generated outputs;
- no full diagnostics without explicit approval;
- no generated data or run outputs committed unless explicitly classified as small thesis-critical provenance.
- preserve the canonical, historical, diagnostic, and generated-artifact distinctions in `docs/RESEARCH_LINEAGE.md`.

## Prompt-writing mode

When the user asks for a prompt or asks to turn an idea into a Codex task, write a compact execution prompt first.

Use this shape:

```text
Goal:

Minimal scope:

Read:

May modify:

Out of scope:

Output limit:

Validation / acceptance criteria:

Methodological warnings:
```

Do not convert such requests into broad repository work unless the user explicitly asks for immediate execution.

## Final response discipline

For repository edits, report:

- modified files only;
- what was moved, shortened, or changed;
- validation performed;
- risks or follow-up decisions.

Avoid narrating every inspected file when it did not affect the result.
