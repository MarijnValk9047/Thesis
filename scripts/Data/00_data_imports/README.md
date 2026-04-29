# ENTSO-E Data Imports

Use `API_GETS.py` as the single runner for ENTSO-E downloads.

## Current dataset

- key: `17_1_bc_nl_ir`
- description: ENTSO-E 17.1 B&C for NL control area
- default years: 2022-2025 (inclusive)

## Day-ahead price import note

The hourly day-ahead A01 price datasets for `NL`, `BE`, and `DE` now default to `2021-2025`.

Relevant dataset keys:
- `12_1_d_energy_prices_a01_day_ahead_nl`
- `12_1_d_energy_prices_a01_day_ahead_be`
- `12_1_d_energy_prices_a01_day_ahead_de`

## Available dataset keys

- `17_1_bc_nl_ir`
- `12_3_bc_nl_ir`
- `12_3_f_nl_ir`
- `12_3_e_nl_ir_a47`
- `12_3_e_nl_ir_a60`
- `12_3_e_nl_ir_a61`
- `12_3_e_de_mari_mfrrsa`
- `12_3_e_de_mari_mfrrda`
- `17_1_f_de_a16_realised`
- `17_1_f_nl_a16_realised`

## Run

```powershell
.venv\Scripts\python.exe scripts/Data/00_data_imports/API_GETS.py --dataset 17_1_bc_nl_ir
```

This writes raw API responses into:

`data/00_Raw/ENTSOE/17_1_BC_NL_IR/`

Depending on ENTSO-E response size, files can be `.xml` or `.zip`.

Notes:
- first page should use `offset=0` (not `100`)
- auth parameter is `securityToken` (not `security_Token`)

## Add another dataset

1. Open `scripts/Data/00_data_imports/API_GETS.py`.
2. Add a new entry in `DATASETS`.
3. Keep shared logic in this file; only dataset params should differ.
4. Run with `--dataset <new_key>`.

## Why one runner is recommended

- avoids copy/paste bugs across multiple scripts
- keeps API key handling in one place (`ENTSOE_KEY` in `.env`)
- standardizes filenames and folders for traceability
