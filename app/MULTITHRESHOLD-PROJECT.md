# Several-cutoff diagnostic review route

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


This route binds a diagnostic PICO and a declared multi-cutoff plan to the existing imported bibliography, duplicate dispositions, title/abstract and full-text decisions, report-to-study map, cutoff-level four-cell inputs, cutoff-level source review, and four diagnostic quality evidence domains per study. It then runs `diagmeta` and produces two figures, two tables, fact-bound English IMRaD Markdown/JSON/Word drafts, selection counts, source ledgers and a manifest. It does not turn a package dataset or synthetic fixture into a new systematic review.

`protocol.json` uses schema `meta-multithreshold-project-v1`, `mode=synthetic_test` or `real`, a question, `pico` with population/index test/reference standard/target condition, eligible designs, threshold rule, actual search status, quality tool identifier/version/reference, and the embedded method plan from [MULTITHRESHOLD-DIAGNOSTIC.md](MULTITHRESHOLD-DIAGNOSTIC.md). Real mode requires an actual human approval claim (`reviewer,reference,date,declaration`), `source_kind=reviewed_extraction`, `review_status=human_reviewed_claim`, cutoff rows marked `human_verified`, and quality rows marked `human_assessed`. The code checks local consistency and dates; it cannot authenticate reviewer identity or whether a person read the source. Synthetic mode may use only synthetic or package method data and is always a non-final draft.

The cutoff CSV adds `record_id` to the method fields. Each row must point to an included report mapped to its study. `threshold_review.csv` needs exactly one row per study/cutoff with `study_id,threshold,record_id,TP,FN,FP,TN,status,reviewer,reviewed_at,source_file,source_sha256,source_location`. Values and source reference must match that cutoff row. `quadas.csv` needs one row per study and each of `patient_selection,index_test,reference_standard,flow_timing`, with `study_id,domain,status,judgment,applicability,rationale,evidence_file,evidence_sha256,evidence_locator,reviewer,reviewed_at`. The framework fields identify user-entered evidence domains only; no copyrighted questionnaire or automatic domain scoring is included. A source location and matching local file hash are not semantic verification of a table value.

```powershell
./launch.cmd meta multithreshold-confirm --protocol protocol.json --records records.csv --dedup dedup.csv --decisions decisions.csv --report-map report_map.csv --input cutoffs.csv --threshold-review threshold_review.csv --quadas quadas.csv --out fresh-confirmation-dir
./launch.cmd meta multithreshold-paper --protocol protocol.json --records records.csv --dedup dedup.csv --decisions decisions.csv --report-map report_map.csv --input cutoffs.csv --threshold-review threshold_review.csv --quadas quadas.csv --confirmation fresh-confirmation-dir --narrative narrative.json --rscript $rscript --out fresh-paper-dir
```
