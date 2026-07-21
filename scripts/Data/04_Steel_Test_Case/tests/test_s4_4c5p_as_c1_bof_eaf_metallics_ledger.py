from __future__ import annotations

from pathlib import Path
import sys

STEEL_ROOT = Path(__file__).resolve().parents[1]
if str(STEEL_ROOT) not in sys.path:
    sys.path.insert(0, str(STEEL_ROOT))

from steel.s4_4c5p_as_c1_bof_eaf_metallics_ledger import (
    _load_config,
    _scenario_maps,
    solve_capacity_case,
)


CONFIG = STEEL_ROOT / "configs" / "steel_c1_bof_eaf_metallics_ledger.yaml"


def _scenario(config: dict, scenario_id: str) -> dict:
    return next(row for row in config["scenarios"] if row["scenario_id"] == scenario_id)


def test_central_ledger_keeps_bof_eaf_and_site_scrap_caps_separate() -> None:
    config = _load_config(CONFIG)
    eaf, bof, ledger = _scenario_maps(config, _scenario(config, "rounded_central_named_consumption"), 168)
    assert eaf is not None and bof is not None and ledger is not None
    assert eaf["scrap_t_per_t_liquid_steel"] == 0.303030303
    assert bof["scrap_t_per_t_liquid_steel"] == 0.294
    assert round(ledger["bof_scrap_supply_cap_t"] + ledger["eaf_scrap_supply_cap_t"], 6) == round(ledger["site_total_scrap_supply_cap_t"], 6)


def test_named_central_metallics_raise_capacity_without_relaxing_a_source_cap() -> None:
    config = _load_config(CONFIG)
    baseline = solve_capacity_case(config, _scenario(config, "legacy_no_named_metallics"))
    central = solve_capacity_case(config, _scenario(config, "rounded_central_named_consumption"))
    assert baseline["status"] == "pass"
    assert central["status"] == "pass"
    assert central["annualised_final_product_mt_y"] > baseline["annualised_final_product_mt_y"] + 0.1
    assert central["annualised_bof_scrap_mt_y"] <= 1.0 + 1e-6
    assert central["annualised_eaf_scrap_mt_y"] <= 1.0 + 1e-6
    assert central["annualised_site_scrap_mt_y"] <= 2.0 + 1e-6
