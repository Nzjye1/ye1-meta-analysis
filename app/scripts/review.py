"""Local protocol confirmation and record/report/study flow accounting. Standard library only."""
import argparse
import csv
import datetime as dt
import hashlib
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from xml.sax.saxutils import escape

import literature as lit

INPUTS = ("protocol", "records", "dedup", "decisions", "ledger", "source_effects",
          "effects", "analysis", "report_map")
DECLARATIONS = {
    "real": "I reviewed and approve the protocol and linked inputs",
    "synthetic_test": "SYNTHETIC TEST CONFIRMATION",
}


def filled(value):
    return isinstance(value, str) and bool(value.strip())


def load_protocol(path):
    with Path(path).open(encoding="utf-8") as handle:
        p = json.load(handle)
    if p.get("planning_status") == "PENDING_HUMAN_REVIEW":
        lit.fail("protocol is a planning candidate; complete actual review before confirmation")
    for key in ("protocol_id", "question", "eligible_designs", "inclusion_criteria",
                "exclusion_criteria", "sensitivity_plan", "pico", "outcome", "analysis"):
        if key not in p:
            lit.fail(f"protocol missing {key}")
    if not all(isinstance(p[key], dict) for key in ("pico", "outcome", "analysis")):
        lit.fail("protocol pico, outcome, and analysis must be objects")
    for key in ("protocol_id", "question"):
        if not filled(p[key]):
            lit.fail(f"protocol {key} must be nonblank")
    for key in ("population", "intervention", "comparator"):
        if not filled(p["pico"].get(key)):
            lit.fail(f"protocol PICO {key} must be nonblank")
    for key in ("eligible_designs", "inclusion_criteria", "exclusion_criteria", "sensitivity_plan"):
        if not isinstance(p[key], list) or not p[key] or not all(filled(x) for x in p[key]):
            lit.fail(f"protocol {key} needs a nonempty text list")
    for key in ("name", "timepoint", "effect_type", "direction"):
        if not filled(p["outcome"].get(key)):
            lit.fail(f"protocol outcome {key} must be nonblank")
    if p["outcome"]["effect_type"] not in {"RR", "OR", "HR", "MD", "SMD"}:
        lit.fail("protocol effect_type invalid")
    for key in ("contrast", "adjustment", "model", "tau_method", "test", "alpha"):
        if key not in p["analysis"] or str(p["analysis"][key]).strip() == "":
            lit.fail(f"protocol analysis {key} missing")
    if (p["analysis"]["model"], p["analysis"]["tau_method"]) not in {
            ("FE", "NONE"), ("RE", "REML"), ("RE", "DL")}:
        lit.fail("protocol model/tau_method mismatch")
    if p["analysis"]["test"] != "z":
        lit.fail("only z test supported")
    if p.get("review_workflow_mode", "legacy_unclassified") not in {
            "legacy_unclassified", "exploratory_single", "formal_dual"}:
        lit.fail("protocol review_workflow_mode must be exploratory_single or formal_dual")
    try:
        alpha = float(p["analysis"]["alpha"])
    except (TypeError, ValueError):
        lit.fail("protocol alpha invalid")
    if not 0 < alpha < .5:
        lit.fail("protocol alpha invalid")
    return p


def validate_inputs(a):
    p = load_protocol(a.protocol)
    from fulltext_extract import verify_export
    source_fields = lit.read_csv(a.source_effects, ["record_id", "study_id"])[1]
    if "extraction_review_mode" in source_fields or (Path(a.source_effects).resolve().parent / "review_receipt.json").exists():
        verify_export(a.source_effects)
    from dual_screen import verify_if_marked
    verify_if_marked(a.records, a.dedup, a.decisions)
    records, _ = lit.read_csv(a.records, ["record_id", "title", "doi", "pmid", "year"])
    by_id = {r["record_id"]: r for r in records}
    if len(by_id) != len(records):
        lit.fail("records.csv has conflicting record IDs")
    dedup = lit.load_dedup(records, a.dedup)
    active = {rid for rid in by_id if dedup[rid]["disposition"] == "keep"}
    ledger, _ = lit.read_csv(a.ledger, ["record_id", "stage", "decision", "reason", "reviewer", "decision_date"])
    source_decisions, _ = lit.read_csv(a.decisions,
                                       ["record_id", "stage", "decision", "reason", "reviewer", "decision_date"])
    if p.get("review_workflow_mode") == "formal_dual":
        if not all(row.get("screening_review_mode") == "formal_dual" for row in source_decisions):
            lit.fail("formal_dual protocol requires a completed formal dual-screen decision file")
        source_rows, _ = lit.read_csv(a.source_effects, ["record_id", "study_id"])
        if not all(row.get("extraction_review_mode") == "formal_dual" for row in source_rows):
            lit.fail("formal_dual protocol requires completed formal dual value-review extraction")
    decision_fields = ("record_id", "stage", "decision", "reason", "reviewer", "decision_date",
                       "revision_of", "revision_reason")
    if len(source_decisions) != len(ledger) or any(
            tuple(source_row.get(k, "") for k in decision_fields) !=
            tuple(ledger_row.get(k, "") for k in decision_fields)
            for source_row, ledger_row in zip(source_decisions, ledger)):
        lit.fail("screening ledger disagrees with source decision CSV; regenerate it")
    stage_rows, included = lit.validate_screening(records, ledger, active)
    mapping, _ = lit.read_csv(a.report_map, ["record_id", "report_id", "study_id"], allow_empty=True)
    if len(mapping) != len(included) or {r["record_id"] for r in mapping} != included:
        lit.fail("report_map must have exactly one row for each included full-text record")
    if any(not filled(r["report_id"]) or not filled(r["study_id"]) for r in mapping):
        lit.fail("report_map has blank report_id or study_id")
    if len({r["report_id"] for r in mapping}) != len(mapping):
        lit.fail("report_id repeated; adjudicate records referring to one report")
    map_by_record = {r["record_id"]: r for r in mapping}
    effects, _ = lit.read_csv(a.effects, ["record_id", "study_id", "cohort_id", "effect_type",
                                                "outcome", "timepoint", "contrast", "adjustment", "source_location"],
                              allow_empty=True)
    source_effects, _ = lit.read_csv(a.source_effects,
                                     ["record_id", "study_id", "cohort_id", "effect_type", "outcome",
                                      "timepoint", "contrast", "adjustment", "source_location"], allow_empty=True)
    if source_effects != effects:
        lit.fail("linked effects disagree with source extraction CSV; regenerate link")
    for i, row in enumerate(effects, 2):
        if row["record_id"] not in map_by_record:
            lit.fail(f"effect row {i}: record not an included report")
        if row["study_id"] != map_by_record[row["record_id"]]["study_id"]:
            lit.fail(f"effect row {i}: study_id disagrees with report_map")
        if not re.search(r"(?i)(page|p\.|table|figure|fig\.)\s*[A-Za-z0-9]",row["source_location"] or ""):
            lit.fail(f"effect row {i}: source locator missing")
    plan, _ = lit.read_csv(a.analysis, ["confirmed", "effect_type", "outcome", "timepoint", "contrast",
                                             "adjustment", "model", "tau_method", "test", "alpha"])
    if len(plan) != 1 or plan[0]["confirmed"] != "YES":
        lit.fail("analysis.csv needs one confirmed=YES row; this is separate from protocol approval")
    plan = plan[0]
    expected = {"effect_type": p["outcome"]["effect_type"], "outcome": p["outcome"]["name"],
                "timepoint": p["outcome"]["timepoint"],
                **{key: p["analysis"][key] for key in ("contrast", "adjustment", "model", "tau_method", "test")}}
    for key, value in expected.items():
        if plan[key] != value:
            lit.fail(f"analysis.csv {key} disagrees with protocol")
    if abs(float(plan["alpha"]) - float(p["analysis"]["alpha"])) > 1e-12:
        lit.fail("analysis.csv alpha disagrees with protocol")
    for i, row in enumerate(effects, 2):
        for key in ("effect_type", "outcome", "timepoint", "contrast", "adjustment"):
            if row[key] != expected[key]:
                lit.fail(f"effect row {i}: {key} disagrees with protocol")
    return p, records, dedup, stage_rows, mapping, effects


def hashes(a):
    return {name: lit.sha256(getattr(a, name)) for name in INPUTS}


def source_provenance(a, records, mode, seen=None):
    """Check local evidence consistency; local hashes cannot authenticate its origin."""
    records_path = Path(a.records).resolve()
    seen = set() if seen is None else set(seen)
    if records_path in seen:
        lit.fail("cyclic bibliography source catalog")
    seen.add(records_path)
    folder = records_path.parent
    catalog_path = folder / "source_catalog.json"
    if catalog_path.is_file():
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        sources = catalog.get("sources", [])
        if (catalog.get("schema") != "meta-merged-sources-v1" or
                not isinstance(sources, list) or not 2 <= len(sources) <= 20 or
                catalog.get("source_count") != len(sources) or
                catalog.get("record_count") != len(records)):
            lit.fail("invalid merged source catalog")
        merge_manifest, _ = lit.read_csv(folder / "merge_manifest.csv", ["key", "value"])
        merge_values = {r["key"]: r["value"] for r in merge_manifest}
        if (len(merge_values) != len(merge_manifest) or
                merge_values.get("status") != "READY_FOR_DEDUP_REVIEW" or
                merge_values.get("records_sha256") != lit.sha256(records_path) or
                merge_values.get("source_catalog_sha256") != lit.sha256(catalog_path)):
            lit.fail("merged source manifest changed or incomplete")
        merged = {r["record_id"]: r for r in records}
        if len(merged) != len(records):
            lit.fail("merged records contain repeated record_id")
        covered, labels, children = set(), set(), []
        for entry in sources:
            path = Path(entry["records_path"]).resolve()
            if not path.is_file() or lit.sha256(path) != entry.get("records_sha256"):
                lit.fail("a source bibliography changed since merge")
            child_rows, _ = lit.read_csv(path, ["record_id", "source_label", "source_record_id",
                                                "title", "authors", "year", "doi", "pmid"])
            label = entry["source_label"]
            if label in labels or {r["source_label"] for r in child_rows} != {label} or \
                    entry.get("identified_records") != len(child_rows):
                lit.fail("merged source label/count mismatch")
            labels.add(label)
            for child in child_rows:
                rid = child["record_id"]
                if rid in covered or rid not in merged or any(
                        merged[rid].get(key, "") != child.get(key, "") for key in
                        ("record_id", "source_label", "source_record_id", "title", "authors",
                         "year", "doi", "pmid", "source_type")):
                    lit.fail("merged record differs from its source or ID is repeated")
                covered.add(rid)
            child_provenance = source_provenance(
                SimpleNamespace(records=path, protocol=a.protocol), child_rows, mode, seen)
            children.append({"source_label": label, "records_sha256": lit.sha256(path),
                             "provenance": child_provenance})
        if covered != set(merged):
            lit.fail("merged source catalog does not cover all records")
        return {"kind": "multi_source_local_evidence", "source_labels": sorted(labels),
                "search_completeness": "MULTISOURCE_COVERAGE_NOT_ESTABLISHED",
                "origin_authentication": "NOT_INDEPENDENTLY_AUTHENTICATED",
                "bound_sha256": {"source_catalog.json": lit.sha256(catalog_path),
                                 "merge_manifest.csv": lit.sha256(folder / "merge_manifest.csv")},
                "sources": children}
    marker = folder / "search_provenance.json"
    tagged = {r.get("source_type", "") for r in records}
    if not marker.is_file():
        original=folder/"original_import.csv"
        if original.is_file():
            raw,fields=lit.read_csv(original,("source_record_id","title","year"))
            if "source_type" in fields and any(r["source_type"]=="europe_pmc_rest" for r in raw):
                lit.fail("Europe PMC export requires its search provenance marker")
        if "pubmed_eutils" in tagged:
            lit.fail("PubMed-tagged records require their search_provenance.json")
        evidence = {name: lit.sha256(folder / name) for name in
                    ("import_manifest.csv", "original_import.csv", "original_import.ris", "ris_tags.csv")
                    if (folder / name).is_file()}
        return {"kind": "manual_import_or_unverified_source", "source_labels":
                sorted({r.get("source_label", "") for r in records}),
                "search_completeness": "NOT_ESTABLISHED",
                "origin_authentication": "NOT_INDEPENDENTLY_AUTHENTICATED", "bound_sha256": evidence}
    marker_type=json.loads(marker.read_text(encoding="utf-8")).get("source_type")
    if marker_type=="europe_pmc_rest":
        import europe_pmc_search
        query,status,_=europe_pmc_search.check_provenance(folder)
        if mode=="real":
            if status["mode"]!="LIVE_EUROPE_PMC" or status["completeness"]!="LIVE_COUNT_RECONCILED_LOCAL_CLAIM" or \
                    query["query_review_status"]!="human_reviewed" or \
                    query["pico_sha256"]!=lit.sha256(a.protocol):
                lit.fail("real Europe PMC source needs complete live count, reviewed strategy and matching PICO")
        elif status["mode"]!="OFFLINE_FIXTURE" or status["completeness"]!="FIXTURE_COUNT_RECONCILED":
            lit.fail("synthetic Europe PMC source needs reconciled offline fixture")
        return {"kind":"europe_pmc_rest_local_evidence","source_labels":[query["source_label"]],
                "search_completeness":status["completeness"],"query_review_status":query["query_review_status"],
                "origin_authentication":"LOCAL_HASHES_NOT_INDEPENDENT_AUTHENTICATION",
                "bound_sha256":{"search_provenance.json":lit.sha256(marker),
                                "search_manifest.csv":lit.sha256(folder.parent/"search_manifest.csv")}}
    if tagged != {"pubmed_eutils"}:
        lit.fail("PubMed provenance marker requires every record to be PubMed-tagged")
    with marker.open(encoding="utf-8") as handle:
        provenance = json.load(handle)
    if (provenance.get("schema") != "meta-search-provenance-v1" or
            provenance.get("source_type") != "pubmed_eutils" or
            provenance.get("search_root") != ".."):
        lit.fail("invalid PubMed provenance marker")
    root = folder.parent.resolve()
    names = ("query_receipt.json", "search_status.json", "search_manifest.csv",
             "result_ledger.csv", "pubmed_export.csv")
    if any(not (root / name).is_file() for name in names):
        lit.fail("PubMed search receipt/status/manifest/export missing")
    for name, key in (("query_receipt.json", "query_receipt_sha256"),
                      ("search_status.json", "search_status_sha256"),
                      ("result_ledger.csv", "result_ledger_sha256"),
                      ("pubmed_export.csv", "pubmed_export_sha256")):
        if provenance.get(key) != lit.sha256(root / name):
            lit.fail(f"PubMed provenance changed: {name}")
    manifest, _ = lit.read_csv(root / "search_manifest.csv", ["relative_path", "sha256", "bytes"])
    paths = [row["relative_path"] for row in manifest]
    if len(paths) != len(set(paths)):
        lit.fail("PubMed search manifest has repeated paths")
    required = {"query_receipt.json", "search_status.json", "result_ledger.csv",
                "pubmed_export.csv", "bibliography/records.csv",
                "bibliography/search_provenance.json", "raw/esearch.json"}
    if not required <= set(paths):
        lit.fail("PubMed search manifest lacks required evidence files")
    for row in manifest:
        item = (root / row["relative_path"]).resolve()
        if not item.is_relative_to(root) or not item.is_file():
            lit.fail("PubMed search manifest path missing or outside search root")
        if lit.sha256(item) != row["sha256"] or item.stat().st_size != int(row["bytes"]):
            lit.fail(f"PubMed search evidence changed: {row['relative_path']}")
    query = json.loads((root / "query_receipt.json").read_text(encoding="utf-8"))
    status = json.loads((root / "search_status.json").read_text(encoding="utf-8"))
    label = provenance["source_label"]
    if label != query.get("source_label") or {r.get("source_label") for r in records} != {label}:
        lit.fail("PubMed source label disagrees with records or query")
    if status.get("status") != "SUCCESS" or status.get("retrieved") != len(records) or \
            status.get("database_count") != len(records):
        lit.fail("PubMed retrieval incomplete or count disagrees with bibliography")
    if query.get("mode") != status.get("mode") or query.get("query_review_status") != status.get("query_review_status"):
        lit.fail("PubMed query/status mode or review state disagrees")
    if mode == "real":
        if (status.get("mode") != "LIVE_NCBI" or
                status.get("completeness") != "LIVE_QUERY_COUNT_RECONCILED_LOCAL_CLAIM" or
                query.get("query_review_status") != "human_reviewed" or
                not filled(query.get("reviewer")) or not filled(query.get("approval_ref")) or
                query.get("pico_sha256") != lit.sha256(a.protocol)):
            lit.fail("real protocol requires locally reconciled live-mode claim, user-reviewed strategy, and matching PICO hash; origin is not authenticated")
    elif status.get("mode") != "OFFLINE_FIXTURE" or status.get("completeness") != "FIXTURE_QUERY_COUNT_RECONCILED":
        lit.fail("synthetic PubMed test requires a fully reconciled offline fixture")
    result_rows, _ = lit.read_csv(root / "result_ledger.csv", ["pmid", "record_id", "source_label"])
    actual = {(r["pmid"], r["record_id"], r["source_label"]) for r in records}
    if len(result_rows) != len(records) or actual != {
            (r["pmid"], r["record_id"], r["source_label"]) for r in result_rows}:
        lit.fail("PubMed result IDs disagree with imported bibliography")
    return {"kind": "pubmed_eutils_local_evidence", "source_labels": [label],
            "search_completeness": status["completeness"],
            "query_review_status": query["query_review_status"],
            "origin_authentication": "NOT_INDEPENDENTLY_AUTHENTICATED",
            "bound_sha256": {"search_provenance.json": lit.sha256(marker),
                             "search_manifest.csv": lit.sha256(root / "search_manifest.csv"),
                             **{name: lit.sha256(root / name) for name in names if name != "search_manifest.csv"}}}


def payload_digest(payload):
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def confirm(a):
    p, records, *_ = validate_inputs(a)
    if a.declaration != DECLARATIONS[a.mode]:
        lit.fail("confirmation declaration does not match selected mode")
    if not filled(a.reviewer) or not filled(a.approval_reference):
        lit.fail("reviewer and approval_reference are required")
    if a.mode == "synthetic_test" and (not p["protocol_id"].startswith("SYNTHETIC-") or
                                       not all("SYNTHETIC" in r["title"] for r in records)):
        lit.fail("synthetic_test mode requires explicitly synthetic protocol and records")
    provenance = source_provenance(a, records, a.mode)
    body = {"schema": "meta-protocol-confirmation-v2", "protocol_id": p["protocol_id"],
            "mode": a.mode, "reviewer": a.reviewer, "approval_reference": a.approval_reference,
            "declaration": a.declaration, "confirmed_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "input_sha256": hashes(a), "source_provenance": provenance,
            "meaning": "synthetic test only" if a.mode == "synthetic_test" else "user-attested local file consistency; NCBI origin and human identity not independently authenticated"}
    receipt = {**body, "receipt_sha256": payload_digest(body)}
    out = lit.fresh_dir(a.out)
    (out / "confirmation.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Recorded {p['protocol_id']} in {a.mode} mode; local hashes bind nine inputs and source files without authenticating origin")


def checked_receipt(a):
    with Path(a.confirmation).open(encoding="utf-8") as handle:
        receipt = json.load(handle)
    body = {k: v for k, v in receipt.items() if k != "receipt_sha256"}
    if receipt.get("receipt_sha256") != payload_digest(body):
        lit.fail("confirmation receipt integrity mismatch")
    if receipt.get("input_sha256") != hashes(a):
        lit.fail("stale confirmation: protocol, records, dedup, decisions, ledger, extraction, analysis, or report map changed")
    p, records, dedup, stage_rows, mapping, effects = validate_inputs(a)
    if receipt.get("protocol_id") != p["protocol_id"]:
        lit.fail("confirmation protocol ID mismatch")
    current_source = source_provenance(a, records, receipt["mode"])
    if receipt.get("source_provenance") is None:
        if current_source["kind"] in {"pubmed_eutils_local_evidence","europe_pmc_rest_local_evidence"}:
            lit.fail("legacy confirmation cannot bind an online search source; reconfirm")
    elif receipt["source_provenance"] != current_source:
        lit.fail("stale confirmation: bibliography source or PubMed search evidence changed")
    return receipt, records, dedup, stage_rows, mapping, effects


def verify(a):
    receipt, *_ = checked_receipt(a)
    print(f"VALID {receipt['protocol_id']} ({receipt['mode']}); input and source hashes match")


def compute_counts(records, dedup, stage_rows, mapping, effects):
    active = {rid for rid in dedup if dedup[rid]["disposition"] == "keep"}
    ta = [stage_rows[(rid, "title_abstract")]["decision"] for rid in active]
    ft = [stage_rows[(rid, "full_text")]["decision"] for rid in active if (rid, "full_text") in stage_rows]
    studies = {r["study_id"] for r in mapping}
    effect_studies = {r["study_id"] for r in effects}
    if not effect_studies <= studies:
        lit.fail("effect studies outside included report mapping")
    values = [
        ("record", "identified", len(records)),
        ("record", "removed_duplicate_by_decision", sum(r["disposition"] == "remove_duplicate" for r in dedup.values())),
        ("record", "removed_other_before_screening", sum(r["disposition"] == "remove_other" for r in dedup.values())),
        ("record", "screened_title_abstract", len(active)),
        ("record", "title_abstract_excluded", ta.count("exclude")),
        ("record", "title_abstract_pending", ta.count("pending")),
        ("record", "advanced_to_full_text", ta.count("include")),
        ("report", "full_text_excluded", ft.count("exclude")),
        ("report", "full_text_pending", ft.count("pending")),
        ("report", "full_text_included", ft.count("include")),
        ("study", "included_unique", len(studies)),
        ("study", "with_extracted_effect", len(effect_studies)),
        ("effect", "linked_rows", len(effects)),
    ]
    numbers = {metric: n for _, metric, n in values}
    if numbers["identified"] != (numbers["removed_duplicate_by_decision"] +
                                  numbers["removed_other_before_screening"] +
                                  numbers["screened_title_abstract"]):
        lit.fail("identification counts do not reconcile")
    if numbers["screened_title_abstract"] != sum(numbers[k] for k in (
            "title_abstract_excluded", "title_abstract_pending", "advanced_to_full_text")):
        lit.fail("title/abstract counts do not reconcile")
    if numbers["advanced_to_full_text"] != sum(numbers[k] for k in (
            "full_text_excluded", "full_text_pending", "full_text_included")):
        lit.fail("full-text counts do not reconcile")
    if numbers["full_text_included"] != len(mapping) or len(studies) > len(mapping):
        lit.fail("report/study units do not reconcile")
    by_study = {}
    for row in mapping:
        by_study.setdefault(row["study_id"], []).append(row["report_id"])
    return values, numbers, by_study


def compute_source_counts(records, dedup, stage_rows, mapping, effects, overall):
    """Record/report/effect counts by import source; study counts are nonadditive."""
    labels = sorted({r.get("source_label", "UNLABELED") or "UNLABELED" for r in records})
    by_source = {label: [r for r in records if (r.get("source_label") or "UNLABELED") == label]
                 for label in labels}
    source_by_id = {r["record_id"]: r.get("source_label") or "UNLABELED" for r in records}
    result = []
    for label, group in by_source.items():
        ids = {r["record_id"] for r in group}
        kept = {rid for rid in ids if dedup[rid]["disposition"] == "keep"}
        ta = [stage_rows[(rid, "title_abstract")]["decision"] for rid in kept]
        ft = [stage_rows[(rid, "full_text")]["decision"] for rid in kept
              if (rid, "full_text") in stage_rows]
        reports = [r for r in mapping if r["record_id"] in ids]
        kinds = {r.get("source_type") or "manual_import" for r in group}
        result.append(dict(source_label=label, source_type="|".join(sorted(kinds)),
            identified_records=len(ids),
            removed_duplicate_by_decision=sum(dedup[rid]["disposition"] == "remove_duplicate" for rid in ids),
            removed_other_before_screening=sum(dedup[rid]["disposition"] == "remove_other" for rid in ids),
            screened_title_abstract=len(kept), title_abstract_excluded=ta.count("exclude"),
            title_abstract_pending=ta.count("pending"), advanced_to_full_text=ta.count("include"),
            full_text_excluded=ft.count("exclude"), full_text_pending=ft.count("pending"),
            included_reports=len(reports), included_studies_within_source=len({r["study_id"] for r in reports}),
            linked_effect_rows=sum(source_by_id[e["record_id"]] == label for e in effects)))
    checks = {"identified_records": "identified", "removed_duplicate_by_decision": "removed_duplicate_by_decision",
              "removed_other_before_screening": "removed_other_before_screening",
              "screened_title_abstract": "screened_title_abstract", "title_abstract_excluded": "title_abstract_excluded",
              "title_abstract_pending": "title_abstract_pending", "advanced_to_full_text": "advanced_to_full_text",
              "full_text_excluded": "full_text_excluded", "full_text_pending": "full_text_pending",
              "included_reports": "full_text_included", "linked_effect_rows": "linked_rows"}
    for source_key, overall_key in checks.items():
        if sum(row[source_key] for row in result) != overall[overall_key]:
            lit.fail(f"source counts do not reconcile: {source_key}")
    return result


def flow_svg(numbers):
    """A labeled local subset diagram, not the complete PRISMA 2020 flow."""
    def box(x, y, w, h, first, second):
        return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="9" fill="#f2f6fb" '
                f'stroke="#45617f"/><text x="{x+14}" y="{y+27}" font-size="17" '
                f'font-family="Arial" fill="#152b45">{escape(first)}</text>'
                f'<text x="{x+14}" y="{y+53}" font-size="16" font-family="Arial" '
                f'fill="#264866">{escape(second)}</text>')
    b = box(240, 75, 380, 68, "Records identified", str(numbers["identified"]))
    b += box(670, 75, 370, 68, "Pre-screen removals", f'{numbers["removed_duplicate_by_decision"]} duplicate; {numbers["removed_other_before_screening"]} other')
    b += box(240, 185, 380, 68, "Title/abstract screened", str(numbers["screened_title_abstract"]))
    b += box(670, 185, 370, 68, "Excluded / pending", f'{numbers["title_abstract_excluded"]} / {numbers["title_abstract_pending"]}')
    b += box(240, 295, 380, 68, "Advanced to full-text stage", str(numbers["advanced_to_full_text"]))
    b += box(670, 295, 370, 68, "Full-text excluded / pending", f'{numbers["full_text_excluded"]} / {numbers["full_text_pending"]}')
    b += box(240, 405, 380, 68, "Included reports", str(numbers["full_text_included"]))
    b += box(240, 515, 380, 68, "Unique included studies", str(numbers["included_unique"]))
    arrows = ''.join(f'<path d="M430 {a} V{z}" stroke="#45617f" stroke-width="2" fill="none" marker-end="url(#arrow)"/>'
                     for a, z in ((143, 181), (253, 291), (363, 401), (473, 511)))
    arrows += ''.join(f'<path d="M620 {y} H665" stroke="#45617f" stroke-width="2" fill="none" marker-end="url(#arrow)"/>'
                      for y in (109, 219, 329))
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="1080" height="650" viewBox="0 0 1080 650">'
            '<defs><marker id="arrow" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto">'
            '<path d="M0 0 L7 3.5 L0 7 Z" fill="#45617f"/></marker></defs>'
            '<rect width="1080" height="650" fill="white"/>'
            '<text x="50" y="38" font-size="23" font-family="Arial" fill="#152b45">Local screening flow subset</text>'
            + arrows + b +
            '<text x="50" y="625" font-size="15" font-family="Arial" fill="#6a3340">'
            'Not a complete PRISMA 2020 diagram; search and retrieval steps are not covered.</text></svg>')


def count(a):
    receipt, records, dedup, stage_rows, mapping, effects = checked_receipt(a)
    values, numbers, by_study = compute_counts(records, dedup, stage_rows, mapping, effects)
    source_counts = compute_source_counts(records, dedup, stage_rows, mapping, effects, numbers)
    effect_studies = {r["study_id"] for r in effects}
    out = lit.fresh_dir(a.out)
    lit.write_csv(out / "prisma_counts.csv", ["unit", "metric", "count"],
                  [{"unit": u, "metric": m, "count": n} for u, m, n in values])
    lit.write_csv(out / "source_counts.csv", list(source_counts[0]), source_counts)
    lit.write_csv(out / "report_study_reconciliation.csv",
                  ["study_id", "report_count", "report_ids", "has_extracted_effect"],
                  [{"study_id": sid, "report_count": len(ids), "report_ids": "|".join(sorted(ids)),
                    "has_extracted_effect": "YES" if sid in effect_studies else "NO"}
                   for sid, ids in sorted(by_study.items())])
    lines = ["# Local PRISMA-style flow accounting", "",
             f"Protocol: {receipt['protocol_id']}; confirmation mode: {receipt['mode']}.",
             "Counts are by explicit unit. This is a reconciled subset, not a complete PRISMA 2020 flow diagram.",
             "Duplicate candidate flags alone remove zero records; only recorded remove_duplicate decisions count.", "",
             f"Records identified: {numbers['identified']}; explicitly removed duplicates: {numbers['removed_duplicate_by_decision']}; other recorded pre-screen removals: {numbers['removed_other_before_screening']}; title/abstract screened: {numbers['screened_title_abstract']}.",
             f"Title/abstract excluded: {numbers['title_abstract_excluded']}; pending: {numbers['title_abstract_pending']}; advanced: {numbers['advanced_to_full_text']}.",
             f"Full-text reports excluded: {numbers['full_text_excluded']}; pending: {numbers['full_text_pending']}; included: {numbers['full_text_included']}.",
             f"Unique included studies: {numbers['included_unique']}; studies with extracted effects: {numbers['with_extracted_effect']}; effect rows: {numbers['linked_rows']}.",
             "", "## By imported source (record/report/effect units)", ""]
    lines += [f"- {r['source_label']} ({r['source_type']}): identified {r['identified_records']}; explicit duplicate removals {r['removed_duplicate_by_decision']}; other pre-screen removals {r['removed_other_before_screening']}; screened {r['screened_title_abstract']}; included reports {r['included_reports']}; linked effects {r['linked_effect_rows']}."
              for r in source_counts]
    lines += ["Source-specific study counts may overlap and must not be added across sources.",
             "", "Multiple reports may map to one study. Mapping and exclusions require human source review.",
             "No risk-of-bias judgment or exhaustive search is inferred from these counts."]
    (out / "flow_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out / "flow_subset.svg").write_text(flow_svg(numbers), encoding="utf-8")
    manifest = [{"key": "confirmation_sha256", "value": lit.sha256(a.confirmation)},
                {"key": "confirmation_mode", "value": receipt["mode"]}]
    manifest += [{"key": f"{key}_sha256", "value": value} for key, value in receipt["input_sha256"].items()]
    source = receipt.get("source_provenance") or {"kind": "legacy_manual_unbound", "search_completeness": "NOT_ESTABLISHED"}
    manifest += [{"key": "source_kind", "value": source["kind"]},
                 {"key": "search_completeness", "value": source["search_completeness"]}]
    manifest += [{"key": f"source_{key}_sha256", "value": value}
                 for key, value in source.get("bound_sha256", {}).items()]
    manifest.append({"key": "source_counts_sha256", "value": lit.sha256(out / "source_counts.csv")})
    lit.write_csv(out / "flow_manifest.csv", ["key", "value"], manifest)
    print(f"Reconciled {numbers['identified']} records, {numbers['full_text_included']} reports, {numbers['included_unique']} studies")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command, func in (("confirm", confirm), ("verify", verify), ("count", count)):
        cmd = sub.add_parser(command)
        for name in INPUTS:
            cmd.add_argument(f"--{name.replace('_', '-')}", dest=name, required=True)
        if command == "confirm":
            cmd.add_argument("--mode", choices=tuple(DECLARATIONS), required=True)
            cmd.add_argument("--reviewer", required=True)
            cmd.add_argument("--approval-reference", dest="approval_reference", required=True)
            cmd.add_argument("--declaration", required=True)
        else:
            cmd.add_argument("--confirmation", required=True)
        if command != "verify":
            cmd.add_argument("--out", required=True)
        cmd.set_defaults(func=func)
    args = parser.parse_args()
    try:
        args.func(args)
    except (ValueError, OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        print(f"Validation: {error}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
