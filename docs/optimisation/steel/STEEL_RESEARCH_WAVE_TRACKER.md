# Steel Research Wave Tracker

## Purpose

Track the staged evidence-building waves for the steel workstream before model implementation starts.

This file is a governance tracker, not a modelling artifact.

## Waves

| Wave | Focus | Status | Expected output | Repo handoff | Incorporated |
|---|---|---|---|---|---|
| `Wave A` | Steel MILP parameter categories | `complete` | Category map of parameter families, modelling roles, and governance rules | `STEEL_PARAMETER_UNIVERSE.md`; `parameter_universe.csv` scaffold | `yes` |
| `Wave B` | Public Tata IJmuiden topology and validation targets | `complete` | Stable source cards, topology candidate rows, validation-target candidates, public parameter candidates, and configuration flags | `source_cards/`; candidate CSVs; assumption-register updates | `yes` |
| `Wave C` | Technology ranges and annual-to-hourly translation | `complete` | Defensible generic technology ranges, route-conversion candidate families, DRI hot/cold split treatment, annual-to-hourly methodology, and S2 validation-check definitions | Wave C source cards; candidate tables; methodology doc updates | `yes` |
| `Wave D` | Energy, cost, utility, and emissions evidence | `complete` | WAGs, internal gas/steam/electricity treatment, energy valuation, emissions framing, and the energy-cost layer | Wave D source cards; WAG/emissions candidate tables; S3 validation and assumption updates | `yes` |
| `Wave E` | Market, uncertainty, and later reserve extensions | `next` | Financial parameters, ETS/free allocation, network tariffs, connection capacity, steel or product value, market settlement, and only later reserve logic | future market and policy governance docs | `no` |

## Current Handoff

- `Wave A` is complete and covers parameter categories.
- `Wave B` is complete and covers public topology and validation targets.
- `Wave C` is complete and covers generic technology ranges, annual-to-hourly translation methodology, and S2 validation-check definitions.
- `Wave D` is complete as candidate evidence and covers WAG carriers, internal-energy topology, valuation hierarchy, first emissions-accounting architecture, and S3 validation definitions.
- The next required research step is `Wave E`, with emphasis on financial parameters, ETS/free allocation detail, network tariffs, connection capacity, steel-value framing, market settlement, and only later reserve interfaces.

## Guardrail

Do not skip from `Wave B` to steel MILP implementation without resolving the `Wave C` translation problem for the first approved baseline parameter set.
