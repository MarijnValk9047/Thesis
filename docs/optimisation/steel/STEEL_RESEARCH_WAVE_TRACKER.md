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
| `Wave E` | Financial, policy, tariff, infrastructure, and market-parameter evidence | `complete` | Financial parameters, ETS/free allocation policy, network-tariff proxies, infrastructure flags, product-value policy, and stage-sequencing governance | Wave E source cards; candidate tables; model-policy and roadmap updates | `yes` |

## Current Handoff

- `Wave A` is complete and covers parameter categories.
- `Wave B` is complete and covers public topology and validation targets.
- `Wave C` is complete and covers generic technology ranges, annual-to-hourly translation methodology, and S2 validation-check definitions.
- `Wave D` is complete as candidate evidence and covers WAG carriers, internal-energy topology, valuation hierarchy, first emissions-accounting architecture, and S3 validation definitions.
- `Wave E` is complete as candidate evidence and covers financial parameters, carbon policy structure, tariff proxies, infrastructure flags, product-value policy, and stage-sequencing policy.
- The next milestone is a cross-wave synthesis and an approved `S2` and `S3` implementation-scope decision before any Pyomo steel implementation starts.

## Guardrail

Do not skip from `Wave B` to steel MILP implementation without resolving the `Wave C` translation problem for the first approved baseline parameter set.

Do not skip from `Wave E` candidate evidence to steel code scaffolding without a cross-wave synthesis that freezes the approved `S2` and `S3` implementation scope.
