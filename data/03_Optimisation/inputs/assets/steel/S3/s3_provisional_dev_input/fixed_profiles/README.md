# S3.0b Fixed WAG Profile Packages

This directory is reserved for governed 24-hour development-only fixed activity and demand profile packages for the S3.0b WAG diagnostic.

The current governed profile packages are:

- `c0_wag_fixed_profile_24h_dev.csv`
- `c1_high_drp_eaf_same_output_profile_24h_dev.csv`
- `c1_central_same_output_profile_24h_dev.csv`
- `c1_low_drp_eaf_same_output_profile_24h_dev.csv`
- `c0_s2_13_downstream_profile_24h_dev.csv`
- `c1_central_s2_13_downstream_profile_24h_dev.csv`

Profiles may be added here only when all relevant gates pass:

- the profile is generated from the frozen S2 model and canonical S2 input surfaces, not from a generated run folder;
- the profile builder consumes explicit config or input paths and does not search for latest runs;
- any C1 route-share treatment is identified or separately source-backed in an S3 wrapper, without changing S2;
- mandatory process-use, steam/boiler useful-demand, and site-electricity-demand rows are governed;
- every row carries UTC timestamps, timestep hours, source-stage metadata, artifact ID, artifact hash, review status, and `thesis_usability=false`;
- profile rows are development-only diagnostics, not observed Tata operation and not thesis-grade input.

As of `S3.0b-b3`, C0 has a development-only fixed profile for the first central WAG diagnostic.

As of `S3.0c-b`, C1 has three development-only same-output route/material/WAG-driver profiles. These are S3 wrapper profiles based on user-selected route-share scenarios, not solved S2 route splits and not observed Tata operation. They are suitable for WAG-generation-only validation. Full C1 energy/WAG diagnostics remain blocked until DRP natural-gas, DRP electricity, EAF electricity, site-electricity cap, mandatory-process-demand, and steam/boiler-demand inputs are selected.

As of the S3 downstream accounting audit, C0 and all C1 profiles also include downstream/end-processing accounting-driver rows for secondary metallurgy, continuous casting, slab transfer, reheating or hot-charge boundary, HSM, finished-product boundary, ASU/oxygen, and residual downstream auxiliary boundary. These rows are throughput drivers only. They do not add downstream energy demand, process scheduling, slab storage, DA price response, cost accounting, product revenue, or ETS logic.

As of `S2.13`, this directory also contains two downstream-aware development snapshots exported directly from the S2.13 downstream scheduling model. These are separate governed snapshots for C0 and C1 central downstream physical scheduling. They do not replace the earlier S3.0b/S3.0c WAG fixed profiles, and they remain `thesis_usability=false`.
