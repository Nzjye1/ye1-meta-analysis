"""Bind an existing checked OA candidate to Europe PMC imported stable record IDs."""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import tempfile

import europe_pmc_search
import literature as lit
import local_retrieval
import oa_fulltext


def build(a):
    search=Path(a.search).resolve();oa=Path(a.oa).resolve();out=Path(a.out).resolve()
    if out.exists():lit.fail("output already exists")
    europe_pmc_search.check_provenance(search/"bibliography")
    receipt=json.loads((oa/"oa_receipt.json").read_text(encoding="utf-8"))
    if not Path(receipt["records_path"]).is_file() or not Path(receipt["metadata_path"]).is_file() or \
            lit.sha256(receipt["records_path"])!=receipt["records_sha256"] or \
            lit.sha256(receipt["metadata_path"])!=receipt["metadata_sha256"]:
        lit.fail("OA source inputs changed")
    _,attempts=oa_fulltext.checked_prior(oa,receipt["records_sha256"],receipt["metadata_sha256"])
    records,_=lit.read_csv(search/"bibliography/records.csv",("record_id","doi","pmid"))
    source_rows,_=lit.read_csv(oa/"local_retrieval_attempts_template.csv",local_retrieval.FIELDS)
    template_by_id={r["record_id"]:r for r in source_rows}
    if len(template_by_id)!=len(source_rows):lit.fail("OA template has repeated record ID")
    mapped=[];crosswalk=[];used=set()
    for original in attempts.values():
        if original["status"]!="OA_CANDIDATE_DOWNLOADED":continue
        match=[r for r in records if (original["doi"] and lit.doi(r["doi"])==lit.doi(original["doi"])) or
               (original["pmid"] and r["pmid"]==original["pmid"])]
        if len(match)!=1:lit.fail("downloaded OA candidate needs exactly one imported record match")
        target=match[0]
        if (original["doi"] and target["doi"] and lit.doi(original["doi"])!=lit.doi(target["doi"])) or \
                (original["pmid"] and target["pmid"] and original["pmid"]!=target["pmid"]):
            lit.fail("OA DOI/PMID disagrees with imported record")
        rid=target["record_id"]
        if rid in used or original["record_id"] not in template_by_id:lit.fail("ambiguous OA candidate mapping")
        used.add(rid)
        old=template_by_id[original["record_id"]]
        if old["status"]!="alternative_candidate" or not old["file_path"] or \
                lit.sha256(old["file_path"])!=original["text_sha256"] or \
                lit.sha256(oa/original["xml_path"])!=original["xml_sha256"]:
            lit.fail("OA candidate file or rights template changed")
        row=dict(old);row["record_id"]=rid
        row["attempt_id"]="OA-"+hashlib.sha256(rid.encode("utf-8")).hexdigest()[:20]
        mapped.append(row)
        crosswalk.append(dict(record_id=rid,oa_record_id=original["record_id"],pmcid=original["pmcid"],
            doi=original["doi"],pmid=original["pmid"],license_uri=original["license_uri"],
            xml_sha256=original["xml_sha256"],text_sha256=original["text_sha256"],
            status="OBTAINED_CANDIDATE_NOT_SCREENED_OR_ACCEPTED"))
    if not mapped:lit.fail("no downloaded OA candidate matches imported records")
    out.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".oa-bridge-",dir=out.parent) as temp:
        stage=Path(temp)/"result";stage.mkdir()
        lit.write_csv(stage/"oa_record_crosswalk.csv",list(crosswalk[0]),crosswalk)
        lit.write_csv(stage/"local_retrieval_attempts_template.csv",local_retrieval.ALL_FIELDS,mapped)
        body=dict(schema="meta-oa-bridge-v1",status="OBTAINED_CANDIDATE_AWAITING_SCREENING_AND_REVIEW",
            search_root=str(search),search_marker_sha256=lit.sha256(search/"bibliography/search_provenance.json"),
            oa_root=str(oa),oa_receipt_sha256=lit.sha256(oa/"oa_receipt.json"),
            mapped_candidates=len(mapped),full_text_assessed=False,study_included=False,
            outputs={p.name:lit.sha256(p) for p in stage.iterdir() if p.is_file()})
        (stage/"bridge_receipt.json").write_text(json.dumps(body,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        os.replace(stage,out)
    print(body["status"],len(mapped),out)


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--search",required=True,help="Europe PMC search output root")
    p.add_argument("--oa",required=True,help="Existing OA output root; no download occurs")
    p.add_argument("--out",required=True)
    a=p.parse_args()
    try:build(a)
    except (OSError,ValueError,KeyError,TypeError,csv.Error) as exc:p.exit(2,"Validation: "+str(exc)+"\n")
