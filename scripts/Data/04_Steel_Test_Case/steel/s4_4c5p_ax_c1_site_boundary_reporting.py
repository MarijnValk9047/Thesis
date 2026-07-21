"""Report C1 represented subtotals and residual site context without filling them."""

from __future__ import annotations

import csv
import json
import subprocess
from pathlib import Path
from typing import Any

import yaml

from .s4_4c_unified_physical_modelbuilder import REPO_ROOT


STAGE = "S4.4c5p_ax_c1_site_boundary_reporting"
DEFAULT_CONFIG = REPO_ROOT / "scripts" / "Data" / "04_Steel_Test_Case" / "configs" / "steel_c1_site_boundary_reporting.yaml"
DEFAULT_RUN_ROOT = REPO_ROOT / "data" / "03_Optimisation" / "runs"
C5P_B_COMPACT = REPO_ROOT / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "S4" / "s4_4c5p_b_boiler_steam_circuit_accounting" / "s4_4c5p_b_compact_table_for_chat.csv"


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields or ["empty"], extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _git_revision() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def _load_config(path: Path) -> dict[str, Any]:
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError("Site-boundary reporting config must be a mapping.")
    if float(config["natural_gas_lhv_mj_per_nm3"]) <= 0:
        raise ValueError("Natural-gas LHV must be positive.")
    return config


def _metric_map(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    return {row["metric"]: row for row in rows}


def _ng_pj(named_volume_million_nm3: float, controller_ng_pj: float, lhv_mj_per_nm3: float) -> float:
    return named_volume_million_nm3 * lhv_mj_per_nm3 / 1000.0 + controller_ng_pj


def _site_rows(utilities: dict[str, dict[str, str]], anchors: dict[str, float], ng_lhv: float) -> list[dict[str, Any]]:
    named_volume = float(utilities["named_NG_DRP_EAF_volume"]["model_value"])
    controller_ng = float(utilities["named_NG_HSM_PEFA_boiler_energy"]["model_value"])
    represented_ng = _ng_pj(named_volume, controller_ng, ng_lhv)
    definitions = (
        ("gross_electricity", float(utilities["gross_electricity"]["model_value"]), "TWh/y", anchors["official_c1_gross_electricity_twh_y"], "official C1 total-site electricity context", "partial represented process boundary"),
        ("net_grid_import", float(utilities["net_grid_import_after_internal_WAG_offset"]["model_value"]), "TWh/y", anchors["official_c1_grid_import_twh_y"], "official C1 grid-import context", "partial represented process boundary"),
        ("named_NG", represented_ng, "PJ_LHV/y", anchors["official_c1_full_site_ng_pj_y"], "official C1 full-site NG context", "represented named NG only; residual remains unallocated"),
        ("explicit_fuel_CO2", float(utilities["WAG_explicit_combustion_CO2"]["model_value"]), "MtCO2/y", anchors["official_c1_scope1_mtco2_y"], "official C1 Scope 1 context", "Mode-B WAG-only subtotal; not Scope 1"),
    )
    rows: list[dict[str, Any]] = []
    for family, represented, unit, anchor, anchor_name, boundary in definitions:
        residual = anchor - represented
        rows.append({
            "metric_family": family,
            "represented_model_subtotal": round(represented, 6),
            "unit": unit,
            "site_context_anchor": anchor,
            "anchor_name": anchor_name,
            "unallocated_or_unrepresented_residual": round(residual, 6),
            "residual_share_of_anchor": round(residual / anchor, 9),
            "reporting_status": "visible_residual_not_model_input",
            "boundary_status": boundary,
        })
    rows.append({
        "metric_family": "Athanasiadis_table9_gross_electricity",
        "represented_model_subtotal": float(utilities["gross_electricity"]["model_value"]),
        "unit": "TWh/y",
        "site_context_anchor": anchors["athanasiadis_table9_electricity_twh_y"],
        "anchor_name": "Athanasiadis Table 9 model-precedent electricity",
        "unallocated_or_unrepresented_residual": round(anchors["athanasiadis_table9_electricity_twh_y"] - float(utilities["gross_electricity"]["model_value"]), 6),
        "residual_share_of_anchor": round((anchors["athanasiadis_table9_electricity_twh_y"] - float(utilities["gross_electricity"]["model_value"])) / anchors["athanasiadis_table9_electricity_twh_y"], 9),
        "reporting_status": "directional_model_precedent_context_only",
        "boundary_status": "Athanasiadis denominator and total-site boundary remain unresolved",
    })
    return rows


def _steam_rows(utilities: dict[str, dict[str, str]]) -> list[dict[str, Any]]:
    return [
        {"aspect": "pressure_buses", "status": "implemented_diagnostic", "evidence": "72bar, 45bar and 15bar buses exist in C5p_b", "limitation": "mass-flow accounting, not enthalpy/thermal-state dispatch"},
        {"aspect": "mapped_15bar_balance", "status": "pass", "evidence": f"demand={utilities['modelled_steam_15bar_demand']['model_value']} kt/y; supply={utilities['modelled_steam_15bar_supply']['model_value']} kt/y; unserved={utilities['modelled_steam_15bar_unserved']['model_value']} kt/y", "limitation": "only existing mapped demand; not full site steam"},
        {"aspect": "boiler_fuel_eligibility", "status": "implemented_diagnostic", "evidence": "BFG/COG eligibility retained where source-backed; NG remains explicit backup", "limitation": "no verified Tata-specific boiler efficiency calibration"},
        {"aspect": "steam_storage_and_recovery", "status": "not_active", "evidence": "steam storage is inactive; EAF off-gas recovery is reporting-only", "limitation": "cannot claim complete utility-network optimisation"},
        {"aspect": "generator_coproduct", "status": "accounting_only", "evidence": "STEG11/TG2 electricity is internal accounting only", "limitation": "not an economic or market generator model"},
    ]


def _figure_rows(context: dict[str, float]) -> list[dict[str, Any]]:
    requirements = {
        "total_CO2": "full-site explicit-fuel coverage bridge plus non-fuel separation",
        "total_site_NG": "all named NG consumers on a common LHV basis; residual stays separate",
        "total_site_coal": "coal/coke/PCI annual material-input ledger",
        "WAG_electricity_generation": "generator electricity output boundary matching the site meter",
    }
    return [
        {
            "metric_family": family,
            "athanasiadis_model_minus_real_share": difference,
            "athanasiadis_direction": "model_above_real" if float(difference) > 0 else "model_below_real",
            "our_current_status": "site_boundary_reporting_only",
            "required_before_numeric_direction_test": requirements[family],
        }
        for family, difference in context.items()
    ]


def run_c1_site_boundary_reporting(*, config_path: str | Path = DEFAULT_CONFIG, output_root: str | Path = DEFAULT_RUN_ROOT) -> dict[str, Any]:
    config_path = Path(config_path).resolve()
    config = _load_config(config_path)
    source_directory = Path(output_root).resolve() / config["source_run_id"]
    output_directory = Path(output_root).resolve() / config["run_id"]
    if output_directory.exists():
        raise ValueError(f"Run directory already exists: {output_directory}")
    required = ("utility_energy_co2_ledger.csv", "run_summary.json", "resolved_config.yaml")
    missing = [name for name in required if not (source_directory / name).exists()]
    if missing:
        raise FileNotFoundError(f"Source run lacks: {', '.join(missing)}")
    utilities = _metric_map(_read_csv(source_directory / "utility_energy_co2_ledger.csv"))
    output_directory.mkdir(parents=True)
    site_rows = _site_rows(utilities, config["site_context_anchors"], float(config["natural_gas_lhv_mj_per_nm3"]))
    steam_rows = _steam_rows(utilities)
    figure_rows = _figure_rows(config["athanasiadis_figure_91_model_minus_real_share"])
    _write_csv(output_directory / "site_boundary_anchor_ledger.csv", site_rows)
    _write_csv(output_directory / "steam_boiler_network_status.csv", steam_rows)
    _write_csv(output_directory / "athanasiadis_figure_91_site_boundary_requirements.csv", figure_rows)
    summary = {
        "stage": STAGE,
        "status": "pass_with_visible_residuals",
        "source_run_id": config["source_run_id"],
        "output_policy": config["output_policy"],
        "run_class": config["run_class"],
        "lineage_role": config["lineage_role"],
        "steam_network_status": "mapped_demand_closes_diagnostic_only",
        "NG_status": "named_NG_represented_full_site_residual_visible",
        "go_no_go": {"site_boundary_reporting": "GO", "residual_as_model_input": "NO_GO", "full_site_utility_claim": "NO_GO", "economics_and_DA": "NO_GO"},
    }
    _write_json(output_directory / "run_summary.json", summary)
    _write_json(output_directory / "s4_4c5p_ax_stage_gate.json", summary)
    _write_json(output_directory / "registry_entry.json", {"run_id": config["run_id"], "run_class": config["run_class"], "lineage_role": config["lineage_role"], "output_policy": config["output_policy"], "git_eligible": False})
    _write_json(output_directory / "code_version.json", {"git_revision": _git_revision(), "module": __file__})
    _write_json(output_directory / "input_manifest.json", {"config": config_path.relative_to(REPO_ROOT).as_posix(), "source_run": config["source_run_id"], "steam_source": C5P_B_COMPACT.relative_to(REPO_ROOT).as_posix() if C5P_B_COMPACT.exists() else "missing"})
    (output_directory / "resolved_config.yaml").write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    (output_directory / "warnings_and_limitations.md").write_text(
        "# Warnings and limitations\n\n"
        "- Residuals are reporting rows only and cannot enter the model.\n"
        "- Steam closure covers mapped C5p_b demand, not the complete site steam system.\n"
        "- Named NG uses a declared 35.8 MJ/Nm3 LHV bridge; it is distinct from full-site NG residual.\n"
        "- Athanasiadis Figure 91 remains directional context until like-for-like total-site boundaries exist.\n",
        encoding="utf-8",
    )
    return {"run_directory": output_directory, "site_rows": site_rows, "summary": summary}
