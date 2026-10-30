# Single-group review route and Word draft

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


Reuse local RIS/CSV bibliography import, explicit duplicate dispositions and ordered title/abstract/full-text screening. Every included record maps to a report and study in `report_map.csv`; multiple reports may map to one study. `study_review.csv` has exactly one row per analyzed study with `study_id,record_id,review_status,reviewer,reviewed_at,risk_tool,risk_tool_version,risk_judgment,risk_basis,source_file,source_sha256,source_location`. Its `record_id` must be an included report mapped to that study, and its source must equal the statistical input's source. The risk tool/version and judgment are reviewer-entered claims; no instrument questionnaire or automatic scoring is bundled. Real mode requires located human review claims, though identity and clinical correctness cannot be authenticated by hashes.

`protocol.json` uses `schema=meta-single-arm-project-v1`, `mode=synthetic_test|real`, `project_id`, `question`, PICO `population,condition,outcome,timepoint`, `eligible_designs`, honest `search_status`, and the plan from [SINGLE-ARM.md](SINGLE-ARM.md). Real mode requires `source_kind=reviewed_extraction` and actual approval `reviewer,reference,date,declaration`. Synthetic data cannot use a real-mode approval claim. The PICO population/outcome/timepoint must equal the statistical plan. A local file confirmation checks consistency, not the human's identity or search completeness.

`narrative.json` supplies title plus substantive Introduction/Discussion paragraphs. Real paragraphs require existing bibliographic IDs and source locators; synthetic paragraphs have `review_status=synthetic_test`. The builder generates Methods, result count/estimate text, tables and figure from checked inputs. Real references come only from imported metadata.

```powershell
./launch.cmd meta single-confirm --protocol protocol.json --records records.csv --dedup dedup.csv --decisions decisions.csv --report-map report_map.csv --input studies.csv --study-review study_review.csv --out fresh-confirmation
./launch.cmd meta single-paper --protocol protocol.json --records records.csv --dedup dedup.csv --decisions decisions.csv --report-map report_map.csv --input studies.csv --study-review study_review.csv --confirmation fresh-confirmation --narrative narrative.json --rscript $rscript --out fresh-paper
```

The build rechecks confirmed input/source/code hashes, runs the selected `metafor` route and writes a selection-count subset, source/risk ledger, statistics, English IMRaD Markdown/DOCX, forest, status and member manifest. Changing a bound file requires a new confirmation. The output remains a **draft**, not a complete PRISMA review or clinical estimate.
