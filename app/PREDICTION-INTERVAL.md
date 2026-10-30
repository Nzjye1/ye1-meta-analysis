# Bound random-effects prediction interval

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


This is an additional statistical appendix for a **previously protocol-bound** `run_protocol.py` result. It leaves the base output untouched. It supports an intercept-only, independent-study RE/REML model with `test=z` and at least three studies, using the currently installed `metafor` 5.2-1. It does not implement subgroup analysis, meta-regression, dependent effects, or a patient-level prediction.

```powershell
./launch.cmd meta prediction-interval --stats-dir BOUND_RE_RUN --confirmation CONFIRMATION.json --rscript $rscript --out FRESH_PI_DIR
```

The command checks the original protocol run receipt, all hashed result files, confirmation hash and base R script hash. Its R module refits from the saved study-scale effect/variance and compares the pooled estimate, CI and tau² against the bound output before calling `metafor::predict.rma`. The output is `prediction_interval.csv`, `prediction_report.md` and `prediction_receipt.json` in a fresh directory. Ratio effects are back-transformed; the pooled ratio is described as a median ratio on the transformed scale. The output is an approximate range for a true effect in a new comparable study; it depends on the fitted heterogeneity estimate and does not establish clinical transportability. With tau² estimated as zero, the prediction and confidence intervals can coincide. The result remains a statistical appendix requiring review, never a final conclusion.
