"""Build a generic, unsubmitted review-registration draft from local plans and search ledgers."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile

import literature as lit
import source_chain

STATUS="DRAFT_NOT_SUBMITTED_NOT_REGISTERED"
FIELDS=("code","status","source","review_action")


def nonblank(value):
    return isinstance(value,str) and bool(value.strip()) and not value.strip().upper().startswith("PENDING")


def completed(value):
    if isinstance(value,str):return nonblank(value)
    if isinstance(value,(list,tuple)):return bool(value) and all(completed(item) for item in value)
    if isinstance(value,dict):return bool(value) and all(completed(item) for item in value.values())
    return value is not None


def save(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")


def load(path):
    value=json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value,dict):lit.fail("registration source must be a JSON object")
    return value


def markdown(value):
    if isinstance(value,(dict,list)):
        value=json.dumps(value,ensure_ascii=False)
    return str(value).replace("\r"," ").replace("\n"," ").replace("|","\\|").replace("<","&lt;")


def build(a):
    protocol_path=Path(a.protocol).resolve();out=Path(a.out).resolve()
    if out.exists():lit.fail("registration output already exists")
    protocol=load(protocol_path)
    project_id=protocol.get("protocol_id") or protocol.get("project_id")
    if not nonblank(project_id) or not nonblank(protocol.get("question")):
        lit.fail("registration draft needs a named protocol/project and research question")
    pico=protocol.get("pico",{})
    if not isinstance(pico,dict):lit.fail("protocol PICO must be an object")
    outcome=protocol.get("outcome",{})
    analysis=protocol.get("analysis",{})
    if analysis and not isinstance(analysis,dict):lit.fail("protocol analysis must be an object")
    search_candidate_path=Path(a.search_candidate).resolve() if a.search_candidate else None
    search_candidate=load(search_candidate_path) if search_candidate_path else None
    if search_candidate and not nonblank(search_candidate.get("query")):
        lit.fail("search candidate lacks a query")
    chain_path=Path(a.source_chain).resolve() if a.source_chain else None
    searches=[];chain_status="NOT_SUPPLIED"
    if chain_path:
        root,_,batches,_=source_chain.checked_prior(chain_path)
        chain_status=load(root/"chain_receipt.json")["status"]
        searches=[{k:row[k] for k in source_chain.BATCH_FIELDS} for row in batches]
    draft={
        "schema":"meta-generic-registration-draft-v1",
        "status":STATUS,"platform":None,"registration_number":None,"submitted_at":None,
        "generated_at_utc":datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "project_id":project_id,"question":protocol["question"],
        "protocol_stage":protocol.get("planning_status") or protocol.get("mode") or "UNCLASSIFIED_LOCAL_PLAN",
        "protocol_schema":protocol.get("schema") or "pairwise_protocol_without_schema",
        "pico":pico,"eligible_designs":protocol.get("eligible_designs"),
        "inclusion_criteria":protocol.get("inclusion_criteria"),
        "exclusion_criteria":protocol.get("exclusion_criteria"),
        "outcome":outcome,"analysis_plan":analysis,
        "sensitivity_plan":protocol.get("sensitivity_plan"),
        "review_workflow_mode":protocol.get("review_workflow_mode"),
        "extraction_plan":protocol.get("extraction_plan"),
        "risk_of_bias_plan":protocol.get("rob_plan") or protocol.get("quality_tool"),
        "certainty_plan":protocol.get("certainty_plan"),
        "registration_contact":protocol.get("registration_contact"),
        "review_team":protocol.get("review_team"),
        "funding":protocol.get("funding"),
        "competing_interests":protocol.get("competing_interests"),
        "ethics_statement":protocol.get("ethics_statement"),
        "planned_timeline":protocol.get("planned_timeline"),
        "search_candidate":search_candidate,
        "recorded_search_batches":searches,"source_chain_status":chain_status,
        "searches_already_recorded":bool(searches),
        "prospective_registration_claim_permitted":False,
        "scope":"generic author-review material; no platform schema mapping, submission or registration claim"}
    fields=[("pico",pico,"protocol.pico","Confirm all relevant PICO or diagnostic/exposure elements"),
            ("eligible_designs",draft["eligible_designs"],"protocol.eligible_designs","Define eligible designs"),
            ("inclusion_criteria",draft["inclusion_criteria"],"protocol.inclusion_criteria","Define inclusion criteria"),
            ("exclusion_criteria",draft["exclusion_criteria"],"protocol.exclusion_criteria","Define exclusion criteria"),
            ("outcome",outcome,"protocol.outcome","Define outcome, measurement and timepoint"),
            ("analysis_plan",analysis,"protocol.analysis","Review effect scale, model and assumptions"),
            ("sensitivity_plan",draft["sensitivity_plan"],"protocol.sensitivity_plan","Prespecify sensitivity analyses"),
            ("database_specific_search_strategies",protocol.get("search_strategies"),"protocol.search_strategies","Supply reviewed full strategy, dates and limits for each source; a query candidate is insufficient"),
            ("screening_process",draft["review_workflow_mode"],"protocol.review_workflow_mode","Describe reviewer roles and conflict resolution"),
            ("extraction_plan",draft["extraction_plan"],"protocol.extraction_plan","Describe data extraction and verification"),
            ("risk_of_bias_plan",draft["risk_of_bias_plan"],"protocol.rob_plan/quality_tool","Specify applicable tool, domains and reviewer process"),
            ("certainty_plan",draft["certainty_plan"],"protocol.certainty_plan","Specify outcome-level certainty process"),
            ("registration_contact",draft["registration_contact"],"protocol.registration_contact","Provide actual contact details locally"),
            ("review_team",draft["review_team"],"protocol.review_team","Provide actual team and roles"),
            ("funding",draft["funding"],"protocol.funding","Disclose funding or explicitly state none after review"),
            ("competing_interests",draft["competing_interests"],"protocol.competing_interests","Disclose conflicts or explicitly state none after review"),
            ("ethics_statement",draft["ethics_statement"],"protocol.ethics_statement","Review applicability of ethics statement"),
            ("planned_timeline",draft["planned_timeline"],"protocol.planned_timeline","Supply realistic planned timeline")]
    rows=[]
    for code,value,source,action in fields:
        present=completed(value)
        rows.append(dict(code=code,status="PRESENT_UNREVIEWED_SOURCE_CLAIM" if present else "MISSING_OR_PENDING",
                         source=source,review_action=action))
    if not searches:
        rows.append(dict(code="recorded_search_batches",status="NOT_SUPPLIED",
                         source="source_chain",review_action="If searches have already occurred, attach and verify their batch ledger; absence is not proof no search occurred"))
    if searches:
        rows.append(dict(code="prospective_timing",status="SEARCHES_ALREADY_RECORDED",
                         source="source_chain.batch_ledger.csv",review_action="Do not describe this later draft as registered before the searches"))
    inputs={"protocol":{"path":str(protocol_path),"sha256":lit.sha256(protocol_path)}}
    if chain_path:inputs["source_chain"]={"path":str(chain_path),"receipt_sha256":lit.sha256(chain_path/"chain_receipt.json")}
    if search_candidate_path:inputs["search_candidate"]={"path":str(search_candidate_path),"sha256":lit.sha256(search_candidate_path)}
    out.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".registration-draft-",dir=out.parent) as temp:
        stage=Path(temp)/"result";stage.mkdir()
        save(stage/"registration_draft.json",draft)
        lit.write_csv(stage/"field_status.csv",FIELDS,rows)
        lit.write_csv(stage/"missing_items.csv",FIELDS,[r for r in rows if r["status"]!="PRESENT_UNREVIEWED_SOURCE_CLAIM"])
        lines=["# Generic review registration material — DRAFT ONLY","",
            "**NOT SUBMITTED. NOT REGISTERED. No platform registration number or submission date exists.**","",
            "This is an author-review worksheet, not a PROSPERO/OSF form or a claim of platform compliance.","",
            "## Protocol source","",f"Project: {markdown(project_id)}",f"Question: {markdown(protocol['question'])}",
            f"Protocol stage: {markdown(draft['protocol_stage'])}","","## Proposed content","",]
        for key in ("pico","eligible_designs","inclusion_criteria","exclusion_criteria","outcome","analysis_plan",
                    "sensitivity_plan","review_workflow_mode","extraction_plan","risk_of_bias_plan","certainty_plan"):
            lines.append(f"- {key}: {markdown(draft.get(key)) if draft.get(key) else '[MISSING / PENDING REVIEW]'}")
        lines.extend(["","## Search provenance","",
            f"Recorded batches supplied: {len(searches)}; source chain status: {chain_status}."])
        if searches:
            lines.append("Searches were already recorded before this draft was made; do not claim prospective registration.")
            for row in searches:
                lines.append("- "+markdown(row))
        else:lines.append("No batch ledger was supplied; this does not establish that no searches took place.")
        if search_candidate:lines.append("Unreviewed search candidate: "+markdown(search_candidate))
        lines.extend(["","## Author details and disclosures",""])
        for key in ("registration_contact","review_team","funding","competing_interests","ethics_statement","planned_timeline"):
            lines.append(f"- {key}: {markdown(draft.get(key)) if draft.get(key) else '[MISSING / PENDING REVIEW]'}")
        lines.extend(["","## Required review","",
            "See `missing_items.csv`; all nonblank fields are still source claims requiring author review. Do not add a platform ID/date until an actual external registration occurs.",""])
        (stage/"registration_draft.md").write_text("\n".join(lines),encoding="utf-8")
        receipt={"schema":"meta-registration-draft-receipt-v1","status":STATUS,"inputs":inputs,
                 "outputs":{p.name:lit.sha256(p) for p in stage.iterdir() if p.is_file()},
                 "missing_count":sum(r["status"]!="PRESENT_UNREVIEWED_SOURCE_CLAIM" for r in rows),
                 "searches_already_recorded":bool(searches)}
        save(stage/"draft_receipt.json",receipt)
        os.replace(stage,out)
    print(STATUS,"missing",receipt["missing_count"],out)


def verify(path):
    root=Path(path).resolve();receipt=load(root/"draft_receipt.json")
    if receipt.get("schema")!="meta-registration-draft-receipt-v1" or receipt.get("status")!=STATUS:
        lit.fail("invalid registration draft receipt")
    for name,item in receipt["inputs"].items():
        file=Path(item["path"])
        if name=="source_chain":
            source_chain.checked_prior(file)
            file=file/"chain_receipt.json";digest=item["receipt_sha256"]
        else:digest=item["sha256"]
        if not file.is_file() or lit.sha256(file)!=digest:lit.fail("registration draft input changed: "+name)
    for name,digest in receipt["outputs"].items():
        file=root/name
        if not file.is_file() or lit.sha256(file)!=digest:lit.fail("registration draft output changed: "+name)
    draft=load(root/"registration_draft.json")
    if draft.get("status")!=STATUS or any(draft.get(k) is not None for k in ("platform","registration_number","submitted_at")) or \
            draft.get("prospective_registration_claim_permitted") is not False:
        lit.fail("registration draft was promoted without an actual external registration")
    return receipt


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest="command",required=True)
    b=sub.add_parser("build");b.add_argument("--protocol",required=True);b.add_argument("--source-chain")
    b.add_argument("--search-candidate");b.add_argument("--out",required=True)
    v=sub.add_parser("verify");v.add_argument("--draft",required=True)
    a=p.parse_args()
    try:
        if a.command=="build":build(a)
        else:print("VERIFIED",verify(a.draft)["status"],Path(a.draft).resolve())
    except (OSError,ValueError,KeyError,TypeError) as exc:p.exit(2,"Validation: "+str(exc)+"\n")
