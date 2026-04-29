from __future__ import annotations

from hourly_da.core.config import HourlyDAPipelineConfig
from hourly_da.core.run_storage_policy import apply_default_storage_policy, format_storage_summary_lines


def main() -> None:
    config = HourlyDAPipelineConfig()
    summary = apply_default_storage_policy(config.output_root)
    for line in format_storage_summary_lines(summary):
        print(line)


if __name__ == "__main__":
    main()
