# FS4 Similar-Days Methodology Plan

## Status

This note is a **design-only planning artifact** for a future `FS4` workstream.

It does **not** authorize:
- FS4 feature-store execution
- model training
- benchmark reruns
- changes to official comparison outputs

It exists to freeze an academically defensible Huang-inspired methodology before any FS4 implementation begins.

Primary reference:
- Huang et al. (2024), *Applied Energy*, 373, 123863, "A hybrid framework for day-ahead electricity spot-price forecasting: A case study in China", DOI `10.1016/j.apenergy.2024.123863`

## 1. Positioning Inside The Thesis

### 1.1 Active thesis scope

The active scope remains:
- hourly day-ahead electricity price forecasting only
- `NL` as the current market focus
- fixed local-date splits:
  - train: `2022-01-01` to `2023-09-30`
  - validation: `2023-10-01` to `2024-09-30`
  - test: `2024-10-01` to `2025-09-30`
- forecast origin: `08:00` on `D-1` in `Europe/Amsterdam`
- forecast horizon: `D` through `D+4`
- daily rolling-origin refit
- internal UTC storage
- availability-based leakage prevention using `known_at_utc <= forecast_origin_utc`

### 1.2 Why FS4 exists

`FS4` is a future feature-set extension for **similar-days derived price features**.

Its role is different from `FS3`:
- `FS3` adds direct exogenous variables known at forecast time.
- `FS4` transforms causal exogenous and historical information into **retrieved analogous historical days** and then derives price-profile features from those retrieved days.

`FS4` must therefore remain a separate experiment dimension because it introduces:
- a retrieval layer
- a similarity metric
- a lookback-window choice
- a top-`K` construction choice
- a second-order feature-engineering step from retrieved historical prices

That logic is methodologically richer than "add more regressors", so it should not be merged invisibly into `FS3`.

### 1.3 Role in the thesis sequence

The benchmark stack remains conceptually frozen first:
- `FS0`: naive
- `FS1`: explicit endogenous features
- `FS2`: explicit endogenous features plus calendar and holiday structure
- `FS3`: causal exogenous families for the models shortlisted after `FS2`
- `FS4`: future similar-days extension

The thesis logic is:
1. establish baseline and benchmark comparability
2. document causal exogenous additions
3. only then add a retrieval-based feature layer

This sequencing preserves interpretability and prevents the methodology from drifting before the benchmark reference is stable.

## 2. Huang-Inspired Flow To Mirror

The value imported from Huang et al. is the **methodological flow and reporting discipline**, not their final predictive stack.

The future FS4 workflow should follow this sequence:
1. descriptive statistics and within-day distribution analysis for target and candidate exogenous drivers
2. correlation analysis between candidate exogenous drivers and price
3. daily price-pattern analysis through clustering
4. similar-day analysis
5. similar-day feature-construction design
6. only later: feature selection and model comparison

This means the preparatory FS4 notebooks should justify:
- **why** a similarity approach is reasonable in `NL`
- **which** families should drive similarity
- **which** rolling search window is defensible
- **which** derived price features should actually move into the later model-comparison stage

## 3. Conceptual Objective

### 3.1 Problem FS4 is meant to solve

Plain lagged features and direct exogenous features do not explicitly retrieve historical days whose **entire local-day system state** resembles the target day.

FS4 is meant to capture:
- recurring daily price shapes
- regime-like days with similar demand-supply patterns
- analogues that combine recent conditions with calendar structure
- historical price curves that can serve as structured prototypes for the target day

### 3.2 Why this is not the same as ordinary FS3

Two models can use the same causal inputs but differ fundamentally:
- `FS3` asks: "Which direct variables should the model receive?"
- `FS4` asks: "Which historical days look most analogous, and what price-profile information can be extracted from them?"

That distinction matters because `FS4` requires extra methodological choices:
- how a daily profile is represented
- how similarity is scored
- how similarity scores are aggregated
- how top similar days are translated into downstream price features

### 3.3 Recommended thesis framing

In the thesis, `FS4` should be framed as:
- a **retrieval-based feature engineering layer**
- inspired by Huang's day-similarity logic
- adapted to the hourly Dutch day-ahead context
- designed under the same causal and walk-forward constraints as the existing benchmark stack

## 4. Candidate Feature Families For Similarity Search

The table below distinguishes what is conceptually interesting from what is currently available and causally valid in the repo.

| Family | Availability at `D-1 08:00` local | Expected relevance | Collinearity / redundancy | Implementation burden | First-pass status |
| --- | --- | --- | --- | --- | --- |
| `NL` day-ahead total load forecast profile | Directly usable for `D` only under the current `day_ahead_local_08` rule | High | Overlaps with residual-style proxies | Low to medium | **Yes** |
| `NL` day-ahead total generation forecast profile | Directly usable for `D` only under the current `day_ahead_local_08` rule | Medium to high | Correlated with load and price regime | Low to medium | **Yes, secondary** |
| `NL` week-ahead total load forecast profile | Directly usable for `D..D+4` | Medium | Partly overlaps with day-ahead load profile | Low | **Yes, as full-horizon-safe bridge** |
| Lagged `NL` DA price profile from historical days | Historical only, but causally safe before the origin | High | Related to existing lag features but structurally different at daily-profile level | Low | **Yes** |
| Residual proxy such as `DA load forecast - DA generation forecast` | Causal for `D` only if both components are known | Medium | High, because it is derived from two core families | Medium | **Extended sensitivity only** |
| Historical actual generation aggregates by PSR | Historical only | Medium for regime labeling, lower for direct target-day similarity | Can overlap with lagged price and generation totals | Medium to high | **Extended only** |
| Installed-capacity aggregates | Full-horizon-known but nearly flat within day | Low for intraday-shape similarity | High overlap with static system descriptors | Low | **Not a primary similarity driver** |
| Neighbor-market forecast proxies | Depends on family-specific `known_at_utc` handling | Potentially useful | Raises cross-market comparability complexity | Medium to high | **Extended only after domestic method freeze** |
| Wind / solar forecast profiles | **Not currently available as future-known forecast families in the repo** | Potentially high if later added | Would overlap with generation/residual families | High right now because the source is missing | **Not part of first-pass FS4** |

### 4.1 First-pass recommendation on drivers

The first-pass `FS4` design should focus on a small, defensible bundle:
- `NL` day-ahead total load forecast profile for `D`
- `NL` day-ahead total generation forecast profile for `D`
- `NL` week-ahead total load forecast profile as the guidance-safe bridge family
- historical `NL` DA price profiles

### 4.2 What should stay out of first-pass FS4

Do not make first-pass FS4 depend on:
- unavailable future-known wind or PV forecasts
- a broad cross-border similarity design
- static installed-capacity profiles as the main similarity driver
- highly engineered residual families before the core domestic method is frozen

## 5. Daily Profile Representation

### 5.1 Core representation

For similar-day analysis, each candidate day should be represented as a **24-slot local market-day profile**:
- index: local delivery date
- slots: local hours `0` through `23`
- values: target or feature values aligned to those local-hour slots

This is a local-day analytical object, even though storage and causal filtering remain in UTC.

### 5.2 UTC and local-time handling

Internally:
- keep `timestamp_utc`
- keep `known_at_utc`
- build similarity-candidate eligibility with `known_at_utc <= forecast_origin_utc`

For profile construction:
- map each UTC timestamp to `target_delivery_local_date`
- map each UTC timestamp to `target_hour_local`
- build a harmonized 24-slot local-day matrix for each family

### 5.3 DST handling recommendation

Because the market problem is defined in local delivery days, the similar-day representation should be harmonized to 24 local-hour slots even though the true UTC horizon can be `23`, `24`, or `25` hours.

Recommended first-pass rule:
- spring DST day with 23 hours:
  - insert the missing local-hour slot by local-time interpolation
  - mark the day with a DST-adjustment flag
- autumn DST day with 25 hours:
  - collapse the repeated local hour to one slot by simple mean
  - mark the day with a DST-adjustment flag
- non-DST missingness:
  - do **not** silently treat large gaps as acceptable
  - store observed-hour count and imputed-hour count per profile

Important:
- this harmonized 24-slot representation is for **similarity analysis and feature construction only**
- official scoring remains on the original UTC-aligned target schedule

### 5.4 Raw levels versus standardized shapes

Both matter, but they should play different roles.

Recommended first-pass representation:
- use **shape-standardized 24-slot profiles** for the main similarity score
- keep **level summaries** as separate descriptors rather than embedding them directly in the first ranking rule

Suggested shape standardization:
- z-score within each daily profile after DST harmonization and quality filtering

Suggested level summaries to store alongside each day:
- daily mean
- daily standard deviation
- daily min / max
- daily range
- total or average load / generation if relevant

### 5.5 Is Pearson alone enough?

For the first baseline, yes.

To stay close to Huang:
- the baseline feature-based similarity should use absolute Pearson correlation on standardized daily profiles

However, the notebook analysis should explicitly check:
- how often top-ranked candidates have materially different daily levels
- whether a mild level-distance penalty would materially change the ranking

Recommendation:
- **baseline**: Pearson-only ranking on standardized shapes
- **sensitivity check**: Pearson plus a simple level-distance penalty
- do not make the first operational definition more complex than that

### 5.6 Quality filter recommendation

Because the cleaned target data is not fully gap-free, every profile used in FS4 analysis should carry a quality record.

Recommended first-pass filters:
- observed local-hour slots must be at least `23` after excluding known DST structure
- non-DST imputation share should be small and explicitly recorded
- historical price profiles may use the already approved deterministic feature-source series for feature construction
- gap-filled values must never be used for official scoring

## 6. Similar-Day Families To Evaluate

Three Huang-style families should be documented and compared.

### 6.1 Family A: time-lag similar days

#### Mathematical intuition

This family does not search across a large candidate set. It treats a small set of pre-defined historical offsets as interpretable analogues.

For target day `d`, define a lag set:

`L = {1, 2, 3, 7, 14, 21, 28, 35, 42, 49, 56}`

Then the candidate family is:

`C_TL(d) = {d - l : l in L, day available at origin}`

#### Exact inputs

- historical `NL` DA price profiles
- optionally historical exogenous summaries for annotation, not for ranking

#### Ranking method

Baseline ranking:
- fixed deterministic lag priority in the order shown above
- tie-breaker not needed because the set is pre-ordered

Optional sensitivity:
- add seasonal anchors such as `364` or `371` days only if the validation analysis shows clear benefit

#### Strengths

- maximally causal
- trivial to interpret
- easy to compare against plain lag benchmarks
- low implementation burden

#### Weaknesses

- not a true feature-driven search
- can miss structurally similar but non-recent days
- may overemphasize recency even when annual seasonality matters

#### Leakage risks

- very low, provided all lagged candidate days satisfy `known_at_utc <= forecast_origin_utc`

#### First-pass recommendation

- **Include**
- treat this as the deterministic reference family for FS4

### 6.2 Family B: feature-based similar days

#### Mathematical intuition

This family ranks historical candidate days according to how similar their daily feature profiles are to the target day's causal feature profiles.

For target day `d`, candidate day `c`, and feature family `f` with harmonized 24-slot profiles `x_f(d)` and `x_f(c)`:

`sim_f(d, c) = |corr(x_f(d), x_f(c))|`

For a bundle of feature families `F`:

`sim_FB(d, c) = mean_f sim_f(d, c)`

computed only over families available for both `d` and `c`.

#### Exact inputs

Recommended first-pass bundle:
- `NL` day-ahead total load forecast profile for `D`
- `NL` day-ahead total generation forecast profile for `D`
- `NL` week-ahead total load forecast profile where full-horizon-safe support is needed
- optional historical price-profile descriptor as a separate similarity bundle, not mixed blindly into exogenous similarity

#### Ranking method

- define a rolling historical candidate pool within a chosen lookback window
- compute `sim_FB(d, c)` for each eligible candidate day
- rank descending by `sim_FB`
- tie-break by lower imputation share, then by recency

#### Strengths

- closest to Huang's feature-driven day-similarity idea
- interpretable at the family level
- can be inspected through example tables and recency-bucket summaries

#### Weaknesses

- Pearson-only shape matching ignores absolute daily level by construction
- absolute correlation can reward inverted profiles, so diagnostics are required
- mixed-family averaging can hide dominance by one family

#### Leakage risks

- using a target-day family that is not known by `D-1 08:00` local
- using validation or test information to preselect candidate bundles
- using future price-cluster information from the target day

#### First-pass recommendation

- **Include**
- this should be the main Huang-aligned operational family in the first FS4 pass

### 6.3 Family C: aggregate-weighted similar days

#### Mathematical intuition

This family combines per-family similarity scores with data-driven weights derived from feature-price association strength.

Let `H_t` denote the historical calibration days available at a forecast origin.
For each feature family `f`, define a family relevance statistic:

`a_f = mean_{h in H_t} |corr(x_f(h), y(h))|`

where `y(h)` is the historical daily price profile for day `h`.

Then transform these relevance statistics with a softmax:

`w_f = exp(tau * a_f) / sum_j exp(tau * a_j)`

with `tau > 0` as a temperature parameter.

The aggregate-weighted similarity is:

`sim_AW(d, c) = sum_f w_f * sim_f(d, c)`

#### Exact inputs

- the same per-family profile matrices used in the feature-based family
- historical price profiles for the weight-calibration step

#### Ranking method

- estimate `a_f` using only history available at the origin
- convert to `w_f`
- compute `sim_AW(d, c)` over the candidate pool
- rank descending by `sim_AW`

#### Strengths

- retains Huang's weighted-similarity logic
- gives a transparent bridge between correlation screening and similarity search
- allows later reporting of family influence

#### Weaknesses

- more computationally involved
- can be unstable if weights are estimated from too little history
- introduces an extra tuning object through `tau`

#### Leakage risks

- estimating `a_f` on validation or test days that should not be visible at the origin
- tuning `tau` on the test set

#### First-pass recommendation

- **Analyze conceptually now**
- **defer to extended experiments for execution**

Reason:
- it is methodologically valuable
- but it adds enough moving parts that the first operational FS4 benchmark should start with time-lag plus feature-based similarity before promoting the weighted version

## 7. Lookback-Window Methodology

The lookback window should not be chosen ad hoc.

### 7.1 Huang-style exploratory design

The exploratory analysis should begin with a **long-window study** and only later choose a shorter operational window.

Recommended candidate windows:
- `30` local days
- `60` local days
- `90` local days
- `180` local days
- `365` local days

### 7.2 What the analysis should measure

For each similarity family and each candidate window, record on the validation period:
- top-`K` similar days per target day
- similarity-score distribution
- candidate-day age in days
- imputation share and eligibility rate
- how often the top similar days come from short, medium, and long recency buckets

### 7.3 Recency-bucket design

Recommended bucket table:
- `1-7` days
- `8-30` days
- `31-90` days
- `91-180` days
- `181-365` days
- `366+` days, when available

The resulting table should show the proportion of top-ranked similar days drawn from each bucket.

### 7.4 Interpretation objective

This analysis should answer:
- are the most useful analogues mostly recent?
- do annual-season candidates actually appear often enough to justify a longer window?
- does a long window mostly add stale days from different market regimes?

For the Dutch hourly market, this tradeoff matters because:
- there is meaningful annual seasonality
- but the `2022-2025` period also contains regime shifts, including crisis-era levels and later normalization

### 7.5 First-pass recommendation on the operational window

Recommended first-pass operational rule:
- use a **90-day rolling candidate window** for feature-based similarity
- keep the separate time-lag family for deterministic weekly structure
- test annual anchors only as an extension if the validation recency-bucket analysis justifies them

Why `90` days is the recommended starting point:
- it is long enough to contain multiple weekday cycles and weather regimes
- it is short enough to limit contamination from much older price regimes
- it balances recent market state against the need for a non-trivial candidate pool

This is a recommendation to **start from**, not a claim that Huang's shorter final window automatically transfers to `NL`.

## 8. Price-Pattern Analysis

FS4 should include a Huang-style daily price-pattern study before feature construction.

### 8.1 Clustering target object

Cluster **historical daily `NL` DA price profiles** after converting them into harmonized 24-slot local-day profiles.

### 8.2 Recommended first method

Use `k`-means on standardized 24-hour price profiles because it is:
- simple
- reproducible
- already familiar to a thesis audience
- easy to report through cluster centroids

### 8.3 How to choose `k`

Evaluate candidate `k` values, for example `3` through `8`, using:
- silhouette score
- Davies-Bouldin index
- minimum cluster-size sanity checks
- visual interpretability of centroid profiles
- stability across train versus validation

No single criterion should dominate. The chosen `k` must be both quantitatively acceptable and qualitatively interpretable.

### 8.4 What to report

Produce:
- a centroid-profile figure for each cluster
- a summary table with:
  - cluster size
  - share of days
  - mean price
  - average intraday range
  - average daily standard deviation
  - share of negative-price hours
  - weekend / holiday share
  - seasonal composition

### 8.5 Why clustering helps FS4

Clustering is useful for FS4 because it:
- shows whether a small number of recurring Dutch price-shape regimes exists
- helps explain why some similar days are more plausible analogues than others
- enables a later cluster-conditioned aggregation of similar-day price profiles

Important causal note:
- cluster labels may be used for **historical candidate days**
- the unknown future target-day price cluster must not be used directly at forecast time

## 9. Similar-Day Feature Construction

The future `FS4` feature store should group features into clearly labeled categories.

### 9.1 Category A: direct top-`K` similar-day price profiles

For each target local hour `h`, store the same-hour price from the top-ranked candidate days.

Examples:
- top-1 similar-day price at hour `h`
- top-2 similar-day price at hour `h`
- top-3 similar-day price at hour `h`

These are easy to interpret and stay close to the analog-day idea.

### 9.2 Category B: weighted-average similar-day price profile

For each hour `h`, compute:

`p_bar(h) = sum_{k=1..K} alpha_k * p_k(h)`

where:
- `p_k(h)` is the candidate day's price at local hour `h`
- `alpha_k` is a normalized similarity weight

Recommended first-pass weighting:
- softmax or simple normalized rank weights over the top `K`

### 9.3 Category C: cluster-conditioned weighted-average price profile

Use historical price-cluster labels of the retrieved candidate days.

Causal version:
- identify the dominant cluster among the top `M` retrieved historical candidates
- compute a weighted average using only candidates from that dominant historical cluster

This avoids using the unknown future target cluster directly.

### 9.4 Category D: recency-aware variants

Optional extension:
- multiply similarity weights by a mild recency discount
- only promote this if the window analysis shows a clear recent-day premium

### 9.5 Category E: similarity-score metadata

Store scalar descriptors such as:
- top-1 similarity score
- mean top-`K` similarity score
- top-1 minus top-2 score gap
- age in days of the top similar day
- cluster concentration among top candidates
- candidate-profile imputation share

These features can help LEAR and XGBoost interpret confidence or regime tightness.

### 9.6 Category F: distributional summaries across similar days

Optional extension:
- per-hour median
- per-hour interquartile range
- per-hour lower / upper quantiles across top similar days

These are useful for richer descriptive analysis and possible future probabilistic extensions, but should not bloat the first operational `FS4`.

### 9.7 Recommended first-pass FS4 feature set

The first operational `FS4` feature set should stay deliberately small:
- feature-based similarity family as the main retrieval engine
- `90`-day candidate window
- top-`K = 3` or `5` candidate days
- direct top-1 price profile
- weighted-average top-`K` price profile
- a few similarity metadata features:
  - top-1 score
  - mean top-`K` score
  - age of top-1 day

Time-lag family should be retained as a transparent reference and possible additive source.

### 9.8 Recommended extended set

Only after the first-pass design is frozen should the following be explored:
- aggregate-weighted similarity family
- residual-style similarity drivers
- cluster-conditioned weighted averages
- per-hour medians and quantiles
- cross-border similarity drivers
- annual anchor extensions

## 10. Reporting Style

The preparatory analysis should follow a Huang-like reporting sequence.

The notebooks should later produce at minimum:
1. a workflow figure or structured methodology summary
2. a figure with within-day distributions of the target and candidate feature families
3. a descriptive-statistics plus Pearson-correlation table
4. a daily price-pattern cluster figure plus summary table
5. a similar-day window-analysis figure
6. a table with example top similar days for one or more target days
7. a table with top-similar-day proportions by recency bucket
8. a final methodological decision summary table

Later phases, but not this planning task, may add placeholders for:
- selected-feature importance tables
- model-comparison metrics tables
- selected case-day forecast plots

## 11. Evaluation And Later Comparison Policy

### 11.1 Later evaluation rule

When `FS4` is eventually executed, it must remain a separate feature-set experiment dimension.

Later fair comparison should be:
- `LEAR`
- `XGBoost`

Optional only with strong justification:
- `Prophet`, but only if the regressor set remains compact and causal

under the same:
- split chronology
- daily rolling-origin schedule
- forecast origin
- horizon logic
- storage schema
- metric definitions

### 11.2 Freeze policy

Methodological choices for `FS4` should be frozen using:
- train data for fitting descriptive structures when appropriate
- validation data for design decisions and promotion choices

The test period must remain untouched until the methodology is frozen.

### 11.3 Metrics

The later project-standard reporting must keep:
- `MAE`
- `RMSE`
- `bias`
- `rMAE`
- Diebold-Mariano tests where feasible

In addition, the Huang-style descriptive reporting should be preserved for interpretability.

### 11.4 Recommended first execution path

Because `D`-only direct day-ahead feature availability is much cleaner than `D+1..D+4`, the first eventual operational `FS4` experiment should likely mirror the existing branching logic used elsewhere in the repo:
- `D` may use the full `FS4` similar-day construction
- `D+1..D+4` should remain on a guidance-safe backbone unless a full-horizon-safe similarity design is explicitly built and justified

That keeps the first execution causally defensible and aligned with the current pipeline architecture.

## 12. What Not To Copy From Huang

The following should be stated explicitly in the thesis and in the notebooks:

- Huang's market design is not Dutch EPEX and should not be treated as directly portable.
- Huang's quarter-hourly `96`-point setup is not the same as this hourly `24`-slot local-day problem.
- Huang's DNN plus ATPE stack is not the immediate objective of this workstream.
- Huang's reported error scale is not directly comparable to raw Dutch `EUR/MWh` results.
- Huang's candidate variables may not all exist, and some may not be causally valid under the repo's `known_at_utc` rules.
- The value imported here is the workflow, the similar-day logic, and the reporting style, not blind replication.

## 13. Immediate Implementation Boundary

This planning phase should stop after:
- documenting the methodology
- creating the notebook skeletons
- listing explicit TODOs for later execution

This planning phase should **not**:
- build the final FS4 feature store
- train LEAR or XGBoost with FS4
- rerun benchmark suites
- update official comparison artifacts

## 14. TODO Summary For Later Implementation

### Notebook 13

Freeze:
- candidate family list
- causal eligibility rules
- profile quality filters
- clustering protocol

### Notebook 14

Freeze:
- similar-day family definitions
- lookback-window choice
- top-`K` choice
- whether aggregate weighting is promoted beyond concept stage

### Notebook 15

Freeze:
- final first-pass FS4 feature categories
- storage schema additions
- walk-forward compatibility design
- reporting obligations for the later execution phase
