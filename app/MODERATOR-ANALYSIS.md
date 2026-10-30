# Subgroup and meta-regression extension

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


This extension uses installed `metafor` 5.2-1 on a single, already validated pairwise effect scale. It supports a categorical subgroup comparison, or one to three continuous/categorical moderators in a single variable or multivariable meta-regression. No individual patient model, causal interaction claim, network model, or dependence correction is implied. The original pooled result is never overwritten.

Prepare `moderator_plan.json`:

```json
{"schema":"meta-moderator-plan-v1","mode":"subgroup","intent":"exploratory","hypothesis":"Specify the expected subgroup contrast","effect_direction":"Define which effect direction favors which arm","moderators":[{"name":"group","type":"categorical","reference":"control"}]}
```

`mode` is `subgroup` (one categorical moderator) or `meta_regression` (one to three moderators). A continuous moderator uses `"reference":""`; categorical reference must be an observed value. `intent` is `exploratory` or `confirmed_protocol`. The latter requires a protocol-bound statistics directory, its original confirmation and protocol, and an exact matching `moderator_analysis` object in that **already confirmed** protocol. It means declared in the locally confirmed plan, not independently registered or publicly preregistered. A direct numeric result can only be exploratory.

`moderators.csv` must contain exactly one row per independent `study_id`, with `source_file,source_sha256,source_location` and one column per named moderator. The source file must exist locally and the locator identify a page/table/figure. This checks local bytes and shape, not correct covariate interpretation. For a confirmed protocol-bound run:

```powershell
./launch.cmd meta moderators --stats-dir BOUND_STATS --plan moderator_plan.json --moderators moderators.csv --confirmation confirmation.json --protocol protocol.json --rscript $rscript --out FRESH_DIR
```

For exploratory direct numeric results from `run_meta.R`, omit `--confirmation` and `--protocol`. The command verifies the original input MD5 values and script identity. For bound results it checks the confirmation and all result SHA-256 values. It then checks study/cohort uniqueness, exact moderator coverage, reference levels, varying numeric predictors, full-rank design, and positive residual degrees of freedom. There is no arbitrary minimum study count; when residual df <4 or studies <10, outputs carry explicit interpretation warnings. A subgroup with one study is reported as a single-study description, not a pooled subgroup estimate.

Outputs: `moderator_coefficients.csv` (regression coefficients and CI on the **analysis scale**, hence log scale for RR/OR/HR), `moderator_model.csv` (QM omnibus/between-group test, QE residual heterogeneity, I², tau², df and warnings), `moderator_trace.csv`, `coefficient_plot.png`, `moderator_report.md`, and receipt. Subgroup mode adds `subgroup_results.csv` and `subgroup_forest.png`; a single continuous moderator adds `moderator_scatter.png`. Within-group estimates are transformed back to the entered effect scale. Treat ecological associations and low-power tests cautiously; these are not clinical or publication conclusions.
