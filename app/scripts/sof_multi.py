"""Multi-outcome Summary of Findings from separately checked quality reviews; no GRADE automation."""
import argparse
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import tempfile

import diagnostic_word
import evidence_quality as quality
import literature as lit

FIELDS = ("outcome_id", "quality_dir", "measurement_unit_override", "unit_evidence_file",
          "unit_evidence_sha256", "unit_locator", "participants", "participants_evidence_file",
          "participants_evidence_sha256", "participants_locator", "baseline_risk_per_1000",
          "baseline_evidence_file", "baseline_evidence_sha256", "baseline_locator",
          "baseline_timepoint", "baseline_population", "baseline_applicability_review",
          "baseline_applicability_basis", "comment")
OUTPUT = ("outcome_id", "outcome", "timepoint", "effect_type", "measurement_unit", "unit_evidence", "studies",
          "participants", "participants_evidence", "relative_or_continuous_effect", "ci_lower", "ci_upper",
          "baseline_risk_per_1000", "intervention_risk_per_1000", "intervention_ci_lower_per_1000",
          "intervention_ci_upper_per_1000", "absolute_difference_per_1000",
          "absolute_difference_ci_lower_per_1000", "absolute_difference_ci_upper_per_1000",
          "absolute_assumption", "baseline_evidence", "baseline_timepoint", "baseline_population",
          "baseline_applicability_review", "baseline_applicability_basis", "certainty", "certainty_source",
          "certainty_evidence", "review_mode", "agent_suggestions_separate", "comment")


def resolved_entries(path):
    entries, _ = lit.read_csv(path, FIELDS)
    parent = Path(path).resolve().parent
    for entry in entries:
        for key in ("quality_dir", "unit_evidence_file", "participants_evidence_file", "baseline_evidence_file"):
            if entry[key]:
                candidate = Path(entry[key]).expanduser()
                entry[key] = str((candidate if candidate.is_absolute() else parent / candidate).resolve())
    return entries


def number(value, label):
    try:
        n = Decimal(str(value))
    except (InvalidOperation, TypeError):
        lit.fail(label + " must be finite numeric")
    if not n.is_finite():
        lit.fail(label + " must be finite numeric")
    return n


def fmt(n):
    return format(n.quantize(Decimal("0.1")), "f")


def absolute_effect(effect_type, estimate, low, high, baseline):
    """Return treated risk/difference and CI in events per 1000, based on fixed entered risk."""
    p0 = number(baseline, "baseline risk") / 1000
    if not 0 < p0 < 1:
        lit.fail("baseline risk must be strictly between 0 and 1000 per 1000")
    values = [number(value, "relative effect") for value in (estimate, low, high)]
    if not 0 < values[1] <= values[0] <= values[2]:
        lit.fail("ratio effect and interval must be positive and ordered")
    if effect_type == "RR":
        risks = [p0 * value for value in values]
        assumption = "fixed sourced comparator risk; RR applied at the stated endpoint"
    elif effect_type == "OR":
        risks = [value * p0 / (1 - p0 + value * p0) for value in values]
        assumption = "fixed sourced comparator risk; OR converted to probability"
    elif effect_type == "HR":
        risks = [1 - (1 - p0) ** value for value in values]
        assumption = "fixed sourced comparator risk at the same timepoint; proportional hazards assumed"
    else:
        lit.fail("absolute binary risk requires RR, OR or HR")
    if any(value < 0 or value > 1 for value in risks):
        lit.fail("implied risk outside 0-1000 per 1000; do not cap silently")
    treated = [fmt(value * 1000) for value in risks]
    difference = [fmt((value - p0) * 1000) for value in risks]
    return dict(intervention_risk_per_1000=treated[0], intervention_ci_lower_per_1000=treated[1],
                intervention_ci_upper_per_1000=treated[2], absolute_difference_per_1000=difference[0],
                absolute_difference_ci_lower_per_1000=difference[1],
                absolute_difference_ci_upper_per_1000=difference[2], absolute_assumption=assumption)


def sourced(value, file, digest, locator, label):
    if not value:
        if any((file, digest, locator)):
            lit.fail(label + " evidence supplied without a value")
        return "NOT_SUPPLIED"
    source = Path(file).resolve()
    if not source.is_file() or lit.sha256(source) != digest or not locator.strip():
        lit.fail(label + " requires matching local evidence bytes and locator")
    return str(source) + " [" + locator + "]; sha256=" + digest


def build(a):
    entries = resolved_entries(a.inputs)
    if not 1 <= len(entries) <= 50:
        lit.fail("SoF accepts 1-50 outcomes")
    seen = set(); result = []; sources = {}
    for i, entry in enumerate(entries, 2):
        oid = entry["outcome_id"].strip()
        if not oid or oid in seen:
            lit.fail(f"SoF row {i}: distinct outcome_id required")
        seen.add(oid)
        folder = Path(entry["quality_dir"]).resolve()
        receipt = quality.verify_quality(folder)
        plan = json.loads((Path(receipt["plan_dir"]) / "quality_plan.json").read_text(encoding="utf-8"))
        sof, _ = lit.read_csv(folder / "sof_table.csv", ("outcome", "timepoint", "effect_type",
            "measurement_unit", "pooled", "ci_lower", "ci_upper", "studies", "certainty",
            "certainty_source", "certainty_evidence_file", "certainty_evidence_sha256",
            "certainty_evidence_locator", "mode"))
        if len(sof) != 1:
            lit.fail("one checked quality outcome per row required")
        source = sof[0]
        if (source["outcome"], source["timepoint"], source["effect_type"]) != (
                plan["outcome"], plan["timepoint"], plan["effect_type"]):
            lit.fail("SoF effect does not match quality plan")
        if int(source["studies"]) < 1:
            lit.fail("positive study count required")
        unit = source["measurement_unit"]
        unit_evidence = "CONFIRMED_PROTOCOL_UNIT_IN_QUALITY_PLAN"
        if entry["measurement_unit_override"]:
            unit_evidence = sourced(entry["measurement_unit_override"], entry["unit_evidence_file"],
                                    entry["unit_evidence_sha256"], entry["unit_locator"], "measurement unit")
            if unit != "UNIT_NOT_SUPPLIED" and unit != entry["measurement_unit_override"]:
                lit.fail("unit override disagrees with confirmed protocol unit")
            unit = entry["measurement_unit_override"]
        elif any((entry["unit_evidence_file"],entry["unit_evidence_sha256"],entry["unit_locator"])):
            lit.fail("unit evidence supplied without an override")
        key = (source["outcome"].casefold(), source["timepoint"].casefold(), source["effect_type"])
        if key in sources:
            lit.fail("same outcome/timepoint/effect scale repeated; use a distinct planned contrast")
        sources[key] = oid
        participant_evidence = sourced(entry["participants"], entry["participants_evidence_file"],
            entry["participants_evidence_sha256"], entry["participants_locator"], "participants")
        if entry["participants"] and (not entry["participants"].isdigit() or int(entry["participants"]) < 1):
            lit.fail("participants must be a positive integer")
        baseline_evidence = sourced(entry["baseline_risk_per_1000"], entry["baseline_evidence_file"],
            entry["baseline_evidence_sha256"], entry["baseline_locator"], "baseline risk")
        effect_type = source["effect_type"]
        if effect_type in {"MD", "SMD"}:
            if entry["baseline_risk_per_1000"] or any((entry["baseline_timepoint"],entry["baseline_population"],
                entry["baseline_applicability_review"],entry["baseline_applicability_basis"])):
                lit.fail("MD/SMD cannot be converted to binary absolute risk")
            if effect_type == "MD" and unit == "UNIT_NOT_SUPPLIED":
                lit.fail("MD SoF requires the original measurement unit")
            if effect_type == "SMD" and unit not in {"standardized SD", "SD units"}:
                lit.fail("SMD must be labeled as standardized SD units")
            absolute = {key: "NOT_APPLICABLE" for key in OUTPUT if key.startswith(("intervention_", "absolute_difference_"))}
            absolute["absolute_assumption"] = "continuous effect; no binary risk conversion"
        elif effect_type in {"RR", "OR", "HR"}:
            if entry["baseline_risk_per_1000"]:
                if entry["baseline_timepoint"] != source["timepoint"] or not entry["baseline_population"].strip():
                    lit.fail("baseline risk needs matching timepoint and stated comparator population")
                decision=entry["baseline_applicability_review"]
                if decision not in {"applicable","not_applicable","uncertain"} or not entry["baseline_applicability_basis"].strip():
                    lit.fail("baseline risk needs applicable/not_applicable/uncertain and reviewer basis")
                if decision=="applicable":
                    absolute = absolute_effect(effect_type, source["pooled"], source["ci_lower"],
                                               source["ci_upper"], entry["baseline_risk_per_1000"])
                else:
                    state="NOT_COMPUTED_BASELINE_"+decision.upper()
                    absolute={key:state for key in OUTPUT if key.startswith(("intervention_","absolute_difference_"))}
                    absolute["absolute_assumption"]="reviewer marked comparator baseline "+decision+"; no absolute conversion"
            else:
                if any((entry["baseline_timepoint"],entry["baseline_population"],
                        entry["baseline_applicability_review"],entry["baseline_applicability_basis"])):
                    lit.fail("baseline descriptors without a sourced risk")
                absolute = {key: "NOT_COMPUTED_NO_SOURCED_BASELINE" for key in OUTPUT if key.startswith(("intervention_", "absolute_difference_"))}
                absolute["absolute_assumption"] = "no sourced baseline risk"
        else:
            lit.fail("this multi-outcome SoF supports checked pairwise RR/OR/HR/MD/SMD only")
        certainty_evidence = sourced("checked", source["certainty_evidence_file"],
            source["certainty_evidence_sha256"], source["certainty_evidence_locator"], "certainty")
        result.append(dict(outcome_id=oid, outcome=source["outcome"], timepoint=source["timepoint"],
            effect_type=effect_type, measurement_unit=unit, unit_evidence=unit_evidence, studies=source["studies"],
            participants=entry["participants"] or "NOT_SUPPLIED", participants_evidence=participant_evidence,
            relative_or_continuous_effect=source["pooled"], ci_lower=source["ci_lower"], ci_upper=source["ci_upper"],
            baseline_risk_per_1000=entry["baseline_risk_per_1000"] or "NOT_SUPPLIED",
            baseline_evidence=baseline_evidence, baseline_timepoint=entry["baseline_timepoint"] or "NOT_SUPPLIED",
            baseline_population=entry["baseline_population"] or "NOT_SUPPLIED",
            baseline_applicability_review=entry["baseline_applicability_review"] or "NOT_SUPPLIED",
            baseline_applicability_basis=entry["baseline_applicability_basis"] or "NOT_SUPPLIED",
            certainty=source["certainty"],
            certainty_source=source["certainty_source"], certainty_evidence=certainty_evidence,
            review_mode=source["mode"], agent_suggestions_separate="true" if "suggestions" in receipt["inputs"] else "false",
            comment=entry["comment"], **absolute))
    out = Path(a.out).resolve()
    if out.exists():
        lit.fail("SoF output exists; use a fresh directory")
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".sof-multi-", dir=out.parent) as tmp:
        stage = Path(tmp) / "result"; stage.mkdir()
        lit.write_csv(stage / "sof_multi.csv", OUTPUT, result)
        display = [["Outcome and timepoint", "Evidence", "Effect and CI", "Absolute effect per 1000", "Certainty", "Status"]]
        for row in result:
            effect = (f"{row['effect_type']} {format(Decimal(row['relative_or_continuous_effect']), '.3g')} "
                      f"({format(Decimal(row['ci_lower']), '.3g')} to {format(Decimal(row['ci_upper']), '.3g')})")
            if row["effect_type"] == "MD":
                effect += " " + row["measurement_unit"]
            if row["effect_type"] == "SMD":
                effect += " SD units"
            absolute_text = ("not applicable" if row["effect_type"] in {"MD","SMD"} else
                "not computed: comparator baseline "+row["baseline_applicability_review"]
                if row["baseline_applicability_review"] in {"not_applicable","uncertain"} else
                (f"Treated {row['intervention_risk_per_1000']} "
                 f"({row['intervention_ci_lower_per_1000']} to {row['intervention_ci_upper_per_1000']}); "
                 f"difference {row['absolute_difference_per_1000']} "
                 f"({row['absolute_difference_ci_lower_per_1000']} to {row['absolute_difference_ci_upper_per_1000']})")
                if row["baseline_risk_per_1000"] != "NOT_SUPPLIED" else "baseline not supplied")
            display.append([row["outcome"] + " at " + row["timepoint"],
                row["studies"] + " studies; " + row["participants"] + " participants",
                effect, absolute_text, row["certainty"], row["certainty_source"]])
        sections = [dict(text="Summary of Findings by Outcome", style="Title"),
            dict(text="This draft combines separately checked outcome reviews. Absolute binary effects use a fixed, sourced comparator risk; certainty remains a reviewer judgment. No source is automatically graded."),
            dict(text="Outcome summary", style="Heading1", table={"title":"Table 1  Summary of Findings", "rows":display})]
        for row in result:
            sections.append(dict(text=(f"{row['outcome_id']}: comparator risk {row['baseline_risk_per_1000']} per 1000. "
                f"{row['absolute_assumption']}. Baseline population: {row['baseline_population']}; "
                f"baseline timepoint: {row['baseline_timepoint']}; reviewer applicability conclusion: "
                f"{row['baseline_applicability_review']}; basis: {row['baseline_applicability_basis']}. "
                f"Baseline evidence: {row['baseline_evidence']}. "
                f"Unit evidence: {row['unit_evidence']}. Participants evidence: {row['participants_evidence']}. "
                f"Certainty evidence: {row['certainty_evidence']}. "
                f"Agent suggestions separate from decisions: {row['agent_suggestions_separate']}")))
        diagnostic_word.write(stage / "sof_multi.docx", sections, [])
        markdown = ["# Summary of Findings by Outcome", "",
            "Draft only. Binary absolute effects assume a fixed sourced comparator risk; certainty is not calculated by software.", "",
            "| Outcome and timepoint | Studies and participants | Effect and CI | Treated risk and absolute difference per 1000 | Certainty source |",
            "|---|---|---|---|---|"]
        for row in display[1:]:
            markdown.append("| " + " | ".join(cell.replace("|", "/") for cell in
                            (row[0], row[1], row[2], row[3], row[4] + "; " + row[5])) + " |")
        for row in result:
            markdown.append(f"\n{row['outcome_id']} baseline: {row['baseline_population']} at {row['baseline_timepoint']}; "
                            f"reviewer applicability conclusion: {row['baseline_applicability_review']}; "
                            f"basis: {row['baseline_applicability_basis']}; "
                            f"evidence: {row['baseline_evidence']}.")
        markdown += ["", "The CSV contains full source paths, SHA-256 values, assumptions and unrounded pooled statistics."]
        (stage / "sof_multi.md").write_text("\n".join(markdown) + "\n", encoding="utf-8")
        receipt = dict(schema="meta-sof-multi-v1", status="DRAFT_REVIEWED_SOURCES" if all(
            r["review_mode"] == "formal_dual" for r in result) else "DRAFT_INCLUDES_EXPLORATORY",
            outcomes=len(result), inputs_path=str(Path(a.inputs).resolve()), inputs_sha256=lit.sha256(a.inputs),
            quality_receipts={r["outcome_id"]: lit.sha256(Path(entry["quality_dir"]) / "quality_receipt.json")
                              for r, entry in zip(result, entries)},
            outputs={p.name: lit.sha256(p) for p in stage.iterdir() if p.is_file()},
            certainty_automatically_calculated=False, baseline_risk_clinically_verified_by_software=False)
        (stage / "sof_multi_receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        os.replace(stage, out)
    print(receipt["status"], len(result), "outcomes", out)


def verify(path):
    folder = Path(path).resolve()
    receipt = json.loads((folder / "sof_multi_receipt.json").read_text(encoding="utf-8"))
    if receipt.get("schema") != "meta-sof-multi-v1" or receipt.get("status") not in {
            "DRAFT_REVIEWED_SOURCES", "DRAFT_INCLUDES_EXPLORATORY"}:
        lit.fail("invalid multi-outcome SoF receipt")
    source = Path(receipt["inputs_path"])
    if not source.is_file() or lit.sha256(source) != receipt["inputs_sha256"]:
        lit.fail("multi-outcome input changed")
    entries = resolved_entries(source)
    if len(entries) != receipt["outcomes"]:
        lit.fail("multi-outcome source count changed")
    for entry in entries:
        folder_quality = Path(entry["quality_dir"]).resolve()
        if lit.sha256(folder_quality / "quality_receipt.json") != receipt["quality_receipts"][entry["outcome_id"]]:
            lit.fail("quality receipt changed")
        quality.verify_quality(folder_quality)
        for label in ("unit", "participants", "baseline"):
            path_key = ("unit_evidence_file" if label == "unit" else label + "_evidence_file")
            sha_key = ("unit_evidence_sha256" if label == "unit" else label + "_evidence_sha256")
            if entry[path_key] and (not Path(entry[path_key]).is_file() or
                    lit.sha256(entry[path_key]) != entry[sha_key]):
                lit.fail(label + " evidence changed")
    for name, digest in receipt["outputs"].items():
        if not (folder / name).is_file() or lit.sha256(folder / name) != digest:
            lit.fail("multi-outcome output changed: " + name)
    print("VERIFIED_LOCAL_FILE_CONSISTENCY", receipt["outcomes"], "outcomes", folder)


if __name__ == "__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--inputs");p.add_argument("--out");p.add_argument("--verify")
    a=p.parse_args()
    try:
        if a.verify:
            if a.inputs or a.out:lit.fail("--verify cannot also build")
            verify(a.verify)
        elif a.inputs and a.out:build(a)
        else:lit.fail("build requires --inputs and --out")
    except (OSError, ValueError, KeyError, TypeError, InvalidOperation) as exc:p.exit(2,"Validation: "+str(exc)+"\n")
