"""Local full-text numeric candidates and human value-by-value review. No semantic auto-verification."""
import argparse
import csv
import datetime as dt
from decimal import Decimal, InvalidOperation
import hashlib
from html.parser import HTMLParser
import importlib.metadata
import json
import os
from pathlib import Path
import re
import sys
import tempfile

import literature as lit

DOC_FIELDS = ["record_id", "source_document", "file_path", "format", "rights_basis"]
TARGET_FIELDS = ["effect_id", "record_id", "study_id", "cohort_id", "effect_type",
                 "outcome", "timepoint", "contrast", "adjustment", "source_document"]
REVIEW_FIELDS = ["effect_id", "field", "candidate_id", "decision", "value", "verified_location",
                 "reason", "reviewer", "reviewed_at"]
ADJ_FIELDS = REVIEW_FIELDS + ["adjudication_reason"]
VALUE_FIELDS = ("estimate", "ci_lower", "ci_upper")
NUMERIC_AUDIT_FIELDS = ["numeric_policy", "source_char_start", "source_char_end", "normalization_rule",
                        "numeric_evidence_sha256", "source_conflict_ids_json"]
EFFECT_FIELDS = ["record_id", "study_id", "cohort_id", "effect_type", "estimate", "ci_lower", "ci_upper",
                 "outcome", "timepoint", "contrast", "adjustment", "source_document", "source_location",
                 "extraction_review_mode", "fulltext_scan_sha256"]
NUMBER = re.compile(r"(?<![\w./])(?P<num>[+\-−]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:[eE][+\-]?\d+)?|[+\-−]?\.\d+(?:[eE][+\-]?\d+)?)(?P<pct>%?)(?![\w./])")
TABLE = re.compile(r"(?i)\btable\s+([A-Za-z0-9]+)\b")


class HTMLText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.table_number, self.in_table, self.hidden = [], 0, 0, 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        if tag == "table":
            self.table_number += 1
            self.in_table += 1
            self.parts.append(f"\nTable {self.table_number}\n")
        elif tag in {"tr", "p", "div", "section", "article", "h1", "h2", "h3", "br"}:
            self.parts.append("\n")
        elif tag in {"td", "th"}:
            self.parts.append("\t")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)
        if tag == "table":
            self.in_table = max(0, self.in_table - 1)
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def iso_day(text, label):
    try:
        dt.date.fromisoformat(text)
    except (ValueError, TypeError):
        lit.fail(f"{label}: YYYY-MM-DD required")


def number(text, label):
    try:
        value = Decimal(text.strip().replace(",", "").replace("−", "-"))
    except (InvalidOperation, AttributeError):
        lit.fail(f"{label}: finite numeric value required")
    if not value.is_finite():
        lit.fail(f"{label}: finite numeric value required")
    return value


def read_pdf_pdfplumber(path):
    """Project-private MIT-licensed selectable-text page adapter."""
    private = Path(__file__).resolve().parents[1] / "method-python-library"
    if private.is_dir() and str(private) not in sys.path:
        sys.path.insert(0, str(private))
    try:
        import pdfplumber
    except ImportError:
        lit.fail("pdfplumber reader unavailable; prepare the project-private PDF dependency or use local text/HTML")
    try:
        with pdfplumber.open(path) as document:
            if len(document.pages) > 500:
                lit.fail("PDF exceeds 500-page bound")
            return [(i + 1, page.extract_text() or "") for i, page in enumerate(document.pages)]
    except Exception as exc:
        lit.fail(f"pdfplumber text extraction failed: {exc}")


PDF_PAGE_READERS = {"pdfplumber": read_pdf_pdfplumber}

TABLE_CELL_FIELDS = ["cell_id", "record_id", "source_document", "source_sha256", "page",
                     "detected_table", "row", "column", "x0", "top", "x1", "bottom",
                     "cell_text", "extractor"]


def pdf_table_cells(path, rid, name, digest):
    """Text-layer table coordinates in PDF points; detected indices are not published table numbers."""
    private = Path(__file__).resolve().parents[1] / "method-python-library"
    if private.is_dir() and str(private) not in sys.path:
        sys.path.insert(0, str(private))
    try:
        import pdfplumber
    except ImportError:
        lit.fail("pdfplumber table reader unavailable in the project-private library")
    rows = []
    try:
        with pdfplumber.open(path) as document:
            if len(document.pages) > 500:
                lit.fail("PDF exceeds 500-page bound")
            for page_no, page in enumerate(document.pages, 1):
                for table_no, table in enumerate(page.find_tables(), 1):
                    values = table.extract()
                    for row_no, table_row in enumerate(table.rows, 1):
                        for column_no, bbox in enumerate(table_row.cells, 1):
                            if bbox is None:
                                continue
                            value = (values[row_no - 1][column_no - 1] or "").strip()
                            if not value:
                                continue
                            key = f"{digest}\x1f{rid}\x1f{name}\x1f{page_no}\x1f{table_no}\x1f{row_no}\x1f{column_no}\x1f{bbox}"
                            rows.append(dict(cell_id="CELL-" + hashlib.sha256(key.encode()).hexdigest()[:20],
                                record_id=rid, source_document=name, source_sha256=digest, page=page_no,
                                detected_table=table_no, row=row_no, column=column_no,
                                x0=f"{bbox[0]:.2f}", top=f"{bbox[1]:.2f}",
                                x1=f"{bbox[2]:.2f}", bottom=f"{bbox[3]:.2f}",
                                cell_text=value[:500], extractor="pdfplumber_text_layer_table_candidate_only"))
                            if len(rows) > 5_000:
                                lit.fail("table cell count exceeds 5,000; split the PDF batch")
    except Exception as exc:
        lit.fail(f"pdfplumber table detection failed: {exc}")
    return rows


def pages(path, kind, pdf_reader="pdfplumber"):
    if kind == "pdf":
        if pdf_reader not in PDF_PAGE_READERS:
            lit.fail(f"unsupported PDF page reader: {pdf_reader}")
        return PDF_PAGE_READERS[pdf_reader](path)
    raw = path.read_text(encoding="utf-8-sig")
    if kind == "text":
        return [(i + 1, part) for i, part in enumerate(raw.split("\f"))]
    parser = HTMLText()
    parser.feed(raw)
    return [(1, "".join(parser.parts))]


def scan(a):
    records, _ = lit.read_csv(a.records, ["record_id", "title"])
    ids = {row["record_id"] for row in records}
    if len(ids) != len(records):
        lit.fail("repeated bibliography record_id")
    docs, _ = lit.read_csv(a.documents, DOC_FIELDS)
    catalog, candidates, table_cells = [], [], []
    used = set()
    for i, row in enumerate(docs, 2):
        if any(row.get(field) is None for field in DOC_FIELDS):
            lit.fail(f"document row {i}: missing CSV cells")
        rid, name, kind = row["record_id"], row["source_document"].strip(), row["format"].lower().strip()
        if rid not in ids or not name or (rid, name) in used or kind not in {"pdf", "html", "text"}:
            lit.fail(f"document row {i}: unknown record, repeated/blank document name, or unsupported format")
        if not row["rights_basis"].strip():
            lit.fail(f"document row {i}: user-attested access/rights basis required")
        used.add((rid, name))
        path = Path(row["file_path"]).expanduser().resolve()
        if not path.is_file() or path.suffix.lower() not in {"pdf": {".pdf"}, "html": {".html", ".htm"},
                                                            "text": {".txt"}}[kind]:
            lit.fail(f"document row {i}: missing file or format/extension mismatch")
        size = path.stat().st_size
        if size <= 0 or size > 25_000_000:
            lit.fail(f"document row {i}: file must be 1 to 25,000,000 bytes")
        digest = lit.sha256(path)
        extracted = pages(path, kind, a.pdf_reader)
        engine = ("pdfplumber " + importlib.metadata.version("pdfplumber")) if kind == "pdf" else "Python standard library"
        if not extracted or len(extracted) > 500:
            lit.fail(f"document row {i}: no pages or exceeds 500-page bound")
        catalog.append(dict(record_id=rid, source_document=name, file_path=str(path), format=kind,
                            rights_basis=row["rights_basis"], source_sha256=digest, page_count=len(extracted),
                            bytes=size, extraction_engine=engine))
        if kind == "pdf":
            cells = pdf_table_cells(path, rid, name, digest)
            table_cells.extend(cells)
            if len(table_cells) > 5_000:
                lit.fail("table cell count exceeds 5,000; split the document batch")
            for cell in cells:
                for token_no, match in enumerate(NUMBER.finditer(cell["cell_text"]), 1):
                    key = cell["cell_id"] + f"\x1f{match.start()}"
                    candidates.append(dict(candidate_id="NUM-" + hashlib.sha256(key.encode()).hexdigest()[:20],
                        record_id=rid, source_document=name, source_sha256=digest, page=cell["page"],
                        line="", token=token_no, raw_token=match.group(0),
                        parsed_number=str(number(match.group("num"), "table candidate")),
                        unit_suffix=match.group("pct"),
                        suggested_location=(f"page {cell['page']} detected table {cell['detected_table']} "
                                            f"row {cell['row']} column {cell['column']} "
                                            f"bbox ({cell['x0']}, {cell['top']}, {cell['x1']}, {cell['bottom']})"),
                        context=cell["cell_text"][:280], extractor="pdfplumber_table_cell_candidate_only"))
                    if len(candidates) > 10_000:
                        lit.fail("candidate count exceeds 10,000; split the document batch")
        for page_no, text in extracted:
            if len(text) > 1_000_000:
                lit.fail(f"document row {i} page {page_no}: extracted text too large")
            recent_table, table_line = "", -100
            for line_no, line in enumerate(text.splitlines(), 1):
                line = " ".join(line.split())
                if not line:
                    continue
                table = TABLE.search(line)
                if table:
                    recent_table, table_line = table.group(1), line_no
                suggested = f"page {page_no}" if kind != "html" else "HTML document"
                if recent_table and line_no - table_line <= 20:
                    suggested += f" table {recent_table}"
                if kind == "html" and not recent_table:
                    suggested = "HTML text (no page number)"
                for token_no, match in enumerate(NUMBER.finditer(line), 1):
                    value = str(number(match.group("num"), "candidate"))
                    key = f"{digest}\x1f{rid}\x1f{name}\x1f{page_no}\x1f{line_no}\x1f{match.start()}"
                    cid = "NUM-" + hashlib.sha256(key.encode()).hexdigest()[:20]
                    candidates.append(dict(candidate_id=cid, record_id=rid, source_document=name,
                        source_sha256=digest, page=page_no if kind != "html" else "", line=line_no,
                        token=token_no, raw_token=match.group(0), parsed_number=value,
                        unit_suffix=match.group("pct"), suggested_location=suggested,
                        context=line[:280], extractor="numeric_text_candidate_only"))
                    if len(candidates) > 10_000:
                        lit.fail("candidate count exceeds 10,000; split the document batch")
    out = Path(a.out).resolve()
    if out.exists():
        lit.fail("output exists; use a fresh scan directory")
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".fulltext-scan-", dir=out.parent) as tmp:
        stage = Path(tmp) / "result"
        stage.mkdir()
        lit.write_csv(stage / "documents.csv", list(catalog[0]), catalog)
        fields = ["candidate_id", "record_id", "source_document", "source_sha256", "page", "line",
                  "token", "raw_token", "parsed_number", "unit_suffix", "suggested_location", "context", "extractor"]
        lit.write_csv(stage / "numeric_candidates.csv", fields, candidates)
        lit.write_csv(stage / "table_cell_candidates.csv", TABLE_CELL_FIELDS, table_cells)
        (stage / "scan_receipt.json").write_text(json.dumps(dict(schema="meta-fulltext-scan-v1",
            pdf_reader=a.pdf_reader,
            records_path=str(Path(a.records).resolve()), records_sha256=lit.sha256(a.records),
            input_documents_path=str(Path(a.documents).resolve()), input_documents_sha256=lit.sha256(a.documents),
            documents_sha256=lit.sha256(stage / "documents.csv"), candidates_sha256=lit.sha256(stage / "numeric_candidates.csv"),
            table_cells_sha256=lit.sha256(stage / "table_cell_candidates.csv"),
            status="CANDIDATES_ONLY_NOT_VERIFIED", document_count=len(catalog), candidate_count=len(candidates),
            table_cell_count=len(table_cells), table_indices_are_published_numbers=False), indent=2) + "\n",
            encoding="utf-8")
        os.replace(stage, out)
    print(f"CANDIDATES_ONLY_NOT_VERIFIED: {len(catalog)} documents, {len(candidates)} numeric tokens; {out}")


def checked_scan(folder):
    folder = Path(folder).resolve()
    receipt = json.loads((folder / "scan_receipt.json").read_text(encoding="utf-8"))
    if receipt.get("schema") != "meta-fulltext-scan-v1":
        lit.fail("invalid fulltext scan receipt")
    for key, path in (("records_sha256", receipt["records_path"]),
                      ("input_documents_sha256", receipt["input_documents_path"]),
                      ("documents_sha256", folder / "documents.csv"),
                      ("candidates_sha256", folder / "numeric_candidates.csv")):
        if not Path(path).is_file() or lit.sha256(path) != receipt[key]:
            lit.fail(f"scan source or output changed: {key}")
    if "table_cells_sha256" in receipt and (not (folder / "table_cell_candidates.csv").is_file() or
            lit.sha256(folder / "table_cell_candidates.csv") != receipt["table_cells_sha256"]):
        lit.fail("scan table-cell candidates changed")
    if receipt.get("pdf_reader") == "docling_cpu":
        artifacts = receipt.get("docling_artifacts_sha256", {})
        if not artifacts or "semantic_candidates.csv" not in artifacts:
            lit.fail("Docling artifact manifest missing")
        for name, digest in artifacts.items():
            path = (folder / name).resolve()
            if not path.is_relative_to(folder) or not path.is_file() or lit.sha256(path) != digest:
                lit.fail("Docling structured evidence changed: " + name)
    if receipt.get("pdf_reader") == "external_page_candidate_import":
        for key, path in (("external_results_sha256", receipt.get("external_results_path")),
                          ("inspection_receipt_sha256", Path(receipt.get("inspection_path", "")) / "ocr_inspection.json"),
                          ("external_page_results_sha256", folder / "external_page_results.csv")):
            if not path or not Path(path).is_file() or lit.sha256(path) != receipt.get(key):
                lit.fail("external page result source/output changed: " + key)
        import ocr_pages
        _, inspection, _ = ocr_pages.checked_inspection(receipt["inspection_path"])
        if inspection["records_sha256"] != receipt["records_sha256"] or \
                inspection["documents_sha256"] != receipt["input_documents_sha256"]:
            lit.fail("external page result inspection differs from scan inputs")
    docs, _ = lit.read_csv(folder / "documents.csv", [*DOC_FIELDS, "source_sha256"])
    for doc in docs:
        if not Path(doc["file_path"]).is_file() or lit.sha256(doc["file_path"]) != doc["source_sha256"]:
            lit.fail(f"fulltext source changed: {doc['record_id']} / {doc['source_document']}")
    candidates, _ = lit.read_csv(folder / "numeric_candidates.csv", ["candidate_id", "record_id",
         "source_document", "source_sha256", "parsed_number", "unit_suffix", "suggested_location"] , allow_empty=True)
    by_id = {row["candidate_id"]: row for row in candidates}
    if len(by_id) != len(candidates):
        lit.fail("repeated numeric candidate IDs")
    if receipt.get("pdf_reader") == "docling_cpu":
        import docling_pdf
        docling_pdf.check_numeric_evidence(folder, receipt, docs, candidates)
    return receipt, docs, by_id


def checked_targets(path, docs):
    targets_list, _ = lit.read_csv(path, TARGET_FIELDS)
    targets = {row["effect_id"]: row for row in targets_list}
    if len(targets) != len(targets_list) or any(not key.strip() for key in targets):
        lit.fail("target effects need distinct nonblank effect_id")
    doc_keys = {(d["record_id"], d["source_document"]) for d in docs}
    for i, row in enumerate(targets_list, 2):
        if any(not (row.get(k) or "").strip() for k in TARGET_FIELDS) or (
                row["record_id"], row["source_document"]) not in doc_keys:
            lit.fail(f"target row {i}: blank field or document absent from scan")
        if row["effect_type"] not in {"RR", "OR", "HR", "MD", "SMD"}:
            lit.fail(f"target row {i}: unsupported effect type")
    return targets_list, targets


def template(a):
    _, docs, _ = checked_scan(a.scan)
    targets_list, _ = checked_targets(a.targets, docs)
    out = Path(a.out).resolve()
    if out.exists():
        lit.fail("output exists; use a fresh template directory")
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".fulltext-template-", dir=out.parent) as tmp:
        stage = Path(tmp) / "result"
        stage.mkdir()
        lit.write_csv(stage / "reviewer_template.csv", REVIEW_FIELDS, [
            dict(effect_id=target["effect_id"], field=field, candidate_id="", decision="pending",
                 value="", verified_location="", reason="", reviewer="", reviewed_at="")
            for target in targets_list for field in VALUE_FIELDS])
        lit.write_csv(stage / "adjudication_template.csv", ADJ_FIELDS, [])
        (stage / "template_receipt.json").write_text(json.dumps(dict(schema="meta-fulltext-review-template-v1",
            scan_receipt_sha256=lit.sha256(Path(a.scan) / "scan_receipt.json"),
            targets_sha256=lit.sha256(a.targets), status="BLANK_TEMPLATE_NOT_REVIEWED"), indent=2) + "\n",
            encoding="utf-8")
        os.replace(stage, out)
    print(f"BLANK_TEMPLATE_NOT_REVIEWED: {len(targets_list) * 3} fields; {out}")


def review_rows(path, fields, label, expected, targets, candidates, allow_empty=False):
    rows, _ = lit.read_csv(path, fields, allow_empty=allow_empty)
    found, identities = {}, set()
    for i, row in enumerate(rows, 2):
        if any(row.get(field) is None for field in fields):
            lit.fail(f"{label} row {i}: missing CSV cells")
        key = (row["effect_id"], row["field"])
        if key not in expected or key in found:
            lit.fail(f"{label} row {i}: unknown or repeated effect/field")
        identity = row["reviewer"].strip()
        if not identity:
            lit.fail(f"{label} row {i}: reviewer name required")
        identities.add(identity)
        iso_day(row["reviewed_at"], f"{label} row {i}")
        if row["decision"] not in {"accept", "correct", "pending"}:
            lit.fail(f"{label} row {i}: invalid decision")
        if row["decision"] == "pending":
            if row["candidate_id"] or row["value"] or row["verified_location"]:
                lit.fail(f"{label} row {i}: pending must not claim a verified value")
        else:
            candidate = candidates.get(row["candidate_id"])
            target = targets[key[0]]
            if candidate is None or (candidate["record_id"], candidate["source_document"]) != (
                    target["record_id"], target["source_document"]):
                lit.fail(f"{label} row {i}: candidate absent or from a different record/document")
            if not row["verified_location"].strip() or not re.search(r"(?i)(page|table|figure|fig\.)\s*[A-Za-z0-9]", row["verified_location"]):
                lit.fail(f"{label} row {i}: explicit page/table/figure locator required")
            if candidate["page"] and not re.search(r"(?i)\bpage\s*" + re.escape(candidate["page"]) + r"\b",
                                                    row["verified_location"]):
                lit.fail(f"{label} row {i}: verified page disagrees with candidate page")
            if candidate.get("extractor", "").startswith("docling_"):
                import docling_numbers
                docling_numbers.validate(candidate)
                if candidate.get("source_conflict_ids_json", "[]") != "[]":
                    lit.fail(f"{label} row {i}: unresolved original-source conflict; no value confirmation permitted")
            if row["decision"] == "accept":
                if candidate.get("numeric_ambiguity"):
                    lit.fail(f"{label} row {i}: ambiguous numeric punctuation/bound; use correct with explicit value and reason")
                if candidate["unit_suffix"] == "%" or row["value"] and number(row["value"], label) != number(candidate["parsed_number"], label):
                    lit.fail(f"{label} row {i}: accept must use an unambiguous candidate number; use correct with reason")
                row["value"] = candidate["parsed_number"]
            else:
                if not row["reason"].strip() or not row["value"].strip():
                    lit.fail(f"{label} row {i}: correction requires value and reason")
                number(row["value"], label)
                if candidate["parsed_number"] and number(row["value"], label) == number(candidate["parsed_number"], label) and candidate["unit_suffix"] != "%" and not candidate.get("numeric_ambiguity"):
                    lit.fail(f"{label} row {i}: correction has no numeric or unit change")
        found[key] = row
    if len(identities) != 1 and not (allow_empty and not rows):
        lit.fail(f"{label}: one stable self-declared reviewer per file required")
    return found, next(iter(identities)) if identities else None


def previous_review_attempt(out, a):
    if not out.is_dir():
        lit.fail("--resume requires an existing incomplete fulltext review directory")
    path = out / "review_receipt.json"
    old = json.loads(path.read_text(encoding="utf-8"))
    if old.get("schema") != "meta-fulltext-review-v1" or old.get("status") not in {
            "NEEDS_REVIEW", "NEEDS_ADJUDICATION"} or old.get("effects_file") is not None:
        lit.fail("--resume only accepts an incomplete fulltext review without exported effects")
    if old.get("mode") != a.mode or old.get("scan_dir") != str(Path(a.scan).resolve()):
        lit.fail("--resume mode or scan changed; start a new dossier")
    for key, value in (("targets", a.targets), ("reviewer_a", a.reviewer_a), ("reviewer_b", a.reviewer_b)):
        if value:
            item = old["inputs"].get(key)
            if not item or item["path"] != str(Path(value).resolve()):
                lit.fail(f"--resume input path changed: {key}")
            if key == "targets" and lit.sha256(value) != item["sha256"]:
                lit.fail("--resume target effects changed; start a new dossier")
    expected = {"value_review_audit.csv": "audit_sha256", "review_votes.csv": "votes_sha256",
                "conflicts.csv": "conflicts_sha256", "missing_values.csv": "missing_sha256"}
    if {p.name for p in out.iterdir()} != set(expected) | {"review_receipt.json"}:
        lit.fail("--resume prior fulltext review has unexpected or missing files")
    for name, key in expected.items():
        if lit.sha256(out / name) != old.get(key):
            lit.fail(f"--resume prior review audit changed: {name}")
    return old


def resolve(a):
    receipt, docs, candidates = checked_scan(a.scan)
    targets_list, targets = checked_targets(a.targets, docs)
    if a.mode == "formal_dual" and (a.reviewer_a_role != "human_attested" or
                                     a.reviewer_b_role != "human_attested" or
                                     a.adjudication and a.adjudicator_role != "human_attested"):
        lit.fail("formal_dual requires explicit human_attested reviewer roles")
    expected = {(e, f) for e in targets for f in VALUE_FIELDS}
    first, who_a = review_rows(a.reviewer_a, REVIEW_FIELDS, "reviewer A", expected, targets, candidates)
    second, who_b = ({}, None)
    if a.mode == "formal_dual":
        if not a.reviewer_b:
            lit.fail("formal_dual requires two separately supplied human reviewer files")
        second, who_b = review_rows(a.reviewer_b, REVIEW_FIELDS, "reviewer B", expected, targets, candidates)
        if who_a == who_b:
            lit.fail("formal_dual reviewer names must differ")
    elif a.reviewer_b or a.adjudication:
        lit.fail("exploratory_single accepts only one reviewer file")
    third, who_c = ({}, None)
    if a.adjudication:
        third, who_c = review_rows(a.adjudication, ADJ_FIELDS, "adjudicator", expected, targets, candidates, allow_empty=True)
        if who_c in {who_a, who_b}:
            lit.fail("adjudicator must differ from primary reviewers")
    missing, conflicts, audit, chosen = [], [], [], {}
    vote_audit = []
    for source, votes in (("reviewer_a", first), ("reviewer_b", second), ("adjudicator", third)):
        for key, row in sorted(votes.items()):
            candidate = candidates.get(row["candidate_id"])
            vote_audit.append(dict(source=source, **{field: row[field] for field in REVIEW_FIELDS},
                adjudication_reason=row.get("adjudication_reason", ""),
                raw_token=candidate["raw_token"] if candidate else "",
                candidate_context=candidate["context"] if candidate else "",
                source_sha256=candidate["source_sha256"] if candidate else "",
                extraction_method=candidate.get("extractor", "") if candidate else "",
                external_result_id=candidate.get("external_result_id", "") if candidate else "",
                external_result_reference=candidate.get("external_result_reference", "") if candidate else "",
                external_input_sha256=candidate.get("external_input_sha256", "") if candidate else "",
                candidate_confidence_status=candidate.get("confidence_status", "") if candidate else "",
                **{k: candidate.get(k, "") if candidate else "" for k in NUMERIC_AUDIT_FIELDS}))
    used_third = set()
    for key in sorted(expected):
        left, right = first.get(key), second.get(key)
        if left is None:
            missing.append(dict(effect_id=key[0], field=key[1], needed="reviewer_A"))
        if a.mode == "formal_dual" and right is None:
            missing.append(dict(effect_id=key[0], field=key[1], needed="reviewer_B"))
        if left is None or a.mode == "formal_dual" and right is None:
            continue
        differs = bool(right and any(left[x] != right[x] for x in
                                    ("candidate_id", "decision", "value", "verified_location", "reason")))
        choice = left
        if differs:
            third_row = third.get(key)
            conflicts.append(dict(effect_id=key[0], field=key[1], reviewer_a=who_a,
                decision_a=left["decision"], value_a=left["value"], reviewer_b=who_b,
                decision_b=right["decision"], value_b=right["value"],
                status="ADJUDICATED" if third_row else "UNRESOLVED"))
            if third_row is None:
                continue
            if not third_row["adjudication_reason"].strip() or dt.date.fromisoformat(third_row["reviewed_at"]) < max(
                    dt.date.fromisoformat(left["reviewed_at"]), dt.date.fromisoformat(right["reviewed_at"])):
                lit.fail(f"{key}: adjudication needs rationale and date after primary reviews")
            choice = third_row
            used_third.add(key)
        elif key in third:
            lit.fail(f"{key}: unneeded adjudication row")
        audit.append(dict(effect_id=key[0], field=key[1], candidate_id=choice["candidate_id"],
            decision=choice["decision"], value=choice["value"], verified_location=choice["verified_location"],
            reason=choice["reason"], reviewer=choice["reviewer"], reviewed_at=choice["reviewed_at"],
            reviewer_a=who_a, reviewer_b=who_b or "", adjudicator=who_c if differs else "",
            adjudication_reason=choice.get("adjudication_reason", "") if differs else "",
            raw_token=candidates[choice["candidate_id"]]["raw_token"] if choice["candidate_id"] else "",
            candidate_context=candidates[choice["candidate_id"]]["context"] if choice["candidate_id"] else "",
            source_sha256=candidates[choice["candidate_id"]]["source_sha256"] if choice["candidate_id"] else "",
            extraction_method=candidates[choice["candidate_id"]].get("extractor", "") if choice["candidate_id"] else "",
            external_result_id=candidates[choice["candidate_id"]].get("external_result_id", "") if choice["candidate_id"] else "",
            external_result_reference=candidates[choice["candidate_id"]].get("external_result_reference", "") if choice["candidate_id"] else "",
            external_input_sha256=candidates[choice["candidate_id"]].get("external_input_sha256", "") if choice["candidate_id"] else "",
            candidate_confidence_status=candidates[choice["candidate_id"]].get("confidence_status", "") if choice["candidate_id"] else "",
            **{k: candidates[choice["candidate_id"]].get(k, "") if choice["candidate_id"] else ""
               for k in NUMERIC_AUDIT_FIELDS}))
        chosen[key] = choice
    if set(third) != used_third:
        lit.fail("adjudication contains a premature or unused row")
    status = "NEEDS_REVIEW" if missing or any(r["decision"] == "pending" for r in chosen.values()) else (
        "NEEDS_ADJUDICATION" if any(r["status"] == "UNRESOLVED" for r in conflicts) else (
        "EXPLORATORY_SINGLE_REVIEW" if a.mode == "exploratory_single" else "FORMAL_DUAL_REVIEWED"))
    effects = []
    if status in {"EXPLORATORY_SINGLE_REVIEW", "FORMAL_DUAL_REVIEWED"}:
        for effect_id, target in targets.items():
            values = {f: chosen[(effect_id, f)]["value"] for f in VALUE_FIELDS}
            nums = {f: number(v, f) for f, v in values.items()}
            if not nums["ci_lower"] < nums["estimate"] < nums["ci_upper"]:
                lit.fail(f"{effect_id}: CI must strictly contain estimate")
            if target["effect_type"] in {"RR", "OR", "HR"} and nums["ci_lower"] <= 0:
                lit.fail(f"{effect_id}: ratio estimate and CI must be positive")
            picked = [chosen[(effect_id, f)]["candidate_id"] for f in VALUE_FIELDS]
            if len(set(picked)) != len(picked):
                lit.fail(f"{effect_id}: same numeric token assigned to multiple effect fields")
            locations = list(dict.fromkeys(chosen[(effect_id, f)]["verified_location"] for f in VALUE_FIELDS))
            effects.append(dict(**{k: target[k] for k in TARGET_FIELDS if k not in {"effect_id"}},
                **values, source_location="; ".join(locations), extraction_review_mode=a.mode,
                fulltext_scan_sha256=lit.sha256(Path(a.scan) / "scan_receipt.json")))
    out = Path(a.out).resolve()
    if out.exists() and not a.resume:
        lit.fail("output exists; use a fresh review directory")
    prior = previous_review_attempt(out, a) if a.resume else None
    backup = None
    if prior:
        attempt = 1
        while True:
            backup = out.with_name(out.name + f".prior-{attempt:04d}")
            if not backup.exists():
                break
            attempt += 1
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".fulltext-review-", dir=out.parent) as tmp:
        stage = Path(tmp) / "result"
        stage.mkdir()
        audit_fields = ["effect_id", "field", "candidate_id", "decision", "value", "verified_location", "reason",
                        "reviewer", "reviewed_at", "reviewer_a", "reviewer_b", "adjudicator", "adjudication_reason",
                        "raw_token", "candidate_context", "source_sha256", "extraction_method",
                        "external_result_id", "external_result_reference", "external_input_sha256",
                        "candidate_confidence_status", *NUMERIC_AUDIT_FIELDS]
        lit.write_csv(stage / "value_review_audit.csv", audit_fields, audit)
        lit.write_csv(stage / "review_votes.csv", ["source", *REVIEW_FIELDS, "adjudication_reason",
                                                  "raw_token", "candidate_context", "source_sha256",
                                                  "extraction_method", "external_result_id",
                                                  "external_result_reference", "external_input_sha256",
                                                  "candidate_confidence_status", *NUMERIC_AUDIT_FIELDS], vote_audit)
        lit.write_csv(stage / "conflicts.csv", ["effect_id", "field", "reviewer_a", "decision_a", "value_a",
                                              "reviewer_b", "decision_b", "value_b", "status"], conflicts)
        lit.write_csv(stage / "missing_values.csv", ["effect_id", "field", "needed"], missing)
        if effects:
            effect_file = "effects_exploratory.csv" if a.mode == "exploratory_single" else "effects_reviewed.csv"
            lit.write_csv(stage / effect_file,
                          EFFECT_FIELDS, effects)
            by_document = {(d["record_id"], d["source_document"]): d for d in docs}
            lit.write_csv(stage / "source_review_template.csv",
                ["record_id", "study_id", "source_document", "source_location", "status", "source_file",
                 "source_sha256", "reviewer", "reviewed_at", "note"], [
                    dict(record_id=e["record_id"], study_id=e["study_id"], source_document=e["source_document"],
                         source_location=e["source_location"], status="pending",
                         source_file=by_document[(e["record_id"], e["source_document"])]["file_path"],
                         source_sha256=by_document[(e["record_id"], e["source_document"])]["source_sha256"],
                         reviewer="", reviewed_at="", note="Value-review output; original-source signoff pending")
                    for e in effects])
        files = {key: {"path": str(Path(path).resolve()), "sha256": lit.sha256(path)} for key, path in
                 (("targets", a.targets), ("reviewer_a", a.reviewer_a), ("scan_receipt", Path(a.scan) / "scan_receipt.json"))}
        if a.reviewer_b:
            files["reviewer_b"] = {"path": str(Path(a.reviewer_b).resolve()), "sha256": lit.sha256(a.reviewer_b)}
        if a.adjudication:
            files["adjudication"] = {"path": str(Path(a.adjudication).resolve()), "sha256": lit.sha256(a.adjudication)}
        (stage / "review_receipt.json").write_text(json.dumps(dict(schema="meta-fulltext-review-v1", mode=a.mode,
            status=status, scan_dir=str(Path(a.scan).resolve()), inputs=files, effect_count=len(effects),
            reviewer_roles_attested={"A": a.reviewer_a_role, "B": a.reviewer_b_role if a.reviewer_b else None,
                                     "adjudicator": a.adjudicator_role if a.adjudication else None},
            effects_file=effect_file if effects else None,
            effects_sha256=lit.sha256(stage / effect_file) if effects else None,
            source_review_template_sha256=lit.sha256(stage / "source_review_template.csv") if effects else None,
            audit_sha256=lit.sha256(stage / "value_review_audit.csv"),
            votes_sha256=lit.sha256(stage / "review_votes.csv"),
            conflicts_sha256=lit.sha256(stage / "conflicts.csv"),
            missing_sha256=lit.sha256(stage / "missing_values.csv"),
            resumed_from_receipt_sha256=lit.sha256(out / "review_receipt.json") if prior else None,
            resumed_from_path=str(backup) if prior else None,
            reviewer_identity_authenticated=False,
            semantic_source_verified_by_software=False, meaning="Human attestation and local source-byte consistency; candidates are not findings"),
            indent=2) + "\n", encoding="utf-8")
        if prior:
            os.replace(out, backup)
            try:
                os.replace(stage, out)
            except OSError:
                os.replace(backup, out)
                raise
        else:
            os.replace(stage, out)
    print(f"{status}: {len(effects)} effects exported; {out}")
    return 0 if effects else 2


def verify_export(path):
    path = Path(path).resolve()
    rows, fields = lit.read_csv(path, ["record_id", "study_id", "estimate", "ci_lower", "ci_upper"])
    receipt_path = path.parent / "review_receipt.json"
    if "extraction_review_mode" not in fields and not receipt_path.exists():
        return False  # an ordinary externally prepared extraction table
    if "extraction_review_mode" not in fields or not receipt_path.is_file():
        lit.fail("reviewed extraction marker requires review receipt")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("schema") != "meta-fulltext-review-v1" or receipt.get("effects_file") != path.name or (
            receipt.get("status") not in {"EXPLORATORY_SINGLE_REVIEW", "FORMAL_DUAL_REVIEWED"}):
        lit.fail("invalid reviewed extraction receipt/status")
    if receipt["mode"] == "formal_dual" and (receipt.get("reviewer_roles_attested", {}).get("A") != "human_attested" or
            receipt["reviewer_roles_attested"].get("B") != "human_attested" or
            receipt["reviewer_roles_attested"].get("adjudicator") not in {None, "human_attested"}):
        lit.fail("formal reviewed extraction is missing attested human reviewer roles")
    verify_prior_chain(receipt)
    checked_scan(receipt["scan_dir"])
    for item in receipt["inputs"].values():
        source = Path(item["path"])
        if not source.is_file() or lit.sha256(source) != item["sha256"]:
            lit.fail("reviewed extraction input changed")
    for filename, key in ((path.name, "effects_sha256"),
                          ("source_review_template.csv", "source_review_template_sha256"),
                          ("value_review_audit.csv", "audit_sha256"), ("review_votes.csv", "votes_sha256"),
                          ("conflicts.csv", "conflicts_sha256"), ("missing_values.csv", "missing_sha256")):
        item = path.parent / filename
        if not item.is_file() or lit.sha256(item) != receipt[key]:
            lit.fail(f"reviewed extraction output changed: {filename}")
    if len(rows) != receipt["effect_count"] or any(row["extraction_review_mode"] != receipt["mode"] for row in rows):
        lit.fail("reviewed extraction rows disagree with receipt")
    return True


def verify_prior_chain(receipt):
    seen = set()
    for _ in range(100):
        if not receipt.get("resumed_from_receipt_sha256"):
            return
        folder = Path(receipt["resumed_from_path"]).resolve()
        if folder in seen:
            lit.fail("cyclic fulltext review history")
        seen.add(folder)
        prior = folder / "review_receipt.json"
        if not prior.is_file() or lit.sha256(prior) != receipt["resumed_from_receipt_sha256"]:
            lit.fail("prior fulltext review attempt changed or missing")
        receipt = json.loads(prior.read_text(encoding="utf-8"))
        if receipt.get("schema") != "meta-fulltext-review-v1" or receipt.get("status") not in {
                "NEEDS_REVIEW", "NEEDS_ADJUDICATION"}:
            lit.fail("invalid prior fulltext review attempt")
        for name, key in (("value_review_audit.csv", "audit_sha256"), ("review_votes.csv", "votes_sha256"),
                          ("conflicts.csv", "conflicts_sha256"), ("missing_values.csv", "missing_sha256")):
            path = folder / name
            if not path.is_file() or lit.sha256(path) != receipt.get(key):
                lit.fail(f"prior fulltext review audit changed: {name}")
    lit.fail("fulltext review history exceeds 100 revisions")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    s = sub.add_parser("scan")
    for opt in ("records", "documents", "out"):
        s.add_argument("--" + opt, required=True)
    s.add_argument("--pdf-reader", choices=("pdfplumber",), default="pdfplumber")
    s.set_defaults(func=scan)
    t = sub.add_parser("template")
    for opt in ("scan", "targets", "out"):
        t.add_argument("--" + opt, required=True)
    t.set_defaults(func=template)
    v = sub.add_parser("resolve")
    for opt in ("scan", "targets", "reviewer-a", "out"):
        v.add_argument("--" + opt, required=True)
    v.add_argument("--mode", choices=("exploratory_single", "formal_dual"), required=True)
    v.add_argument("--reviewer-b")
    v.add_argument("--adjudication")
    v.add_argument("--resume", action="store_true")
    for role in ("reviewer-a-role", "reviewer-b-role", "adjudicator-role"):
        v.add_argument("--" + role, choices=("unspecified", "human_attested", "agent_assisted", "ai_simulated"),
                       default="unspecified")
    v.set_defaults(func=resolve)
    args = p.parse_args()
    try:
        code = args.func(args)
        sys.exit(code or 0)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, json.JSONDecodeError) as exc:
        p.exit(2, f"Validation: {exc}\n")
