"""Project-private search-query lint and BibDedupe candidate overlay for checked source chains.

Neither translation nor duplicate matching executes a database search or deletes a record.
"""
import argparse
from contextlib import redirect_stdout, redirect_stderr
import csv
from datetime import date
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile

import literature as lit
import source_chain

LIBRARY = Path(__file__).resolve().parents[1] / "frontend-python-library"
sys.path.insert(0, str(LIBRARY))

PAIR_FIELDS = ("pair_id", "record_id_1", "record_id_2", "source_label_1", "source_label_2",
               "existing_match_evidence", "bib_dedupe_label", "status")
DECISION_FIELDS = ("pair_id", "decision", "retained_record_id", "reason", "reviewer",
                   "decision_date", "revision_of", "revision_reason")
CURRENT_FIELDS = PAIR_FIELDS + DECISION_FIELDS[1:6]
PLATFORMS = {"pubmed": "pubmed", "wos": "wos", "ebscohost": "ebscohost"}


def sha(path):
    return lit.sha256(path)


def package_versions():
    from importlib import metadata
    return {name: metadata.version(name) for name in ("search-query", "bib-dedupe")}


def save(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def staging(out):
    out = Path(out).resolve()
    if out.exists():
        lit.fail("output exists; use a new local version directory")
    out.parent.mkdir(parents=True, exist_ok=True)
    return out


def query_check(a):
    from search_query.parser import parse
    source = Path(a.candidate).resolve()
    candidate = json.loads(source.read_text(encoding="utf-8"))
    query = candidate.get("query")
    if not isinstance(query, str) or not query.strip() or len(query) > 3000:
        lit.fail("query candidate needs 1-3000 public-term characters")
    if a.platform not in PLATFORMS:
        lit.fail("unsupported search-query platform")
    declared = str(candidate.get("database", "")).lower().replace(" ", "")
    if declared and declared not in {a.platform, "webofscience" if a.platform == "wos" else a.platform}:
        lit.fail("candidate database and syntax platform disagree")
    out = staging(a.out)
    diagnostics = io.StringIO()
    translations = {}
    status = "PENDING_HUMAN_REVIEW"
    try:
        with redirect_stdout(diagnostics), redirect_stderr(diagnostics):
            parsed = parse(query, platform=a.platform)
            normalized = parsed.to_string()
            for target in a.translate or []:
                if target == a.platform:
                    continue
                translations[target] = parsed.translate(target_syntax=target).to_string()
    except Exception as exc:
        status = "QUERY_SYNTAX_REVIEW_REQUIRED"
        normalized = ""
        diagnostics.write(f"{type(exc).__name__}: {exc}\n")
    with tempfile.TemporaryDirectory(prefix=".query-check-", dir=out.parent) as temp:
        stage = Path(temp) / "result"
        stage.mkdir()
        result = {"schema": "meta-front-query-v1", "status": status, "database_query_executed": False,
                  "candidate": str(source), "candidate_sha256": sha(source), "platform": a.platform,
                  "query": query, "normalized_query": normalized, "draft_translations": translations,
                  "translation_review_status": "PENDING_HUMAN_REVIEW", "package_versions": package_versions()}
        save(stage / "query_review.json", result)
        (stage / "parser_diagnostics.txt").write_text(diagnostics.getvalue(), encoding="utf-8")
        save(stage / "receipt.json", {"schema": "meta-front-query-receipt-v1", "status": status,
                                    "source_path": str(source), "source_sha256": sha(source),
                                    "outputs": {p.name: sha(p) for p in stage.iterdir() if p.is_file()}})
        os.replace(stage, out)
    print(status, out)
    return status == "PENDING_HUMAN_REVIEW"


def pair_id(a, b):
    return hashlib.sha256((min(a, b) + "\0" + max(a, b)).encode("utf-8")).hexdigest()[:20]


def checked_review(path):
    root = Path(path).resolve()
    receipt = json.loads((root / "receipt.json").read_text(encoding="utf-8"))
    if receipt.get("schema") != "meta-front-dedupe-v1":
        lit.fail("invalid prior candidate review")
    for name, digest in receipt["outputs"].items():
        if not (root / name).is_file() or sha(root / name) != digest:
            lit.fail("prior candidate review output changed: " + name)
    chain = Path(receipt["source_chain"])
    if not (chain / "chain_receipt.json").is_file() or sha(chain / "chain_receipt.json") != receipt["source_chain_sha256"]:
        lit.fail("prior source chain changed")
    source_chain.checked_prior(chain)
    return root, receipt


def bib_pairs(records):
    import pandas as pd
    from bib_dedupe.bib_dedupe import prep, block, match
    frame = pd.DataFrame([{
        "ID": row["record_id"], "ENTRYTYPE": "article", "author": row.get("authors") or "",
        "title": row["title"], "year": row["year"], "doi": row.get("doi") or "",
        "search_set": row["source_label"], "journal": row.get("journal") or "",
        "abstract": row.get("abstract") or "",
    } for row in records])
    log = io.StringIO()
    with redirect_stdout(log), redirect_stderr(log):
        matched = match(block(prep(frame, cpu=1), cpu=1), cpu=1)
    labels = {}
    for _, row in matched.iterrows():
        left, right = str(row["ID_1"]), str(row["ID_2"])
        labels[pair_id(left, right)] = (left, right, str(row["duplicate_label"]))
    return labels, log.getvalue()


def candidate_pairs(chain):
    root, catalog, batches, history = source_chain.checked_prior(chain)
    records = source_chain.csv_rows(root / "records.csv", ("record_id", "source_label", "title", "year"))
    if len(records) > 2000:
        lit.fail("front-end candidate overlay supports at most 2000 records")
    by_id = {r["record_id"]: r for r in records}
    native = source_chain.csv_rows(root / "duplicate_candidates.csv",
        ("record_id_1", "record_id_2", "match_evidence"), empty=True)
    bib, log = bib_pairs(records)
    pairs = {}
    for row in native:
        key = pair_id(row["record_id_1"], row["record_id_2"])
        pairs[key] = (min(row["record_id_1"], row["record_id_2"]),
                      max(row["record_id_1"], row["record_id_2"]), row["match_evidence"])
    for key, (left, right, label) in bib.items():
        if left not in by_id or right not in by_id or left == right:
            lit.fail("BibDedupe returned an unknown or self-linked source ID")
        if key not in pairs:
            pairs[key] = (min(left, right), max(left, right), "")
    result = []
    for key, (left, right, evidence) in sorted(pairs.items()):
        result.append(dict(pair_id=key, record_id_1=left, record_id_2=right,
            source_label_1=by_id[left]["source_label"], source_label_2=by_id[right]["source_label"],
            existing_match_evidence=evidence, bib_dedupe_label=bib[key][2] if key in bib else "",
            status="REVIEW_REQUIRED"))
    return root, records, result, log


def decisions(history, prior, pairs):
    if history[:len(prior)] != prior:
        lit.fail("candidate decision history must preserve prior rows exactly")
    by_pair = {p["pair_id"]: p for p in pairs}
    state = {}
    for i, row in enumerate(history, 2):
        if None in row or any(row.get(field) is None for field in DECISION_FIELDS):
            lit.fail(f"pair decision row {i}: truncated or extra CSV cells")
        key = row["pair_id"]
        if key not in by_pair or row["decision"] not in {"same_report", "different_report", "uncertain"}:
            lit.fail(f"pair decision row {i}: unknown pair or decision")
        if not all((row.get(k) or "").strip() for k in ("reason", "reviewer", "decision_date")):
            lit.fail(f"pair decision row {i}: reason, reviewer and date required")
        try:
            date.fromisoformat(row["decision_date"])
        except (ValueError, TypeError):
            lit.fail(f"pair decision row {i}: invalid date")
        members = {by_pair[key]["record_id_1"], by_pair[key]["record_id_2"]}
        if row["decision"] == "same_report":
            if row["retained_record_id"] not in members:
                lit.fail(f"pair decision row {i}: retained record must be a pair member")
        elif row["retained_record_id"]:
            lit.fail(f"pair decision row {i}: retained record only for same_report")
        if key in state:
            before = state[key]
            if row["revision_of"] != before["decision"] or not row["revision_reason"].strip() or \
                    row["decision"] == before["decision"] or row["decision_date"] < before["decision_date"]:
                lit.fail(f"pair decision row {i}: explicit ordered reversal required")
        elif row["revision_of"] or row["revision_reason"]:
            lit.fail(f"pair decision row {i}: first decision cannot claim a revision")
        state[key] = row
    return state


def dedupe(a):
    root, records, pairs, engine_log = candidate_pairs(a.chain)
    out = staging(a.out)
    prior_history = []
    prior_receipt = ""
    if a.prior_review:
        old, prior = checked_review(a.prior_review)
        if Path(prior["source_chain"]) != root or prior["candidate_sha256"] != hashlib.sha256(
                json.dumps(pairs, sort_keys=True).encode("utf-8")).hexdigest():
            lit.fail("prior candidate review belongs to a different source snapshot")
        prior_history = source_chain.csv_rows(old / "pair_decision_history.csv", DECISION_FIELDS, empty=True)
        prior_receipt = sha(old / "receipt.json")
    history = source_chain.csv_rows(a.decisions, DECISION_FIELDS, empty=True) if a.decisions else prior_history
    state = decisions(history, prior_history, pairs)
    current = [dict(pair, decision=state[pair["pair_id"]]["decision"] if pair["pair_id"] in state else "pending",
                    retained_record_id=state[pair["pair_id"]]["retained_record_id"] if pair["pair_id"] in state else "",
                    reason=state[pair["pair_id"]]["reason"] if pair["pair_id"] in state else "",
                    reviewer=state[pair["pair_id"]]["reviewer"] if pair["pair_id"] in state else "",
                    decision_date=state[pair["pair_id"]]["decision_date"] if pair["pair_id"] in state else "")
               for pair in pairs]
    unresolved = sum(r["decision"] in {"pending", "uncertain"} for r in current)
    status = "NEEDS_PAIR_REVIEW" if unresolved else "PAIR_REVIEW_COMPLETE_RECORD_DISPOSITIONS_REQUIRED"
    with tempfile.TemporaryDirectory(prefix=".front-dedupe-", dir=out.parent) as temp:
        stage = Path(temp) / "result"
        stage.mkdir()
        lit.write_csv(stage / "candidate_pairs.csv", PAIR_FIELDS, pairs)
        lit.write_csv(stage / "pair_decision_history.csv", DECISION_FIELDS, history)
        lit.write_csv(stage / "pair_review_current.csv", CURRENT_FIELDS, current)
        lit.write_csv(stage / "pair_decisions_template.csv", DECISION_FIELDS,
            [dict(pair_id=r["pair_id"], decision="", retained_record_id="", reason="", reviewer="",
                  decision_date="", revision_of="", revision_reason="") for r in current
             if r["decision"] in {"pending", "uncertain"}])
        lit.write_csv(stage / "source_chain_disposition_template.csv", source_chain.HISTORY_FIELDS,
            [dict(record_id=r["record_id"], disposition="", retained_record_id="", reason="",
                  reviewer="", decision_date="", revision_of="", revision_reason="") for r in records])
        (stage / "bib_dedupe_log.txt").write_text(engine_log, encoding="utf-8")
        receipt = dict(schema="meta-front-dedupe-v1", status=status, final=False,
            source_chain=str(root), source_chain_sha256=sha(root / "chain_receipt.json"),
            candidate_sha256=hashlib.sha256(json.dumps(pairs, sort_keys=True).encode("utf-8")).hexdigest(),
            prior_review=str(Path(a.prior_review).resolve()) if a.prior_review else "",
            prior_review_receipt_sha256=prior_receipt,
            decisions_path=str(Path(a.decisions).resolve()) if a.decisions else "",
            decisions_sha256=sha(a.decisions) if a.decisions else "",
            package_versions=package_versions(), record_count=len(records), pair_count=len(pairs),
            unresolved_pair_count=unresolved, records_deleted=0,
            note="Pair labels are review candidates. Existing source-update requires separate explicit per-record dispositions.",
            outputs={p.name: sha(p) for p in stage.iterdir() if p.is_file()})
        save(stage / "receipt.json", receipt)
        os.replace(stage, out)
    print(status, len(pairs), "candidates", unresolved, "unresolved", out)


def verify(out):
    root = Path(out).resolve()
    receipt = json.loads((root / "receipt.json").read_text(encoding="utf-8"))
    schema = receipt.get("schema")
    if schema == "meta-front-dedupe-v1":
        checked_review(root)
        if receipt["prior_review"]:
            prior, _ = checked_review(receipt["prior_review"])
            if sha(prior / "receipt.json") != receipt["prior_review_receipt_sha256"]:
                lit.fail("prior pair review changed")
        if receipt["decisions_path"] and sha(receipt["decisions_path"]) != receipt["decisions_sha256"]:
            lit.fail("candidate decision input changed")
        if package_versions() != receipt["package_versions"]:
            lit.fail("candidate engine version changed")
    elif schema == "meta-front-query-receipt-v1":
        if sha(receipt["source_path"]) != receipt["source_sha256"]:
            lit.fail("query candidate changed")
        for name, digest in receipt["outputs"].items():
            if sha(root / name) != digest:
                lit.fail("query check output changed: " + name)
    else:
        lit.fail("unknown front-end receipt")
    print("FRONTEND_RECEIPT_VERIFIED", root)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    q = sub.add_parser("query-check")
    q.add_argument("--candidate", required=True)
    q.add_argument("--platform", required=True, choices=PLATFORMS)
    q.add_argument("--translate", action="append", choices=PLATFORMS)
    q.add_argument("--out", required=True)
    d = sub.add_parser("dedupe")
    d.add_argument("--chain", required=True)
    d.add_argument("--decisions")
    d.add_argument("--prior-review")
    d.add_argument("--out", required=True)
    v = sub.add_parser("verify")
    v.add_argument("--out", required=True)
    args = parser.parse_args()
    try:
        if args.command == "query-check":
            ok = query_check(args)
            sys.exit(0 if ok else 2)
        if args.command == "dedupe":
            dedupe(args)
        else:
            verify(args.out)
    except (OSError, ValueError, KeyError, TypeError, ImportError, csv.Error) as exc:
        parser.exit(2, "Validation: " + str(exc) + "\n")
