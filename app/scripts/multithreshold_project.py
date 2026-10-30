"""Several-cutoff diagnostic protocol, threshold review, quality evidence and Word draft."""
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
import literature as lit
import multithreshold_diag as multi

CORE=("protocol","records","dedup","decisions","report_map","input","threshold_review","quadas")
REVIEW_FIELDS=("study_id","threshold","record_id","TP","FN","FP","TN","status","reviewer","reviewed_at","source_file","source_sha256","source_location")
QUALITY_FIELDS=("study_id","domain","status","judgment","applicability","rationale","evidence_file","evidence_sha256","evidence_locator","reviewer","reviewed_at")


def protocol(path):
    p=shared.read_json(path)
    if p.get("schema")!="meta-multithreshold-project-v1" or p.get("mode") not in {"synthetic_test","real"}:
        lit.fail("invalid multithreshold project schema/mode")
    for key in ("project_id","question","threshold_rule","search_status"):
        if not shared.nonblank(p.get(key)):lit.fail(f"multithreshold protocol needs {key}")
    pico=p.get("pico",{})
    if any(not shared.nonblank(pico.get(k)) for k in ("population","index_test","reference_standard","target_condition")):
        lit.fail("diagnostic PICO needs population, index test, reference standard and target condition")
    if not isinstance(p.get("eligible_designs"),list) or not p["eligible_designs"] or not all(map(shared.nonblank,p["eligible_designs"])):
        lit.fail("eligible designs required")
    quality=p.get("quality_tool",{})
    if any(not shared.nonblank(quality.get(k)) for k in ("name","version","reference")):
        lit.fail("diagnostic quality tool name/version/reference required without bundled questionnaire")
    analysis=p.get("analysis",{});multi.plan_check(analysis)
    if analysis["index_test"]!=pico["index_test"] or analysis["reference_standard"]!=pico["reference_standard"] or analysis["outcome"]!=pico["target_condition"]:
        lit.fail("multithreshold analysis differs from PICO")
    if p["mode"]=="real":
        if analysis["source_kind"]!="reviewed_extraction" or p["search_status"]=="complete_verified_by_software":
            lit.fail("real multithreshold route needs reviewed extraction and no software-complete search claim")
        approval=p.get("approval",{})
        if any(not shared.nonblank(approval.get(k)) for k in ("reviewer","reference","date","declaration")):
            lit.fail("real multithreshold protocol needs human approval claim/reference/date")
        shared.date(approval["date"])
    elif analysis["source_kind"] not in {"synthetic_fixture","package_method_example"}:
        lit.fail("synthetic project needs synthetic/package method data")
    return p


def checked(a):
    p=protocol(a.protocol)
    from dual_screen import verify_if_marked
    verify_if_marked(a.records,a.dedup,a.decisions)
    records,_=lit.read_csv(a.records,["record_id","title","authors","year","doi","pmid"])
    if len({r["record_id"] for r in records})!=len(records):lit.fail("repeated bibliography record ID")
    dedup=lit.load_dedup(records,a.dedup);active={rid for rid,r in dedup.items() if r["disposition"]=="keep"}
    decisions,_=lit.read_csv(a.decisions,["record_id","stage","decision","reason","reviewer","decision_date"])
    _,included=lit.validate_screening(records,decisions,active)
    mapping,_=lit.read_csv(a.report_map,["record_id","report_id","study_id"])
    if len(mapping)!=len(included) or {r["record_id"] for r in mapping}!=included or len({r["report_id"] for r in mapping})!=len(mapping):
        lit.fail("multithreshold report map needs every included report exactly once")
    study_by_record={r["record_id"]:r["study_id"] for r in mapping}
    rows=multi.table(a.input)
    if "record_id" not in rows[0]:lit.fail("project cutoff input needs record_id")
    count,multi_count,warnings,_=multi.validate(p["analysis"],rows)
    if {r["study_id"] for r in rows}!=set(study_by_record.values()):lit.fail("included/analyzed multithreshold studies differ")
    for r in rows:
        if r["record_id"] not in study_by_record or study_by_record[r["record_id"]]!=r["study_id"]:
            lit.fail("cutoff row needs included report mapped to its study")
    reviews,_=lit.read_csv(a.threshold_review,REVIEW_FIELDS)
    keys=[(r["study_id"],multi.number(r["threshold"],"review cutoff")) for r in reviews]
    by_key={(r["study_id"],r["threshold"]):r for r in rows}
    if len(keys)!=len(rows) or len(set(keys))!=len(keys) or set(keys)!=set(by_key):
        lit.fail("threshold review needs exactly one row per study/cutoff")
    expected="human_verified" if p["mode"]=="real" else "synthetic_test"
    for r,key in zip(reviews,keys):
        original=by_key[key]
        if r["record_id"]!=original["record_id"] or any(r[k]!=original[k] for k in ("source_file","source_sha256","source_location")) or any(str(original[k])!=r[k] for k in ("TP","FN","FP","TN")):
            lit.fail("threshold review report/count/source differs from checked cutoff row")
        if r["status"]!=expected or not shared.nonblank(r["reviewer"]):lit.fail("cutoff review needs appropriate reviewer status")
        shared.date(r["reviewed_at"])
    votes,_=lit.read_csv(a.quadas,QUALITY_FIELDS)
    required={(sid,domain) for sid in {r["study_id"] for r in rows} for domain in shared.DOMAINS}
    found={(r["study_id"],r["domain"]) for r in votes}
    if len(found)!=len(votes) or found!=required:lit.fail("quality ledger needs exactly four domains per study")
    expected="human_assessed" if p["mode"]=="real" else "synthetic_test"
    for r in votes:
        if r["status"]!=expected or r["judgment"] not in {"low","high","unclear"} or r["applicability"] not in {"low","high","unclear","not_applicable"}:
            lit.fail("quality item needs mode-appropriate assessed judgment/applicability")
        if r["domain"]=="flow_timing" and r["applicability"]!="not_applicable":lit.fail("flow/timing applicability must be not_applicable")
        if any(not shared.nonblank(r[k]) for k in ("rationale","evidence_file","evidence_sha256","evidence_locator","reviewer","reviewed_at")):
            lit.fail("quality item needs evidence/reviewer/date")
        shared.date(r["reviewed_at"])
        source=Path(r["evidence_file"]).resolve()
        locator=r"(?i)(page|p\.|table|figure)\s*[A-Za-z0-9]" if p["mode"]=="real" else r"(?i)(synthetic row|dataset row|page|p\.|table|figure)\s*[A-Za-z0-9]"
        if not source.is_file() or lit.sha256(source)!=r["evidence_sha256"] or not re.search(locator,r["evidence_locator"]):
            lit.fail("quality evidence missing, changed or unlocated")
    return p,records,dedup,included,mapping,rows,reviews,votes,count,multi_count,warnings


def hashes(a,rows,votes):
    result={k:lit.sha256(getattr(a,k)) for k in CORE}
    for name in ("multithreshold_diag.py","multithreshold_diag.R","diagmeta_fit_check.R","multithreshold_project.py","diagnostic_project.py","diagnostic_word.py"):
        result[name]=lit.sha256(Path(__file__).with_name(name))
    result["source_bytes"]={str(Path(r["source_file"]).resolve()):r["source_sha256"] for r in rows}
    result["quality_evidence_bytes"]={str(Path(r["evidence_file"]).resolve()):r["evidence_sha256"] for r in votes}
    return result


def confirm(a):
    p,_,_,_,_,rows,_,votes,_,_,_=checked(a);out=Path(a.out).resolve()
    if out.exists():lit.fail("multithreshold confirmation output exists")
    out.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".multithreshold-confirm-",dir=out.parent) as temp:
        stage=Path(temp)/"result";stage.mkdir()
        receipt={"schema":"meta-multithreshold-confirmation-v1","mode":p["mode"],
                 "status":"SYNTHETIC_TEST_CONFIRMATION" if p["mode"]=="synthetic_test" else "HUMAN_APPROVAL_CLAIM_FILE_CONSISTENCY",
                 "approval":p.get("approval",{}),"input_paths":{k:str(Path(getattr(a,k)).resolve()) for k in CORE},
                 "hashes":hashes(a,rows,votes),"human_identity_authenticated":False,"quality_judgment_verified_by_software":False,"final_report":False}
        (stage/"multithreshold_confirmation.json").write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        os.replace(stage,out)
    print(receipt["status"],out)


def build(a):
    p,records,dedup,included,mapping,rows,reviews,votes,count,multi_count,warnings=checked(a)
    confirmation=Path(a.confirmation)/"multithreshold_confirmation.json";receipt=shared.read_json(confirmation)
    if receipt.get("schema")!="meta-multithreshold-confirmation-v1" or receipt.get("mode")!=p["mode"] or receipt.get("input_paths")!={k:str(Path(getattr(a,k)).resolve()) for k in CORE} or receipt.get("hashes")!=hashes(a,rows,votes):
        lit.fail("multithreshold confirmation stale or invalid")
    for path,digest in {**receipt["hashes"]["source_bytes"],**receipt["hashes"]["quality_evidence_bytes"]}.items():
        if not Path(path).is_file() or lit.sha256(path)!=digest:lit.fail("multithreshold original evidence changed")
    narrative=shared.narrative_check(a.narrative,records,p["mode"]);out=Path(a.out).resolve()
    if out.exists():lit.fail("multithreshold paper output exists")
    out.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".multithreshold-paper-",dir=out.parent) as temp:
        stage=Path(temp)/"result";stage.mkdir();stats=stage/"statistics";plan=stage/"analysis_plan.json"
        plan.write_text(json.dumps(p["analysis"],ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        multi.run(SimpleNamespace(input=a.input,plan=plan,rscript=a.rscript,out=stats))
        with (stats/"multithreshold_summary.csv").open(encoding="utf-8",newline="") as f:s=next(csv.DictReader(f))
        with (stats/"cutoff_predictions.csv").open(encoding="utf-8",newline="") as f:pred=list(csv.DictReader(f))
        counts={"records_imported":len(records),"records_removed_before_screening":sum(r["disposition"]!="keep" for r in dedup.values()),
                "reports_included":len(included),"studies_analyzed":count,"threshold_rows":len(rows),"studies_with_multiple_cutoffs":multi_count,"not_complete_prisma":True}
        (stage/"selection_counts.json").write_text(json.dumps(counts,indent=2)+"\n",encoding="utf-8")
        shutil.copyfile(a.threshold_review,stage/"threshold_review.csv");shutil.copyfile(a.quadas,stage/"quality_evidence.csv")
        status="DRAFT_SYNTHETIC_OR_PACKAGE_EXAMPLE" if p["mode"]=="synthetic_test" else "DRAFT_EVIDENCE_RECORDED_NOT_FINAL"
        by_record={r["record_id"]:r for r in records};used=[];sections=[]
        def add(text,style=None,figures=None,table=None):
            sections.append({"text":text,**({"style":style} if style else {}),**({"figures":figures} if figures else {}),**({"table":table} if table else {})})
        def prose(items):
            for entry in items:
                for rid in entry["record_ids"]:
                    if rid not in used:used.append(rid)
                cite=" ["+", ".join(str(used.index(rid)+1) for rid in entry["record_ids"])+"]" if p["mode"]=="real" and entry["record_ids"] else ""
                add(entry["text"]+cite)
        add(narrative["title"],"Title");add(status+": cutoff selection and clinical interpretation require human review.")
        add("Introduction","Heading1");prose(narrative["Introduction"])
        add("Methods","Heading1")
        add(f"Question: {p['question']} Population: {p['pico']['population']}. Index test: {p['pico']['index_test']}. Reference standard: {p['pico']['reference_standard']}. Target condition: {p['pico']['target_condition']} at {p['analysis']['timepoint']}. Eligible designs: {'; '.join(p['eligible_designs'])}. Search status: {p['search_status']}.")
        add(f"Cutoff rule: {p['threshold_rule']}. Higher marker values were predeclared positive. diagmeta {s['diagmeta_version']} fitted its CICS logistic unequal-variance multiple-cutoffs model with inverse-variance weights, log cutoff={s['log_cutoff']}, sensitivity weight lambda={s['lambda_sensitivity']}, continuity increment={s['continuity_increment']} and alpha={s['alpha']}. Multiple cutoffs from one study remained one correlated group.")
        add(f"Quality framework recorded by reviewer: {p['quality_tool']['name']} version {p['quality_tool']['version']} ({p['quality_tool']['reference']}). Four evidence-domain rows per study are retained; the software does not reproduce a questionnaire or determine bias judgments.")
        add("Results","Heading1")
        add(f"The local ledger had {counts['records_imported']} records, {counts['reports_included']} included reports, {count} labeled study groups and {len(rows)} cutoff rows; {multi_count} groups supplied multiple cutoffs. This is not a complete PRISMA flow.",figures=[(1,"Sensitivity and specificity across cutoffs",stats/"sensspec_curve.png")])
        if p["mode"]=="real":
            for m in mapping:
                if m["record_id"] not in used:used.append(m["record_id"])
            add("Included report sources: ["+", ".join(str(used.index(m["record_id"])+1) for m in mapping)+"].")
        study_rows=[["Study","Reports","Cutoffs","Quality rows"]]
        for sid in sorted({r["study_id"] for r in rows}):
            study_rows.append([sid,", ".join(m["report_id"] for m in mapping if m["study_id"]==sid),str(sum(r["study_id"]==sid for r in rows)),"4 reviewer-entered domains"])
        add("Study IDs label groups supplied to the model; hidden cohort overlap and quality judgments still need human assessment.",table={"title":"Table 1. Included diagnostic study groups","rows":study_rows})
        pred_rows=[["Cutoff ("+p["analysis"]["threshold_unit"]+")","Sensitivity","Specificity"]]
        for r in pred:pred_rows.append([f"{float(r['cutoff']):g}",f"{float(r['sensitivity']):.3f} ({float(r['sensitivity_lower']):.3f} to {float(r['sensitivity_upper']):.3f})",f"{float(r['specificity']):.3f} ({float(r['specificity_lower']):.3f} to {float(r['specificity_upper']):.3f})"])
        add("Predictions are restricted to observed cutoff range; table entries are model-based, not raw per-study ratios.",table={"title":"Table 2. Prespecified cutoff predictions","rows":pred_rows})
        add(f"The model-derived optimum for the declared lambda was {float(s['optimal_cutoff']):.2f} {s['threshold_unit']}, with sensitivity {float(s['sensitivity_optimal']):.3f} and specificity {float(s['specificity_optimal']):.3f}. This threshold has not been clinically validated.",figures=[(2,"Multiple-cutoffs summary ROC",stats/"sroc.png")])
        add(f"Model-fit diagnostics: lme4 optimizer code {s['optimizer_code']}; {s['fit_status']}. "+("This is a boundary (singular) fit; uncertainty and model assumptions require special review before interpretation." if s["singular_boundary"]=="TRUE" else "No singular boundary was reported by the underlying lme4 fit."))
        if warnings:add("PACKAGE METHOD DATA WARNING: disease-group totals change across cutoffs in labeled group(s) "+", ".join(warnings)+". The source data were not silently changed; this exception is unavailable for real analyses.")
        add("Discussion","Heading1");prose(narrative["Discussion"])
        add("Limitations","Heading1")
        add("The parametric cutoff-response model assumes comparable marker units, positive direction, reference standard, case design and study groups. The source-level totals, hidden participant overlap, bias, screening completeness and clinical threshold utility require human review. A model-derived optimum is not a recommendation to use that cutoff. Local hashes do not authenticate original papers or reviewer identities. This draft is not a final diagnostic review.")
        add("References","Heading1")
        if p["mode"]=="real":
            for i,rid in enumerate(used,1):
                r=by_record[rid];add(f"[{i}] {r['authors']}. {r['title']}. {r['year']}."+(f" doi:{r['doi']}" if r['doi'] else "")+(f" PMID:{r['pmid']}" if r['pmid'] else ""))
        else:add("Synthetic/package method example: no newly verified article bibliography is asserted.")
        document={"schema":"meta-multithreshold-manuscript-v1","status":status,"final":False,
                  "sections":[{k:v for k,v in sec.items() if k!="figures"} for sec in sections],
                  "fact_sources":{"confirmation_sha256":lit.sha256(confirmation),"statistics_receipt_sha256":lit.sha256(stats/"multithreshold_receipt.json"),"narrative_sha256":lit.sha256(a.narrative)}}
        (stage/"manuscript.json").write_text(json.dumps(document,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        def markdown(sec):
            text=("# " if sec.get("style")=="Title" else "## " if sec.get("style")=="Heading1" else "")+sec["text"]
            if sec.get("table"):
                rr=sec["table"]["rows"];text+="\n\n"+sec["table"]["title"]+"\n\n"+" | ".join(rr[0])+"\n"+" | ".join("---" for _ in rr[0]);text+="\n"+"\n".join(" | ".join(str(c).replace("|","/") for c in row) for row in rr[1:])
            return text
        (stage/"manuscript.md").write_text("\n\n".join(markdown(sec) for sec in sections)+"\n",encoding="utf-8")
        diagnostic_word.write(stage/"manuscript.docx",sections,[(1,"sensspec",stats/"sensspec_curve.png"),(2,"sroc",stats/"sroc.png")])
        (stage/"status.json").write_text(json.dumps({"status":status,"final":False,"human_identity_authenticated":False,"word_visual_reviewed":False,"cutoff_clinically_validated":False},indent=2)+"\n",encoding="utf-8")
        files={str(path.relative_to(stage)).replace("\\","/"):lit.sha256(path) for path in stage.rglob("*") if path.is_file()}
        (stage/"manifest.json").write_text(json.dumps({"schema":"meta-multithreshold-draft-manifest-v1","files":files},indent=2)+"\n",encoding="utf-8")
        os.replace(stage,out)
    print(status,out)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("command",choices=("confirm","build"))
    for name in CORE:parser.add_argument("--"+name.replace("_","-"),required=True)
    parser.add_argument("--confirmation");parser.add_argument("--narrative");parser.add_argument("--rscript")
    parser.add_argument("--out",required=True);args=parser.parse_args()
    try:
        if args.command=="confirm":confirm(args)
        else:
            if not all((args.confirmation,args.narrative,args.rscript)):lit.fail("multithreshold build needs confirmation, narrative and Rscript")
            build(args)
    except (OSError,ValueError,KeyError,TypeError,json.JSONDecodeError,csv.Error) as error:parser.exit(2,f"Validation: {error}\n")
