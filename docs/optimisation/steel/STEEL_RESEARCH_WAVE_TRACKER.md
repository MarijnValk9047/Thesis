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
| `Wave D` | Energy, cost, utility, and emissions evidence | `next` | WAGs, internal gas/steam/electricity treatment, energy valuation, emissions framing, and the energy-cost layer | future source cards and candidate tables | `no` |
| `Wave E` | Market, uncertainty, and later reserve extensions | `planned` | DA bidding evidence pack, stochastic/CVaR evidence pack, granularity/horizon interfaces, and only later reserve logic | future market and scenario governance docs | `no` |

## Current Handoff

- `Wave A` is complete and covers parameter categories.
- `Wave B` is complete and covers public topology and validation targets.
- `Wave C` is complete and covers generic technology ranges, annual-to-hourly translation methodology, and S2 validation-check definitions.
- The next required research step is `Wave D`, with emphasis on WAGs, internal utilities, energy valuation, emissions, and the energy-cost layer.

## Guardrail

Do not skip from `Wave B` to steel MILP implementation without resolving the `Wave C` translation problem for the first approved baseline parameter set.
