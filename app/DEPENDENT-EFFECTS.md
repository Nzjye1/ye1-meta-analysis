# Related effects in the same study

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


`./launch.cmd meta dependent --input effects.csv --plan dependent_plan.json --rscript $rscript --out fresh-result` uses project-private [`metafor` 5.2-1](https://cran.r-project.org/package=metafor) `rma.mv` and [`clubSandwich` 0.7.0](https://cran.r-project.org/package=clubSandwich) CR2/Satterthwaite inference. This is a separate route for multiple **related estimates of one prespecified construct, contrast, outcome, timepoint, population, adjustment and unit**. It does not silently route repeated rows through the independent-study pairwise model.

Input CSV: `study_id,cohort_id,effect_id,estimate,se,effect_type,outcome,timepoint,contrast,adjustment,population,effect_unit,effect_definition,source_file,source_sha256,source_location`. A study may have several unique effect IDs, but every effect in that study must refer to the same labeled cohort. A cohort ID may not appear under another study. At least three independent study clusters and some multiple effects are required. Each effect definition is unique within its study. Ratio effects RR/OR/HR are **entered as log ratios with log-scale SE**; MD/SMD use a common linear unit or `standardized` for SMD. The input format does not convert raw arms or resolve hidden cohort overlaps.

Plan JSON: `schema=meta-dependent-plan-v1`, `source_kind=synthetic_fixture|reviewed_extraction`, `model=rma.mv_nested_REML_CR2`, `effect_type`, `input_scale=log_ratio|linear`, `outcome,timepoint,contrast,adjustment,population,effect_unit,effect_direction,dependency_rationale`, `alpha`, `rho_values` (two to five distinct values in [0, .95)) and `primary_rho` (one of those values). Real input additionally has `review_status=human_reviewed_claim`. The working within-study sampling covariance is **assumed equicorrelation**: diagonal `SE²`, off-diagonal `rho × SEᵢ × SEⱼ`; all rho values are run as prespecified sensitivity analyses. The R engine checks positive definiteness, fits nested study/effect random intercepts with REML, and computes cluster-robust CR2 intervals and Satterthwaite degrees of freedom. The assumed correlation is not recovered from the published summary estimates. A warning flags fewer than ten independent clusters; a numerically non-estimable CR2 result fails rather than becoming a final result.

Outputs: checked effects, primary working covariance table, one pooled estimate/CR2 CI/df per rho, study/effect variance components, primary forest, rho-sensitivity plot, factual report and SHA-256 receipt. Ratio estimates are exponentiated only for display. Source hashes check local bytes, not whether the effects truly measure one construct. The route blocks mixed scales/outcomes/timepoints/adjustments/units, duplicate cohorts under different study IDs, duplicate effect definitions, invalid rho, stale or missing source and existing output. It does **not** support arbitrary known covariance matrices, multivariate cross-outcome modeling, multiple timepoints, network effects, or verified review-level clinical exchangeability.
