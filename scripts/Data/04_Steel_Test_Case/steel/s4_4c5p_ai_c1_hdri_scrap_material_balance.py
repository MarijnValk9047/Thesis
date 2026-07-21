"""C1 diagnostic for named HDRI plus scrap EAF material accounting."""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from pyomo.environ import Objective, maximize, value

from .s4_4c_unified_physical_modelbuilder import (
    REPO_ROOT,
    S44B_INPUT_DIR,
    _apply_solver_time_limit,
    _build_c1_inputs,
    _build_c1_model,
    _load_tables,
    _select_solver,
)


DEFAULT_CONFIG = REPO_ROOT / "scripts" / "Data" / "04_Steel_Test_Case" / "configs" / "steel_c1_hdri_scrap_material_balance.yaml"
DEFAULT_RUN_ROOT = REPO_ROOT / "data" / "03_Optimisation" / "runs"


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def run_c1_hdri_scrap_material_balance(*, config_path: str | Path = DEFAULT_CONFIG, output_root: str | Path = DEFAULT_RUN_ROOT) -> dict[str, Any]:
    config_file = Path(config_path).resolve()
    config = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError("C1 HDRI/scrap diagnostic config must be a mapping.")
    run_directory = Path(output_root).resolve() / str(config["run_id"])
    if run_directory.exists():
        raise ValueError(f"Run directory already exists: {run_directory}")
    run_directory.mkdir(parents=True)
    horizon_hours = int(config["horizon_hours"])
    scrap_cap = float(config["annual_scrap_supply_t_y"]) / 365.0 * horizon_hours / 24.0
    material_balance = {
        "hdri_t_per_t_liquid_steel": float(config["hdri_t_per_t_liquid_steel"]),
        "scrap_t_per_t_liquid_steel": float(config["scrap_t_per_t_liquid_steel"]),
        "scrap_supply_cap_t": scrap_cap,
    }
    tables = _load_tables(S44B_INPUT_DIR)
    inputs = _build_c1_inputs(tables, horizon_hours_override=horizon_hours, include_retained_bf_bof=True)
    model = _build_c1_model(
        inputs,
        enable_minimal_wag_layer=True,
        enable_c1_retained_bf_bof_route=True,
        enable_internal_wag_power=True,
        development_controller_activation="full",
        c1_retained_route_policy="quota_driven_topology",
        commitment_granularity="daily_binary_hourly_throughput",
        eaf_material_balance=material_balance,
    )
    model.final_product_fulfilment.deactivate()
    model.static_price_naive_objective.deactivate()
    model.diagnostic_max_final_product = Objective(
        expr=sum(model.final_product_output[t] for t in model.TIME), sense=maximize
    )
    solver_name, solver = _select_solver()
    _apply_solver_time_limit(solver_name, solver, 120.0)
    result = solver.solve(model)
    eaf_output = sum(value(model.eaf_final_product_output[t]) for t in model.TIME)
    retained_output = sum(value(model.retained_bf_bof_final_product_output[t]) for t in model.TIME)
    scrap_used = sum(value(model.scrap_t[t]) for t in model.TIME)
    hdri_used = sum(value(model.eaf_dri_input[t]) for t in model.TIME)
    total_output = eaf_output + retained_output
    summary = {
        "run_id": config["run_id"], "status": "pass", "solver_name": solver_name,
        "termination_condition": str(result.solver.termination_condition),
        "max_final_product_t_7d": round(total_output, 6),
        "annualised_final_product_mt_y": round(total_output / 7.0 * 365.0 / 1_000_000.0, 6),
        "retained_route_final_product_t_7d": round(retained_output, 6),
        "eaf_liquid_steel_t_7d": round(eaf_output, 6),
        "hdri_input_t_7d": round(hdri_used, 6),
        "named_scrap_input_t_7d": round(scrap_used, 6),
        "scrap_supply_cap_t_7d": round(scrap_cap, 6),
        "scrap_supply_cap_binding": abs(scrap_used - scrap_cap) < 1e-5,
        "material_balance_mode": "MER_HDRI_plus_named_scrap_diagnostic",
        "caveat": "Diagnostic only. MER annual context constrains named scrap supply but is not converted into an hourly plant capacity or a base executable input.",
    }
    (run_directory / "config_resolved.yaml").write_text(yaml.safe_dump({**config, "scrap_supply_cap_t_7d": scrap_cap}, sort_keys=False), encoding="utf-8")
    _write_json(run_directory / "input_manifest.json", {"config_sha256": hashlib.sha256(config_file.read_bytes()).hexdigest(), "input_directory": str(S44B_INPUT_DIR.relative_to(REPO_ROOT))})
    _write_json(run_directory / "code_version.json", {"timestamp_utc": datetime.now(timezone.utc).isoformat()})
    _write_csv(run_directory / "material_balance_summary.csv", [summary])
    _write_json(run_directory / "run_summary.json", summary)
    _write_json(run_directory / "registry_entry.json", {"run_id": config["run_id"], "run_class": "material_balance_diagnostic", "lineage_role": "diagnostic", "output_policy": "diagnostics", "git_eligible": False})
    (run_directory / "warnings_and_limitations.md").write_text("# Limitations\n\n- No capacity, source card or base input was changed.\n- Scrap is named and capped; no free scrap is introduced.\n- This does not make a whole-site annual-capacity claim.\n", encoding="utf-8")
    return {"run_directory": run_directory, "summary": summary}
