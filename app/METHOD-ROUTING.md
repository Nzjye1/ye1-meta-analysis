# Agent method selection and unified execution

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


For supplied author-extracted continuous MD data only, use the explicit [existing summary data workflow](AGGREGATE-WORKFLOW.md) through `launch.cmd meta run`. That mode binds the supplied source and a prespecified FE/NONE, RE/DL or RE/REML configuration without claiming a new systematic review. It does not require a fabricated route approval or screening chain. The complete-review method routing and actual review requirements below remain unchanged.

Use this before preparing a method-specific protocol when a customer describes the research question and the structure of their study-level data. The Agent asks for the question type and data shape, records them in a short JSON idea, and calls one unified entry. The router never guesses that related estimates are independent, or that diagnostic thresholds may be pooled as ordinary comparative effects. It cannot infer study design or data structure from free prose alone; the Agent must review those choices with the customer.

```json
{
  "schema": "meta-method-idea-v1",
  "project_id": "EXAMPLE-01",
  "question": "How does the index test classify the target condition at several cutoffs?",
  "population": "people with the target clinical presentation",
  "outcome": "target condition",
  "question_type": "diagnostic_accuracy",
  "data_shape": "several_cutoffs_per_study",
  "effect_type": null
}
```

| Customer data | `question_type` / `data_shape` | Route | Allowed effect type |
|---|---|---|---|
| One independent comparative effect per study | `comparative_effect` / `one_independent_effect_per_study` | pairwise | RR, OR, HR, MD, SMD |
| Independent sparse two-arm event counts | `comparative_effect` / `independent_sparse_two_arm_event_counts` | rare | RR or OR, fixed MH primary |
| Several related estimates within study | `comparative_effect` / `several_related_effects_per_study` | dependent | RR, OR, HR, MD, SMD |
| Connected treatment comparisons | `comparative_effect` / `connected_treatment_network` | network | RR, OR, MD |
| One diagnostic cutoff per study | `diagnostic_accuracy` / `one_cutoff_per_study` | diagnostic | no comparative effect type |
| Several ordered cutoffs per study | `diagnostic_accuracy` / `several_cutoffs_per_study` | multithreshold | no comparative effect type |
| Several exposure doses per study | `exposure_response` / `several_dose_categories_per_study` | dose | RR only in this implementation |
| Event numerator with people or person-time denominator | `event_frequency` / `events_over_people_or_person_time` | single_arm | proportion or incidence_rate |

The sparse-count route requires the separate `RARE-EVENT.md` count, correction, source and review contracts. A route choice must agree with the actual OR/RR plan.

For pairwise ideas, also supply `intervention,comparator,timepoint,direction,eligible_designs,search_concepts` as required by the existing PICO preparation entry. A single-group proportion and an incidence rate share a route but have different denominator contracts and separate plans. Network, dose, diagnostic, dependent and multithreshold protocols are still governed by their own linked method/project guides.

```powershell
./launch.cmd meta method-prepare --idea idea.json --out fresh-route-dir
```

This writes `route.json` with the selected method, guide, available phases and machine-readable `phase_required_options`; `protocol_outline.json` with unresolved design questions (not an executable protocol); `routing_guide.md`; and `choice_template.json` with `status=pending_human_review`. A real reviewer must check suitability and set `status=human_confirmed_claim`, `reviewer`, `decision_date`, and an actual `reference`. Synthetic tests may set `status=synthetic_test`. Neither status authenticates a person's identity. The choice binds the route bytes, and the route binds the original idea bytes; changing the question or effect type invalidates it. The dispatch also rejects a synthetic choice paired with a real-extraction method plan, or the reverse.

After review, call the same command for every method. The router passes options only to an allowlisted existing method module. The method module still checks its full plan, study data, sources, confirmation and output status.

```powershell
./launch.cmd meta method --route fresh-route-dir/route.json --choice reviewed-choice.json --phase analyze --input cutoffs.csv --plan analysis.json --rscript 'C:/path/to/Rscript.exe' --out fresh-analysis
./launch.cmd meta method --route fresh-route-dir/route.json --choice reviewed-choice.json --phase confirm --protocol protocol.json --records records.csv --dedup dedup.csv --decisions decisions.csv --report-map report_map.csv --input cutoffs.csv --threshold-review threshold_review.csv --quadas quadas.csv --out fresh-confirmation
./launch.cmd meta method --route fresh-route-dir/route.json --choice reviewed-choice.json --phase paper --protocol protocol.json --records records.csv --dedup dedup.csv --decisions decisions.csv --report-map report_map.csv --input cutoffs.csv --threshold-review threshold_review.csv --quadas quadas.csv --confirmation fresh-confirmation --narrative narrative.json --rscript 'C:/path/to/Rscript.exe' --out fresh-paper
```

The example commands above are for the several-cutoff route. For another route, read its generated `phase_required_options`. Pairwise `prepare` uses the bound idea and makes only pending PICO/search candidates; pairwise `workflow` uses an existing stage project JSON. `customer_workflow.py` now allowlists confirm/build stages for all seven separate method-project modules. An incomplete pairwise workflow can use its underlying `--resume` path with the unchanged route and choice. No online search or package installation is performed by routing.

Successful dispatch writes a sibling `OUTPUT.method-route-receipt.json` with route/choice hashes and output-tree hashes. `./launch.cmd meta method-verify --receipt OUTPUT.method-route-receipt.json` rechecks those local bytes. This is a file-consistency record, not proof of method appropriateness, source authenticity or clinical approval. Results retain their method-specific `final=false` status.

Dispatch checks that the route's selected RR/OR/HR/MD/SMD or proportion/incidence-rate choice equals the actual method analysis plan (`effect_type` or `measure`) at analyze, confirm and paper phases. The pairwise workflow route checks its explicit confirmed protocol effect type before stage execution. Selected and actual scales are both recorded in the route receipt. This blocks a confirmed HR route from silently running MD, or a proportion route from running an incidence-rate plan. Study population and clinical comparability still require the method protocol and human assessment.
