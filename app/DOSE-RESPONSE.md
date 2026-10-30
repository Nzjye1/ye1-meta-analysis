# Dose-response meta-analysis

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


`./launch.cmd meta dose --input categories.csv --plan dose_plan.json --rscript $rscript --out fresh-result` runs a two-stage REML model using project-private [`dosresmeta` 2.2.0](https://cran.r-project.org/package=dosresmeta) (GPL-2). It treats exposure categories within each study as correlated and exports the reconstructed Greenland–Longnecker covariance matrices. The model is limited to a single exposure, outcome, endpoint time, adjustment definition and dose unit, with log RR inputs. It does not convert OR/HR to RR, pool multiple correlated outcomes, establish causal effects, or perform a literature review.

The UTF-8 category CSV requires `study_id,cohort_id,dose,logrr,se,cases,n,type,reference,category_lower,category_upper,category_basis,open_end_basis,open_end_rationale,dose_unit,outcome,timepoint,adjustment,source_file,source_sha256,source_location`. `type` is `ci` for cumulative incidence (integer cases and people) or `ir` for incidence rate (integer cases and positive person-time). Every study has one plan-matching zero-log-RR reference and at least two nonreference categories with positive SE. Reference SE may be blank. At least three independent labeled studies are required; duplicated cohorts or dose categories, mixed units, outcomes, incidence types, timepoints and adjustment definitions are blocked. Shared cohorts hidden behind distinct IDs remain a human review task.

`category_basis` records `reported_mean`, `reported_median`, `midpoint`, or `author_assigned`. A closed interval must contain its representative dose; a `midpoint` must equal the arithmetic midpoint. An open-ended interval requires `open_end_basis` (`reported_mean`, `reported_median`, `adjacent_width`, or `author_assigned`) and a written `open_end_rationale`. A mean/median or assigned open-end value is **an entered extraction claim**, not an algorithmically imputed value. `package_example` is reserved for the official package dataset route with `dataset row N` locators. Real inputs need page/table/figure locators, a matching local source file SHA-256, and a separate human review claim. The software checks format and bytes, not the paper's meaning.

The JSON plan has `schema=meta-dose-plan-v1`, `source_kind` (`synthetic_fixture`, `package_method_example`, `reviewed_extraction`), `model` (`linear` or `natural_spline`), `covariance=greenland_longnecker`, `method=REML`, `effect_type=RR`, `data_type=ci|ir`, `alpha`, `reference_dose`, `reference_description`, `prediction_doses`, `dose_unit`, `outcome`, `timepoint`, `adjustment`, `effect_direction`, and `dose_definition`. The project route requires the reference description to equal the PICO comparator. Real input also requires `review_status=human_reviewed_claim`, which is a declaration, not authenticated identity. For a natural spline, specify one or two interior `knots` and two `boundary_knots`; they must cover observed dose values. Prediction doses must lie within the observed range and include the reference. The spline form is a planned model choice; a curved plot alone is not a formal nonlinearity test. The route does not select knots or an optimal model from the data.

Outputs include `checked_categories.csv`, `category_trace.csv`, `dose_summary.csv`, `dose_coefficients.csv` on the log RR scale, `dose_predictions.csv` as RR with CIs, `within_study_covariance.csv`, `between_study_covariance.csv`, `dose_curve.png`, `dose_report.md`, and a SHA-256 receipt. A failed run leaves no final output directory, and an existing output is never overwritten. There is no automatic zero-event continuity correction: a zero case count is refused for separate method choice. The input SE, incidence data and category assignments must be coherent; the software does not independently re-extract or validate those scientific choices. No interval outside observed doses is reported.

The complete protocol/screening/review/Word route is described in [DOSE-PROJECT.md](DOSE-PROJECT.md).
