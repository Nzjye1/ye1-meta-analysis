# PRISMA 2020 local reporting attachment

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


The existing `prisma2020_flow.py` calculates identification, explicit duplicate and other removals, screening, retrieval, full-text exclusions with reasons, included reports and distinct studies from a confirmed local ledger. The `meta.py prisma-article` entry adds search-batch/update accounting, previous-version report reconciliation, a dynamic selection diagram, excluded-report details, 42 checklist item/subitem location rows, and an article supplement alongside a bound Word draft. It accepts the original pairwise evidence packet or one of seven method-specific drafts, including sparse-event counts, through a single confirmed-input adapter. It does not run a database search or infer whether a reported item satisfies PRISMA.

The official [PRISMA 2020 checklist](https://www.prisma-statement.org/prisma-2020-checklist) has 27 numbered items and 42 item/subitem IDs. The [official flow page](https://www.prisma-statement.org/prisma-2020-flow-diagram) distinguishes new and updated reviews and searches through databases/registers and other sources. Both pages state CC BY 4.0. This project references item IDs, creates its own diagram, and attributes Page et al., BMJ 2021;372:n71, DOI 10.1136/bmj.n71. It does not copy the checklist wording or official template and never asserts official certification.

## Inputs and command

For the pairwise route, first generate a current extended PRISMA flow, `report.py` packet with that flow, and `manuscript.py` Word draft. The packet must have `report_inputs.json`; the manuscript must have its manifest and bound PRISMA count attachment. A direct numeric-only Meta result cannot be used as a review packet.

For the seven development method routes, supply that method's existing `*-confirmation.json`, `paper` directory, `source_methods.csv` and `retrieval.csv`. The adapter checks the method manuscript manifest, statistics receipt, confirmation/input hashes, screened record IDs, report-to-study map and the method paper's original selection counts; it then calls the same flow counter used by pairwise. It refuses a method draft without the source/retrieval ledgers. Sources lacking `source_label` in an older method fixture use the explicit `UNLABELED` source label in `source_methods.csv`; real multi-source reviews should import with stable source labels. No values are inferred from method summary rows.

`search_batches.csv` columns: `batch_id,source_label,source_name,phase,update_of,search_date,query_reference,reviewer,status`. Each current imported source gets exactly one row. `phase=initial` has no `update_of`; `phase=update` references an earlier batch with the same `source_name`. The row's label, name and date must match the bound `source_methods.csv`. `status=documented_user_claim` or `pending_review`; the code does not authenticate a database response. An updated review may also have a historical batch reference (`phase=historical`, blank `source_label`, `status=historical_prior_reference`) with no imported record count. The historical row supports an update chain without pretending its original record count was loaded. Batches and the source-specific flow must reconcile exactly.

For an updated review, `prior_included.csv` columns: `study_id,report_id,current_status,change_reason,source_reference,reviewer,reviewed_at`. Use `current_status=retained` for each previous report that remains under the same study/report ID in the current included mapping; use `excluded_on_update` with an explicit reason for a previous report no longer included. A prior study can have multiple reports; reports are counted separately from unique study IDs. Reidentified prior reports are not counted as new reports. Prior-only retained reports must be integrated into the current bibliography and mapping before this route can call them currently included. A missing or renamed prior ID requires human reconciliation, not automatic matching.

Optional `locations.csv` columns: `item_id,article_paragraph_id,supplement_section,applicability,reviewer,rationale`. Valid item IDs are the 42 official IDs such as `10a`, `13f`, `16b`, `24c`. `reported` requires a reviewer and an existing manuscript paragraph ID or one generated supplement section. `not_applicable` requires reviewer and reason. `pending` makes no location claim. Omit this file to keep all items pending with evidence-based candidate locations. These are stable paragraph/section IDs; final page numbers require document rendering and author review.

```powershell
./launch.cmd meta prisma-article --packet existing-packet --manuscript existing-paper --search-batches search_batches.csv --prior-included prior_included.csv --locations locations.csv --out fresh-prisma-article-bundle
```

For diagnostic, multiple-cutoff diagnostic, network, dose-response, single-group or dependent-effect manuscripts, use the same entry without `--packet`:

```powershell
./launch.cmd meta prisma-article --manuscript existing-method-paper --confirmation existing-method-confirmation.json --source-methods source_methods.csv --retrieval retrieval.csv --search-batches search_batches.csv --out fresh-method-article-bundle
```

The method attachment copies the original method selection counts, analysis plan and statistics receipt alongside the Word draft. Its selection flow counts **records, reports and distinct studies**; diagnostic cutoff rows, network contrasts, dose categories, single-group event denominators and correlated effects remain method-specific units, never extra studies. It does not infer a patient sample size absent from source data. Method-specific reporting extensions and PRISMA item applicability need author review; all 42 item claims default to pending. A user-entered locator for a method manuscript uses its actual `section-0001` etc. IDs from `manuscript.json` section order, not pairwise paragraph IDs. Existing study/report reconciliation and update-batch options remain available.

Omit `--prior-included` for a new review and `--locations` when no author item decisions exist. Outputs include `article_draft.docx`, `article_draft.md`, `article_supplement.md`, current and updated count CSVs, batch counts, previous-report reconciliation, excluded-report detail, included-study/report table, 42-row item locator CSV, two local SVG accounting views, and a hash receipt. Item 16b's table retains all full-text exclusions as candidates; a person must decide which were potentially eligible and describe them. The bundle is a **draft article with auditable attachments**, not a final review or publication submission. Author judgment on search coverage, study selection, RoB/GRADE, interpretation and item applicability is still required.

## Checked evidence and certainty attachments

The same `prisma-article` entry accepts optional `--method-sof DIR`, `--official-rob DIR`, `--method-rob DIR`, and `--quadas3-binding DIR`. It rechecks each source receipt and original evidence, then writes `evidence_attachment_inventory.csv` with an explicit bound, absent or unsupported state. Checked summaries are appended to the **copied** `article_draft.md` and `article_draft.docx`; the original manuscript and statistics remain untouched. `article_supplement.md` points to the source receipt and states which items are missing. Output CSV and source hashes retain unrounded values even when a future visual presentation may round them.

`--method-sof` accepts the existing `method-sof` result for rare-event, diagnostic, multiple-cutoff diagnostic, network, dose-response, single-group and dependent-effect papers. A multi-paper SoF input is filtered to exact paper manifest and method; only matching rows become `method_sof_bound.csv`. Pairwise uses its already bound quality/SoF packet. The rare-event rows keep MH primary separate from IV/Peto sensitivity, identify double-boundary exclusions and show an absolute effect only for a sourced baseline risk explicitly reviewed as applicable. A stale or different-paper SoF is refused.

`--official-rob` binds externally completed RoB 2/ROBINS-I results **only to their checked pairwise quality packet**, copying the assessment references and non-final appendix. `--method-rob` uses a distinct checked study-design contract for **network and rare-event intervention** papers and copies the supplied overall judgments and external assessment references. Both refuse another packet/paper or a synthetic/real mode conflict. Neither parses an external questionnaire or runs its official algorithm. The method route is not applicable to diagnostic studies.
