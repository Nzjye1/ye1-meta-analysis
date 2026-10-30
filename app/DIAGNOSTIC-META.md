# Diagnostic accuracy meta-analysis

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


Call `./launch.cmd meta diagnostic --input checked_2x2.csv --plan diagnostic_plan.json --rscript $rscript --out fresh-result`. This separate method uses the project-private `mada` 0.5.12 library and a bivariate Reitsma random-effects REML fit. It does not reuse pairwise RR/OR/HR or MD/SMD inputs. It does not silently combine diagnostic thresholds, reference standards, outcomes, timepoints or cohorts.

The CSV needs `study_id,cohort_id,TP,FN,FP,TN,index_test,reference_standard,threshold,outcome,timepoint,source_file,source_sha256,source_location`. Counts are nonnegative integers, with a positive diseased and non-diseased denominator in every study. Study and cohort IDs must each be unique. A real extraction has a local source file/hash and page, table or figure locator; these are consistency checks, not proof of correct extraction. The package method fixture uses `dataset row N` and `source_kind=package_method_example`. The code requires at least three independent 2×2 tables; fit convergence is checked, while low study counts and model assumptions still need method review.

Example plan:

```json
{"schema":"meta-diagnostic-plan-v1","source_kind":"package_method_example","index_test":"Example test","reference_standard":"Example reference","outcome":"Example outcome","timepoint":"Example","effect_direction":"Higher sensitivity and specificity indicate better classification","threshold_policy":"common","zero_policy":"half_all","alpha":0.05}
```

`source_kind=reviewed_extraction` additionally requires `review_status=human_reviewed_claim`; this is a user declaration, not authenticated reviewer identity. `source_kind=synthetic_fixture` is only for explicitly labeled test data with `synthetic row N` locators. `threshold_policy=common` blocks distinct threshold labels. `mixed_exploratory` permits them but marks the pooled result exploratory; clinical threshold comparability remains a human decision. `zero_policy=reject` stops on any zero cell. `half_all` follows `mada::reitsma(correction=0.5, correction.control="all")`, adding 0.5 to all study tables if any has a zero cell; `half_single` uses `correction.control="single"` for affected studies. The correction choice can change results and must be prespecified. Other zero strategies, multiple cutpoints per study, paired tests, and dependent cohorts are not modeled here.

Outputs are `diagnostic_summary.csv` (pooled sensitivity, specificity and confidence intervals), `study_2x2_trace.csv`, `sroc.png`, `paired_forest.png`, a fact report, and a receipt binding inputs, local source hashes, script and outputs. The result is a statistical appendix, never an automatically final report. No automated QUADAS judgment, GRADE conclusion or PRISMA claim is made. The current customer packages predate this module.

## Protocol-bound diagnostic draft route

The `meta.py diagnostic-confirm` and `meta.py diagnostic-paper` route links the existing bibliography deduplication and ordered screening decisions to a diagnosis-specific protocol, one analyzed 2×2 table per independent study, source review, and evidence-domain judgments. Read [DIAGNOSTIC-PROJECT.md](DIAGNOSTIC-PROJECT.md). It emits an English IMRaD draft and a Word file containing the forest and SROC figures. Its factual Methods/Results are generated from checked inputs; user-supplied Introduction/Discussion paragraphs remain explicitly sourced or synthetic.
