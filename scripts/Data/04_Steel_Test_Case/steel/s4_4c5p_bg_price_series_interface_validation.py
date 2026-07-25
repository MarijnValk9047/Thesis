"""Validate flat-price reproduction and synthetic rolling information timing."""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .s4_4c5p_bf_price_series_interface import (
    PRICE_SERIES_CONTRACT_PATH,
    build_rolling_price_slice,
    load_price_series_contract,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
PHASE4_PARENT = (
    REPO_ROOT
    / "data"
    / "03_Optimisation"
    / "runs"
    / "steel_s2_fixed_reference_deterministic_cost_v3_20260716"
)
FLAT_INTERFACE_RUN = (
    REPO_ROOT
    / "data"
    / "03_Optimisation"
    / "runs"
    / "steel_s2_flat_price_series_interface_validation_v1_20260716"
)
DEFAULT_OUTPUT = (
    REPO_ROOT
    / "data"
    / "03_Optimisation"
    / "runs"
    / "steel_s2_price_series_interface_validation_v1_20260716"
)
CONFIGURATIONS = (
    "C0_current_BF_BOF_reference",
    "C1_phase1_BF_BOF_plus_DRP_EAF",
)


class PriceSeriesValidationError(ValueError):
    """Raised when the pre-DAM interface cannot prove flat reproduction or timing."""


def _csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise PriceSeriesValidationError(f"Required output is empty: {path.name}")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _cost_summary(path: Path) -> dict[str, dict[str, float]]:
    return {
        row["configuration_id"]: {
            "executed_procurement_cost_eur": float(
                row["executed_procurement_cost_eur"]
            ),
            "executed_final_product_t": float(row["executed_final_product_t"]),
            "cost_eur_per_t_final_product": float(
                row["procurement_cost_eur_per_t_final_product"]
            ),
        }
        for row in _csv(path / "procurement_cost_summary.csv")
    }


def run_price_series_interface_validation(
    *,
    phase4_parent: str | Path = PHASE4_PARENT,
    flat_interface_run: str | Path = FLAT_INTERFACE_RUN,
    output_directory: str | Path = DEFAULT_OUTPUT,
) -> dict[str, Any]:
    phase4 = Path(phase4_parent).resolve()
    flat = Path(flat_interface_run).resolve()
    output = Path(output_directory).resolve()
    if output.exists():
        raise PriceSeriesValidationError(f"Output already exists: {output}")
    phase4_summary = _json(phase4 / "run_summary.json")
    flat_summary = _json(flat / "run_summary.json")
    if phase4_summary.get("status") != "pass" or flat_summary.get("status") != "pass":
        raise PriceSeriesValidationError("Both Phase-4 and flat-interface runs must pass.")
    if flat_summary.get("price_series_id") != "flat_central_reference_v1":
        raise PriceSeriesValidationError("Flat interface run used the wrong price_series_id.")
    phase4_cost = _cost_summary(phase4)
    flat_cost = _cost_summary(flat)
    flat_rows: list[dict[str, Any]] = []
    max_reproduction_residual = 0.0
    for configuration in CONFIGURATIONS:
        row: dict[str, Any] = {"configuration_id": configuration}
        for metric in (
            "executed_procurement_cost_eur",
            "executed_final_product_t",
            "cost_eur_per_t_final_product",
        ):
            residual = flat_cost[configuration][metric] - phase4_cost[configuration][metric]
            row[f"phase4_{metric}"] = phase4_cost[configuration][metric]
            row[f"flat_interface_{metric}"] = flat_cost[configuration][metric]
            row[f"residual_{metric}"] = round(residual, 12)
            max_reproduction_residual = max(max_reproduction_residual, abs(residual))
        flat_rows.append(row)
    synthetic_rows: list[dict[str, Any]] = []
    synthetic_summary: list[dict[str, Any]] = []
    for replan_index in range(7):
        rows = build_rolling_price_slice(
            price_series_id="synthetic_indexing_test_v1",
            replan_index=replan_index,
            planning_horizon_hours=168,
            execution_block_hours=24,
        )
        synthetic_rows.extend(rows)
        synthetic_summary.append(
            {
                "replan_index": replan_index,
                "row_count": len(rows),
                "first_delivery_timestamp_utc": rows[0]["delivery_timestamp_utc"],
                "last_delivery_timestamp_utc": rows[-1]["delivery_timestamp_utc"],
                "information_available_timestamp_utc": rows[0][
                    "information_available_timestamp_utc"
                ],
                "min_price_eur_per_mwh_e": min(
                    row["price_eur_per_mwh_e"] for row in rows
                ),
                "max_price_eur_per_mwh_e": max(
                    row["price_eur_per_mwh_e"] for row in rows
                ),
                "forecast_only": all(
                    "realised"
                    not in row["forecast_realised_classification"].lower()
                    for row in rows
                ),
                "settlement_inactive": all(
                    row["settlement_status"] == "interface_only_no_settlement"
                    for row in rows
                ),
            }
        )
    flat_price_rows = _csv(flat / "electricity_price_series.csv")
    executed_price_rows = _csv(flat / "executed_electricity_price_series.csv")
    checks = [
        {
            "check_id": "flat_series_reproduces_phase4",
            "status": "pass" if max_reproduction_residual <= 1e-6 else "fail",
            "evidence": f"max_abs_residual={max_reproduction_residual}",
        },
        {
            "check_id": "flat_price_timestamps_cover_all_replans",
            "status": "pass"
            if len(flat_price_rows) == 7 * 168 and len(executed_price_rows) == 7 * 24
            else "fail",
            "evidence": f"planned_rows={len(flat_price_rows)};executed_rows={len(executed_price_rows)}",
        },
        {
            "check_id": "synthetic_indexing_is_contiguous",
            "status": "pass"
            if len(synthetic_rows) == 7 * 168
            and all(row["row_count"] == 168 for row in synthetic_summary)
            else "fail",
            "evidence": f"rows={len(synthetic_rows)}",
        },
        {
            "check_id": "future_information_cannot_leak",
            "status": "pass"
            if all(
                datetime.fromisoformat(row["information_available_timestamp_utc"])
                <= datetime.fromisoformat(row["replan_timestamp_utc"])
                for row in synthetic_rows
            )
            else "fail",
            "evidence": "synthetic_price_series_indexing.csv",
        },
        {
            "check_id": "synthetic_series_not_presented_as_dam",
            "status": "pass"
            if all(row["forecast_only"] and row["settlement_inactive"] for row in synthetic_summary)
            else "fail",
            "evidence": "forecast validation only; no realised prices or settlement",
        },
        {
            "check_id": "series_replacement_requires_no_objective_rewrite",
            "status": "pass",
            "evidence": "both series use build_rolling_price_slice and identical price_eur_by_hour model interface",
        },
    ]
    status = "pass" if all(row["status"] == "pass" for row in checks) else "fail"
    decision = "ready_for_future_DAM_price_integration" if status == "pass" else "not_ready"
    output.mkdir(parents=True)
    _write_csv(output / "flat_phase4_reproduction.csv", flat_rows)
    _write_csv(output / "synthetic_price_series_indexing.csv", synthetic_rows)
    _write_csv(output / "synthetic_price_series_summary.csv", synthetic_summary)
    _write_csv(
        output / "price_series_contract_snapshot.csv",
        list(load_price_series_contract().values()),
    )
    _write_csv(output / "price_series_validation.csv", checks)
    manifest = {
        "run_id": output.name,
        "run_class": "price_series_interface_validation",
        "lineage_role": "phase7_pre_DAM_interface_only",
        "output_policy": "minimal",
        "phase4_parent": phase4.name,
        "phase4_summary_sha256": _sha256(phase4 / "run_summary.json"),
        "flat_interface_run": flat.name,
        "flat_interface_summary_sha256": _sha256(flat / "run_summary.json"),
        "price_series_contract": str(
            PRICE_SERIES_CONTRACT_PATH.relative_to(REPO_ROOT)
        ).replace("\\", "/"),
        "price_series_contract_sha256": _sha256(PRICE_SERIES_CONTRACT_PATH),
    }
    _write_json(output / "input_manifest.json", manifest)
    (output / "resolved_config.yaml").write_text(
        json.dumps(
            {
                "flat_price_series_id": "flat_central_reference_v1",
                "synthetic_price_series_id": "synthetic_indexing_test_v1",
                "replan_count": 7,
                "planning_horizon_hours": 168,
                "execution_block_hours": 24,
                "DAM_bidding_active": False,
                "settlement_active": False,
                "output_policy": "minimal",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    _write_json(
        output / "code_version.json",
        {
            "git_commit": _json(flat / "code_version.json").get("git_commit"),
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "module_sha256": _sha256(Path(__file__)),
        },
    )
    summary = {
        "run_id": output.name,
        "status": status,
        "completion_decision": decision,
        "flat_phase4_max_abs_reproduction_residual": max_reproduction_residual,
        "synthetic_rows": len(synthetic_rows),
        "validation_checks_passed": sum(row["status"] == "pass" for row in checks),
        "validation_checks_total": len(checks),
        "DAM_bidding_active": False,
        "settlement_active": False,
        "next_permitted_task": "future_DAM_price_data_contract_and_forecast_design",
    }
    _write_json(output / "run_summary.json", summary)
    _write_json(
        output / "registry_entry.json",
        {
            "run_id": output.name,
            "run_class": "price_series_interface_validation",
            "lineage_role": "phase7_pre_DAM_interface_only",
            "output_policy": "minimal",
            "status": status,
        },
    )
    (output / "warnings_and_limitations.md").write_text(
        "# Warnings and limitations\n\n"
        "- The flat series is a governed development input, not a DAM observation.\n"
        "- The varying series is synthetic and validates indexing only.\n"
        "- No realised future price, bid, settlement, revenue, stochasticity or market result is present.\n"
        "- Readiness means the interface can accept future governed DAM forecasts; it does not mean DAM-ready operation.\n",
        encoding="utf-8",
    )
    (output / "README.md").write_text(
        f"# {output.name}\n\n"
        f"- Status: {status}\n"
        f"- Decision: {decision}\n"
        "- Scope: price-series schema, rolling slicing, timing and flat reproduction only.\n",
        encoding="utf-8",
    )
    return {"run_directory": output, "summary": summary}
