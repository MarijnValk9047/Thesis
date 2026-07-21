# C5 C1 BOF/EAF metallics ledger

## Decision

The C1 capacity diagnostic may now use an **optional, bounded BOF/EAF
metallics ledger**. It replaces the old BOF proxy only in the diagnostic case:

```text
BOF liquid steel = BOF hot-metal input / 0.824
BOF scrap = 0.294 × BOF liquid steel

EAF liquid steel = HDRI input / 0.8484848485
EAF scrap = 0.3030303030 × EAF liquid steel

BOF scrap + EAF scrap <= bounded site scrap total
```

The BOF and EAF retain separate scrap variables and separate annual caps. The
site total prevents the same scrap from satisfying both routes. This is not an
unbounded pooled supply: it is a material bus with explicit route draws and a
bounded total. External import and internal-reuse origins remain a reporting
gap because the public source does not assign them to individual BOF/EAF draws.

## Evidence and cases

The official C1 context gives approximately 2.8 Mt/y hot metal, 1.0 Mt/y BOF
scrap and 3.4 Mt/y BOF liquid steel, alongside 2.8 Mt/y HDRI, approximately
1.0 Mt/y EAF scrap and 3.3 Mt/y EAF liquid steel. It also reports a 1.9--2.8
Mt/y site scrap envelope. The source cards retain the detailed locators:
[BOF/OSF](../../../data/03_Optimisation/inputs/assets/steel/source_cards/BOF_OSF_Parameters.md),
[EAF](../../../data/03_Optimisation/inputs/assets/steel/source_cards/EAF_Parameters.md), and
[DRP](../../../data/03_Optimisation/inputs/assets/steel/source_cards/DRP_Parameters.md).

The diagnostic compares four fixed evidence cases:

| Case | BOF/EAF/site scrap cap (Mt/y) | Role |
|---|---:|---|
| Legacy | no named metallics | historical development reference |
| Official lower | 1.0 / 0.9 / 1.9 | fully bounded public lower envelope |
| Rounded central | 1.0 / 1.0 / 2.0 | central diagnostic within the public envelope |
| Official upper | 1.0 / 1.8 / 2.8 | context only; not eligible for active-target selection |

The rounded central case is intentionally not described as a fully attributed
external/internal supply ledger: its 2.0 Mt/y rounded process demand differs
by 0.1 Mt/y from the rounded 1.3 + 0.6 Mt/y source breakdown. That difference
is retained as a source-boundary caveat rather than hidden as a free source.

## Interpretation rules

- The model does **not** change any BOF, EAF, DRP, BF, HSM or DSP capacity.
- The upper scrap envelope is an explanatory bound, not an anchor-fitting
  choice. It must be read together with the 2.8-Mt/y HDRI annual anchor and
  annual availability policy.
- The capacity diagnostic uses the existing C1 coke-chain reconciliation and
  downstream-origin interface; it does not activate a WAG/NG ratio, mixed WAG
  carrier, economics or a residual supply.
- A capacity result remains a representative-week annualisation diagnostic,
  not proof of 100% annual availability.

## Expected significance

The old retained BOF proxy equated a tonne of hot metal to a tonne of BOF
liquid steel. The source-backed BOF recipe instead permits approximately
3.4 Mt/y liquid steel from the 2.8-Mt/y hot-metal context, provided the
separate 1.0-Mt/y BOF scrap draw is available. This is a physical conversion
correction, not a capacity increase.

The associated run reports whether that correction materially improves the
final-product capacity while keeping BOF, EAF and site scrap caps visible.
If the central case remains below 6.75 Mt/y, the next investigation is the
remaining downstream/availability gap, not a larger scrap cap by default.
