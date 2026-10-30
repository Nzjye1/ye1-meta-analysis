"""Clustered same-study effect meta-analysis with explicit working correlations."""
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

FIELDS=("study_id","cohort_id","effect_id","estimate","se","effect_type","outcome","timepoint","contrast",
        "adjustment","population","effect_unit","effect_definition","source_file","source_sha256","source_location")


def fail(msg):raise ValueError(msg)


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def table(path):
    with Path(path).open(encoding="utf-8-sig",newline="") as f:
        reader=csv.DictReader(f)
        if reader.fieldnames is None or any(k not in reader.fieldnames for k in FIELDS):fail("dependent-effect table lacks required fields")
        rows=list(reader)
    if not rows:fail("dependent-effect table empty")
    return rows


def number(value,label):
    try:v=float(value)
    except (ValueError,TypeError):fail(f"{label} must be numeric")
    if not math.isfinite(v) or abs(v)>1e12:fail(f"{label} must be finite and bounded")
    return v


def plan_check(p):
    if p.get("schema")!="meta-dependent-plan-v1" or p.get("source_kind") not in {"synthetic_fixture","reviewed_extraction"}:
        fail("invalid dependent-effect schema/source kind")
    if p.get("model")!="rma.mv_nested_REML_CR2" or p.get("effect_type") not in {"RR","OR","HR","MD","SMD"}:
        fail("dependent route needs explicit nested REML/CR2 model and one supported effect type")
    if p.get("input_scale")!=("log_ratio" if p["effect_type"] in {"RR","OR","HR"} else "linear"):
        fail("ratio estimates/SE must be log-scale; MD/SMD are linear")
    for key in ("outcome","timepoint","contrast","adjustment","population","effect_unit","effect_direction","dependency_rationale"):
        if not isinstance(p.get(key),str) or not p[key].strip():fail(f"dependent plan needs {key}")
    if p["effect_type"] in {"RR","OR","HR"} and p["effect_unit"]!="ratio":fail("ratio effect unit must be ratio")
    if p["effect_type"]=="SMD" and p["effect_unit"]!="standardized":fail("SMD unit must be standardized")
    alpha=number(p.get("alpha"),"alpha")
    if not 0<alpha<.5:fail("alpha invalid")
    grid=p.get("rho_values")
    if not isinstance(grid,list) or not 2<=len(grid)<=5:fail("give two to five prespecified working correlations")
    rho=[number(x,"working correlation") for x in grid]
    if len(set(rho))!=len(rho) or any(x<0 or x>=.95 for x in rho):fail("working correlations must be unique in [0, .95)")
    primary=number(p.get("primary_rho"),"primary correlation")
    if primary not in rho:fail("primary correlation must be in sensitivity grid")
    if p["source_kind"]=="reviewed_extraction" and p.get("review_status")!="human_reviewed_claim":
        fail("real dependent effects need human-reviewed claim")
    return rho,primary


def validate(p,rows):
    rho,primary=plan_check(p)
    by_study={};cohorts={};keys=set()
    for i,r in enumerate(rows,2):
        if any(r.get(k) is None or not str(r[k]).strip() for k in FIELDS):fail(f"dependent row {i} blank required field")
        if any(r[k]!=p[k] for k in ("effect_type","outcome","timepoint","contrast","adjustment","population","effect_unit")):
            fail(f"dependent row {i} mixes effect scale/unit/population/outcome/timepoint/contrast/adjustment")
        r["estimate"]=number(r["estimate"],f"row {i} estimate")
        r["se"]=number(r["se"],f"row {i} SE")
        if r["se"]<=0:fail(f"dependent row {i} SE must be positive")
        key=(r["study_id"],r["effect_id"])
        if key in keys:fail("repeated effect ID within study")
        keys.add(key)
        sid,cid=r["study_id"],r["cohort_id"]
        if cid in cohorts and cohorts[cid]!=sid:fail("same cohort appears under different study IDs")
        cohorts[cid]=sid
        study=by_study.setdefault(sid,{"cohort":cid,"definitions":set(),"rows":[]})
        if study["cohort"]!=cid or r["effect_definition"] in study["definitions"]:
            fail("study mixes cohorts or repeats an effect definition")
        study["definitions"].add(r["effect_definition"]);study["rows"].append(r)
        source=Path(r["source_file"]).resolve()
        locator=r"(?i)(page|p\.|table|figure)\s*[A-Za-z0-9]" if p["source_kind"]=="reviewed_extraction" else r"(?i)synthetic row\s*[A-Za-z0-9]"
        if not source.is_file() or sha(source)!=r["source_sha256"] or not re.search(locator,r["source_location"]):
            fail(f"dependent row {i}: source missing, changed or unlocated")
    if len(by_study)<3 or len(rows)<=len(by_study):fail("dependent model needs at least three independent clusters and some multiple effects")
    if max(len(v["rows"]) for v in by_study.values())>8:fail("more than eight effects per study requires a separately reviewed covariance plan")
    return len(by_study),rho,primary


def run(a):
    p=json.loads(Path(a.plan).read_text(encoding="utf-8"));rows=table(a.input)
    nstudies,rho,primary=validate(p,rows)
    out=Path(a.out).resolve()
    if out.exists():fail("dependent-effect output exists")
    binary=shutil.which(a.rscript) or str(Path(a.rscript).resolve())
    if not Path(binary).is_file():fail("Rscript missing")
    out.parent.mkdir(parents=True,exist_ok=True)
    script=Path(__file__).with_suffix(".R")
    with tempfile.TemporaryDirectory(prefix=".dependent-",dir=out.parent) as temp:
        stage=Path(temp)/"result";stage.mkdir()
        checked=stage/"checked_effects.csv"
        with checked.open("w",encoding="utf-8",newline="") as f:
            w=csv.DictWriter(f,fieldnames=FIELDS);w.writeheader();w.writerows({k:r[k] for k in FIELDS} for r in sorted(rows,key=lambda r:(r["study_id"],r["effect_id"])))
        config=stage/"engine_plan.csv"
        scalar={k:v for k,v in p.items() if not isinstance(v,(list,dict))}
        scalar["rho_values"]="|".join(str(v) for v in rho)
        with config.open("w",encoding="utf-8",newline="") as f:
            w=csv.DictWriter(f,fieldnames=scalar);w.writeheader();w.writerow(scalar)
        proc=subprocess.run([binary,str(script),str(checked),str(config),str(stage)],capture_output=True,text=True)
        if proc.returncode:fail("dependent metafor/clubSandwich fit failed: "+(proc.stderr.strip() or proc.stdout.strip()))
        needed=("dependent_results.csv","working_covariance.csv","dependent_forest.png","rho_sensitivity.png","fact_report.md")
        if any(not (stage/name).is_file() or (stage/name).stat().st_size==0 for name in needed):fail("dependent result incomplete")
        with (stage/"dependent_results.csv").open(encoding="utf-8",newline="") as f:results=list(csv.DictReader(f))
        if len(results)!=len(rho) or any(int(r["n_studies"])!=nstudies or r["inference_status"]!="CR2_SATTERTHWAITE" for r in results):
            fail("dependent rho sensitivity incomplete or non-estimable")
        receipt={"schema":"meta-dependent-result-v1","status":"SYNTHETIC_METHOD_DRAFT" if p["source_kind"]=="synthetic_fixture" else "REVIEWED_EXTRACTION_CLAIM_NEEDS_REVIEW",
                 "final_report":False,"input_sha256":sha(a.input),"plan_sha256":sha(a.plan),"r_script_sha256":sha(script),
                 "source_files":sorted({(str(Path(r["source_file"]).resolve()),r["source_sha256"]) for r in rows}),
                 "outputs":{f.name:sha(f) for f in stage.iterdir() if f.is_file()}}
        (stage/"dependent_receipt.json").write_text(json.dumps(receipt,indent=2)+"\n",encoding="utf-8")
        os.replace(stage,out)
    print(receipt["status"],out)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ("input","plan","rscript","out"):parser.add_argument("--"+name,required=True)
    args=parser.parse_args()
    try:run(args)
    except (OSError,ValueError,KeyError,TypeError,json.JSONDecodeError,csv.Error) as error:parser.exit(2,f"Validation: {error}\n")
