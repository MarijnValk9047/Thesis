"""Run the C5 downstream origin-tag audit."""

from __future__ import annotations

from steel.s4_4c5p_al_downstream_origin_tag_audit import run_downstream_origin_tag_audit


if __name__ == "__main__":
    print(run_downstream_origin_tag_audit()["summary"])
