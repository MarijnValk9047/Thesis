# C5 Downstream Origin-Tag Audit

## Result

The unified C5 builder does not yet support a site-final-product comparison
that distinguishes BOF-origin, EAF-origin and imported-slab product.  This is
a boundary finding, not a capacity failure.

- C0 final product is a HSM proxy without a preserved BOF/DSP origin tag.
- C1 retained BF/BOF output is separately visible, but only as a HSM proxy.
- C1 EAF output enters the final-product proxy directly, bypassing an explicit
  EAF-to-HSM/DSP routing interface.
- C1 imported slab is absent from executable material balances, correctly so:
  the source card now records its annual HSM/WBW destination, but no rolling
  supply profile or separate external-material interface exists yet.

The audit output is local-only under
`data/03_Optimisation/runs/steel_downstream_origin_tag_audit_v1/`.

## Consequence

Do not use current final-product output to conclude that a 6.75 Mt/y
all-endogenous stress case is inconsistent with the MER's 7.0 Mt/y C1 site
product anchor.  The quantities have different boundaries.

## Next Physical Gate

Design one material interface with origin-tagged flows:

```text
BOF liquid steel -> HSM/DSP -> final product
EAF liquid steel -> HSM/DSP -> final product
imported slab    -> HSM/WBW -> final product
```

The imported-slab leg remains disabled until an annual-cap-to-rolling-profile
policy is explicit.  The interface must preserve existing capacities and
yields in its first version and must keep imported slab separate from
cold-slab inventory.
