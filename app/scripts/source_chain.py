"""Versioned local bibliography batches, without automatic record deletion."""
import argparse
import csv
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace

import literature as lit
import merge_sources

BATCH_FIELDS=("source_label","batch_id","source_name","identification_route","phase","update_of",
              "searched_on","strategy_reference","reviewer")
HISTORY_FIELDS=("record_id","disposition","retained_record_id","reason","reviewer","decision_date",
                "revision_of","revision_reason")
CATALOG_FIELDS=("source_label","batch_id","records_path","records_sha256","identified_records")

def verify_import(folder,temp_parent):
    """Rebuild canonical records from the preserved original import, including the RIS bridge."""
    folder=Path(folder).resolve()
    manifest=csv_rows(folder/"import_manifest.csv",("key","value"))
    values={row["key"]:row["value"] for row in manifest}
    original=folder/"original_import.csv"
    marker=folder/"search_provenance.json"
    provenance=json.loads(marker.read_text(encoding="utf-8")) if marker.is_file() else {}
    if len(values)!=len(manifest) or not original.is_file() or not values.get("source_label") or \
            lit.sha256(original)!=values.get("input_sha256"):
        lit.fail("import manifest or preserved original CSV changed")
    with tempfile.TemporaryDirectory(prefix=".import-recheck-",dir=temp_parent) as temp:
        rebuilt=Path(temp)/"rebuilt"
        lit.import_records(SimpleNamespace(input=str(original),source=values["source_label"],out=str(rebuilt)))
        compared=rebuilt/"records.csv"
        if provenance.get("source_type")=="pubmed_eutils":
            rows,fields=lit.read_csv(compared,("record_id","source_label","pmid"))
            for row in rows:row["source_type"]="pubmed_eutils"
            compared=Path(temp)/"tagged_records.csv"
            lit.write_csv(compared,fields+["source_type"],rows)
        if lit.sha256(compared)!=lit.sha256(folder/"records.csv"):
            lit.fail("imported normalized records disagree with preserved original")
    raw_ris=folder/"original_import.ris"
    if raw_ris.is_file():
        import import_ris
        normalized,trace,tags=import_ris.normalize(import_ris.parse(raw_ris.read_text(encoding="utf-8-sig")))
        bridge=csv_rows(original,("source_record_id","title","authors","year","doi","pmid"))
        if normalized!=bridge:
            lit.fail("RIS original and normalized CSV bridge disagree")
        for name,expected in (("ris_trace.csv",trace),("ris_tags.csv",tags)):
            actual=csv_rows(folder/name,expected[0].keys())
            if [{k:str(v) for k,v in row.items()} for row in expected]!=actual:
                lit.fail("RIS trace/tags disagree with preserved original: "+name)
    elif (folder/"ris_trace.csv").exists() or (folder/"ris_tags.csv").exists():
        lit.fail("RIS trace without preserved original RIS")
    original_rows,original_fields=lit.read_csv(original,("source_record_id","title","year"))
    emark="source_type" in original_fields and any(r["source_type"]=="europe_pmc_rest" for r in original_rows)
    if marker.is_file():
        provenance=json.loads(marker.read_text(encoding="utf-8"))
        if provenance.get("source_type")=="europe_pmc_rest":
            if not emark or {r["source_type"] for r in original_rows}!={"europe_pmc_rest"}:
                lit.fail("Europe PMC source marker/export type mismatch")
            import europe_pmc_search
            europe_pmc_search.check_provenance(folder)
        elif provenance.get("source_type")=="pubmed_eutils":
            if provenance.get("source_label")!=values["source_label"] or provenance.get("search_root")!="..":
                lit.fail("PubMed source provenance label/root mismatch")
            search=folder.parent
            for name,key in (("query_receipt.json","query_receipt_sha256"),
                             ("search_status.json","search_status_sha256"),
                             ("result_ledger.csv","result_ledger_sha256"),
                             ("pubmed_export.csv","pubmed_export_sha256")):
                file=search/name
                if not file.is_file() or lit.sha256(file)!=provenance.get(key):
                    lit.fail("PubMed source provenance changed: "+name)
            if lit.sha256(original)!=provenance["pubmed_export_sha256"] or json.loads(
                    (search/"search_status.json").read_text(encoding="utf-8")).get("status")!="SUCCESS":
                lit.fail("PubMed original export or search status disagrees with source marker")
        else:
            lit.fail("unknown search provenance source type")
    elif emark:
        lit.fail("Europe PMC export requires its search provenance marker")
    return values["source_label"]

def csv_rows(path,fields,empty=False):return lit.read_csv(path,fields,allow_empty=empty)[0]
def save(path,body):path.write_text(json.dumps(body,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
def date(value):
    from datetime import date as D
    try:return D.fromisoformat(value)
    except (ValueError,TypeError):lit.fail("batch/decision date must be YYYY-MM-DD")

def checked_prior(path):
    root=Path(path).resolve();receipt=json.loads((root/"chain_receipt.json").read_text(encoding="utf-8"))
    if receipt.get("schema")!="meta-source-chain-v1":lit.fail("invalid prior source chain")
    for name,digest in receipt["output_sha256"].items():
        file=root/name
        if not file.is_file() or lit.sha256(file)!=digest:lit.fail("prior source-chain output changed: "+name)
    catalog=csv_rows(root/"batch_catalog.csv",CATALOG_FIELDS)
    for row in catalog:
        if not Path(row["records_path"]).is_file() or lit.sha256(row["records_path"])!=row["records_sha256"]:
            lit.fail("prior imported source changed: "+row["source_label"])
        if verify_import(Path(row["records_path"]).parent,root.parent)!=row["source_label"]:
            lit.fail("prior import source label changed")
    return root,catalog,csv_rows(root/"batch_ledger.csv",BATCH_FIELDS),csv_rows(root/"disposition_history.csv",HISTORY_FIELDS,True)

def validate_history(history,records,prior_history,batches,temp_parent):
    if history[:len(prior_history)]!=prior_history:lit.fail("updated disposition history must preserve prior rows exactly")
    ids={r["record_id"] for r in records};state={}
    searched={r["source_label"]:date(r["searched_on"]) for r in batches}
    source_by_id={r["record_id"]:r["source_label"] for r in records}
    for i,row in enumerate(history,2):
        rid=row["record_id"];action=row["disposition"]
        if rid not in ids or action not in {"keep","remove_duplicate","remove_other"} or not row["reviewer"].strip():
            lit.fail(f"disposition history row {i}: unknown record/action/reviewer")
        date(row["decision_date"])
        if date(row["decision_date"])<searched[source_by_id[rid]]:
            lit.fail(f"disposition history row {i}: decision predates source search")
        if rid in state:
            before=state[rid]
            if row["revision_of"]!=before["disposition"] or not row["revision_reason"].strip() or \
                    date(row["decision_date"])<date(before["decision_date"]) or row["disposition"]==before["disposition"]:
                lit.fail(f"disposition history row {i}: changed decision needs an ordered explicit revision")
        elif row["revision_of"] or row["revision_reason"]:
            lit.fail(f"disposition history row {i}: first decision cannot be a revision")
        state[rid]=row
    current=[]
    for record in records:
        row=state.get(record["record_id"])
        current.append({key:(row.get(key,"") if row else "") for key in HISTORY_FIELDS})
        if row is None:current[-1]["record_id"]=record["record_id"];current[-1]["disposition"]="pending"
    if len(state)==len(records):
        # Reuse the established DOI/PMID/title and retained-record checks.
        with tempfile.TemporaryDirectory(prefix=".dedup-check-",dir=temp_parent) as temp:
            file=Path(temp)/"dedup.csv";lit.write_csv(file,HISTORY_FIELDS,current)
            lit.load_dedup(records,file)
    return current

def build(a):
    out=Path(a.out).resolve()
    if out.exists():lit.fail("source-chain output exists; use a new version directory")
    out.parent.mkdir(parents=True,exist_ok=True)
    prior_catalog=[];prior_batches=[];prior_history=[];prior_records=[]
    if a.prior:
        prior_root,prior_catalog,prior_batches,prior_history=checked_prior(a.prior)
        prior_records=csv_rows(prior_root/"records.csv",merge_sources.CORE)
    new_batches=csv_rows(a.batch_ledger,BATCH_FIELDS) if a.batch_ledger else []
    by_new={r["source_label"]:r for r in new_batches}
    if not a.prior and not a.source:lit.fail("initial source chain needs at least one imported source")
    if len(by_new)!=len(new_batches) or len(a.source or [])>20 or bool(a.source)!=bool(a.batch_ledger):
        lit.fail("new batch ledger/source folders must be paired, distinct and bounded to 20")
    used_labels={r["source_label"] for r in prior_catalog};used_batch={r["batch_id"]:r for r in prior_batches}
    sources=[];new_records=[]
    for folder_name in a.source or []:
        folder=Path(folder_name).resolve();path=folder/"records.csv"
        import_label=verify_import(folder,out.parent)
        records=csv_rows(path,merge_sources.CORE)
        labels={r["source_label"] for r in records}
        if len(labels)!=1 or import_label not in labels:lit.fail("one verified import source label per batch required")
        label=next(iter(labels))
        if label in used_labels or label not in by_new:lit.fail("new imported source label missing/previously used")
        used_labels.add(label)
        sources.append({"source_label":label,"batch_id":by_new[label]["batch_id"],"records_path":str(path),
                        "records_sha256":lit.sha256(path),"identified_records":len(records)})
        new_records.extend(records)
    if set(by_new)!={r["source_label"] for r in sources}:lit.fail("batch ledger/source folders differ")
    batches=prior_batches+new_batches
    for row in new_batches:
        bid,label=row["batch_id"],row["source_label"]
        if not bid or bid in used_batch or row["identification_route"] not in {"database_register","other_source"} or \
                row["phase"] not in {"initial","update"} or any(not row[k].strip() for k in ("source_name","strategy_reference","reviewer")):
            lit.fail("batch metadata incomplete/duplicate or unsupported")
        date(row["searched_on"])
        if row["phase"]=="initial":
            if row["update_of"]:lit.fail("initial batch cannot update another batch")
        else:
            parent=used_batch.get(row["update_of"])
            if not parent or parent["source_name"]!=row["source_name"] or date(parent["searched_on"])>=date(row["searched_on"]):
                lit.fail("update batch needs an earlier batch of the same named source")
        used_batch[bid]=row
    catalog=prior_catalog+sources
    records=prior_records+new_records
    if len(records)>2000 or len({r["record_id"] for r in records})!=len(records):
        lit.fail("source chain exceeds 2000 records or has repeated stable record IDs")
    records.sort(key=lambda r:r["record_id"])
    history=csv_rows(a.dispositions,HISTORY_FIELDS,True) if a.dispositions else prior_history
    out.parent.mkdir(parents=True,exist_ok=True)
    current=validate_history(history,records,prior_history,batches,out.parent)
    candidates=merge_sources.candidates(records)
    states={r["record_id"]:r for r in current}
    exact_unresolved=[r for r in candidates if ("exact_doi" in r["match_evidence"] or "exact_pmid" in r["match_evidence"])
        and all(states[x]["disposition"]=="keep" and not states[x]["reason"].strip() for x in (r["record_id_1"],r["record_id_2"]))]
    pending=sum(r["disposition"]=="pending" for r in current)
    status="NEEDS_DEDUP_REVIEW" if pending or exact_unresolved else "READY_FOR_SCREENING"
    old_ids={r["record_id"] for r in prior_records}
    by_new_candidate={r["record_id"]:[] for r in new_records}
    for candidate in candidates:
        for key in ("record_id_1","record_id_2"):
            if candidate[key] in by_new_candidate and (candidate["record_id_2"] if key=="record_id_1" else candidate["record_id_1"]) in old_ids:
                by_new_candidate[candidate[key]].append(candidate)
    incremental=[{"record_id":rid,"prior_match_record_ids":"; ".join(sorted({c["record_id_2"] if c["record_id_1"]==rid else c["record_id_1"] for c in matches})),
                  "match_evidence":"; ".join(sorted({c["match_evidence"] for c in matches})),
                  "status":"REIDENTIFIED_CANDIDATE_NOT_REMOVED" if matches else "NEW_RECORD_ID_NO_PRIOR_CANDIDATE"}
                 for rid,matches in sorted(by_new_candidate.items())]
    out.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".source-chain-",dir=out.parent) as temp:
        stage=Path(temp)/"result";stage.mkdir()
        lit.write_csv(stage/"records.csv",list(records[0]),records)
        lit.write_csv(stage/"batch_catalog.csv",CATALOG_FIELDS,catalog)
        lit.write_csv(stage/"batch_ledger.csv",BATCH_FIELDS,batches)
        lit.write_csv(stage/"disposition_history.csv",HISTORY_FIELDS,history)
        lit.write_csv(stage/"disposition_current.csv",HISTORY_FIELDS,current)
        lit.write_csv(stage/"duplicate_candidates.csv",["record_id_1","record_id_2","source_label_1","source_label_2","match_evidence","title_similarity","identifier_conflict","disposition"],candidates)
        lit.write_csv(stage/"exact_pairs_needing_review.csv",["record_id_1","record_id_2","match_evidence"],exact_unresolved)
        lit.write_csv(stage/"incremental_comparison.csv",["record_id","prior_match_record_ids","match_evidence","status"],incremental)
        lit.write_csv(stage/"source_methods.csv",["source_label","identification_route","source_name","searched_on","strategy_reference","reviewer"],
            [{k:r[k] for k in ("source_label","identification_route","source_name","searched_on","strategy_reference","reviewer")} for r in batches])
        lit.write_csv(stage/"search_batches.csv",["batch_id","source_label","source_name","phase","update_of","search_date","query_reference","reviewer","status"],
            [{"batch_id":r["batch_id"],"source_label":r["source_label"],"source_name":r["source_name"],"phase":r["phase"],
              "update_of":r["update_of"],"search_date":r["searched_on"],"query_reference":r["strategy_reference"],
              "reviewer":r["reviewer"],"status":"documented_user_claim"} for r in batches])
        if status=="READY_FOR_SCREENING":lit.write_csv(stage/"dedup.csv",HISTORY_FIELDS,current)
        receipt={"schema":"meta-source-chain-v1","status":status,"source_count":len(catalog),"record_count":len(records),
                 "new_record_count":len(new_records),"pending_dispositions":pending,"exact_pairs_needing_review":len(exact_unresolved),
                 "prior_receipt_sha256":lit.sha256(Path(a.prior)/"chain_receipt.json") if a.prior else "",
                 "input_sha256":{**({"batch_ledger":lit.sha256(a.batch_ledger)} if a.batch_ledger else {}),
                                 **({"dispositions":lit.sha256(a.dispositions)} if a.dispositions else {})},
                 "output_sha256":{p.name:lit.sha256(p) for p in stage.iterdir() if p.is_file()},
                 "scope":"local imports, including checked online-response snapshots when tagged; duplicate candidates and source claims require review; search coverage not authenticated"}
        save(stage/"chain_receipt.json",receipt)
        os.replace(stage,out)
    print(status,len(records),"records",len(new_records),"new",len(candidates),"candidates",out)

if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source",action="append");p.add_argument("--batch-ledger")
    p.add_argument("--dispositions");p.add_argument("--prior");p.add_argument("--out",required=True)
    a=p.parse_args()
    try:build(a)
    except (OSError,ValueError,KeyError,TypeError,csv.Error) as exc:p.exit(2,f"Validation: {exc}\n")
