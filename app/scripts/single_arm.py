"""Single-group proportion or incidence-rate meta-analysis; distinct denominators."""
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

FIELDS=("study_id","cohort_id","events","denominator","denominator_unit","outcome","timepoint","population",
        "source_file","source_sha256","source_location")


def fail(msg): raise ValueError(msg)


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def table(path):
    with Path(path).open(encoding="utf-8-sig",newline="") as f:
        reader=csv.DictReader(f)
        if reader.fieldnames is None or any(k not in reader.fieldnames for k in FIELDS): fail("single-group input lacks required fields")
        rows=list(reader)
    if not rows: fail("single-group input empty")
    return rows


def number(value,label):
    try: v=float(value)
    except (ValueError,TypeError): fail(f"{label} must be numeric")
    if not math.isfinite(v) or abs(v)>1e12: fail(f"{label} must be finite and bounded")
    return v


def plan_check(p):
    if p.get("schema")!="meta-single-arm-plan-v1" or p.get("source_kind") not in {"synthetic_fixture","reviewed_extraction"}:
        fail("invalid single-group schema/source kind")
    if p.get("measure") not in {"proportion","incidence_rate"} or p.get("model") not in {"FE","REML"}:
        fail("measure must be proportion or incidence_rate; model FE or REML")
    for key in ("outcome","timepoint","population","denominator_unit","event_definition","effect_direction"):
        if not isinstance(p.get(key),str) or not p[key].strip(): fail(f"plan needs {key}")
    if p["measure"]=="proportion" and p["denominator_unit"]!="people": fail("proportion denominator must be people")
    if p["measure"]=="incidence_rate" and p["denominator_unit"] not in {"person_years","person_months","person_days"}:
        fail("incidence rate needs explicit person-time unit")
    scale=number(p.get("display_per"),"display_per")
    if (p["measure"]=="proportion" and scale!=1) or (p["measure"]=="incidence_rate" and scale not in {1,100,1000,100000}):
        fail("invalid display rate scale")
    alpha=number(p.get("alpha"),"alpha")
    if not 0<alpha<.5: fail("alpha must lie between zero and 0.5")
    if p["source_kind"]=="reviewed_extraction" and p.get("review_status")!="human_reviewed_claim":
        fail("real single-group inputs need explicit human-reviewed claim")
    return p["measure"],p["model"],scale


def validate(p,rows):
    measure,_,_=plan_check(p)
    if len(rows)<3: fail("single-group meta needs at least three independent studies")
    studies=set();cohorts=set()
    for i,r in enumerate(rows,2):
        if any(r.get(k) is None or not str(r[k]).strip() for k in FIELDS): fail(f"single-group row {i} blank required value")
        if r["study_id"] in studies or r["cohort_id"] in cohorts: fail("repeated study or cohort; dependent rows need a separate model")
        studies.add(r["study_id"]);cohorts.add(r["cohort_id"])
        if any(r[k]!=p[k] for k in ("outcome","timepoint","population","denominator_unit")):
            fail(f"single-group row {i} mixes outcome/timepoint/population/denominator unit")
        r["events"]=number(r["events"],f"row {i} events")
        r["denominator"]=number(r["denominator"],f"row {i} denominator")
        if r["events"]!=int(r["events"]) or r["events"]<=0 or r["denominator"]<=0:
            fail(f"single-group row {i}: events must be positive whole counts and denominator positive")
        if measure=="proportion" and (r["denominator"]!=int(r["denominator"]) or r["events"]>=r["denominator"]):
            fail(f"single-group row {i}: proportion needs events strictly between zero and number of people")
        source=Path(r["source_file"]).resolve()
        locator=r"(?i)(page|p\.|table|figure)\s*[A-Za-z0-9]" if p["source_kind"]=="reviewed_extraction" else r"(?i)synthetic row\s*[A-Za-z0-9]"
        if not source.is_file() or sha(source)!=r["source_sha256"] or not re.search(locator,r["source_location"]):
            fail(f"single-group row {i}: source missing, changed or unlocated")
    return len(studies)


def run(a):
    p=json.loads(Path(a.plan).read_text(encoding="utf-8"))
    rows=table(a.input);count=validate(p,rows)
    out=Path(a.out).resolve()
    if out.exists(): fail("single-group output exists")
    binary=shutil.which(a.rscript) or str(Path(a.rscript).resolve())
    if not Path(binary).is_file(): fail("Rscript missing")
    out.parent.mkdir(parents=True,exist_ok=True)
    script=Path(__file__).with_suffix(".R")
    with tempfile.TemporaryDirectory(prefix=".single-arm-",dir=out.parent) as temp:
        stage=Path(temp)/"result";stage.mkdir()
        checked=stage/"checked_studies.csv"
        with checked.open("w",encoding="utf-8",newline="") as f:
            w=csv.DictWriter(f,fieldnames=FIELDS);w.writeheader();w.writerows({k:r[k] for k in FIELDS} for r in sorted(rows,key=lambda r:r["study_id"]))
        config=stage/"engine_plan.csv"
        with config.open("w",encoding="utf-8",newline="") as f:
            w=csv.DictWriter(f,fieldnames=p.keys());w.writeheader();w.writerow(p)
        proc=subprocess.run([binary,str(script),str(checked),str(config),str(stage)],capture_output=True,text=True)
        if proc.returncode: fail("single-group metafor fit failed: "+(proc.stderr.strip() or proc.stdout.strip()))
        required=("single_summary.csv","study_estimates.csv","single_forest.png","fact_report.md")
        if any(not (stage/name).is_file() or (stage/name).stat().st_size==0 for name in required):fail("single-group result incomplete")
        with (stage/"single_summary.csv").open(encoding="utf-8",newline="") as f:s=list(csv.DictReader(f))
        if len(s)!=1 or s[0]["converged"]!="TRUE" or int(s[0]["n_studies"])!=count:
            fail("single-group fit did not converge or study count disagreed")
        receipt={"schema":"meta-single-arm-result-v1","status":"SYNTHETIC_METHOD_DRAFT" if p["source_kind"]=="synthetic_fixture" else "REVIEWED_EXTRACTION_CLAIM_NEEDS_REVIEW",
                 "final_report":False,"input_sha256":sha(a.input),"plan_sha256":sha(a.plan),"r_script_sha256":sha(script),
                 "source_files":sorted({(str(Path(r["source_file"]).resolve()),r["source_sha256"]) for r in rows}),
                 "outputs":{f.name:sha(f) for f in stage.iterdir() if f.is_file()}}
        (stage/"single_receipt.json").write_text(json.dumps(receipt,indent=2)+"\n",encoding="utf-8")
        os.replace(stage,out)
    print(receipt["status"],out)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ("input","plan","rscript","out"):parser.add_argument("--"+name,required=True)
    args=parser.parse_args()
    try:run(args)
    except (OSError,ValueError,KeyError,TypeError,json.JSONDecodeError,csv.Error) as error:parser.exit(2,f"Validation: {error}\n")
