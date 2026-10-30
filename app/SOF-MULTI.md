# Multiple outcome Summary of Findings draft

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


`./launch.cmd meta sof-multi --inputs outcomes.csv --out fresh-sof` combines **separately checked** `quality-resolve` outcomes into a draft CSV, Markdown summary and Word table. Each outcome/timepoint/effect scale must have its own protocol-bound pairwise statistics packet and reviewer quality result. The module calls `evidence_quality.verify_quality` for every row, then binds the existing SoF fact row and reviewer-supplied certainty. It never derives a GRADE grade or treats Agent proposals as final judgments. This first version supports RR, OR, HR, MD and SMD from the existing pairwise quality source contract; method-specific diagnostic, network, dose-response and single-group certainty tables need their own contracts.

Use `./launch.cmd meta sof-multi --verify fresh-sof` to recheck the manifest, each quality packet, cited local evidence and output hashes. Relative input paths are resolved against the input CSV directory.

The CSV columns are:

`outcome_id,quality_dir,measurement_unit_override,unit_evidence_file,unit_evidence_sha256,unit_locator,participants,participants_evidence_file,participants_evidence_sha256,participants_locator,baseline_risk_per_1000,baseline_evidence_file,baseline_evidence_sha256,baseline_locator,baseline_timepoint,baseline_population,baseline_applicability_review,baseline_applicability_basis,comment`

Use an absolute or project-relative `quality_dir` for each completed `quality-resolve` result. Its report packet, source review, confirmed analysis and certainty evidence must still pass their original checks. An outcome/timepoint/scale combination cannot appear twice. A missing MD unit may be supplied only as `measurement_unit_override` with a local evidence file, hash and locator; the override cannot contradict an existing protocol unit. SMD is reported in standardized SD units. Optional `participants` is a positive integer with its own source citation; a study-level effect table does not imply a participant count. The software checks citation file consistency and locator presence, but a reviewer must verify the count and unit in the original report.

For RR, OR or HR, an optional comparator `baseline_risk_per_1000` must have a local evidence file/hash/locator, stated comparator population, a timepoint identical to the pooled outcome, `baseline_applicability_review` set to exactly `applicable`, `not_applicable`, or `uncertain`, and a nonempty reviewer rationale in `baseline_applicability_basis`. Only `applicable` permits conditional absolute-effect calculation. The other two statuses retain the pooled relative effect and source but output `NOT_COMPUTED` for treated risk and risk difference in CSV, Markdown and Word. Software checks the declared state, not the clinical truth of applicability. Without a sourced risk, the absolute effect reads `NOT_COMPUTED_NO_SOURCED_BASELINE`. For an applicable supplied risk `p0 = baseline/1000` and relative point/CI `x`, treated risks are:

- RR: `p1 = p0 × x`.
- OR: `p1 = p0 × x / (1 − p0 + p0 × x)`.
- HR: `p1 = 1 − (1 − p0)^x`, requiring a proportional-hazards assumption and baseline event risk at the same timepoint.

The absolute difference is `(p1 − p0) × 1000`, with CI endpoints transformed separately. The baseline is treated as fixed: its uncertainty is **not** propagated, and the result is a conditional illustration, not an independently estimated risk. Invalid probabilities are rejected rather than capped. MD/SMD cannot accept a baseline risk and output `NOT_APPLICABLE` for binary absolute effects. Display rounds only to one decimal per 1000; `sof_multi.csv` retains the original pooled point/CI strings. The Word and Markdown files are draft attachments. The receipt distinguishes formal human-attested role claims from exploratory sources, and still cannot authenticate people or clinical interpretation.
