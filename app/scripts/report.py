"""Assemble a local, explicitly staged evidence packet. No automatic source or RoB judgment."""
import argparse
import csv
from collections import Counter
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

import literature as lit
import review
import prisma2020_flow as prisma


def csv_rows(path, fields, allow_empty=False):
    return lit.read_csv(path, fields, allow_empty=allow_empty)[0]


def nonblank(value):
    return isinstance(value, str) and bool(value.strip())


def valid_date(value, label):
    try:
        dt.date.fromisoformat(value)
    except (TypeError, ValueError):
        lit.fail(f"{label}: date must be YYYY-MM-DD")


def locator(value):
    return bool(re.search(r"(?i)(page|p\.|table|figure|fig\.)\s*[A-Za-z0-9]", value or ""))


def effect_key(row):
    return row["record_id"], row["study_id"]


def verify_sources(effects, ledger_path, corrections_path, prior_path, mode):
    fields = ["record_id", "study_id", "source_document", "source_location", "status",
              "source_file", "source_sha256", "reviewer", "reviewed_at", "note"]
    rows = csv_rows(ledger_path, fields)
    by_effect = {effect_key(e): e for e in effects}
    if len(by_effect) != len(effects):
        lit.fail("effect rows are not uniquely identified by record_id and study_id")
    seen = {}
    for i, row in enumerate(rows, 2):
        key = effect_key(row)
        if key not in by_effect or key in seen:
            lit.fail(f"source review row {i}: unknown or repeated effect")
        effect = by_effect[key]
        if any(row[k] != effect[k] for k in ("source_document", "source_location")):
            lit.fail(f"source review row {i}: document/locator disagrees with extraction")
        if not locator(row["source_location"]):
            lit.fail(f"source review row {i}: locator format missing")
        status = row["status"]
        if status not in {"pending", "human_verified", "synthetic_test"}:
            lit.fail(f"source review row {i}: invalid status")
        if status == "human_verified":
            if not all(nonblank(row[k]) for k in ("source_file", "source_sha256", "reviewer", "reviewed_at", "note")):
                lit.fail(f"source review row {i}: human verification needs file hash, reviewer, date, and note")
            valid_date(row["reviewed_at"], f"source review row {i}")
            path = Path(row["source_file"])
            if not path.is_file() or lit.sha256(path).lower() != row["source_sha256"].lower():
                lit.fail(f"source review row {i}: source file missing or hash changed")
        elif status == "synthetic_test":
            if mode != "synthetic_test" or not all(nonblank(row[k]) for k in ("reviewer", "reviewed_at", "note")):
                lit.fail(f"source review row {i}: synthetic status only valid for labeled test receipt")
            valid_date(row["reviewed_at"], f"source review row {i}")
        seen[key] = row
    if set(seen) != set(by_effect):
        lit.fail("source verification ledger has unreviewed extracted effects")

    correction_fields = ["record_id", "study_id", "field", "prior_value", "current_value",
                         "source_location", "reason", "reviewer", "corrected_at", "prior_effects_sha256"]
    corrections = csv_rows(corrections_path, correction_fields, allow_empty=True)
    if corrections and not prior_path:
        lit.fail("correction rows require --prior-effects")
    prior = csv_rows(prior_path, ["record_id", "study_id"], allow_empty=True) if prior_path else []
    prior_by_key = {effect_key(r): r for r in prior}
    if len(prior_by_key) != len(prior):
        lit.fail("prior extraction has repeated effect keys")
    correction_seen = set()
    allowed_fields = {"estimate", "ci_lower", "ci_upper", "source_document", "source_location",
                      "outcome", "timepoint", "contrast", "adjustment", "effect_type"}
    for i, row in enumerate(corrections, 2):
        key = effect_key(row)
        field = row["field"]
        if key not in by_effect or key not in prior_by_key or field not in allowed_fields or (key, field) in correction_seen:
            lit.fail(f"correction row {i}: unknown effect, field, or repeated correction")
        correction_seen.add((key, field))
        if field not in prior_by_key[key] or field not in by_effect[key]:
            lit.fail(f"correction row {i}: field absent from extraction")
        if prior_by_key[key][field] != row["prior_value"] or by_effect[key][field] != row["current_value"]:
            lit.fail(f"correction row {i}: values disagree with prior/current extraction")
        if row["prior_value"] == row["current_value"] or row["source_location"] != by_effect[key]["source_location"]:
            lit.fail(f"correction row {i}: no change or mismatched locator")
        if not all(nonblank(row[k]) for k in ("reason", "reviewer", "corrected_at")) or not locator(row["source_location"]):
            lit.fail(f"correction row {i}: rationale, reviewer, date, and locator required")
        valid_date(row["corrected_at"], f"correction row {i}")
        if lit.sha256(prior_path).lower() != row["prior_effects_sha256"].lower():
            lit.fail(f"correction row {i}: prior extraction hash mismatch")
    return rows, corrections


def verify_rob(plan_path, ledger_path, mapping, protocol, mode):
    with Path(plan_path).open(encoding="utf-8") as handle:
        plan = json.load(handle)
    if not all(nonblank(plan.get(k)) for k in ("tool_name", "tool_version")):
        lit.fail("RoB plan needs user-supplied tool name and version")
    domains = plan.get("required_domains")
    if not isinstance(domains, list) or not domains or len(domains) != len(set(domains)) or not all(nonblank(x) for x in domains):
        lit.fail("RoB plan needs unique required domain names")
    fields = ["study_id", "outcome", "timepoint", "domain", "status", "judgment",
              "rationale", "evidence_locator", "assessor", "assessed_at"]
    rows = csv_rows(ledger_path, fields)
    studies = {r["study_id"] for r in mapping}
    expected = {(sid, domain) for sid in studies for domain in domains}
    seen = {}
    for i, row in enumerate(rows, 2):
        key = row["study_id"], row["domain"]
        if key not in expected or key in seen:
            lit.fail(f"RoB row {i}: unknown or repeated study/domain")
        if row["outcome"] != protocol["outcome"]["name"] or row["timepoint"] != protocol["outcome"]["timepoint"]:
            lit.fail(f"RoB row {i}: outcome/timepoint disagrees with protocol")
        status = row["status"]
        if status not in {"pending", "human_assessed", "synthetic_test"}:
            lit.fail(f"RoB row {i}: invalid status")
        if status == "human_assessed":
            if not all(nonblank(row[k]) for k in ("judgment", "rationale", "evidence_locator", "assessor", "assessed_at")):
                lit.fail(f"RoB row {i}: human judgment requires rationale, locator, assessor, and date")
            if row["judgment"].lower() == "not_assessed" or not locator(row["evidence_locator"]):
                lit.fail(f"RoB row {i}: unresolved judgment or locator format")
            valid_date(row["assessed_at"], f"RoB row {i}")
        elif status == "synthetic_test":
            if mode != "synthetic_test" or not all(nonblank(row[k]) for k in ("assessor", "assessed_at", "rationale")):
                lit.fail(f"RoB row {i}: synthetic status only valid for test receipt")
            valid_date(row["assessed_at"], f"RoB row {i}")
        else:
            if row["judgment"] not in ("", "not_assessed"):
                lit.fail(f"RoB row {i}: pending row cannot carry a risk judgment")
        seen[key] = row
    if set(seen) != expected:
        lit.fail("RoB ledger has missing required study/domain rows")
    return plan, rows


def check_stats(a, effects, confirmation):
    folder = Path(a.stats_dir)
    run_receipt_path = folder / "protocol_run_receipt.json"
    if not run_receipt_path.is_file():
        lit.fail("protocol-bound R run receipt missing; direct R output cannot be used as a protocol report")
    with run_receipt_path.open(encoding="utf-8") as handle:
        run_receipt = json.load(handle)
    if (run_receipt.get("confirmation_sha256") != lit.sha256(a.confirmation) or
            run_receipt.get("confirmed_input_sha256") != confirmation["input_sha256"] or
            run_receipt.get("mode") != confirmation["mode"]):
        lit.fail("R run is not bound to the current protocol confirmation")
    required_results = {"pooled_result.csv", "study_effects_trace.csv", "forest.png",
                        "reproducibility_manifest.csv", "fact_report.md"}
    if not required_results <= set(run_receipt.get("result_sha256", {})):
        lit.fail("protocol-bound R result hashes incomplete")
    for name, recorded_hash in run_receipt.get("result_sha256", {}).items():
        result_file = folder / name
        if not result_file.is_file() or lit.sha256(result_file) != recorded_hash:
            lit.fail(f"protocol-bound R result changed: {name}")
    manifest = {r["key"]: r["value"] for r in csv_rows(folder / "reproducibility_manifest.csv", ["key", "value"])}
    md5 = lambda path: hashlib.md5(Path(path).read_bytes()).hexdigest()
    if manifest.get("input_md5") != md5(a.effects) or manifest.get("analysis_md5") != md5(a.analysis):
        lit.fail("statistical results were run on different effects or analysis settings")
    pooled = csv_rows(folder / "pooled_result.csv", ["effect_type", "model", "alpha", "k", "pooled",
                                                     "ci_lower", "ci_upper", "Q", "I2_percent", "tau2"])
    plan = csv_rows(a.analysis, ["effect_type", "model", "alpha"])[0]
    if len(pooled) != 1 or pooled[0]["effect_type"] != plan["effect_type"] or pooled[0]["model"] != plan["model"]:
        lit.fail("pooled result disagrees with analysis settings")
    if int(pooled[0]["k"]) != len(effects) or abs(float(pooled[0]["alpha"])-float(plan["alpha"])) > 1e-12:
        lit.fail("pooled result effect count or alpha mismatch")
    if not (folder / "forest.png").is_file() or not (folder / "study_effects_trace.csv").is_file():
        lit.fail("statistical trace or forest missing")
    return pooled[0], manifest


def status_for(mode, source_rows, rob_rows, source=None, extended=None):
    if mode == "synthetic_test":
        return "DRAFT_SYNTHETIC", ["Synthetic test confirmation; no real source or risk assessment claimed"]
    reasons = []
    if any(r["status"] != "human_verified" for r in source_rows):
        reasons.append("Source extraction verification unresolved")
    if any(r["status"] != "human_assessed" for r in rob_rows):
        reasons.append("Risk-of-bias assessment unresolved")
    if source is not None and source.get("search_completeness") != "LIVE_QUERY_COUNT_RECONCILED_LOCAL_CLAIM":
        reasons.append("Search source completeness not established in bound evidence")
    if extended is None:
        reasons.append("Reports-sought/retrieval ledger not attached")
    elif any(extended[key] for key in ("title_abstract_pending", "retrieval_pending", "assessment_pending")):
        reasons.append("Selection/retrieval decisions remain pending in extended flow")
    return ("DRAFT_REVIEW_PENDING", reasons) if reasons else ("REVIEW_READY", ["User-attested local evidence is ready for final human review; origin and identity remain unauthenticated"])


def assemble(a):
    receipt, records, dedup, stages, mapping, effects = review.checked_receipt(a)
    protocol = review.load_protocol(a.protocol)
    count_values, numbers, by_study = review.compute_counts(records, dedup, stages, mapping, effects)
    supplied_counts = {r["metric"]: int(r["count"]) for r in csv_rows(Path(a.counts) / "prisma_counts.csv",
                                                                ["unit", "metric", "count"])}
    if "removed_other_before_screening" not in supplied_counts and numbers["removed_other_before_screening"] == 0:
        supplied_counts["removed_other_before_screening"] = 0  # retained pre-extension count packet
    if supplied_counts != numbers:
        lit.fail("count file disagrees with current reconciled inputs")
    source_count_path = Path(a.counts) / "source_counts.csv"
    source_count_rows = review.compute_source_counts(records, dedup, stages, mapping, effects, numbers)
    if source_count_path.is_file():
        supplied_source_rows = csv_rows(source_count_path, list(source_count_rows[0]))
        if supplied_source_rows != [{key: str(value) for key, value in row.items()}
                                    for row in source_count_rows]:
            lit.fail("source count file disagrees with current reconciled inputs")
    extended = None
    if any((a.prisma_dir, a.source_methods, a.retrieval)):
        if not all((a.prisma_dir, a.source_methods, a.retrieval)):
            lit.fail("extended flow requires --prisma-dir, --source-methods, and --retrieval together")
        _, extended, _, _ = prisma.calculate(a)
        folder = Path(a.prisma_dir)
        flow_rows = csv_rows(folder / "prisma_flow_counts.csv", ["unit", "metric", "count"])
        if {r["metric"]: int(r["count"]) for r in flow_rows} != extended or len(flow_rows) != len(extended):
            lit.fail("extended PRISMA flow counts disagree with current ledgers")
        manifest = {r["key"]: r["value"] for r in csv_rows(folder / "flow_manifest.csv", ["key", "value"])}
        expected = {"confirmation_sha256": a.confirmation,
                    "source_methods_sha256": a.source_methods, "retrieval_sha256": a.retrieval,
                    "prisma_flow_counts_sha256": folder / "prisma_flow_counts.csv",
                    "source_route_counts_sha256": folder / "source_route_counts.csv",
                    "reason_counts_sha256": folder / "reason_counts.csv",
                    "prisma_flow_svg_sha256": folder / "prisma_flow.svg",
                    "prisma_item_audit_sha256": folder / "prisma_item_audit.json"}
        if any(manifest.get(key) != lit.sha256(path) for key, path in expected.items()) or \
                manifest.get("protocol_id") != receipt["protocol_id"]:
            lit.fail("extended PRISMA flow manifest or sources changed")
    source_rows, corrections = verify_sources(effects, a.source_review, a.corrections, a.prior_effects, receipt["mode"])
    rob_plan, rob_rows = verify_rob(a.rob_plan, a.rob_ledger, mapping, protocol, receipt["mode"])
    pooled, stat_manifest = check_stats(a, effects, receipt)
    quality = None
    if a.quality_dir:
        from evidence_quality import verify_quality
        quality = verify_quality(a.quality_dir, a)
    source = receipt.get("source_provenance") or {
        "kind": "legacy_manual_unbound", "search_completeness": "NOT_ESTABLISHED"}
    status, reasons = status_for(receipt["mode"], source_rows, rob_rows, source, extended)
    if quality and quality["status"] == "EXPLORATORY_DRAFT" and receipt["mode"] != "synthetic_test":
        status = "DRAFT_REVIEW_PENDING"
        reasons.append("Attached certainty judgments are single-review exploration")
    if a.require_review_ready and status != "REVIEW_READY":
        lit.fail("review-ready report blocked: " + "; ".join(reasons))

    by_record = {r["record_id"]: r for r in records}
    reports_by_study = {}
    for m in mapping:
        reports_by_study.setdefault(m["study_id"], []).append(m)
    included = []
    for sid, reports in sorted(reports_by_study.items()):
        included.append({"study_id": sid, "report_count": len(reports),
                         "report_ids": "|".join(sorted(r["report_id"] for r in reports)),
                         "record_ids": "|".join(sorted(r["record_id"] for r in reports)),
                         "titles_from_input": " | ".join(by_record[r["record_id"]]["title"] for r in reports),
                         "authors_year_from_input": " | ".join(
                             f"{by_record[r['record_id']]['authors']} ({by_record[r['record_id']]['year']})"
                             for r in reports),
                         "doi_from_input": " | ".join(filter(None, (by_record[r["record_id"]].get("doi", "") for r in reports))),
                         "pmid_from_input": " | ".join(filter(None, (by_record[r["record_id"]].get("pmid", "") for r in reports))),
                         "effect_rows": sum(e["study_id"] == sid for e in effects)})
    correction_counts = {}
    for c in corrections:
        correction_counts[effect_key(c)] = correction_counts.get(effect_key(c), 0) + 1
    source_audit = [{**r, "correction_count": correction_counts.get(effect_key(r), 0)} for r in source_rows]
    source_status_counts = Counter(r["status"] for r in source_rows)
    rob_status_counts = Counter(r["status"] for r in rob_rows)
    source_status_text = ", ".join(f"{status_name}={n}" for status_name, n in sorted(source_status_counts.items()))
    rob_status_text = ", ".join(f"{status_name}={n}" for status_name, n in sorted(rob_status_counts.items()))

    lines = ["# Local meta-analysis evidence packet", "", f"**Status: {status}**", "",
             "This packet combines local records and computed facts. It is not a completed systematic review or an automatically final report.",
             f"Confirmation mode: {receipt['mode']}. " + " ".join(reasons), "",
             "## Protocol and PICO", "", f"Protocol ID: {protocol['protocol_id']}. {protocol['question']}",
             f"Population: {protocol['pico']['population']}; intervention: {protocol['pico']['intervention']}; comparator: {protocol['pico']['comparator']}.",
             f"Eligible designs: {', '.join(protocol['eligible_designs'])}.",
             f"Outcome/timepoint: {protocol['outcome']['name']} / {protocol['outcome']['timepoint']}; effect: {protocol['outcome']['effect_type']}; direction: {protocol['outcome']['direction']}.",
             f"Model: {protocol['analysis']['model']}; tau method: {protocol['analysis']['tau_method']}; test: {protocol['analysis']['test']}; alpha: {protocol['analysis']['alpha']}.",
             f"Sensitivity plan: {'; '.join(protocol['sensitivity_plan'])}.", "",
             "## Bibliography provenance", "",
             f"Source kind: {source['kind']}; search completeness: {source['search_completeness']}.",
             "Local hashes check file consistency and stale changes; a computer owner can rewrite files and hashes. They do not authenticate NCBI origin or a reviewer. Mode and query-review fields are user attestations.",
             "Manual RIS/CSV import does not prove automated or exhaustive retrieval. A PubMed count reconciliation covers one stated query and database only and is not independently authenticated.", "",
             "## Screening flow (local PRISMA subset)", "",
             f"{numbers['identified']} records identified; {numbers['removed_duplicate_by_decision']} explicitly removed as duplicates; {numbers['removed_other_before_screening']} removed for other recorded pre-screen reasons; {numbers['screened_title_abstract']} screened.",
             f"{numbers['full_text_included']} reports included; {numbers['included_unique']} unique studies; {numbers['linked_rows']} linked effect rows. See [flow diagram](flow_subset.svg) and [included studies](included_studies.csv).",
             "Source-specific record/report/effect counts accompany new count outputs; source-specific study counts are not additive.",
             ("An attached extended local flow records reports sought/retrieved and exclusion reasons; it does not certify PRISMA compliance."
              if extended else "This omits reports sought/retrieved and other PRISMA 2020 fields."),
             "Candidate flags do not count as removal; search coverage remains unverified.", "",
             "## Included studies and source review", ""]
    for row in included:
        lines.append(f"- {row['study_id']}: {row['report_count']} report(s), {row['effect_rows']} linked effect(s); report IDs {row['report_ids']}.")
    lines += ["", f"Source review statuses: {source_status_text}.",
              f"Logged corrections: {len(corrections)}. See [source verification](source_verification_audit.csv) and [corrections](corrections.csv).",
              "A locator and local file hash do not prove that an assessor interpreted the source correctly.", "",
              "## Risk-of-bias record", "",
              f"Instrument field supplied by user: {rob_plan['tool_name']} (version {rob_plan['tool_version']}); domain names: {', '.join(rob_plan['required_domains'])}.",
              f"Assessment statuses: {rob_status_text}.",
              "Judgments and evidence are user-entered; no tool questionnaire text or automatic low-risk rating is supplied.", "",
              "## Statistical facts", "",
              f"{pooled['k']} effect rows; pooled {pooled['effect_type']} {pooled['pooled']} ({100*(1-float(pooled['alpha'])):g}% CI {pooled['ci_lower']} to {pooled['ci_upper']}); Q {pooled['Q']}, I² {pooled['I2_percent']}%, tau² {pooled['tau2']}.",
              "See the bound R output for weights, sensitivity results, forest figure, and exact methods.", "",
              "## Input metadata", ""]
    if receipt["mode"] == "synthetic_test":
        lines.append("Synthetic fixture titles are shown in `included_studies.csv`; they are not real references. DOI/PMID placeholders are omitted from this packet.")
    else:
        for m in mapping:
            r = by_record[m["record_id"]]
            parts = [r["authors"], f"({r['year']})", r["title"]]
            if r.get("doi"):
                parts.append("DOI " + r["doi"])
            if r.get("pmid"):
                parts.append("PMID " + r["pmid"])
            lines.append("- " + ". ".join(p for p in parts if p))
    if quality:
        lines += ["", "## Design-specific RoB and outcome certainty appendix", "",
                  f"Attached quality status: {quality['status']}. See [quality report](quality_report.md), "
                  "[Summary of Findings](sof_table.csv), and [design-domain evidence](risk_of_bias_design_audit.csv).",
                  "Certainty and risk judgments are reviewer supplied and locally hash checked, not software-calculated or independently authenticated."]
    lines += ["", "## Limits", "",
              "No automated full-text reading, independent extraction check, exhaustive search claim, publication conclusion, or AI-detection score is provided.",
              "The direct R extraction-table entry remains available but has no protocol/flow certification."]
    if source_count_path.is_file():
        lines += ["", "Source count audit: [source_counts.csv](source_counts.csv)."]
    if extended:
        lines += ["", "Extended selection ledger: [diagram](prisma_flow.svg), [counts](prisma_flow_counts.csv), "
                  "[source routes](source_route_counts.csv), [reasons](reason_counts.csv), and "
                  "[item audit](prisma_item_audit.json). These are user-entered local records."]

    final = Path(a.out)
    if final.exists():
        lit.fail(f"output already exists: {final}")
    final.parent.mkdir(parents=True, exist_ok=True)
    pending = Path(tempfile.mkdtemp(prefix=f".{final.name}.pending-", dir=final.parent))
    try:
        lit.write_csv(pending / "included_studies.csv", list(included[0]) if included else
                      ["study_id", "report_count", "report_ids", "record_ids", "titles_from_input",
                       "authors_year_from_input", "doi_from_input", "pmid_from_input", "effect_rows"], included)
        lit.write_csv(pending / "source_verification_audit.csv", list(source_audit[0]), source_audit)
        lit.write_csv(pending / "risk_of_bias_audit.csv", list(rob_rows[0]), rob_rows)
        if quality:
            for name in ("quality_report.md", "sof_table.csv", "risk_of_bias_design_audit.csv",
                         "quality_receipt.json", "review_decisions.csv"):
                shutil.copyfile(Path(a.quality_dir) / name, pending / name)
        shutil.copyfile(a.corrections, pending / "corrections.csv")
        if source_count_path.is_file():
            shutil.copyfile(source_count_path, pending / "source_counts.csv")
        if extended:
            for name in ("prisma_flow.svg", "prisma_flow_counts.csv", "source_route_counts.csv",
                         "reason_counts.csv", "prisma_item_audit.json", "flow_manifest.csv"):
                shutil.copyfile(Path(a.prisma_dir) / name, pending / name)
        (pending / "flow_subset.svg").write_text(review.flow_svg(numbers), encoding="utf-8")
        (pending / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        (pending / "report_status.json").write_text(json.dumps({"status": status, "reasons": reasons,
                "confirmation_mode": receipt["mode"], "origin_authenticated": False,
                "human_identity_authenticated": False, "extended_flow_attached": bool(extended),
                "quality_attached": bool(quality),
                "certainty_status": quality["status"] if quality else "NOT_ATTACHED",
                "prisma_compliance_authenticated": False, "final_report": False}, indent=2) + "\n", encoding="utf-8")
        source_paths = {key: getattr(a, key) for key in review.INPUTS}
        source_paths.update({"confirmation": a.confirmation, "prisma_counts": Path(a.counts) / "prisma_counts.csv",
                             "source_review": a.source_review, "corrections": a.corrections, "rob_plan": a.rob_plan,
                             "rob_ledger": a.rob_ledger, "pooled_result": Path(a.stats_dir) / "pooled_result.csv"})
        if a.prior_effects:
            source_paths["prior_effects"] = a.prior_effects
        if source_count_path.is_file():
            source_paths["source_counts"] = source_count_path
        if extended:
            source_paths.update({"source_methods": a.source_methods, "retrieval": a.retrieval,
                                 "prisma_flow_manifest": Path(a.prisma_dir) / "flow_manifest.csv"})
        if quality:
            source_paths.update({"quality_receipt": Path(a.quality_dir) / "quality_receipt.json",
                                 "quality_sof": Path(a.quality_dir) / "sof_table.csv",
                                 "quality_report": Path(a.quality_dir) / "quality_report.md"})
        lit.write_csv(pending / "report_manifest.csv", ["key", "value"],
                      [{"key": f"{key}_sha256", "value": lit.sha256(path)} for key, path in source_paths.items()] +
                      [{"key": "R_version", "value": stat_manifest["R_version"]},
                       {"key": "metafor_version", "value": stat_manifest["metafor_version"]}])
        expected = ("included_studies.csv", "source_verification_audit.csv", "risk_of_bias_audit.csv",
                    "corrections.csv", "flow_subset.svg", "report.md", "report_status.json", "report_manifest.csv")
        if any(not (pending / name).is_file() or (pending / name).stat().st_size == 0 for name in expected):
            lit.fail("incomplete report output")
        context={key:(str(Path(value).resolve()) if isinstance(value,str) else value)
                 for key,value in vars(a).items() if key != "out"}
        (pending/"report_inputs.json").write_text(json.dumps(context,indent=2),encoding="utf-8")
        if final.exists():
            lit.fail("final output appeared during assembly")
        os.replace(pending, final)
    finally:
        if pending.exists():
            shutil.rmtree(pending)
    print(f"Wrote {status} evidence packet: {final}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in review.INPUTS:
        parser.add_argument("--" + key.replace("_", "-"), dest=key, required=True)
    for key in ("confirmation", "counts", "source_review", "corrections", "rob_plan", "rob_ledger", "stats_dir", "out"):
        parser.add_argument("--" + key.replace("_", "-"), dest=key, required=True)
    parser.add_argument("--prior-effects", dest="prior_effects")
    parser.add_argument("--prisma-dir")
    parser.add_argument("--source-methods")
    parser.add_argument("--retrieval")
    parser.add_argument("--quality-dir")
    parser.add_argument("--require-review-ready", action="store_true")
    a = parser.parse_args()
    try:
        assemble(a)
    except (ValueError, OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        print(f"Validation: {error}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
