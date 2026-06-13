# Steel Research Wave Tracker

## Purpose

Track the staged evidence-building waves for the steel workstream before model implementation starts.

This file is a governance tracker, not a modelling artifact.

## Waves

| Wave | Focus | Status | Expected output | Repo handoff | Incorporated |
|---|---|---|---|---|---|
| `Wave A` | Steel MILP parameter categories | `complete` | Category map of parameter families, modelling roles, and governance rules | `STEEL_PARAMETER_UNIVERSE.md`; `parameter_universe.csv` scaffold | `yes` |
| `Wave B` | Public Tata IJmuiden topology and validation targets | `complete` | Stable source cards, topology candidate rows, validation-target candidates, public parameter candidates, and configuration flags | `source_cards/`; candidate CSVs; assumption-register updates | `yes` |
| `Wave C` | Technology ranges and annual-to-hourly translation | `next` | Defensible aggregate yields, route-conversion ranges, DRI hot/cold split treatment, and annual-to-hourly methodology | future candidate tables and methodology notes | `no` |
| `Wave D` | Energy, cost, utility, and emissions evidence | `planned` | Utility layer evidence, WAG treatment, purchased power, ETS framing, CCS/H2 cases, and internal valuation rules | future source cards and candidate tables | `no` |
| `Wave E` | Market, uncertainty, and later reserve extensions | `planned` | DA bidding evidence pack, stochastic/CVaR evidence pack, granularity/horizon interfaces, and only later reserve logic | future market and scenario governance docs | `no` |

## Current Handoff

- `Wave A` is complete and covers parameter categories.
- `Wave B` is complete and covers public topology and validation targets.
- The next required research step is `Wave C`, with emphasis on technology ranges and annual-to-hourly translation without inventing hourly plant truth.

## Guardrail

Do not skip from `Wave B` to steel MILP implementation without resolving the `Wave C` translation problem for the first approved baseline parameter set.
