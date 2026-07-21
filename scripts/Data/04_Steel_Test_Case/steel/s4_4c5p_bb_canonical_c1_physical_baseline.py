"""Create the single canonical C1 physical baseline from a governed YAML."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from .s4_4c5p_at_c1_central_metallics_wag_steam_utility_reconciliation import (
    DEFAULT_RUN_ROOT,
    run_c1_central_metallics_wag_steam_utility_reconciliation,
)
from .s4_4c_unified_physical_modelbuilder import REPO_ROOT


DEFAULT_CONFIG = REPO_ROOT / "scripts" / "Data" / "04_Steel_Test_Case" / "configs" / "steel_c1_canonical_physical_baseline.yaml"


def _load_config(path: Path) -> dict[str, Any]:
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError("Canonical C1 baseline config must be a mapping.")
    required = {
        "run_id", "metallics_config_path", "scenario_id", "downstream_boundary_case",
        "output_policy", "run_class", "lineage_role", "retention",
    }
    missing = sorted(required.difference(config))
    if missing:
        raise ValueError(f"Canonical C1 config is missing: {missing}")
    for key in ("market_prices_enabled", "energy_cost_objective_enabled", "product_revenue_enabled", "co2_ets_objective_enabled"):
        if config.get(key) is not False:
            raise ValueError(f"Canonical C1 baseline requires {key}: false.")
    if config["downstream_boundary_case"] != "mer_site_product":
        raise ValueError("The canonical C1 baseline is the explicit MER-site-product boundary case.")
    return config


def run_canonical_c1_physical_baseline(
    *, config_path: str | Path = DEFAULT_CONFIG, output_root: str | Path = DEFAULT_RUN_ROOT
) -> dict[str, Any]:
    config_file = Path(config_path).resolve()
    config = _load_config(config_file)
    result = run_c1_central_metallics_wag_steam_utility_reconciliation(
        output_root=output_root,
        run_id=str(config["run_id"]),
        metallics_config_path=REPO_ROOT / str(config["metallics_config_path"]),
        scenario_id=str(config["scenario_id"]),
        downstream_boundary_case=str(config["downstream_boundary_case"]),
        output_policy=str(config["output_policy"]),
        run_class=str(config["run_class"]),
        lineage_role=str(config["lineage_role"]),
        retention=str(config["retention"]),
    )
    run_directory = Path(result["run_directory"])
    contract = dict(config)
    contract["canonical_configuration"] = "C1_phase1_BF_BOF_plus_DRP_EAF"
    contract["production_denominator"] = "final_product_proxy"
    contract["source_config_sha256"] = hashlib.sha256(config_file.read_bytes()).hexdigest()
    (run_directory / "canonical_baseline_contract.yaml").write_text(
        yaml.safe_dump(contract, sort_keys=False), encoding="utf-8"
    )
    manifest_path = run_directory / "input_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["canonical_baseline_config"] = {
        "path": config_file.relative_to(REPO_ROOT).as_posix(),
        "sha256": contract["source_config_sha256"],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result
