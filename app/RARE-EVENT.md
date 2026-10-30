# Independent two arm binary counts

> 从源码根目录执行命令。`$runtime` 是用户已确认可用的依赖目录；源码 ZIP 不含该目录。路径均为可替换的示例。

```powershell
$runtime = 'C:/Meta Runtime'
$rscript = Join-Path $runtime 'native/R/bin/Rscript.exe'
$env:META_PYTHON = Join-Path $runtime 'native/python/python.exe'
$env:META_RSCRIPT = $rscript
$env:META_R_LIBRARY = Join-Path $runtime 'libraries/r-extended'
$env:META_METHOD_PYTHON_LIBRARY = Join-Path $runtime 'python/standard'
$env:META_FRONTEND_PYTHON_LIBRARY = $null
$env:PYTHONPATH = $env:META_METHOD_PYTHON_LIBRARY
$env:PYTHONUTF8 = '1'
```


For an analysis Word report from existing supplied aggregate data, use the [MH aggregate report出口](RARE-AGGREGATE-REPORT.md). This separate source-bound reporting route does not require invented screening or review approvals and does not relax the full systematic-review manuscript gates below.

Use the local `launch.cmd meta rare --input tables.csv --plan plan.json --rscript $rscript --out NEW_DIR` route for independent, unadjusted 2x2 endpoint counts. It supports fixed Mantel-Haenszel (MH) RR or OR, individual study effects, a separate inverse-variance fixed-effect sensitivity, optional OR-only Peto, and leave-one-out analysis. It does not silently choose a random-effects model. The clinical meaning, independence and source extraction require review.

`tables.csv` has one row per independent study: `record_id,study_id,cohort_id,events_t,n_t,events_c,n_c,outcome,timepoint,contrast,population,scale_direction,source_file,source_sha256,source_location`. Counts are integers within positive arm totals. A valid locator and matching source hash do not independently verify the article. Adjusted effects, overlapping cohorts and mixed endpoints or timepoints do not belong in this route. One to 200 input tables are accepted, including source rows that are excluded from the relative-effect pool.

## Explicit correction configuration

The plan retains schema `meta-rare-event-analysis-v1`, `effect_type=RR` or `OR`, `model=MH_fixed`, `source_kind=synthetic_fixture` or `reviewed_extraction`, boolean `peto_sensitivity` (OR only), `alpha`, and nonblank `outcome,timepoint,contrast,population,scale_direction`. Direction is `event_adverse` or `event_benefit`. Real input needs `review_status=human_reviewed_claim`; this remains a claim, not software authentication.

| Field | Default | Meaning |
|---|---|---|
| `individual_effect_correction` | `half_all_cells_if_any_zero` | For a study with any zero cell, add 0.5 to **all four cells**, so each arm total increases by 1. Used for study plots, individual log variance, Q weights and the separate IV sensitivity. |
| `pooled_MH_correction` | `none` | Use original counts for MH pooling and its variance. This preserves the previous numerical default. |
| `pooled_MH_correction` | explicit `revman_0.5` option | Add 0.5 to all four cells of each study with any zero, and increase each arm total by 1, before MH pooling and its variance. No-zero studies remain unchanged. |
| `double_zero_policy` | `exclude_with_trace` | Exclude both-arms-zero-event and both-arms-all-event studies from the relative-effect pool and retain their original counts and reason in the source trace. |
| `cmh_test_correction` | `false` | Controls the CMH test correction only. It is not the pooled RR/OR correction switch. |

Legacy `study_display_add=0.5` and `double_boundary_policy=exclude_with_trace` are still accepted. Missing canonical fields resolve to the defaults above and appear explicitly in the engine plan and receipt. Conflicting or unsupported policies are rejected. The RevMan-compatible option is an explicit compatibility configuration; an article's mention of RevMan alone does not establish the authors' exact zero-cell settings.

The engine uses `metafor::rma.mh(add=c(0.5,0),to=c("only0","none"))` by default and `add=c(0.5,0.5),to=c("only0","only0")` for the compatible option. Boundary studies are excluded before either fit. Scalar `add` in metafor applies to individual effects; a two-element vector independently controls individual effects and MH pooling. `correct` controls the CMH test, not pooling. See the [metafor reference](https://wviechtb.github.io/metafor/reference/rma.mh.html) and [Cochrane RevMan algorithms](https://training.cochrane.org/handbook/current/statistical-methods-revman5), pages 2-6.

## Heterogeneity and weights

Q is `sum((yi-log(MH))^2/vi)`, using individual corrected log effects `yi`, individual variance `vi`, and the configured MH center. Its degrees of freedom are the informative study count minus 1; Q p uses chi-square and I2 is `max(0,(Q-df)/Q)*100` (zero if Q is zero). This follows the MH heterogeneity formula, distinct from Q centered on an IV pooled estimate. The engine does not use an uncorrected individual-effect Q when zero cells make it undefined. `tau2=0` is the fixed-model assumption, not an estimate of absent heterogeneity.

The study trace exports separate MH denominator weights (`c*n1/N` for RR, `b*c/N` for OR), their percentages, MH numerator contributions, and Q's IV weights `1/vi` with percentages. Here `a,b,c,d,n1,n2,N` are the configured pooling counts and totals. A study with zero MH denominator weight can still have a nonzero numerator contribution; its corrected displayed ratio must not be multiplied by the uncorrected MH weight to reconstruct pooling. Forest square sizes indicate the MH denominator weights; the plotted individual ratios use the individual correction.

## Estimability and leave one out

Every supplied study is omitted once, including excluded boundary studies, with the selected configuration unchanged. `rare_leave_one_out.csv` and its PNG report configured MH effects and heterogeneity. If one informative study remains, a finite configured effect and interval are reported as `SINGLE_STUDY_ESTIMABLE`; Q, df, Q p and I2 are blank and marked not applicable. If MH cannot estimate a finite positive ratio and interval, those fields stay blank with `NOT_ESTIMABLE_MH`. Corrected single-study display effects are reported separately and never substituted into the MH fields. Zero informative studies produce a traced `NOT_ESTIMABLE_NO_INFORMATIVE_STUDIES` result and labeled plot. Successful output creation does not mean an effect was estimable.

Outputs include `rare_summary.csv`, `study_trace.csv`, `rare_forest.png`, `rare_leave_one_out.csv`, `rare_leave_one_out.png`, `fact_report.md`, checked counts, normalized engine plan, engine conditions in `engine_warnings.csv`, full child stdout/stderr, and a hash receipt containing the resolved plan and command. All source and study rows remain local.

## Reviewed manuscript route

`rare-confirm` takes `--protocol --records --dedup --decisions --report-map --input --study-review --out`; `rare-paper` takes the same inputs plus `--confirmation --narrative --rscript --out`. The protocol (`meta-rare-event-project-v1`) binds the analysis plan, PICO, source-review claim, screening and approval. Follow [the customer workflow](CUSTOMER-WORKFLOW.md); real method or source review cannot be replaced by synthetic approval. `method-prepare` can route `comparative_effect` / `independent_sparse_two_arm_event_counts` through analyze, confirm and paper. The manuscript carries the resolved correction policies, MH heterogeneity, separate IV sensitivity, leave-one-out table and both figures. It remains non-final.

For a source-bound SoF, use `meta method-sof` with `method=rare` and a blank selector; see [METHOD-SOF.md](METHOD-SOF.md). The adapter preserves the selected MH correction and unavailable intervals. A sourced and reviewed applicable comparator risk can be converted only when the MH ratio is estimable. `prisma-article --method-sof` may attach the resulting non-final facts. Optional Peto is sensitivity only and can mislead with imbalanced arms, nonrare events or large effects. No method here establishes a publishable clinical conclusion.
