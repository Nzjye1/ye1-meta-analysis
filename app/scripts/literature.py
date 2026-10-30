"""Small, local CSV bibliography/screening/extraction bridge. Python standard library only."""
import argparse
import csv
import datetime as dt
import difflib
import hashlib
import re
import shutil
import sys
from pathlib import Path


def fail(message):
    raise ValueError(message)


def read_csv(path, required, allow_empty=False):
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames or []
        missing = set(required) - set(fields)
        if missing:
            fail(f"{path}: missing columns {', '.join(sorted(missing))}")
        rows = list(reader)
    if not rows and not allow_empty:
        fail(f"{path}: no rows")
    for i, row in enumerate(rows, 2):
        if None in row:
            fail(f"{path}:{i}: extra CSV cells")
    return rows, fields


def write_csv(path, fields, rows):
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def fresh_dir(path):
    path = Path(path)
    if path.exists():
        fail(f"output already exists: {path}")
    path.mkdir(parents=True)
    return path


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def doi(value):
    value = (value or "").strip().lower()
    value = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:\s*)", "", value)
    return value.strip()


def title_key(value):
    return " ".join(re.findall(r"\w+", (value or "").casefold()))


def load_dedup(records, path):
    """Return explicit keep/duplicate/other pre-screen decisions; flags never remove records."""
    rows, _ = read_csv(path, ["record_id", "disposition", "retained_record_id",
                              "reason", "reviewer", "decision_date"])
    by_id = {r["record_id"]: r for r in records}
    if len(by_id) != len(records):
        fail("records.csv has repeated record_id")
    decisions = {}
    for i, row in enumerate(rows, 2):
        rid = row["record_id"]
        if rid not in by_id or rid in decisions:
            fail(f"dedup row {i}: unknown or conflicting record_id")
        if row["disposition"] not in {"keep", "remove_duplicate", "remove_other"}:
            fail(f"dedup row {i}: invalid disposition")
        if not (row["reviewer"] or "").strip():
            fail(f"dedup row {i}: reviewer required")
        try:
            dt.date.fromisoformat(row["decision_date"])
        except (TypeError, ValueError):
            fail(f"dedup row {i}: decision_date must be YYYY-MM-DD")
        if row["disposition"] == "remove_duplicate":
            retained = row["retained_record_id"]
            if retained not in by_id or retained == rid or not (row["reason"] or "").strip():
                fail(f"dedup row {i}: removal needs another retained record and reason")
            left, right = by_id[rid], by_id[retained]
            exact = (left.get("doi") and left["doi"] == right.get("doi")) or (
                left.get("pmid") and left["pmid"] == right.get("pmid"))
            suspected = left.get("year") == right.get("year") and difflib.SequenceMatcher(
                None, title_key(left.get("title")), title_key(right.get("title"))).ratio() >= .90
            if not (exact or suspected):
                fail(f"dedup row {i}: retained record has no recorded identifier/title match")
        elif row["disposition"] == "remove_other":
            if row["retained_record_id"] or not (row["reason"] or "").strip():
                fail(f"dedup row {i}: remove_other needs a reason and no retained record")
        elif row["retained_record_id"]:
            fail(f"dedup row {i}: keep must not name a retained_record_id")
        decisions[rid] = row
    if set(decisions) != set(by_id):
        fail("dedup ledger has unreviewed records")
    for rid, row in decisions.items():
        if row["disposition"] == "remove_duplicate" and decisions[row["retained_record_id"]]["disposition"] != "keep":
            fail(f"dedup: retained record for {rid} is not kept")
    return decisions


def import_records(a):
    required = ["source_record_id", "title", "authors", "year", "doi", "pmid"]
    rows, fields = read_csv(a.input, required)
    if not a.source.strip():
        fail("source label must be nonblank and stable across reimports")
    seen = set()
    records = []
    for i, row in enumerate(rows, 2):
        source_id = (row["source_record_id"] or "").strip()
        if not source_id or source_id in seen:
            fail(f"row {i}: blank or repeated source_record_id")
        seen.add(source_id)
        if not (row["title"] or "").strip() or not (row["year"] or "").strip():
            fail(f"row {i}: title and year required")
        pmid = (row["pmid"] or "").strip()
        if pmid and not re.fullmatch(r"\d+", pmid):
            fail(f"row {i}: PMID must contain digits only")
        d = doi(row["doi"])
        if d and not re.fullmatch(r"10\.\d{4,9}/\S+", d):
            fail(f"row {i}: invalid DOI syntax")
        rid = "REF-" + hashlib.sha256(f"{a.source}\x1f{source_id}".encode()).hexdigest()[:16]
        records.append({"record_id": rid, "source_label": a.source, "source_record_id": source_id,
                        "source_row": i, "title": row["title"], "authors": row["authors"],
                        "year": row["year"], "doi": d, "pmid": pmid,
                        "original_doi": row["doi"], "original_pmid": row["pmid"]})
    records.sort(key=lambda row: row["record_id"])
    candidates = []
    for i, left in enumerate(records):
        for right in records[i + 1:]:
            evidence = []
            if left["doi"] and left["doi"] == right["doi"]:
                evidence.append("exact_doi")
            if left["pmid"] and left["pmid"] == right["pmid"]:
                evidence.append("exact_pmid")
            score = difflib.SequenceMatcher(None, title_key(left["title"]), title_key(right["title"])).ratio()
            if not evidence and left["year"] == right["year"] and score >= 0.90:
                evidence.append("suspected_title")
            if evidence:
                conflict = bool("exact_doi" in evidence and left["pmid"] and right["pmid"]
                                and left["pmid"] != right["pmid"])
                candidates.append({"record_id_1": left["record_id"], "record_id_2": right["record_id"],
                                   "match_evidence": "+".join(evidence), "title_similarity": f"{score:.3f}",
                                   "identifier_conflict": "YES" if conflict else "NO",
                                   "disposition": "REVIEW_REQUIRED"})
    out = fresh_dir(a.out)
    shutil.copyfile(a.input, out / "original_import.csv")
    write_csv(out / "records.csv", list(records[0]), records)
    write_csv(out / "duplicate_candidates.csv",
              ["record_id_1", "record_id_2", "match_evidence", "title_similarity", "identifier_conflict", "disposition"], candidates)
    write_csv(out / "screening_template.csv",
              ["record_id", "stage", "decision", "reason", "reviewer", "decision_date"],
              [{"record_id": r["record_id"], "stage": "title_abstract", "decision": "", "reason": "",
                "reviewer": "", "decision_date": ""} for r in records])
    write_csv(out / "import_manifest.csv", ["key", "value"],
              [{"key": "input_sha256", "value": sha256(a.input)},
               {"key": "original_source_path", "value": str(Path(a.input).resolve())},
               {"key": "source_label", "value": a.source},
               {"key": "record_id_rule", "value": "REF- + first 16 hex sha256(source_label + U+001F + source_record_id)"}])
    print(f"Imported {len(records)} records; {len(candidates)} review candidates; none deleted")


def validate_screening(records, decisions, active_ids=None):
    """Apply an append-only decision history and enforce stage transitions."""
    by_id = {r["record_id"]: r for r in records}
    if len(by_id) != len(records):
        fail("records.csv has repeated record_id")
    active_ids = set(by_id) if active_ids is None else set(active_ids)
    if not active_ids <= set(by_id):
        fail("active record outside bibliography")
    seen = {}
    downstream_invalidated = set()
    for i, row in enumerate(decisions, 2):
        rid, stage, decision = row["record_id"], row["stage"], row["decision"]
        if rid not in by_id:
            fail(f"decision row {i}: unknown record_id {rid}")
        if rid not in active_ids:
            fail(f"decision row {i}: removed duplicate must not be screened")
        if stage not in {"title_abstract", "full_text"} or decision not in {"include", "exclude", "pending"}:
            fail(f"decision row {i}: invalid stage or decision")
        if stage == "full_text" and (rid, "title_abstract") not in seen:
            fail(f"decision row {i}: full_text before title_abstract decision")
        if stage == "full_text" and seen[(rid, "title_abstract")]["decision"] != "include":
            fail(f"decision row {i}: full_text without current title_abstract inclusion")
        if decision == "exclude" and not (row["reason"] or "").strip():
            fail(f"decision row {i}: exclusion needs reason")
        if not (row["reviewer"] or "").strip():
            fail(f"decision row {i}: reviewer required")
        try:
            dt.date.fromisoformat(row["decision_date"])
        except (TypeError, ValueError):
            fail(f"decision row {i}: decision_date must be YYYY-MM-DD")
        prior = seen.get((rid, stage))
        revision_of = (row.get("revision_of") or "").strip()
        revision_reason = (row.get("revision_reason") or "").strip()
        if prior is None:
            if revision_of or revision_reason:
                fail(f"decision row {i}: first decision cannot claim a revision")
        else:
            reaffirming_after_upstream_change = stage == "full_text" and rid in downstream_invalidated
            if revision_of != prior["decision"] or not revision_reason or (
                    decision == prior["decision"] and not reaffirming_after_upstream_change):
                fail(f"decision row {i}: repeated record/stage without documented revision")
            if row["decision_date"] < prior["decision_date"]:
                fail(f"decision row {i}: revision predates prior decision")
            if stage == "title_abstract" and (rid, "full_text") in seen:
                downstream_invalidated.add(rid)
        seen[(rid, stage)] = row
        if stage == "full_text":
            downstream_invalidated.discard(rid)
    for rid in active_ids:
        ta = seen.get((rid, "title_abstract"))
        if ta is None:
            fail(f"missing title_abstract decision for {rid}")
        ft = seen.get((rid, "full_text"))
        if ta["decision"] == "include" and ft is None:
            fail(f"missing full_text decision for {rid}")
        if ta["decision"] != "include" and ft is not None:
            fail(f"full_text decision without title_abstract inclusion for {rid}")
        if ft is not None and ft["decision_date"] < ta["decision_date"]:
            fail(f"full_text decision predates final title_abstract decision for {rid}")
        if rid in downstream_invalidated:
            fail(f"downstream full_text decision invalidated by later title_abstract revision for {rid}")
    eligible = {rid for rid in active_ids if (rid, "full_text") in seen
                and seen[(rid, "full_text")]["decision"] == "include"}
    return seen, eligible


def screen(a):
    records, _ = read_csv(a.records, ["record_id", "title", "doi", "pmid"])
    decisions, fields = read_csv(a.decisions, ["record_id", "stage", "decision", "reason", "reviewer", "decision_date"])
    from dual_screen import verify_if_marked
    verify_if_marked(a.records, a.dedup, a.decisions)
    if "screening_review_mode" in fields:
        if a.review_mode:
            fail("dual-screen decision mode is bound to its receipt; do not override it")
        modes = {row["screening_review_mode"] for row in decisions}
        if len(modes) != 1 or next(iter(modes)) not in {"exploratory_pair", "formal_dual"}:
            fail("invalid bound dual-screen mode")
        review_mode = next(iter(modes))
    else:
        review_mode = a.review_mode or "exploratory_single"
    by_id = {r["record_id"]: r for r in records}
    dedup = load_dedup(records, a.dedup) if a.dedup else None
    active_ids = {rid for rid in by_id if dedup is None or dedup[rid]["disposition"] == "keep"}
    _, eligible_ids = validate_screening(records, decisions, active_ids)
    eligible = [by_id[rid] for rid in by_id if rid in eligible_ids]
    out = fresh_dir(a.out)
    write_csv(out / "screening_ledger.csv", fields + ["title", "doi", "pmid"],
              [{**r, **{k: by_id[r["record_id"]][k] for k in ("title", "doi", "pmid")}}
               for r in decisions])
    write_csv(out / "eligible_records.csv", list(records[0]), eligible)
    write_csv(out / "screening_manifest.csv", ["key", "value"],
              [{"key": "records_sha256", "value": sha256(a.records)},
               {"key": "decisions_sha256", "value": sha256(a.decisions)},
               {"key": "dedup_sha256", "value": sha256(a.dedup) if a.dedup else "NONE"},
               {"key": "review_mode", "value": review_mode},
               {"key": "reviewer_identity_authenticated", "value": "false"},
               {"key": "note", "value": "Decision counts are not a validated PRISMA flow"}])
    print(f"Recorded {len(decisions)} decisions; {len(eligible)} full-text included records")


def link(a):
    records, _ = read_csv(a.records, ["record_id", "source_label", "source_record_id"])
    ledger, _ = read_csv(a.ledger, ["record_id", "stage", "decision", "reason", "reviewer", "decision_date"])
    effects, fields = read_csv(a.effects, ["record_id", "study_id", "cohort_id", "source_document", "source_location"])
    if "extraction_review_mode" in fields or (Path(a.effects).resolve().parent / "review_receipt.json").exists():
        from fulltext_extract import verify_export
        verify_export(a.effects)
    by_id = {r["record_id"]: r for r in records}
    if len(by_id) != len(records):
        fail("records.csv has repeated record_id")
    dedup = load_dedup(records, a.dedup) if a.dedup else None
    active_ids = {rid for rid in by_id if dedup is None or dedup[rid]["disposition"] == "keep"}
    _, eligible = validate_screening(records, ledger, active_ids)
    warnings = []
    blocked = False
    for i, row in enumerate(effects, 2):
        rid = row["record_id"]
        if rid not in by_id or rid not in eligible:
            fail(f"effects row {i}: record_id {rid} is unknown or not full-text included")
        if not re.search(r"(?i)(page|p\.|table|figure|fig\.)\s*[A-Za-z0-9]", row["source_location"] or ""):
            fail(f"effects row {i}: page/table/figure source locator required")
        if not (row["source_document"] or "").strip():
            fail(f"effects row {i}: source_document required")
    for key in ("cohort_id", "study_id"):
        groups = {}
        for row in effects:
            groups.setdefault(row[key], []).append(row)
        for value, group in groups.items():
            if len(group) > 1:
                reports = sorted({r["record_id"] for r in group})
                warnings.append({"issue": "same_cohort_multiple_effects" if key == "cohort_id" else "same_study_multiple_effects",
                                 "value": value, "record_ids": "|".join(reports),
                                 "action": "BLOCK_POOLING_REVIEW_DEPENDENCE"})
                blocked = True
    out = fresh_dir(a.out)
    write_csv(out / "link_warnings.csv", ["issue", "value", "record_ids", "action"], warnings)
    write_csv(out / "link_manifest.csv", ["key", "value"],
              [{"key": "records_sha256", "value": sha256(a.records)},
               {"key": "ledger_sha256", "value": sha256(a.ledger)},
               {"key": "dedup_sha256", "value": sha256(a.dedup) if a.dedup else "NONE"},
               {"key": "effects_sha256", "value": sha256(a.effects)},
               {"key": "status", "value": "BLOCKED" if blocked else "READY"}])
    if blocked:
        fail("multiple effects from the same cohort or study require adjudication; see link_warnings.csv")
    write_csv(out / "linked_effects.csv", fields, effects)
    print(f"Linked {len(effects)} effects to screened bibliography; ready for R input")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    imp = sub.add_parser("import")
    for opt in ("input", "source", "out"):
        imp.add_argument(f"--{opt}", required=True)
    imp.set_defaults(func=import_records)
    scr = sub.add_parser("screen")
    for opt in ("records", "decisions", "out"):
        scr.add_argument(f"--{opt}", required=True)
    scr.add_argument("--dedup", help="Explicit keep/remove_duplicate adjudication CSV")
    scr.add_argument("--review-mode", choices=("exploratory_single", "agent_assisted"),
                     help="Manual one-file route only; dual-screen mode comes from its receipt")
    scr.set_defaults(func=screen)
    lnk = sub.add_parser("link")
    for opt in ("records", "ledger", "effects", "out"):
        lnk.add_argument(f"--{opt}", required=True)
    lnk.add_argument("--dedup", help="Same explicit dedup CSV used for screening")
    lnk.set_defaults(func=link)
    args = parser.parse_args()
    try:
        args.func(args)
    except (ValueError, OSError) as error:
        print(f"Validation: {error}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
