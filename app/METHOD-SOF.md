# Method-specific Summary of Findings draft

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


`./launch.cmd meta method-sof --inputs method_sof_inputs.csv --out NEW_DIR` combines **previously checked, non-final method papers** and reviewer-entered certainty evidence. `./launch.cmd meta method-sof --verify NEW_DIR` rechecks the input CSV, original method paper and confirmation inputs, evidence bytes and generated outputs. The module calls no statistical engine and does not change the underlying model.

The input CSV uses the header in `scripts/method_sof.py` (`INPUT`). Each row has a distinct `outcome_id`, one `method`, a `paper_dir`, and a method selector when needed. Supported methods and native metrics:

| Method | Selector | Native output |
|---|---|---|
| `rare` | blank | Checked MH fixed-effect RR/OR primary, IV sensitivity and Peto OR sensitivity only when estimable; identified versus informative studies, double-boundary exclusions and zero policies remain separate |
| `diagnostic` | blank | Sensitivity and specificity for the stated threshold policy, two rows referring to the same study set |
| `multithreshold` | blank | Sensitivity and specificity at the model-selected cutoff, with cutoff unit and optimizer/singularity status; clinical cutoff suitability unreviewed |
| `network` | `treatment1\|treatment2` | Exact league-table orientation and effect scale; OR/RR log intervals are exponentiated and marked as transformations, MD unit remains `UNIT_NOT_SUPPLIED` when the plan has none; study count is network-wide, not comparison-specific |
| `dose` | exact modeled dose | RR versus stated reference and dose unit; reference RR=1 is labeled a definition, not an estimated confidence interval |
| `single_arm` | blank | Distinct proportion of people or incidence rate per person-time in the engine's display unit |
| `dependent` | blank | Primary working-correlation result, cluster study count rather than correlated effect-row count, model inference status |

For `participants`, use only a count supported by `participants_evidence_file`, its SHA-256, and a locator. `participants_scope` must state `outcome_specific`, `model_population`, or (network only) `whole_network_not_comparison_specific`; no cross-outcome or cross-comparison sum occurs. An absent count remains `NOT_SUPPLIED`. The code cannot decide whether a supplied population denominator is clinically appropriate.

`certainty_status` is `not_assessed`, `reviewer_claim`, `synthetic_test`, or `agent_suggestion`. A graded reviewer claim needs a named reviewer, date, local evidence file/SHA-256 and locator. `AGENT_` labels cannot pass as reviewer claims; an Agent grade remains `NOT_ASSESSED` in the main certainty column and is retained as a separate suggestion. A synthetic grade is labeled as such. These are local evidence and attribution claims, **not automatic GRADE or official RoB instrument scoring**.

For `rare` only, the optional input columns in `RARE_BASELINE_INPUT` declare a comparator event risk per 1000, exact source file/SHA-256/locator, population and timepoint, explicit `applicable`, `not_applicable`, or `uncertain` review, basis, reviewer and date. A blank set means `not_supplied`. Only `applicable` converts the **primary MH** RR/OR using the existing `sof_multi.absolute_effect` function; other states retain relative effects without absolute values. The endpoint must match the analyzed timepoint, and an `AGENT_` label cannot stand in for a completed applicability review. The software checks local evidence bytes and declared fields, not clinical transportability. Peto and IV are sensitivity rows, never additional studies or separate absolute-risk claims.
