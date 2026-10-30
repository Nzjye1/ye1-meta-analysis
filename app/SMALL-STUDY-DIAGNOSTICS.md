# Exploratory influence and small study diagnostics

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


`small_study_test.csv` separates `asymmetry_slope`, the standard-error coefficient tested by z/p, from `limit_effect` and its CI, the fitted effect extrapolated to standard error zero. The latter is not the test coefficient.

For an existing **protocol-bound** pairwise RR, OR, HR, MD or SMD result with at least three independent study effects, run:

```powershell
./launch.cmd meta small-study --stats-dir bound-result --confirmation confirmation.json --rscript E:/Tools/R/R-4.6.1/bin/Rscript.exe --out fresh-diagnostics
```

The wrapper rechecks the confirmation, current base R script, and every bound result file, then reconstructs the exact FE or REML `metafor::rma.uni` result before diagnostics. It writes `influence.csv` (studentized residual, DFFITS, Cook distance, covariance ratio, leverage, weight, package influence flag), `funnel.png`, `small_study_test.csv`, a factual Markdown appendix and a hash receipt. It never rewrites the pooled result. Flagged studies are prompts for source and sensitivity review, not automatic exclusions.

The `metafor::regtest` standard-error asymmetry regression runs only at **10 or more independent studies**. Under 10 it emits `NOT_RUN_LOW_K`; if standard errors make the added predictor unidentifiable, it emits `NOT_ESTIMABLE` with the method error instead of a fabricated p value. A funnel plot may still be produced for context, with the low-k status on the image. Asymmetry can reflect heterogeneity, chance, study design or selection; it does not prove publication bias. A nonsignificant test does not establish absence of bias. The eventual GRADE publication-bias judgment remains with reviewers.
