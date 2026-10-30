# Connected network meta-analysis

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


`./launch.cmd meta network --input contrasts.csv --plan network_plan.json --rscript $rscript --out fresh-result` runs a connected-treatment network with project-private `netmeta` 3.7-0. The contrast CSV requires `study_id,cohort_id,treat1,treat2,TE,seTE,effect_type,outcome,timepoint,adjustment,source_file,source_sha256,source_location`. `TE` is the effect for `treat1` relative to `treat2`: MD is on its linear unit; OR/RR must be entered on the log scale with its standard error. The method does not derive arm-level effects or convert raw percentages. Every contrast has a local source hash and locator. Package examples use `dataset row N`; synthetic fixtures use `synthetic row N`; real extractions use page/table/figure locators.

The JSON plan uses `schema=meta-network-plan-v1`, `source_kind`, `reference_treatment`, `outcome`, `timepoint`, `adjustment`, `effect_type` (MD, OR or RR), `effect_direction`, `model` (FE or RE), `tau_method` (FE/NONE, RE/REML or prespecified RE/DL), `alpha`, `small_values` (`good` or `bad`), `multiarm_policy` (`two_arm_only` or `allow_complete_multiarm`), and a nonempty user-supplied `transitivity_rationale`. `reviewed_extraction` adds `review_status=human_reviewed_claim`; this is not authenticated. The analysis checks one effect scale/outcome/timepoint/adjustment, positive SE, unique cohorts across studies, treatment connectivity, declared reference, and a complete set of pairwise contrasts within each multi-arm study. A missing multi-arm edge is blocked. `netmeta` performs its own internal multi-arm consistency/covariance handling after these checks; arms are not counted as independent studies. Shared populations concealed behind different IDs remain a human responsibility.

Outputs: `network_summary.csv` with Q heterogeneity and design-by-treatment inconsistency status/statistics; `local_inconsistency.csv` for estimable direct versus indirect splits; `reference_effects.csv`; all-pair `league_table.csv`; `ranking.csv` with P-scores; `network_graph.png`; `reference_forest.png`; SVG copies of both figures; a factual report and integrity receipt. Figures use the fitted confidence limits, configured effect/reference/model and actual network counts. Equal-size graph nodes do not imply participant totals. FE is a constrained common-effect model; tau² is fixed at zero for its report. RE uses the planned REML or DL estimator; an omitted RE tau_method retains the REML compatibility default. The actual estimator is checked against the plan and saved in the receipt. When the network has no independent inconsistency degrees of freedom, the status is explicitly `NOT_ESTIMABLE`, not evidence of agreement. P-scores are model rankings, **not** probabilities of clinical benefit or certainty grades. Local p-values are exploratory and may be sparse.

The protocol-to-draft route is in [NETWORK-PROJECT.md](NETWORK-PROJECT.md).
