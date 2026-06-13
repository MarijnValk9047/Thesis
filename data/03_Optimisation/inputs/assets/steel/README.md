# Governed Steel Input Layer

## Purpose

This folder is the governed steel input layer for the optimisation workstream.

It is the place where steel asset inputs move from category discovery toward controlled model-use tables without hiding assumptions in code.

The folder currently contains scaffolding only. It does not yet contain approved steel model-input values.

## Folder Roles

### `parameter_universe.csv`

Category-level map of the steel parameter universe.

Use it to record:

- parameter families;
- modelling role;
- required phase;
- likely source tier;
- current value status;
- ownership and review state.

This is not an approved model-input table.

### `source_cards/`

Structured notes for stable sources only.

Use source cards to record what a source supports, what it does not support, and whether it may be used for model parameter promotion.

### Schema Files

Header-only schema placeholders define the intended column contracts for later approved tables such as:

- process units;
- carriers;
- stores;
- conversion factors;
- emissions factors;
- costs;
- configurations;
- validation targets.

These schema files are not model inputs by themselves.

### Candidate Registers

Candidate registers are the working layer between source cards and approved inputs.

They may contain:

- candidate values;
- ranges;
- confidence;
- caveats;
- sensitivity-only entries.

They must remain separate from approved tables.

### Approved Model Input Tables

Approved model input tables are the only tables allowed to drive steel loaders and optimisation models directly.

They must be created only after review and explicit approval.

## Current Status

Current contents are limited to:

- governance README files;
- source-card contract materials;
- category-level parameter-universe scaffold;
- header-only schema placeholders.

No approved values are present in this folder.
