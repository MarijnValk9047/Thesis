from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OutputPolicy:
    name: str
    save_timeseries: bool
    save_figures: bool
    include_audit_manifest: bool
    include_solver_logs_for_failures: bool
    include_solver_logs_for_audit_days: bool
    retain_nested_day_outputs: bool

    def should_persist_solver_log(self, *, solver_status: str, audit_day: bool = False) -> bool:
        status_text = str(solver_status).strip().lower()
        solved_optimally = status_text == "optimal" or status_text.startswith("optimal")
        if audit_day and self.include_solver_logs_for_audit_days:
            return True
        if not solved_optimally and self.include_solver_logs_for_failures:
            return True
        return False


def get_output_policy(name: str) -> OutputPolicy:
    normalized = str(name).strip().lower()
    if normalized == "minimal":
        return OutputPolicy(
            name="minimal",
            save_timeseries=False,
            save_figures=False,
            include_audit_manifest=False,
            include_solver_logs_for_failures=True,
            include_solver_logs_for_audit_days=True,
            retain_nested_day_outputs=False,
        )
    if normalized == "audit":
        return OutputPolicy(
            name="audit",
            save_timeseries=True,
            save_figures=False,
            include_audit_manifest=True,
            include_solver_logs_for_failures=True,
            include_solver_logs_for_audit_days=True,
            retain_nested_day_outputs=True,
        )
    if normalized == "full":
        return OutputPolicy(
            name="full",
            save_timeseries=True,
            save_figures=True,
            include_audit_manifest=True,
            include_solver_logs_for_failures=True,
            include_solver_logs_for_audit_days=True,
            retain_nested_day_outputs=True,
        )
    raise ValueError(f"Unsupported output policy: {name!r}")
