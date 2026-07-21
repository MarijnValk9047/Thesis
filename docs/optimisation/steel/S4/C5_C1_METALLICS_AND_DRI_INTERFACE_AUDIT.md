# C5 C1 metallics and DRI-interface audit

## Purpose

This diagnostic answers two structural questions before a capacity or anchor
sensitivity is changed:

1. Are BOF and EAF scrap inputs one combined quantity or two distinct streams?
2. Does the existing DRP-to-EAF DRI buffer exist and close its material balance?

It is an audit only. It does not change a capacity, activate scrap in the
optimiser, alter source cards, or use a residual as a supply.

## Source-backed findings

The official Heracless C1 material table distinguishes converter/BOF scrap from
EAF scrap. The rounded annual public values are 1.0 Mt/y BOF scrap and
0.9--1.8 Mt/y EAF scrap, which sum to the stated 1.9--2.8 Mt/y site envelope.
The lower site total is also consistent with approximately 1.3 Mt/y external
scrap plus 0.6 Mt/y internal reuse. These are separate demand streams, not a
licence to create a single free 2-Mt/y scrap pool. The relevant source-card
locators are [BOF_OSF_Parameters.md](../../../data/03_Optimisation/inputs/assets/steel/source_cards/BOF_OSF_Parameters.md)
and [EAF_Parameters.md](../../../data/03_Optimisation/inputs/assets/steel/source_cards/EAF_Parameters.md).

The C1 source cards give a BOF candidate recipe of 0.824 t hot metal and
0.294 t scrap per t liquid steel, and an EAF candidate recipe of 0.848 t HDRI
and about 0.303 t scrap per t liquid steel. The rounded C1 anchors reconcile:

```text
BOF: 3.4 Mt LS × 0.824 = 2.80 Mt hot metal
BOF: 3.4 Mt LS × 0.294 = 1.00 Mt scrap
EAF: 3.3 Mt LS × 0.848 = 2.80 Mt HDRI
EAF: 3.3 Mt LS × 0.303 ≈ 1.00 Mt scrap
```

This is evidence for separate BOF and EAF metallics, not proof that both use
the same scrap percentage. A common 20% BOF/EAF scrap claim attributed to
Athanasiadis is **not verified** in the current source cards. The current
legacy EAF `0.2 t scrap/t DRI` is a development assumption and must not be
presented as a confirmed common physical recipe without the exact thesis
locator.

## Existing DRI/sponge-iron buffer

The model already contains a finite `dri_inventory[t]` with:

```text
inventory[t] = inventory[t-1] + DRP_DRI_output[t] - EAF_DRI_input[t]
inventory[t] <= capacity
inventory[end] = inventory[start]
```

The audit forces DRP at its existing upper rate, forces EAF DRI input to zero
in the first hour and to its existing maximum in the next hour, then solves
the remaining 24-hour schedule. A successful result proves that the current
generic buffer can store, release, respect its capacity, and return to its
initial inventory. It does **not** create a new buffer or imply unlimited DRI
flexibility.

The current builder uses a generic 17.76-kt DRI store with zero initial
inventory. The source-card policy instead describes HDRI direct transfer plus
CDRI storage, a two-day development capacity of about 15.35 kt, a 50%
initial-inventory policy, and terminal equality. Both capacities are
development proxies rather than a published Tata silo measurement; the
difference must be reconciled before a buffer sensitivity. The public MER
confirms CDRI silos but not a numerical silo capacity. Therefore the current buffer is adequate for
deterministic material feasibility, but not for claims about HDRI temperature,
CDRI cooling/reoxidation, or an exact Tata silo capacity.

## What can still distort C1 capacity results

| Priority | Factor | Why it can mislead |
|---|---|---|
| P0 | BOF named metallics | Current retained route maps hot metal directly to BOF steel and does not yet use the separate BOF scrap recipe. |
| P0 | Site scrap supply ledger | Separate BOF/EAF demands may double count external/internal scrap unless their supply categories are explicitly bounded. |
| P0 | EAF capacity basis | Model EAF capacity is DRI-input/h; MER design data use liquid-steel output/h. They cannot be compared without the material recipe. |
| P1 | DRP annual anchor vs hourly upper bound | The 2.8 Mt/y anchor is annual output; annualising an operational maximum assumes 100% availability. |
| P1 | Generic vs physical DRI buffer | HDRI-direct and CDRI-silo states are not separated; the initial inventory policy is not yet active. |
| P1 | DRI-buffer provenance | The active 17.76-kt development capacity differs from the 15.35-kt two-day source-card candidate. |
| P1 | Downstream/slab boundary | Final-product capacity can bind through HSM/DSP yields and bounded imported slab rather than upstream steelmaking. |

## Decision

- **GO:** retain the existing generic DRI buffer and terminal equality in
  deterministic feasibility checks.
- **GO:** treat BOF and EAF scrap as separate source-backed demand streams.
- **NO-GO:** activate either as an unbounded or pooled scrap supply.
- **NO-GO:** change DRP/EAF/BF capacity from this audit alone.
- **Next physical gate:** build a named BOF/EAF scrap supply ledger and apply
  the source-backed BOF metallics balance, then rerun the bounded capacity
  probe and compare the capacity basis before changing any source ceiling.
