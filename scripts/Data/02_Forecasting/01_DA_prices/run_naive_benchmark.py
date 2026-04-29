from __future__ import annotations

from dataclasses import replace

from hourly_da.core.config import HourlyDAPipelineConfig
from hourly_da.core.pipeline import run_benchmark_suite
from hourly_da.core.run_storage_policy import apply_default_storage_policy, format_storage_summary_lines
from hourly_da.models.registry import build_naive_baseline_models


def main() -> None:
    config = replace(HourlyDAPipelineConfig())
    models = build_naive_baseline_models()
    run_id, _, _, _, official_naive = run_benchmark_suite(
        config=config,
        run_label="naive_benchmark",
        models=models,
        show_progress=True,
        progress_label="naive_benchmark",
    )
    print(f"Run completed: {run_id}")
    print(f"Naive models included: {[model.name for model in models]}")
    print(f"Selected naive benchmark on validation: {official_naive['model']} (MAE={official_naive['mae']:.4f})")
    storage_summary = apply_default_storage_policy(config.output_root)
    for line in format_storage_summary_lines(storage_summary):
        print(line)


if __name__ == "__main__":
    main()
