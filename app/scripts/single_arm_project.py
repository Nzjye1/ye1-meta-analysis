"""Single-group proportion/rate study review and evidence-bound Word draft."""
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
import single_arm

CORE=("protocol","records","dedup","decisions","report_map","input","study_review")
REVIEW_FIELDS=("study_id","record_id","review_status","reviewer","reviewed_at","risk_tool","risk_tool_version",
               "risk_judgment","risk_basis","source_file","source_sha256","source_location")


def protocol(path):
    p=shared.read_json(path)
    if p.get("schema")!="meta-single-arm-project-v1" or p.get("mode") not in {"synthetic_test","real"}:
        lit.fail("invalid single-group project schema/mode")
    for key in ("project_id","question","search_status"):
        if not shared.nonblank(p.get(key)):lit.fail(f"single-group protocol needs {key}")
    pico=p.get("pico",{})
    if any(not shared.nonblank(pico.get(k)) for k in ("population","condition","outcome","timepoint")):
        lit.fail("single-group PICO needs population, condition, outcome and timepoint")
    if not isinstance(p.get("eligible_designs"),list) or not p["eligible_designs"] or not all(map(shared.nonblank,p["eligible_designs"])):
        lit.fail("single-group eligible designs required")
    analysis=p.get("analysis",{});single_arm.plan_check(analysis)
    if any(analysis[k]!=pico[k] for k in ("population","outcome","timepoint")):
        lit.fail("single-group analysis differs from PICO")
    if p["mode"]=="real":
        if analysis["source_kind"]!="reviewed_extraction" or p["search_status"]=="complete_verified_by_software":
            lit.fail("real single-group project needs reviewed extraction and cannot assert software-verified complete search")
        approval=p.get("approval",{})
        if any(not shared.nonblank(approval.get(k)) for k in ("reviewer","reference","date","declaration")):
            lit.fail("real single-group project needs actual human approval declaration/reference/date")
        shared.date(approval["date"])
    elif analysis["source_kind"]!="synthetic_fixture":lit.fail("synthetic project needs synthetic data")
    return p


def checked(a):
    p=protocol(a.protocol)
    from dual_screen import verify_if_marked
    verify_if_marked(a.records,a.dedup,a.decisions)
    records,_=lit.read_csv(a.records,["record_id","title","authors","year","doi","pmid"])
    if len({r["record_id"] for r in records})!=len(records):lit.fail("repeated bibliography record ID")
    dedup=lit.load_dedup(records,a.dedup)
    active={rid for rid,r in dedup.items() if r["disposition"]=="keep"}
    decisions,_=lit.read_csv(a.decisions,["record_id","stage","decision","reason","reviewer","decision_date"])
    _,included=lit.validate_screening(records,decisions,active)
    mapping,_=lit.read_csv(a.report_map,["record_id","report_id","study_id"])
    if len(mapping)!=len(included) or {r["record_id"] for r in mapping}!=included or len({r["report_id"] for r in mapping})!=len(mapping):
        lit.fail("single-group report map needs each included report exactly once")
    study_by_record={r["record_id"]:r["study_id"] for r in mapping}
    rows=single_arm.table(a.input);count=single_arm.validate(p["analysis"],rows)
    if {r["study_id"] for r in rows}!=set(study_by_record.values()):lit.fail("single-group included/analyzed studies differ")
    review,_=lit.read_csv(a.study_review,REVIEW_FIELDS)
    if len(review)!=len(rows) or {r["study_id"] for r in review}!={r["study_id"] for r in rows}:
        lit.fail("single-group review needs one row per analyzed study")
    by_study={r["study_id"]:r for r in rows}
    expected="human_reviewed_claim" if p["mode"]=="real" else "synthetic_test"
    for r in review:
        original=by_study[r["study_id"]]
        if r["record_id"] not in study_by_record or study_by_record[r["record_id"]]!=r["study_id"]:
            lit.fail("single-group review report not included/mapped to study")
        if any(r[k]!=original[k] for k in ("source_file","source_sha256","source_location")):
            lit.fail("single-group review source differs from statistical input")
        if r["review_status"]!=expected or any(not shared.nonblank(r[k]) for k in ("reviewer","risk_tool","risk_tool_version","risk_basis")):
            lit.fail("single-group review status/reviewer/risk evidence missing or wrong mode")
        if r["risk_judgment"] not in {"low","some_concerns","high","unclear"}:
            lit.fail("single-group risk judgment invalid")
        shared.date(r["reviewed_at"])
        if p["mode"]=="real" and (r["risk_judgment"]=="unclear" or not re.search(r"(?i)(page|p\.|table|figure)\s*[A-Za-z0-9]",r["risk_basis"])):
            lit.fail("real single-group review needs located human risk basis")
    return p,records,dedup,included,mapping,rows,review,count


def hashes(a,rows):
    result={k:lit.sha256(getattr(a,k)) for k in CORE}
    for name in ("single_arm.py","single_arm.R","single_arm_project.py","diagnostic_project.py","diagnostic_word.py"):
        result[name]=lit.sha256(Path(__file__).with_name(name))
    result["source_bytes"]={str(Path(r["source_file"]).resolve()):r["source_sha256"] for r in rows}
    return result


def confirm(a):
    p,_,_,_,_,rows,_,_=checked(a)
    out=Path(a.out).resolve()
    if out.exists():lit.fail("single-group confirmation output exists")
    out.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".single-confirm-",dir=out.parent) as temp:
        stage=Path(temp)/"result";stage.mkdir()
        receipt={"schema":"meta-single-arm-confirmation-v1","mode":p["mode"],
                 "status":"SYNTHETIC_TEST_CONFIRMATION" if p["mode"]=="synthetic_test" else "HUMAN_APPROVAL_CLAIM_FILE_CONSISTENCY",
                 "approval":p.get("approval",{}),"input_paths":{k:str(Path(getattr(a,k)).resolve()) for k in CORE},
                 "hashes":hashes(a,rows),"human_identity_authenticated":False,"source_meaning_verified_by_software":False,"final_report":False}
        (stage/"single_confirmation.json").write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        os.replace(stage,out)
    print(receipt["status"],out)


def build(a):
    p,records,dedup,included,mapping,rows,review,count=checked(a)
    confirmation=Path(a.confirmation)/"single_confirmation.json";receipt=shared.read_json(confirmation)
    if receipt.get("schema")!="meta-single-arm-confirmation-v1" or receipt.get("mode")!=p["mode"] or receipt.get("input_paths")!={k:str(Path(getattr(a,k)).resolve()) for k in CORE} or receipt.get("hashes")!=hashes(a,rows):
        lit.fail("single-group confirmation stale or invalid")
    for path,digest in receipt["hashes"]["source_bytes"].items():
        if not Path(path).is_file() or lit.sha256(path)!=digest:lit.fail("single-group original source changed")
    narrative=shared.narrative_check(a.narrative,records,p["mode"])
    out=Path(a.out).resolve()
    if out.exists():lit.fail("single-group draft output exists")
    out.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".single-paper-",dir=out.parent) as temp:
        stage=Path(temp)/"result";stage.mkdir();stats=stage/"statistics";plan=stage/"analysis_plan.json"
        plan.write_text(json.dumps(p["analysis"],ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        single_arm.run(SimpleNamespace(input=a.input,plan=plan,rscript=a.rscript,out=stats))
        with (stats/"single_summary.csv").open(encoding="utf-8",newline="") as f:s=next(csv.DictReader(f))
        with (stats/"study_estimates.csv").open(encoding="utf-8",newline="") as f:estimates=list(csv.DictReader(f))
        counts={"records_imported":len(records),"records_removed_before_screening":sum(r["disposition"]!="keep" for r in dedup.values()),
                "reports_included":len(included),"studies_analyzed":count,"not_complete_prisma":True}
        (stage/"selection_counts.json").write_text(json.dumps(counts,indent=2)+"\n",encoding="utf-8")
        shutil.copyfile(a.study_review,stage/"study_review.csv")
        status="DRAFT_SYNTHETIC" if p["mode"]=="synthetic_test" else "DRAFT_EVIDENCE_RECORDED_NOT_FINAL"
        by_record={r["record_id"]:r for r in records};used=[];sections=[]
        def add(text,style=None,figures=None,table=None):
            sections.append({"text":text,**({"style":style} if style else {}),**({"figures":figures} if figures else {}),**({"table":table} if table else {})})
        def prose(items):
            for entry in items:
                for rid in entry["record_ids"]:
                    if rid not in used:used.append(rid)
                cite=" ["+", ".join(str(used.index(rid)+1) for rid in entry["record_ids"])+"]" if p["mode"]=="real" and entry["record_ids"] else ""
                add(entry["text"]+cite)
        add(narrative["title"],"Title");add(status+": statistical facts and clinical meaning require review.")
        add("Introduction","Heading1");prose(narrative["Introduction"])
        add("Methods","Heading1")
        add(f"Question: {p['question']} Population: {p['pico']['population']}. Condition: {p['pico']['condition']}. Outcome: {p['pico']['outcome']} at {p['pico']['timepoint']}.")
        add(f"Eligible designs: {'; '.join(p['eligible_designs'])}. Search status: {p['search_status']}. Raw unadjusted event counts were converted by metafor {s['metafor_version']} to {s['transformed_scale']} and pooled by inverse-variance {s['model']}; alpha {s['alpha']}. Denominator unit: {p['analysis']['denominator_unit']}; reporting unit: {s['display_unit']}.")
        add(f"Event definition: {p['analysis']['event_definition']}. Effect direction: {p['analysis']['effect_direction']}. Boundary zero/all-event proportions and zero-event rates are refused; no implicit continuity correction or p-value against a no-effect null was applied.")
        add("Results","Heading1")
        add(f"The local ledger had {counts['records_imported']} imported records, {counts['reports_included']} included reports and {count} independently labeled studies. This is a selection-count subset, not a complete PRISMA search.",figures=[(1,"Single-group estimates and pooled result; "+s['display_unit'],stats/"single_forest.png")])
        if p["mode"]=="real":
            for m in mapping:
                if m["record_id"] not in used:used.append(m["record_id"])
            add("Included report sources: ["+", ".join(str(used.index(m["record_id"])+1) for m in mapping)+"].")
        review_by={r["study_id"]:r for r in review}
        study_rows=[["Study","Events/denominator","Raw value","Risk judgment"]]
        for r in estimates:
            study_rows.append([r["study_id"],f"{float(r['events']):g}/{float(r['denominator']):g} {r['denominator_unit']}",
                               f"{float(r['raw_value']):.4f}",review_by[r["study_id"]]["risk_judgment"]])
        add("Raw study values are distinct from model estimates. Reviewer-entered risk judgments and their source basis are in the ledger; the software has not verified them.",table={"title":"Table 1. Included single-group studies","rows":study_rows})
        add(f"The pooled {s['display_unit']} was {float(s['pooled_display']):.4f} ({100*(1-float(s['alpha'])):g}% CI {float(s['ci_lower']):.4f} to {float(s['ci_upper']):.4f}); Q={float(s['Q']):.3f}, df={s['Q_df']}, I²={float(s['I2']):.1f}%. Tau²={float(s['tau2']):.6f} ({s['tau2_status']}).")
        add("Discussion","Heading1");prose(narrative["Discussion"])
        add("Limitations","Heading1")
        add("A pooled proportion is a fraction of people; a pooled incidence rate is events per specified person-time and can include recurrent events. They are not interchangeable. Event definitions, source extraction, cohort independence, case mix, ascertainment and risk of bias need human review. Source hashes confirm local bytes only. This draft does not establish a causal or clinical conclusion.")
        add("References","Heading1")
        if p["mode"]=="real":
            for i,rid in enumerate(used,1):
                r=by_record[rid];add(f"[{i}] {r['authors']}. {r['title']}. {r['year']}."+(f" doi:{r['doi']}" if r['doi'] else "")+(f" PMID:{r['pmid']}" if r['pmid'] else ""))
        else:add("Fully synthetic example; no real source bibliography is asserted.")
        doc={"schema":"meta-single-arm-manuscript-v1","status":status,"final":False,"sections":[{k:v for k,v in sec.items() if k!="figures"} for sec in sections],
             "fact_sources":{"confirmation_sha256":lit.sha256(confirmation),"statistics_receipt_sha256":lit.sha256(stats/"single_receipt.json"),"narrative_sha256":lit.sha256(a.narrative)}}
        (stage/"manuscript.json").write_text(json.dumps(doc,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        def markdown(sec):
            text=("# " if sec.get("style")=="Title" else "## " if sec.get("style")=="Heading1" else "")+sec["text"]
            if sec.get("table"):
                rr=sec["table"]["rows"]
                text+="\n\n"+sec["table"]["title"]+"\n\n"+" | ".join(rr[0])+"\n"+" | ".join("---" for _ in rr[0])
                text+="\n"+"\n".join(" | ".join(str(c).replace("|","/") for c in row) for row in rr[1:])
            return text
        (stage/"manuscript.md").write_text("\n\n".join(markdown(sec) for sec in sections)+"\n",encoding="utf-8")
        diagnostic_word.write(stage/"manuscript.docx",sections,[(1,"single-group",stats/"single_forest.png")])
        (stage/"status.json").write_text(json.dumps({"status":status,"final":False,"human_identity_authenticated":False,"word_visual_reviewed":False,"source_meaning_verified_by_software":False},indent=2)+"\n",encoding="utf-8")
        files={str(path.relative_to(stage)).replace("\\","/"):lit.sha256(path) for path in stage.rglob("*") if path.is_file()}
        (stage/"manifest.json").write_text(json.dumps({"schema":"meta-single-arm-draft-manifest-v1","files":files},indent=2)+"\n",encoding="utf-8")
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
            if not all((args.confirmation,args.narrative,args.rscript)):lit.fail("single-group build needs confirmation, narrative and Rscript")
            build(args)
    except (OSError,ValueError,KeyError,TypeError,json.JSONDecodeError,csv.Error) as error:parser.exit(2,f"Validation: {error}\n")
