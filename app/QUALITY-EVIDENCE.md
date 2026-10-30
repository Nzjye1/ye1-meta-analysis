# Design-specific RoB evidence and outcome-level certainty ledger

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


This development-source module records reviewer judgments for **one protocol outcome and timepoint** already represented by a checked evidence packet. It does not run an official risk-of-bias instrument, calculate GRADE certainty, reproduce licensed questionnaire text, authenticate reviewer identity, or replace clinical review. All `low` and `high` judgments and the final certainty are supplied by people (or remain explicitly exploratory draft).

## Inputs and commands

Start from a fresh `report.py` packet containing `report_inputs.json`, `included_studies.csv`, a protocol-bound statistics result, and the checked source/selection ledgers. Supply `study_designs.csv` with exactly one row per included `study_id`:

`study_id,design_type,instrument_name,instrument_version,instrument_reference,design_note`

Supported design tags are `randomized`, `nonrandomized_intervention`, `observational_exposure`, `diagnostic_accuracy`, and `single_group`. These tags choose generic evidence slots, **not** an official scoring algorithm. The recorded instrument name, version and reference are user supplied; use an instrument appropriate to the actual design and current license. No real tool's questionnaire is copied.

```powershell
./launch.cmd meta quality-plan --packet checked-packet --designs study_designs.csv --out fresh-quality-plan
./launch.cmd meta quality-resolve --plan fresh-quality-plan --reviewer-a reviewer_a.csv --mode exploratory_single --reviewer-a-role agent_assisted --out fresh-quality-review
```

The plan writes `reviewer_template.csv`. Each row is one study/domain, study overall judgment, one GRADE domain for the protocol outcome, or its overall certainty. Required columns are `item_type,study_id,domain,status,judgment,rationale,evidence_file,evidence_sha256,evidence_locator,reviewer,reviewed_at`. Set `status=pending` with no judgment or evidence until assessed. An assessed row needs a reason and local evidence file with its SHA-256; study RoB rows need a page/table/figure locator. GRADE domains are risk of bias, inconsistency, indirectness, imprecision, and publication bias. The overall GRADE row accepts `high`, `moderate`, `low`, or `very_low`; **the program does not derive it from domain rows**. `reviewed_at` is `YYYY-MM-DD`. Evidence locator and file hashes check traceability and ordinary local changes, not whether a claim is clinically correct.

An Agent can read a locally supplied source and propose judgments **without making reviewer votes**. Write a partial `agent_proposals.csv` with `item_type,study_id,domain,proposed_judgment,rationale,evidence_file,evidence_sha256,evidence_locator,evidence_excerpt,agent_id,suggested_at`, quoting 8–700 exact source characters from the cited PDF page or local text/HTML/CSV. Run `./launch.cmd meta quality-suggest --plan fresh-quality-plan --proposals agent_proposals.csv --out fresh-agent-suggestions`. The module checks the excerpt against the cited local bytes/page and emits `agent_suggestions.csv` labeled `AGENT_PROPOSAL_NOT_ASSESSED` plus `reviewer_template_with_suggestions.csv` whose actual status and judgment columns remain pending/blank. A reviewer must assess the source and supply a separate vote CSV. Use `--suggestions fresh-agent-suggestions` with `quality-resolve` to bind the proposal trail; no proposed judgment is copied into a decision. Text matching proves the quote is present, not that the inference is clinically sound. Do not send confidential full text to an external model.

For a `Table N` locator in PDF/text, the matching page excerpt must visibly contain that table marker; an absent marker (such as `Table 999`) is rejected. Formats without a verifiable table/page layout are marked `TABLE_LOCATION_UNVERIFIED_FOR_THIS_FORMAT` in the suggestion ledger. A successful marker check still does not verify the study's methods, the numeric value, or the proposed clinical judgment.

For a formal dual review, use separate reviewer files and explicit human role declarations:

```powershell
./launch.cmd meta quality-resolve --plan fresh-quality-plan --reviewer-a reviewer_a.csv --reviewer-b reviewer_b.csv --adjudication adjudication.csv --mode formal_dual --reviewer-a-role human_attested --reviewer-b-role human_attested --adjudicator-role human_attested --out fresh-quality-review
```

The optional adjudication CSV adds `adjudication_reason`. A disagreement in status, judgment, rationale, source, or locator needs a distinct adjudicator; missing votes, pending items and unresolved conflicts stop SoF output. A stopped review retains `review_decisions.csv`, `missing_items.csv`, `conflicts.csv` and `quality_receipt.json`; supply completed vote files and use the **same output path** with `--resume`. Prior attempts are kept as `.prior-0001`, etc. The current and prior audit file hashes are checked when verifying a completed review. Role labels are self declarations; the software cannot prove independence, blinding, or identity. An Agent may suggest evidence and draft judgments in exploratory mode; never label those as human formal review.

A complete result includes `risk_of_bias_design_audit.csv`, `sof_table.csv`, and `quality_report.md`. The SoF row binds the outcome, timepoint, effect type, pooled result and study count to the checked statistics. Participant count is `NOT_SUPPLIED` and absolute effect is `NOT_COMPUTED`; this is a deliberately limited SoF, not a complete clinical presentation. Attach to a fresh packet with `report.py --quality-dir fresh-quality-review` alongside the original report inputs. The report rechecks packet, source, vote, output and prior-audit hashes. The original packet remains unchanged. Every packet and manuscript stays draft until human signoff.

The SoF also records the protocol outcome's `unit` when supplied, otherwise `UNIT_NOT_SUPPLIED`. Its overall certainty row cites the reviewer evidence file, hash and locator. In exploratory mode the Markdown and CSV explicitly label the certainty as a draft, including `agent_assisted` or `ai_simulated` role when declared. In formal mode the role is human-attested but identity is not authenticated.
