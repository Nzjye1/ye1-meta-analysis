"""Dose-response protocol, report/category evidence and a non-final Word draft."""
import argparse
import csv
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from types import SimpleNamespace

import diagnostic_project as shared
import diagnostic_word
import dose_response as dose
import literature as lit

CORE = ("protocol", "records", "dedup", "decisions", "report_map", "input", "category_review")
REVIEW_FIELDS = ("study_id", "dose", "record_id", "review_status", "reviewer", "reviewed_at",
                 "risk_of_bias_judgment", "risk_basis", "source_file", "source_sha256", "source_location")


def protocol(path):
    p = shared.read_json(path)
    if p.get("schema") != "meta-dose-project-v1" or p.get("mode") not in {"synthetic_test", "real"}:
        lit.fail("invalid dose project schema/mode")
    for key in ("project_id", "question", "search_status"):
        if not shared.nonblank(p.get(key)): lit.fail(f"dose protocol needs {key}")
    pico = p.get("pico", {})
    if any(not shared.nonblank(pico.get(k)) for k in ("population", "exposure", "comparator", "outcome")):
        lit.fail("dose PICO needs population, exposure, comparator and outcome")
    if not isinstance(p.get("eligible_designs"), list) or not p["eligible_designs"] or not all(map(shared.nonblank, p["eligible_designs"])):
        lit.fail("dose eligible designs required")
    analysis = p.get("analysis", {})
    dose.plan_check(analysis)
    if analysis["outcome"] != pico["outcome"] or analysis["reference_description"] != pico["comparator"]:
        lit.fail("dose outcome/reference differs from PICO")
    if p["mode"] == "real":
        if analysis["source_kind"] != "reviewed_extraction" or p["search_status"] == "complete_verified_by_software":
            lit.fail("real dose route needs reviewed extraction and no software claim of complete search")
        approval = p.get("approval", {})
        if any(not shared.nonblank(approval.get(k)) for k in ("reviewer", "reference", "date", "declaration")):
            lit.fail("real dose protocol needs human approval claim/reference/date")
        shared.date(approval["date"])
    elif analysis["source_kind"] not in {"synthetic_fixture", "package_method_example"}:
        lit.fail("synthetic dose route needs synthetic/package data")
    return p


def checked(a):
    p = protocol(a.protocol)
    from dual_screen import verify_if_marked
    verify_if_marked(a.records, a.dedup, a.decisions)
    records, _ = lit.read_csv(a.records, ["record_id", "title", "authors", "year", "doi", "pmid"])
    if len({r["record_id"] for r in records}) != len(records): lit.fail("repeated bibliography record ID")
    dedup = lit.load_dedup(records, a.dedup)
    active = {rid for rid, r in dedup.items() if r["disposition"] == "keep"}
    decisions, _ = lit.read_csv(a.decisions, ["record_id", "stage", "decision", "reason", "reviewer", "decision_date"])
    _, included = lit.validate_screening(records, decisions, active)
    mapping, _ = lit.read_csv(a.report_map, ["record_id", "report_id", "study_id"])
    if len(mapping) != len(included) or {r["record_id"] for r in mapping} != included or len({r["report_id"] for r in mapping}) != len(mapping):
        lit.fail("dose report map needs each included report exactly once")
    study_by_record = {r["record_id"]: r["study_id"] for r in mapping}
    rows = dose.table(a.input)
    count, _, _ = dose.validate(p["analysis"], rows)
    studies = {r["study_id"] for r in rows}
    if studies != set(study_by_record.values()): lit.fail("included and analyzed dose study sets differ")
    reviews, _ = lit.read_csv(a.category_review, REVIEW_FIELDS)
    if len(reviews) != len(rows): lit.fail("dose category review needs one row per category")
    by_category = {}
    for row in rows:
        key = (row["study_id"], row["dose"])
        if key in by_category: lit.fail("repeated dose category")
        by_category[key] = row
    checked_reviews = set()
    risk_by_study = {}
    for r in reviews:
        key = (r["study_id"], dose.number(r["dose"], "review dose"))
        if key not in by_category or key in checked_reviews: lit.fail("unmapped/repeated category review")
        checked_reviews.add(key)
        original = by_category[key]
        if r["record_id"] not in study_by_record or study_by_record[r["record_id"]] != r["study_id"]:
            lit.fail("category source report is not included in mapped study")
        if any(r[k] != original[k] for k in ("source_file", "source_sha256", "source_location")):
            lit.fail("category review source differs from statistical input")
        expected = "human_reviewed_claim" if p["mode"] == "real" else "synthetic_test"
        if r["review_status"] != expected or not shared.nonblank(r["reviewer"]) or not shared.nonblank(r["risk_basis"]):
            lit.fail("category review status/reviewer/risk basis missing or wrong mode")
        shared.date(r["reviewed_at"])
        if r["risk_of_bias_judgment"] not in {"low", "some_concerns", "high", "unclear"}:
            lit.fail("category review needs explicit risk-of-bias judgment")
        if r["study_id"] in risk_by_study and risk_by_study[r["study_id"]] != r["risk_of_bias_judgment"]:
            lit.fail("one study has inconsistent risk-of-bias judgments")
        risk_by_study[r["study_id"]] = r["risk_of_bias_judgment"]
        if p["mode"] == "real" and (r["risk_of_bias_judgment"] == "unclear" or not re.search(r"(?i)(page|p\.|table|figure)\s*[A-Za-z0-9]", r["risk_basis"])):
            lit.fail("real dose review needs a located human risk judgment")
    return p, records, dedup, included, mapping, rows, reviews, count


def hashes(a, rows):
    result = {key: lit.sha256(getattr(a, key)) for key in CORE}
    for name in ("dose_response.py", "dose_response.R", "dose_project.py", "diagnostic_project.py", "diagnostic_word.py"):
        result[name] = lit.sha256(Path(__file__).with_name(name))
    result["source_bytes"] = {str(Path(r["source_file"]).resolve()): r["source_sha256"] for r in rows}
    return result


def confirm(a):
    p, _, _, _, _, rows, _, _ = checked(a)
    out = Path(a.out).resolve()
    if out.exists(): lit.fail("dose confirmation output exists")
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".dose-confirm-", dir=out.parent) as temp:
        stage = Path(temp) / "result"; stage.mkdir()
        receipt = {"schema":"meta-dose-confirmation-v1", "mode":p["mode"],
                   "status":"SYNTHETIC_TEST_CONFIRMATION" if p["mode"]=="synthetic_test" else "HUMAN_APPROVAL_CLAIM_FILE_CONSISTENCY",
                   "approval":p.get("approval",{}), "input_paths":{k:str(Path(getattr(a,k)).resolve()) for k in CORE},
                   "hashes":hashes(a,rows), "human_identity_authenticated":False,
                   "source_meaning_verified_by_software":False, "final_report":False}
        (stage / "dose_confirmation.json").write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        os.replace(stage,out)
    print(receipt["status"],out)


def build(a):
    p, records, dedup, included, mapping, rows, reviews, study_count = checked(a)
    receipt_path = Path(a.confirmation) / "dose_confirmation.json"
    receipt = shared.read_json(receipt_path)
    if receipt.get("schema") != "meta-dose-confirmation-v1" or receipt.get("mode") != p["mode"] or receipt.get("input_paths") != {k:str(Path(getattr(a,k)).resolve()) for k in CORE} or receipt.get("hashes") != hashes(a,rows):
        lit.fail("dose confirmation stale or invalid")
    for path,digest in receipt["hashes"]["source_bytes"].items():
        if not Path(path).is_file() or lit.sha256(path)!=digest: lit.fail("dose original source changed")
    narrative = shared.narrative_check(a.narrative,records,p["mode"])
    out = Path(a.out).resolve()
    if out.exists(): lit.fail("dose draft output exists")
    out.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".dose-paper-",dir=out.parent) as temp:
        stage = Path(temp)/"result";stage.mkdir()
        stats=stage/"statistics"; plan_file=stage/"analysis_plan.json"
        plan_file.write_text(json.dumps(p["analysis"],ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        dose.run(SimpleNamespace(input=a.input,plan=plan_file,rscript=a.rscript,out=stats))
        with (stats/"dose_summary.csv").open(encoding="utf-8",newline="") as f: summary=next(csv.DictReader(f))
        with (stats/"dose_coefficients.csv").open(encoding="utf-8",newline="") as f: coefs=list(csv.DictReader(f))
        with (stats/"dose_predictions.csv").open(encoding="utf-8",newline="") as f: predictions=list(csv.DictReader(f))
        counts={"records_imported":len(records),"records_removed_before_screening":sum(r["disposition"]!="keep" for r in dedup.values()),
                "reports_included":len(included),"studies_analyzed":study_count,"dose_categories":len(rows),"not_complete_prisma":True}
        (stage/"selection_counts.json").write_text(json.dumps(counts,indent=2)+"\n",encoding="utf-8")
        shutil.copyfile(a.category_review,stage/"category_review.csv")
        status="DRAFT_SYNTHETIC_OR_PACKAGE_EXAMPLE" if p["mode"]=="synthetic_test" else "DRAFT_EVIDENCE_RECORDED_NOT_FINAL"
        refs={r["record_id"]:r for r in records};used=[];sections=[]
        def add(text,style=None,figures=None,table=None):
            sections.append({"text":text,**({"style":style} if style else {}),**({"figures":figures} if figures else {}),**({"table":table} if table else {})})
        def prose(items):
            for entry in items:
                for rid in entry["record_ids"]:
                    if rid not in used:used.append(rid)
                cite=" ["+", ".join(str(used.index(rid)+1) for rid in entry["record_ids"])+"]" if p["mode"]=="real" and entry["record_ids"] else ""
                add(entry["text"]+cite)
        add(narrative["title"],"Title")
        add(status+": statistical facts and clinical meaning remain a human-reviewed draft.")
        add("Introduction","Heading1");prose(narrative["Introduction"])
        add("Methods","Heading1")
        add(f"Question: {p['question']} Population: {p['pico']['population']}. Exposure: {p['pico']['exposure']}. Comparator: {p['pico']['comparator']}. Outcome: {p['pico']['outcome']} at {p['analysis']['timepoint']}.")
        add(f"Eligible designs: {'; '.join(p['eligible_designs'])}. Search status: {p['search_status']}. The prespecified {p['analysis']['model']} two-stage REML model used dosresmeta {summary['dosresmeta_version']} with log RR and Greenland-Longnecker within-study covariance. Dose unit: {p['analysis']['dose_unit']}; reference: {p['analysis']['reference_dose']}; alpha: {p['analysis']['alpha']}; adjustment: {p['analysis']['adjustment']}.")
        add(f"Representative dose definition: {p['analysis']['dose_definition']}. Interior knots: {p['analysis'].get('knots',[])}; boundary knots: {p['analysis'].get('boundary_knots',[])}. Category bounds, open-end assignment rationale and source locators are retained per row; package examples do not independently verify published article extraction.")
        add("Results","Heading1")
        add(f"The local ledger contained {counts['records_imported']} records and {counts['reports_included']} included reports representing {study_count} independently labeled studies and {len(rows)} correlated dose categories. These counts do not establish a complete PRISMA search.",figures=[(1,"Dose-response model with confidence limits; dose in "+p['analysis']['dose_unit'],stats/"dose_curve.png")])
        if p["mode"]=="real":
            for m in mapping:
                if m["record_id"] not in used:used.append(m["record_id"])
            add("Included report sources: ["+", ".join(str(used.index(m["record_id"])+1) for m in mapping)+"].")
        study_rows=[["Study","Reports","Dose categories","Risk judgment"]]
        risk={r["study_id"]:r["risk_of_bias_judgment"] for r in reviews}
        for sid in sorted(risk):
            study_rows.append([sid,", ".join(m["report_id"] for m in mapping if m["study_id"]==sid),str(sum(r["study_id"]==sid for r in rows)),risk[sid]])
        add("Reviewer-entered risk judgments are recorded with source basis in the category ledger, not independently adjudicated by software.",table={"title":"Table 1. Included dose study inputs","rows":study_rows})
        pred_rows=[["Dose ("+p["analysis"]["dose_unit"]+")","RR versus reference",f"{100*(1-float(p['analysis']['alpha'])):g}% CI"]]
        for r in predictions:
            pred_rows.append([f"{float(r['dose']):g}",f"{float(r['RR']):.3f}",f"{float(r['ci_lower']):.3f} to {float(r['ci_upper']):.3f}"])
        add("Model-based predictions at the prespecified doses; the reference RR is 1 by definition.",table={"title":"Table 2. Dose-response predictions","rows":pred_rows})
        add("Model coefficients on the log RR basis (spline terms are basis coefficients, not per-unit effects): "+"; ".join(f"{r['term']} {float(r['estimate']):.6f} ({float(r['ci_lower']):.6f} to {float(r['ci_upper']):.6f})" for r in coefs)+". "+f"Residual heterogeneity Q={float(summary['Q']):.3f}, df={summary['Q_df']}, p={float(summary['Q_p']):.3f}.")
        add("Discussion","Heading1");prose(narrative["Discussion"])
        add("Limitations","Heading1")
        add("The reconstructed category covariance depends on supplied cases, denominators, SEs and incidence type. Dose assignments, adjustment compatibility, shared cohorts, exposure comparability and risk of bias require source-level review. The spline form and knots are prespecified model choices, not evidence of a detected nonlinear association. Predictions outside observed doses are refused. Source hashes confirm local file consistency, not article authenticity or reviewer identity. This draft is not a clinical or causal conclusion.")
        add("References","Heading1")
        if p["mode"]=="real":
            for i,rid in enumerate(used,1):
                r=refs[rid];add(f"[{i}] {r['authors']}. {r['title']}. {r['year']}."+(f" doi:{r['doi']}" if r['doi'] else "")+(f" PMID:{r['pmid']}" if r['pmid'] else ""))
        else:add("Synthetic/package method example: no article bibliography or full-text verification is asserted.")
        document={"schema":"meta-dose-manuscript-v1","status":status,"final":False,"sections":[{k:v for k,v in s.items() if k!="figures"} for s in sections],
                  "fact_sources":{"confirmation_sha256":lit.sha256(receipt_path),"statistics_receipt_sha256":lit.sha256(stats/"dose_receipt.json"),"narrative_sha256":lit.sha256(a.narrative)}}
        (stage/"manuscript.json").write_text(json.dumps(document,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        def markdown(item):
            text=("# " if item.get("style")=="Title" else "## " if item.get("style")=="Heading1" else "")+item["text"]
            if item.get("table"):
                rr=item["table"]["rows"]
                text+="\n\n"+item["table"]["title"]+"\n\n"+" | ".join(rr[0])+"\n"+" | ".join("---" for _ in rr[0])
                text+="\n"+"\n".join(" | ".join(str(c).replace("|","/") for c in row) for row in rr[1:])
            return text
        (stage/"manuscript.md").write_text("\n\n".join(markdown(s) for s in sections)+"\n",encoding="utf-8")
        diagnostic_word.write(stage/"manuscript.docx",sections,[(1,"dose-response",stats/"dose_curve.png")])
        (stage/"status.json").write_text(json.dumps({"status":status,"final":False,"human_identity_authenticated":False,"word_visual_reviewed":False,"source_meaning_verified_by_software":False},indent=2)+"\n",encoding="utf-8")
        files={str(path.relative_to(stage)).replace("\\","/"):lit.sha256(path) for path in stage.rglob("*") if path.is_file()}
        (stage/"manifest.json").write_text(json.dumps({"schema":"meta-dose-draft-manifest-v1","files":files},indent=2)+"\n",encoding="utf-8")
        os.replace(stage,out)
    print(status,out)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command",choices=("confirm","build"))
    for name in CORE:parser.add_argument("--"+name.replace("_","-"),required=True)
    parser.add_argument("--confirmation");parser.add_argument("--narrative");parser.add_argument("--rscript")
    parser.add_argument("--out",required=True)
    args=parser.parse_args()
    try:
        if args.command=="confirm":confirm(args)
        else:
            if not all((args.confirmation,args.narrative,args.rscript)):lit.fail("dose build needs confirmation, narrative and Rscript")
            build(args)
    except (OSError,ValueError,KeyError,TypeError,json.JSONDecodeError,csv.Error) as error:
        parser.exit(2,f"Validation: {error}\n")
