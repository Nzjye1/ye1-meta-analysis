# Single-group proportions and incidence rates

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


`./launch.cmd meta single-arm --input studies.csv --plan single_plan.json --rscript $rscript --out fresh-result` uses the installed [`metafor` 5.2-1](https://cran.r-project.org/package=metafor). The analysis plan selects **one** of two distinct contracts:

| Measure | Entered numerator/denominator | Metafor transformation | Display |
|---|---|---|---|
| `proportion` | integer events / integer people | `escalc(measure="PLO")`, logit proportion | fraction of people, 0–1 |
| `incidence_rate` | integer events / positive person-time | `escalc(measure="IRLN")`, log rate | events per explicit 1, 100, 1,000 or 100,000 person-time units |

The proportion route refuses zero/all-event studies; the rate route refuses zero events. No continuity correction is silently applied. A fraction of people is not a rate; person-years, person-months and person-days are not interchangeable. Recurrent events can yield a rate numerator larger than a number of people, but the event definition and source extraction remain user responsibilities. These are raw, unadjusted counts only, not standardized rates or adjusted estimates.

Input CSV fields: `study_id,cohort_id,events,denominator,denominator_unit,outcome,timepoint,population,source_file,source_sha256,source_location`. One row per independent study and cohort; at least three studies. Source locators are `synthetic row N` in synthetic mode or page/table/figure claims for real extraction. All rows must match the plan's outcome, timepoint, population and denominator unit. The software checks local file bytes and locator shape, not the paper's meaning or hidden cohort overlap.

Plan JSON fields: `schema=meta-single-arm-plan-v1`, `source_kind=synthetic_fixture|reviewed_extraction`, `measure=proportion|incidence_rate`, `model=FE|REML`, `outcome`, `timepoint`, `population`, `denominator_unit`, `event_definition`, `effect_direction`, `display_per`, `alpha`. Real inputs also require `review_status=human_reviewed_claim`, which is not identity authentication. FE constrains tau² to zero; REML estimates it. The route uses inverse variance meta-analysis of transformed per-study raw outcomes. A null-effect p-value is not interpreted for a single-group event frequency.

Outputs: checked input, study `yi`/variance/raw/display estimates and CI, pooled transformed and back-transformed estimates and CI, Q/I²/tau² with FE/REML status, forest plot, factual report and SHA-256 receipt. Failure does not leave a final output; an existing output is refused. The result is descriptive and does not establish external validity or a complete review.
