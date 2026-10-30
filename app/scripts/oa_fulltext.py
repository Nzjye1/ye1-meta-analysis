"""Bounded Europe PMC OA JATS candidate acquisition; no live call without explicit online mode."""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener
import xml.etree.ElementTree as ET

import literature as lit
import local_retrieval

OFFICIAL="https://www.ebi.ac.uk/europepmc/webservices/rest/"
LIMIT=16_000_000
MAX_RECORDS=20
ALLOWED_LICENSES={
    "https://creativecommons.org/licenses/by/4.0/":"CC BY 4.0",
    "https://creativecommons.org/licenses/by/3.0/":"CC BY 3.0",
    "https://creativecommons.org/publicdomain/zero/1.0/":"CC0 1.0",
}
FIELDS=("record_id","pmid","doi","pmcid","metadata_oa","status","reason","content_url",
        "license_uri","license_label","version_status","mime","bytes","xml_path","xml_sha256",
        "text_path","text_sha256","attempted_at","reused_prior")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        raise ValueError("redirect refused; only the fixed Europe PMC API path is allowed")


def now():return datetime.now(timezone.utc).isoformat(timespec="seconds")
def sha(data):return hashlib.sha256(data).hexdigest()
def tag(elem):return elem.tag.rsplit("}",1)[-1]


def metadata(path):
    source=json.loads(Path(path).read_text(encoding="utf-8"))
    entries=source.get("resultList",{}).get("result")
    if not isinstance(entries,list) or len(entries)>500:
        lit.fail("metadata needs bounded Europe PMC resultList.result array")
    return entries


def match(record,entries):
    pmid=record["pmid"].strip();doi=lit.doi(record["doi"])
    if not pmid and not doi:return None,"NO_IDENTIFIER"
    found=[]
    for entry in entries:
        if not isinstance(entry,dict):continue
        mid=str(entry.get("pmid") or "").strip()
        mdoi=lit.doi(str(entry.get("doi") or ""))
        if (pmid and mid==pmid) or (doi and mdoi==doi):
            if pmid and mid and mid!=pmid:continue
            if doi and mdoi and mdoi!=doi:continue
            found.append(entry)
    if len(found)>1:return None,"AMBIGUOUS_METADATA_MATCH"
    return (found[0],"") if found else (None,"NO_METADATA_MATCH")


def base_url(a):
    if a.local_base_url:
        parsed=urlparse(a.local_base_url)
        if a.online or parsed.scheme!="http" or parsed.hostname not in {"127.0.0.1","localhost"} or \
                parsed.username or parsed.password or parsed.query or parsed.fragment or not parsed.port:
            lit.fail("local fixture URL must be explicit loopback HTTP with port and no credentials")
        return a.local_base_url.rstrip("/")+"/","LOCAL_HTTP_FIXTURE"
    if not a.online:lit.fail("external retrieval disabled by default; use a loopback fixture or explicit --online")
    return OFFICIAL,"ONLINE_REQUEST_PENDING_REAL_VALIDATION"


def fetch(url):
    opener=build_opener(NoRedirect)
    with opener.open(Request(url,headers={"Accept":"application/xml,text/xml","User-Agent":"MetaSkill-OA-Candidate/0.1"}),timeout=15) as response:
        if response.status!=200:lit.fail("HTTP status "+str(response.status))
        mime=response.headers.get_content_type().lower()
        if mime not in {"application/xml","text/xml","application/jats+xml"}:
            lit.fail("response MIME is not XML: "+mime)
        declared=response.headers.get("Content-Length")
        if declared and (not declared.isdigit() or int(declared)>LIMIT):lit.fail("content length exceeds 16 MB cap")
        chunks=[];total=0
        while True:
            part=response.read(min(65536,LIMIT+1-total))
            if not part:break
            total+=len(part)
            if total>LIMIT:lit.fail("download exceeds 16 MB cap")
            chunks.append(part)
        if total==0:lit.fail("empty full-text response")
        if declared and total!=int(declared):lit.fail("response size differs from Content-Length")
        return b"".join(chunks),mime


def inspect_jats(data,record,pmcid):
    try:article=ET.fromstring(data)
    except ET.ParseError as exc:lit.fail("invalid JATS XML: "+str(exc))
    if tag(article)!="article":lit.fail("fullTextXML response is not a JATS article")
    fronts=[child for child in article if tag(child)=="front"]
    metas=[child for front in fronts for child in front if tag(child)=="article-meta"]
    if len(metas)!=1:lit.fail("JATS needs one front/article-meta for article identity and rights")
    ids={}
    for element in metas[0]:
        if tag(element)!="article-id":continue
        kind=element.attrib.get("pub-id-type","").lower();value=(element.text or "").strip()
        if kind in ids and ids[kind]!=value:lit.fail("conflicting JATS article-meta identifier")
        ids[kind]=value
    pmc_values=[value.upper() for kind,value in ids.items() if kind in {"pmc","pmcid"} and value]
    pmc_values=["PMC"+value.removeprefix("PMC") for value in pmc_values]
    if len(set(pmc_values))>1:lit.fail("conflicting JATS PMCID identifiers")
    actual_pmc=pmc_values[0] if pmc_values else ""
    if actual_pmc!=pmcid:lit.fail("JATS PMCID differs from metadata")
    if record["pmid"] and ids.get("pmid") and ids["pmid"]!=record["pmid"]:lit.fail("JATS PMID differs from bibliography")
    if record["doi"] and ids.get("doi") and lit.doi(ids["doi"])!=lit.doi(record["doi"]):
        lit.fail("JATS DOI differs from bibliography")
    if not ((record["pmid"] and ids.get("pmid")==record["pmid"]) or
            (record["doi"] and ids.get("doi") and lit.doi(ids["doi"])==lit.doi(record["doi"]))):
        lit.fail("JATS lacks a matching bibliography DOI or PMID")
    hrefs=[]
    permissions=[child for meta in metas for child in meta if tag(child)=="permissions"]
    for element in permissions:
        for license_node in element:
            if tag(license_node)!="license":continue
            candidates=[license_node.attrib.get("{http://www.w3.org/1999/xlink}href","").strip()]
            candidates += [node.attrib.get("{http://www.w3.org/1999/xlink}href","").strip()
                           for node in license_node.iter() if tag(node)=="ext-link"]
            for href in candidates:
                if href:hrefs.append(href.replace("http://creativecommons.org/","https://creativecommons.org/").rstrip("/")+"/")
    if len(set(hrefs))!=1 or hrefs[0] not in ALLOWED_LICENSES:
        lit.fail("article-level license absent, conflicting, or outside explicit CC BY/CC0 allowlist")
    versions=[" ".join((element.text or "").split()).lower() for element in article.iter() if tag(element)=="article-version"]
    version="VERSION_OF_RECORD_CLAIM" if versions and all(v in {"version of record","vor","published version"} for v in versions) else \
            "VERSION_UNSPECIFIED_REVIEW_REQUIRED" if not versions else "ALTERNATIVE_VERSION_REVIEW_REQUIRED"
    text="Europe PMC JATS candidate; original XML retained.\nPMCID "+pmcid+"\n"
    text+="PMID "+ids.get("pmid","")+"\nDOI "+ids.get("doi","")+"\n"
    for element in article.iter():
        if tag(element) in {"article-title","title","p"}:
            content=" ".join("".join(element.itertext()).split())
            if content:text+=content+"\n"
    return hrefs[0],ALLOWED_LICENSES[hrefs[0]],version,text.encode("utf-8")


def checked_prior(path,records_hash,metadata_hash):
    root=Path(path).resolve();receipt=json.loads((root/"oa_receipt.json").read_text(encoding="utf-8"))
    if receipt.get("schema")!="meta-oa-fulltext-v1" or receipt.get("records_sha256")!=records_hash or \
            receipt.get("metadata_sha256")!=metadata_hash:lit.fail("prior OA receipt/input differs")
    for name,digest in receipt["outputs"].items():
        if Path(name).is_absolute() or ".." in Path(name).parts or not (root/name).is_file() or lit.sha256(root/name)!=digest:
            lit.fail("prior OA output changed: "+name)
    rows,_=lit.read_csv(root/"oa_attempts.csv",FIELDS)
    return root,{row["record_id"]:row for row in rows}


def build(a):
    records,_=lit.read_csv(a.records,("record_id","title","doi","pmid"))
    if not 1<=len(records)<=MAX_RECORDS or len({r["record_id"] for r in records})!=len(records):
        lit.fail("OA run needs 1-20 distinct bibliographic records")
    entries=metadata(a.metadata);base,network_mode=base_url(a)
    records_hash=lit.sha256(a.records);metadata_hash=lit.sha256(a.metadata)
    prior_root,prior=(checked_prior(a.prior,records_hash,metadata_hash) if a.prior else (None,{}))
    out=Path(a.out).resolve()
    if out.exists():lit.fail("OA output exists")
    out.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".oa-fulltext-",dir=out.parent) as temp:
        stage=Path(temp)/"result";stage.mkdir();(stage/"documents").mkdir()
        attempts=[];templates=[]
        for record in records:
            rid=record["record_id"]
            row=dict.fromkeys(FIELDS,"");row.update(record_id=rid,pmid=record["pmid"],doi=record["doi"],attempted_at=now())
            prior_row=prior.get(rid)
            if prior_row and prior_row["status"]=="OA_CANDIDATE_DOWNLOADED":
                for key in ("xml_path","text_path"):
                    old=prior_root/prior_row[key]
                    if lit.sha256(old)!=prior_row[key.replace("path","sha256")]:lit.fail("prior downloaded content changed")
                    shutil.copyfile(old,stage/prior_row[key])
                row.update(prior_row);row["reused_prior"]="true"
            else:
                entry,reason=match(record,entries)
                if reason:row.update(status=reason,reason=reason)
                elif str(entry.get("isOpenAccess","")).upper()!="Y":
                    row.update(status="OA_NOT_CONFIRMED",reason="Europe PMC metadata did not assert open access")
                elif str(entry.get("isRetracted","")).upper()=="Y":
                    row.update(status="RETRACTED_METADATA_REVIEW",reason="retracted metadata; no automatic retrieval")
                else:
                    pmcid=str(entry.get("pmcid") or "").strip().upper()
                    row["metadata_oa"]="Y";row["pmcid"]=pmcid
                    if not re.fullmatch(r"PMC[0-9]+",pmcid):
                        row.update(status="NO_VALID_PMCID",reason="OA metadata lacks a valid PMCID")
                    else:
                        url=base+pmcid+"/fullTextXML";row["content_url"]=url
                        try:
                            data,mime=fetch(url)
                        except (HTTPError,URLError,TimeoutError,OSError,ValueError,http.client.HTTPException) as exc:
                            row.update(status="FETCH_FAILED",reason=str(exc)[:300])
                        else:
                            try:
                                license_uri,license_label,version,text=inspect_jats(data,record,pmcid)
                                stem=sha(rid.encode("utf-8"))[:20]
                                xml_name="documents/"+stem+".xml";text_name="documents/"+stem+".txt"
                                (stage/xml_name).write_bytes(data);(stage/text_name).write_bytes(text)
                                row.update(status="OA_CANDIDATE_DOWNLOADED",license_uri=license_uri,
                                    license_label=license_label,version_status=version,mime=mime,bytes=str(len(data)),
                                    xml_path=xml_name,xml_sha256=sha(data),text_path=text_name,text_sha256=sha(text))
                            except (OSError,ValueError) as exc:
                                row.update(status="JATS_REVIEW_REQUIRED",reason=str(exc)[:300])
            attempts.append(row)
            stem=sha(rid.encode("utf-8"))[:20]
            good=row["status"]=="OA_CANDIDATE_DOWNLOADED"
            templates.append(dict(record_id=rid,attempt_id="OA-"+stem,status="alternative_candidate" if good else
                "awaiting_permission" if row["status"]=="OA_NOT_CONFIRMED" else "pending",
                source_document="Europe PMC JATS "+row["pmcid"] if good else "",
                file_path=str((out/row["text_path"]).resolve()) if good else "",format="text" if good else "",
                rights_basis=row["license_uri"] if good else "",document_doi=record["doi"] if good else "",
                document_pmid=record["pmid"] if good else "",version_relation=row["version_status"] if good else "",
                identity_basis="pmid_in_text" if good and record["pmid"] else "doi_in_text" if good else "",
                identity_evidence="candidate JATS IDs and license; human article/version check pending" if good else "",
                reason="" if good else row["reason"] or row["status"],reviewer="AGENT_CANDIDATE_NOT_HUMAN",
                decision_date=now()[:10],revision_of="",revision_reason=""))
        lit.write_csv(stage/"oa_attempts.csv",FIELDS,attempts)
        lit.write_csv(stage/"local_retrieval_attempts_template.csv",local_retrieval.ALL_FIELDS,templates)
        receipt=dict(schema="meta-oa-fulltext-v1",status="OFFLINE_LOCAL_HTTP_TEST" if network_mode=="LOCAL_HTTP_FIXTURE" else
            "LIVE_EXTERNAL_RESPONSE_UNVALIDATED",final=False,records_path=str(Path(a.records).resolve()),records_sha256=records_hash,
            metadata_path=str(Path(a.metadata).resolve()),metadata_sha256=metadata_hash,
            source="Europe PMC resultList.result plus fixed fullTextXML path",network_mode=network_mode,
            prior_receipt_sha256=lit.sha256(prior_root/"oa_receipt.json") if prior_root else "",
            downloaded=sum(r["status"]=="OA_CANDIDATE_DOWNLOADED" for r in attempts),
            candidate_requires_explicit_identity_version_review=True,
            outputs={str(p.relative_to(stage)).replace('\\','/'):lit.sha256(p) for p in stage.rglob('*') if p.is_file()})
        (stage/"oa_receipt.json").write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        os.replace(stage,out)
    print(receipt["status"],receipt["downloaded"],"candidates",out)


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    for key in ("records","metadata","out"):p.add_argument("--"+key,required=True)
    p.add_argument("--local-base-url");p.add_argument("--online",action="store_true")
    p.add_argument("--prior");a=p.parse_args()
    try:build(a)
    except (OSError,ValueError,KeyError,TypeError,csv.Error) as exc:p.exit(2,"Validation: "+str(exc)+"\n")
