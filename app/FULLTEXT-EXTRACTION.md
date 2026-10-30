# Local full-text candidate extraction and value review

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


This module handles **legally supplied local files**, not network retrieval. Its deterministic text scan proposes numeric tokens and page/table locations. An Agent may help prioritize or map proposals, but the scan does not decide eligibility or verify a source value. Source bytes remain at the supplied local path; the output contains short text contexts and hashes, so keep the output local as research material. Do not put patient identifiers or confidential full text into external model inputs.

PDF reading has a narrow `PDF_PAGE_READERS` adapter in `scripts/fulltext_extract.py`: a reader returns ordered `(one-based page number, extracted text)` pairs. The default selectable-text PDF reader is separately installed [pdfplumber 0.11.10](https://pypi.org/project/pdfplumber/) (MIT). It was tested on an actual selectable-text synthetic PDF generated without PyMuPDF. The previous optional PyMuPDF path was removed from the scanner; old receipt files can still be read for their existing audit checks. This reader does not perform OCR, verify numerical meaning or establish table semantics.

## 1. Register and scan

The optional local CPU Docling reader has a separate [customer entry and evidence contract](DOCLING-PDF.md). It consumes the same registered documents and produces the existing scan/template/resolve contract plus lossless table and block evidence. The original pdfplumber scanner remains available.

Prepare `documents.csv` with `record_id,source_document,file_path,format,rights_basis`. Every `record_id` must exist in the bibliography. `rights_basis` is a user supplied access statement, not a legal determination. `format` is `pdf`, `html`, or `text` (UTF-8; form feed separates pages). PDF must have selectable text; scanned image pages need an independently reviewed OCR step. HTML has no page number unless its own text says so; table numbers are proposed from `<table>` order. Each file is bounded at 25 MB and each document at 500 pages.

```text
./launch.cmd meta fulltext-scan --records records.csv --documents documents.csv --out fresh-scan
```

`numeric_candidates.csv` includes a stable candidate ID, record/document ID, local file hash, PDF/text page, line, raw token, parsed number, percent marker, nearby text, and a **suggested** location. `documents.csv` and `scan_receipt.json` bind the local files and candidate table. A candidate such as `20%` cannot be accepted as an effect value without an explicit corrected value and reason; no unit transformation is inferred.

PDF reading uses the explicitly selected `pdfplumber` 0.11.10 environment and matching dependencies. HTML and text use Python's standard library. The standard online setup installs these fixed PDF-reader dependencies; the optional Docling setup is separate.

### Scanned-page preflight

`./launch.cmd meta ocr-pages inspect --records records.csv --documents documents.csv --image-reader unknown --external-ocr unknown --out fresh-ocr-inspection` checks each local PDF page for selectable text and a large raster image. The two capability flags may be `unknown`, `declared_available` or `declared_unavailable` and describe the **current caller's** image-reading/external-OCR ability, not a detected or authenticated host feature. No platform or Agent brand is assumed. It writes `ocr_pages.csv` with original PDF hash, record/document ID, one-based page, text character count, estimated image coverage, largest image bbox or text-layer location, detection method and `PENDING_SOURCE_REVIEW`. `available_paths` lists the detected text-layer route or caller-declared image/OCR routes; `USER_SUPPLIED_TEXT` remains a resumable option when neither is available. Classifications are `IMAGE_ONLY_CANDIDATE`, `MIXED_LOW_TEXT_CANDIDATE`, `SELECTABLE_TEXT` and `LOW_TEXT_MANUAL`. `ocr-pages verify --inspection fresh-ocr-inspection` rechecks the input bytes. This is a page classifier, **not OCR**; a large image may contain no readable text and low text may have other causes.

To continue with **caller-supplied** page text or numeric candidates from an actually available host image reader, external OCR, or a user's own transcription, make `external_results.csv` with `result_id,record_id,source_document,source_sha256,page,method,producer_label,external_result_reference,source_locator,raw_text,raw_number,confidence,review_status`. `method` is `host_image_reading`, `external_ocr` or `user_supplied_text`; the first two require the matching capability declaration in the inspection. `source_sha256` is the **original PDF** SHA-256; `page` and `source_locator` must identify that PDF page. `external_result_reference` is a nonempty local caller label/receipt identifier, not proof of identity. Keep `review_status=unreviewed_candidate`; confidence may be blank and is never treated as calibrated. `raw_number` may be blank to propose all number tokens in the supplied short `raw_text`, or name one token occurring exactly once.

```text
./launch.cmd meta external-page-import --inspection fresh-ocr-inspection --external-results external_results.csv --out fresh-external-scan
./launch.cmd meta fulltext-template --scan fresh-external-scan --targets targets.csv --out fresh-templates
./launch.cmd meta fulltext-resolve --scan fresh-external-scan --targets targets.csv --reviewer-a reviewer.csv --mode exploratory_single --out fresh-review
```

## 2. Plan one effect and create reviewer templates

Prepare `targets.csv` with `effect_id,record_id,study_id,cohort_id,effect_type,outcome,timepoint,contrast,adjustment,source_document`. The effect type must be RR, OR, HR, MD, or SMD. A target names one source document from the scan. It does not assert the document has the planned effect or that reports refer to independent cohorts.

```text
./launch.cmd meta fulltext-template --scan fresh-scan --targets targets.csv --out fresh-templates
```

Copy `reviewer_template.csv` to a separately completed file per reviewer. For each target, fill `estimate`, `ci_lower`, and `ci_upper` rows. Fields are `effect_id,field,candidate_id,decision,value,verified_location,reason,reviewer,reviewed_at`. Use `accept` for a checked candidate number, `correct` for an explicitly changed number or unit with a reason, or `pending` without a claimed value. A reviewed location must name the candidate's page for PDF/text and a page/table/figure identifier; HTML table locators can use `table N`. `adjudication_template.csv` is header only; add rows solely for real disagreements and include `adjudication_reason`.

### Single-review exploration

```text
./launch.cmd meta fulltext-resolve --scan fresh-scan --targets targets.csv --reviewer-a reviewer.csv --mode exploratory_single --out fresh-exploration
```

This accepts one self-identified reviewer or an explicitly agent-assisted exploratory file. Complete values are exported to `effects_exploratory.csv`, labeled `extraction_review_mode=exploratory_single`; they are **not** a formal two-reviewer extraction. The earlier direct numeric path remains usable for exploration. A pending value blocks export.

### Formal dual-review route

```text
./launch.cmd meta fulltext-resolve --scan fresh-scan --targets targets.csv --reviewer-a reviewer_a.csv --reviewer-b reviewer_b.csv --adjudication adjudication.csv --mode formal_dual --reviewer-a-role human_attested --reviewer-b-role human_attested --adjudicator-role human_attested --out fresh-formal-review
```

The two submitted files must name different self-declared reviewers. Differences in candidate, decision, value, location, or correction reason require a distinct third adjudicator with a dated rationale. AI simulated or agent-assisted roles cannot be marked formal by this interface. Identity, independence, source interpretation and blinding are **not** authenticated by software. A protocol can set `review_workflow_mode=formal_dual`; then `review.py confirm/verify` requires both a formal dual-screen decision file and this formal dual-reviewed extraction. An exploratory protocol need not demand two reviewers.

An incomplete run writes `review_votes.csv`, `value_review_audit.csv`, `conflicts.csv`, `missing_values.csv`, and `review_receipt.json`, exits 2, and writes no effects. After adding votes/adjudication, rerun with the same `--out` and `--resume`; the previous attempt is preserved alongside as `.prior-0001`, `.prior-0002`, etc. The allowlisted `customer_workflow.py --resume` passes this through for the paused resolve stage. A completed output cannot be overwritten.

On completion the result contains `effects_reviewed.csv` or `effects_exploratory.csv`, the per-value vote/audit trail, and a `source_review_template.csv` deliberately left `pending` for the later source signoff gate. `literature.py link` and `review.py` recheck scan, original file, reviewer input and output hashes when they see this extraction marker. They detect ordinary local changes; a machine owner can deliberately rewrite all evidence and hashes. The resulting table still needs existing `literature.py link`, report-to-study mapping, cohort overlap checks, protocol/analysis agreement, RoB records, and human interpretation. For raw two-arm counts or means/SD, use the separate `derive_effects.R` route; this module does not derive such effects.

The development scanner defaults to `--pdf-reader pdfplumber` from the project-private 0.11.10 install. It proposes text and table locations; it performs no OCR and cannot establish semantic correctness. Local synthetic PDF/HTML tests establish code behavior only; they are not a real-study extraction or completed systematic review.
