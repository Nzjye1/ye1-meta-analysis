"""Bounded Europe PMC public REST search to a checked local bibliography export."""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time
from types import SimpleNamespace
from urllib.parse import urlencode
from urllib.request import Request, build_opener

import literature as lit
from oa_fulltext import NoRedirect, OFFICIAL

FIELDS=("source_record_id","title","authors","year","doi","pmid","source_type")
LEDGER=("page","cursor_mark","requested","returned","request_url","response_file",
        "response_bytes","response_sha256","fetched_at_utc","mode")
MAX_BYTES=256_000


def now():return datetime.now(timezone.utc).isoformat(timespec="seconds")
def digest(data):return hashlib.sha256(data).hexdigest()
def save(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")


def validate(a):
    if not a.query.strip() or len(a.query)>1000:lit.fail("query needs 1-1000 public-search characters")
    if not a.source_label.strip() or len(a.source_label)>100:lit.fail("stable source label needed")
    if not 1<=a.max_records<=20 or not 1<=a.page_size<=20:lit.fail("max-records and page-size must be 1-20")
    if bool(a.fixture_dir)==bool(a.online):lit.fail("choose exactly one: --fixture-dir or --online")
    if a.fixture_dir and not Path(a.fixture_dir).is_dir():lit.fail("fixture directory missing")
    if a.pico and not Path(a.pico).is_file():lit.fail("PICO file missing")
    if a.review_status=="human_reviewed" and not (a.reviewer and a.approval_ref):
        lit.fail("human_reviewed needs reviewer and approval-ref")
    if a.review_status!="human_reviewed" and (a.reviewer or a.approval_ref):
        lit.fail("reviewer/approval-ref require human_reviewed")


def request_page(a,page,cursor,size):
    url=OFFICIAL+"search?"+urlencode({"query":a.query,"format":"json","resultType":"lite",
                                      "pageSize":size,"cursorMark":cursor})
    if a.fixture_dir:
        data=(Path(a.fixture_dir)/f"page_{page:03d}.json").read_bytes()
        mode="OFFLINE_FIXTURE"
    else:
        opener=build_opener(NoRedirect)
        with opener.open(Request(url,headers={"Accept":"application/json",
            "User-Agent":"MetaSkill-EuropePMC-Bounded-Search/0.1"}),timeout=20) as response:
            if response.status!=200 or response.headers.get_content_type()!="application/json":
                lit.fail("Europe PMC search needs HTTP 200 application/json")
            declared=response.headers.get("Content-Length")
            if declared and (not declared.isdigit() or int(declared)>MAX_BYTES):
                lit.fail("search page Content-Length exceeds 256 KB cap")
            data=response.read(MAX_BYTES+1)
            if declared and len(data)!=int(declared):lit.fail("search page length differs from Content-Length")
        mode="LIVE_EUROPE_PMC"
    if not data or len(data)>MAX_BYTES:lit.fail("search page empty or above 256 KB cap")
    return data,url,mode


def parse_page(data,query):
    response=json.loads(data)
    if not isinstance(response,dict) or not isinstance(response.get("resultList",{}).get("result"),list):
        lit.fail("Europe PMC response lacks resultList.result")
    if response.get("request",{}).get("queryString")!=query:
        lit.fail("Europe PMC echoed a different query")
    count=response.get("hitCount")
    if isinstance(count,bool) or not isinstance(count,int) or count<0:lit.fail("invalid Europe PMC hitCount")
    return count,response["resultList"]["result"],str(response.get("nextCursorMark") or "")


def normalize(entry):
    if not isinstance(entry,dict):lit.fail("Europe PMC result is not an object")
    source=str(entry.get("source") or "").strip();eid=str(entry.get("id") or "").strip()
    title=str(entry.get("title") or "").strip();year=str(entry.get("pubYear") or "").strip()
    if not year:year=str(entry.get("firstPublicationDate") or "")[:4]
    if not source or not eid or not title or not re.fullmatch(r"(?:19|20)\d{2}",year):
        lit.fail("Europe PMC result lacks stable source/id/title/year")
    pmid=str(entry.get("pmid") or "").strip()
    if pmid and not pmid.isdigit():lit.fail("Europe PMC result PMID is not numeric")
    return dict(source_record_id=source+":"+eid,title=title,
                authors=str(entry.get("authorString") or ""),year=year,
                doi=str(entry.get("doi") or ""),pmid=pmid,source_type="europe_pmc_rest")


def run(a):
    validate(a);out=Path(a.out).resolve()
    if out.exists():lit.fail("output already exists")
    out.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".europe-pmc-search-",dir=out.parent) as temp:
        stage=Path(temp)/"result";stage.mkdir();(stage/"raw").mkdir()
        mode="OFFLINE_FIXTURE" if a.fixture_dir else "LIVE_EUROPE_PMC"
        receipt=dict(schema="meta-europe-pmc-search-v1",database="Europe PMC REST",
            query=a.query,source_label=a.source_label,started_at_utc=now(),max_records=a.max_records,
            page_size=a.page_size,query_review_status=a.review_status,reviewer=a.reviewer or "",
            approval_ref=a.approval_ref or "",mode=mode,
            pico_path=str(Path(a.pico).resolve()) if a.pico else "",
            pico_sha256=lit.sha256(a.pico) if a.pico else "",
            scope="single Europe PMC service, with overlap with PubMed; not an independent second database")
        save(stage/"query_receipt.json",receipt)
        status=dict(status="FAILED",completeness="NOT_ESTABLISHED",hit_count=None,retrieved=0,
                    mode=mode,error="",origin_authentication="LOCAL_RESPONSE_HASHES_ONLY")
        ledger=[];collected=[];seen=set();cursor="*";page=0
        try:
            while status["hit_count"] is None or len(collected)<min(status["hit_count"],a.max_records):
                size=min(a.page_size,a.max_records-len(collected))
                if status["hit_count"] is not None:size=min(size,status["hit_count"]-len(collected))
                if size<=0:break
                if page and not a.fixture_dir:time.sleep(.35)
                data,url,source_mode=request_page(a,page,cursor,size)
                name=f"raw/page_{page:03d}.json";(stage/name).write_bytes(data)
                count,batch,next_cursor=parse_page(data,a.query)
                if status["hit_count"] is None:status["hit_count"]=count
                if count!=status["hit_count"] or len(batch)!=min(size,count-len(collected)):
                    lit.fail("Europe PMC page count/size changed during bounded cursor retrieval")
                for entry in batch:
                    item=normalize(entry)
                    if item["source_record_id"] in seen:lit.fail("repeated stable record across Europe PMC pages")
                    seen.add(item["source_record_id"]);collected.append(item)
                ledger.append(dict(page=page,cursor_mark=cursor,requested=size,returned=len(batch),
                    request_url=url,response_file=name,response_bytes=len(data),response_sha256=digest(data),
                    fetched_at_utc=now(),mode=source_mode))
                status["retrieved"]=len(collected)
                if len(collected)<min(count,a.max_records):
                    if not next_cursor or next_cursor==cursor:lit.fail("Europe PMC next cursor missing/repeated")
                    cursor=next_cursor
                page+=1
            lit.write_csv(stage/"europe_pmc_export.csv",FIELDS,collected)
            lit.write_csv(stage/"result_ledger.csv",("source_record_id","record_id","source_label","page","raw_response_file"),[])
            if collected:
                lit.import_records(SimpleNamespace(input=str(stage/"europe_pmc_export.csv"),
                                                   source=a.source_label,out=str(stage/"bibliography")))
                manifest=stage/"bibliography/import_manifest.csv"
                import_rows,_=lit.read_csv(manifest,("key","value"))
                for row in import_rows:
                    if row["key"]=="original_source_path":row["value"]=str(out/"europe_pmc_export.csv")
                lit.write_csv(manifest,("key","value"),import_rows)
                records,_=lit.read_csv(stage/"bibliography/records.csv",("source_record_id","record_id"))
                ids={r["source_record_id"]:r["record_id"] for r in records}
                offsets={item["source_record_id"]:i//a.page_size for i,item in enumerate(collected)}
                lit.write_csv(stage/"result_ledger.csv",("source_record_id","record_id","source_label","page","raw_response_file"),
                    [dict(source_record_id=item["source_record_id"],record_id=ids[item["source_record_id"]],
                          source_label=a.source_label,page=offsets[item["source_record_id"]],
                          raw_response_file=f"raw/page_{offsets[item['source_record_id']]:03d}.json") for item in collected])
            status["status"]="SUCCESS"
            status["completeness"]=("FIXTURE_COUNT_RECONCILED" if a.fixture_dir else "LIVE_COUNT_RECONCILED_LOCAL_CLAIM") \
                if len(collected)==status["hit_count"] else ("FIXTURE_QUERY_LIMITED" if a.fixture_dir else "LIVE_QUERY_LIMITED")
        except (OSError,ValueError,KeyError,TypeError,IndexError,json.JSONDecodeError) as exc:
            status["error"]=f"{type(exc).__name__}: {exc}"
        finally:
            status["finished_at_utc"]=now();save(stage/"search_status.json",status)
            lit.write_csv(stage/"request_ledger.csv",LEDGER,ledger)
            if status["status"]=="SUCCESS" and collected:
                save(stage/"bibliography/search_provenance.json",dict(schema="meta-search-provenance-v1",
                    source_type="europe_pmc_rest",source_label=a.source_label,search_root="..",
                    query_receipt_sha256=lit.sha256(stage/"query_receipt.json"),
                    search_status_sha256=lit.sha256(stage/"search_status.json"),
                    result_ledger_sha256=lit.sha256(stage/"result_ledger.csv"),
                    export_sha256=lit.sha256(stage/"europe_pmc_export.csv")))
            lit.write_csv(stage/"search_manifest.csv",("relative_path","sha256","bytes"),
                [dict(relative_path=p.relative_to(stage).as_posix(),sha256=lit.sha256(p),bytes=p.stat().st_size)
                 for p in sorted(stage.rglob("*")) if p.is_file()])
            os.replace(stage,out)
    print(status["status"],status["completeness"],status["retrieved"],"of",status["hit_count"],out)
    return status


def check_provenance(folder):
    folder=Path(folder).resolve();root=folder.parent
    marker=json.loads((folder/"search_provenance.json").read_text(encoding="utf-8"))
    if marker.get("schema")!="meta-search-provenance-v1" or marker.get("source_type")!="europe_pmc_rest" or \
            marker.get("search_root")!="..":lit.fail("invalid Europe PMC search marker")
    names=(("query_receipt.json","query_receipt_sha256"),("search_status.json","search_status_sha256"),
           ("result_ledger.csv","result_ledger_sha256"),("europe_pmc_export.csv","export_sha256"))
    for name,key in names:
        if not (root/name).is_file() or marker.get(key)!=lit.sha256(root/name):
            lit.fail("Europe PMC search evidence changed: "+name)
    manifest,_=lit.read_csv(root/"search_manifest.csv",("relative_path","sha256","bytes"))
    paths=[r["relative_path"] for r in manifest]
    if len(set(paths))!=len(paths) or not {"query_receipt.json","search_status.json","request_ledger.csv",
            "result_ledger.csv","europe_pmc_export.csv","bibliography/records.csv",
            "bibliography/search_provenance.json","raw/page_000.json"}<=set(paths):
        lit.fail("Europe PMC search manifest incomplete/repeated")
    for row in manifest:
        file=(root/row["relative_path"]).resolve()
        if not file.is_relative_to(root) or not file.is_file() or lit.sha256(file)!=row["sha256"] or \
                file.stat().st_size!=int(row["bytes"]):lit.fail("Europe PMC search file changed: "+row["relative_path"])
    ledger,_=lit.read_csv(root/"request_ledger.csv",LEDGER)
    if len(ledger)>20 or {r["response_file"] for r in ledger}!={p for p in paths if p.startswith("raw/page_")}:
        lit.fail("Europe PMC page ledger disagrees with raw responses")
    query=json.loads((root/"query_receipt.json").read_text(encoding="utf-8"))
    status=json.loads((root/"search_status.json").read_text(encoding="utf-8"))
    recovered=[];cursor="*"
    for i,row in enumerate(ledger):
        raw=(root/row["response_file"]).read_bytes()
        if row["response_file"]!=f"raw/page_{i:03d}.json" or row["page"]!=str(i) or \
                row["cursor_mark"]!=cursor or row["response_bytes"]!=str(len(raw)) or \
                digest(raw)!=row["response_sha256"] or row["mode"]!=status.get("mode"):
            lit.fail("Europe PMC page ledger disagrees with raw responses")
        count,batch,cursor=parse_page(raw,query["query"])
        if count!=status.get("hit_count") or row["returned"]!=str(len(batch)) or \
                row["requested"]!=str(len(batch)):
            lit.fail("Europe PMC raw page count disagrees with page ledger/status")
        recovered.extend(normalize(item) for item in batch)
    records,_=lit.read_csv(folder/"records.csv",("record_id","source_label","source_record_id"))
    export,_=lit.read_csv(root/"europe_pmc_export.csv",FIELDS)
    if status.get("status")!="SUCCESS" or status.get("retrieved")!=len(records) or \
            query.get("source_label")!=marker.get("source_label") or \
            {r["source_label"] for r in records}!={marker["source_label"]} or \
            status.get("mode")!=query.get("mode") or \
            len(export)!=len(records) or export!=recovered or \
            {r["source_type"] for r in export}!={"europe_pmc_rest"}:
        lit.fail("Europe PMC query/status/records disagree")
    result,_=lit.read_csv(root/"result_ledger.csv",("source_record_id","record_id","source_label"))
    if {(r["source_record_id"],r["record_id"],r["source_label"]) for r in records} != \
            {(r["source_record_id"],r["record_id"],r["source_label"]) for r in result}:
        lit.fail("Europe PMC result IDs disagree with imported records")
    return query,status,marker


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--query",required=True,help="Public search terms only; never patient data")
    p.add_argument("--source-label",required=True);p.add_argument("--out",required=True)
    p.add_argument("--max-records",type=int,default=20);p.add_argument("--page-size",type=int,default=10)
    p.add_argument("--fixture-dir");p.add_argument("--online",action="store_true")
    p.add_argument("--pico");p.add_argument("--review-status",choices=("pending_review","human_reviewed"),default="pending_review")
    p.add_argument("--reviewer");p.add_argument("--approval-ref")
    args=p.parse_args()
    try:
        result=run(args)
        if result["status"]!="SUCCESS":p.exit(2,result["error"]+"\n")
    except (OSError,ValueError,KeyError,TypeError,csv.Error) as exc:p.exit(2,"Validation: "+str(exc)+"\n")
