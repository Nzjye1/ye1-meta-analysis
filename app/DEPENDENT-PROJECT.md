# Dependent-effect review, confirmation and Word draft

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


Reuse bibliography RIS/CSV import, explicit dedup dispositions, ordered title/abstract and full-text screening, and `report_map.csv`. Every included record maps to one report/study; multiple reports may map to the same study. `effect_review.csv` has one row per modeled effect: `study_id,effect_id,record_id,review_status,reviewer,reviewed_at,risk_tool,risk_tool_version,risk_judgment,dependency_basis,source_file,source_sha256,source_location`. The record must be included and mapped to the effect's study, and source file/hash/location must exactly match the statistical input. A study's risk label must be consistent across its effects. These are reviewer claims, not automatic RoB scoring or software proof that the effects share participants/construct.

`protocol.json` uses `schema=meta-dependent-project-v1`, `mode=synthetic_test|real`, `project_id`, `question`, PICO `population,intervention,comparator,outcome`, `eligible_designs`, honest `search_status`, and an analysis plan from [DEPENDENT-EFFECTS.md](DEPENDENT-EFFECTS.md). PICO population/outcome/contrast must equal the analysis. Real mode requires a human-reviewed extraction declaration and approval `reviewer,reference,date,declaration`; it cannot assert software-verified search completeness. `narrative.json` provides title and sourced Introduction/Discussion paragraphs. Real paragraphs require existing reference IDs and page/table/figure locator; the builder generates Methods and Results from bound plan/statistics.

```powershell
./launch.cmd meta dependent-confirm --protocol protocol.json --records records.csv --dedup dedup.csv --decisions decisions.csv --report-map report_map.csv --input effects.csv --effect-review effect_review.csv --out fresh-confirmation
./launch.cmd meta dependent-paper --protocol protocol.json --records records.csv --dedup dedup.csv --decisions decisions.csv --report-map report_map.csv --input effects.csv --effect-review effect_review.csv --confirmation fresh-confirmation --narrative narrative.json --rscript $rscript --out fresh-paper
```

Confirmation binds all core files, original source bytes and code hashes. Build rechecks them, runs all planned rho values, and produces selection-count subset, effect review ledger, statistics and working covariance, English IMRaD Markdown/DOCX, two plots, status and member manifest. Changed inputs require new confirmation. `DRAFT_EVIDENCE_RECORDED_NOT_FINAL` means only that reviewer claims exist, not that CR2 assumptions or risk judgments are correct. The counts are not a complete PRISMA flow.
