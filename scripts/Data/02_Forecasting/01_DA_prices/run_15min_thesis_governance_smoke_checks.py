from __future__ import annotations

import json
from pathlib import Path

from quarterhour_da import (
    QuarterHourDAExtensionConfig,
    assert_thesis_grade_actual_source_authorized,
    build_thesis_grade_frozen_actual_metadata,
    find_frozen_actual_version,
    find_latest_phase05_run,
    load_frozen_actual_path,
    resolve_frozen_actual_registry_entry,
)


def main() -> int:
    config = QuarterHourDAExtensionConfig()
    version_id = "canonical_v1"

    version_dir = find_frozen_actual_version(config, version_id)
    if version_dir is None:
        raise FileNotFoundError(f"Frozen actual version '{version_id}' was not found.")

    registry_entry = resolve_frozen_actual_registry_entry(config, version_id=version_id, verify_hash=True)
    assert_thesis_grade_actual_source_authorized(registry_entry.canonical_csv_path, config=config, thesis_grade=True)
    frame = load_frozen_actual_path(config, version_id=version_id, verify_hash=True, thesis_grade=True)
    metadata = build_thesis_grade_frozen_actual_metadata(config, version_id=version_id, verify_hash=False)

    attrs_ok = all(frame.attrs.get(key) == value for key, value in metadata.items())

    legacy_run = find_latest_phase05_run(config)
    legacy_path = (
        legacy_run / "counterfactual_realized_15min_long.csv"
        if legacy_run is not None
        else Path("data/02_Forecasting/01_DA_prices/quarterhour_da/phase05_runs/example/counterfactual_realized_15min_long.csv")
    )
    legacy_rejected = False
    legacy_error = ""
    try:
        assert_thesis_grade_actual_source_authorized(legacy_path, config=config, thesis_grade=True)
    except ValueError as exc:
        legacy_rejected = True
        legacy_error = str(exc)

    notebook_source = (
        config.repo_root
        / "scripts"
        / "Data"
        / "02_Forecasting"
        / "01_DA_prices"
        / "create_da_15min_extension_notebooks.py"
    ).read_text(encoding="utf-8")
    active_summary_uses_legacy_realized = 'phase05_realized = pd.read_csv(latest_phase05 / "counterfactual_realized_15min_long.csv"' in notebook_source
    generated_summary_notebook = (
        config.repo_root
        / "notebooks"
        / "Data"
        / "02_Forecasting"
        / "01_DA_prices"
        / "15min_extension"
        / "08_results_and_plot_interpretation.ipynb"
    )
    generated_summary_text = generated_summary_notebook.read_text(encoding="utf-8") if generated_summary_notebook.exists() else ""
    generated_summary_uses_legacy_realized = 'counterfactual_realized_15min_long.csv' in generated_summary_text

    payload = {
        "canonical_version_dir": str(version_dir),
        "canonical_csv_path": str(registry_entry.canonical_csv_path),
        "canonical_manifest_path": str(registry_entry.manifest_path),
        "canonical_csv_sha256": registry_entry.authoritative_sha256,
        "canonical_row_count": int(frame.shape[0]),
        "canonical_loader_attrs_match_metadata": bool(attrs_ok),
        "legacy_phase05_path_checked": str(legacy_path),
        "legacy_phase05_rejected_in_thesis_grade_mode": bool(legacy_rejected),
        "legacy_phase05_rejection_message": legacy_error,
        "active_summary_uses_legacy_realized_path": bool(active_summary_uses_legacy_realized),
        "generated_summary_notebook_uses_legacy_realized_path": bool(generated_summary_uses_legacy_realized),
    }
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
