"""Merge distinct local bibliography exports without deleting duplicate candidates."""
import argparse
import csv
import difflib
import json
import os
from pathlib import Path
import tempfile

import literature as lit


CORE = ("record_id", "source_label", "source_record_id", "title", "authors", "year", "doi", "pmid")


def candidates(records):
    result = []
    for i, left in enumerate(records):
        for right in records[i + 1:]:
            evidence = []
            if left["doi"] and left["doi"] == right["doi"]:
                evidence.append("exact_doi")
            if left["pmid"] and left["pmid"] == right["pmid"]:
                evidence.append("exact_pmid")
            score = difflib.SequenceMatcher(None, lit.title_key(left["title"]),
                                            lit.title_key(right["title"])).ratio()
            if not evidence and left["year"] == right["year"] and score >= .90:
                evidence.append("suspected_title")
            if evidence:
                conflict = ("exact_doi" in evidence and left["pmid"] and right["pmid"]
                            and left["pmid"] != right["pmid"])
                result.append(dict(record_id_1=left["record_id"], record_id_2=right["record_id"],
                    source_label_1=left["source_label"], source_label_2=right["source_label"],
                    match_evidence="+".join(evidence), title_similarity=f"{score:.3f}",
                    identifier_conflict="YES" if conflict else "NO", disposition="REVIEW_REQUIRED"))
    return result


def merge(folders, output):
    if not 2 <= len(folders) <= 20:
        lit.fail("merge requires 2-20 distinct imported source directories")
    target = Path(output)
    if target.exists():
        lit.fail("output already exists")
    all_records, catalog, labels, ids, fields = [], [], set(), set(), list(CORE)
    for supplied in folders:
        folder = Path(supplied).resolve()
        path = folder / "records.csv"
        records, columns = lit.read_csv(path, CORE)
        source_labels = {r["source_label"] for r in records}
        if len(source_labels) != 1 or not next(iter(source_labels)).strip():
            lit.fail(f"{path}: exactly one nonblank source_label required")
        label = next(iter(source_labels))
        if label in labels:
            lit.fail(f"duplicate source_label {label}; use distinct stable labels")
        labels.add(label)
        tagged = {r.get("source_type", "") for r in records}
        marker = folder / "search_provenance.json"
        source_kind="manual_ris_or_csv"
        if marker.is_file():
            kind=json.loads(marker.read_text(encoding="utf-8")).get("source_type")
            if kind=="pubmed_eutils":
                if tagged!={"pubmed_eutils"}:lit.fail(f"{path}: PubMed source marker/tag mismatch")
                source_kind="pubmed_eutils_local_evidence"
            elif kind=="europe_pmc_rest":
                import europe_pmc_search
                europe_pmc_search.check_provenance(folder)
                source_kind="europe_pmc_rest_local_evidence"
            else:lit.fail(f"{path}: unknown search provenance source type")
        elif "pubmed_eutils" in tagged:
            lit.fail(f"{path}: PubMed-tagged records require search marker")
        for row in records:
            if row["record_id"] in ids:
                lit.fail(f"record_id collision {row['record_id']}; source labels/IDs must be unique")
            ids.add(row["record_id"])
        all_records.extend(records)
        for field in columns:
            if field not in fields:
                fields.append(field)
        catalog.append(dict(source_label=label, records_path=str(path), records_sha256=lit.sha256(path),
                            input_kind=source_kind,
                            identified_records=len(records)))
    if len(all_records) > 2000:
        lit.fail("bounded merge supports at most 2000 records; split and review sources")
    all_records.sort(key=lambda r: r["record_id"])
    review_candidates = candidates(all_records)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".source-merge-", dir=target.parent) as temp:
        stage = Path(temp) / "result"
        stage.mkdir()
        lit.write_csv(stage / "records.csv", fields, all_records)
        lit.write_csv(stage / "duplicate_candidates.csv",
            ["record_id_1", "record_id_2", "source_label_1", "source_label_2",
             "match_evidence", "title_similarity", "identifier_conflict", "disposition"],
            review_candidates)
        lit.write_csv(stage / "screening_template.csv",
            ["record_id", "stage", "decision", "reason", "reviewer", "decision_date"],
            [dict(record_id=r["record_id"], stage="title_abstract", decision="", reason="",
                  reviewer="", decision_date="") for r in all_records])
        (stage / "source_catalog.json").write_text(json.dumps({
            "schema": "meta-merged-sources-v1", "source_count": len(catalog),
            "record_count": len(all_records), "sources": catalog,
            "meaning": "local imported records with unchanged IDs; duplicate candidates require human review; search coverage not authenticated"
        }, indent=2) + "\n", encoding="utf-8")
        lit.write_csv(stage / "merge_manifest.csv", ["key", "value"], [
            dict(key="status", value="READY_FOR_DEDUP_REVIEW"),
            dict(key="records_sha256", value=lit.sha256(stage / "records.csv")),
            dict(key="source_catalog_sha256", value=lit.sha256(stage / "source_catalog.json")),
            dict(key="source_count", value=len(catalog)),
            dict(key="record_count", value=len(all_records)),
            dict(key="duplicate_candidate_count", value=len(review_candidates)),
        ])
        if target.exists():
            lit.fail("output path appeared before commit")
        os.replace(stage, target)
    print(f"Merged {len(all_records)} records from {len(catalog)} sources; "
          f"{len(review_candidates)} duplicate candidates, none removed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", action="append", required=True,
                        help="Repeat for each distinct imported CSV, RIS, or PubMed bibliography directory")
    parser.add_argument("--out", required=True)
    a = parser.parse_args()
    try:
        merge(a.source, a.out)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(2, f"Validation: {exc}\n")


if __name__ == "__main__":
    main()
