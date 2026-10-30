"""Bind reviewer-supplied RoB 2 / ROBINS-I assessment files to a checked outcome packet.

No questionnaire text, signalling rules, or official judgment algorithm is included.
"""
import argparse
import csv
from datetime import date
import json
import os
from pathlib import Path
import tempfile

import diagnostic_word
import evidence_quality as quality
import literature as lit


FIELDS = ("study_id", "record_id", "tool", "version", "effect_of_interest",
          "overall_judgment", "assessment_file", "assessment_sha256",
          "assessment_locator", "reviewer", "assessed_at", "completion_declaration")
TOOLS = {
    ("randomized", "RoB 2", "22 August 2019"):
        ("assignment", "adherence"),
    ("nonrandomized_intervention", "ROBINS-I", "2016"):
        ("intention_to_treat", "per_protocol"),
    ("nonrandomized_intervention", "ROBINS-I", "V2 Nov 2025 draft"):
        ("intention_to_treat", "per_protocol"),
}


def error(message):
    raise ValueError(message)


def source(path, digest, label):
    if not path.is_file() or not digest or lit.sha256(path) != digest.lower():
        error(f"{label}: missing or changed file")


def bound_inputs(quality_dir, assessments):
    root = Path(quality_dir).resolve()
    receipt = quality.verify_quality(root)
    _, plan, _, _, included, effects, designs = quality.checked_plan(receipt["plan_dir"])
    audit, _ = lit.read_csv(root / "risk_of_bias_design_audit.csv",
                            ["study_id", "domain", "judgment", "instrument_name", "instrument_version"])
    overall = {r["study_id"]: r for r in audit if r["domain"] == "overall"}
    expected = {sid for sid, item in designs.items() if item["design_type"] in
                {"randomized", "nonrandomized_intervention"}}
    if not expected:
        error("no randomized or nonrandomized-intervention studies in this quality result")
    effect_ids = {r["study_id"]: r["record_id"] for r in effects}
    path = Path(assessments).resolve()
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames is None or any(f not in reader.fieldnames for f in FIELDS):
            error("assessment CSV lacks required columns")
        rows = list(reader)
    seen = set()
    for n, row in enumerate(rows, 2):
        if None in row or any(row.get(f) is None for f in FIELDS):
            error(f"row {n}: truncated or extra CSV fields")
        sid = row["study_id"].strip()
        if sid not in expected or sid in seen:
            error(f"row {n}: unknown, ineligible, or repeated study")
        seen.add(sid)
        design = designs[sid]
        tool_key = (design["design_type"], row["tool"], row["version"])
        if tool_key not in TOOLS or row["effect_of_interest"] not in TOOLS[tool_key]:
            error(f"row {n}: tool/version/effect does not fit this study design")
        if (design["instrument_name"], design["instrument_version"]) != (row["tool"], row["version"]):
            error(f"row {n}: tool/version disagrees with frozen quality plan")
        if row["record_id"] != effect_ids[sid]:
            error(f"row {n}: record ID differs from bound analyzed effect")
        if row["overall_judgment"] != overall[sid]["judgment"]:
            error(f"row {n}: submitted overall claim conflicts with reviewed quality overall judgment")
        if row["completion_declaration"] != "reviewer_declares_completed":
            error(f"row {n}: completed external assessment declaration required")
        for f in ("assessment_locator", "reviewer"):
            if not row[f].strip():
                error(f"row {n}: {f} required")
        try:
            date.fromisoformat(row["assessed_at"])
        except ValueError:
            error(f"row {n}: assessed_at must be YYYY-MM-DD")
        file = Path(row["assessment_file"])
        file = (file if file.is_absolute() else path.parent / file).resolve()
        if file.suffix.lower() not in {".docx", ".xlsx", ".pdf", ".csv"}:
            error(f"row {n}: external assessment must be DOCX, XLSX, PDF, or CSV")
        source(file, row["assessment_sha256"], f"row {n} assessment")
        row["assessment_file"] = str(file)
        row["assessment_sha256"] = row["assessment_sha256"].lower()
    if seen != expected:
        error(f"one completed assessment per eligible study required; missing {sorted(expected - seen)}")
    return root, receipt, plan, path, rows


def build(quality_dir, assessments, out, mode):
    if mode not in {"synthetic_test", "reviewer_declared"}:
        error("mode must be synthetic_test or reviewer_declared")
    root, receipt, plan, path, rows = bound_inputs(quality_dir, assessments)
    if mode == "reviewer_declared" and receipt["status"] != "FORMAL_REVIEWED":
        error("reviewer_declared needs a completed formal dual quality result")
    target = Path(out).resolve()
    if target.exists():
        error("output exists; choose a fresh directory")
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".official-rob-binding-", dir=target.parent) as tmp:
        stage = Path(tmp) / "result"
        stage.mkdir()
        lit.write_csv(stage / "official_rob_assessments.csv", FIELDS, rows)
        title = "Externally completed RoB assessment evidence binding"
        note = ("Supplied overall judgments match the checked quality ledger. The external files "
                "are referenced and hashed; their questionnaire completion, algorithm and clinical "
                "reasoning are not verified by this software. Reviewer names are self-declared.")
        lines = ["# " + title, "", f"Mode: {mode}. Quality status: {receipt['status']}.",
                 f"Outcome: {plan['outcome']}; timepoint: {plan['timepoint']}.", note, "",
                 "| Study | Record | Tool/version | Effect of interest | Overall judgment | Assessment file/location |",
                 "|---|---|---|---|---|---|"]
        for r in rows:
            lines.append("| " + " | ".join((r["study_id"], r["record_id"],
                r["tool"] + " " + r["version"], r["effect_of_interest"],
                r["overall_judgment"], r["assessment_file"] + " [" + r["assessment_locator"] + "]")) + " |")
        (stage / "official_rob_binding.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        table = [["Study / record", "Tool / version", "Effect", "Overall", "Source location"]]
        table += [[r["study_id"] + " / " + r["record_id"], r["tool"] + " " + r["version"],
                   r["effect_of_interest"], r["overall_judgment"], r["assessment_locator"]] for r in rows]
        diagnostic_word.write(stage / "official_rob_binding.docx", [
            {"text": title, "style": "Title"},
            {"text": f"{plan['outcome']} at {plan['timepoint']}. {note}"},
            {"text": "External assessment references", "table": {"title": "Reviewer-supplied results; exact file paths and hashes are in CSV", "rows": table}},
        ], [])
        result = {"schema": "meta-official-rob-binding-v1", "status":
                  "SYNTHETIC_EXTERNAL_ASSESSMENT_BINDING" if mode == "synthetic_test" else
                  "REVIEWER_DECLARED_EXTERNAL_ASSESSMENTS_NOT_ALGORITHM_VERIFIED",
                  "final": False, "mode": mode, "official_algorithm_applied": False,
                  "official_questionnaire_checked": False, "identity_authenticated": False,
                  "quality_dir": str(root), "quality_receipt_sha256": lit.sha256(root / "quality_receipt.json"),
                  "assessments_path": str(path), "assessments_sha256": lit.sha256(path),
                  "assessment_sources": {r["assessment_file"]: r["assessment_sha256"] for r in rows},
                  "study_count": len(rows), "outcome": plan["outcome"], "timepoint": plan["timepoint"],
                  "outputs": {p.name: lit.sha256(p) for p in stage.iterdir() if p.is_file()}}
        (stage / "official_rob_binding_receipt.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        os.replace(stage, target)
    print(result["status"], target)


def verify(out):
    root = Path(out).resolve()
    receipt = json.loads((root / "official_rob_binding_receipt.json").read_text(encoding="utf-8"))
    if receipt.get("schema") != "meta-official-rob-binding-v1" or receipt.get("final") is not False:
        error("invalid external RoB binding receipt")
    quality_dir = Path(receipt["quality_dir"])
    source(quality_dir / "quality_receipt.json", receipt["quality_receipt_sha256"], "quality receipt")
    source(Path(receipt["assessments_path"]), receipt["assessments_sha256"], "assessment CSV")
    _, quality_receipt, plan, _, rows = bound_inputs(quality_dir, receipt["assessments_path"])
    status_by_mode = {"synthetic_test": "SYNTHETIC_EXTERNAL_ASSESSMENT_BINDING",
                      "reviewer_declared": "REVIEWER_DECLARED_EXTERNAL_ASSESSMENTS_NOT_ALGORITHM_VERIFIED"}
    if receipt.get("status") != status_by_mode.get(receipt.get("mode")) or (
            receipt["mode"] == "reviewer_declared" and quality_receipt["status"] != "FORMAL_REVIEWED"):
        error("binding status or reviewer mode disagrees with checked quality result")
    if (len(rows), plan["outcome"], plan["timepoint"]) != (receipt["study_count"], receipt["outcome"], receipt["timepoint"]):
        error("bound outcome, timepoint, or study count changed")
    if {r["assessment_file"]: r["assessment_sha256"] for r in rows} != receipt["assessment_sources"]:
        error("external assessment files changed")
    for name, digest in receipt["outputs"].items():
        source(root / name, digest, "output " + name)
    print("OFFICIAL_ROB_BINDING_VERIFIED", root)


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    sub = cli.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build")
    b.add_argument("--quality-dir", required=True)
    b.add_argument("--assessments", required=True)
    b.add_argument("--mode", choices=("synthetic_test", "reviewer_declared"), required=True)
    b.add_argument("--out", required=True)
    v = sub.add_parser("verify")
    v.add_argument("--out", required=True)
    args = cli.parse_args()
    try:
        build(args.quality_dir, args.assessments, args.out, args.mode) if args.command == "build" else verify(args.out)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        cli.exit(2, "Validation: " + str(exc) + "\n")
