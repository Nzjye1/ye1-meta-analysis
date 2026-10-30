"""Clustered-effect protocol, evidence ledger and CR2 Word draft."""
import argparse
import csv
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from types import SimpleNamespace

import dependent_effects as dep
import diagnostic_project as shared
import diagnostic_word
import literature as lit

CORE=("protocol","records","dedup","decisions","report_map","input","effect_review")
REVIEW_FIELDS=("study_id","effect_id","record_id","review_status","reviewer","reviewed_at","risk_tool","risk_tool_version",
               "risk_judgment","dependency_basis","source_file","source_sha256","source_location")


def protocol(path):
    p=shared.read_json(path)
    if p.get("schema")!="meta-dependent-project-v1" or p.get("mode") not in {"synthetic_test","real"}:
        lit.fail("invalid dependent project schema/mode")
    for k in ("project_id","question","search_status"):
        if not shared.nonblank(p.get(k)):lit.fail(f"dependent protocol needs {k}")
    pico=p.get("pico",{})
    if any(not shared.nonblank(pico.get(k)) for k in ("population","intervention","comparator","outcome")):
        lit.fail("dependent PICO needs population, intervention, comparator, outcome")
    if not isinstance(p.get("eligible_designs"),list) or not p["eligible_designs"] or not all(map(shared.nonblank,p["eligible_designs"])):
        lit.fail("dependent eligible designs needed")
    analysis=p.get("analysis",{});dep.plan_check(analysis)
    if pico["population"]!=analysis["population"] or pico["outcome"]!=analysis["outcome"] or pico["intervention"]+" vs "+pico["comparator"]!=analysis["contrast"]:
        lit.fail("dependent PICO differs from analysis population/outcome/contrast")
    if p["mode"]=="real":
        if analysis["source_kind"]!="reviewed_extraction" or p["search_status"]=="complete_verified_by_software":
            lit.fail("real dependent project needs reviewed extraction and no software-complete search claim")
        approval=p.get("approval",{})
        if any(not shared.nonblank(approval.get(k)) for k in ("reviewer","reference","date","declaration")):
            lit.fail("real dependent project needs human approval claim/reference/date")
        shared.date(approval["date"])
    elif analysis["source_kind"]!="synthetic_fixture":lit.fail("synthetic dependent project needs synthetic inputs")
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
        lit.fail("dependent report map needs each included report exactly once")
    study_by_record={r["record_id"]:r["study_id"] for r in mapping}
    rows=dep.table(a.input);count,_,_=dep.validate(p["analysis"],rows)
    if {r["study_id"] for r in rows}!=set(study_by_record.values()):lit.fail("dependent included/analyzed study sets differ")
    review,_=lit.read_csv(a.effect_review,REVIEW_FIELDS)
    by_effect={(r["study_id"],r["effect_id"]):r for r in rows}
    keys=[(r["study_id"],r["effect_id"]) for r in review]
    if len(keys)!=len(rows) or len(set(keys))!=len(keys) or set(keys)!=set(by_effect):
        lit.fail("dependent effect review needs exactly one row per effect")
    risk_by={};expected="human_reviewed_claim" if p["mode"]=="real" else "synthetic_test"
    for r in review:
        original=by_effect[(r["study_id"],r["effect_id"])]
        if r["record_id"] not in study_by_record or study_by_record[r["record_id"]]!=r["study_id"]:
            lit.fail("dependent effect report not included/mapped")
        if any(r[k]!=original[k] for k in ("source_file","source_sha256","source_location")):
            lit.fail("dependent effect review source mismatch")
        if r["review_status"]!=expected or any(not shared.nonblank(r[k]) for k in ("reviewer","risk_tool","risk_tool_version","dependency_basis")):
            lit.fail("dependent review status/reviewer/risk/dependency basis missing")
        if r["risk_judgment"] not in {"low","some_concerns","high","unclear"}:
            lit.fail("dependent risk judgment invalid")
        shared.date(r["reviewed_at"])
        if r["study_id"] in risk_by and risk_by[r["study_id"]]!=r["risk_judgment"]:lit.fail("one study has inconsistent risk judgments")
        risk_by[r["study_id"]]=r["risk_judgment"]
        if p["mode"]=="real" and (r["risk_judgment"]=="unclear" or not re.search(r"(?i)(page|p\.|table|figure)\s*[A-Za-z0-9]",r["dependency_basis"])):
            lit.fail("real dependent review needs located human dependency/risk basis")
    return p,records,dedup,included,mapping,rows,review,count


def hashes(a,rows):
    result={k:lit.sha256(getattr(a,k)) for k in CORE}
    for name in ("dependent_effects.py","dependent_effects.R","dependent_project.py","diagnostic_project.py","diagnostic_word.py"):
        result[name]=lit.sha256(Path(__file__).with_name(name))
    result["source_bytes"]={str(Path(r["source_file"]).resolve()):r["source_sha256"] for r in rows}
    return result


def confirm(a):
    p,_,_,_,_,rows,_,_=checked(a);out=Path(a.out).resolve()
    if out.exists():lit.fail("dependent confirmation output exists")
    out.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".dependent-confirm-",dir=out.parent) as temp:
        stage=Path(temp)/"result";stage.mkdir()
        receipt={"schema":"meta-dependent-confirmation-v1","mode":p["mode"],
                 "status":"SYNTHETIC_TEST_CONFIRMATION" if p["mode"]=="synthetic_test" else "HUMAN_APPROVAL_CLAIM_FILE_CONSISTENCY",
                 "approval":p.get("approval",{}),"input_paths":{k:str(Path(getattr(a,k)).resolve()) for k in CORE},
                 "hashes":hashes(a,rows),"human_identity_authenticated":False,"dependency_justification_verified_by_software":False,"final_report":False}
        (stage/"dependent_confirmation.json").write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        os.replace(stage,out)
    print(receipt["status"],out)


def build(a):
    p,records,dedup,included,mapping,rows,review,count=checked(a)
    confirmation=Path(a.confirmation)/"dependent_confirmation.json";receipt=shared.read_json(confirmation)
    if receipt.get("schema")!="meta-dependent-confirmation-v1" or receipt.get("mode")!=p["mode"] or receipt.get("input_paths")!={k:str(Path(getattr(a,k)).resolve()) for k in CORE} or receipt.get("hashes")!=hashes(a,rows):
        lit.fail("dependent confirmation stale or invalid")
    for path,digest in receipt["hashes"]["source_bytes"].items():
        if not Path(path).is_file() or lit.sha256(path)!=digest:lit.fail("dependent original source changed")
    narrative=shared.narrative_check(a.narrative,records,p["mode"]);out=Path(a.out).resolve()
    if out.exists():lit.fail("dependent draft output exists")
    out.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".dependent-paper-",dir=out.parent) as temp:
        stage=Path(temp)/"result";stage.mkdir();stats=stage/"statistics";plan=stage/"analysis_plan.json"
        plan.write_text(json.dumps(p["analysis"],ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        dep.run(SimpleNamespace(input=a.input,plan=plan,rscript=a.rscript,out=stats))
        with (stats/"dependent_results.csv").open(encoding="utf-8",newline="") as f:result=list(csv.DictReader(f))
        primary=next(r for r in result if r["primary"]=="TRUE")
        counts={"records_imported":len(records),"records_removed_before_screening":sum(r["disposition"]!="keep" for r in dedup.values()),
                "reports_included":len(included),"studies_analyzed":count,"correlated_effects":len(rows),"not_complete_prisma":True}
        (stage/"selection_counts.json").write_text(json.dumps(counts,indent=2)+"\n",encoding="utf-8")
        shutil.copyfile(a.effect_review,stage/"effect_review.csv")
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
        add(narrative["title"],"Title");add(status+": assumed dependence and interpretation require review.")
        add("Introduction","Heading1");prose(narrative["Introduction"])
        add("Methods","Heading1")
        add(f"Question: {p['question']} Population: {p['pico']['population']}. Comparison: {p['analysis']['contrast']}. Outcome: {p['analysis']['outcome']} at {p['analysis']['timepoint']}. Eligible designs: {'; '.join(p['eligible_designs'])}. Search status: {p['search_status']}.")
        add(f"The prespecified {p['analysis']['effect_type']} inputs used {p['analysis']['input_scale']} estimates and a common {p['analysis']['effect_unit']} unit/adjustment ({p['analysis']['adjustment']}). A nested study/effect random-intercept REML model used metafor {primary['metafor_version']}; cluster-robust CR2/Satterthwaite inference used clubSandwich {primary['clubSandwich_version']}. Alpha was {p['analysis']['alpha']}.")
        add(f"The working equicorrelation assumption was {p['analysis']['primary_rho']}, with prespecified sensitivity values {p['analysis']['rho_values']}. Reviewer-entered rationale: {p['analysis']['dependency_rationale']}. The working covariance is an assumption; the robust inference clusters by independent study.")
        add("Results","Heading1")
        add(f"The local ledger contained {counts['records_imported']} records, {counts['reports_included']} included reports, {count} study clusters and {len(rows)} related effects. These are a selection subset, not complete PRISMA accounting.",figures=[(1,"Related effects and primary robust estimate",stats/"dependent_forest.png")])
        if p["mode"]=="real":
            for m in mapping:
                if m["record_id"] not in used:used.append(m["record_id"])
            add("Included report sources: ["+", ".join(str(used.index(m["record_id"])+1) for m in mapping)+"].")
        risk={r["study_id"]:r["risk_judgment"] for r in review}
        study_rows=[["Study","Reports","Related effects","Risk judgment"]]
        for sid in sorted(risk):
            study_rows.append([sid,", ".join(m["report_id"] for m in mapping if m["study_id"]==sid),str(sum(r["study_id"]==sid for r in rows)),risk[sid]])
        add("The effect review ledger retains each source and dependence basis. Risk labels are reviewer claims, not automatic ratings.",table={"title":"Table 1. Related-effect study inputs","rows":study_rows})
        rows_rho=[["Assumed rho","Pooled "+p["analysis"]["effect_type"],f"{100*(1-float(p['analysis']['alpha'])):g}% CR2 CI","Satterthwaite df"]]
        for r in result:rows_rho.append([f"{float(r['rho']):.2f}"+(" (primary)" if r["primary"]=="TRUE" else ""),f"{float(r['display_estimate']):.3f}",f"{float(r['display_lower']):.3f} to {float(r['display_upper']):.3f}",f"{float(r['df_satterthwaite']):.2f}"])
        add("The pooled result changes with the assumed within-study sampling correlation; all sensitivity estimates and cluster degrees of freedom should be inspected.",figures=[(2,"Working-correlation sensitivity",stats/"rho_sensitivity.png")],table={"title":"Table 2. Correlation sensitivity","rows":rows_rho})
        add("Discussion","Heading1");prose(narrative["Discussion"])
        add("Limitations","Heading1")
        add("The sampling correlation is assumed, not recovered from source covariance. CR2 can be unstable with few independent clusters; the result table flags fewer than ten. Nested random effects do not make outcomes, adjustment models, repeated timepoints or overlapping cohorts exchangeable. Each source and common-construct decision needs human review. Local hashes are consistency checks, not identity or clinical verification. This draft is not a causal or final clinical conclusion.")
        add("References","Heading1")
        if p["mode"]=="real":
            for i,rid in enumerate(used,1):
                r=by_record[rid];add(f"[{i}] {r['authors']}. {r['title']}. {r['year']}."+(f" doi:{r['doi']}" if r['doi'] else "")+(f" PMID:{r['pmid']}" if r['pmid'] else ""))
        else:add("Fully synthetic example; no real article bibliography is asserted.")
        doc={"schema":"meta-dependent-manuscript-v1","status":status,"final":False,"sections":[{k:v for k,v in sec.items() if k!="figures"} for sec in sections],
             "fact_sources":{"confirmation_sha256":lit.sha256(confirmation),"statistics_receipt_sha256":lit.sha256(stats/"dependent_receipt.json"),"narrative_sha256":lit.sha256(a.narrative)}}
        (stage/"manuscript.json").write_text(json.dumps(doc,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        def markdown(sec):
            text=("# " if sec.get("style")=="Title" else "## " if sec.get("style")=="Heading1" else "")+sec["text"]
            if sec.get("table"):
                rr=sec["table"]["rows"];text+="\n\n"+sec["table"]["title"]+"\n\n"+" | ".join(rr[0])+"\n"+" | ".join("---" for _ in rr[0]);text+="\n"+"\n".join(" | ".join(str(c).replace("|","/") for c in row) for row in rr[1:])
            return text
        (stage/"manuscript.md").write_text("\n\n".join(markdown(sec) for sec in sections)+"\n",encoding="utf-8")
        diagnostic_word.write(stage/"manuscript.docx",sections,[(1,"dependent-forest",stats/"dependent_forest.png"),(2,"rho-sensitivity",stats/"rho_sensitivity.png")])
        (stage/"status.json").write_text(json.dumps({"status":status,"final":False,"human_identity_authenticated":False,"word_visual_reviewed":False,"dependency_justification_verified_by_software":False},indent=2)+"\n",encoding="utf-8")
        files={str(path.relative_to(stage)).replace("\\","/"):lit.sha256(path) for path in stage.rglob("*") if path.is_file()}
        (stage/"manifest.json").write_text(json.dumps({"schema":"meta-dependent-draft-manifest-v1","files":files},indent=2)+"\n",encoding="utf-8")
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
            if not all((args.confirmation,args.narrative,args.rscript)):lit.fail("dependent build needs confirmation, narrative and Rscript")
            build(args)
    except (OSError,ValueError,KeyError,TypeError,json.JSONDecodeError,csv.Error) as error:parser.exit(2,f"Validation: {error}\n")
