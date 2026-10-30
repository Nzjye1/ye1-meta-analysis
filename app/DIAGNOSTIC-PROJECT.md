# Diagnostic review to article draft

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


Use the existing `literature.py import` or RIS route, dedup disposition ledger, and ordered title/abstract/full-text decision file. Retain one `report_map.csv` row per included report: `record_id,report_id,study_id`. Several reports may map to one study; the analysis needs exactly one selected, independent 2×2 row per included study. Keep source files local. This route neither retrieves full text nor decides eligibility for the reviewer.

`protocol.json` uses `meta-diagnostic-project-v1`, `mode=synthetic_test` or `real`, a project ID and clinical question, PICO `population,index_test,reference_standard,target_condition`, eligible designs, `case_design` (`single_gate`, `two_gate`, or `case_control`), a named `threshold_rule`, honest `search_status`, `quality_tool` name/version/reference, and an `analysis` object using the diagnostic plan in `DIAGNOSTIC-META.md`. The index test, reference standard and condition must match the analysis. In real mode, the analysis must use `source_kind=reviewed_extraction` and needs an actual user supplied `approval` object with `reviewer,reference,date,declaration`. Synthetic mode requires `synthetic_fixture` or package-method source. Changing the protocol or any checked input after confirmation invalidates the run. These fields record declarations; the program cannot authenticate reviewer identity or search completeness.

The protocol-bound 2×2 CSV adds `record_id,case_design` to the method table. Every record must be full-text included and map to the same study. The case design and common threshold label must match the protocol. `source_review.csv` has one `study_id,status,reviewer,reviewed_at,source_file,source_sha256,source_location` row per study. A real analysis requires `human_verified` for every analyzed row; `pending` remains an unfinished preparation state. Synthetic tests use `synthetic_test`. This is a claim backed by local source/hash/locator, not a semantic PDF recheck.

`quadas.csv` has one row per study and domain `patient_selection,index_test,reference_standard,flow_timing`: `study_id,domain,status,judgment,applicability,rationale,evidence_file,evidence_sha256,evidence_locator,reviewer,reviewed_at`. `status=pending` leaves judgments blank; `human_assessed` needs a judgment (`low`,`high`,`unclear`), applicability, reason, reviewer/date and source locator; `synthetic_test` is accepted only in synthetic projects. `flow_timing` applicability is `not_applicable`. The protocol records a user-supplied QUADAS tool name/version/reference, but this program does not reproduce a restricted questionnaire or score the domains itself. Formal independent dual review of 2×2 counts and quality domains is not yet implemented; do not label these ledgers as two independent human votes. The existing dual-screen module can supply screening decisions only.

`narrative.json` contains `title`, and nonempty `Introduction` and `Discussion` arrays of `text,record_ids,source_locator,review_status`. A real paragraph requires existing reference IDs and a locator; `pending` is allowed but remains a draft. Synthetic paragraphs use `review_status=synthetic_test` and do not create real references. Methods, numeric Results, counts and figures come only from the checked files.

```powershell
./launch.cmd meta diagnostic-confirm --protocol protocol.json --records records.csv --dedup dedup.csv --decisions decisions.csv --report-map report_map.csv --input dta.csv --source-review source_review.csv --quadas quadas.csv --out fresh-confirmation
./launch.cmd meta diagnostic-paper --protocol protocol.json --records records.csv --dedup dedup.csv --decisions decisions.csv --report-map report_map.csv --input dta.csv --source-review source_review.csv --quadas quadas.csv --confirmation fresh-confirmation --narrative narrative.json --rscript $rscript --out fresh-paper
```

The second command verifies all confirmed file hashes and source bytes again, runs the `mada` bivariate model, and commits a fresh result only when outputs are complete. Outputs include `statistics/`, included-study and quality evidence tables, local selection counts, `manuscript.md`, `manuscript.docx`, status and manifest. Both forest and SROC are embedded in the Word draft. The local selection subset is **not** a complete PRISMA diagram. Do not call the draft a completed clinical review.
