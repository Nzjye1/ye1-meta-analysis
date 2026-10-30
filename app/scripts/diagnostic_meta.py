"""Bivariate diagnostic-test meta-analysis from checked, independent 2x2 tables."""
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


FIELDS = ("study_id", "cohort_id", "TP", "FN", "FP", "TN", "index_test",
          "reference_standard", "threshold", "outcome", "timepoint",
          "source_file", "source_sha256", "source_location")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fail(message):
    raise ValueError(message)


def read_rows(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None or any(k not in reader.fieldnames for k in FIELDS):
            fail("diagnostic input is missing required columns")
        rows = list(reader)
    if len(rows) < 3:
        fail("bivariate model needs at least three independent 2x2 studies")
    return rows


def validate(plan, rows):
    if plan.get("schema") != "meta-diagnostic-plan-v1":
        fail("invalid diagnostic plan schema")
    if plan.get("source_kind") not in ("package_method_example", "synthetic_fixture", "reviewed_extraction"):
        fail("source_kind must identify a package example, synthetic fixture, or reviewed extraction")
    if plan.get("zero_policy") not in ("reject", "half_all", "half_single"):
        fail("zero_policy must explicitly select reject, half_all, or half_single")
    if plan.get("threshold_policy") not in ("common", "mixed_exploratory"):
        fail("threshold_policy must be explicit")
    for key in ("index_test", "reference_standard", "outcome", "timepoint", "effect_direction"):
        if not isinstance(plan.get(key), str) or not plan[key].strip():
            fail(f"plan needs {key}")
    alpha = plan.get("alpha")
    if not isinstance(alpha, (int, float)) or isinstance(alpha, bool) or not math.isfinite(alpha) or not 0 < alpha < 0.5:
        fail("alpha must be between zero and 0.5")
    if plan["source_kind"] == "reviewed_extraction" and plan.get("review_status") != "human_reviewed_claim":
        fail("reviewed extraction needs an explicit human_reviewed_claim; identity is not authenticated")
    ids, cohorts, thresholds = set(), set(), set()
    for n, row in enumerate(rows, 2):
        if any(row[key] is None or not str(row[key]).strip() for key in FIELDS):
            fail(f"row {n}: all required fields must be nonempty")
        if row["study_id"] in ids or row["cohort_id"] in cohorts:
            fail(f"row {n}: repeated study or cohort; correlated effects are unsupported")
        ids.add(row["study_id"]); cohorts.add(row["cohort_id"])
        for key in ("index_test", "reference_standard", "outcome", "timepoint"):
            if row[key] != plan[key]:
                fail(f"row {n}: {key} differs from the plan")
        thresholds.add(row["threshold"])
        for key in ("TP", "FN", "FP", "TN"):
            if not re.fullmatch(r"\d+", row[key].strip()):
                fail(f"row {n}: {key} must be a nonnegative integer")
            row[key] = int(row[key])
        if row["TP"] + row["FN"] == 0 or row["FP"] + row["TN"] == 0:
            fail(f"row {n}: diseased and non-diseased denominators must be positive")
        source = Path(row["source_file"]).resolve()
        if not source.is_file() or digest(source) != row["source_sha256"]:
            fail(f"row {n}: local source missing or changed")
        locator = row["source_location"]
        if plan["source_kind"] == "package_method_example":
            if not re.fullmatch(r"dataset row \d+", locator):
                fail(f"row {n}: package method example needs dataset row locator")
        elif plan["source_kind"] == "synthetic_fixture":
            if not re.fullmatch(r"synthetic row \d+", locator):
                fail(f"row {n}: synthetic fixture needs synthetic row locator")
        elif not re.search(r"(?i)\b(?:page|p\.|table|figure)\s*[A-Za-z0-9]", locator):
            fail(f"row {n}: reviewed extraction needs a page/table/figure locator")
    if len(thresholds) != 1 and plan["threshold_policy"] == "common":
        fail("mixed thresholds need an explicit mixed_exploratory plan or separate analyses")
    if any(row[key] == 0 for row in rows for key in ("TP", "FN", "FP", "TN")) and plan["zero_policy"] == "reject":
        fail("zero cell found under reject policy")
    return sorted(thresholds)


def run(args):
    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    rows = read_rows(args.input)
    thresholds = validate(plan, rows)
    out = Path(args.out).resolve()
    if out.exists():
        fail("output already exists; choose a fresh directory")
    binary = shutil.which(args.rscript) or str(Path(args.rscript).resolve())
    if not Path(binary).is_file():
        fail("Rscript executable missing")
    out.parent.mkdir(parents=True, exist_ok=True)
    script = Path(__file__).with_suffix(".R")
    with tempfile.TemporaryDirectory(prefix=".diagnostic-meta-", dir=out.parent) as temp:
        stage = Path(temp) / "result"
        stage.mkdir()
        checked = stage / "checked_2x2.csv"
        with checked.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            writer.writeheader(); writer.writerows({key: row[key] for key in FIELDS} for row in rows)
        process = subprocess.run([binary, str(script), str(checked), plan["zero_policy"], str(plan["alpha"]), plan["threshold_policy"], str(stage)],
                                 capture_output=True, text=True)
        if process.returncode:
            fail("mada bivariate model failed: " + (process.stderr.strip() or process.stdout.strip()))
        required = ("diagnostic_summary.csv", "study_2x2_trace.csv", "sroc.png", "paired_forest.png")
        if any(not (stage / name).is_file() or (stage / name).stat().st_size == 0 for name in required):
            fail("mada output incomplete")
        with (stage / "diagnostic_summary.csv").open(encoding="utf-8", newline="") as f:
            summary = list(csv.DictReader(f))
        if len(summary) != 1 or summary[0]["converged"] != "TRUE":
            fail("bivariate fit did not converge")
        s = summary[0]
        caution = "Thresholds differ; this pooled estimate is exploratory." if len(thresholds) > 1 else "Threshold is common by supplied label; its clinical equivalence is not verified."
        report = ["# Diagnostic test meta-analysis: statistical facts", "",
                  f"Input source: {plan['source_kind']}; {len(rows)} independent labeled studies; {caution}",
                  f"Index test: {plan['index_test']}; reference standard: {plan['reference_standard']}; outcome: {plan['outcome']}; timepoint: {plan['timepoint']}.",
                  f"Bivariate Reitsma REML (mada {s['mada_version']}); zero-cell policy: {plan['zero_policy']}; confidence level: {100*(1-plan['alpha']):g}%.",
                  f"Pooled sensitivity {float(s['sensitivity']):.3f} (CI {float(s['sensitivity_lower']):.3f}–{float(s['sensitivity_upper']):.3f}); "
                  f"specificity {float(s['specificity']):.3f} (CI {float(s['specificity_lower']):.3f}–{float(s['specificity_upper']):.3f}).",
                  f"Direction supplied by user: {plan['effect_direction']}.", "",
                  "These are statistical outputs from supplied 2x2 values. Source hashes and locators check local consistency, not extraction correctness or reviewer identity. "
                  "Package examples validate the method only. No clinical conclusion, complete search, risk-of-bias decision, or publication-ready manuscript is established."]
        (stage / "diagnostic_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
        receipt = {"schema": "meta-diagnostic-result-v1", "status": {"package_method_example": "PACKAGE_METHOD_EXAMPLE", "synthetic_fixture": "SYNTHETIC_FIXTURE", "reviewed_extraction": "REVIEWED_EXTRACTION_CLAIM_NEEDS_EVIDENCE_REVIEW"}[plan["source_kind"]],
                   "final_report": False, "input_sha256": digest(args.input), "plan_sha256": digest(args.plan),
                   "r_script_sha256": digest(script), "thresholds": thresholds, "threshold_policy": plan["threshold_policy"],
                   "interpretation_scope": "MIXED_THRESHOLDS_EXPLORATORY" if len(thresholds) > 1 else "COMMON_THRESHOLD_LABEL_UNVERIFIED_CLINICALLY",
                   "zero_policy": plan["zero_policy"],
                   "source_files": sorted({(str(Path(row["source_file"]).resolve()), row["source_sha256"]) for row in rows}),
                   "outputs": {p.name: digest(p) for p in stage.iterdir() if p.is_file()}}
        (stage / "diagnostic_receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        if out.exists():
            fail("output appeared before commit")
        os.replace(stage, out)
    print(f"{receipt['status']}: {out}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("input", "plan", "out", "rscript"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    try:
        run(args)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        parser.exit(2, f"Validation: {exc}\n")
