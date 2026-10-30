"""Traceable correlated-category dose-response meta-analysis using dosresmeta."""
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


FIELDS = ("study_id", "cohort_id", "dose", "logrr", "se", "cases", "n", "type", "reference",
          "category_lower", "category_upper", "category_basis", "open_end_basis", "open_end_rationale",
          "dose_unit", "outcome", "timepoint", "adjustment", "source_file", "source_sha256", "source_location")


def fail(message):
    raise ValueError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def table(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None or any(k not in reader.fieldnames for k in FIELDS):
            fail("dose category table lacks required columns")
        rows = list(reader)
    if not rows:
        fail("dose category table is empty")
    return rows


def number(value, label, allow_blank=False):
    if allow_blank and (value is None or str(value).strip() == ""):
        return None
    try:
        result = float(value)
    except (ValueError, TypeError):
        fail(f"{label} must be numeric")
    if not math.isfinite(result) or abs(result) > 1e12:
        fail(f"{label} must be finite and reasonably bounded")
    return result


def plan_check(p):
    if p.get("schema") != "meta-dose-plan-v1" or p.get("source_kind") not in {"package_method_example", "synthetic_fixture", "reviewed_extraction"}:
        fail("invalid dose-response plan schema/source kind")
    for key in ("dose_unit", "outcome", "timepoint", "adjustment", "effect_direction", "dose_definition", "reference_description"):
        if not isinstance(p.get(key), str) or not p[key].strip():
            fail(f"dose-response plan needs {key}")
    if p.get("model") not in {"linear", "natural_spline"} or p.get("covariance") != "greenland_longnecker" or p.get("method") != "REML":
        fail("model, covariance approximation and REML method must be explicit")
    if p.get("effect_type") != "RR" or p.get("data_type") not in {"ci", "ir"}:
        fail("this dose route needs log RR and one incidence type ci or ir")
    alpha = number(p.get("alpha"), "alpha")
    if not 0 < alpha < .5:
        fail("alpha must be between zero and 0.5")
    ref = number(p.get("reference_dose"), "reference_dose")
    grid = p.get("prediction_doses")
    if not isinstance(grid, list) or not 2 <= len(grid) <= 100:
        fail("prediction_doses needs 2-100 explicit values")
    grid = [number(v, "prediction dose") for v in grid]
    if len(set(grid)) != len(grid) or ref not in grid:
        fail("prediction grid must contain reference exactly once and no repeats")
    if p["model"] == "natural_spline":
        knots = p.get("knots")
        boundaries = p.get("boundary_knots")
        if not isinstance(knots, list) or not 1 <= len(knots) <= 2 or not isinstance(boundaries, list) or len(boundaries) != 2:
            fail("natural spline needs one or two explicit interior knots and two boundary knots")
        knots = [number(v, "spline knot") for v in knots]; bounds = [number(v, "boundary knot") for v in boundaries]
        if not bounds[0] < min(knots) <= max(knots) < bounds[1] or len(set(knots)) != len(knots):
            fail("spline knots must be distinct and strictly inside boundaries")
    elif p.get("knots") or p.get("boundary_knots"):
        fail("linear plan must not supply spline knots")
    if p["source_kind"] == "reviewed_extraction" and p.get("review_status") != "human_reviewed_claim":
        fail("real dose inputs need an explicit human-reviewed claim")
    return ref, grid


def validate(p, rows):
    ref, grid = plan_check(p)
    studies, cohort_owner = {}, {}
    for index, row in enumerate(rows, 2):
        required = ("study_id", "cohort_id", "dose", "logrr", "cases", "n", "type", "reference",
                    "category_basis", "dose_unit", "outcome", "timepoint", "adjustment", "source_file", "source_sha256", "source_location")
        if any(row[k] is None or not str(row[k]).strip() for k in required):
            fail(f"dose row {index} has blank required field")
        if any(row[k] != p[k] for k in ("dose_unit", "outcome", "timepoint", "adjustment")) or row["type"] != p["data_type"]:
            fail(f"dose row {index} mixes unit, outcome, timepoint, adjustment or incidence type")
        if row["reference"] not in {"YES", "NO"}:
            fail(f"dose row {index}: reference must be YES or NO")
        for key in ("dose", "logrr", "cases", "n"):
            row[key] = number(row[key], f"dose row {index} {key}")
        row["se"] = number(row["se"], f"dose row {index} se", allow_blank=True)
        if row["dose"] < 0 or row["cases"] <= 0 or row["n"] <= 0 or (row["type"] == "ci" and row["cases"] > row["n"]):
            fail(f"dose row {index}: dose/count/denominator invalid")
        if row["cases"] != int(row["cases"]) or (row["type"] == "ci" and row["n"] != int(row["n"])):
            fail(f"dose row {index}: cases and cumulative-incidence denominators must be whole counts")
        if row["reference"] == "YES":
            if row["dose"] != ref or abs(row["logrr"]) > 1e-12 or row["se"] not in (None, 0.0):
                fail(f"dose row {index}: reference row must be plan dose with logRR zero and no SE")
        elif row["se"] is None or row["se"] <= 0:
            fail(f"dose row {index}: nonreference needs positive SE")
        lower = number(row["category_lower"], f"dose row {index} lower", allow_blank=True)
        upper = number(row["category_upper"], f"dose row {index} upper", allow_blank=True)
        basis = row["category_basis"]
        if basis not in {"reported_mean", "reported_median", "midpoint", "author_assigned", "package_example"}:
            fail(f"dose row {index}: representative-dose basis invalid")
        if p["source_kind"] == "package_method_example":
            if basis != "package_example" or not re.fullmatch(r"dataset row \d+", row["source_location"]):
                fail(f"dose row {index}: package example needs package dataset locator/basis")
        else:
            if basis == "package_example":
                fail("package category basis in non-package source")
            if not re.search(r"(?i)(?:page|p\.|table|figure|synthetic row)\s*[A-Za-z0-9]", row["source_location"]):
                fail(f"dose row {index}: source locator required")
            if p["source_kind"] == "reviewed_extraction" and "synthetic row" in row["source_location"].lower():
                fail("synthetic source locator in real dose data")
            if lower is None and upper is None:
                fail(f"dose row {index}: category bounds missing")
            if lower is not None and upper is not None:
                if lower >= upper or not lower <= row["dose"] <= upper:
                    fail(f"dose row {index}: representative dose outside closed category")
                if basis == "midpoint" and abs(row["dose"] - (lower + upper)/2) > 1e-8:
                    fail(f"dose row {index}: midpoint does not match category bounds")
                if row["open_end_basis"] or row["open_end_rationale"]:
                    fail(f"dose row {index}: closed category must not claim open-end assignment")
            else:
                if row["open_end_basis"] not in {"reported_mean", "reported_median", "adjacent_width", "author_assigned"} or not row["open_end_rationale"].strip():
                    fail(f"dose row {index}: open-ended category needs explicit assignment basis and rationale")
                if lower is not None and row["dose"] < lower or upper is not None and row["dose"] > upper:
                    fail(f"dose row {index}: representative dose outside open category")
        source = Path(row["source_file"]).resolve()
        if not source.is_file() or sha(source) != row["source_sha256"]:
            fail(f"dose row {index}: local source missing or changed")
        sid, cohort = row["study_id"], row["cohort_id"]
        if cohort in cohort_owner and cohort_owner[cohort] != sid:
            fail("one cohort appears under different study IDs")
        cohort_owner[cohort] = sid
        study = studies.setdefault(sid, {"cohort": cohort, "type": row["type"], "doses": set(), "rows": []})
        if study["cohort"] != cohort or study["type"] != row["type"] or row["dose"] in study["doses"]:
            fail(f"dose row {index}: cohort/type mismatch or repeated study dose")
        study["doses"].add(row["dose"]); study["rows"].append(row)
    if len(studies) < 3:
        fail("dose-response meta-analysis needs at least three independent studies")
    for sid, study in studies.items():
        entries = study["rows"]
        if len(entries) < 3 or sum(r["reference"] == "YES" for r in entries) != 1:
            fail(f"study {sid}: at least three categories and exactly one reference required")
    observed = [r["dose"] for r in rows]
    if min(grid) < min(observed) or max(grid) > max(observed):
        fail("prediction grid extrapolates beyond observed doses")
    if p["model"] == "natural_spline":
        bounds = p["boundary_knots"]
        if bounds[0] > min(observed) or bounds[1] < max(observed):
            fail("spline boundary knots must cover observed dose range")
        if min(p["knots"]) <= min(observed) or max(p["knots"]) >= max(observed):
            fail("interior spline knots must lie within observed dose range")
        if len(studies) <= len(p["knots"]) + 2:
            fail("too few independent studies for requested spline basis")
    return len(studies), ref, grid


def run(a):
    p = json.loads(Path(a.plan).read_text(encoding="utf-8"))
    rows = table(a.input)
    n_studies, ref, grid = validate(p, rows)
    out = Path(a.out).resolve()
    if out.exists(): fail("output exists")
    binary = shutil.which(a.rscript) or str(Path(a.rscript).resolve())
    if not Path(binary).is_file(): fail("Rscript missing")
    out.parent.mkdir(parents=True, exist_ok=True)
    script = Path(__file__).with_suffix(".R")
    with tempfile.TemporaryDirectory(prefix=".dose-response-", dir=out.parent) as temp:
        stage = Path(temp)/"result"; stage.mkdir()
        checked=stage/"checked_categories.csv"
        with checked.open("w",encoding="utf-8",newline="") as f:
            writer=csv.DictWriter(f,fieldnames=FIELDS);writer.writeheader();writer.writerows({key:r[key] for key in FIELDS} for r in sorted(rows,key=lambda row:(row["study_id"],row["dose"])))
        config=stage/"engine_plan.csv"
        scalar={key:value for key,value in p.items() if not isinstance(value,(list,dict))}
        scalar["knots"]="|".join(str(v) for v in p.get("knots",[]))
        scalar["boundary_knots"]="|".join(str(v) for v in p.get("boundary_knots",[]))
        scalar["prediction_doses"]="|".join(str(v) for v in grid)
        with config.open("w",encoding="utf-8",newline="") as f:
            writer=csv.DictWriter(f,fieldnames=scalar);writer.writeheader();writer.writerow(scalar)
        proc=subprocess.run([binary,str(script),str(checked),str(config),str(stage)],capture_output=True,text=True)
        if proc.returncode: fail("dosresmeta fit failed: "+(proc.stderr.strip() or proc.stdout.strip()))
        required=("dose_summary.csv","dose_coefficients.csv","dose_predictions.csv","within_study_covariance.csv","dose_curve.png","category_trace.csv")
        if any(not (stage/name).is_file() or (stage/name).stat().st_size==0 for name in required):
            fail("dose-response result incomplete")
        with (stage/"dose_summary.csv").open(encoding="utf-8",newline="") as f: summary=list(csv.DictReader(f))
        if len(summary)!=1 or summary[0]["converged"]!="TRUE" or int(summary[0]["n_studies"])!=n_studies:
            fail("dose-response model did not converge or study count disagreed")
        report=["# Dose-response statistical facts", "",f"Input source: {p['source_kind']}; {n_studies} independent labeled studies; {len(rows)} dose categories.",
                f"Outcome: {p['outcome']} at {p['timepoint']}; dose unit: {p['dose_unit']}; reference: {p['reference_description']} (dose {ref}); effect: log RR (display RR).",
                f"Primary form: {p['model']}; explicit spline knots: {p.get('knots',[])}; covariance: Greenland-Longnecker approximation from supplied cases/{p['data_type']} denominators; REML two-stage fit.",
                f"Effect direction supplied by user: {p['effect_direction']}. Dose definition: {p['dose_definition']}.",
                "Predictions are restricted to the observed dose range. The model uses within-study correlated category estimates; categories are not independent studies.",
                "Representative doses and any open-ended assignments are supplied claims with local source locators. Source hashes check file consistency, not extraction correctness. No automatic clinical conclusion or complete review is established."]
        (stage/"dose_report.md").write_text("\n".join(report)+"\n",encoding="utf-8")
        receipt={"schema":"meta-dose-result-v1","status":"METHOD_EXAMPLE_OR_SYNTHETIC" if p["source_kind"]!="reviewed_extraction" else "REVIEWED_EXTRACTION_CLAIM_NEEDS_REVIEW",
                 "final_report":False,"input_sha256":sha(a.input),"plan_sha256":sha(a.plan),"r_script_sha256":sha(script),
                 "study_count":n_studies,"covariance":"greenland_longnecker","source_files":sorted({(str(Path(r["source_file"]).resolve()),r["source_sha256"]) for r in rows}),
                 "outputs":{f.name:sha(f) for f in stage.iterdir() if f.is_file()}}
        (stage/"dose_receipt.json").write_text(json.dumps(receipt,indent=2)+"\n",encoding="utf-8")
        os.replace(stage,out)
    print(receipt["status"],out)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ("input","plan","rscript","out"):parser.add_argument("--"+name,required=True)
    args=parser.parse_args()
    try:run(args)
    except (OSError,ValueError,KeyError,TypeError,json.JSONDecodeError,csv.Error) as error:
        parser.exit(2,f"Validation: {error}\n")
