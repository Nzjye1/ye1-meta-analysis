"""Local full-text access attempts and checked document-to-record links; no downloader."""
import argparse
import csv
import json
import os
from pathlib import Path
import re
import tempfile

import fulltext_extract as ft
import literature as lit
import source_chain

FIELDS=("record_id","attempt_id","status","source_document","file_path","format","rights_basis",
        "document_doi","document_pmid","version_relation","identity_basis","identity_evidence",
        "reason","reviewer","decision_date","revision_of","revision_reason")
REVIEW_FIELDS=("review_mode","identity_conclusion","version_conclusion","version_evidence")
ALL_FIELDS=FIELDS+REVIEW_FIELDS
STATES={"pending","awaiting_permission","not_retrieved","retrieved_primary","alternative_candidate","retrieved_alternative"}
FILE_STATES={"retrieved_primary","alternative_candidate","retrieved_alternative"}

def rows(path,fields,empty=False):
    values,_=lit.read_csv(path,fields,allow_empty=empty)
    if fields==FIELDS:
        for row in values:
            for key in REVIEW_FIELDS:row.setdefault(key,"")
    return values
def date(value):return source_chain.date(value)

def validate_oa_revision(row,previous,mode):
    if mode not in {"formal_review","exploratory_agent"}:
        lit.fail("OA alternative promotion needs explicit formal_review or exploratory_agent mode")
    if row["identity_conclusion"]!="same_report" or row["version_conclusion"] not in {
            "version_of_record","same_report_alternative"}:
        lit.fail("OA alternative promotion needs affirmative identity and version conclusions")
    if row["version_relation"]==previous["version_relation"] or "REVIEW_REQUIRED" in row["version_relation"] or \
            not row["version_relation"].strip() or not row["version_evidence"].strip():
        lit.fail("OA alternative promotion needs a new version relation and cited evidence")
    if row["identity_evidence"]==previous["identity_evidence"] or not row["identity_evidence"].strip() or \
            "pending" in row["identity_evidence"].casefold():
        lit.fail("OA alternative promotion needs new identity evidence, not the pending candidate text")
    if mode=="formal_review" and row["reviewer"].startswith("AGENT_"):
        lit.fail("Agent candidate cannot claim formal human review")

def checked_prior(path):
    root=Path(path).resolve();receipt=json.loads((root/"retrieval_receipt.json").read_text(encoding="utf-8"))
    if receipt.get("schema")!="meta-local-retrieval-v1":lit.fail("invalid prior retrieval ledger")
    for name,digest in receipt["output_sha256"].items():
        if not (root/name).is_file() or lit.sha256(root/name)!=digest:lit.fail("prior retrieval output changed: "+name)
    for name,path in receipt.get("input_paths",{}).items():
        if not Path(path).is_file() or lit.sha256(path)!=receipt["input_sha256"][name]:
            lit.fail("prior retrieval input changed: "+name)
    for path,digest in receipt["document_sha256"].items():
        if not Path(path).is_file() or lit.sha256(path)!=digest:lit.fail("prior local full text changed")
    return rows(root/"attempt_history.csv",FIELDS,True)

def checked_file(record,row):
    file=Path(row["file_path"]).expanduser().resolve();fmt=row["format"].strip().lower()
    extensions={"pdf":{'.pdf'},"html":{'.html','.htm'},"text":{'.txt'}}
    if fmt not in extensions or not file.is_file() or file.suffix.lower() not in extensions[fmt] or \
            not 0<file.stat().st_size<=25_000_000 or not row["source_document"].strip() or not row["rights_basis"].strip():
        lit.fail("retrieved file needs existing bounded PDF/HTML/text, document name and access/rights basis")
    doi=lit.doi(row["document_doi"]);pmid=row["document_pmid"].strip()
    if doi and not re.fullmatch(r"10\.\d{4,9}/\S+",doi):lit.fail("document DOI syntax invalid")
    if pmid and not re.fullmatch(r"\d+",pmid):lit.fail("document PMID syntax invalid")
    alternate=row["status"]!="retrieved_primary"
    if not alternate and ((doi and doi!=lit.doi(record["doi"])) or (pmid and pmid!=record["pmid"])):
        lit.fail("primary document DOI/PMID disagrees with bibliography record")
    if alternate and not row["version_relation"].strip():lit.fail("alternative version needs explicit relation to the indexed report")
    if not alternate and row["version_relation"]:lit.fail("primary report cannot claim alternative version relation")
    basis=row["identity_basis"]
    if basis not in {"doi_in_text","pmid_in_text","title_in_text","human_claim"}:
        lit.fail("document identity basis must be checkable text or an explicit human claim")
    if basis=="human_claim":
        if not row["identity_evidence"].strip():lit.fail("human identity claim needs a rationale and location")
        identity="HUMAN_CLAIM_NOT_INDEPENDENTLY_VERIFIED"
    else:
        text="\n".join(part for _,part in ft.pages(file,fmt)[:5]).casefold()
        if basis=="doi_in_text":
            if not doi or not record["doi"] or doi!=lit.doi(record["doi"]) or not re.search(
                    r"(?<![\w/])"+re.escape(doi)+r"(?![\w/.-])",text):
                lit.fail("document DOI not found in text or differs from indexed DOI")
        elif basis=="pmid_in_text":
            if not pmid or not record["pmid"] or pmid!=record["pmid"] or not re.search(r"(?<!\d)"+re.escape(pmid)+r"(?!\d)",text):
                lit.fail("document PMID not found in text or differs from indexed PMID")
        elif not lit.title_key(record["title"]) or lit.title_key(record["title"]) not in lit.title_key(text):
            lit.fail("indexed title not found in local document text")
        identity="TEXT_IDENTIFIER_OR_TITLE_MATCH_ONLY"
    if row["status"]=="retrieved_alternative" and not row["identity_evidence"].strip():
        lit.fail("accepted alternative needs reviewer explanation of equivalence")
    return file,lit.sha256(file),identity

def build(a):
    chain=Path(a.chain).resolve();source_chain.checked_prior(chain)
    if not (chain/"dedup.csv").is_file():lit.fail("source chain has pending duplicate review")
    records=rows(chain/"records.csv",("record_id","title","doi","pmid"));by_id={r["record_id"]:r for r in records}
    dedup=lit.load_dedup(records,chain/"dedup.csv")
    decisions=rows(a.decisions,("record_id","stage","decision","reason","reviewer","decision_date"))
    stages,_=lit.validate_screening(records,decisions,{rid for rid,row in dedup.items() if row["disposition"]=="keep"})
    sought={rid for rid,row in dedup.items() if row["disposition"]=="keep" and stages[(rid,"title_abstract")]["decision"]=="include"}
    prior_history=checked_prior(a.prior) if a.prior else []
    history=rows(a.attempts,FIELDS,True)
    if history[:len(prior_history)]!=prior_history:lit.fail("retrieval update must preserve the earlier attempt history")
    state={};ids=set();oa_candidates=set()
    for i,row in enumerate(history,2):
        rid=row["record_id"];attempt=row["attempt_id"];status=row["status"]
        if rid not in sought or not attempt or attempt in ids or status not in STATES or not row["reviewer"].strip():
            lit.fail(f"attempt row {i}: unknown record, ID, status or reviewer")
        ids.add(attempt);date(row["decision_date"])
        if status=="retrieved_alternative" and (rid not in state or
                state[rid]["status"] not in {"alternative_candidate","retrieved_alternative"}):
            lit.fail(f"attempt row {i}: alternative must first be logged as a candidate and then reviewed")
        if status=="alternative_candidate" and row["reviewer"]=="AGENT_CANDIDATE_NOT_HUMAN" and \
                row["attempt_id"].startswith("OA-"):
            oa_candidates.add(rid)
        if rid in oa_candidates and status=="retrieved_primary":
            lit.fail(f"attempt row {i}: OA alternative candidate cannot silently become a primary report")
        if rid in oa_candidates and status=="retrieved_alternative":
            validate_oa_revision(row,state[rid],row["review_mode"])
        if rid in state:
            previous=state[rid]
            if row["revision_of"]!=previous["attempt_id"] or not row["revision_reason"].strip() or \
                    date(row["decision_date"])<date(previous["decision_date"]):
                lit.fail(f"attempt row {i}: updated access state needs an ordered revision")
        elif row["revision_of"] or row["revision_reason"]:lit.fail("first retrieval attempt cannot claim a revision")
        if status in FILE_STATES:
            if row["reason"]:lit.fail("file-bearing attempt reason is reserved for unavailable reports")
        elif row["file_path"] or row["source_document"] or row["format"] or row["document_doi"] or row["document_pmid"]:
            lit.fail("unavailable/pending report cannot claim a local full-text file")
        if status in {"not_retrieved","awaiting_permission"} and not row["reason"].strip():
            lit.fail("unavailable/permission state requires reason")
        state[rid]=row
    missing=sought-set(state)
    current=[];documents=[];exploratory=[];doc_hashes={}
    for rid in sorted(sought):
        row=state.get(rid)
        if row is None:continue
        status=row["status"]
        exploratory_oa=rid in oa_candidates and status=="retrieved_alternative" and row["review_mode"]=="exploratory_agent"
        retrieved=status in {"retrieved_primary","retrieved_alternative"} and not exploratory_oa
        if not retrieved and stages[(rid,"full_text")]["decision"]!="pending":
            lit.fail("pending/unavailable full text cannot be assessed or included: "+rid)
        if status in FILE_STATES:
            file,digest,identity=checked_file(by_id[rid],row);doc_hashes[str(file)]=digest
            doc={"record_id":rid,"source_document":row["source_document"],"file_path":str(file),
                 "format":row["format"].lower(),"rights_basis":row["rights_basis"]}
            if retrieved:documents.append(doc)
            elif exploratory_oa:exploratory.append(doc)
        else:identity="NO_LOCAL_FILE"
        current.append({**row,"file_path":str(file) if status in FILE_STATES else "","file_sha256":digest if status in FILE_STATES else "",
                        "identity_check":identity})
    out=Path(a.out).resolve()
    if out.exists():lit.fail("retrieval output exists; use new version directory")
    out.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".local-retrieval-",dir=out.parent) as temp:
        stage=Path(temp)/"result";stage.mkdir()
        lit.write_csv(stage/"attempt_history.csv",ALL_FIELDS,history)
        lit.write_csv(stage/"attempt_current.csv",[*ALL_FIELDS,"file_sha256","identity_check"],current)
        lit.write_csv(stage/"missing_attempts.csv",["record_id"],[{"record_id":rid} for rid in sorted(missing)])
        # An alternative candidate is a file actually obtained. Count retrieval now,
        # while full-text assessment and document export remain pending review.
        lit.write_csv(stage/"retrieval.csv",["record_id","status","reason","retrieval_reference","reviewer","decision_date"],
            [{"record_id":r["record_id"],"status":"retrieved" if r["status"] in FILE_STATES else
               "not_retrieved" if r["status"]=="not_retrieved" else "pending",
              "reason":r["reason"] if r["status"]=="not_retrieved" else "",
              "retrieval_reference":r["attempt_id"]+("; sha256="+r["file_sha256"] if r["file_sha256"] else ""),
              "reviewer":r["reviewer"],"decision_date":r["decision_date"]} for r in current])
        lit.write_csv(stage/"documents.csv",ft.DOC_FIELDS,documents)
        lit.write_csv(stage/"exploratory_documents.csv",ft.DOC_FIELDS,exploratory)
        receipt={"schema":"meta-local-retrieval-v1","status":"NEEDS_ATTEMPTS" if missing else "READY_FOR_PRISMA_LEDGER",
                 "sought_reports":len(sought),
                 "retrieved_reports":sum(r["status"] in FILE_STATES for r in current),
                 "reviewed_retrieved_reports":len(documents),"exploratory_documents":len(exploratory),
                 "missing_attempts":len(missing),
                 "permission_pending":sum(r["status"]=="awaiting_permission" for r in current),
                 "alternative_pending":sum(r["status"]=="alternative_candidate" for r in current),
                 "input_sha256":{"chain_receipt":lit.sha256(chain/"chain_receipt.json"),"decisions":lit.sha256(a.decisions),"attempts":lit.sha256(a.attempts)},
                 "input_paths":{"chain_receipt":str(chain/"chain_receipt.json"),
                                "decisions":str(Path(a.decisions).resolve()),"attempts":str(Path(a.attempts).resolve())},
                 "prior_receipt_sha256":lit.sha256(Path(a.prior)/"retrieval_receipt.json") if a.prior else "",
                 "document_sha256":doc_hashes,
                 "output_sha256":{p.name:lit.sha256(p) for p in stage.iterdir() if p.is_file()},
                 "scope":"user-provided local files; text match is not semantic article verification; no network retrieval"}
        (stage/"retrieval_receipt.json").write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        os.replace(stage,out)
    print(receipt["status"],len(sought),"sought",receipt["retrieved_reports"],
          "files obtained",len(documents),"reviewed documents",out)

if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    for name in ("chain","decisions","attempts","out"):p.add_argument("--"+name,required=True)
    p.add_argument("--prior");a=p.parse_args()
    try:build(a)
    except (OSError,ValueError,KeyError,TypeError,csv.Error) as exc:p.exit(2,f"Validation: {exc}\n")
