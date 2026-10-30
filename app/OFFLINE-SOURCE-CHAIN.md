# Offline search updates and local full-text access

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


These commands **do not search a database or download a paper**. They reconcile locally imported RIS/CSV batches and user-supplied, lawfully accessible PDF, HTML, or text files. Search dates, strategy references, access basis, and reviewer identities are user claims. SHA-256 checks detect accidental changes to referenced local bytes; they do not authenticate a database or person. No patient data is needed.

## Versioned bibliography

Import each search/export batch with a **new stable source label** using `literature.py import` or `import_ris.py`; keep its directory and original export. Even an update of the same database receives a new label, while `source_name` remains the same. Create `batches.csv` with columns:

`source_label,batch_id,source_name,identification_route,phase,update_of,searched_on,strategy_reference,reviewer`

`identification_route` is `database_register` or `other_source`; `phase` is `initial` or `update`. An update names an earlier `batch_id` from the same source. For example:

```powershell
./launch.cmd meta source-update --source registry-2025-import --batch-ledger batches1.csv --out chain-v1-pending
./launch.cmd meta source-update --source registry-2025-import --batch-ledger batches1.csv --dispositions dispositions1.csv --out chain-v1
./launch.cmd meta source-update --prior chain-v1 --source registry-2026-import --source handsearch-import --batch-ledger batches2.csv --dispositions dispositions2.csv --out chain-v2
./launch.cmd meta source-update --prior chain-v2 --dispositions dispositions3.csv --out chain-v3
```

`dispositions.csv` is an **append-only history** with columns `record_id,disposition,retained_record_id,reason,reviewer,decision_date,revision_of,revision_reason`. Valid decisions are `keep`, `remove_duplicate`, `remove_other`. Removal requires a reason; duplicate removal also needs the retained record ID. Reversal appends a new row naming the previous decision and explaining the change. The source folders and older version outputs must remain at their recorded paths. A fresh version directory is required for each call.

`chain_receipt.json` reports `NEEDS_DEDUP_REVIEW` until every record has an explicit decision and exact DOI/PMID pairs kept as separate records have a documented rationale. Candidate flags never delete a record. Only `READY_FOR_SCREENING` emits `dedup.csv`. `incremental_comparison.csv` distinguishes newly seen IDs from candidates matching earlier batches; an article found by several sources remains several *records* until a reviewer explicitly reconciles them. `source_methods.csv` and `search_batches.csv` feed the local PRISMA accounting. A withdrawal or retraction is an explicit `remove_other` decision, not a silent deletion.

On entry, the preserved `original_import.csv` must match its import manifest and regenerate the current `records.csv` byte for byte. For RIS, the preserved raw `.ris` must regenerate the CSV bridge, ordered tag ledger and trace. A legitimate metadata correction therefore uses a new documented import/batch version with a distinct source label; do not edit a prior normalized `records.csv` in place. This is local consistency checking, not independent bibliographic authentication.

## Local report acquisition

After screening the kept records, create `attempts.csv` with columns:

`record_id,attempt_id,status,source_document,file_path,format,rights_basis,document_doi,document_pmid,version_relation,identity_basis,identity_evidence,reason,reviewer,decision_date,revision_of,revision_reason`

For a Europe PMC `alternative_candidate`, add optional review columns `review_mode,identity_conclusion,version_conclusion,version_evidence` when appending an acceptance revision. `review_mode` is `formal_review` (reviewer-declared formal review) or `exploratory_agent`. Promotion requires `identity_conclusion=same_report`, `version_conclusion=version_of_record` or `same_report_alternative`, a newly stated version relation, new identity evidence and version evidence. Copying the candidate's pending-review text or merely changing `status` is rejected. A formal review row cannot retain the `AGENT_` reviewer marker. Agent exploratory outputs appear only in `exploratory_documents.csv`, not the formal `documents.csv`, and full-text screening must remain pending. Names and declarations are auditable claims, not independent authentication of a human or source.

Statuses: `pending`, `awaiting_permission`, `not_retrieved`, `retrieved_primary`, `alternative_candidate`, `retrieved_alternative`. File-bearing states require a local PDF/HTML/text path, a document name and access basis. A primary report's entered DOI/PMID cannot conflict with the indexed record; `doi_in_text`, `pmid_in_text`, or `title_in_text` checks require matching selectable text. `human_claim` needs an explanation and remains explicitly unverified by software. An alternative version needs its relation and an explicit acceptance revision before it enters `documents.csv` for `meta.py fulltext-scan`. A failed or pending acquisition needs a reason where applicable. A downloaded `alternative_candidate` counts as a **file obtained** in PRISMA retrieval accounting, with full-text assessment pending; it is neither an included report nor a reviewed source for extraction.

```powershell
./launch.cmd meta fulltext-access --chain chain-v3 --decisions screening.csv --attempts attempts1.csv --out access-v1
./launch.cmd meta fulltext-access --chain chain-v3 --decisions screening-updated.csv --attempts attempts2.csv --prior access-v1 --out access-v2
./launch.cmd meta fulltext-scan --records chain-v3/records.csv --documents access-v2/documents.csv --out scan-v1
```

`attempts.csv` also preserves previous rows exactly; each new or revised attempt appends a new `attempt_id`, `revision_of` previous attempt ID, and a reason. Existing prior inputs, receipts, outputs and document bytes are checked before an update. `retrieval.csv` uses the existing PRISMA `retrieved/not_retrieved/pending` contract. Its `retrieved` includes downloaded alternative candidates, while `retrieval_receipt.json` separates `retrieved_reports` (files obtained) from `reviewed_retrieved_reports` (accepted local documents). A report still awaiting permission or not retrieved **must have a pending full-text screening decision** and cannot be included. `missing_attempts.csv` makes incomplete sought reports visible; `NEEDS_ATTEMPTS` is not a complete retrieval ledger. To run local PRISMA accounting, pass the chain's `source_methods.csv` and the access output's `retrieval.csv` to `prisma2020_flow.py` with the usual confirmed core inputs.

### One customer PDF replenishment list

For an existing access version, create one list with record ID, title, DOI, PMID, prior failure reason and whether an alternative file is already obtained:

```powershell
./launch.cmd meta fulltext-fill list --chain chain-v3 --prior access-v1 --out gap-v1
./launch.cmd meta fulltext-fill scan --list gap-v1 --pdf-dir customer-pdf-drop --out pdf-scan-v1
```

Place lawfully held PDFs directly in `customer-pdf-drop`. The scan checks PDF structure, selectable first-page text and identifiers against **all reports in the source chain**, including already obtained reports; it suggests links only for reports still missing a file. It reports wrong-paper conflicts, byte-identical duplicates, possible abstract-only files and access-error pages. These are **candidate checks**, not proof of full text, a license, a version of record or study eligibility. `gap-v1/fulltext_resolution_list.csv` includes an obtained OA alternative as *awaiting identity/version review*, not as missing bytes; the scanner targets only reports without a file. A scanned PDF never enters `documents.csv` or PRISMA as retrieved automatically.

Inspect `pdf-scan-v1/pdf_matches.csv`. For an unambiguous candidate, `attempts_review_template.csv` preserves the old attempt history and adds one row with blank `status`, `rights_basis`, `reviewer` and `decision_date`. Check the actual PDF, full-text scope, identifier, permission and version; then fill those fields and a revision reason. For a primary report choose `retrieved_primary` only after that review. Conflict, duplicate, alternative-version and abstract-only files need explicit resolution through the existing attempt-history format; no machine row is promoted for them. Then continue the **same chain and screening project**, with a fresh output version:

```powershell
./launch.cmd meta fulltext-access --chain chain-v3 --decisions screening.csv --attempts reviewed-attempts.csv --prior access-v1 --out access-v2
```

PDF text-layer scans also emit `table_cell_candidates.csv` with page, *detected* table index, row/column and bounding box in PDF points. Matching numeric tokens enter `numeric_candidates.csv` and use the existing `fulltext-resolve` reviewer workflow. Detected index is **not** an article's published table number. The reviewer must inspect the original source, enter the real locator, check the statistic and units, and correct misleading tokens. Scanned pages/OCR and semantic equivalence are not supplied by this module.
