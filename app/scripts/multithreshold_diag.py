"""Diagnostic meta-analysis of several ordered cutoffs per study via diagmeta."""
import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

FIELDS=("study_id","cohort_id","threshold","TP","FN","FP","TN","threshold_unit","index_test",
        "reference_standard","outcome","timepoint","case_design","source_file","source_sha256","source_location")


def fail(message):raise ValueError(message)


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def table(path):
    with Path(path).open(encoding="utf-8-sig",newline="") as f:
        reader=csv.DictReader(f)
        if reader.fieldnames is None or any(k not in reader.fieldnames for k in FIELDS):fail("multithreshold input lacks required columns")
        rows=list(reader)
    if not rows:fail("multithreshold input empty")
    return rows


def number(value,label):
    try:v=float(value)
    except (ValueError,TypeError):fail(f"{label} must be numeric")
    if not math.isfinite(v) or abs(v)>1e12:fail(f"{label} must be finite and bounded")
    return v


def plan_check(p):
    if p.get("schema")!="meta-multithreshold-plan-v1" or p.get("source_kind") not in {"package_method_example","synthetic_fixture","reviewed_extraction"}:
        fail("invalid multithreshold plan schema/source kind")
    for key in ("threshold_unit","index_test","reference_standard","outcome","timepoint","case_design","effect_direction"):
        if not isinstance(p.get(key),str) or not p[key].strip():fail(f"multithreshold plan needs {key}")
    if p["case_design"] not in {"single_gate","two_gate","case_control","package_unspecified"} or (p["source_kind"]=="reviewed_extraction" and p["case_design"]=="package_unspecified"):
        fail("case design must be explicit; package_unspecified cannot describe real extraction")
    if p.get("positive_direction")!="higher_value_positive":fail("diagmeta route requires higher biomarker values to mean positive test")
    if p.get("model")!="CICS" or p.get("distribution")!="logistic" or p.get("equal_variance") is not False or p.get("method_weights")!="invvar":
        fail("this route fixes documented CICS logistic unequal-variance inverse-variance model")
    if p.get("continuity_increment")!=.5:fail("explicit diagmeta continuity increment 0.5 required")
    if not isinstance(p.get("log_cutoff"),bool):fail("log_cutoff must be explicit boolean")
    alpha=number(p.get("alpha"),"alpha");weight=number(p.get("lambda_sensitivity"),"lambda_sensitivity")
    if not 0<alpha<.5 or not 0<=weight<=1:fail("invalid alpha or sensitivity weight")
    grid=p.get("prediction_cutoffs")
    if not isinstance(grid,list) or not 2<=len(grid)<=100:fail("prediction_cutoffs needs 2-100 values")
    grid=[number(v,"prediction cutoff") for v in grid]
    if len(set(grid))!=len(grid) or (p["log_cutoff"] and any(v<=0 for v in grid)):
        fail("prediction cutoffs must be distinct and positive for log cutoff")
    if p["source_kind"]=="reviewed_extraction" and p.get("review_status")!="human_reviewed_claim":
        fail("real multithreshold data need human-reviewed claim")
    return grid


def validate(p,rows):
    grid=plan_check(p);studies={};cohorts={};warning=[]
    for i,r in enumerate(rows,2):
        if any(r.get(k) is None or not str(r[k]).strip() for k in FIELDS):fail(f"multithreshold row {i} blank required field")
        if any(r[k]!=p[k] for k in ("threshold_unit","index_test","reference_standard","outcome","timepoint","case_design")):
            fail(f"multithreshold row {i} mixes test/standard/condition/time/unit/design")
        r["threshold"]=number(r["threshold"],f"row {i} threshold")
        if p["log_cutoff"] and r["threshold"]<=0:fail(f"row {i} cutoff must be positive when logged")
        for key in ("TP","FN","FP","TN"):
            if not re.fullmatch(r"\d+",str(r[key]).strip()):fail(f"row {i} {key} must be a nonnegative whole count")
            r[key]=int(r[key])
        if r["TP"]+r["FN"]<=0 or r["FP"]+r["TN"]<=0:fail(f"row {i} diseased/non-diseased denominators invalid")
        source=Path(r["source_file"]).resolve()
        pattern=(r"dataset row \d+" if p["source_kind"]=="package_method_example" else
                 r"synthetic row \d+" if p["source_kind"]=="synthetic_fixture" else
                 r"(?i)(?:page|p\.|table|figure)\s*[A-Za-z0-9]")
        if not source.is_file() or sha(source)!=r["source_sha256"] or not re.search(pattern,r["source_location"]):
            fail(f"row {i} local source missing, changed or unlocated")
        sid,cid=r["study_id"],r["cohort_id"]
        if cid in cohorts and cohorts[cid]!=sid:fail("one cohort under different study IDs")
        cohorts[cid]=sid
        s=studies.setdefault(sid,{"cohort":cid,"rows":[]})
        if s["cohort"]!=cid:fail(f"study {sid} mixes cohorts")
        s["rows"].append(r)
    if len(studies)<3 or sum(len(s["rows"])>=2 for s in studies.values())<2:
        fail("multithreshold model needs at least three labeled studies and two with multiple cutoffs")
    for sid,s in studies.items():
        rr=sorted(s["rows"],key=lambda r:r["threshold"])
        if len({r["threshold"] for r in rr})!=len(rr):fail(f"study {sid} has repeated cutoff")
        if any(a["TP"]<b["TP"] or a["FP"]<b["FP"] for a,b in zip(rr,rr[1:])):
            fail(f"study {sid} violates higher-threshold monotonicity")
        diseased={r["TP"]+r["FN"] for r in rr};nondiseased={r["FP"]+r["TN"] for r in rr}
        if len(diseased)>1 or len(nondiseased)>1:
            if p["source_kind"]!="package_method_example":fail(f"study {sid} changes disease-group totals across cutoffs")
            warning.append(sid)
    observed=[r["threshold"] for r in rows]
    if min(grid)<min(observed) or max(grid)>max(observed):fail("prediction cutoffs extrapolate beyond observed values")
    return len(studies),sum(len(s["rows"])>=2 for s in studies.values()),sorted(warning),grid


def run(a):
    p=json.loads(Path(a.plan).read_text(encoding="utf-8"));rows=table(a.input)
    count,multi,warnings,grid=validate(p,rows)
    out=Path(a.out).resolve()
    if out.exists():fail("multithreshold output exists")
    binary=shutil.which(a.rscript) or str(Path(a.rscript).resolve())
    if not Path(binary).is_file():fail("Rscript missing")
    out.parent.mkdir(parents=True,exist_ok=True);script=Path(__file__).with_suffix(".R")
    with tempfile.TemporaryDirectory(prefix=".multithreshold-",dir=out.parent) as temp:
        stage=Path(temp)/"result";stage.mkdir();checked=stage/"checked_cutoffs.csv"
        with checked.open("w",encoding="utf-8",newline="") as f:
            w=csv.DictWriter(f,fieldnames=FIELDS);w.writeheader();w.writerows({k:r[k] for k in FIELDS} for r in sorted(rows,key=lambda r:(r["study_id"],r["threshold"])))
        config=stage/"engine_plan.csv";scalar={k:v for k,v in p.items() if not isinstance(v,(list,dict))}
        scalar["prediction_cutoffs"]="|".join(str(v) for v in grid)
        scalar["inconsistent_total_studies"]="|".join(warnings)
        with config.open("w",encoding="utf-8",newline="") as f:
            w=csv.DictWriter(f,fieldnames=scalar);w.writeheader();w.writerow(scalar)
        proc=subprocess.run([binary,str(script),str(checked),str(config),str(stage)],capture_output=True,text=True)
        if proc.returncode:fail("diagmeta fit failed: "+(proc.stderr.strip() or proc.stdout.strip()))
        needed=("multithreshold_summary.csv","cutoff_predictions.csv","cutoff_trace.csv","sensspec_curve.png","sroc.png","fact_report.md")
        if any(not (stage/name).is_file() or (stage/name).stat().st_size==0 for name in needed):fail("diagmeta result incomplete")
        with (stage/"multithreshold_summary.csv").open(encoding="utf-8",newline="") as f:summary=list(csv.DictReader(f))
        if len(summary)!=1 or int(summary[0]["n_studies"])!=count or int(summary[0]["n_multicutoff_studies"])!=multi or summary[0]["fit_status"] not in {"converged_non_singular","converged_singular_boundary"} or summary[0]["optimizer_code"]!="0":
            fail("diagmeta study count or fit status invalid")
        receipt={"schema":"meta-multithreshold-result-v1","status":"PACKAGE_METHOD_EXAMPLE" if p["source_kind"]=="package_method_example" else "SYNTHETIC_FIXTURE" if p["source_kind"]=="synthetic_fixture" else "REVIEWED_EXTRACTION_CLAIM_NEEDS_REVIEW",
                 "final_report":False,"input_sha256":sha(a.input),"plan_sha256":sha(a.plan),"r_script_sha256":sha(script),
                 "fit_check_script_sha256":sha(script.with_name("diagmeta_fit_check.R")),
                 "fit_status":summary[0]["fit_status"],"singular_boundary":summary[0]["singular_boundary"]=="TRUE","optimizer_code":int(summary[0]["optimizer_code"]),
                 "package_example_inconsistent_totals":warnings,"source_files":sorted({(str(Path(r["source_file"]).resolve()),r["source_sha256"]) for r in rows}),
                 "outputs":{f.name:sha(f) for f in stage.iterdir() if f.is_file()}}
        (stage/"multithreshold_receipt.json").write_text(json.dumps(receipt,indent=2)+"\n",encoding="utf-8")
        os.replace(stage,out)
    print(receipt["status"],out)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ("input","plan","rscript","out"):parser.add_argument("--"+name,required=True)
    args=parser.parse_args()
    try:run(args)
    except (OSError,ValueError,KeyError,TypeError,json.JSONDecodeError,csv.Error) as error:parser.exit(2,f"Validation: {error}\n")
