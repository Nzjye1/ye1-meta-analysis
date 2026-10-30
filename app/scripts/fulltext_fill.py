"""Make one unresolved-report list and match local PDF candidates for an existing access ledger.

The PDF scan never decides eligibility, rights, version equivalence or full-text scope.
"""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

import fulltext_extract as ft
import literature as lit
import local_retrieval as access
import source_chain

LIST_FIELDS = ("record_id", "title", "doi", "pmid", "access_status", "reason",
               "file_obtained", "next_action")
MATCH_FIELDS = ("file_path", "file_sha256", "bytes", "status", "record_id",
                "identity_basis_candidate", "details")
DOI = re.compile(r"(?i)\b10\.\d{4,9}/[^\s<>\[\]{}]+")


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def new_output(path):
    out = Path(path).resolve()
    if out.exists():
        lit.fail("output exists; use a new version directory")
    out.parent.mkdir(parents=True, exist_ok=True)
    return out


def checked_list(root):
    root = Path(root).resolve()
    receipt = json.loads((root / "fill_receipt.json").read_text(encoding="utf-8"))
    if receipt.get("schema") != "meta-fulltext-fill-list-v1":
        lit.fail("invalid full-text resolution list receipt")
    for name, digest in receipt["output_sha256"].items():
        if not (root / name).is_file() or lit.sha256(root / name) != digest:
            lit.fail("full-text resolution list changed: " + name)
    chain = Path(receipt["chain_root"])
    prior = Path(receipt["prior_access_root"])
    source_chain.checked_prior(chain)
    access.checked_prior(prior)
    if lit.sha256(chain / "chain_receipt.json") != receipt["chain_receipt_sha256"] or \
            lit.sha256(prior / "retrieval_receipt.json") != receipt["prior_receipt_sha256"]:
        lit.fail("source or access ledger changed since missing-list creation")
    return receipt, source_chain.csv_rows(root / "fulltext_resolution_list.csv", LIST_FIELDS, True)


def prepare(a):
    chain = Path(a.chain).resolve()
    prior = Path(a.prior).resolve()
    source_chain.checked_prior(chain)
    access.checked_prior(prior)
    prior_receipt = json.loads((prior / "retrieval_receipt.json").read_text(encoding="utf-8"))
    if Path(prior_receipt["input_paths"]["chain_receipt"]).resolve() != chain / "chain_receipt.json":
        lit.fail("access ledger belongs to a different source chain")
    records = source_chain.csv_rows(chain / "records.csv", ("record_id", "title", "doi", "pmid"))
    by_id = {row["record_id"]: row for row in records}
    current = source_chain.csv_rows(prior / "attempt_current.csv", ("record_id", "status", "reason"), True)
    missing = source_chain.csv_rows(prior / "missing_attempts.csv", ("record_id",), True)
    state = {row["record_id"]: row for row in current}
    sought = set(state) | {row["record_id"] for row in missing}
    if len(sought) != prior_receipt["sought_reports"] or not sought <= set(by_id):
        lit.fail("access report count/record IDs disagree with source chain")
    lines = []
    for rid in sorted(sought):
        row = state.get(rid, {})
        status = row.get("status", "no_attempt")
        if status in {"retrieved_primary", "retrieved_alternative"}:
            continue
        file_obtained = status == "alternative_candidate"
        lines.append({"record_id": rid, "title": by_id[rid]["title"],
                      "doi": by_id[rid]["doi"], "pmid": by_id[rid]["pmid"],
                      "access_status": status, "reason": row.get("reason", "no attempt recorded"),
                      "file_obtained": "yes" if file_obtained else "no",
                      "next_action": "review obtained alternative identity/version" if file_obtained
                      else "supply lawful PDF or record why unavailable"})
    out = new_output(a.out)
    with tempfile.TemporaryDirectory(prefix=".fulltext-list-", dir=out.parent) as temp:
        stage = Path(temp) / "result"
        stage.mkdir()
        lit.write_csv(stage / "fulltext_resolution_list.csv", LIST_FIELDS, lines)
        save(stage / "fill_receipt.json", {
            "schema": "meta-fulltext-fill-list-v1", "status": "REVIEW_AND_SUPPLY_PDFS",
            "chain_root": str(chain), "chain_receipt_sha256": lit.sha256(chain / "chain_receipt.json"),
            "prior_access_root": str(prior), "prior_receipt_sha256": lit.sha256(prior / "retrieval_receipt.json"),
            "unresolved_reports": len(lines), "files_not_obtained": sum(x["file_obtained"] == "no" for x in lines),
            "output_sha256": {"fulltext_resolution_list.csv": lit.sha256(stage / "fulltext_resolution_list.csv")},
            "scope": "local consistency and customer-supplied PDF candidate workflow; no inclusion decision"})
        os.replace(stage, out)
    print("REVIEW_AND_SUPPLY_PDFS", len(lines), "unresolved reports", out)


def pdf_text(path):
    if not 0 < path.stat().st_size <= 25_000_000:
        raise ValueError("PDF exceeds the 25 MB file bound")
    raw = path.read_bytes()
    if not raw.startswith(b"%PDF-") or b"%%EOF" not in raw[-1024:]:
        raise ValueError("not a bounded PDF file (header/EOF/size)")
    pages = ft.pages(path, "pdf")
    if not pages or not any(text.strip() for _, text in pages[:2]):
        raise ValueError("PDF has no selectable first-page text; OCR/manual review needed")
    return "\n".join(text for _, text in pages[:2]), len(raw)


def match_pdf(path, records, target_ids):
    try:
        content, size = pdf_text(path)
    except (ValueError, OSError) as exc:
        return dict(file_path=str(path), file_sha256=lit.sha256(path), bytes=path.stat().st_size,
                    status="INVALID_OR_UNREADABLE_PDF", record_id="", identity_basis_candidate="", details=str(exc))
    low = content.casefold()
    if any(marker in low for marker in ("access denied", "403 forbidden", "404 not found")):
        return dict(file_path=str(path), file_sha256=lit.sha256(path), bytes=size,
                    status="ACCESS_ERROR_PAGE_REJECTED", record_id="", identity_basis_candidate="",
                    details="PDF wrapper contains an access-error message; no full text inferred")
    found_doi = {lit.doi(hit.rstrip(".,;:)")) for hit in DOI.findall(content)}
    found_pmid = set(re.findall(r"(?i)\bPMID\s*[:#]?\s*(\d{5,10})\b", content))
    hits = []
    for record in records:
        doi = lit.doi(record["doi"])
        pmid = record["pmid"].strip()
        doi_match = bool(doi and doi in found_doi)
        pmid_match = bool(pmid and pmid in found_pmid)
        title = lit.title_key(record["title"])
        title_match = bool(title and title in lit.title_key(low))
        if doi_match or pmid_match or title_match:
            conflict = bool((found_doi and doi and not doi_match) or
                            (found_pmid and pmid and not pmid_match))
            basis = "doi_in_text" if doi_match else "pmid_in_text" if pmid_match else "title_in_text"
            hits.append((record["record_id"], basis, conflict))
    if not hits:
        status, rid, basis = "NO_INDEXED_REPORT_MATCH", "", ""
    elif len(hits) > 1 or any(x[2] for x in hits):
        status, rid, basis = "IDENTITY_CONFLICT_REVIEW_REQUIRED", "", ""
    else:
        rid, basis, _ = hits[0]
        status = ("OTHER_INDEXED_REPORT_NOT_MISSING" if rid not in target_ids else
                  "POSSIBLE_ABSTRACT_ONLY_REVIEW_REQUIRED" if "abstract" in low and len(low) < 1000
                  and not any(part in low for part in ("methods", "results", "discussion"))
                  else "POSSIBLE_MATCH_REVIEW_REQUIRED")
    return dict(file_path=str(path), file_sha256=lit.sha256(path), bytes=size,
                status=status, record_id=rid, identity_basis_candidate=basis,
                details=f"first_two_pages_only; DOI={','.join(sorted(found_doi))}; PMID={','.join(sorted(found_pmid))}; "
                        f"matched={','.join(x[0] for x in hits)}; full_text_scope_and_rights_unverified")


def scan(a):
    receipt, unresolved = checked_list(a.list)
    folder = Path(a.pdf_dir).resolve()
    if not folder.is_dir():
        lit.fail("PDF drop directory does not exist")
    files = sorted((x for x in folder.iterdir() if x.is_file()), key=lambda x: x.name.casefold())
    if len(files) > 100:
        lit.fail("PDF drop directory exceeds 100-file bound")
    targets = [r for r in unresolved if r["file_obtained"] == "no"]
    chain = Path(receipt["chain_root"])
    all_records = source_chain.csv_rows(chain / "records.csv", ("record_id", "title", "doi", "pmid"))
    target_ids = {r["record_id"] for r in targets}
    matches = [match_pdf(f, all_records, target_ids) if f.suffix.lower() == ".pdf" else
               dict(file_path=str(f), file_sha256=lit.sha256(f), bytes=f.stat().st_size,
                    status="NOT_PDF", record_id="", identity_basis_candidate="",
                    details="only .pdf files with PDF header, EOF and selectable text are considered")
               for f in files]
    by_hash = {}
    for row in matches:
        by_hash.setdefault(row["file_sha256"], []).append(row)
    for group in by_hash.values():
        if len(group) > 1:
            for row in group:
                if row["status"] == "POSSIBLE_MATCH_REVIEW_REQUIRED":
                    row["status"] = "DUPLICATE_FILE_REVIEW_REQUIRED"
    by_record = {}
    for row in matches:
        if row["record_id"] and row["status"] in {
                "POSSIBLE_MATCH_REVIEW_REQUIRED", "DUPLICATE_FILE_REVIEW_REQUIRED"}:
            by_record.setdefault(row["record_id"], []).append(row)
    for group in by_record.values():
        if len(group) > 1:
            for row in group:
                if row["status"] == "POSSIBLE_MATCH_REVIEW_REQUIRED":
                    row["status"] = "MULTIPLE_FILES_REVIEW_REQUIRED"
    prior = Path(receipt["prior_access_root"])
    history = access.checked_prior(prior)
    latest = {r["record_id"]: r for r in history}
    suggestions = []
    for row in matches:
        if row["status"] != "POSSIBLE_MATCH_REVIEW_REQUIRED":
            continue
        rid = row["record_id"]
        old = latest.get(rid)
        suggestions.append({k: v for k, v in {
            "record_id": rid,
            "attempt_id": "FILL-" + hashlib.sha256((rid + row["file_sha256"]).encode()).hexdigest()[:20],
            "status": "", "source_document": Path(row["file_path"]).name,
            "file_path": row["file_path"], "format": "pdf", "rights_basis": "",
            "document_doi": next((r["doi"] for r in targets if r["record_id"] == rid), ""),
            "document_pmid": next((r["pmid"] for r in targets if r["record_id"] == rid), ""),
            "version_relation": "", "identity_basis": row["identity_basis_candidate"],
            "identity_evidence": "", "reason": "", "reviewer": "", "decision_date": "",
            "revision_of": old["attempt_id"] if old else "",
            "revision_reason": "", "review_mode": "", "identity_conclusion": "",
            "version_conclusion": "", "version_evidence": ""}.items() if k in access.ALL_FIELDS})
    out = new_output(a.out)
    with tempfile.TemporaryDirectory(prefix=".fulltext-scan-", dir=out.parent) as temp:
        stage = Path(temp) / "result"
        stage.mkdir()
        lit.write_csv(stage / "pdf_matches.csv", MATCH_FIELDS, matches)
        lit.write_csv(stage / "attempts_review_template.csv", access.ALL_FIELDS, history + suggestions)
        save(stage / "scan_receipt.json", {
            "schema": "meta-fulltext-fill-scan-v1", "status": "CANDIDATES_REQUIRE_REVIEW",
            "list_root": str(Path(a.list).resolve()), "list_receipt_sha256": lit.sha256(Path(a.list) / "fill_receipt.json"),
            "pdf_drop_dir": str(folder), "pdf_sha256": {r["file_path"]: r["file_sha256"] for r in matches},
            "candidate_count": len(suggestions),
            "output_sha256": {f.name: lit.sha256(f) for f in stage.iterdir() if f.is_file()},
            "scope": "candidate identification only; blanks require review; no PDF is included, read or assessed"})
        os.replace(stage, out)
    print("CANDIDATES_REQUIRE_REVIEW", len(suggestions), "unambiguous candidate files", out)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    one = sub.add_parser("list")
    for name in ("chain", "prior", "out"):
        one.add_argument("--" + name, required=True)
    two = sub.add_parser("scan")
    for name in ("list", "pdf-dir", "out"):
        two.add_argument("--" + name, required=True)
    args = parser.parse_args()
    try:
        {"list": prepare, "scan": scan}[args.command](args)
    except (OSError, ValueError, KeyError, TypeError, csv.Error) as exc:
        parser.exit(2, f"Validation: {exc}\n")
