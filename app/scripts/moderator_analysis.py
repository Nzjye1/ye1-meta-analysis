"""Auditable subgroup and one/multiple moderator regression over one checked pairwise effect scale."""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

import literature as lit

SAFE_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
META_FIELDS = ["study_id", "source_file", "source_sha256", "source_location"]


def table(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def checked_plan(path):
    p = json.loads(Path(path).read_text(encoding="utf-8"))
    if p.get("schema") != "meta-moderator-plan-v1" or p.get("mode") not in {"subgroup", "meta_regression"} or p.get("intent") not in {"exploratory", "confirmed_protocol"}:
        lit.fail("invalid moderator plan schema, mode, or intent")
    if not all(isinstance(p.get(key), str) and p[key].strip() for key in ("hypothesis", "effect_direction")):
        lit.fail("moderator hypothesis and effect direction required")
    covars = p.get("moderators")
    if not isinstance(covars, list) or not 1 <= len(covars) <= 3 or (p["mode"] == "subgroup" and len(covars) != 1):
        lit.fail("one to three moderators required; subgroup uses exactly one")
    names = set()
    for item in covars:
        if not isinstance(item, dict) or set(item) != {"name", "type", "reference"} or not SAFE_NAME.fullmatch(item["name"]) or item["name"] in names:
            lit.fail("moderator names must be distinct simple identifiers")
        names.add(item["name"])
        if item["type"] not in {"categorical", "continuous"} or (item["type"] == "categorical" and not item["reference"].strip()) or (item["type"] == "continuous" and item["reference"] != ""):
            lit.fail("categorical moderator needs a reference; continuous reference must be blank")
    if p["mode"] == "subgroup" and covars[0]["type"] != "categorical":
        lit.fail("subgroup mode needs a categorical moderator")
    return p


def checked_stats(path, confirmation, protocol, intent):
    root = Path(path).resolve()
    receipt_path = root / "protocol_run_receipt.json"
    bound = receipt_path.is_file()
    if bound:
        if not confirmation:
            lit.fail("protocol-bound statistics require --confirmation")
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if receipt.get("schema") != "meta-protocol-run-v1" or lit.sha256(confirmation) != receipt.get("confirmation_sha256"):
            lit.fail("stale or invalid protocol-bound result")
        if lit.sha256(Path(__file__).with_name("run_meta.R")) != receipt.get("run_meta_sha256"):
            lit.fail("base statistical script changed since bound run")
        for name, digest in receipt["result_sha256"].items():
            if Path(name).name != name or not (root / name).is_file() or lit.sha256(root / name) != digest:
                lit.fail(f"bound statistical output changed: {name}")
    else:
        if confirmation or intent != "exploratory":
            lit.fail("unbound numeric result is exploratory only and cannot use confirmation")
        manifest = {row["key"]: row["value"] for row in table(root / "reproducibility_manifest.csv")}
        for source, digest in (("input_file", "input_md5"), ("analysis_file", "analysis_md5")):
            file = Path(manifest[source])
            if not file.is_file() or hashlib.md5(file.read_bytes()).hexdigest() != manifest[digest]:
                lit.fail(f"direct numeric input changed: {source}")
        if hashlib.md5(Path(__file__).with_name("run_meta.R").read_bytes()).hexdigest() != manifest["script_md5"]:
            lit.fail("base statistical script changed since direct run")
    for name in ("study_effects_trace.csv", "pooled_result.csv", "confirmed_analysis.csv"):
        if not (root / name).is_file():
            lit.fail(f"statistical output missing: {name}")
    if intent == "confirmed_protocol":
        if not bound or not protocol:
            lit.fail("confirmed_protocol moderator analysis needs bound statistics and --protocol")
        c = json.loads(Path(confirmation).read_text(encoding="utf-8"))
        if lit.sha256(protocol) != c.get("input_sha256", {}).get("protocol"):
            lit.fail("moderator protocol differs from confirmed protocol")
    return root, bound


def run(a):
    plan = checked_plan(a.plan)
    stats, bound = checked_stats(a.stats_dir, a.confirmation, a.protocol, plan["intent"])
    if plan["intent"] == "confirmed_protocol":
        protocol = json.loads(Path(a.protocol).read_text(encoding="utf-8"))
        declared = {key: plan[key] for key in ("mode", "hypothesis", "effect_direction", "moderators")}
        if protocol.get("moderator_analysis") != declared:
            lit.fail("moderator analysis is not declared in confirmed protocol")
    trace = table(stats / "study_effects_trace.csv")
    pooled = table(stats / "pooled_result.csv")
    if len(pooled) != 1 or not trace or len({r["study_id"] for r in trace}) != len(trace) or len({r["cohort_id"] for r in trace}) != len(trace):
        lit.fail("base statistics have repeated study/cohort or invalid pooled rows")
    fields = META_FIELDS + [item["name"] for item in plan["moderators"]]
    values, _ = lit.read_csv(a.moderators, fields)
    lookup = {r["study_id"]: r for r in values}
    if len(lookup) != len(values) or set(lookup) != {r["study_id"] for r in trace}:
        lit.fail("moderator table must contain exactly one row per bound independent study")
    for i, row in enumerate(values, 2):
        path = Path(row["source_file"]).resolve()
        if not path.is_file() or lit.sha256(path) != row["source_sha256"] or not re.search(r"(?i)(page|p\.|table|figure)\s*[A-Za-z0-9]", row["source_location"]):
            lit.fail(f"moderator row {i}: local source/hash/page or table locator required")
        for item in plan["moderators"]:
            value = row[item["name"]].strip()
            if not value:
                lit.fail(f"moderator row {i}: blank {item['name']}")
            if item["type"] == "continuous":
                try:
                    number = float(value)
                except ValueError:
                    lit.fail(f"moderator row {i}: invalid continuous {item['name']}")
                if not (-1e12 < number < 1e12):
                    lit.fail(f"moderator row {i}: nonfinite or extreme {item['name']}")
    output = Path(a.out).resolve()
    if output.exists():
        lit.fail("output exists; use a fresh moderator result directory")
    binary = shutil.which(a.rscript) or str(Path(a.rscript).resolve())
    if not Path(binary).is_file():
        lit.fail("Rscript executable not found")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".meta-moderators-", dir=output.parent) as tmp:
        stage = Path(tmp) / "result"
        stage.mkdir()
        design = stage / "moderator_plan.csv"
        lit.write_csv(design, ["name", "type", "reference"], plan["moderators"])
        script = Path(__file__).with_name("moderator_analysis.R")
        proc = subprocess.run([binary, str(script), str(stats), str(a.moderators), str(design),
                               plan["mode"], str(stage)], capture_output=True, text=True)
        if proc.returncode:
            lit.fail("moderator R run failed: " + (proc.stderr.strip() or proc.stdout.strip()))
        required = ["moderator_coefficients.csv", "moderator_model.csv", "moderator_trace.csv",
                    "coefficient_plot.png"]
        if plan["mode"] == "subgroup":
            required.append("subgroup_results.csv")
        if any(not (stage / name).is_file() or (stage / name).stat().st_size == 0 for name in required):
            lit.fail("moderator R output incomplete")
        model = table(stage / "moderator_model.csv")[0]
        report = ["# Moderator analysis statistical appendix", "",
                  f"Mode: {plan['mode']}; intent: {plan['intent']}; base result: {stats}.",
                  f"Hypothesis supplied by user: {plan['hypothesis']}",
                  f"Effect direction supplied by user: {plan['effect_direction']}",
                  f"Effect scale: {model['effect_type']}; coefficients remain on the analysis scale (log scale for RR/OR/HR).",
                  f"Studies: {model['k']}; model parameters: {model['p']}; residual degrees of freedom: {model['residual_df']}.",
                  f"Omnibus moderator or between-group test: QM={model['QM']}, df={model['QM_df']}, p={model['QM_p']}.",
                  f"Residual heterogeneity: QE={model['QE']}, df={model['residual_df']}, p={model['QE_p']}; tau²={model['tau2']}; I²={model['I2_percent']}%.",
                  f"Warning: {model['warning'] or 'none'}", "",
                  "Association or subgroup differences do not establish causality. Study-level moderation can be confounded and correlated effects are unsupported. Source locators and hashes establish local traceability, not correct extraction. This appendix is not a clinical conclusion."]
        (stage / "moderator_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
        receipt = dict(schema="meta-moderator-analysis-v1", status="SYNTHETIC_OR_EXPLORATORY_STATISTICAL_APPENDIX" if not bound or json.loads((stats / "protocol_run_receipt.json").read_text(encoding="utf-8"))["mode"] == "synthetic_test" else "STATISTICAL_APPENDIX_REQUIRES_REVIEW",
                       intent=plan["intent"], bound_protocol=bound, stats_dir=str(stats),
                       source_hashes={"stats_receipt": lit.sha256(stats / "protocol_run_receipt.json") if bound else "DIRECT_NUMERIC_ONLY",
                                      "plan": lit.sha256(a.plan), "moderators": lit.sha256(a.moderators),
                                      "r_script": lit.sha256(script)},
                       outputs={f.name: lit.sha256(f) for f in stage.iterdir() if f.is_file()}, final_report=False)
        (stage / "moderator_receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        if output.exists():
            lit.fail("output path appeared before commit")
        os.replace(stage, output)
    print(f"{receipt['status']}: {output}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for option in ("stats-dir", "plan", "moderators", "rscript", "out"):
        p.add_argument("--" + option, required=True)
    for option in ("confirmation", "protocol"):
        p.add_argument("--" + option)
    a = p.parse_args()
    try:
        run(a)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        p.exit(2, f"Validation: {error}\n")
