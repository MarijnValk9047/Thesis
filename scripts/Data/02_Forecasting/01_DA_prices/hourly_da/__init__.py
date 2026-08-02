from .core.config import HourlyDAPipelineConfig


_NOTEBOOK_EXPORTS = {
    "estimate_run_duration_seconds",
    "format_duration",
    "load_selected_case_weeks",
    "run_suite_with_feedback",
}


def __getattr__(name: str):
    """Load notebook-only helpers lazily so CLI pipelines do not require IPython."""
    if name in _NOTEBOOK_EXPORTS:
        from . import notebook_support

        return getattr(notebook_support, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "HourlyDAPipelineConfig",
    "estimate_run_duration_seconds",
    "format_duration",
    "load_selected_case_weeks",
    "run_suite_with_feedback",
]
