"""Confirmed diagnostic review inputs -> mada facts -> evidence-bound IMRaD/Word draft."""
import argparse
import csv
import datetime as dt
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from types import SimpleNamespace

import diagnostic_meta
import diagnostic_word
import literature as lit

CORE = ("protocol", "records", "dedup", "decisions", "report_map", "input", "source_review", "quadas")
DOMAINS = ("patient_selection", "index_test", "reference_standard", "flow_timing")


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def nonblank(value):
    return isinstance(value, str) and bool(value.strip())


def date(value):
    try:
        dt.date.fromisoformat(value)
    except (ValueError, TypeError):
        lit.fail("review date must be YYYY-MM-DD")


def protocol_check(path):
    p = read_json(path)
    if p.get("schema") != "meta-diagnostic-project-v1" or p.get("mode") not in {"synthetic_test", "real"}:
        lit.fail("invalid diagnostic project schema/mode")
    for key in ("project_id", "question", "case_design", "threshold_rule", "search_status"):
        if not nonblank(p.get(key)):
            lit.fail(f"diagnostic protocol needs {key}")
    if p["case_design"] not in {"single_gate", "two_gate", "case_control"}:
        lit.fail("case_design must distinguish single-gate, two-gate or case-control sampling")
    if not isinstance(p.get("pico"), dict) or any(not nonblank(p["pico"].get(k)) for k in
            ("population", "index_test", "reference_standard", "target_condition")):
        lit.fail("diagnostic PICO needs population, index test, reference standard and target condition")
    if not isinstance(p.get("eligible_designs"), list) or not p["eligible_designs"] or not all(map(nonblank, p["eligible_designs"])):
        lit.fail("eligible designs required")
    a = p.get("analysis")
    if not isinstance(a, dict) or any(a.get(key) != p["pico"][key] for key in ("index_test", "reference_standard")):
        lit.fail("diagnostic analysis test/reference must match PICO")
    if a.get("outcome") != p["pico"]["target_condition"]:
        lit.fail("diagnostic analysis outcome must match target condition")
    if p.get("mode") == "real":
        if a.get("source_kind") != "reviewed_extraction" or p["search_status"] == "complete_verified_by_software":
            lit.fail("real diagnostic project needs reviewed extraction and cannot assert software-verified search completeness")
        approval = p.get("approval", {})
        if not all(nonblank(approval.get(k)) for k in ("reviewer", "reference", "date", "declaration")):
            lit.fail("real protocol needs actual reviewer approval declaration/reference/date")
        date(approval["date"])
    elif a.get("source_kind") not in {"synthetic_fixture", "package_method_example"}:
        lit.fail("synthetic project needs explicitly synthetic/package inputs")
    quadas = p.get("quality_tool", {})
    if not all(nonblank(quadas.get(k)) for k in ("name", "version", "reference")):
        lit.fail("quality tool name/version/reference required; no questionnaire is bundled")
    return p


def checked_inputs(a):
    p = protocol_check(a.protocol)
    from dual_screen import verify_if_marked
    verify_if_marked(a.records, a.dedup, a.decisions)
    records, _ = lit.read_csv(a.records, ["record_id", "title", "authors", "year", "doi", "pmid"])
    by_record = {r["record_id"]: r for r in records}
    if len(by_record) != len(records):
        lit.fail("bibliography has repeated record IDs")
    dedup = lit.load_dedup(records, a.dedup)
    active = {rid for rid, d in dedup.items() if d["disposition"] == "keep"}
    decisions, _ = lit.read_csv(a.decisions, ["record_id", "stage", "decision", "reason", "reviewer", "decision_date"])
    _, included = lit.validate_screening(records, decisions, active)
    mapping, _ = lit.read_csv(a.report_map, ["record_id", "report_id", "study_id"])
    if len(mapping) != len(included) or {r["record_id"] for r in mapping} != included or len({r["report_id"] for r in mapping}) != len(mapping):
        lit.fail("report map must cover exactly included reports with unique report IDs")
    if any(not nonblank(r["study_id"]) or not nonblank(r["report_id"]) for r in mapping):
        lit.fail("report map has blank study/report ID")
    study_by_record = {r["record_id"]: r["study_id"] for r in mapping}
    rows = diagnostic_meta.read_rows(a.input)
    if "record_id" not in rows[0] or "case_design" not in rows[0]:
        lit.fail("protocol-bound diagnostic input needs record_id and case_design")
    diagnostic_meta.validate(p["analysis"], rows)
    if any(r["case_design"] != p["case_design"] for r in rows):
        lit.fail("per-study case_design differs from the protocol")
    if p["analysis"]["threshold_policy"] == "common" and any(r["threshold"] != p["threshold_rule"] for r in rows):
        lit.fail("per-study threshold differs from the protocol threshold rule")
    if any(r["record_id"] not in study_by_record or study_by_record[r["record_id"]] != r["study_id"] for r in rows):
        lit.fail("2x2 row needs an included report mapped to its study")
    if {r["study_id"] for r in rows} != set(study_by_record.values()):
        lit.fail("included study and analyzed 2x2 study sets differ")
    source_rows, _ = lit.read_csv(a.source_review, ["study_id", "status", "reviewer", "reviewed_at", "source_file", "source_sha256", "source_location"])
    sources = {r["study_id"]: r for r in source_rows}
    if len(sources) != len(source_rows) or set(sources) != {r["study_id"] for r in rows}:
        lit.fail("source review needs one row per analyzed study")
    for row in rows:
        claim = sources[row["study_id"]]
        if any(claim[k] != row[k] for k in ("source_file", "source_sha256", "source_location")):
            lit.fail("source review disagrees with analyzed 2x2 source")
        status = claim["status"]
        if status not in {"pending", "synthetic_test", "human_verified"}:
            lit.fail("source review status invalid")
        if status == "human_verified":
            if not nonblank(claim["reviewer"]) or not nonblank(claim["reviewed_at"]):
                lit.fail("human verified source needs reviewer/date")
            date(claim["reviewed_at"])
        if p["mode"] == "real" and status == "synthetic_test":
            lit.fail("synthetic source status in real project")
        if p["mode"] == "real" and status != "human_verified":
            lit.fail("real diagnostic analysis requires human-verified source rows; pending may remain in a preparation ledger")
    votes, _ = lit.read_csv(a.quadas, ["study_id", "domain", "status", "judgment", "applicability", "rationale", "evidence_file", "evidence_sha256", "evidence_locator", "reviewer", "reviewed_at"])
    required = {(r["study_id"], domain) for r in rows for domain in DOMAINS}
    found = {(r["study_id"], r["domain"]) for r in votes}
    if len(found) != len(votes) or found != required:
        lit.fail("quality ledger needs exactly four diagnostic evidence domains per study")
    for row in votes:
        if row["status"] not in {"pending", "synthetic_test", "human_assessed"}:
            lit.fail("quality status invalid")
        if p["mode"] == "real" and row["status"] == "synthetic_test":
            lit.fail("synthetic quality judgment in real project")
        if row["status"] == "pending":
            if row["judgment"] or row["applicability"]:
                lit.fail("pending quality item cannot claim a judgment")
            continue
        if row["judgment"] not in {"low", "high", "unclear"} or row["applicability"] not in {"low", "high", "unclear", "not_applicable"} or not nonblank(row["rationale"]):
            lit.fail("assessed quality item needs judgment, applicability and rationale")
        if row["domain"] == "flow_timing" and row["applicability"] != "not_applicable":
            lit.fail("flow/timing applicability must be not_applicable")
        if not all(nonblank(row[k]) for k in ("evidence_file", "evidence_sha256", "evidence_locator", "reviewer", "reviewed_at")):
            lit.fail("assessed quality item needs source locator and reviewer/date")
        date(row["reviewed_at"])
        source = Path(row["evidence_file"]).resolve()
        if not source.is_file() or lit.sha256(source) != row["evidence_sha256"]:
            lit.fail("quality evidence file changed or missing")
        locator_pattern = r"(?i)(page|p\.|table|figure)\s*[A-Za-z0-9]" if p["mode"] == "real" else r"(?i)(page|p\.|table|figure|synthetic row)\s*[A-Za-z0-9]"
        if not re.search(locator_pattern, row["evidence_locator"]):
            lit.fail("quality evidence needs a concrete locator")
    return p, records, dedup, included, mapping, rows, source_rows, votes


def evidence_hashes(a, rows, votes):
    hashes = {name: lit.sha256(getattr(a, name)) for name in CORE}
    hashes["diagnostic_meta.py"] = lit.sha256(Path(__file__).with_name("diagnostic_meta.py"))
    hashes["diagnostic_meta.R"] = lit.sha256(Path(__file__).with_name("diagnostic_meta.R"))
    hashes["diagnostic_project.py"] = lit.sha256(__file__)
    hashes["diagnostic_word.py"] = lit.sha256(Path(__file__).with_name("diagnostic_word.py"))
    hashes["source_bytes"] = {str(Path(r["source_file"]).resolve()): r["source_sha256"] for r in rows}
    hashes["quality_evidence_bytes"] = {str(Path(r["evidence_file"]).resolve()): r["evidence_sha256"] for r in votes if r["status"] != "pending"}
    return hashes


def confirm(a):
    p, _, _, _, _, rows, _, votes = checked_inputs(a)
    out = Path(a.out).resolve()
    if out.exists():
        lit.fail("confirmation output exists")
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".dta-confirm-", dir=out.parent) as temp:
        stage = Path(temp) / "result"; stage.mkdir()
        receipt = {"schema": "meta-diagnostic-confirmation-v1", "mode": p["mode"],
                   "status": "SYNTHETIC_TEST_CONFIRMATION" if p["mode"] == "synthetic_test" else "HUMAN_APPROVAL_CLAIM_FILE_CONSISTENCY",
                   "approval": p.get("approval", {}), "input_paths": {key: str(Path(getattr(a, key)).resolve()) for key in CORE},
                   "hashes": evidence_hashes(a, rows, votes), "identity_authenticated": False,
                   "search_completeness_established": False, "final_report": False}
        (stage / "diagnostic_confirmation.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(stage, out)
    print(receipt["status"], out)


def narrative_check(path, records, mode):
    n = read_json(path)
    if not nonblank(n.get("title")):
        lit.fail("draft title required")
    known = {r["record_id"] for r in records}
    for section in ("Introduction", "Discussion"):
        entries = n.get(section)
        if not isinstance(entries, list) or not entries:
            lit.fail(f"{section} needs substantive sourced paragraphs")
        for entry in entries:
            ids = entry.get("record_ids")
            if not nonblank(entry.get("text")) or not isinstance(ids, list) or any(rid not in known for rid in ids):
                lit.fail(f"{section} has blank text or unknown reference")
            if mode == "real" and (not ids or not re.search(r"(?i)(page|p\.|table|figure)\s*[A-Za-z0-9]", entry.get("source_locator") or "") or entry.get("review_status") not in {"pending", "human_verified"}):
                lit.fail(f"real {section} needs existing references, locator and reviewer status")
            if mode == "synthetic_test" and entry.get("review_status") != "synthetic_test":
                lit.fail("synthetic narrative must be labeled synthetic_test")
    return n


def build(a):
    p, records, dedup, included, mapping, rows, source_rows, votes = checked_inputs(a)
    confirmation = read_json(Path(a.confirmation) / "diagnostic_confirmation.json")
    if confirmation.get("schema") != "meta-diagnostic-confirmation-v1" or confirmation.get("mode") != p["mode"]:
        lit.fail("diagnostic confirmation invalid")
    if confirmation.get("input_paths") != {key: str(Path(getattr(a, key)).resolve()) for key in CORE} or confirmation.get("hashes") != evidence_hashes(a, rows, votes):
        lit.fail("diagnostic confirmation stale; reconfirm changed protocol or evidence")
    for path, sha in {**confirmation["hashes"]["source_bytes"], **confirmation["hashes"]["quality_evidence_bytes"]}.items():
        if not Path(path).is_file() or lit.sha256(path) != sha:
            lit.fail("original diagnostic evidence changed after confirmation")
    narrative = narrative_check(a.narrative, records, p["mode"])
    out = Path(a.out).resolve()
    if out.exists():
        lit.fail("draft output exists")
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".dta-paper-", dir=out.parent) as temp:
        stage = Path(temp) / "result"; stage.mkdir()
        stats = stage / "statistics"
        plan_path = stage / "analysis_plan.json"
        plan_path.write_text(json.dumps(p["analysis"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        diagnostic_meta.run(SimpleNamespace(input=a.input, plan=plan_path, out=stats, rscript=a.rscript))
        with (stats / "diagnostic_summary.csv").open(encoding="utf-8", newline="") as f:
            value = next(csv.DictReader(f))
        total = len(records); removed = sum(x["disposition"] != "keep" for x in dedup.values())
        counts = {"records_imported": total, "records_removed_before_screening": removed,
                  "records_screened": total-removed, "reports_included": len(included),
                  "studies_analyzed": len(rows), "source_count_claim": p["search_status"],
                  "not_a_complete_prisma_flow": True}
        (stage / "selection_counts.json").write_text(json.dumps(counts, indent=2) + "\n", encoding="utf-8")
        lit.write_csv(stage / "included_studies.csv", ["study_id", "record_id", "report_ids", "source_location"],
                      [dict(study_id=r["study_id"], record_id=r["record_id"],
                            report_ids="|".join(m["report_id"] for m in mapping if m["study_id"] == r["study_id"]),
                            source_location=r["source_location"]) for r in rows])
        shutil.copyfile(a.source_review, stage / "source_review.csv")
        shutil.copyfile(a.quadas, stage / "quadas_evidence.csv")
        status = "DRAFT_SYNTHETIC" if p["mode"] == "synthetic_test" else "DRAFT_HUMAN_REVIEW_PENDING"
        if p["mode"] == "real" and all(r["status"] == "human_verified" for r in source_rows) and all(r["status"] == "human_assessed" for r in votes):
            status = "DRAFT_EVIDENCE_RECORDED_NOT_FINAL"
        refs = {r["record_id"]: r for r in records}
        used = []
        def para(text, style=None, figures=None, table=None):
            return {"text": text, **({"style": style} if style else {}), **({"figures": figures} if figures else {}), **({"table": table} if table else {})}
        sections = [para(narrative["title"], "Title"), para(status + ": diagnostic research draft; source meaning and clinical judgments require review.")]
        sections.append(para("Introduction", "Heading1"))
        for entry in narrative["Introduction"]:
            for rid in entry["record_ids"]:
                if rid not in used: used.append(rid)
            cite = " [" + ", ".join(str(used.index(rid)+1) for rid in entry["record_ids"]) + "]" if entry["record_ids"] and p["mode"] == "real" else ""
            sections.append(para(entry["text"] + cite))
        sections.append(para("Methods", "Heading1"))
        sections.append(para(f"Question: {p['question']} Population: {p['pico']['population']}. Index test: {p['pico']['index_test']}. Reference standard: {p['pico']['reference_standard']}. Target condition: {p['pico']['target_condition']}.") )
        sections.append(para(f"Eligible designs: {'; '.join(p['eligible_designs'])}. Sampling design: {p['case_design']}. Threshold rule: {p['threshold_rule']}. Search status: {p['search_status']}; comprehensive coverage is not established by this program."))
        sections.append(para(f"Independent study 2×2 tables were analyzed by mada bivariate Reitsma REML with {p['analysis']['zero_policy']} zero-cell policy and {100*(1-p['analysis']['alpha']):g}% confidence intervals. Threshold handling: {p['analysis']['threshold_policy']}. The named quality tool was {p['quality_tool']['name']} {p['quality_tool']['version']}; the evidence ledger contains reviewer-entered domain judgments or unresolved entries, without automatic scoring."))
        sections.append(para("Results", "Heading1"))
        sections.append(para(f"{counts['records_imported']} records entered the local ledger; {counts['records_removed_before_screening']} were explicitly removed before screening; {counts['reports_included']} reports mapped to {counts['studies_analyzed']} analyzed studies. These local counts do not establish complete PRISMA reporting."))
        if p["mode"] == "real":
            for mapped in mapping:
                if mapped["record_id"] not in used: used.append(mapped["record_id"])
            sections.append(para("Included report sources: [" + ", ".join(str(used.index(mapped["record_id"])+1) for mapped in mapping) + "]."))
        study_rows = [["Study", "Case design", "TP / FN / FP / TN", "Threshold", "Source locator"]]
        study_rows += [[r["study_id"], r["case_design"], " / ".join(str(r[k]) for k in ("TP","FN","FP","TN")), r["threshold"], r["source_location"]] for r in rows]
        sections.append(para("Included study characteristics and selected 2×2 data.", table={"title":"Table 1. Included diagnostic study inputs", "rows":study_rows}))
        threshold_note = "Mixed thresholds: exploratory pooled result only." if value["interpretation_scope"] == "MIXED_THRESHOLDS_EXPLORATORY" else "Common threshold label supplied; clinical equivalence is unverified."
        sections.append(para(f"Pooled sensitivity was {float(value['sensitivity']):.3f} ({100*(1-p['analysis']['alpha']):g}% CI {float(value['sensitivity_lower']):.3f}–{float(value['sensitivity_upper']):.3f}); pooled specificity was {float(value['specificity']):.3f} (CI {float(value['specificity_lower']):.3f}–{float(value['specificity_upper']):.3f}). The model used {len(rows)} independent labeled study tables. {threshold_note} The forest plots use the planned {p['analysis']['zero_policy']} correction; raw study ratios are in the trace table. These are descriptive model estimates, not a clinical recommendation.", figures=[(1, "Sensitivity and specificity forest plots; supplied local 2×2 data", stats / "paired_forest.png"), (2, "Summary receiver operating characteristic plot; bivariate model", stats / "sroc.png")]))
        pending_quality = sum(r["status"] == "pending" for r in votes)
        sections.append(para(f"Quality evidence: {len(votes)} study-domain entries; {pending_quality} remain pending. The ledger records user judgments, not software-derived QUADAS ratings."))
        vote_map = {(r["study_id"], r["domain"]): r for r in votes}
        quality_rows = [["Study", "Patient selection", "Index test", "Reference standard", "Flow and timing"]]
        quality_rows += [[r["study_id"]] + [f"{vote_map[(r['study_id'], domain)]['judgment'] or 'pending'} ({vote_map[(r['study_id'], domain)]['status']})" for domain in DOMAINS] for r in rows]
        sections.append(para("Risk-of-bias domain evidence status; see the cited ledger for rationale and applicability.", table={"title":"Table 2. Diagnostic evidence-domain judgments", "rows":quality_rows}))
        sections.append(para("Discussion", "Heading1"))
        for entry in narrative["Discussion"]:
            for rid in entry["record_ids"]:
                if rid not in used: used.append(rid)
            cite = " [" + ", ".join(str(used.index(rid)+1) for rid in entry["record_ids"]) + "]" if entry["record_ids"] and p["mode"] == "real" else ""
            sections.append(para(entry["text"] + cite))
        sections.append(para("Limitations", "Heading1"))
        sections.append(para("Local hashes and review labels check consistency, not truth, identity or independent study sampling. Sensitivity and specificity depend on thresholds, spectrum and reference-standard quality. Mixed thresholds require separate clinical review. Search completeness, original full text, QUADAS instrument scoring and final certainty are not authenticated here."))
        sections.append(para("References", "Heading1"))
        if p["mode"] == "real":
            for i, rid in enumerate(used, 1):
                ref = refs[rid]
                sections.append(para(f"[{i}] {ref['authors']}. {ref['title']}. {ref['year']}." + (f" doi:{ref['doi']}" if ref["doi"] else "") + (f" PMID:{ref['pmid']}" if ref["pmid"] else "")))
        else:
            sections.append(para("Synthetic fixture: no real bibliographic references are asserted."))
        manuscript = {"schema": "meta-diagnostic-manuscript-v1", "status": status, "final": False,
                      "sections": [{k:v for k,v in s.items() if k != "figures"} for s in sections],
                      "fact_sources": {"confirmation_sha256": lit.sha256(Path(a.confirmation) / "diagnostic_confirmation.json"),
                                       "statistics_receipt_sha256": lit.sha256(stats / "diagnostic_receipt.json"),
                                       "narrative_sha256": lit.sha256(a.narrative)}}
        (stage / "manuscript.json").write_text(json.dumps(manuscript, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        def markdown(item):
            text = ("# " if item.get("style") == "Title" else "## " if item.get("style") == "Heading1" else "") + item["text"]
            if item.get("table"):
                lines = item["table"]["rows"]
                text += "\n\n" + item["table"]["title"] + "\n\n" + " | ".join(lines[0]) + "\n" + " | ".join("---" for _ in lines[0])
                text += "\n" + "\n".join(" | ".join(str(cell).replace("|", "/") for cell in row) for row in lines[1:])
            return text
        (stage / "manuscript.md").write_text("\n\n".join(markdown(s) for s in sections) + "\n", encoding="utf-8")
        diagnostic_word.write(stage / "manuscript.docx", sections, [(1, "forest", stats / "paired_forest.png"), (2, "sroc", stats / "sroc.png")])
        (stage / "status.json").write_text(json.dumps({"status": status, "final": False, "human_identity_authenticated": False, "search_completeness_established": False, "word_visual_reviewed": False}, indent=2) + "\n", encoding="utf-8")
        files = {str(path.relative_to(stage)).replace("\\", "/"): lit.sha256(path) for path in stage.rglob("*") if path.is_file()}
        (stage / "manifest.json").write_text(json.dumps({"schema": "meta-diagnostic-draft-manifest-v1", "files": files}, indent=2) + "\n", encoding="utf-8")
        os.replace(stage, out)
    print(status, out)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("confirm", "build"))
    for name in CORE:
        parser.add_argument("--" + name.replace("_", "-"), required=True)
    parser.add_argument("--confirmation")
    parser.add_argument("--narrative")
    parser.add_argument("--rscript")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    try:
        if args.command == "confirm":
            confirm(args)
        else:
            if not all((args.confirmation, args.narrative, args.rscript)):
                lit.fail("build needs --confirmation, --narrative and --rscript")
            build(args)
    except (ValueError, OSError, KeyError, TypeError, json.JSONDecodeError, csv.Error) as error:
        parser.exit(2, f"Validation: {error}\n")
