# Several-cutoff diagnostic method

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


`meta.py multithreshold` runs the installed project-private `diagmeta` 0.5-1 package. It fits the explicit CICS logistic, unequal-variance multiple-cutoff model with inverse-variance weights. Multiple cutoffs within a labeled study remain grouped; they are not separate independent studies. This route is separate from the single-threshold `mada` bivariate route.

Input CSV requires `study_id,cohort_id,threshold,TP,FN,FP,TN,threshold_unit,index_test,reference_standard,outcome,timepoint,case_design,source_file,source_sha256,source_location`. It needs at least three labeled studies and at least two with multiple cutoffs. `case_design` is `single_gate`, `two_gate`, or `case_control`; `package_unspecified` is allowed only for a package method example. All rows must use the same test, reference standard, condition, timepoint, design and cutoff unit. A cohort cannot appear under different study IDs. Within a study, thresholds must be distinct, higher thresholds must have no more TP or FP, and diseased/nondiseased denominators must be constant. The sole exception is `source_kind=package_method_example`, which preserves and flags inconsistent package rows; real and synthetic runs fail. The software cannot discover differently named overlapping cohorts.

Plan JSON schema is `meta-multithreshold-plan-v1`. Required choices: `source_kind` (`package_method_example`, `synthetic_fixture`, or `reviewed_extraction`), `threshold_unit,index_test,reference_standard,outcome,timepoint,case_design,effect_direction`, `positive_direction=higher_value_positive`, `model=CICS`, `distribution=logistic`, `equal_variance=false`, `method_weights=invvar`, `continuity_increment=0.5`, boolean `log_cutoff`, `lambda_sensitivity` from 0 to 1, `alpha` between 0 and 0.5, and 2–100 distinct `prediction_cutoffs`. Real extraction additionally needs `review_status=human_reviewed_claim`. Predictions outside the observed cutoff range fail. Cutoff selection needs clinical assessment even after model fitting. The `.5` continuity increment is explicit; raw per-study sensitivity and specificity in `cutoff_trace.csv` do not apply that correction.

```powershell
./launch.cmd meta multithreshold --input cutoffs.csv --plan plan.json --rscript $rscript --out fresh-method-dir
```

Outputs: `multithreshold_summary.csv`, `cutoff_predictions.csv`, `cutoff_trace.csv`, `sensspec_curve.png`, `sroc.png`, `fact_report.md` and a hash receipt. Outputs are staged, then committed to a fresh directory. The receipt is a local file-consistency record, not proof of paper origin, independent reviewers, or a clinically valid cutoff. No OCR or threshold harmonization occurs here.

The summary now records the underlying `lme4` optimizer code, convergence messages and `isSingular` result. A nonzero optimizer code or other convergence warning blocks the output. A converged singular boundary fit can produce finite values but is visibly marked in the summary, receipt, figures, fact report and draft manuscript for cautious interpretation. It is not independent model validation.
