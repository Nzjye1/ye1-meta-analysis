"""Auditable local PRISMA 2020 flow subset from human-entered source/retrieval ledgers.

This is an original diagram and a targeted item audit, not a completed PRISMA checklist.
"""
import argparse
import collections
import datetime as dt
import json
import os
from pathlib import Path
import sys
import tempfile
from xml.sax.saxutils import escape

import literature as lit
import review

OFFICIAL_CHECKLIST = "https://www.prisma-statement.org/prisma-2020-checklist"
OFFICIAL_FLOW = "https://www.prisma-statement.org/prisma-2020-flow-diagram"
ROUTES = {"database_register", "other_source"}
RETRIEVAL = {"retrieved", "not_retrieved", "pending"}


def iso_date(value, label):
    try:
        dt.date.fromisoformat(value)
    except (ValueError, TypeError):
        lit.fail(f"{label}: YYYY-MM-DD date required")


def validate(a, verified=None):
    receipt, records, dedup, stages, mapping, effects = (
        review.checked_receipt(a) if verified is None else verified)
    methods, _ = lit.read_csv(a.source_methods,
        ["source_label", "identification_route", "source_name", "searched_on",
         "strategy_reference", "reviewer"])
    sources = {r.get("source_label") or "UNLABELED" for r in records}
    by_source = {}
    for row in methods:
        label = row["source_label"]
        if label in by_source or label not in sources or row["identification_route"] not in ROUTES:
            lit.fail("source_methods: duplicate/unknown source or unsupported route")
        if not all((row[key] or "").strip() for key in
                   ("source_name", "strategy_reference", "reviewer")):
            lit.fail("source_methods: source name, strategy reference, and reviewer required")
        iso_date(row["searched_on"], f"source {label}")
        by_source[label] = row
    if set(by_source) != sources:
        lit.fail("source_methods must classify every imported source exactly once")
    sought = {rid for rid, row in dedup.items() if row["disposition"] == "keep" and
              stages[(rid, "title_abstract")]["decision"] == "include"}
    retrieval, _ = lit.read_csv(a.retrieval,
        ["record_id", "status", "reason", "retrieval_reference", "reviewer", "decision_date"],
        allow_empty=not sought)
    by_retrieval = {}
    for row in retrieval:
        rid, state = row["record_id"], row["status"]
        if rid not in sought or rid in by_retrieval or state not in RETRIEVAL:
            lit.fail("retrieval ledger: unknown/duplicate record or unsupported status")
        if not (row["reviewer"] or "").strip():
            lit.fail(f"retrieval {rid}: reviewer required")
        iso_date(row["decision_date"], f"retrieval {rid}")
        if state in {"retrieved", "not_retrieved"} and not (row["retrieval_reference"] or "").strip():
            lit.fail(f"retrieval {rid}: document or search-attempt reference required")
        if state == "not_retrieved" and not (row["reason"] or "").strip():
            lit.fail(f"retrieval {rid}: reason for not retrieving required")
        if state != "not_retrieved" and (row["reason"] or "").strip():
            lit.fail(f"retrieval {rid}: reason reserved for not_retrieved")
        ft = stages[(rid, "full_text")]["decision"]
        if state != "retrieved" and ft != "pending":
            lit.fail(f"retrieval {rid}: unavailable/pending report cannot be assessed or included")
        by_retrieval[rid] = row
    if set(by_retrieval) != sought:
        lit.fail("retrieval ledger must cover every title/abstract included record")
    return receipt, records, dedup, stages, mapping, effects, by_source, by_retrieval


def calculate(a, verified=None):
    receipt, records, dedup, stages, mapping, effects, methods, retrieval = validate(a, verified)
    source_counts = []
    for label in sorted(methods):
        rids = {r["record_id"] for r in records if (r.get("source_label") or "UNLABELED") == label}
        source_counts.append(dict(source_label=label, identification_route=methods[label]["identification_route"],
            source_name=methods[label]["source_name"], searched_on=methods[label]["searched_on"],
            strategy_reference=methods[label]["strategy_reference"],
            identified_records=len(rids), removed_duplicates=sum(dedup[r]["disposition"] == "remove_duplicate" for r in rids),
            removed_other=sum(dedup[r]["disposition"] == "remove_other" for r in rids),
            screened_records=sum(dedup[r]["disposition"] == "keep" for r in rids),
            reports_sought=sum(r in retrieval for r in rids),
            reports_not_retrieved=sum(r in retrieval and retrieval[r]["status"] == "not_retrieved" for r in rids),
            retrieval_pending=sum(r in retrieval and retrieval[r]["status"] == "pending" for r in rids),
            reports_retrieved=sum(r in retrieval and retrieval[r]["status"] == "retrieved" for r in rids),
            reports_assessed=sum(r in retrieval and retrieval[r]["status"] == "retrieved" and
                                 stages[(r, "full_text")]["decision"] in {"include", "exclude"} for r in rids),
            assessment_pending=sum(r in retrieval and retrieval[r]["status"] == "retrieved" and
                                   stages[(r, "full_text")]["decision"] == "pending" for r in rids),
            reports_excluded=sum(r in retrieval and retrieval[r]["status"] == "retrieved" and
                                 stages[(r, "full_text")]["decision"] == "exclude" for r in rids),
            included_reports=sum(m["record_id"] in rids for m in mapping)))
    by_route = collections.defaultdict(int)
    for row in source_counts:
        by_route[row["identification_route"]] += row["identified_records"]
    totals = {k: sum(row[k] for row in source_counts) for k in (
        "identified_records", "removed_duplicates", "removed_other", "screened_records",
        "reports_sought", "reports_not_retrieved", "retrieval_pending", "reports_retrieved",
        "reports_assessed", "assessment_pending", "reports_excluded", "included_reports")}
    totals.update(database_register_identified=by_route["database_register"],
                  other_source_identified=by_route["other_source"],
                  title_abstract_excluded=sum(row["decision"] == "exclude" for (rid, stage), row in stages.items()
                                              if stage == "title_abstract"),
                  title_abstract_pending=sum(row["decision"] == "pending" for (rid, stage), row in stages.items()
                                             if stage == "title_abstract"),
                  included_studies=len({m["study_id"] for m in mapping}))
    if totals["identified_records"] != totals["removed_duplicates"] + totals["removed_other"] + totals["screened_records"]:
        lit.fail("identified/pre-screen counts do not reconcile")
    if totals["screened_records"] != totals["title_abstract_excluded"] + totals["title_abstract_pending"] + totals["reports_sought"]:
        lit.fail("screening/sought counts do not reconcile")
    if totals["reports_sought"] != totals["reports_not_retrieved"] + totals["retrieval_pending"] + totals["reports_retrieved"]:
        lit.fail("retrieval counts do not reconcile")
    if totals["reports_retrieved"] != totals["reports_assessed"] + totals["assessment_pending"] or \
            totals["reports_assessed"] != totals["reports_excluded"] + totals["included_reports"]:
        lit.fail("assessment and report decisions do not reconcile")
    reasons = collections.Counter()
    for rid, item in retrieval.items():
        if item["status"] == "not_retrieved":
            reasons[("not_retrieved", item["reason"].strip())] += 1
        if item["status"] == "retrieved" and stages[(rid, "full_text")]["decision"] == "exclude":
            reasons[("full_text_excluded", stages[(rid, "full_text")]["reason"].strip())] += 1
    reason_rows = [dict(stage=stage, reason=reason, report_count=count)
                   for (stage, reason), count in sorted(reasons.items())]
    if sum(r["report_count"] for r in reason_rows if r["stage"] == "full_text_excluded") != totals["reports_excluded"]:
        lit.fail("full-text exclusion reason counts do not reconcile")
    return receipt, totals, source_counts, reason_rows


def diagram(n):
    def box(x, y, title, body):
        return (f'<rect x="{x}" y="{y}" width="480" height="82" rx="7" fill="#f3f6f9" stroke="#35516c"/>'
                f'<text x="{x+14}" y="{y+29}" font-size="18" font-family="Arial">{escape(title)}</text>'
                f'<text x="{x+14}" y="{y+57}" font-size="16" font-family="Arial">{escape(str(body))}</text>')
    cells = [box(35, 70, "Databases/registers identified", n["database_register_identified"]),
             box(555, 70, "Other sources identified", n["other_source_identified"]),
             box(35, 180, "Removed before screening", f'{n["removed_duplicates"]} duplicates; {n["removed_other"]} other'),
             box(555, 180, "Records screened", n["screened_records"]),
             box(35, 290, "Title/abstract excluded or pending", f'{n["title_abstract_excluded"]} excluded; {n["title_abstract_pending"]} pending'),
             box(555, 290, "Reports sought", n["reports_sought"]),
             box(35, 400, "Retrieval unresolved", f'{n["reports_not_retrieved"]} not retrieved; {n["retrieval_pending"]} pending'),
             box(555, 400, "Reports retrieved", n["reports_retrieved"]),
             box(35, 510, "Retrieved, assessment pending", n["assessment_pending"]),
             box(555, 510, "Reports assessed", n["reports_assessed"]),
             box(35, 620, "Reports excluded with reasons", n["reports_excluded"]),
             box(555, 620, "Included reports / unique studies", f'{n["included_reports"]} / {n["included_studies"]}')]
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="1070" height="780" viewBox="0 0 1070 780">'
            '<rect width="1070" height="780" fill="white"/>'
            '<text x="35" y="38" font-size="23" font-family="Arial">Local PRISMA 2020 selection ledger view</text>'
            + ''.join(cells) + '<text x="35" y="760" font-size="14" font-family="Arial">'
            'Original summary diagram; not an official template or a compliance certificate.</text></svg>')


def item_audit(n):
    # Item numbers are references, not copied checklist text or automatic compliance scores.
    supported = {
        "4": ("protocol PICO", "user must check objective"),
        "5": ("protocol eligibility fields", "human grouping rationale required"),
        "6": ("source_methods.csv", "verify every source and actual search date"),
        "7": ("strategy_reference fields", "full strategies/limits not contained or authenticated here"),
        "8": ("screening_ledger.csv", "reviewer process and independence require human description"),
        "9": ("", "data collection process and any separate source-review ledger are not bound here"),
        "10": ("protocol outcome", "other variables and result selection need human review"),
        "11": ("", "RoB instrument and human judgments are not bound in this flow"),
        "12": ("analysis.csv", "human effect-scale rationale required"),
        "13": ("analysis.csv and linked effects", "model rationale, missing data, heterogeneity and applicability need review"),
        "16": ("prisma_flow_counts.csv and reason_counts.csv", "confirm actual source coverage and potentially eligible exclusions"),
        "17": ("report_map.csv", "full study characteristics and citations need human verification"),
        "18": ("", "RoB assessments are not bound in this flow"),
        "19": ("effect trace", "group summaries may be absent"),
        "20": ("", "statistical result packet is not bound in this flow; human interpretation required"),
        "24": ("protocol JSON", "registration/amendments must be declared by user"),
        "27": ("local manifest", "public availability and location require user decision"),
    }
    items = []
    for i in range(1, 28):
        artifact, gap = supported.get(str(i), ("", "human reporting/applicability decision required"))
        items.append(dict(item=str(i), applicability="HUMAN_REVIEW_REQUIRED",
                          local_artifact=artifact, has_local_artifact=bool(artifact),
                          gap_status="HUMAN_VERIFICATION_REQUIRED" if artifact else "NO_LOCAL_ARTIFACT_MAPPED",
                          missing_or_human_check=gap, automatic_compliance=False))
    return dict(schema="meta-prisma-item-audit-v1", official_checklist=OFFICIAL_CHECKLIST,
                scope="targeted local artifact map; official checklist and all subitems require human review",
                selection_decisions_complete=not any(n[key] for key in
                    ("title_abstract_pending", "retrieval_pending", "assessment_pending")),
                search_coverage_authenticated=False, automatic_prisma_compliance=False, items=items)


def generate(a):
    receipt, totals, source_rows, reasons = calculate(a)
    final = Path(a.out)
    if final.exists():
        lit.fail("output already exists")
    final.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".prisma-flow-", dir=final.parent) as temp:
        stage = Path(temp) / "packet"
        stage.mkdir()
        lit.write_csv(stage / "prisma_flow_counts.csv", ["unit", "metric", "count"],
            [dict(unit=("study" if key == "included_studies" else "report" if key.startswith("report") or
                        key in {"retrieval_pending", "assessment_pending", "included_reports"} else "record"),
                  metric=key, count=value) for key, value in totals.items()])
        lit.write_csv(stage / "source_route_counts.csv", list(source_rows[0]), source_rows)
        lit.write_csv(stage / "reason_counts.csv", ["stage", "reason", "report_count"], reasons)
        (stage / "prisma_flow.svg").write_text(diagram(totals), encoding="utf-8")
        (stage / "prisma_item_audit.json").write_text(json.dumps(item_audit(totals), indent=2) + "\n", encoding="utf-8")
        (stage / "README.md").write_text(
            "# Local selection accounting\n\nHuman-entered source and retrieval fields were checked for internal consistency. "
            "Source coverage, original reports, screening judgments and search origins were not independently authenticated. "
            "Pending stages remain visible. This original diagram is not an official PRISMA template or a compliance claim.\n\n"
            f"Official checklist: {OFFICIAL_CHECKLIST}\nOfficial flow templates: {OFFICIAL_FLOW}\n"
            "PRISMA 2020 statement/checklist/templates: CC BY 4.0; Page et al., BMJ 2021;372:n71, DOI 10.1136/bmj.n71.\n",
            encoding="utf-8")
        lit.write_csv(stage / "flow_manifest.csv", ["key", "value"], [
            dict(key="confirmation_sha256", value=lit.sha256(a.confirmation)),
            dict(key="source_methods_sha256", value=lit.sha256(a.source_methods)),
            dict(key="retrieval_sha256", value=lit.sha256(a.retrieval)),
            dict(key="prisma_flow_counts_sha256", value=lit.sha256(stage / "prisma_flow_counts.csv")),
            dict(key="source_route_counts_sha256", value=lit.sha256(stage / "source_route_counts.csv")),
            dict(key="reason_counts_sha256", value=lit.sha256(stage / "reason_counts.csv")),
            dict(key="prisma_flow_svg_sha256", value=lit.sha256(stage / "prisma_flow.svg")),
            dict(key="prisma_item_audit_sha256", value=lit.sha256(stage / "prisma_item_audit.json")),
            dict(key="protocol_id", value=receipt["protocol_id"]),
            dict(key="status", value="LOCAL_DECISIONS_COMPLETE" if item_audit(totals)["selection_decisions_complete"]
                 else "LOCAL_DECISIONS_PENDING")])
        os.replace(stage, final)
    print(f"Wrote local flow: {totals['included_reports']} reports / {totals['included_studies']} studies; "
          f"{totals['reports_not_retrieved']} not retrieved")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in review.INPUTS:
        parser.add_argument("--" + key.replace("_", "-"), dest=key, required=True)
    for key in ("confirmation", "source_methods", "retrieval", "out"):
        parser.add_argument("--" + key.replace("_", "-"), dest=key, required=True)
    a = parser.parse_args()
    try:
        generate(a)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"Validation: {exc}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
