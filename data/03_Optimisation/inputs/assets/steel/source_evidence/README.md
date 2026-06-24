# Steel Source Evidence

This directory contains the canonical steel source-card and candidate parameter-evidence surfaces.

Source-card metadata is separate from parameter evidence. Source cards identify stable public documents, reports, regulations, datasets, or other evidence-bearing sources. Parameter-evidence rows record extracted candidate values, ranges, rules, validation targets, assumptions, sensitivities, or blocked evidence claims linked back to canonical source-card IDs.

Candidate evidence is separate from approved model input. Research memos are discovery aids and are not primary evidence. A research memo may be listed as discovery provenance, but it cannot replace the underlying source document.

No row in this directory is executable unless a later governed approved-input table explicitly promotes it. No approved model inputs are created here.

Future source-card IDs should use the canonical sequence `STEEL-SC-0001`, `STEEL-SC-0002`, and so on. Draft IDs from research memos or external conversion files are discovery identifiers unless they are explicitly mapped into this sequence.

For S3 final thesis model assumptions, use the separate evidence-use policy in `docs/optimisation/steel/S3/STEEL_S3_EVIDENCE_USE_AND_THESIS_ASSUMPTION_POLICY.md` and the governed S3 policy CSVs under `data/03_Optimisation/inputs/assets/steel/S3/s3_candidate_review/`. That policy separates final thesis model assumptions from validation claims and Tata-exact public claims. It does not promote candidate evidence rows or approved input rows automatically.
