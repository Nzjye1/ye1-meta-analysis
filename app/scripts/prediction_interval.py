"""Additional prediction interval for a checked protocol-bound RE/REML run; no base result rewrite."""
import argparse
import csv
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import literature as lit


def run(a):
    source = Path(a.stats_dir).resolve()
    receipt_path = source / "protocol_run_receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("schema") != "meta-protocol-run-v1" or not receipt.get("result_sha256"):
        lit.fail("protocol-bound statistics receipt required")
    if lit.sha256(a.confirmation) != receipt.get("confirmation_sha256"):
        lit.fail("stale or different protocol confirmation")
    if lit.sha256(Path(__file__).with_name("run_meta.R")) != receipt.get("run_meta_sha256"):
        lit.fail("base statistical script differs from bound run")
    for name, digest in receipt["result_sha256"].items():
        if Path(name).name != name or not (source / name).is_file() or lit.sha256(source / name) != digest:
            lit.fail(f"bound statistical output changed: {name}")
    for name in ("study_effects_trace.csv", "pooled_result.csv", "confirmed_analysis.csv"):
        if name not in receipt["result_sha256"]:
            lit.fail(f"bound statistical output missing: {name}")
    binary = shutil.which(a.rscript) or str(Path(a.rscript).resolve())
    if not Path(binary).is_file():
        lit.fail("Rscript executable not found")
    output = Path(a.out).resolve()
    if output.exists():
        lit.fail("output exists; use a fresh prediction interval directory")
    output.parent.mkdir(parents=True, exist_ok=True)
    script = Path(__file__).with_name("prediction_interval.R")
    with tempfile.TemporaryDirectory(prefix=".meta-prediction-", dir=output.parent) as temp:
        stage = Path(temp) / "result"
        stage.mkdir()
        process = subprocess.run([binary, str(script), str(source), str(stage / "prediction_interval.csv")],
                                 text=True, capture_output=True)
        if process.returncode:
            lit.fail("prediction interval R run failed: " + (process.stderr.strip() or process.stdout.strip()))
        with (stage / "prediction_interval.csv").open(encoding="utf-8-sig", newline="") as handle:
            result = list(csv.DictReader(handle))
        if len(result) != 1:
            lit.fail("prediction interval R output is incomplete")
        row = result[0]
        level = 100 * (1 - float(row["alpha"]))
        report = ["# Random-effects prediction interval", "",
                  f"Bound run: {source}; protocol mode: {receipt['mode']}.",
                  f"{row['k']} independent studies; {row['effect_type']} pooled {row['pooled']} "
                  f"({level:g}% CI {row['ci_lower']} to {row['ci_upper']}); "
                  f"{level:g}% prediction interval {row['pi_lower']} to {row['pi_upper']}.",
                  f"Method: {row['prediction_method']}; tau²={row['tau2']}.",
                  f"Interpretation: {row['ratio_interpretation']}.", "",
                  "The interval is an approximate range for a true effect in a new comparable study, not a patient-level prediction or proof of clinical generalizability. It does not account for uncertainty in the heterogeneity estimate beyond the fitted model. If estimated tau² is zero it can coincide with the confidence interval. This is a statistical appendix, not a new systematic review or final conclusion."]
        (stage / "prediction_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
        audit = {"schema": "meta-prediction-interval-v1", "status": "SYNTHETIC_STATISTICAL_APPENDIX" if receipt["mode"] == "synthetic_test" else "STATISTICAL_APPENDIX_REQUIRES_REVIEW",
                 "stats_dir": str(source), "stats_receipt_sha256": lit.sha256(receipt_path),
                 "confirmation_sha256": lit.sha256(a.confirmation), "rscript": str(Path(binary).resolve()),
                 "script_sha256": lit.sha256(script), "metafor_version_source": "bound base reproducibility_manifest.csv",
                 "outputs": {f.name: lit.sha256(f) for f in stage.iterdir() if f.is_file()},
                 "final_report": False}
        (stage / "prediction_receipt.json").write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
        if output.exists():
            lit.fail("output path appeared before commit")
        os.replace(stage, output)
    print(f"{audit['status']}: {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("stats-dir", "confirmation", "rscript", "out"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    try:
        run(args)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        parser.exit(2, f"Validation: {error}\n")
