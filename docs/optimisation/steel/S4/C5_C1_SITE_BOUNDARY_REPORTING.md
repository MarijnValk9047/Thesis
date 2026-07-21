# C5 C1 Site-Boundary Reporting

## Purpose

`S4.4c5p_ax` creates a reporting boundary around the represented C1 physical
model so that official and Athanasiadis total-site context can be shown beside
the model. It is not a full-site load model.

Every site comparison is expressed as:

```text
site-context anchor = represented model subtotal + visible residual
```

The residual is a signed reporting quantity. It is never a load, fuel supply,
allocation, price term or calibration variable.

## Steam and boilers

The model has a useful diagnostic steam network: 72-, 45- and 15-bar buses,
carrier-specific boiler eligibility, mapped demand closure, and internal-only
STEG11/TG2 electricity accounting. It is not yet a complete site utility
network because it uses mass-flow rather than enthalpy dispatch, has no active
steam store, no complete process-demand mapping, and no active EAF off-gas
recovery.

## Natural gas

Named DRP/EAF volume is converted on a declared 35.8 MJ/Nm3 LHV bridge and is
kept separate from named HSM/PEFA/boiler NG. The difference to full-site NG is
reported as unallocated residual. It is not assigned to generators, boilers or
out-of-scope processes.

## Athanasiadis Figure 91

Figure 91 supplies directional model-precedent context only. Its total CO2,
NG, coal and WAG-electricity comparisons require matching total-site C1
boundaries before a numerical direction test is allowed.
