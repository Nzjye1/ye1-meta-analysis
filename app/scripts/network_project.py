"""Network protocol, screening and transitivity ledger to a netmeta-backed Word draft."""
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

import diagnostic_project as shared
import diagnostic_word
import literature as lit
import network_meta

CORE = ("protocol", "records", "dedup", "decisions", "report_map", "input", "assumptions")
ASSUMPTION_FIELDS = ("study_id", "status", "population_note", "effect_modifier_note", "allocation_note",
                     "risk_of_bias_judgment", "source_file", "source_sha256", "source_location", "reviewer", "reviewed_at")


def protocol(path):
    p = shared.read_json(path)
    if p.get("schema") != "meta-network-project-v1" or p.get("mode") not in {"synthetic_test", "real"}:
        lit.fail("invalid network project schema/mode")
    for key in ("project_id", "question", "search_status"):
        if not shared.nonblank(p.get(key)):
            lit.fail(f"network protocol needs {key}")
    pico = p.get("pico", {})
    if any(not shared.nonblank(pico.get(key)) for key in ("population", "interventions", "comparator", "outcome")):
        lit.fail("network PICO needs population, interventions, comparator and outcome")
    if not isinstance(p.get("eligible_designs"), list) or not p["eligible_designs"] or not all(map(shared.nonblank, p["eligible_designs"])):
        lit.fail("network eligible designs required")
    analysis = network_meta.plan_check(p.get("analysis", {}))
    if analysis["outcome"] != pico["outcome"] or analysis["reference_treatment"] != pico["comparator"]:
        lit.fail("network effect outcome/reference differs from PICO")
    if p["mode"] == "real":
        if analysis["source_kind"] != "reviewed_extraction" or p["search_status"] == "complete_verified_by_software":
            lit.fail("real network route needs reviewed extraction and cannot assert software-verified search completeness")
        approval = p.get("approval", {})
        if any(not shared.nonblank(approval.get(k)) for k in ("reviewer", "reference", "date", "declaration")):
            lit.fail("real network protocol needs human approval declaration/reference/date")
        shared.date(approval["date"])
    elif analysis["source_kind"] not in {"synthetic_fixture", "package_method_example"}:
        lit.fail("synthetic network route needs synthetic/package data")
    return p


def checked(a):
    p = protocol(a.protocol)
    from dual_screen import verify_if_marked
    verify_if_marked(a.records, a.dedup, a.decisions)
    records, _ = lit.read_csv(a.records, ["record_id", "title", "authors", "year", "doi", "pmid"])
    if len({r["record_id"] for r in records}) != len(records):
        lit.fail("repeated bibliography record ID")
    dedup = lit.load_dedup(records, a.dedup)
    active = {rid for rid, r in dedup.items() if r["disposition"] == "keep"}
    decisions, _ = lit.read_csv(a.decisions, ["record_id", "stage", "decision", "reason", "reviewer", "decision_date"])
    _, included = lit.validate_screening(records, decisions, active)
    mapping, _ = lit.read_csv(a.report_map, ["record_id", "report_id", "study_id"])
    if len(mapping) != len(included) or {r["record_id"] for r in mapping} != included or len({r["report_id"] for r in mapping}) != len(mapping):
        lit.fail("network report map needs exactly included reports and unique IDs")
    study_by_record = {r["record_id"]: r["study_id"] for r in mapping}
    rows = network_meta.table(a.input)
    if "record_id" not in rows[0]:
        lit.fail("network project contrast input needs record_id")
    study_count, multiarm_count, nodes = network_meta.validate(p["analysis"], rows)
    if any(r["record_id"] not in study_by_record or r["study_id"] != study_by_record[r["record_id"]] for r in rows):
        lit.fail("network contrast needs a full-text included report mapped to its study")
    if {r["study_id"] for r in rows} != set(study_by_record.values()):
        lit.fail("network included and analyzed study sets differ")
    assumptions, _ = lit.read_csv(a.assumptions, ASSUMPTION_FIELDS)
    by_study = {r["study_id"]: r for r in assumptions}
    if len(by_study) != len(assumptions) or set(by_study) != {r["study_id"] for r in rows}:
        lit.fail("transitivity ledger needs one row per independent study")
    for r in assumptions:
        if r["status"] not in {"synthetic_test", "human_assessed", "pending"} or any(not shared.nonblank(r[k]) for k in ("population_note", "effect_modifier_note", "allocation_note")):
            lit.fail("transitivity entry needs design/effect-modifier notes and status")
        if p["mode"] == "real" and r["status"] != "human_assessed":
            lit.fail("real network analysis needs human-assessed transitivity entries")
        if p["mode"] == "real" and r["risk_of_bias_judgment"] not in {"low", "some_concerns", "high", "unclear"}:
            lit.fail("real network transitivity ledger needs reviewer risk-of-bias judgment")
        if r["status"] != "pending":
            if any(not shared.nonblank(r[k]) for k in ("source_file", "source_sha256", "source_location", "reviewer", "reviewed_at")):
                lit.fail("assessed transitivity row needs local evidence and reviewer/date")
            shared.date(r["reviewed_at"])
            source = Path(r["source_file"]).resolve()
            locator_pattern = r"(?i)(page|p\.|table|figure)\s*[A-Za-z0-9]" if p["mode"] == "real" else r"(?i)(page|p\.|table|figure|dataset row|synthetic row)\s*[A-Za-z0-9]"
            if not source.is_file() or lit.sha256(source) != r["source_sha256"] or not re.search(locator_pattern, r["source_location"]):
                lit.fail("transitivity evidence missing, changed or unlocated")
    return p, records, dedup, included, mapping, rows, assumptions, study_count, multiarm_count, nodes


def hashes(a, rows, assumptions):
    result = {key: lit.sha256(getattr(a, key)) for key in CORE}
    for file in ("network_meta.py", "network_meta.R", "network_project.py", "diagnostic_project.py", "diagnostic_word.py"):
        result[file] = lit.sha256(Path(__file__).with_name(file))
    result["source_bytes"] = {str(Path(r["source_file"]).resolve()): r["source_sha256"] for r in rows}
    result["assumption_bytes"] = {str(Path(r["source_file"]).resolve()): r["source_sha256"] for r in assumptions if r["status"] != "pending"}
    return result


def confirm(a):
    p, _, _, _, _, rows, assumptions, _, _, _ = checked(a)
    out = Path(a.out).resolve()
    if out.exists(): lit.fail("network confirmation output exists")
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".network-confirm-", dir=out.parent) as temp:
        stage = Path(temp) / "result"; stage.mkdir()
        receipt = {"schema": "meta-network-confirmation-v1", "mode": p["mode"],
                   "status": "SYNTHETIC_TEST_CONFIRMATION" if p["mode"] == "synthetic_test" else "HUMAN_APPROVAL_CLAIM_FILE_CONSISTENCY",
                   "approval": p.get("approval", {}), "input_paths": {k: str(Path(getattr(a, k)).resolve()) for k in CORE},
                   "hashes": hashes(a, rows, assumptions), "human_identity_authenticated": False,
                   "transitivity_clinically_verified_by_software": False, "final_report": False}
        (stage / "network_confirmation.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
        os.replace(stage, out)
    print(receipt["status"], out)


def build(a):
    p, records, dedup, included, mapping, rows, assumptions, study_count, multiarm_count, nodes = checked(a)
    receipt_path = Path(a.confirmation) / "network_confirmation.json"
    receipt = shared.read_json(receipt_path)
    if receipt.get("schema") != "meta-network-confirmation-v1" or receipt.get("mode") != p["mode"] or receipt.get("input_paths") != {k: str(Path(getattr(a, k)).resolve()) for k in CORE} or receipt.get("hashes") != hashes(a, rows, assumptions):
        lit.fail("network confirmation stale or invalid")
    for path, digest in {**receipt["hashes"]["source_bytes"], **receipt["hashes"]["assumption_bytes"]}.items():
        if not Path(path).is_file() or lit.sha256(path) != digest:
            lit.fail("network original evidence changed")
    narrative = shared.narrative_check(a.narrative, records, p["mode"])
    out = Path(a.out).resolve()
    if out.exists(): lit.fail("network paper output exists")
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".network-paper-", dir=out.parent) as temp:
        stage = Path(temp) / "result"; stage.mkdir()
        stats = stage / "statistics"
        engine_plan = stage / "analysis_plan.json"
        engine_plan.write_text(json.dumps(p["analysis"], ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
        network_meta.run(SimpleNamespace(input=a.input, plan=engine_plan, rscript=a.rscript, out=stats))
        with (stats / "network_summary.csv").open(encoding="utf-8", newline="") as f: summary = next(csv.DictReader(f))
        with (stats / "reference_effects.csv").open(encoding="utf-8", newline="") as f: effects = list(csv.DictReader(f))
        with (stats / "ranking.csv").open(encoding="utf-8", newline="") as f: ranks = list(csv.DictReader(f))
        status = "DRAFT_SYNTHETIC" if p["mode"] == "synthetic_test" else "DRAFT_HUMAN_REVIEW_PENDING"
        if p["mode"] == "real" and all(r["status"] == "human_assessed" for r in assumptions):
            status = "DRAFT_EVIDENCE_RECORDED_NOT_FINAL"
        counts = {"records_imported": len(records), "records_removed_before_screening": sum(r["disposition"] != "keep" for r in dedup.values()),
                  "reports_included": len(included), "studies_analyzed": study_count, "multiarm_studies": multiarm_count,
                  "treatments": nodes, "not_complete_prisma": True}
        (stage / "selection_counts.json").write_text(json.dumps(counts, indent=2)+"\n", encoding="utf-8")
        shutil.copyfile(a.assumptions, stage / "transitivity_evidence.csv")
        records_by_id = {r["record_id"]: r for r in records}
        used = []
        sections = []
        def add(text, style=None, figures=None, table=None):
            sections.append({"text": text, **({"style": style} if style else {}), **({"figures": figures} if figures else {}), **({"table": table} if table else {})})
        def prose(items):
            for entry in items:
                for rid in entry["record_ids"]:
                    if rid not in used: used.append(rid)
                cite = " [" + ", ".join(str(used.index(rid)+1) for rid in entry["record_ids"]) + "]" if p["mode"] == "real" and entry["record_ids"] else ""
                add(entry["text"] + cite)
        add(narrative["title"], "Title")
        add(status + ": model results and scientific assumptions require human review.")
        add("Introduction", "Heading1"); prose(narrative["Introduction"])
        add("Methods", "Heading1")
        add(f"Question: {p['question']} Population: {p['pico']['population']}. Treatments: {p['pico']['interventions']}. Reference: {p['pico']['comparator']}. Outcome: {p['pico']['outcome']} at {p['analysis']['timepoint']}.")
        add(f"Eligible designs: {'; '.join(p['eligible_designs'])}. Search status: {p['search_status']}. Independent treatment contrasts were pooled with netmeta {summary['netmeta_version']} using {p['analysis']['model']}/{p['analysis']['tau_method']}, effect scale {p['analysis']['effect_type']} ({summary['scale']}), alpha {p['analysis']['alpha']}. Complete multi-arm contrast sets were handled by netmeta; no arm was copied as an independent study.")
        add(f"Transitivity rationale supplied by reviewer: {p['analysis']['transitivity_rationale']}. Per-study population, effect-modifier, allocation and bias notes are in the evidence ledger; these are not automatically verified. Smaller values were predeclared {p['analysis']['small_values']} for ranking.")
        add("Results", "Heading1")
        add(f"The local ledger contained {counts['records_imported']} records; {counts['records_removed_before_screening']} were explicitly removed; {counts['reports_included']} reports represented {study_count} studies and {len(nodes)} connected treatments. {multiarm_count} studies had multiple arms. These counts do not establish full PRISMA compliance.", figures=[(1,"Connected treatment network; node/edge geometry from checked contrasts",stats/"network_graph.png")])
        if p["mode"] == "real":
            for mapped in mapping:
                if mapped["record_id"] not in used: used.append(mapped["record_id"])
            add("Included report sources: [" + ", ".join(str(used.index(mapped["record_id"])+1) for mapped in mapping) + "].")
        assumption_by_study = {r["study_id"]:r for r in assumptions}
        study_rows = [["Study", "Compared treatments", "Cohort", "Transitivity/bias status"]]
        for sid in sorted(assumption_by_study):
            study_rows.append([sid, "; ".join(f"{r['treat1']} vs {r['treat2']}" for r in rows if r["study_id"] == sid),
                               next(r["cohort_id"] for r in rows if r["study_id"] == sid),
                               assumption_by_study[sid]["status"] + "/" + assumption_by_study[sid]["risk_of_bias_judgment"]])
        add("Included network designs and transitivity evidence status.", table={"title":"Table 1. Included network study inputs", "rows":study_rows})
        effect_rows = [["Treatment", "Reference", p["analysis"]["effect_type"] + " estimate", f"{100*(1-p['analysis']['alpha']):g}% CI"]]
        effect_rows += [[e["treatment"], e["reference"], f"{float(e['display_estimate']):.3f}",
                         f"{float(e['display_lower']):.3f} to {float(e['display_upper']):.3f}"] for e in effects]
        add("Model estimates against the prespecified reference; ratio effects are shown after exponentiating entered log effects.", table={"title":"Table 2. Network effects versus reference", "rows":effect_rows})
        q_display = f"{float(summary['Q_inconsistency']):.3g}" if summary['Q_inconsistency'] else "not estimable"
        p_value = float(summary['p_inconsistency']) if summary['p_inconsistency'] else None
        p_display = ("p not estimable" if p_value is None else
                     "p<0.001" if 0 <= p_value < 0.001 else f"p={p_value:.3f}")
        add(f"Global design-by-treatment inconsistency: {summary['inconsistency_status']}; Q={q_display}, df={summary['df_inconsistency'] or 'not estimable'}, {p_display}. Inspect local direct-versus-indirect results before interpretation.", figures=[(2,"Network effects versus the prespecified reference",stats/"reference_forest.png")])
        add("Model-based P-scores: " + "; ".join(f"{r['treatment']} {float(r['p_score']):.3f}" for r in ranks) + ". These are ranking scores, not probabilities of benefit or certainty grades.")
        add("Discussion", "Heading1"); prose(narrative["Discussion"])
        add("Limitations", "Heading1")
        add("Transitivity and effect-modifier similarity require clinical assessment. Global and local inconsistency tests have limited power; a nonsignificant test does not prove consistency. Multi-arm covariance handling is delegated to netmeta after complete-contrast validation. Source hashes check local bytes, not extraction correctness or reviewer identity. This draft is not a treatment recommendation.")
        add("References", "Heading1")
        if p["mode"] == "real":
            for i, rid in enumerate(used, 1):
                ref = records_by_id[rid]
                add(f"[{i}] {ref['authors']}. {ref['title']}. {ref['year']}." + (f" doi:{ref['doi']}" if ref['doi'] else "") + (f" PMID:{ref['pmid']}" if ref['pmid'] else ""))
        else: add("Synthetic/package example: no real bibliography is asserted.")
        document = {"schema": "meta-network-manuscript-v1", "status": status, "final": False,
                    "sections": [{k:v for k,v in s.items() if k != "figures"} for s in sections],
                    "fact_sources": {"confirmation_sha256": lit.sha256(receipt_path), "statistics_receipt_sha256": lit.sha256(stats/"network_receipt.json"), "narrative_sha256": lit.sha256(a.narrative)}}
        (stage / "manuscript.json").write_text(json.dumps(document, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
        def markdown(item):
            text = ("# " if item.get("style") == "Title" else "## " if item.get("style") == "Heading1" else "") + item["text"]
            if item.get("table"):
                rows = item["table"]["rows"]
                text += "\n\n" + item["table"]["title"] + "\n\n" + " | ".join(rows[0]) + "\n" + " | ".join("---" for _ in rows[0])
                text += "\n" + "\n".join(" | ".join(str(cell).replace("|", "/") for cell in row) for row in rows[1:])
            return text
        (stage / "manuscript.md").write_text("\n\n".join(markdown(s) for s in sections)+"\n", encoding="utf-8")
        diagnostic_word.write(stage/"manuscript.docx", sections, [(1,"network",stats/"network_graph.png"),(2,"forest",stats/"reference_forest.png")])
        (stage/"status.json").write_text(json.dumps({"status":status,"final":False,"human_identity_authenticated":False,"word_visual_reviewed":False,"transitivity_clinically_verified_by_software":False},indent=2)+"\n",encoding="utf-8")
        files = {str(path.relative_to(stage)).replace("\\", "/"): lit.sha256(path) for path in stage.rglob("*") if path.is_file()}
        (stage/"manifest.json").write_text(json.dumps({"schema":"meta-network-draft-manifest-v1","files":files},indent=2)+"\n",encoding="utf-8")
        os.replace(stage, out)
    print(status, out)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("confirm", "build"))
    for name in CORE: parser.add_argument("--"+name.replace("_","-"), required=True)
    parser.add_argument("--confirmation"); parser.add_argument("--narrative"); parser.add_argument("--rscript")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    try:
        if args.command == "confirm": confirm(args)
        else:
            if not all((args.confirmation,args.narrative,args.rscript)):
                lit.fail("network build needs confirmation, narrative and Rscript")
            build(args)
    except (OSError,ValueError,KeyError,TypeError,json.JSONDecodeError,csv.Error) as error:
        parser.exit(2, f"Validation: {error}\n")
