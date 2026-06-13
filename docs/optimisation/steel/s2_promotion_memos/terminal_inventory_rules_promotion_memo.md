# Terminal Inventory Rules Promotion Memo

## Category Purpose In S2

`terminal_inventory_rules` stop the optimisation from creating false value through end-horizon stock shifts.

## Evidence Status

Current support is structural or methodological:

- endpoint neutrality for `DRI`
- endpoint neutrality and anti-free-battery logic for slab or `WIP`

No approved numerical terminal quantities exist.

## Unit Conventions

- future executable bounds: `tonnes`
- current rows may be structural class labels rather than numeric quantities

## Sign Conventions

Terminal rules constrain positive inventory states.

## Model Role

- structural assumption support now;
- executable constraint input later only after policy review.

## Approval Blockers

- no reviewed numeric terminal-policy values;
- slab or `WIP` treatment still depends on hot/cold route assumptions;
- endpoint neutrality must be translated into explicit parameter rules.

## Thesis-Usability Requirements

- explicit terminal-policy design;
- reviewed numeric bounds or reviewed neutrality rule;
- consistency with opening-inventory and storage-physics assumptions.

## Misuse Red Flags

- turning structural endpoint rules into approved numeric bounds without review;
- letting buffer classes exist without terminal policy;
- treating hot-transfer assumptions as free storage.
