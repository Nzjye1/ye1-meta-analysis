# Dose protocol, category evidence and Word draft

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


Reuse the local RIS/CSV bibliography importer, explicit duplicate dispositions, ordered title/abstract and full-text screening and `report_map.csv`. Every included record maps to one report and study; several reports may map to one study. The `category_review.csv` maps each statistical category by `study_id,dose` to one **included** `record_id`, preserving the exact source file/hash/location from the category input. Its fields are `study_id,dose,record_id,review_status,reviewer,reviewed_at,risk_of_bias_judgment,risk_basis,source_file,source_sha256,source_location`. The risk judgment is a reviewer-entered, study-consistent label; this is not an instrument-specific RoB questionnaire or automated appraisal. In real mode, a located human review claim is required. Identity and source interpretation are not authenticated by local hashes.

`protocol.json` uses `schema=meta-dose-project-v1`, `mode=synthetic_test|real`, `project_id`, `question`, PICO `population,exposure,comparator,outcome`, `eligible_designs`, honest `search_status`, and an `analysis` object from [DOSE-RESPONSE.md](DOSE-RESPONSE.md). Real mode requires `source_kind=reviewed_extraction` and an actual approval declaration with `reviewer,reference,date,declaration`. Synthetic/package data are confined to `synthetic_test`. The method cannot claim a software-verified complete search. The reviewer must check adjustment, source values, category bounds/representative values, dose units, cohort independence and clinical meaning.

`narrative.json` supplies a title and substantive Introduction/Discussion paragraphs with `text,record_ids,source_locator,review_status`. Real paragraphs require existing bibliographic IDs and source locators; synthetic paragraphs use `review_status=synthetic_test`. The builder generates Methods, result values, counts, tables and model figure from the checked protocol and `dosresmeta` output; narrative input does not replace those generated sections. Real references come only from imported metadata. Package/synthetic examples do not fabricate a bibliography.

```powershell
./launch.cmd meta dose-confirm --protocol protocol.json --records records.csv --dedup dedup.csv --decisions decisions.csv --report-map report_map.csv --input categories.csv --category-review category_review.csv --out fresh-confirmation
./launch.cmd meta dose-paper --protocol protocol.json --records records.csv --dedup dedup.csv --decisions decisions.csv --report-map report_map.csv --input categories.csv --category-review category_review.csv --confirmation fresh-confirmation --narrative narrative.json --rscript $rscript --out fresh-paper
```

The confirmation records input, source and program hashes and a human approval **claim**. Build rechecks the source bytes and confirmation, then produces statistics, category review ledger, selection count subset, an English IMRaD Markdown/Word draft, model plot, status and member manifest. A changed protocol, category, review or source file invalidates the confirmation. The record/report/study counts are only a local subset, not complete PRISMA accounting. `DRAFT_EVIDENCE_RECORDED_NOT_FINAL` is still not a clinically approved report.
