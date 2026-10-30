"""Bind supplied QUADAS-3 selected-estimate judgments to a checked diagnostic draft.

This validates study/result identity and local bytes; it never runs official QUADAS-3
questions, conditional skips, or judgment algorithms.
"""
import argparse
import csv
import json
import os
from pathlib import Path
import tempfile

import diagnostic_project
import diagnostic_word
import literature as lit
import quadas3_import as quadas

FIELDS = ("study_id", "estimate_id", "record_id", "threshold", "accuracy_measure",
          "raw_sensitivity", "raw_specificity", "judgment_rows", "source_location")
MEASURES = {"sensitivity", "specificity", "sensitivity_and_specificity"}


def fail(message):
    raise ValueError(message)


def read_csv(path, required):
    rows, _ = lit.read_csv(path, list(required))
    if any(None in row or any(row.get(key) is None for key in required) for row in rows):
        fail(f"truncated CSV: {path}")
    return rows


def source(path, digest, label):
    if not path.is_file() or not digest or lit.sha256(path) != digest.lower():
        fail(f"{label}: missing or changed file")


def checked_paper(paper_dir, confirmation_dir):
    paper = Path(paper_dir).resolve()
    confirmation = Path(confirmation_dir).resolve() / "diagnostic_confirmation.json"
    manifest = json.loads((paper / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema") != "meta-diagnostic-draft-manifest-v1":
        fail("only a checked bivariate diagnostic manuscript is supported")
    for rel, digest in manifest["files"].items():
        child = (paper / rel).resolve()
        if not child.is_relative_to(paper):
            fail("diagnostic manifest path escapes paper directory")
        source(child, digest, "diagnostic paper " + rel)
    manuscript = json.loads((paper / "manuscript.json").read_text(encoding="utf-8"))
    if manuscript.get("schema") != "meta-diagnostic-manuscript-v1" or manuscript.get("final") is not False:
        fail("diagnostic manuscript is not the supported non-final draft")
    source(confirmation, manuscript["fact_sources"]["confirmation_sha256"], "diagnostic confirmation")
    confirm = json.loads(confirmation.read_text(encoding="utf-8"))
    if confirm.get("schema") != "meta-diagnostic-confirmation-v1":
        fail("invalid diagnostic confirmation")
    for key, path in confirm["input_paths"].items():
        source(Path(path), confirm["hashes"][key], "diagnostic confirmed input " + key)
    protocol = diagnostic_project.protocol_check(confirm["input_paths"]["protocol"])
    if protocol["quality_tool"]["name"] != "QUADAS-3" or protocol["quality_tool"]["version"] != "1.2":
        fail("diagnostic protocol must explicitly select QUADAS-3 v1.2")
    paper_plan = json.loads((paper / "analysis_plan.json").read_text(encoding="utf-8"))
    if paper_plan != protocol["analysis"]:
        fail("diagnostic paper analysis plan differs from confirmed protocol")
    included = read_csv(paper / "included_studies.csv", ("study_id", "record_id"))
    data = read_csv(paper / "statistics" / "checked_2x2.csv",
                    ("study_id", "index_test", "threshold", "outcome", "timepoint"))
    trace = read_csv(paper / "statistics" / "study_2x2_trace.csv",
                     ("study_id", "raw_sensitivity", "raw_specificity", "source_location"))
    by_id = lambda rows: {r["study_id"]: r for r in rows}
    ids = {r["study_id"] for r in included}
    if not ids or len(ids) != len(included) or len(by_id(data)) != len(data) or len(by_id(trace)) != len(trace) or set(by_id(data)) != ids or set(by_id(trace)) != ids:
        fail("included studies, checked 2x2 inputs and raw result trace disagree")
    if len({r["record_id"] for r in included}) != len(included):
        fail("included diagnostic record IDs must be unique")
    return paper, confirmation, protocol, by_id(included), by_id(data), by_id(trace)


def bound_inputs(quadas_dir, paper_dir, confirmation_dir):
    import_dir = Path(quadas_dir).resolve()
    quadas.verify(import_dir)
    qreceipt = json.loads((import_dir / "quadas3_receipt.json").read_text(encoding="utf-8"))
    qplan = json.loads(Path(qreceipt["plan"]).read_text(encoding="utf-8"))
    paper, confirmation, protocol, included, data, trace = checked_paper(paper_dir, confirmation_dir)
    if (qplan["review_mode"] == "synthetic_test") != (protocol["mode"] == "synthetic_test"):
        fail("QUADAS review mode and diagnostic protocol mode disagree")
    qstudies = {s["study_id"]: s for s in qplan["studies"]}
    if len(qstudies) != len(qplan["studies"]) or set(qstudies) != set(included):
        fail("QUADAS assessed studies must equal diagnostic analyzed studies")
    judgment_rows = read_csv(import_dir / "quadas3_judgments.csv",
                             ("study_id", "estimate_id", "dimension", "domain", "judgment"))
    counts = {}
    for row in judgment_rows:
        key = (row["study_id"], row["estimate_id"])
        counts[key] = counts.get(key, 0) + 1
    result = []
    for sid, study in sorted(qstudies.items()):
        entered = data[sid]
        if entered["index_test"] != protocol["pico"]["index_test"] or entered["outcome"] != protocol["pico"]["target_condition"] or entered["timepoint"] != protocol["analysis"]["timepoint"]:
            fail(f"diagnostic study {sid} test, condition or timepoint disagrees with protocol")
        for estimate in study["estimates"]:
            eid = estimate["estimate_id"]
            if (estimate["index_test"] != entered["index_test"] or
                    estimate["target_condition"] != entered["outcome"] or
                    estimate["threshold"] != entered["threshold"] or
                    estimate["accuracy_measure"] not in MEASURES):
                fail(f"QUADAS estimate {sid}/{eid} test, target, threshold or measure does not match analyzed 2x2 result")
            if counts.get((sid, eid)) != 9:
                fail(f"QUADAS estimate {sid}/{eid} lacks nine supplied judgment slots")
            result.append(dict(study_id=sid, estimate_id=eid,
                record_id=included[sid]["record_id"], threshold=entered["threshold"],
                accuracy_measure=estimate["accuracy_measure"],
                raw_sensitivity=trace[sid]["raw_sensitivity"],
                raw_specificity=trace[sid]["raw_specificity"], judgment_rows="9",
                source_location=trace[sid]["source_location"]))
    return import_dir, paper, confirmation, protocol, result


def build(quadas_dir, paper_dir, confirmation_dir, out):
    import_dir, paper, confirmation, protocol, rows = bound_inputs(quadas_dir, paper_dir, confirmation_dir)
    target = Path(out).resolve()
    if target.exists():
        fail("output exists; choose a fresh directory")
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".quadas3-paper-", dir=target.parent) as tmp:
        stage = Path(tmp) / "result"
        stage.mkdir()
        lit.write_csv(stage / "quadas3_estimate_links.csv", FIELDS, rows)
        note = ("These study/record/threshold links and raw ratios come from a checked diagnostic 2x2 draft. "
                "The QUADAS-3 judgments were supplied separately by the declared assessor; "
                "the official signalling questions, reuse rules and algorithms were not run here.")
        lines = ["# QUADAS-3 selected-estimate link to diagnostic draft", "",
                 f"Mode: {protocol['mode']}. Studies: {len({r['study_id'] for r in rows})}. Selected estimates: {len(rows)}.",
                 note, "See `quadas3_estimate_links.csv` for exact links and the imported QUADAS-3 judgment ledger for rationales and cited evidence."]
        (stage / "quadas3_paper_binding.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        table = [["Study / record", "Estimate", "Threshold", "Measure", "Raw sensitivity / specificity"]]
        table += [[r["study_id"] + " / " + r["record_id"], r["estimate_id"], r["threshold"],
                   r["accuracy_measure"], r["raw_sensitivity"] + " / " + r["raw_specificity"]] for r in rows]
        diagnostic_word.write(stage / "quadas3_paper_binding.docx", [
            {"text": "QUADAS-3 selected-estimate evidence link", "style": "Title"},
            {"text": note},
            {"text": "Analyzed result and supplied judgment links", "table": {"title": "Raw study ratios; not model pooled estimates or derived risk judgments", "rows": table}},
        ], [])
        receipt = {"schema": "meta-quadas3-paper-binding-v1", "status":
                   "SYNTHETIC_ESTIMATE_LINKS" if protocol["mode"] == "synthetic_test" else
                   "REVIEWER_DECLARED_ESTIMATE_LINKS_NOT_OFFICIAL_SCORING",
                   "final": False, "official_algorithm_applied": False,
                   "clinical_judgments_verified": False, "identity_authenticated": False,
                   "quadas_dir": str(import_dir), "quadas_receipt_sha256": lit.sha256(import_dir / "quadas3_receipt.json"),
                   "paper_dir": str(paper), "paper_manifest_sha256": lit.sha256(paper / "manifest.json"),
                   "confirmation_dir": str(confirmation.parent), "confirmation_sha256": lit.sha256(confirmation),
                   "study_count": len({r["study_id"] for r in rows}), "estimate_count": len(rows),
                   "outputs": {p.name: lit.sha256(p) for p in stage.iterdir() if p.is_file()}}
        (stage / "quadas3_paper_receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        os.replace(stage, target)
    print(receipt["status"], target)


def verify(out):
    root = Path(out).resolve()
    receipt = json.loads((root / "quadas3_paper_receipt.json").read_text(encoding="utf-8"))
    if receipt.get("schema") != "meta-quadas3-paper-binding-v1" or receipt.get("final") is not False:
        fail("invalid QUADAS-3 paper binding receipt")
    source(Path(receipt["quadas_dir"]) / "quadas3_receipt.json", receipt["quadas_receipt_sha256"], "QUADAS import")
    source(Path(receipt["paper_dir"]) / "manifest.json", receipt["paper_manifest_sha256"], "diagnostic paper manifest")
    source(Path(receipt["confirmation_dir"]) / "diagnostic_confirmation.json", receipt["confirmation_sha256"], "diagnostic confirmation")
    _, _, _, protocol, rows = bound_inputs(receipt["quadas_dir"], receipt["paper_dir"], receipt["confirmation_dir"])
    expected = "SYNTHETIC_ESTIMATE_LINKS" if protocol["mode"] == "synthetic_test" else "REVIEWER_DECLARED_ESTIMATE_LINKS_NOT_OFFICIAL_SCORING"
    if receipt["status"] != expected or len(rows) != receipt["estimate_count"] or len({r["study_id"] for r in rows}) != receipt["study_count"]:
        fail("binding mode or selected-estimate counts changed")
    for name, digest in receipt["outputs"].items():
        source(root / name, digest, "binding output " + name)
    print("QUADAS3_PAPER_BINDING_VERIFIED", root)


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    sub = cli.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build")
    for key in ("quadas-dir", "paper-dir", "confirmation-dir", "out"):
        b.add_argument("--" + key, required=True)
    v = sub.add_parser("verify")
    v.add_argument("--out", required=True)
    args = cli.parse_args()
    try:
        build(args.quadas_dir, args.paper_dir, args.confirmation_dir, args.out) if args.command == "build" else verify(args.out)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        cli.exit(2, "Validation: " + str(exc) + "\n")
