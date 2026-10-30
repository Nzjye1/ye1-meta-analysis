"""Import reviewer-entered QUADAS-3 judgments without reproducing its questionnaire or algorithm.

This is a phase/domain/estimate and evidence-integrity adapter, not an official
implementation of the QUADAS-3 assessment instrument.
"""
import argparse
import csv
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import tempfile

import diagnostic_word


DOMAINS = {
    "risk_of_bias": ("participants", "index_test", "target_condition", "analysis"),
    "applicability": ("participants", "index_test", "target_condition"),
    "overall": ("risk_of_bias", "applicability"),
}
FIELDS = ("study_id", "estimate_id", "dimension", "domain", "judgment",
          "rationale", "evidence_file", "evidence_sha256", "evidence_locator",
          "reviewer", "reviewed_at")


def fail(message):
    raise ValueError(message)


def required_text(value, label):
    if not isinstance(value, str) or not value.strip() or value.strip().upper() in {
            "PENDING", "NOT_SUPPLIED", "TODO", "TBD", "NONE", "NULL"}:
        fail(f"{label}: a completed text value is required")
    return value.strip()


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def resolved(path, base):
    p = Path(path)
    return (p if p.is_absolute() else base / p).resolve()


def checked_file(path, digest, label):
    if not path.is_file() or not digest or sha(path) != digest.lower():
        fail(f"{label}: missing or changed source")


def read_inputs(plan_path, judgments_path):
    plan_path = Path(plan_path).resolve()
    judgments_path = Path(judgments_path).resolve()
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if plan.get("schema") != "meta-quadas3-review-v1" or plan.get("tool") != "QUADAS-3" or plan.get("version") != "1.2":
        fail("this adapter accepts only explicit QUADAS-3 v1.2 review metadata")
    for key in ("review_question", "ideal_test_accuracy_trial"):
        required_text(plan.get(key), f"phase 1/2 {key}")
    if plan.get("review_mode") not in {"synthetic_test", "human_attested"}:
        fail("review_mode must distinguish synthetic_test from human_attested")
    if plan["review_mode"] == "human_attested":
        required_text(plan.get("human_attestation_ref"), "human_attested local attestation reference")
    studies = plan.get("studies")
    if not isinstance(studies, list) or not studies:
        fail("phase 3/4 study and estimate records required")
    expected, flows = set(), {}
    for study in studies:
        if not isinstance(study, dict):
            fail("each study must be a JSON object")
        sid = required_text(study.get("study_id"), "study ID")
        if not sid or sid in flows:
            fail("study IDs must be present and unique")
        flow = resolved(study.get("flow_file", ""), plan_path.parent)
        checked_file(flow, study.get("flow_sha256"), f"study {sid} phase 3 flow")
        flows[sid] = flow
        estimates = study.get("estimates")
        if not isinstance(estimates, list) or not estimates:
            fail(f"study {sid}: phase 4 needs selected accuracy estimates")
        seen = set()
        for estimate in estimates:
            if not isinstance(estimate, dict):
                fail(f"study {sid}: each selected estimate must be a JSON object")
            eid = required_text(estimate.get("estimate_id"), f"study {sid} estimate ID")
            if eid in seen:
                fail(f"study {sid}: selected estimate ID repeated")
            for key in ("index_test", "target_condition", "threshold", "accuracy_measure"):
                required_text(estimate.get(key), f"study {sid} estimate {eid} {key}")
            seen.add(eid)
            for dimension, domains in DOMAINS.items():
                expected.update((sid, eid, dimension, domain) for domain in domains)
    with judgments_path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames is None or any(key not in reader.fieldnames for key in FIELDS):
            fail("judgment CSV lacks required columns")
        rows = list(reader)
    found = set()
    for number, row in enumerate(rows, 2):
        if None in row or any(row.get(field) is None for field in FIELDS):
            fail(f"row {number}: truncated or extra CSV fields")
        key = tuple(row[x].strip() for x in FIELDS[:4])
        if key not in expected or key in found:
            fail(f"row {number}: unknown or repeated estimate/dimension/domain")
        found.add(key)
        if any(not row[x].strip() for x in ("judgment", "rationale", "evidence_file",
                                            "evidence_sha256", "evidence_locator", "reviewer", "reviewed_at")):
            fail(f"row {number}: reviewer judgment and evidence are required")
        try:
            date.fromisoformat(row["reviewed_at"])
        except ValueError:
            fail(f"row {number}: reviewed_at must be YYYY-MM-DD")
        source = resolved(row["evidence_file"], judgments_path.parent)
        checked_file(source, row["evidence_sha256"], f"row {number} evidence")
        row["evidence_file"] = str(source)
    if found != expected:
        fail(f"incomplete phase 5/6 judgments: {len(expected - found)} missing")
    return plan_path, judgments_path, plan, rows, flows


def build(plan_path, judgments_path, out):
    plan_path, judgments_path, plan, rows, flows = read_inputs(plan_path, judgments_path)
    out = Path(out).resolve()
    if out.exists():
        fail("output exists; choose a fresh directory")
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".quadas3-", dir=out.parent) as temp:
        stage = Path(temp) / "result"
        stage.mkdir()
        with (stage / "quadas3_judgments.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows({key: row[key] for key in FIELDS} for row in rows)
        count = sum(len(study["estimates"]) for study in plan["studies"])
        lines = ["# QUADAS-3 v1.2 supplied judgment import", "",
                 f"Mode: {plan['review_mode']}. Studies: {len(flows)}. Selected accuracy estimates: {count}. Judgment rows: {len(rows)}.",
                 "This imports supplied reviewer judgments and evidence locations. It does not run the official signalling-question branching or certify that the tool was completed correctly.",
                 "No clinical or applicability judgment was generated by this adapter."]
        (stage / "quadas3_import.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        summary = [["Study", "Estimate", "Dimension", "Domain", "Reviewer judgment"]]
        summary += [[r["study_id"], r["estimate_id"], r["dimension"], r["domain"], r["judgment"]] for r in rows]
        diagnostic_word.write(stage / "quadas3_import.docx", [
            {"text": "QUADAS-3 supplied judgment import", "style": "Title"},
            {"text": lines[2] + " " + lines[3]},
            {"text": "Supplied judgments by selected accuracy estimate",
             "table": {"title": "Imported judgments; see CSV for rationale, reviewer and exact evidence", "rows": summary}},
        ], [])
        receipt = {"schema": "meta-quadas3-import-v1", "status": "SYNTHETIC_STRUCTURE_TEST" if plan["review_mode"] == "synthetic_test" else "HUMAN_ATTESTED_JUDGMENTS_IMPORTED_NOT_OFFICIAL_TOOL_EXECUTION",
                   "final": False, "tool": "QUADAS-3", "version": "1.2",
                   "review_mode": plan["review_mode"],
                   "official_algorithm_applied": False, "identity_authenticated": False,
                   "plan": str(plan_path), "plan_sha256": sha(plan_path),
                   "judgments": str(judgments_path), "judgments_sha256": sha(judgments_path),
                   "flow_sources": {sid: {"path": str(path), "sha256": sha(path)} for sid, path in flows.items()},
                   "evidence_sources": {r["evidence_file"]: r["evidence_sha256"].lower() for r in rows},
                   "study_count": len(flows), "estimate_count": count, "judgment_count": len(rows),
                   "outputs": {p.name: sha(p) for p in stage.iterdir() if p.is_file()}}
        (stage / "quadas3_receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        os.replace(stage, out)
    print(receipt["status"], out)


def verify(out):
    out = Path(out).resolve()
    receipt = json.loads((out / "quadas3_receipt.json").read_text(encoding="utf-8"))
    if receipt.get("schema") != "meta-quadas3-import-v1" or receipt.get("final") is not False:
        fail("invalid QUADAS-3 import receipt")
    for key in ("plan", "judgments"):
        checked_file(Path(receipt[key]), receipt[key + "_sha256"], key)
    read_inputs(receipt["plan"], receipt["judgments"])
    for sid, item in receipt["flow_sources"].items():
        checked_file(Path(item["path"]), item["sha256"], f"flow {sid}")
    for path, digest in receipt["evidence_sources"].items():
        checked_file(Path(path), digest, "judgment evidence")
    for name, digest in receipt["outputs"].items():
        checked_file(out / name, digest, "output " + name)
    print("QUADAS3_IMPORT_VERIFIED", out)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("build")
    create.add_argument("--plan", required=True)
    create.add_argument("--judgments", required=True)
    create.add_argument("--out", required=True)
    check = sub.add_parser("verify")
    check.add_argument("--out", required=True)
    args = parser.parse_args()
    try:
        build(args.plan, args.judgments, args.out) if args.command == "build" else verify(args.out)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        parser.exit(2, "Validation: " + str(exc) + "\n")
