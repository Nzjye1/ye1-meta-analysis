"""Local design-specific RoB evidence and outcome-level GRADE/SoF ledger; human judgments only."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
from types import SimpleNamespace

import literature as lit
import report as packet_report
import review

# Generic evidence slots. These are not instrument questionnaires or official scoring algorithms.
DESIGN_DOMAINS = {
    "randomized": ("allocation_process", "departures_from_plan", "missing_outcome_data",
                   "outcome_measurement", "selective_result_reporting"),
    "nonrandomized_intervention": ("baseline_confounding", "participant_selection",
                   "intervention_definition", "departures_from_plan", "missing_outcome_data",
                   "outcome_measurement", "selective_result_reporting"),
    "observational_exposure": ("exposure_confounding", "participant_selection",
                   "exposure_measurement", "missing_outcome_data", "outcome_measurement",
                   "selective_result_reporting"),
    "diagnostic_accuracy": ("patient_sampling", "index_test_measurement",
                   "reference_standard", "test_flow_and_timing"),
    "single_group": ("sampling_frame", "outcome_measurement", "missing_data",
                     "selective_result_reporting"),
}
ROB_JUDGMENTS = {
    "randomized": {"low", "some_concerns", "high"},
    "nonrandomized_intervention": {"low", "moderate", "serious", "critical", "no_information"},
    "observational_exposure": {"low", "moderate", "serious", "critical", "no_information"},
    "diagnostic_accuracy": {"low", "high", "unclear"},
    "single_group": {"low", "some_concerns", "high"},
}
GRADE_DOMAINS = ("risk_of_bias", "inconsistency", "indirectness", "imprecision", "publication_bias")
GRADE_JUDGMENTS = {"no_serious_concern", "serious", "very_serious", "not_assessed"}
CERTAINTY = {"high", "moderate", "low", "very_low"}
DESIGN_FIELDS = ["study_id", "design_type", "instrument_name", "instrument_version",
                 "instrument_reference", "design_note"]
VOTE_FIELDS = ["item_type", "study_id", "domain", "status", "judgment", "rationale",
               "evidence_file", "evidence_sha256", "evidence_locator", "reviewer", "reviewed_at"]
ADJ_FIELDS = VOTE_FIELDS + ["adjudication_reason"]
SUGGEST_FIELDS = ["item_type", "study_id", "domain", "proposed_judgment", "rationale",
                  "evidence_file", "evidence_sha256", "evidence_locator", "evidence_excerpt",
                  "agent_id", "suggested_at"]


def day(value, label):
    try:
        return dt.date.fromisoformat(value)
    except (ValueError, TypeError):
        lit.fail(f"{label}: YYYY-MM-DD required")


def packet(a):
    root = Path(a).resolve()
    args = SimpleNamespace(**json.loads((root / "report_inputs.json").read_text(encoding="utf-8")))
    manifest, _ = lit.read_csv(root / "report_manifest.csv", ["key", "value"])
    values = {r["key"]: r["value"] for r in manifest}
    if len(values) != len(manifest):
        lit.fail("repeated report manifest key")
    special = {"prisma_counts": Path(args.counts) / "prisma_counts.csv",
               "source_counts": Path(args.counts) / "source_counts.csv",
               "pooled_result": Path(args.stats_dir) / "pooled_result.csv",
               "prisma_flow_manifest": Path(args.prisma_dir) / "flow_manifest.csv" if args.prisma_dir else None,
               "quality_receipt": Path(args.quality_dir) / "quality_receipt.json" if args.quality_dir else None,
               "quality_sof": Path(args.quality_dir) / "sof_table.csv" if args.quality_dir else None,
               "quality_report": Path(args.quality_dir) / "quality_report.md" if args.quality_dir else None}
    for key, digest in values.items():
        if not key.endswith("_sha256"):
            continue
        name = key[:-7]
        path = special.get(name) if name in special else getattr(args, name, None)
        if not path or not Path(path).is_file() or lit.sha256(path) != digest:
            lit.fail(f"underlying evidence packet source changed: {name}")
    receipt, records, dedup, stages, mapping, effects = review.checked_receipt(args)
    packet_report.check_stats(args, effects, receipt)
    included, _ = lit.read_csv(root / "included_studies.csv", ["study_id", "record_ids", "effect_rows"])
    studies = {r["study_id"] for r in included}
    if len(studies) != len(included) or studies != {e["study_id"] for e in effects}:
        lit.fail("packet included-study table disagrees with bound effects")
    return root, args, receipt, included, effects


def designs(path, included):
    rows, _ = lit.read_csv(path, DESIGN_FIELDS)
    by_study = {r["study_id"]: r for r in rows}
    if len(by_study) != len(rows) or set(by_study) != {r["study_id"] for r in included}:
        lit.fail("study-design ledger needs exactly one row per included study")
    for i, row in enumerate(rows, 2):
        if row["design_type"] not in DESIGN_DOMAINS or any(not (row.get(k) or "").strip()
                for k in ("instrument_name", "instrument_version", "instrument_reference", "design_note")):
            lit.fail(f"study-design row {i}: design or user-supplied instrument metadata missing")
    return by_study


def keys(by_study):
    expected = {("rob_domain", sid, domain) for sid, row in by_study.items()
                for domain in DESIGN_DOMAINS[row["design_type"]]}
    expected |= {("rob_overall", sid, "overall") for sid in by_study}
    expected |= {("grade_domain", "", domain) for domain in GRADE_DOMAINS}
    expected.add(("grade_overall", "", "overall"))
    return expected


def plan(a):
    root, args, receipt, included, effects = packet(a.packet)
    by_study = designs(a.designs, included)
    expected = sorted(keys(by_study))
    out = Path(a.out).resolve()
    if out.exists():
        lit.fail("output exists; use a fresh quality plan directory")
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".quality-plan-", dir=out.parent) as tmp:
        stage = Path(tmp) / "result"
        stage.mkdir()
        template = [dict(item_type=kind, study_id=sid, domain=domain, status="pending", judgment="",
                         rationale="", evidence_file="", evidence_sha256="", evidence_locator="",
                         reviewer="", reviewed_at="") for kind, sid, domain in expected]
        lit.write_csv(stage / "reviewer_template.csv", VOTE_FIELDS, template)
        lit.write_csv(stage / "adjudication_template.csv", ADJ_FIELDS, [])
        lit.write_csv(stage / "study_designs.csv", DESIGN_FIELDS,
                      [by_study[sid] for sid in sorted(by_study)])
        p = review.load_protocol(args.protocol)
        body = dict(schema="meta-quality-plan-v1", protocol_id=p["protocol_id"],
                    outcome=p["outcome"]["name"], timepoint=p["outcome"]["timepoint"],
                    effect_type=p["outcome"]["effect_type"],
                    measurement_unit=p["outcome"].get("unit") or "UNIT_NOT_SUPPLIED", packet_dir=str(root),
                    packet_manifest_sha256=lit.sha256(root / "report_manifest.csv"),
                    packet_status_sha256=lit.sha256(root / "report_status.json"),
                    included_studies_sha256=lit.sha256(root / "included_studies.csv"),
                    confirmation_sha256=lit.sha256(args.confirmation),
                    pooled_result_sha256=lit.sha256(Path(args.stats_dir) / "pooled_result.csv"),
                    designs_path=str(Path(a.designs).resolve()), designs_sha256=lit.sha256(a.designs),
                    template_sha256=lit.sha256(stage / "reviewer_template.csv"),
                    status="PENDING_JUDGMENT", meaning="generic domain evidence slots; no official tool scoring")
        (stage / "quality_plan.json").write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
        os.replace(stage, out)
    print(f"PENDING_JUDGMENT: {len(by_study)} studies, {len(expected)} domain/overall rows; {out}")


def checked_plan(path):
    folder = Path(path).resolve()
    p = json.loads((folder / "quality_plan.json").read_text(encoding="utf-8"))
    if p.get("schema") != "meta-quality-plan-v1" or p.get("status") != "PENDING_JUDGMENT":
        lit.fail("invalid quality plan")
    for key, source in (("packet_manifest_sha256", Path(p["packet_dir"]) / "report_manifest.csv"),
                        ("packet_status_sha256", Path(p["packet_dir"]) / "report_status.json"),
                        ("included_studies_sha256", Path(p["packet_dir"]) / "included_studies.csv"),
                        ("designs_sha256", p["designs_path"]),
                        ("template_sha256", folder / "reviewer_template.csv")):
        if not Path(source).is_file() or lit.sha256(source) != p[key]:
            lit.fail(f"quality plan input changed: {key}")
    root, args, receipt, included, effects = packet(p["packet_dir"])
    if lit.sha256(args.confirmation) != p["confirmation_sha256"] or lit.sha256(
            Path(args.stats_dir) / "pooled_result.csv") != p["pooled_result_sha256"]:
        lit.fail("quality plan confirmation or statistics changed")
    by_study = designs(p["designs_path"], included)
    return folder, p, root, args, included, effects, by_study


def check_suggestions(path, expected, by_study):
    proposals, _ = lit.read_csv(path, SUGGEST_FIELDS)
    found = set()
    for i, row in enumerate(proposals, 2):
        key = (row["item_type"], row["study_id"], row["domain"])
        if key not in expected or key in found:
            lit.fail(f"Agent suggestion row {i}: unknown or repeated review item")
        found.add(key)
        allowed = (ROB_JUDGMENTS[by_study[key[1]]["design_type"]] if key[0].startswith("rob") else
                   GRADE_JUDGMENTS if key[0] == "grade_domain" else CERTAINTY)
        if row["proposed_judgment"] not in allowed or not all(row[x].strip() for x in
                ("rationale", "evidence_file", "evidence_sha256", "evidence_locator",
                 "evidence_excerpt", "agent_id", "suggested_at")):
            lit.fail(f"Agent suggestion row {i}: complete proposed judgment, reason and source required")
        day(row["suggested_at"], f"Agent suggestion row {i}")
        source = Path(row["evidence_file"]).resolve()
        if not source.is_file() or source.stat().st_size > 25_000_000 or lit.sha256(source) != row["evidence_sha256"]:
            lit.fail(f"Agent suggestion row {i}: source missing, too large, or changed")
        excerpt = " ".join(row["evidence_excerpt"].split())
        if len(excerpt) < 8 or len(excerpt) > 700:
            lit.fail(f"Agent suggestion row {i}: excerpt must be 8-700 characters")
        suffix = source.suffix.lower()
        if suffix in {".pdf", ".txt", ".html", ".htm"}:
            from fulltext_extract import pages
            kind = "pdf" if suffix == ".pdf" else "text" if suffix == ".txt" else "html"
            extracted = pages(source, kind)
            match = re.search(r"\bpage\s+(\d+)\b", row["evidence_locator"], re.I)
            if kind == "pdf" and not match:
                lit.fail(f"Agent suggestion row {i}: PDF needs a page locator")
            texts = [text for page, text in extracted if not match or page == int(match.group(1))]
        elif suffix == ".csv":
            texts = [source.read_text(encoding="utf-8-sig")]
        else:
            lit.fail(f"Agent suggestion row {i}: unsupported source type")
        if not any(excerpt in " ".join(text.split()) for text in texts):
            lit.fail(f"Agent suggestion row {i}: quoted excerpt absent from cited source/page")
        table = re.search(r"\btable\s+([A-Za-z0-9_-]+)\b", row["evidence_locator"], re.I)
        if table:
            marker = re.compile(r"\btable\s+" + re.escape(table.group(1)) + r"\b", re.I)
            if suffix in {".pdf", ".txt"}:
                if not any(marker.search(text) for text in texts):
                    lit.fail(f"Agent suggestion row {i}: cited table marker absent from page text")
                row["table_locator_check"] = "TEXT_MARKER_PRESENT_ONLY"
            else:
                row["table_locator_check"] = "TABLE_LOCATION_UNVERIFIED_FOR_THIS_FORMAT"
        elif "table" in row["evidence_locator"].lower():
            row["table_locator_check"] = "TABLE_LOCATION_UNPARSED_NOT_VERIFIED"
        else:
            row["table_locator_check"] = "NO_TABLE_CLAIM"
    return proposals


def suggest(a):
    folder, _, _, _, _, _, by_study = checked_plan(a.plan)
    proposals = check_suggestions(a.proposals, keys(by_study), by_study)
    out = Path(a.out).resolve()
    if out.exists():
        lit.fail("output exists; use a fresh Agent suggestion directory")
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".quality-suggestion-", dir=out.parent) as tmp:
        stage = Path(tmp) / "result"
        stage.mkdir()
        lit.write_csv(stage / "agent_suggestions.csv", SUGGEST_FIELDS + ["status", "table_locator_check"],
                      [dict(row, status="AGENT_PROPOSAL_NOT_ASSESSED") for row in proposals])
        originals, _ = lit.read_csv(folder / "reviewer_template.csv", VOTE_FIELDS)
        by_key = {(row["item_type"], row["study_id"], row["domain"]): row for row in proposals}
        extras = ["agent_proposed_judgment", "agent_rationale", "agent_evidence_locator", "agent_evidence_excerpt"]
        annotated = []
        for row in originals:
            proposal = by_key.get((row["item_type"], row["study_id"], row["domain"]), {})
            annotated.append(dict(row, agent_proposed_judgment=proposal.get("proposed_judgment", ""),
                agent_rationale=proposal.get("rationale", ""),
                agent_evidence_locator=proposal.get("evidence_locator", ""),
                agent_evidence_excerpt=proposal.get("evidence_excerpt", "")))
        lit.write_csv(stage / "reviewer_template_with_suggestions.csv", VOTE_FIELDS + extras, annotated)
        receipt = dict(schema="meta-quality-agent-suggestions-v1", status="AGENT_PROPOSALS_PENDING_HUMAN_REVIEW",
                       plan_dir=str(folder), plan_sha256=lit.sha256(folder / "quality_plan.json"),
                       proposals_path=str(Path(a.proposals).resolve()), proposals_sha256=lit.sha256(a.proposals),
                       outputs={f.name: lit.sha256(f) for f in stage.iterdir()}, human_judgment=False)
        (stage / "suggestion_receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        os.replace(stage, out)
    print(f"AGENT_PROPOSALS_PENDING_HUMAN_REVIEW: {len(proposals)} suggestions; {out}")


def verify_suggestions(path, plan_folder, expected, by_study):
    folder = Path(path).resolve()
    receipt = json.loads((folder / "suggestion_receipt.json").read_text(encoding="utf-8"))
    if receipt.get("schema") != "meta-quality-agent-suggestions-v1" or receipt.get("status") != "AGENT_PROPOSALS_PENDING_HUMAN_REVIEW" or receipt.get("plan_dir") != str(plan_folder):
        lit.fail("invalid or different Agent suggestion receipt")
    if lit.sha256(plan_folder / "quality_plan.json") != receipt["plan_sha256"] or lit.sha256(receipt["proposals_path"]) != receipt["proposals_sha256"]:
        lit.fail("Agent suggestion input changed")
    for name, digest in receipt["outputs"].items():
        if lit.sha256(folder / name) != digest:
            lit.fail(f"Agent suggestion output changed: {name}")
    check_suggestions(receipt["proposals_path"], expected, by_study)
    return receipt


def read_votes(path, label, expected, by_study, allow_empty=False, adjudication=False):
    fields = ADJ_FIELDS if adjudication else VOTE_FIELDS
    rows, _ = lit.read_csv(path, fields, allow_empty=allow_empty)
    found, people = {}, set()
    for i, row in enumerate(rows, 2):
        if any(row.get(k) is None for k in fields):
            lit.fail(f"{label} row {i}: missing CSV cell")
        key = (row["item_type"], row["study_id"], row["domain"])
        if key not in expected or key in found:
            lit.fail(f"{label} row {i}: unknown/repeated study, domain, or outcome item")
        if not row["reviewer"].strip():
            lit.fail(f"{label} row {i}: named assessor required")
        people.add(row["reviewer"].strip())
        day(row["reviewed_at"], f"{label} row {i}")
        if row["status"] not in {"pending", "assessed"}:
            lit.fail(f"{label} row {i}: invalid status")
        if row["status"] == "pending":
            if any(row[k].strip() for k in ("judgment", "evidence_file", "evidence_sha256", "evidence_locator")):
                lit.fail(f"{label} row {i}: pending cannot claim a judgment or evidence")
        else:
            if not all(row[k].strip() for k in ("judgment", "rationale", "evidence_file",
                                                  "evidence_sha256", "evidence_locator")):
                lit.fail(f"{label} row {i}: judgment needs rationale and local source evidence")
            allowed = (ROB_JUDGMENTS[by_study[key[1]]["design_type"]] if key[0].startswith("rob") else
                       GRADE_JUDGMENTS if key[0] == "grade_domain" else CERTAINTY)
            if row["judgment"] not in allowed:
                lit.fail(f"{label} row {i}: judgment is outside this design/domain vocabulary")
            source = Path(row["evidence_file"]).resolve()
            if not source.is_file() or lit.sha256(source) != row["evidence_sha256"]:
                lit.fail(f"{label} row {i}: evidence file missing or changed")
            if key[0].startswith("rob") and not any(token in row["evidence_locator"].lower()
                    for token in ("page", "table", "figure", "p.")):
                lit.fail(f"{label} row {i}: study-level RoB evidence needs a page/table/figure locator")
            if adjudication and not row["adjudication_reason"].strip():
                lit.fail(f"{label} row {i}: adjudication rationale required")
        found[key] = row
    if len(people) != 1 and not (allow_empty and not rows):
        lit.fail(f"{label}: one stable self-declared assessor per file required")
    return found, next(iter(people)) if people else None


def prior_attempt(out, a):
    if not out.is_dir():
        lit.fail("--resume requires an existing incomplete quality review")
    old = json.loads((out / "quality_receipt.json").read_text(encoding="utf-8"))
    if old.get("schema") != "meta-quality-review-v1" or old.get("status") not in {
            "NEEDS_REVIEW", "NEEDS_ADJUDICATION"} or (out / "sof_table.csv").exists():
        lit.fail("--resume only accepts an incomplete quality review without SoF")
    if old.get("mode") != a.mode or old.get("plan_dir") != str(Path(a.plan).resolve()):
        lit.fail("--resume plan or mode changed")
    for key, source in (("reviewer_a", a.reviewer_a), ("reviewer_b", a.reviewer_b)):
        if source and old["inputs"].get(key, {}).get("path") != str(Path(source).resolve()):
            lit.fail(f"--resume reviewer path changed: {key}")
    old_suggestions = old["inputs"].get("suggestions", {}).get("path")
    new_suggestions = str(Path(a.suggestions).resolve() / "suggestion_receipt.json") if a.suggestions else None
    if old_suggestions != new_suggestions:
        lit.fail("--resume Agent suggestion path changed")
    if new_suggestions and lit.sha256(new_suggestions) != old["inputs"]["suggestions"]["sha256"]:
        lit.fail("--resume Agent suggestion receipt changed")
    expected = {"review_decisions.csv", "missing_items.csv", "conflicts.csv", "quality_receipt.json"}
    if {f.name for f in out.iterdir()} != expected:
        lit.fail("--resume prior quality output has unexpected/missing files")
    for name, digest in old["outputs"].items():
        if lit.sha256(out / name) != digest:
            lit.fail(f"--resume prior quality audit changed: {name}")
    return old


def resolve(a):
    folder, p, root, packet_args, included, effects, by_study = checked_plan(a.plan)
    expected = keys(by_study)
    suggestions = verify_suggestions(a.suggestions, folder, expected, by_study) if a.suggestions else None
    first, who_a = read_votes(a.reviewer_a, "reviewer A", expected, by_study)
    second, who_b = {}, None
    if a.mode == "formal_dual":
        if not a.reviewer_b or a.reviewer_a_role != "human_attested" or a.reviewer_b_role != "human_attested":
            lit.fail("formal_dual needs two human_attested reviewer files")
        second, who_b = read_votes(a.reviewer_b, "reviewer B", expected, by_study)
        if who_a == who_b:
            lit.fail("formal_dual reviewer names must differ")
    elif a.reviewer_b or a.adjudication:
        lit.fail("exploratory_single accepts one vote file only")
    third, who_c = {}, None
    if a.adjudication:
        if a.adjudicator_role != "human_attested":
            lit.fail("formal adjudicator role must be human_attested")
        third, who_c = read_votes(a.adjudication, "adjudicator", expected, by_study,
                                  allow_empty=True, adjudication=True)
        if who_c in {who_a, who_b}:
            lit.fail("adjudicator must differ from primary reviewers")
    missing, conflicts, decisions, used_third = [], [], [], set()
    for key in sorted(expected):
        left, right = first.get(key), second.get(key)
        if left is None:
            missing.append(dict(item_type=key[0], study_id=key[1], domain=key[2], needed="reviewer_A"))
        if a.mode == "formal_dual" and right is None:
            missing.append(dict(item_type=key[0], study_id=key[1], domain=key[2], needed="reviewer_B"))
        if left is None or a.mode == "formal_dual" and right is None:
            continue
        differs = bool(right and any(left[x] != right[x] for x in
                ("status", "judgment", "rationale", "evidence_file", "evidence_sha256", "evidence_locator")))
        choice = left
        if differs:
            adjudicated = third.get(key)
            conflicts.append(dict(item_type=key[0], study_id=key[1], domain=key[2],
                                  judgment_a=left["judgment"], judgment_b=right["judgment"],
                                  status="ADJUDICATED" if adjudicated else "UNRESOLVED"))
            if not adjudicated:
                continue
            if day(adjudicated["reviewed_at"], "adjudication") < max(
                    day(left["reviewed_at"], "vote A"), day(right["reviewed_at"], "vote B")):
                lit.fail(f"{key}: adjudication predates reviewer judgments")
            choice = adjudicated
            used_third.add(key)
        elif key in third:
            lit.fail(f"{key}: adjudication submitted without conflict")
        decisions.append({**choice, "reviewer_a": who_a, "reviewer_b": who_b or "",
                          "adjudicator": who_c if differs else "",
                          "adjudication_reason": choice.get("adjudication_reason", "") if differs else ""})
    if set(third) != used_third:
        lit.fail("adjudication contains premature/unused item")
    pending = sum(r["status"] == "pending" for r in decisions)
    status = "NEEDS_REVIEW" if missing or pending else (
        "NEEDS_ADJUDICATION" if any(r["status"] == "UNRESOLVED" for r in conflicts) else
        "EXPLORATORY_DRAFT" if a.mode == "exploratory_single" else "FORMAL_REVIEWED")
    complete = status in {"EXPLORATORY_DRAFT", "FORMAL_REVIEWED"}
    rob_rows, sof_rows, report_lines = [], [], []
    if complete:
        by_key = {(r["item_type"], r["study_id"], r["domain"]): r for r in decisions}
        for sid, design in sorted(by_study.items()):
            for domain in (*DESIGN_DOMAINS[design["design_type"]], "overall"):
                item = by_key[("rob_overall" if domain == "overall" else "rob_domain", sid, domain)]
                rob_rows.append(dict(study_id=sid, design_type=design["design_type"],
                    instrument_name=design["instrument_name"], instrument_version=design["instrument_version"],
                    instrument_reference=design["instrument_reference"], domain=domain,
                    judgment=item["judgment"], rationale=item["rationale"],
                    evidence_file=item["evidence_file"], evidence_sha256=item["evidence_sha256"],
                    evidence_locator=item["evidence_locator"], reviewer=item["reviewer"],
                    assessed_at=item["reviewed_at"]))
        pooled, _ = packet_report.check_stats(packet_args, effects, review.checked_receipt(packet_args)[0])
        overall = by_key[("grade_overall", "", "overall")]
        certainty_source = ("human_attested_reviewer_files_identity_unverified" if a.mode == "formal_dual" else
            "agent_assisted_draft_not_human_attested" if a.reviewer_a_role == "agent_assisted" else
            "ai_simulated_draft_not_human_attested" if a.reviewer_a_role == "ai_simulated" else
            "single_reviewer_draft_not_human_attested")
        sof_rows.append(dict(outcome=p["outcome"], timepoint=p["timepoint"],
            effect_type=pooled["effect_type"], measurement_unit=p["measurement_unit"],
            pooled=pooled["pooled"], ci_lower=pooled["ci_lower"],
            ci_upper=pooled["ci_upper"], studies=pooled["k"], participants="NOT_SUPPLIED",
            absolute_effect="NOT_COMPUTED", certainty=overall["judgment"],
            certainty_rationale=overall["rationale"],
            certainty_evidence_file=overall["evidence_file"],
            certainty_evidence_sha256=overall["evidence_sha256"],
            certainty_evidence_locator=overall["evidence_locator"],
            certainty_source=certainty_source, mode=a.mode,
            certainty_is_human_attested="true" if a.mode == "formal_dual" else "false"))
        report_lines = ["# Evidence certainty and risk-of-bias appendix", "",
            f"Status: {status}. Protocol: {p['protocol_id']}; outcome: {p['outcome']} at {p['timepoint']}.",
            f"Certainty source: {certainty_source}. The software does not calculate an official instrument score or GRADE certainty.",
            "Participant count and absolute effect are not supplied by the bound study-level effect table.", "",
            "## Summary of Findings (reported effect only)", "",
            "| Outcome | Studies | Pooled effect (CI) | Measurement unit | Reviewer-supplied certainty (draft if exploratory) |", "|---|---:|---|---|---|",
            f"| {p['outcome']} / {p['timepoint']} | {pooled['k']} | {pooled['effect_type']} {pooled['pooled']} ({pooled['ci_lower']} to {pooled['ci_upper']}) | {p['measurement_unit']} | {overall['judgment']} |",
            f"Overall certainty evidence: {overall['evidence_file']} [{overall['evidence_locator']}], SHA-256 {overall['evidence_sha256']}.",
            "", "## GRADE domain judgments and evidence", ""]
        for domain in GRADE_DOMAINS:
            row = by_key[("grade_domain", "", domain)]
            report_lines.append(f"- {domain}: {row['judgment']}. {row['rationale']} Evidence: {row['evidence_file']} [{row['evidence_locator']}], SHA-256 {row['evidence_sha256']}.")
        report_lines += ["", "## Study-level risk-of-bias evidence", ""]
        for row in rob_rows:
            report_lines.append(f"- {row['study_id']} ({row['design_type']}; {row['domain']}): {row['judgment']}. {row['rationale']} Evidence: {row['evidence_file']} [{row['evidence_locator']}], SHA-256 {row['evidence_sha256']}.")
        report_lines += ["", "The instrument name/version and evidence are user supplied. No licensed questionnaire text or automated low-risk label is included."]
        if suggestions:
            report_lines.append("Agent suggestions were separate pending proposals. Reviewer decisions above were supplied in reviewer files; no proposal was automatically accepted.")
    out = Path(a.out).resolve()
    if out.exists() and not a.resume:
        lit.fail("output exists; use a fresh quality result directory")
    prior = prior_attempt(out, a) if a.resume else None
    backup = None
    if prior:
        n = 1
        while True:
            backup = out.with_name(out.name + f".prior-{n:04d}")
            if not backup.exists():
                break
            n += 1
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".quality-review-", dir=out.parent) as tmp:
        stage = Path(tmp) / "result"
        stage.mkdir()
        lit.write_csv(stage / "review_decisions.csv", VOTE_FIELDS + ["reviewer_a", "reviewer_b",
                      "adjudicator", "adjudication_reason"], decisions)
        lit.write_csv(stage / "missing_items.csv", ["item_type", "study_id", "domain", "needed"], missing)
        lit.write_csv(stage / "conflicts.csv", ["item_type", "study_id", "domain", "judgment_a", "judgment_b", "status"], conflicts)
        if complete:
            lit.write_csv(stage / "risk_of_bias_design_audit.csv", list(rob_rows[0]), rob_rows)
            lit.write_csv(stage / "sof_table.csv", list(sof_rows[0]), sof_rows)
            (stage / "quality_report.md").write_text("\n".join(report_lines) + "\n", encoding="utf-8")
        inputs = {key: {"path": str(Path(path).resolve()), "sha256": lit.sha256(path)}
                  for key, path in (("plan", folder / "quality_plan.json"), ("reviewer_a", a.reviewer_a))}
        if a.reviewer_b:
            inputs["reviewer_b"] = {"path": str(Path(a.reviewer_b).resolve()), "sha256": lit.sha256(a.reviewer_b)}
        if a.adjudication:
            inputs["adjudication"] = {"path": str(Path(a.adjudication).resolve()), "sha256": lit.sha256(a.adjudication)}
        if a.suggestions:
            source = Path(a.suggestions).resolve() / "suggestion_receipt.json"
            inputs["suggestions"] = {"path": str(source), "sha256": lit.sha256(source)}
        outputs = {f.name: lit.sha256(f) for f in stage.iterdir() if f.is_file()}
        (stage / "quality_receipt.json").write_text(json.dumps(dict(schema="meta-quality-review-v1",
            status=status, mode=a.mode, plan_dir=str(folder), packet_dir=str(root), inputs=inputs,
            outputs=outputs, reviewer_roles_attested={"A": a.reviewer_a_role,
            "B": a.reviewer_b_role if a.reviewer_b else None,
            "adjudicator": a.adjudicator_role if a.adjudication else None},
            resumed_from_path=str(backup) if prior else None,
            resumed_from_receipt_sha256=lit.sha256(out / "quality_receipt.json") if prior else None,
            identity_authenticated=False, grade_automatically_calculated=False), indent=2) + "\n", encoding="utf-8")
        if prior:
            os.replace(out, backup)
            try:
                os.replace(stage, out)
            except OSError:
                os.replace(backup, out)
                raise
        else:
            os.replace(stage, out)
    print(f"{status}: {len(decisions)} decisions, {len(conflicts)} conflicts; {out}")
    return 0 if complete else 2


def verify_quality(path, expected_args=None):
    folder = Path(path).resolve()
    q = json.loads((folder / "quality_receipt.json").read_text(encoding="utf-8"))
    if q.get("schema") != "meta-quality-review-v1" or q.get("status") not in {
            "EXPLORATORY_DRAFT", "FORMAL_REVIEWED"}:
        lit.fail("quality result is incomplete or invalid")
    verify_prior_chain(q)
    _, p, root, args, included, effects, by_study = checked_plan(q["plan_dir"])
    if str(root) != q["packet_dir"]:
        lit.fail("quality result packet path changed")
    if expected_args is not None:
        for key in review.INPUTS + ("confirmation", "rob_ledger", "rob_plan", "stats_dir"):
            if str(Path(getattr(expected_args, key)).resolve()) != str(Path(getattr(args, key)).resolve()):
                lit.fail(f"quality result bound to different report input: {key}")
    for item in q["inputs"].values():
        source = Path(item["path"])
        if not source.is_file() or lit.sha256(source) != item["sha256"]:
            lit.fail("quality reviewer input changed")
    if "suggestions" in q["inputs"]:
        verify_suggestions(Path(q["inputs"]["suggestions"]["path"]).parent,
                           Path(q["plan_dir"]), keys(by_study), by_study)
    for name, digest in q["outputs"].items():
        if not (folder / name).is_file() or lit.sha256(folder / name) != digest:
            lit.fail(f"quality output changed: {name}")
    decisions, _ = lit.read_csv(folder / "review_decisions.csv", VOTE_FIELDS)
    for i, row in enumerate(decisions, 2):
        if row["status"] == "assessed" and (not Path(row["evidence_file"]).is_file() or
                lit.sha256(row["evidence_file"]) != row["evidence_sha256"]):
            lit.fail(f"quality judgment evidence changed: row {i}")
    return q


def verify_prior_chain(receipt):
    seen = set()
    for _ in range(100):
        if not receipt.get("resumed_from_receipt_sha256"):
            return
        folder = Path(receipt["resumed_from_path"]).resolve()
        if folder in seen:
            lit.fail("cyclic quality review history")
        seen.add(folder)
        prior = folder / "quality_receipt.json"
        if not prior.is_file() or lit.sha256(prior) != receipt["resumed_from_receipt_sha256"]:
            lit.fail("prior quality review attempt changed or missing")
        receipt = json.loads(prior.read_text(encoding="utf-8"))
        if receipt.get("schema") != "meta-quality-review-v1" or receipt.get("status") not in {
                "NEEDS_REVIEW", "NEEDS_ADJUDICATION"}:
            lit.fail("invalid prior quality review attempt")
        for name, digest in receipt["outputs"].items():
            path = folder / name
            if not path.is_file() or lit.sha256(path) != digest:
                lit.fail(f"prior quality review audit changed: {name}")
    lit.fail("quality review history exceeds 100 revisions")


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    sub = cli.add_subparsers(dest="command", required=True)
    p = sub.add_parser("plan")
    for opt in ("packet", "designs", "out"):
        p.add_argument("--" + opt, required=True)
    p.set_defaults(func=plan)
    s = sub.add_parser("suggest")
    for opt in ("plan", "proposals", "out"):
        s.add_argument("--" + opt, required=True)
    s.set_defaults(func=suggest)
    r = sub.add_parser("resolve")
    for opt in ("plan", "reviewer-a", "mode", "out"):
        r.add_argument("--" + opt, required=True)
    r.add_argument("--reviewer-b")
    r.add_argument("--adjudication")
    r.add_argument("--suggestions")
    r.add_argument("--resume", action="store_true")
    for role in ("reviewer-a-role", "reviewer-b-role", "adjudicator-role"):
        r.add_argument("--" + role, choices=("unspecified", "human_attested", "agent_assisted", "ai_simulated"),
                       default="unspecified")
    r.set_defaults(func=resolve)
    a = cli.parse_args()
    if a.command == "resolve" and a.mode not in {"exploratory_single", "formal_dual"}:
        cli.exit(2, "Validation: invalid quality review mode\n")
    try:
        sys.exit(a.func(a) or 0)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        cli.exit(2, f"Validation: {error}\n")
