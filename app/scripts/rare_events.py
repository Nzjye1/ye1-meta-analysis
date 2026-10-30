"""Source-checked rare-event two-arm MH analysis; numeric route, not a review confirmation."""
import argparse
import csv
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

import literature as lit

FIELDS=("record_id","study_id","cohort_id","events_t","n_t","events_c","n_c","outcome","timepoint",
        "contrast","population","scale_direction","source_file","source_sha256","source_location")


def checked_plan(path):
    p=json.loads(Path(path).read_text(encoding="utf-8"))
    return checked_plan_data(p)


def checked_plan_data(p):
    p=dict(p)
    if p.get("schema")!="meta-rare-event-analysis-v1" or p.get("source_kind") not in {"synthetic_fixture","reviewed_extraction"}:
        lit.fail("invalid rare-event plan/source kind")
    # Legacy v1 plans keep their numerical defaults. Normalize every layer into the receipt.
    p.setdefault("individual_effect_correction","half_all_cells_if_any_zero")
    p.setdefault("pooled_MH_correction","none")
    p.setdefault("double_zero_policy",p.get("double_boundary_policy","exclude_with_trace"))
    p.setdefault("double_boundary_policy",p["double_zero_policy"])
    p.setdefault("study_display_add",0.5)
    p.setdefault("cmh_test_correction",False)
    if p.get("effect_type") not in {"OR","RR"} or p.get("model")!="MH_fixed" or \
            p["double_zero_policy"]!="exclude_with_trace" or p["double_boundary_policy"]!=p["double_zero_policy"] or \
            p["study_display_add"]!=0.5 or p["individual_effect_correction"]!="half_all_cells_if_any_zero" or \
            p["pooled_MH_correction"] not in {"none","revman_0.5"} or \
            not isinstance(p["cmh_test_correction"],bool) or \
            not isinstance(p.get("peto_sensitivity"),bool):
        lit.fail("rare-event slice requires OR/RR MH fixed, exclude_with_trace, four-cell individual correction, and pooled_MH_correction none or revman_0.5")
    for key in ("outcome","timepoint","contrast","population","scale_direction"):
        if not isinstance(p.get(key),str) or not p[key].strip():lit.fail("rare-event plan needs "+key)
    if p["scale_direction"] not in {"event_adverse","event_benefit"}:lit.fail("event direction required")
    if p["peto_sensitivity"] and p["effect_type"]!="OR":lit.fail("Peto sensitivity is OR only")
    try:alpha=float(p["alpha"])
    except (ValueError,TypeError,KeyError):lit.fail("alpha invalid")
    if not 0<alpha<.5:lit.fail("alpha must lie between zero and .5")
    if p["source_kind"]=="reviewed_extraction" and p.get("review_status")!="human_reviewed_claim":
        lit.fail("real extraction needs explicit review status claim")
    return p


def checked_data(path,p):
    rows,_=lit.read_csv(path,FIELDS)
    if len(rows)<1 or len(rows)>200:lit.fail("rare-event analysis accepts 1-200 independent tables")
    ids=set();cohorts=set();records=set()
    for i,row in enumerate(rows,2):
        if any(not (row[k] or "").strip() for k in FIELDS):lit.fail(f"row {i}: blank required value")
        if row["study_id"] in ids or row["cohort_id"] in cohorts or row["record_id"] in records:
            lit.fail("repeated study, cohort or report; resolve dependent effects")
        ids.add(row["study_id"]);cohorts.add(row["cohort_id"]);records.add(row["record_id"])
        if any(row[k]!=p[k] for k in ("outcome","timepoint","contrast","population","scale_direction")):
            lit.fail(f"row {i}: plan outcome/timepoint/population/direction differs")
        for key in ("events_t","n_t","events_c","n_c"):
            if not row[key].isdigit():lit.fail(f"row {i}: {key} must be a nonnegative integer")
            row[key]=int(row[key])
        if row["n_t"]<=0 or row["n_c"]<=0 or row["events_t"]>row["n_t"] or row["events_c"]>row["n_c"]:
            lit.fail(f"row {i}: events exceed positive group totals")
        source=Path(row["source_file"]).resolve()
        locator=(r"(?i)(page|p\.|table|figure)\s*[A-Za-z0-9]" if p["source_kind"]=="reviewed_extraction"
                 else r"(?i)synthetic row\s*[A-Za-z0-9]")
        if not source.is_file() or lit.sha256(source)!=row["source_sha256"] or not re.search(locator,row["source_location"]):
            lit.fail(f"row {i}: source bytes or locator missing/changed")
    return rows


def run(a):
    p=checked_plan(a.plan);rows=checked_data(a.input,p)
    binary=shutil.which(a.rscript) or str(Path(a.rscript).resolve())
    if not Path(binary).is_file():lit.fail("Rscript missing")
    out=Path(a.out).resolve()
    if out.exists():lit.fail("rare-event output exists")
    out.parent.mkdir(parents=True,exist_ok=True)
    script=Path(__file__).with_suffix(".R")
    with tempfile.TemporaryDirectory(prefix=".rare-events-",dir=out.parent) as temp:
        stage=Path(temp)/"result";stage.mkdir()
        checked=stage/"checked_tables.csv";lit.write_csv(checked,FIELDS,sorted(rows,key=lambda row:row["study_id"]))
        engine=stage/"engine_plan.csv";lit.write_csv(engine,list(p),[p])
        child=subprocess.run([binary,str(script),str(checked),str(engine),str(stage)],capture_output=True,text=True)
        (stage/"engine_stdout.txt").write_text(child.stdout,encoding="utf-8")
        (stage/"engine_stderr.txt").write_text(child.stderr,encoding="utf-8")
        if child.returncode:lit.fail("rare-event metafor fit failed: "+(child.stderr.strip() or child.stdout.strip()))
        expected=("rare_summary.csv","study_trace.csv","rare_forest.png","fact_report.md",
                  "rare_leave_one_out.csv","rare_leave_one_out.png","engine_warnings.csv")
        if any(not (stage/name).is_file() or (stage/name).stat().st_size==0 for name in expected):
            lit.fail("rare-event output incomplete")
        summary,_=lit.read_csv(stage/"rare_summary.csv",("effect_type","k_identified","k_informative","mh_ratio","mh_ci_lower","mh_ci_upper"))
        if len(summary)!=1 or summary[0]["effect_type"]!=p["effect_type"] or int(summary[0]["k_identified"])!=len(rows):
            lit.fail("rare-event R result contradicts checked plan/input")
        audit=dict(schema="meta-rare-event-result-v1",status="SYNTHETIC_METHOD_DRAFT" if p["source_kind"]=="synthetic_fixture" else "REVIEWED_EXTRACTION_CLAIM_NEEDS_REVIEW",
            final=False,input_path=str(Path(a.input).resolve()),input_sha256=lit.sha256(a.input),
            plan_path=str(Path(a.plan).resolve()),plan_sha256=lit.sha256(a.plan),r_script_sha256=lit.sha256(script),
            resolved_plan=p,engine_command=[binary,str(script),str(checked),str(engine),str(stage)],
            engine_exit_code=child.returncode,
            source_files={str(Path(r["source_file"]).resolve()):r["source_sha256"] for r in rows},
            outputs={f.name:lit.sha256(f) for f in stage.iterdir() if f.is_file()})
        (stage/"rare_receipt.json").write_text(json.dumps(audit,indent=2)+"\n",encoding="utf-8")
        os.replace(stage,out)
    print(audit["status"],summary[0]["k_informative"],"informative",out)


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    for key in ("input","plan","rscript","out"):p.add_argument("--"+key,required=True)
    a=p.parse_args()
    try:run(a)
    except (OSError,ValueError,KeyError,TypeError) as exc:p.exit(2,"Validation: "+str(exc)+"\n")
