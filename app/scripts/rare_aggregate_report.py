"""Bound analysis report for supplied MH summary counts; no systematic-review approval claim."""
import argparse
import csv
import json
import os
from pathlib import Path
import shutil
import tempfile

import aggregate_workflow as aggregate
import diagnostic_word
import literature as lit

SCHEMA="meta-rare-aggregate-project-v1"


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def resolve(base,value):
    path=Path(aggregate.text(value,"path"))
    return (path if path.is_absolute() else base/path).resolve()


def bind_statistics(stats):
    receipt=load(stats/"rare_receipt.json")
    if receipt.get("schema")!="meta-rare-event-result-v1" or receipt.get("final") is not False:
        lit.fail("checked non-final MH result receipt required")
    if receipt.get("status") not in {"SYNTHETIC_METHOD_DRAFT","REVIEWED_EXTRACTION_CLAIM_NEEDS_REVIEW"}:
        lit.fail("unsupported MH source status")
    files={str(stats/"rare_receipt.json"):lit.sha256(stats/"rare_receipt.json")}
    for name,digest in receipt["outputs"].items():
        path=(stats/name).resolve()
        if not path.is_relative_to(stats) or not path.is_file() or lit.sha256(path)!=digest:
            lit.fail("MH result member missing or changed: "+name)
        files[str(path)]=digest
    for key in ("input","plan"):
        path=Path(receipt[key+"_path"])
        if not path.is_file() or lit.sha256(path)!=receipt[key+"_sha256"]:
            lit.fail("original MH "+key+" missing or changed")
        files[str(path)]=receipt[key+"_sha256"]
    for name,digest in receipt["source_files"].items():
        path=Path(name)
        if not path.is_file() or lit.sha256(path)!=digest:lit.fail("original MH source missing or changed")
        files[str(path)]=digest
    required=("rare_summary.csv","study_trace.csv","rare_forest.png","rare_leave_one_out.csv",
              "rare_leave_one_out.png","engine_warnings.csv","fact_report.md","engine_plan.csv")
    if any(name not in receipt["outputs"] for name in required):lit.fail("MH report needs current complete statistical outputs")
    import rare_events
    plan=rare_events.checked_plan_data(load(receipt["plan_path"]))
    if receipt.get("resolved_plan")!=plan:lit.fail("MH resolved plan contradicts original plan")
    summary=lit.read_csv(stats/"rare_summary.csv",("effect_type","pooled_MH_correction","individual_effect_correction","double_zero_policy"))[0]
    if len(summary)!=1 or any(summary[0][k]!=str(plan[k]) for k in ("effect_type","pooled_MH_correction","individual_effect_correction","double_zero_policy")):
        lit.fail("MH summary configuration differs from bound plan")
    return receipt,plan,summary[0],files


def validate(project):
    p=load(project)
    if p.get("schema")!=SCHEMA or p.get("mode")!="existing_summary_data" or "stages" in p:
        lit.fail("explicit MH aggregate schema / existing_summary_data without review stages required")
    for key in ("project_id","question","population","direction","independence_assumption"):
        aggregate.text(p.get(key),key)
    for key in ("citation","locator","supplied_data_description"):
        aggregate.text(p.get("source",{}).get(key),"source "+key)
    if p["source"].get("verification_status")!="not_independently_verified":
        lit.fail("source must remain not_independently_verified")
    unit=p.get("unit",{})
    if unit.get("status") not in {"reported","unverified"}:lit.fail("explicit unit status required")
    if unit["status"]=="reported":
        aggregate.text(unit.get("value"),"unit value");aggregate.text(unit.get("reference"),"unit reference")
    elif unit.get("value")!="":lit.fail("unverified unit value must remain empty")
    if not isinstance(p.get("limitations"),list) or not p["limitations"]:lit.fail("explicit limitations required")
    for v in p["limitations"]:aggregate.text(v,"limitation")
    original=p.get("original_inputs")
    if not isinstance(original,list) or not original:lit.fail("original_inputs required")
    stats=resolve(project.parent,p.get("statistics"))
    receipt,plan,summary,files=bind_statistics(stats)
    if p["population"]!=plan["population"]:lit.fail("project population differs from MH plan")
    files[str(project)]=lit.sha256(project)
    for name in original:
        path=resolve(project.parent,name)
        if not path.is_file():lit.fail("original supplied file missing")
        files[str(path)]=lit.sha256(path)
    if Path(receipt["input_path"]).resolve() not in {resolve(project.parent,x) for x in original}:
        lit.fail("original_inputs must include the MH count input")
    return p,stats,plan,summary,files


def verify(run):
    root=Path(run).resolve();binding=load(root/"report_binding.json")
    if binding.get("schema")!="meta-rare-aggregate-report-v1" or binding.get("mode")!="existing_summary_data":
        lit.fail("invalid MH aggregate report binding")
    for group in ("original_files","outputs"):
        for name,digest in binding[group].items():
            path=Path(name) if group=="original_files" else (root/name).resolve()
            if group=="outputs" and not path.is_relative_to(root):lit.fail("unsafe output member")
            if not path.is_file() or lit.sha256(path)!=digest:lit.fail(group+" member missing or changed: "+name)
    return binding


def run(a):
    if getattr(a,"resume",False):lit.fail("MH aggregate reporting requires a new output; resume unsupported")
    project=Path(a.project).resolve();p,stats,plan,s,files=validate(project)
    out=Path(a.out).resolve()
    if out.exists():lit.fail("report output exists; choose a fresh directory")
    out.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".mh-report-",dir=out.parent) as temp:
        stage=Path(temp)/"result";stage.mkdir();paper=stage/"paper";paper.mkdir()
        shutil.copytree(stats,stage/"statistics")
        (stage/"project.json").write_bytes(project.read_bytes())
        sections=[]
        def add(text,style=None,**kw):sections.append(dict(text=text,**({"style":style} if style else {}),**kw))
        def num(v):return format(float(v),".5g") if v else "not estimable or not applicable"
        def interval(row,prefix="mh"):
            return num(row[prefix+"_ratio"])+" ("+num(row[prefix+"_ci_lower"])+" to "+num(row[prefix+"_ci_upper"])+")"
        add("Supplied binary summary data analysis report","Title")
        add("DRAFT EXISTING SUMMARY DATA ANALYSIS NOT A NEW SYSTEMATIC REVIEW")
        add(aggregate.BOUNDARY)
        add("Question and source","Heading1")
        for key in ("question","population","direction","independence_assumption"):add(key+": "+p[key])
        for key in ("citation","locator","supplied_data_description","verification_status"):add(key+": "+p["source"][key])
        add("Outcome: "+plan["outcome"]+"; timepoint: "+plan["timepoint"]+"; contrast: "+plan["contrast"])
        add("Effect is a dimensionless "+plan["effect_type"]+". Source count denominator and source unit status: "+p["unit"]["status"]+"; "+(p["unit"]["value"] or "not independently verified")+". "+p["unit"].get("reference",""))
        add("Analysis configuration","Heading1")
        add("Fixed Mantel-Haenszel analysis of unadjusted independent arm counts. No statistical refit or model selection is performed by this report exporter.")
        for key in ("alpha","individual_effect_correction","individual_display_and_iv_correction","pooled_MH_correction","mh_zero_correction","double_zero_policy","cmh_test_correction","metafor_add","metafor_to","metafor_drop00","interval_method","mh_variance_method","R_version","metafor_version"):
            add(key+": "+s[key])
        add("RevMan-compatible correction is an explicit configuration, not evidence of the authors' original project. CMH correction is a test option, not the pooled RR switch.")
        add("Results","Heading1")
        add("Identified studies: "+s["k_identified"]+"; informative: "+s["k_informative"]+"; double-zero excluded: "+s["k_double_zero"]+"; double-all excluded: "+s["k_double_all"])
        add("Configured MH status: "+s["estimation_status"]+". "+s["effect_type"]+" "+interval(s)+"; confidence level "+str(100*(1-float(s["alpha"])))+"%; overall z-test p="+num(s["mh_p_value"]),figures=[(1,"Configured MH forest with individual correction stated",stage/"statistics/rare_forest.png")])
        add("Heterogeneity status: "+s["heterogeneity_status"]+"; Q="+num(s["Q"])+"; df="+num(s["Q_df"])+"; Q p="+num(s["Q_p"])+"; I2 percent="+num(s["I2_percent"])+". Q uses individual inverse-variance weights centered on configured MH, distinct from MH pooling weights. tau2 is assumed zero in a fixed model, not estimated absence of heterogeneity.")
        add("IV corrected sensitivity: "+interval(s,"iv_corrected")+". Peto: "+s["peto_status"]+"; "+s["peto_warning"])
        trace=lit.read_csv(stats/"study_trace.csv",("study_id","study_ratio","mh_weight_percent","q_iv_weight_percent"))[0]
        add("Study effects and distinct weights. Full source counts, hashes and exclusions remain in the local statistical trace.",table={"title":"Study estimates and weights","rows":[["Study","Individual ratio and CI","MH weight percent","Q IV weight percent"]]+[[r["study_id"],num(r["study_ratio"])+" ("+num(r["study_ci_lower"])+" to "+num(r["study_ci_upper"])+")",num(r["mh_weight_percent"]),num(r["q_iv_weight_percent"])] for r in trace]})
        loo=lit.read_csv(stats/"rare_leave_one_out.csv",("omitted_study","estimation_status","mh_ratio"))[0]
        add("Leave one out","Heading1")
        add("The configured method is held fixed. Single informative study heterogeneity is not applicable; unavailable MH intervals are never replaced by corrected individual display intervals.",table={"title":"Configured MH leave one out","rows":[["Omitted study","Configured ratio and CI","Status","Heterogeneity"]]+[[r["omitted_study"],interval(r),r["estimation_status"].replace("_"," ").lower(),r["heterogeneity_status"].replace("_"," ").lower()] for r in loo]},figures=[(2,"Leave one out configured MH",stage/"statistics/rare_leave_one_out.png")])
        add("Warnings and limitations","Heading1")
        with (stats/"engine_warnings.csv").open(encoding="utf-8-sig",newline="") as stream:
            reader=csv.DictReader(stream)
            if not {"context","kind","message"}.issubset(reader.fieldnames or []):lit.fail("engine warnings header invalid")
            warnings=list(reader)
        if not warnings:add("No engine conditions recorded. This does not establish source validity or clinical reliability.")
        for w in warnings:add(w["context"]+"; "+w["kind"]+": "+w["message"])
        for value in p["limitations"]:add(value)
        add("Binding and scope","Heading1");add("Original input, plan, source files and result hashes are bound in report_binding.json. Copied statistics remain byte-identical. Verification checks file binding, not clinical eligibility or source truth. No bibliography, screening record, review approval, PRISMA process, RoB or certainty judgment is created by this exporter.")
        diagnostic_word.write(paper/"manuscript.docx",sections,[(1,"MH forest",stage/"statistics/rare_forest.png"),(2,"MH leave one out",stage/"statistics/rare_leave_one_out.png")])
        text=[]
        for section in sections:
            text.append(section["text"])
            if "table" in section:
                text.extend(" | ".join(row) for row in section["table"]["rows"])
        (paper/"manuscript.md").write_text("\n\n".join(text)+"\n",encoding="utf-8")
        aggregate.dump(paper/"manuscript.json",dict(schema="meta-rare-aggregate-manuscript-v1",mode="existing_summary_data",final=False,sections=[{k:v for k,v in section.items() if k!="figures"} for section in sections]))
        aggregate.dump(stage/"workflow_receipt.json",dict(schema="meta-rare-aggregate-workflow-v1",status="COMPLETED",mode="existing_summary_data",final=False,statistics_refitted=False,word_visual_reviewed=False))
        binding=dict(schema="meta-rare-aggregate-report-v1",mode="existing_summary_data",final=False,original_files=files,outputs={str(f.relative_to(stage)).replace("\\","/"):lit.sha256(f) for f in stage.rglob("*") if f.is_file()})
        aggregate.dump(stage/"report_binding.json",binding)
        verify(stage);os.replace(stage,out)
    print("COMPLETED EXISTING_SUMMARY_DATA_MH_REPORT",out)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest="action",required=True)
    p=sub.add_parser("build");p.add_argument("--project",required=True);p.add_argument("--out",required=True)
    p=sub.add_parser("verify");p.add_argument("--run",required=True)
    a=parser.parse_args()
    try:
        if a.action=="verify":verify(a.run);print("VERIFIED MH_AGGREGATE_REPORT")
        else:run(a)
    except (OSError,ValueError,KeyError,TypeError) as exc:parser.exit(2,"Validation: "+str(exc)+"\n")
