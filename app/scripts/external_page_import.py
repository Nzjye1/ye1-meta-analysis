"""Import caller-supplied page text/numeric candidates into the existing full-text review contract.

Host image reading, external OCR and user-supplied text are input claims, never a
second reviewer or a verified reading of the original PDF.
"""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

import fulltext_extract as fulltext
import literature as lit
import ocr_pages

INPUT_FIELDS=("result_id","record_id","source_document","source_sha256","page","method",
              "producer_label","external_result_reference","source_locator","raw_text",
              "raw_number","confidence","review_status")
CANDIDATE_FIELDS=("candidate_id","record_id","source_document","source_sha256","page","line",
                  "token","raw_token","parsed_number","unit_suffix","suggested_location","context",
                  "extractor","external_result_id","external_result_reference","external_input_sha256",
                  "confidence","confidence_status","review_status")
METHODS={"host_image_reading","external_ocr","user_supplied_text"}


def fail(message):raise ValueError(message)


def run(inspection,external,out):
    root,ins_receipt,page_rows=ocr_pages.checked_inspection(inspection)
    external=Path(external).resolve();target=Path(out).resolve()
    source_sha=lit.sha256(external)
    incoming,_=lit.read_csv(external,INPUT_FIELDS)
    pages={(r["record_id"],r["source_document"],r["page"]):r for r in page_rows}
    if len(pages)!=len(page_rows):fail("inspection has repeated record/document/page")
    catalog,_=lit.read_csv(ins_receipt["documents_path"],fulltext.DOC_FIELDS)
    by_doc={(r["record_id"],r["source_document"]):r for r in catalog}
    used=set();docs={};candidates=[];audit=[]
    for n,row in enumerate(incoming,2):
        if any(row.get(k) is None for k in INPUT_FIELDS):fail(f"external row {n}: truncated CSV")
        key=(row["record_id"],row["source_document"],row["page"])
        page=pages.get(key);rid=row["result_id"].strip()
        if not rid or rid in used or page is None:fail(f"external row {n}: repeated result ID or unknown PDF page")
        used.add(rid)
        if row["source_sha256"].lower()!=page["source_sha256"] or row["method"] not in METHODS:
            fail(f"external row {n}: original PDF hash or extraction method differs")
        if row["method"]=="host_image_reading" and page["image_reader_declared"]!="declared_available":
            fail(f"external row {n}: host image reading was not declared available")
        if row["method"]=="external_ocr" and page["external_ocr_declared"]!="declared_available":
            fail(f"external row {n}: external OCR was not declared available")
        if row["review_status"]!="unreviewed_candidate":
            fail(f"external row {n}: external result must remain an unreviewed candidate")
        for field in ("producer_label","external_result_reference","source_locator","raw_text"):
            if not row[field].strip():fail(f"external row {n}: {field} required")
        if not re.search(r"(?i)\bpage\s*"+re.escape(row["page"])+r"\b",row["source_locator"]):
            fail(f"external row {n}: locator must name the actual PDF page")
        if len(row["raw_text"])>1000:fail(f"external row {n}: text candidate exceeds 1000 characters")
        if row["confidence"].strip():
            try:confidence=float(row["confidence"])
            except ValueError:fail(f"external row {n}: confidence must be 0-100 or blank")
            if not 0<=confidence<=100:fail(f"external row {n}: confidence must be 0-100 or blank")
            confidence_status="LOW" if confidence<70 else "REPORTED_NOT_CALIBRATED"
        else:confidence_status="UNKNOWN"
        matches=list(fulltext.NUMBER.finditer(row["raw_text"]))
        if row["raw_number"].strip():
            matches=[m for m in matches if m.group(0)==row["raw_number"].strip()]
            if len(matches)!=1:fail(f"external row {n}: raw_number must occur exactly once in raw_text")
        doc=by_doc.get(key[:2])
        if doc is None or doc["format"].strip().lower()!="pdf":fail(f"external row {n}: PDF document not registered")
        docs[key[:2]]=dict(record_id=key[0],source_document=key[1],file_path=page["file_path"],
            format="pdf",rights_basis=doc["rights_basis"],source_sha256=page["source_sha256"],
            page_count=sum(r["record_id"]==key[0] and r["source_document"]==key[1] for r in page_rows),
            bytes=Path(page["file_path"]).stat().st_size,extraction_engine="caller-supplied external page candidate; unverified")
        audit.append({**row,"source_sha256":page["source_sha256"],"method":row["method"],
                      "review_status":"unreviewed_candidate","external_input_sha256":source_sha})
        for token,m in enumerate(matches,1):
            marker=f"{source_sha}\x1f{rid}\x1f{m.start()}"
            candidates.append(dict(candidate_id="NUM-"+hashlib.sha256(marker.encode()).hexdigest()[:20],
                record_id=key[0],source_document=key[1],source_sha256=page["source_sha256"],
                page=key[2],line=n,token=token,raw_token=m.group(0),
                parsed_number=str(fulltext.number(m.group("num"),"external candidate")),
                unit_suffix=m.group("pct"),suggested_location=row["source_locator"],
                context=row["raw_text"],extractor="external_"+row["method"]+"_candidate_only",
                external_result_id=rid,external_result_reference=row["external_result_reference"],
                external_input_sha256=source_sha,confidence=row["confidence"],
                confidence_status=confidence_status,review_status="UNREVIEWED_EXTERNAL_CANDIDATE"))
        if len(candidates)>10_000:fail("external numeric candidates exceed 10,000")
    if not incoming:fail("external page result file is empty")
    if target.exists():fail("output exists; choose a fresh external-page import directory")
    target.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".external-page-import-",dir=target.parent) as tmp:
        stage=Path(tmp)/"result";stage.mkdir()
        doc_rows=list(docs.values())
        doc_fields=["record_id","source_document","file_path","format","rights_basis","source_sha256",
                    "page_count","bytes","extraction_engine"]
        lit.write_csv(stage/"documents.csv",doc_fields,doc_rows)
        lit.write_csv(stage/"numeric_candidates.csv",CANDIDATE_FIELDS,candidates)
        lit.write_csv(stage/"table_cell_candidates.csv",fulltext.TABLE_CELL_FIELDS,[])
        lit.write_csv(stage/"external_page_results.csv",INPUT_FIELDS+("external_input_sha256",),audit)
        receipt=dict(schema="meta-fulltext-scan-v1",pdf_reader="external_page_candidate_import",
            records_path=ins_receipt["records_path"],records_sha256=ins_receipt["records_sha256"],
            input_documents_path=ins_receipt["documents_path"],input_documents_sha256=ins_receipt["documents_sha256"],
            documents_sha256=lit.sha256(stage/"documents.csv"),candidates_sha256=lit.sha256(stage/"numeric_candidates.csv"),
            table_cells_sha256=lit.sha256(stage/"table_cell_candidates.csv"),
            external_results_path=str(external),external_results_sha256=source_sha,
            inspection_path=str(root),inspection_receipt_sha256=lit.sha256(root/"ocr_inspection.json"),
            external_page_results_sha256=lit.sha256(stage/"external_page_results.csv"),
            status="CANDIDATES_ONLY_NOT_VERIFIED",source_result_identity_authenticated=False,
            document_count=len(doc_rows),candidate_count=len(candidates),table_cell_count=0,
            table_indices_are_published_numbers=False)
        (stage/"scan_receipt.json").write_text(json.dumps(receipt,indent=2)+"\n",encoding="utf-8")
        os.replace(stage,target)
    print("EXTERNAL_PAGE_CANDIDATES_NOT_VERIFIED",len(candidates),"numeric candidates",target)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inspection",required=True);parser.add_argument("--external-results",required=True)
    parser.add_argument("--out",required=True)
    a=parser.parse_args()
    try:run(a.inspection,a.external_results,a.out)
    except (OSError,ValueError,KeyError,TypeError,json.JSONDecodeError,csv.Error) as exc:
        parser.exit(2,"Validation: "+str(exc)+"\n")
