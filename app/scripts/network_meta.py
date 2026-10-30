"""Auditable connected-treatment network meta-analysis using netmeta."""
import argparse
import csv
import hashlib
import itertools
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile


FIELDS = ("study_id", "cohort_id", "treat1", "treat2", "TE", "seTE", "effect_type", "outcome",
          "timepoint", "adjustment", "source_file", "source_sha256", "source_location")


def fail(message):
    raise ValueError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def table(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None or any(k not in reader.fieldnames for k in FIELDS):
            fail("network contrast CSV lacks required columns")
        rows = list(reader)
    if len(rows) < 3:
        fail("network needs at least three contrast rows")
    return rows


def plan_check(p):
    if p.get("schema") != "meta-network-plan-v1" or p.get("source_kind") not in {"synthetic_fixture", "package_method_example", "reviewed_extraction"}:
        fail("invalid network plan or source kind")
    for key in ("reference_treatment", "outcome", "timepoint", "adjustment", "effect_direction", "transitivity_rationale"):
        if not isinstance(p.get(key), str) or not p[key].strip():
            fail(f"network plan needs {key}")
    if p.get("effect_type") not in {"MD", "OR", "RR"}:
        fail("network effect type invalid")
    p.setdefault("tau_method", "REML" if p.get("model") == "RE" else "NONE")
    if p.get("model") not in {"FE", "RE"} or p.get("tau_method") not in ({"NONE"} if p.get("model") == "FE" else {"REML", "DL"}):
        fail("network model/tau method mismatch")
    if p.get("small_values") not in {"good", "bad"}:
        fail("ranking direction must be good or bad")
    if p.get("multiarm_policy") not in {"two_arm_only", "allow_complete_multiarm"}:
        fail("multiarm policy must be explicit")
    alpha = p.get("alpha")
    if isinstance(alpha, bool) or not isinstance(alpha, (float, int)) or not math.isfinite(alpha) or not 0 < alpha < .5:
        fail("alpha invalid")
    if p["source_kind"] == "reviewed_extraction" and p.get("review_status") != "human_reviewed_claim":
        fail("real network data needs an explicit human reviewed claim")
    return p


def validate(p, rows):
    plan_check(p)
    studies, cohort_owner, nodes, graph = {}, {}, set(), {}
    for index, r in enumerate(rows, 2):
        if any(r[k] is None or not str(r[k]).strip() for k in FIELDS):
            fail(f"contrast row {index} has blank required field")
        if any(r[k] != p[k] for k in ("effect_type", "outcome", "timepoint", "adjustment")):
            fail(f"contrast row {index} mixes effect scale, outcome, timepoint or adjustment")
        a, b = r["treat1"], r["treat2"]
        if a == b:
            fail(f"contrast row {index} compares a treatment with itself")
        for key in ("TE", "seTE"):
            try:
                r[key] = float(r[key])
            except ValueError:
                fail(f"contrast row {index} has nonnumeric {key}")
            if not math.isfinite(r[key]) or abs(r[key]) > 1e8:
                fail(f"contrast row {index} has nonfinite/extreme {key}")
        if r["seTE"] <= 0:
            fail(f"contrast row {index} needs positive seTE")
        source = Path(r["source_file"]).resolve()
        if not source.is_file() or sha(source) != r["source_sha256"]:
            fail(f"contrast row {index} source missing or changed")
        locator = r["source_location"]
        expected = r"(?:dataset|synthetic) row \d+" if p["source_kind"] != "reviewed_extraction" else r"(?i)(?:page|p\.|table|figure)\s*[A-Za-z0-9]"
        if not re.search(expected, locator):
            fail(f"contrast row {index} lacks source location")
        sid, cohort = r["study_id"], r["cohort_id"]
        if cohort in cohort_owner and cohort_owner[cohort] != sid:
            fail("cohort appears under different study IDs")
        cohort_owner[cohort] = sid
        group = studies.setdefault(sid, {"cohort": cohort, "pairs": set(), "treatments": set(), "rows": []})
        if group["cohort"] != cohort:
            fail("one study ID contains multiple cohorts; split or adjudicate")
        pair = frozenset((a, b))
        if pair in group["pairs"]:
            fail("same study has a repeated treatment comparison")
        group["pairs"].add(pair); group["treatments"].update((a, b)); group["rows"].append(r)
        nodes.update((a, b)); graph.setdefault(a, set()).add(b); graph.setdefault(b, set()).add(a)
    if p["reference_treatment"] not in nodes or len(nodes) < 3:
        fail("reference treatment missing or fewer than three treatments")
    reached = {p["reference_treatment"]}; stack = list(reached)
    while stack:
        for other in graph[stack.pop()]:
            if other not in reached:
                reached.add(other); stack.append(other)
    if reached != nodes:
        fail("treatment network is disconnected")
    multiarm = 0
    for sid, g in studies.items():
        arms = len(g["treatments"])
        expected = {frozenset(pair) for pair in itertools.combinations(g["treatments"], 2)}
        if g["pairs"] != expected:
            fail(f"study {sid} has incomplete multi-arm contrast triangle")
        if arms > 2:
            multiarm += 1
            if p["multiarm_policy"] != "allow_complete_multiarm":
                fail("multi-arm study needs explicit allow_complete_multiarm plan")
    if len(studies) < len(nodes)-1:
        fail("too few independent studies for network treatment effects")
    return len(studies), multiarm, sorted(nodes)


def run(a):
    p = json.loads(Path(a.plan).read_text(encoding="utf-8"))
    rows = table(a.input)
    study_count, multiarm_count, nodes = validate(p, rows)
    output = Path(a.out).resolve()
    if output.exists():
        fail("output already exists")
    binary = shutil.which(a.rscript) or str(Path(a.rscript).resolve())
    if not Path(binary).is_file():
        fail("Rscript missing")
    output.parent.mkdir(parents=True, exist_ok=True)
    script = Path(__file__).with_suffix(".R")
    with tempfile.TemporaryDirectory(prefix=".network-meta-", dir=output.parent) as temp:
        stage = Path(temp) / "result"; stage.mkdir()
        checked = stage / "checked_contrasts.csv"
        with checked.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            writer.writeheader(); writer.writerows({key: r[key] for key in FIELDS} for r in rows)
        engine_plan = stage / "engine_plan.csv"
        with engine_plan.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(p))
            writer.writeheader(); writer.writerow(p)
        process = subprocess.run([binary, str(script), str(checked), str(engine_plan), str(stage)], capture_output=True, text=True)
        if process.returncode:
            fail("netmeta model failed: " + (process.stderr.strip() or process.stdout.strip()))
        required = ("network_summary.csv", "reference_effects.csv", "league_table.csv", "ranking.csv", "local_inconsistency.csv", "network_graph.png", "reference_forest.png")
        if any(not (stage / name).is_file() or (stage / name).stat().st_size == 0 for name in required):
            fail("network result incomplete")
        with (stage / "network_summary.csv").open(encoding="utf-8", newline="") as f:
            summary = list(csv.DictReader(f))
        if len(summary) != 1 or summary[0]["n_treatments"] != str(len(nodes)):
            fail("netmeta network summary invalid")
        s = summary[0]
        if s["tau_method"] != p["tau_method"]:
            fail("actual engine tau estimator differs from the plan")
        report = ["# Network meta-analysis: statistical facts", "",
                  f"Input: {p['source_kind']}; {study_count} independent study IDs, {len(rows)} contrasts, {len(nodes)} connected treatments; {multiarm_count} multi-arm studies.",
                  f"Effect scale: {p['effect_type']} ({'entered log ratio' if p['effect_type'] in ('OR','RR','HR') else 'linear'}); reference: {p['reference_treatment']}; model: {p['model']}/{p['tau_method']}; alpha {p['alpha']}.",
                  f"Global heterogeneity Q={s['Q']}; design-by-treatment inconsistency Q={s['Q_inconsistency']}, df={s['df_inconsistency']}, p={s['p_inconsistency']}; status={s['inconsistency_status']}.",
                  f"Transitivity rationale supplied by user: {p['transitivity_rationale']}",
                  f"Ranking direction supplied by user: {p['small_values']}. P-scores summarize this model's ranking and are not treatment-benefit probabilities or evidence certainty.", "",
                  "Network geometry, transitivity, bias and local incoherence need scientific review. Local source hashes/locators establish file consistency only. Package and synthetic examples are method demonstrations, not new systematic reviews. No clinical recommendation or final publication claim is made."]
        (stage / "network_report.md").write_text("\n".join(report)+"\n", encoding="utf-8")
        receipt = {"schema": "meta-network-result-v1", "status": "METHOD_EXAMPLE_OR_SYNTHETIC" if p["source_kind"] != "reviewed_extraction" else "REVIEWED_EXTRACTION_CLAIM_NEEDS_NETWORK_REVIEW", "final_report": False,
                   "plan_sha256": sha(a.plan), "input_sha256": sha(a.input), "r_script_sha256": sha(script), "figure_script_sha256": sha(script.with_name("network_figures.R")), "planned_tau_method": p["tau_method"], "actual_tau_method": s["tau_method"],
                   "treatments": nodes, "study_count": study_count, "multiarm_study_count": multiarm_count,
                   "source_files": sorted({(str(Path(r["source_file"]).resolve()), r["source_sha256"]) for r in rows}),
                   "outputs": {f.name: sha(f) for f in stage.iterdir() if f.is_file()}}
        (stage / "network_receipt.json").write_text(json.dumps(receipt, indent=2)+"\n", encoding="utf-8")
        os.replace(stage, output)
    print(receipt["status"], output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("input", "plan", "rscript", "out"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    try:
        run(args)
    except (ValueError, OSError, KeyError, TypeError, json.JSONDecodeError, csv.Error) as error:
        parser.exit(2, f"Validation: {error}\n")
