"""Bind external RoB 2/ROBINS-I result references to checked intervention method drafts.

This adapter reuses the pairwise binder's tool/version and assessment contract.
It does not reproduce questionnaires, branching rules or official scoring.
Only network and sparse-event intervention drafts are supported here.
"""
import argparse
import csv
from datetime import date
import json
import os
from pathlib import Path
import tempfile

import diagnostic_word
import literature as lit
import method_sof
import official_rob_binding as official

DESIGN_FIELDS=("study_id","record_id","design_type","tool","version","effect_of_interest",
               "source_file","source_sha256","source_locator","reviewer","reviewed_at")
FAMILIES={"network":"transitivity_evidence.csv","rare":"study_review.csv"}
JUDGMENTS={"RoB 2":{"low","some_concerns","high"},
           "ROBINS-I":{"low","moderate","serious","critical","no_information"}}


def fail(message):raise ValueError(message)
def load(path):return json.loads(Path(path).read_text(encoding="utf-8"))
def rows(path,fields):
    result,_=lit.read_csv(path,fields)
    if any(None in r or any(r.get(k) is None for k in fields) for r in result):
        fail("truncated or extra assessment/design CSV fields")
    return result
def source(path,digest,label):official.source(Path(path),digest,label)


def checked(paper_dir,confirmation_path,design_path,assessment_path,mode):
    paper=Path(paper_dir).resolve();confirmation=Path(confirmation_path).resolve()
    doc=load(paper/"manuscript.json")
    schema=doc.get("schema")
    family={"meta-network-manuscript-v1":"network","meta-rare-event-manuscript-v1":"rare"}.get(schema)
    if not family:fail("external intervention RoB supports network and rare-event manuscripts only")
    _,_,plan,_,manifest_sha,confirmation_sha=method_sof.checked_paper(paper,family)
    source(confirmation,confirmation_sha,"method confirmation")
    claim=load(confirmation)
    if claim.get("schema")!=("meta-network-confirmation-v1" if family=="network" else "meta-rare-event-confirmation-v1"):
        fail("confirmation schema differs from method manuscript")
    synthetic=doc.get("status")=="DRAFT_SYNTHETIC"
    if doc.get("final") is not False or mode not in {"synthetic_test","reviewer_declared"} or \
            synthetic!=(mode=="synthetic_test"):
        fail("external assessment mode differs from non-final method manuscript")
    inputs=claim["input_paths"]
    study_rows=rows(inputs["input"],("study_id","record_id","source_file","source_sha256","source_location"))
    source_by_record={};record_by_study={}
    input_dir=Path(inputs["input"]).resolve().parent
    for r in study_rows:
        sid=r["study_id"]
        linked=Path(r["source_file"])
        linked=(linked if linked.is_absolute() else input_dir/linked).resolve()
        source_by_record.setdefault((sid,r["record_id"]),set()).add((str(linked),r["source_sha256"].lower()))
        record_by_study.setdefault(sid,set()).add(r["record_id"])
    review_key="status" if family=="network" else "review_status"
    ledger_fields=("study_id",review_key,"source_file","source_sha256",
        "risk_of_bias_judgment" if family=="network" else "risk_judgment")
    if family=="rare":ledger_fields+=("risk_tool",)
    ledger=rows(paper/FAMILIES[family],ledger_fields)
    if len({r["study_id"] for r in ledger})!=len(ledger) or set(record_by_study)!={r["study_id"] for r in ledger}:
        fail("method risk ledger and analyzed study set differ")
    status_key="risk_of_bias_judgment" if family=="network" else "risk_judgment"
    ledger_by={r["study_id"]:r for r in ledger}
    if mode=="reviewer_declared" and any(r[review_key]!=("human_assessed" if family=="network" else "human_reviewed_claim") for r in ledger):
        fail("real external binding needs completed human-reviewed method risk ledger")
    design_path=Path(design_path).resolve();assessment_path=Path(assessment_path).resolve()
    designs=rows(design_path,DESIGN_FIELDS);assessments=rows(assessment_path,official.FIELDS)
    if len(designs)!=len(ledger) or len(assessments)!=len(ledger) or \
            {r["study_id"] for r in designs}!={r["study_id"] for r in ledger} or \
            {r["study_id"] for r in assessments}!={r["study_id"] for r in ledger}:
        fail("one design and one external assessment reference per analyzed study required")
    if len({r["study_id"] for r in designs})!=len(designs) or len({r["study_id"] for r in assessments})!=len(assessments):
        fail("duplicate study design or assessment")
    by_design={r["study_id"]:r for r in designs};selected=[]
    for n,row in enumerate(assessments,2):
        sid=row["study_id"];design=by_design[sid]
        common=("record_id","tool","version","effect_of_interest")
        if any(row[k]!=design[k] for k in common) or row["record_id"] not in record_by_study[sid]:
            fail(f"row {n}: assessment study/record/tool differs from sourced design")
        if (design["design_type"],row["tool"],row["version"]) not in official.TOOLS or \
                row["effect_of_interest"] not in official.TOOLS[(design["design_type"],row["tool"],row["version"])]:
            fail(f"row {n}: official intervention tool/version/effect does not fit design")
        if row["overall_judgment"] not in JUDGMENTS[row["tool"]] or \
                row["overall_judgment"]!=ledger_by[sid][status_key]:
            fail(f"row {n}: external overall judgment conflicts with method risk ledger or tool categories")
        if family=="rare" and ledger_by[sid]["risk_tool"]!=row["tool"]:
            fail(f"row {n}: external tool conflicts with method risk ledger")
        if row["completion_declaration"]!="reviewer_declares_completed" or \
                any(not row[k].strip() for k in ("assessment_locator","reviewer")):
            fail(f"row {n}: completed external assessment reference/reviewer required")
        if mode=="reviewer_declared" and any(str(x).startswith("AGENT_") for x in (row["reviewer"],design["reviewer"])):
            fail(f"row {n}: Agent cannot be a formal external reviewer")
        for label,value in (("assessment date",row["assessed_at"]),("design date",design["reviewed_at"])):
            try:date.fromisoformat(value)
            except ValueError:fail(f"row {n}: {label} needs YYYY-MM-DD")
        src=Path(design["source_file"]);src=(src if src.is_absolute() else design_path.parent/src).resolve()
        if (str(src),design["source_sha256"].lower()) not in source_by_record[(sid,row["record_id"])] or \
                not all(design[k].strip() for k in ("source_locator","reviewer")):
            fail(f"row {n}: study design lacks linked analyzed-source evidence")
        source(src,design["source_sha256"],f"row {n} design source")
        form=Path(row["assessment_file"]);form=(form if form.is_absolute() else assessment_path.parent/form).resolve()
        if form.suffix.lower() not in {".docx",".xlsx",".pdf",".csv"}:
            fail(f"row {n}: external assessment file type unsupported")
        source(form,row["assessment_sha256"],f"row {n} external assessment")
        selected.append({**row,"assessment_file":str(form),"assessment_sha256":row["assessment_sha256"].lower(),
            "design_type":design["design_type"],"design_source":str(src),"design_source_sha256":design["source_sha256"].lower(),
            "design_locator":design["source_locator"]})
    if plan["outcome"]!=load(inputs["protocol"])["analysis"]["outcome"] or \
            plan["timepoint"]!=load(inputs["protocol"])["analysis"]["timepoint"]:
        fail("method outcome/timepoint differs from confirmed protocol")
    return paper,confirmation,manifest_sha,family,plan,selected,design_path,assessment_path,mode


def build(paper,confirmation,designs,assessments,mode,out):
    paper,confirmation,manifest_sha,family,plan,data,designs,assessments,mode=checked(
        paper,confirmation,designs,assessments,mode)
    target=Path(out).resolve()
    if target.exists():fail("output exists; choose a fresh directory")
    target.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".method-rob-",dir=target.parent) as tmp:
        stage=Path(tmp)/"result";stage.mkdir()
        cols=official.FIELDS+("design_type","design_source","design_source_sha256","design_locator")
        lit.write_csv(stage/"method_rob_assessments.csv",cols,data)
        warning="Externally supplied intervention-tool results; questionnaire completion, official algorithm and clinical judgment are not verified. Reviewer identity is self-declared."
        lines=["# External intervention RoB binding — non-final","",f"Method: {family}; outcome: {plan['outcome']}; timepoint: {plan['timepoint']}; mode: {mode}.",warning,"",
               "| Study / record | Tool/version | Effect of interest | Supplied overall | Assessment and source |",
               "|---|---|---|---|---|"]
        for r in data:
            lines.append("| "+" | ".join((r["study_id"]+" / "+r["record_id"],r["tool"]+" "+r["version"],
                r["effect_of_interest"],r["overall_judgment"],r["assessment_file"]+" ["+r["assessment_locator"]+"]"))+" |")
        (stage/"method_rob_binding.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
        table=[["Study / record","Tool / version","Supplied overall","Assessment locator"]]
        table += [[r["study_id"]+" / "+r["record_id"],r["tool"]+" "+r["version"],
                   r["overall_judgment"],r["assessment_locator"]] for r in data]
        diagnostic_word.write(stage/"method_rob_binding.docx",[
            {"text":"External intervention RoB references — non-final","style":"Title"},
            {"text":plan["outcome"]+" at "+plan["timepoint"]+". "+warning},
            {"text":"Sourced study/result links","table":{"title":"Reviewer supplied; exact sources and hashes in CSV","rows":table}}],[])
        receipt={"schema":"meta-method-rob-binding-v1","status":"SYNTHETIC_EXTERNAL_REFERENCE" if mode=="synthetic_test" else
            "REVIEWER_DECLARED_EXTERNAL_REFERENCE_NOT_ALGORITHM_VERIFIED","final":False,"official_algorithm_applied":False,
            "official_questionnaire_checked":False,"identity_authenticated":False,"method":family,"mode":mode,
            "outcome":plan["outcome"],"timepoint":plan["timepoint"],"study_count":len(data),
            "paper_dir":str(paper),"paper_manifest_sha256":manifest_sha,"confirmation":str(confirmation),
            "confirmation_sha256":lit.sha256(confirmation),"designs":str(designs),"designs_sha256":lit.sha256(designs),
            "assessments":str(assessments),"assessments_sha256":lit.sha256(assessments),
            "external_sources":{r["assessment_file"]:r["assessment_sha256"] for r in data},
            "outputs":{p.name:lit.sha256(p) for p in stage.iterdir() if p.is_file()}}
        (stage/"method_rob_receipt.json").write_text(json.dumps(receipt,indent=2)+"\n",encoding="utf-8")
        os.replace(stage,target)
    print(receipt["status"],family,len(data),"studies",target)


def verify(path):
    root=Path(path).resolve();receipt=load(root/"method_rob_receipt.json")
    if receipt.get("schema")!="meta-method-rob-binding-v1" or receipt.get("final") is not False:
        fail("method RoB receipt invalid")
    source(Path(receipt["paper_dir"])/"manifest.json",receipt["paper_manifest_sha256"],"method manuscript")
    for key,label in (("confirmation","confirmation"),("designs","designs"),("assessments","assessments")):
        source(receipt[key],receipt[key+"_sha256"],label)
    _,_,_,family,plan,data,_,_,mode=checked(receipt["paper_dir"],receipt["confirmation"],
        receipt["designs"],receipt["assessments"],receipt["mode"])
    expected="SYNTHETIC_EXTERNAL_REFERENCE" if mode=="synthetic_test" else "REVIEWER_DECLARED_EXTERNAL_REFERENCE_NOT_ALGORITHM_VERIFIED"
    if receipt["status"]!=expected or (receipt["method"],receipt["outcome"],receipt["timepoint"],receipt["study_count"])!=\
            (family,plan["outcome"],plan["timepoint"],len(data)):
        fail("method RoB receipt status/outcome/studies changed")
    if receipt["external_sources"]!={r["assessment_file"]:r["assessment_sha256"] for r in data}:
        fail("external RoB source list changed")
    for name,digest in receipt["outputs"].items():source(root/name,digest,"method RoB output "+name)
    print("METHOD_ROB_BINDING_VERIFIED",family,root)
    return receipt


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest="command",required=True)
    b=sub.add_parser("build")
    for key in ("paper","confirmation","designs","assessments","mode","out"):
        b.add_argument("--"+key,required=True)
    v=sub.add_parser("verify");v.add_argument("--out",required=True)
    a=p.parse_args()
    try:
        if a.command=="build":build(a.paper,a.confirmation,a.designs,a.assessments,a.mode,a.out)
        else:verify(a.out)
    except (OSError,ValueError,KeyError,TypeError,json.JSONDecodeError,csv.Error) as exc:
        p.exit(2,"Validation: "+str(exc)+"\n")
