# Network protocol, evidence and Word draft

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


Reuse the existing RIS/CSV import, explicit duplicate dispositions and ordered title/abstract and full-text screening decisions. `report_map.csv` maps every included record to one report and study. The network contrast CSV adds `record_id`, which must refer to an included report mapped to that contrast's study. Multiple reports may map to one study; all included studies must be represented in the analysis.

`protocol.json` has `schema=meta-network-project-v1`, `mode=synthetic_test` or `real`, `project_id`, `question`, PICO `population,interventions,comparator,outcome`, `eligible_designs`, honest `search_status`, and an `analysis` object from [NETWORK-META.md](NETWORK-META.md). The PICO comparator/outcome must match the analysis reference/outcome. Real mode requires `source_kind=reviewed_extraction` and an actual approval `reviewer,reference,date,declaration`. Approval, search completeness and reviewer identity are self-declared and not authenticated by local hashes.

`transitivity.csv` requires exactly one `study_id,status,population_note,effect_modifier_note,allocation_note,risk_of_bias_judgment,source_file,source_sha256,source_location,reviewer,reviewed_at` row per independent study. Real mode requires a human-assessed row, a documented risk-of-bias judgment and local cited evidence for each study. The software verifies source bytes and locator shape, not whether effect modifiers are truly exchangeable or a risk judgment is right. Synthetic examples use `synthetic_test`. Formal independent dual review of network-specific transitivity judgments is not yet implemented.

`narrative.json` supplies a title and Introduction/Discussion paragraphs with `text,record_ids,source_locator,review_status`; real paragraphs require existing reference IDs and locators, while synthetic text is marked `synthetic_test`. Methods, comparison estimates, confidence intervals, network counts, inconsistency results, ranking values and charts are generated from checked protocol/statistics, so narrative text cannot change them through the builder.

```powershell
./launch.cmd meta network-confirm --protocol protocol.json --records records.csv --dedup dedup.csv --decisions decisions.csv --report-map report_map.csv --input contrasts.csv --assumptions transitivity.csv --out fresh-confirmation
./launch.cmd meta network-paper --protocol protocol.json --records records.csv --dedup dedup.csv --decisions decisions.csv --report-map report_map.csv --input contrasts.csv --assumptions transitivity.csv --confirmation fresh-confirmation --narrative narrative.json --rscript $rscript --out fresh-paper
```

The build rechecks confirmed input and source hashes, runs `netmeta`, and writes the statistical tables, a local selection-count subset, transitivity ledger, English IMRaD Markdown and DOCX, two figures embedded in Word, status and member manifest. A changed protocol or evidence file requires a new confirmation. Output is always a draft. `DRAFT_EVIDENCE_RECORDED_NOT_FINAL` means data and evidence labels are present, not that transitivity, coherence or comparative treatment claims are clinically approved. The local counts are not full PRISMA 2020 compliance.
