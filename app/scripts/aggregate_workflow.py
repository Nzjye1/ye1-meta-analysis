"""Supplied continuous summary effects to a bounded local report, without a review claim."""
import argparse
import datetime as dt
import json
import math
import re
import subprocess
import sys
from pathlib import Path

import literature as lit
import manuscript
from environment_check import resolve_r

SCHEMA = "meta-aggregate-project-v1"
MODE = "existing_summary_data"
BOUNDARY = (
    "This analysis reproduces supplied author-extracted study-level summary data. "
    "It is not a new systematic review. No new literature search, screening, full-text "
    "extraction verification, independent study eligibility review, risk-of-bias assessment "
    "or certainty assessment was performed by this workflow. Study independence and "
    "source values have not been independently verified."
)
PLAN_FIELDS = ["confirmed", "effect_type", "outcome", "timepoint", "contrast", "adjustment",
               "model", "tau_method", "test", "alpha"]
EFFECT_FIELDS = ["study_id", "cohort_id", "effect_type", "estimate", "ci_lower", "ci_upper",
                 "outcome", "timepoint", "contrast", "adjustment", "source_document", "source_location"]


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def text(value, label):
    if not isinstance(value, str) or not value.strip():
        lit.fail(label + " must be nonblank text")
    return value


def resolve(base, value):
    path = Path(text(value, "input path"))
    return (path if path.is_absolute() else base / path).resolve()


def validate(project):
    """Validate the requested analysis before creating any result directory."""
    project_digest = lit.sha256(project)
    p = load(project)
    if p.get("schema") != SCHEMA or p.get("mode") != MODE:
        lit.fail("explicit meta-aggregate-project-v1 / existing_summary_data required")
    if "stages" in p:
        lit.fail("aggregate mode cannot contain systematic-review stages")
    for key in ("project_id", "question", "population", "direction", "independence_assumption"):
        text(p.get(key), key)
    source = p.get("source", {})
    for key in ("citation", "locator", "supplied_data_description"):
        text(source.get(key), "source " + key)
    if source.get("verification_status") != "not_independently_verified":
        lit.fail("aggregate source verification_status must be not_independently_verified")
    unit = p.get("unit", {})
    if unit.get("status") not in {"reported", "unverified"}:
        lit.fail("unit status must be reported or unverified")
    if unit["status"] == "reported":
        text(unit.get("value"), "reported unit")
        text(unit.get("reference"), "unit reference")
    elif unit.get("value") != "":
        lit.fail("unverified unit must have an empty value; do not infer a time unit")
    if not isinstance(p.get("limitations"), list) or not p["limitations"]:
        lit.fail("explicit limitations list required")
    for item in p["limitations"]:
        text(item, "limitation")
    original = p.get("original_inputs")
    if not isinstance(original, list) or not original:
        lit.fail("original_inputs must preserve supplied source files")
    inputs = {"project": project, "effects": resolve(project.parent, p.get("effects")),
              "analysis": resolve(project.parent, p.get("analysis"))}
    for i, item in enumerate(original, 1):
        inputs[f"original_{i:02d}"] = resolve(project.parent, item)
    for path in inputs.values():
        if not path.is_file():
            lit.fail("missing input: " + str(path))
    validated_hashes = {key: lit.sha256(path) for key, path in inputs.items()}
    if validated_hashes["project"] != project_digest:
        lit.fail("project changed during validation")
    plan, _ = lit.read_csv(inputs["analysis"], PLAN_FIELDS)
    if len(plan) != 1 or plan[0]["confirmed"] != "YES":
        lit.fail("analysis requires one explicit confirmed=YES configuration")
    plan = plan[0]
    # This customer mode is deliberately restricted to continuous generic-IV MD.
    if plan["effect_type"] != "MD":
        lit.fail("aggregate mode currently supports continuous MD only")
    if (plan["model"], plan["tau_method"]) not in {("FE", "NONE"), ("RE", "REML"), ("RE", "DL")}:
        lit.fail("model/tau_method mismatch: use FE/NONE, RE/REML or RE/DL")
    if plan["test"] != "z":
        lit.fail("only z test supported")
    alpha = float(plan["alpha"])
    if not math.isfinite(alpha) or not 0 < alpha < .5:
        lit.fail("alpha must be in (0,0.5)")
    effects, _ = lit.read_csv(inputs["effects"], EFFECT_FIELDS)
    if len(effects) < 2:
        lit.fail("at least two independent study effects required")
    for key in ("study_id", "cohort_id"):
        if len({r[key] for r in effects}) != len(effects):
            lit.fail("duplicate " + key + "; resolve dependence before pooling")
    source_paths = {inputs[f"original_{i:02d}"] for i in range(1, len(original) + 1)}
    for row in effects:
        for key in EFFECT_FIELDS:
            text(row[key], "effect " + key)
        for key in ("effect_type", "outcome", "timepoint", "contrast", "adjustment"):
            if row[key] != plan[key]:
                lit.fail("mixed or mismatched " + key)
        if resolve(inputs["effects"].parent, row["source_document"]) not in source_paths:
            lit.fail("effect source_document must name a preserved original input")
        if not re.search(r"(?i)(page|p\.|table|figure|fig\.)\s*[A-Za-z0-9]", row["source_location"]):
            lit.fail("effect source_location needs a page, table or figure identifier")
        lo, est, hi = [float(row[key]) for key in ("ci_lower", "estimate", "ci_upper")]
        if not all(math.isfinite(v) for v in (lo, est, hi)) or not lo < est < hi:
            lit.fail("finite CI must strictly contain estimate")
    if any(lit.sha256(path) != validated_hashes[key] for key, path in inputs.items()):
        lit.fail("input changed during validation")
    return p, plan, effects, inputs, validated_hashes


def files(path):
    return {p.relative_to(path).as_posix(): lit.sha256(p) for p in path.rglob("*") if p.is_file()
            and p != path / "workflow_receipt.json"}


def report(root, project, plan, effects):
    stats = root / "statistics"
    result = lit.read_csv(stats / "pooled_result.csv", ["pooled", "ci_lower", "ci_upper"])[0][0]
    unit = project["unit"]
    unit_label = unit["value"] if unit["status"] == "reported" else "UNVERIFIED unit; no time unit inferred"
    method = "fixed effect inverse variance" if plan["model"] == "FE" else (
        "random effects with DerSimonian-Laird (DL) tau2" if plan["tau_method"] == "DL" else "random effects with REML tau2")
    ci_pct = 100 * (1 - float(plan["alpha"]))
    f = lambda value: format(float(value), ".10g")
    paragraphs = []
    def add(key, value, style="Normal"):
        paragraphs.append(dict(id=key, text=value, style=style))
    add("title", "Supplied summary data analysis", "Title")
    add("question", project["question"])
    add("boundary", "DRAFT FOR HUMAN REVIEW. " + BOUNDARY)
    add("source_heading", "Source and scope", "Heading1")
    add("source", project["source"]["citation"] + "; " + project["source"]["locator"] + ". " + project["source"]["supplied_data_description"])
    add("population", "Population as supplied: " + project["population"] + ". " + project["independence_assumption"])
    add("methods_heading", "Analysis methods", "Heading1")
    add("methods", f"Prespecified configuration: MD; {method}; normal z intervals; alpha={plan['alpha']}. "
        f"Outcome: {plan['outcome']}; timepoint: {plan['timepoint']}; contrast: {plan['contrast']}; adjustment: {plan['adjustment']}. "
        "The supplied effect confidence intervals are interpreted at this alpha and used to derive standard errors on the MD scale. "
        "No model selection, heterogeneity threshold switching or answer matching is performed. The same estimator is retained for each leave-one-out fit.")
    add("unit", "Unit: " + unit_label + ". Direction: " + project["direction"] + ".")
    add("results_heading", "Numerical results", "Heading1")
    add("results", f"Supplied study effects: {len(effects)}. Pooled MD={f(result['pooled'])} ({ci_pct:g}% CI {f(result['ci_lower'])} to {f(result['ci_upper'])}); "
        f"Q={f(result['Q'])}, Q p={f(result['Q_p'])}, I2={f(result['I2_percent'])}%, tau2={f(result['tau2'])}. "
        + ("Fixed effect constrains tau2 to zero." if plan["model"] == "FE" else "Tau2 uses the prespecified estimator."))
    loo_file = stats / "leave_one_out.csv"
    if loo_file.is_file():
        loo = lit.read_csv(loo_file, ["omitted_study", "pooled", "ci_lower", "ci_upper"])[0]
        add("loo", f"Leave-one-out analyses: {len(loo)}. Pooled MD range {f(min(float(r['pooled']) for r in loo))} to {f(max(float(r['pooled']) for r in loo))}. "
            "Each omission and its interval are in the attached leave_one_out.csv. No source study is automatically excluded.")
    else:
        add("loo", "Leave-one-out was not estimated because fewer than three study effects were supplied; omitting one would leave fewer than two.")
    add("limitations_heading", "Interpretation limits", "Heading1")
    for i, item in enumerate(project["limitations"]):
        add("limit_" + str(i), item)
    add("interpretation", "No clinical recommendation, publication-ready conclusion, PRISMA compliance or complete systematic-review claim follows from these computations. Original study values, independence, units and applicability need researcher verification.")
    add("audit", "The inputs directory retains byte-for-byte source files, effects, analysis settings and the project. analysis_binding.json records their SHA256 hashes before computation. Statistical trace and software versions accompany this report. workflow_receipt.json binds all generated files.")
    attachments = {name: str(stats / name) for name in ("forest.png", "pooled_result.csv", "study_effects_trace.csv", "fact_report.md", "confirmed_analysis.csv", "reproducibility_manifest.csv")}
    attachments["forest.png"] = str(stats / "forest_display.png")
    attachments["native_engine_forest.png"] = str(stats / "forest.png")
    if loo_file.is_file():
        attachments["leave_one_out.csv"] = str(loo_file)
    document = dict(schema="meta-aggregate-report-v1", mode=MODE, synthetic=False,
                    paragraphs=paragraphs, attachments=attachments,
                    source_semantics_verified=False, systematic_review=False)
    manuscript.write_output(root / "paper", document)


def run(a):
    project_path = Path(a.project).resolve()
    project, plan, effects, inputs, validated_hashes = validate(project_path)
    root = Path(a.out).resolve()
    if root.exists():
        lit.fail("output already exists; aggregate runs require a fresh directory")
    if getattr(a, "resume", False):
        lit.fail("aggregate mode has no resume; choose a fresh directory")
    binary = resolve_r(a.rscript)
    if not binary or not Path(binary).is_file():
        lit.fail("Rscript unavailable: supply --rscript or META_RSCRIPT")
    root.mkdir(parents=True)
    receipt = dict(schema="meta-aggregate-workflow-v1", mode=MODE, status="BINDING",
                   systematic_review=False, source_semantics_verified=False, events=[])
    def save():
        dump(root / "workflow_receipt.json", receipt)
    save()
    try:
        snapshot = root / "inputs"
        snapshot.mkdir()
        entries = {}
        for key, path in inputs.items():
            target = snapshot / (key + path.suffix)
            raw = path.read_bytes()
            target.write_bytes(raw)
            digest = lit.sha256(target)
            if lit.sha256(path) != digest or digest != validated_hashes[key]:
                lit.fail("input changed during binding: " + key)
            entries[key] = dict(original=str(path), snapshot=target.relative_to(root).as_posix(), sha256=digest)
        # Configuration is frozen before R starts. No review receipt is synthesized.
        scripts = {name: lit.sha256(Path(__file__).with_name(name)) for name in
                   ("aggregate_workflow.py", "run_meta.R", "runtime_library.R", "render_forest.R", "manuscript.py", "literature.py")}
        binding = dict(schema="meta-aggregate-binding-v1", mode=MODE,
                       bound_at=dt.datetime.now(dt.timezone.utc).isoformat(), analysis=plan,
                       boundary=BOUNDARY, inputs=entries, script_sha256=scripts)
        dump(root / "analysis_binding.json", binding)
        receipt.update(status="RUNNING", binding_sha256=lit.sha256(root / "analysis_binding.json"))
        save()
        command = [binary, str(Path(__file__).with_name("run_meta.R")),
                   str(root / entries["effects"]["snapshot"]), str(root / entries["analysis"]["snapshot"]), str(root / "statistics")]
        proc = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
        receipt["events"].append(dict(stage="statistics", command=command, exit_code=proc.returncode, stdout=proc.stdout, stderr=proc.stderr))
        save()
        if proc.returncode:
            lit.fail("statistical engine failed; see workflow_receipt.json")
        # Report unit and mode accompany the numerical fact report and forest.
        stats = root / "statistics"
        fact = stats / "fact_report.md"
        fact.write_text(fact.read_text(encoding="utf-8") + "\n## Supplied data scope\n\n" + BOUNDARY +
                        "\n\nUnit: " + (project["unit"]["value"] if project["unit"]["status"] == "reported" else "UNVERIFIED; no time unit inferred") + "\n", encoding="utf-8")
        # Presentation only; stored estimates and CI are not refitted.
        display = [binary, str(Path(__file__).with_name("render_forest.R")),
                   str(stats / "study_effects_trace.csv"), str(stats / "pooled_result.csv"),
                   str(stats / "forest_display.png"),
                   project["unit"]["value"] if project["unit"]["status"] == "reported" else "unit unverified",
                   project["direction"], "Supplied summary data " + plan["model"] + "/" + plan["tau_method"]]
        drawn = subprocess.run(display, capture_output=True, text=True, encoding="utf-8", errors="replace")
        receipt["events"].append(dict(stage="forest_display", command=display, exit_code=drawn.returncode, stdout=drawn.stdout, stderr=drawn.stderr))
        if drawn.returncode:
            lit.fail("forest presentation failed; see workflow_receipt.json")
        # Keep the native engine forest alongside the explicitly labelled display.
        report(root, project, plan, effects)
        for key, item in entries.items():
            if lit.sha256(root / item["snapshot"]) != item["sha256"] or lit.sha256(item["original"]) != item["sha256"]:
                lit.fail("input changed during execution: " + key)
        receipt.update(status="COMPLETED", result_sha256=files(root),
                       meaning="local supplied-data computation and non-final report; no systematic review or scientific approval")
        save()
    except Exception as error:
        receipt.update(status="NEEDS_ATTENTION", error=str(error))
        save()
        raise
    print("Completed supplied summary data analysis and non-final Word report: " + str(root))


def verify(a):
    root = Path(a.run).resolve()
    receipt = load(root / "workflow_receipt.json")
    if receipt.get("schema") != "meta-aggregate-workflow-v1" or receipt.get("status") != "COMPLETED":
        lit.fail("completed aggregate receipt required")
    if files(root) != receipt["result_sha256"]:
        lit.fail("aggregate output changed")
    if lit.sha256(root / "analysis_binding.json") != receipt["binding_sha256"]:
        lit.fail("analysis binding changed")
    binding = load(root / "analysis_binding.json")
    for item in binding["inputs"].values():
        snapshot = (root / item["snapshot"]).resolve()
        if not snapshot.is_relative_to(root / "inputs") or lit.sha256(snapshot) != item["sha256"]:
            lit.fail("bound input changed")
        if not Path(item["original"]).is_file() or lit.sha256(item["original"]) != item["sha256"]:
            lit.fail("original input missing or changed")
    print("VERIFIED supplied-data inputs and outputs; scientific validity not certified")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    v = sub.add_parser("verify")
    v.add_argument("--run", required=True)
    v.set_defaults(func=verify)
    a = parser.parse_args()
    try:
        a.func(a)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(2, f"Validation: {error}\n")
