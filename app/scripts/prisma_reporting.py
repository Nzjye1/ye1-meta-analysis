"""PRISMA 2020 batch/update accounting and inspectable article supplement."""
import argparse
import csv
from datetime import date
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import zipfile
from types import SimpleNamespace
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

import diagnostic_word
import literature as lit
import prisma2020_flow as flow

METHOD_SCHEMAS={
    "meta-diagnostic-manuscript-v1":("diagnostic","meta-diagnostic-confirmation-v1"),
    "meta-multithreshold-manuscript-v1":("multithreshold","meta-multithreshold-confirmation-v1"),
    "meta-network-manuscript-v1":("network","meta-network-confirmation-v1"),
    "meta-dose-manuscript-v1":("dose","meta-dose-confirmation-v1"),
    "meta-single-arm-manuscript-v1":("single_arm","meta-single-arm-confirmation-v1"),
    "meta-dependent-manuscript-v1":("dependent","meta-dependent-confirmation-v1"),
    "meta-rare-event-manuscript-v1":("rare","meta-rare-event-confirmation-v1"),
}

ITEMS=("1","2","3","4","5","6","7","8","9","10a","10b","11","12",
       "13a","13b","13c","13d","13e","13f","14","15","16a","16b","17","18","19",
       "20a","20b","20c","20d","21","22","23a","23b","23c","23d","24a","24b","24c","25","26","27")
BATCH_FIELDS=("batch_id","source_label","source_name","phase","update_of","search_date","query_reference","reviewer","status")
PRIOR_FIELDS=("study_id","report_id","current_status","change_reason","source_reference","reviewer","reviewed_at")
LOCATION_FIELDS=("item_id","article_paragraph_id","supplement_section","applicability","reviewer","rationale")
SECTIONS={"search_batches","selection","prior_review","excluded_reports","included_studies","item_locations"}
EVIDENCE_FIELDS=("component","status","source_receipt","source_receipt_sha256","scope","interpretation")


def rows(path,fields,allow_empty=False):return lit.read_csv(path,fields,allow_empty=allow_empty)[0]
def load(path):return json.loads(Path(path).read_text(encoding="utf-8"))
def nonblank(value):return isinstance(value,str) and bool(value.strip())
def valid_date(value):
    try:date.fromisoformat(value)
    except (ValueError,TypeError):lit.fail("PRISMA ledger date must be YYYY-MM-DD")


def recheck(packet,paper):
    packet=Path(packet).resolve();paper=Path(paper).resolve()
    context=load(packet/"report_inputs.json")
    if not all(context.get(key) for key in ("prisma_dir","source_methods","retrieval")):
        lit.fail("article supplement needs packet with bound extended PRISMA flow")
    a=SimpleNamespace(**context)
    _,numbers,source_rows,reason_rows=flow.calculate(a)
    counts={r["metric"]:int(r["count"]) for r in rows(packet/"prisma_flow_counts.csv",("metric","count"))}
    if counts!=numbers:lit.fail("packet PRISMA counts differ from current source ledgers")
    packet_sources=rows(packet/"source_route_counts.csv",("source_label","identified_records"))
    if packet_sources!=[{k:str(v) for k,v in row.items()} for row in source_rows]:
        lit.fail("packet source counts differ from current source ledgers")
    packet_reasons=rows(packet/"reason_counts.csv",("stage","reason","report_count"),allow_empty=True)
    if packet_reasons!=[{k:str(v) for k,v in r.items()} for r in reason_rows]:
        lit.fail("packet exclusion reasons differ from current source ledgers")
    manifest={r["key"]:r["value"] for r in rows(packet/"flow_manifest.csv",("key","value"))}
    for key,path in {"confirmation_sha256":a.confirmation,"source_methods_sha256":a.source_methods,
                     "retrieval_sha256":a.retrieval,"prisma_flow_counts_sha256":packet/"prisma_flow_counts.csv",
                     "source_route_counts_sha256":packet/"source_route_counts.csv","reason_counts_sha256":packet/"reason_counts.csv",
                     "prisma_flow_svg_sha256":packet/"prisma_flow.svg","prisma_item_audit_sha256":packet/"prisma_item_audit.json"}.items():
        if manifest.get(key)!=lit.sha256(path):lit.fail("packet PRISMA manifest/source changed: "+key)
    document=load(paper/"manuscript.json");files=load(paper/"manifest.json")
    if document.get("schema")!="meta-manuscript-v1" or not (paper/"manuscript.docx").is_file():
        lit.fail("article supplement requires existing pairwise manuscript")
    if any(not (paper/name).is_file() or lit.sha256(paper/name)!=digest for name,digest in files.items()):
        lit.fail("manuscript output changed after its manifest")
    for path,digest in document["source_sha256"].items():
        if not Path(path).is_file() or lit.sha256(path)!=digest:lit.fail("manuscript source changed")
    for name,path in document["attachments"].items():
        if not Path(path).is_file() or lit.sha256(path)!=document["attachment_sha256"][name]:
            lit.fail("manuscript attachment changed: "+name)
    if document["attachment_sha256"].get("prisma_flow_counts.csv")!=lit.sha256(packet/"prisma_flow_counts.csv"):
        lit.fail("manuscript is not bound to this extended selection flow")
    with zipfile.ZipFile(paper/"manuscript.docx") as archive:
        if archive.testzip() is not None:lit.fail("Word archive damaged")
    return a,numbers,source_rows,reason_rows,document


def recheck_method(a):
    paper=Path(a.manuscript).resolve();doc=load(paper/"manuscript.json")
    family,confirmation_schema=METHOD_SCHEMAS.get(doc.get("schema"),(None,None))
    if not family:lit.fail("unsupported manuscript schema for PRISMA attachment")
    if not all((a.confirmation,a.source_methods,a.retrieval,a.search_batches)) or a.packet:
        lit.fail("method paper needs confirmation, source-methods, retrieval and search-batches, without pairwise packet")
    manifest=load(paper/"manifest.json");files=manifest.get("files",{})
    actual={str(p.relative_to(paper)).replace("\\","/"):lit.sha256(p) for p in paper.rglob("*") if p.is_file() and p.name!="manifest.json"}
    if not files or actual!=files:lit.fail("method manuscript manifest/files changed")
    with zipfile.ZipFile(paper/"manuscript.docx") as archive:
        if archive.testzip() is not None:lit.fail("method Word archive damaged")
    status=load(paper/"status.json")
    if status.get("final") is not False or doc.get("final") is not False or status.get("status")!=doc.get("status"):
        lit.fail("method manuscript status/final flag inconsistent")
    confirmation_path=Path(a.confirmation).resolve();confirmation=load(confirmation_path)
    if confirmation.get("schema")!=confirmation_schema or lit.sha256(confirmation_path)!=doc.get("fact_sources",{}).get("confirmation_sha256"):
        lit.fail("method paper confirmation does not match its fact source")
    receipt_files=list((paper/"statistics").glob("*receipt.json"))
    if len(receipt_files)!=1 or lit.sha256(receipt_files[0])!=doc["fact_sources"].get("statistics_receipt_sha256"):
        lit.fail("method paper statistics receipt does not match its fact source")
    paths=confirmation.get("input_paths",{});hashes=confirmation.get("hashes",{})
    for key in ("protocol","records","dedup","decisions","report_map"):
        if key not in paths or hashes.get(key)!=lit.sha256(paths[key]):lit.fail("method confirmation input changed: "+key)
    for key,path in paths.items():
        if key in hashes and hashes[key]!=lit.sha256(path):lit.fail("method confirmation input changed: "+key)
    for key in ("source_bytes","quality_evidence_bytes"):
        for path,digest in hashes.get(key,{}).items():
            if lit.sha256(path)!=digest:lit.fail("method confirmation source evidence changed")
    records,_=lit.read_csv(paths["records"],["record_id","title","authors","year","doi","pmid"])
    dedup=lit.load_dedup(records,paths["dedup"])
    decisions,_=lit.read_csv(paths["decisions"],["record_id","stage","decision","reason","reviewer","decision_date"])
    active={rid for rid,row in dedup.items() if row["disposition"]=="keep"}
    stages,included=lit.validate_screening(records,decisions,active)
    mapping,_=lit.read_csv(paths["report_map"],["record_id","report_id","study_id"])
    if len(mapping)!=len(included) or {r["record_id"] for r in mapping}!=included or len({r["report_id"] for r in mapping})!=len(mapping):
        lit.fail("method paper report/study map does not match included records")
    method_counts=load(paper/"selection_counts.json")
    expected={"records_imported":len(records),"records_removed_before_screening":len(records)-len(active),
              "reports_included":len(mapping),"studies_analyzed":len({r["study_id"] for r in mapping})}
    if any(method_counts.get(k)!=v for k,v in expected.items()):lit.fail("method selection counts differ from bound records/reports/studies")
    verified=(confirmation,records,dedup,stages,mapping,[])
    context=SimpleNamespace(source_methods=a.source_methods,retrieval=a.retrieval)
    _,numbers,source_rows,reason_rows=flow.calculate(context,verified)
    if (numbers["included_reports"],numbers["included_studies"])!=(expected["reports_included"],expected["studies_analyzed"]):
        lit.fail("method full-flow counts differ from its analyzed report/study units")
    normalized={"schema":doc["schema"],"synthetic":doc["status"].startswith("DRAFT_SYNTHETIC"),
                "paragraphs":[{"id":f"section-{i:04d}","text":section.get("text","")} for i,section in enumerate(doc.get("sections",[]),1)],
                "method_family":family,"status":doc["status"]}
    return context,numbers,source_rows,reason_rows,normalized,verified,method_counts,receipt_files[0]


def batches(path,source_rows,methods):
    data=rows(path,BATCH_FIELDS);by_source={};by_id={}
    methods={r["source_label"]:r for r in methods}
    source={r["source_label"]:r for r in source_rows}
    for row in data:
        bid,label=row["batch_id"],row["source_label"]
        if not bid or bid in by_id or row["phase"] not in {"initial","update","historical"}:
            lit.fail("search batches need distinct IDs and supported phases")
        historical=row["phase"]=="historical"
        if historical:
            if label or row["update_of"] or row["status"]!="historical_prior_reference":
                lit.fail("historical batch is a prior reference without a current source label or record count")
        elif label in by_source or label not in source or row["status"] not in {"documented_user_claim","pending_review"}:
            lit.fail("current search batch needs one row per known source and a declared status")
        if not all(nonblank(row[k]) for k in ("source_name","query_reference","reviewer")):
            lit.fail("batch strategy reference/reviewer/status required")
        valid_date(row["search_date"])
        if not historical and (row["search_date"]!=methods[label]["searched_on"] or row["source_name"]!=methods[label]["source_name"]):
            lit.fail("batch search date differs from source-method ledger")
        by_id[bid]=row
        if not historical:by_source[label]=row
    if set(by_source)!=set(source):lit.fail("search batches must cover every imported source exactly once")
    for row in data:
        parent=row["update_of"]
        if row["phase"] in {"initial","historical"} and parent:lit.fail("initial/historical batch cannot have update_of")
        if row["phase"]=="update":
            if parent not in by_id or by_id[parent]["search_date"]>=row["search_date"]:
                lit.fail("update batch needs an earlier known batch")
            if row["source_name"]!=by_id[parent]["source_name"]:
                lit.fail("update batch source name differs from parent")
    combined=[]
    for row in sorted(data,key=lambda r:(r["search_date"],r["batch_id"])):
        if row["phase"]=="historical":
            combined.append({**row,"identification_route":"previous_version_reference_only",
                             **{k:"" for k in ("identified_records","removed_duplicates","removed_other","screened_records",
                                                 "reports_sought","reports_not_retrieved","retrieval_pending","reports_assessed",
                                                 "reports_excluded","included_reports")}})
        else:
            src=source[row["source_label"]]
            combined.append({**row,"identification_route":src["identification_route"],
                             **{k:src[k] for k in ("identified_records","removed_duplicates","removed_other","screened_records",
                                                  "reports_sought","reports_not_retrieved","retrieval_pending","reports_assessed",
                                                  "reports_excluded","included_reports")}})
    return combined


def previous(path,mapping):
    if not path:return [],{"review_kind":"new","prior_studies":0,"prior_reports":0,"prior_reports_removed_on_update":0,
                          "prior_studies_removed_on_update":0,"new_studies":len({r["study_id"] for r in mapping}),
                          "new_reports":len(mapping),"reidentified_prior_reports":0,"final_studies":len({r["study_id"] for r in mapping}),"final_reports":len(mapping)}
    data=rows(path,PRIOR_FIELDS);by_report={};current={r["report_id"]:r["study_id"] for r in mapping}
    for row in data:
        rid,sid=row["report_id"],row["study_id"]
        if not rid or not sid or rid in by_report or row["current_status"] not in {"retained","excluded_on_update"}:
            lit.fail("previous-review report IDs must be unique with explicit disposition")
        if not all(nonblank(row[k]) for k in ("source_reference","reviewer","reviewed_at")):
            lit.fail("previous-review report needs source, reviewer and date")
        valid_date(row["reviewed_at"])
        if row["current_status"]=="retained":
            if row["change_reason"] or current.get(rid)!=sid:lit.fail("retained prior report must map to the same current study")
        elif not nonblank(row["change_reason"]) or rid in current:
            lit.fail("excluded prior report needs reason and cannot remain in included map")
        by_report[rid]=row
    prior_studies={r["study_id"] for r in data};current_studies={r["study_id"] for r in mapping}
    retained_studies={r["study_id"] for r in data if r["current_status"]=="retained"}
    if (prior_studies-retained_studies)&current_studies:
        lit.fail("prior study excluded on update but reappears under same study ID")
    counts={"review_kind":"updated","prior_studies":len(prior_studies),"prior_reports":len(data),
            "prior_reports_removed_on_update":sum(r["current_status"]=="excluded_on_update" for r in data),
            "prior_studies_removed_on_update":len(prior_studies-retained_studies),
            "new_studies":len(current_studies-prior_studies),"new_reports":len(set(current)-set(by_report)),
            "reidentified_prior_reports":sum(r["current_status"]=="retained" for r in data),
            "final_studies":len(current_studies),"final_reports":len(mapping)}
    if counts["final_reports"]!=counts["new_reports"]+counts["reidentified_prior_reports"]:
        lit.fail("updated-review report counts do not reconcile")
    return data,counts


def svg(n,prior):
    def box(x,y,title,value):
        return (f'<rect x="{x}" y="{y}" width="330" height="83" rx="7" fill="#f4f7fa" stroke="#35516c"/>'
                f'<text x="{x+12}" y="{y+27}" font-size="16" font-family="Arial">{escape(title)}</text>'
                f'<text x="{x+12}" y="{y+56}" font-size="20" font-family="Arial">{escape(str(value))}</text>')
    parts=[box(25,65,"Current search records identified",n["identified_records"]),
           box(385,65,"Removed before screening",f'{n["removed_duplicates"]} duplicate; {n["removed_other"]} other'),
           box(745,65,"Records screened",n["screened_records"]),
           box(25,185,"Title/abstract excluded or pending",f'{n["title_abstract_excluded"]} excluded; {n["title_abstract_pending"]} pending'),
           box(385,185,"Reports sought",n["reports_sought"]),
           box(745,185,"Not retrieved / pending",f'{n["reports_not_retrieved"]} / {n["retrieval_pending"]}'),
           box(25,305,"Reports assessed",n["reports_assessed"]),
           box(385,305,"Excluded after assessment",n["reports_excluded"]),
           box(745,305,"Current included reports / studies",f'{n["included_reports"]} / {n["included_studies"]}')]
    if prior["review_kind"]=="updated":
        parts.extend((box(25,440,"Previous version reports / studies",f'{prior["prior_reports"]} / {prior["prior_studies"]}'),
                      box(385,440,"Prior reports removed on update",prior["prior_reports_removed_on_update"]),
                      box(745,440,"New reports / studies",f'{prior["new_reports"]} / {prior["new_studies"]}'),
                      box(385,560,"Final included reports / studies",f'{prior["final_reports"]} / {prior["final_studies"]}')))
    h=690 if prior["review_kind"]=="updated" else 440
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="1100" height="'+str(h)+'" viewBox="0 0 1100 '+str(h)+'">'
            '<rect width="1100" height="'+str(h)+'" fill="white"/><text x="25" y="36" font-size="22" font-family="Arial">'
            'Local PRISMA 2020 '+escape(prior["review_kind"])+ ' review accounting</text>'+''.join(parts)+
            '<text x="25" y="'+str(h-18)+'" font-size="13" font-family="Arial">Original ledger diagram; counts depend on user records, not certified coverage or official template.</text></svg>')


def locations(path,document):
    supplied=rows(path,LOCATION_FIELDS,allow_empty=True) if path else []
    by_id={};paragraphs={r["id"] for r in document["paragraphs"]}
    for row in supplied:
        item=row["item_id"];state=row["applicability"]
        if item not in ITEMS or item in by_id or state not in {"reported","not_applicable","pending"}:
            lit.fail("reporting locations need distinct official item IDs and valid state")
        if state=="reported":
            if not nonblank(row["reviewer"]) or not (row["article_paragraph_id"] or row["supplement_section"]):
                lit.fail("reported item needs reviewer and an actual article/supplement locator")
            if row["article_paragraph_id"] and row["article_paragraph_id"] not in paragraphs:lit.fail("unknown article paragraph ID")
            if row["supplement_section"] and row["supplement_section"] not in SECTIONS:lit.fail("unknown supplement section")
        elif state=="not_applicable":
            if not nonblank(row["reviewer"]) or not nonblank(row["rationale"]):lit.fail("not-applicable claim needs reviewer and reason")
        elif row["article_paragraph_id"] or row["supplement_section"]:
            lit.fail("pending item cannot claim a location")
        by_id[item]=row
    candidates={"1":"title","3":"introduction1","4":"methods_pico","5":"methods_eligibility",
                "8":"methods_limits","10a":"methods_analysis","12":"methods_analysis","13d":"methods_analysis",
                "16a":"results_selection","17":"results_evidence","18":"results_review","19":"results_numeric",
                "20b":"results_numeric","20d":"results_sensitivity","23b":"discussion_limits","23c":"discussion_limits",
                "24a":"declarations","25":"declarations","26":"declarations","27":"declarations"}
    section={"6":"search_batches","7":"search_batches","8":"selection","9":"selection",
             "16a":"selection","16b":"excluded_reports","17":"included_studies","24b":"item_locations","27":"item_locations"}
    output=[]
    for item in ITEMS:
        claim=by_id.get(item,{"applicability":"pending","article_paragraph_id":"","supplement_section":"","reviewer":"","rationale":""})
        output.append({"item_id":item,"candidate_article_paragraph":candidates.get(item,"") if candidates.get(item) in paragraphs else "",
                       "candidate_supplement_section":section.get(item,""),"author_applicability_claim":claim["applicability"],
                       "article_paragraph_id":claim["article_paragraph_id"],"supplement_section":claim["supplement_section"],
                       "reviewer":claim["reviewer"],"rationale":claim["rationale"],"automatic_compliance":"false"})
    return output


def append_word_evidence(path, paragraphs):
    """Append bounded plain-text evidence notes to the copied manuscript, without Word COM."""
    with zipfile.ZipFile(path) as archive:
        members=[(item,archive.read(item.filename)) for item in archive.infolist()]
    changed=[]
    for item,data in members:
        if item.filename=="word/document.xml":
            xml=data.decode("utf-8")
            body=re.search(r'<(?P<prefix>[A-Za-z_][\w.-]*:)?body(?:\s|>)',xml)
            if not body:lit.fail("Word body start missing")
            prefix=body.group("prefix") or ""
            marker="<"+prefix+"sectPr"
            at=xml.rfind(marker)
            if at<0:at=xml.rfind("</"+prefix+"body>")
            if at<0:lit.fail("Word body/section end missing")
            added="".join(diagnostic_word.paragraph(line) for line in paragraphs)
            if prefix!="w:":added=added.replace("<w:","<"+prefix).replace("</w:","</"+prefix)
            xml=xml[:at]+added+xml[at:]
            ET.fromstring(xml)
            data=xml.encode("utf-8")
        changed.append((item,data))
    if not any(item.filename=="word/document.xml" for item,_ in changed):lit.fail("Word document XML missing")
    replacement=path.with_name(".article-evidence.docx")
    with zipfile.ZipFile(replacement,"w") as archive:
        for item,data in changed:archive.writestr(item,data)
    with zipfile.ZipFile(replacement) as archive:
        if archive.testzip() is not None:lit.fail("assembled Word archive damaged")
    os.replace(replacement,path)


def checked_evidence(a,method_paper,paper,document,stage):
    """Reverify supplied source products, select only this paper's rows, and retain non-final claims."""
    inventory=[];notes=[];inputs={};family=document.get("method_family","pairwise")
    def record(component,status,source,scope,interpretation):
        source=Path(source).resolve() if source else None
        inventory.append(dict(component=component,status=status,source_receipt=str(source) if source else "",
            source_receipt_sha256=lit.sha256(source) if source else "",scope=scope,interpretation=interpretation))
        if source:inputs[component+"_receipt"]=lit.sha256(source)
    if a.method_sof:
        if not method_paper:lit.fail("method SoF requires a method-specific manuscript")
        import method_sof
        root=Path(a.method_sof).resolve();method_sof.verify(root)
        all_rows=rows(root/"method_sof.csv",method_sof.OUTPUT)
        selected=[r for r in all_rows if r["paper_manifest_sha256"]==lit.sha256(paper/"manifest.json")
                  and r["method"]==document["method_family"]]
        if not selected:lit.fail("method SoF has no rows for this manuscript and method")
        if any((r["certainty_status"]=="synthetic_test")!=document["synthetic"]
               for r in selected if r["certainty_status"]=="synthetic_test"):
            lit.fail("synthetic method SoF cannot bind to a real manuscript")
        fields=method_sof.OUTPUT+(method_sof.RARE_OUTPUT if document["method_family"]=="rare" else ())
        lit.write_csv(stage/"method_sof_bound.csv",fields,selected)
        receipt=root/"method_sof_receipt.json"
        record("method_sof","BOUND_NON_FINAL",receipt,
               document["method_family"]+"; "+str(len(selected))+" metric rows",
               "Reviewer-entered certainty or Agent suggestion; no automatic GRADE judgment")
        notes.append("Method-specific SoF: "+str(len(selected))+" checked metric rows; source receipt "+str(receipt)+
                     " sha256="+lit.sha256(receipt)+". Non-final; Agent suggestions are not reviewer judgments.")
        for r in selected:
            interval=("CI not reported" if r["ci_status"]=="NOT_REPORTED" else
                      "reference, not estimated" if r["ci_status"]=="DEFINITIONAL_REFERENCE_NOT_ESTIMATED" else
                      r["ci_lower"]+" to "+r["ci_upper"])
            notes.append("SoF "+r["outcome_id"]+" / "+r["outcome"]+" at "+r["timepoint"]+
                         "; "+r["metric"]+" = "+r["estimate"]+" ("+interval+") "+r["unit"]+
                         "; studies "+r["studies"]+" ("+r["study_count_scope"]+"); certainty "+
                         r["certainty"]+" ["+r["certainty_status"]+"]; result source "+
                         r["source_result_file"]+" sha256="+r["source_result_sha256"])
            if r["method"]=="rare":
                notes.append("Rare-event "+r["metric"]+": identified "+r["identified_studies"]+
                    ", informative "+r["informative_studies"]+", double-zero/all excluded "+
                    r["double_zero_excluded"]+"/"+r["double_all_excluded"]+"; pooled correction "+
                    r["pooled_zero_correction"]+"; Peto "+r["peto_status"]+"; baseline applicability "+
                    r["baseline_applicability_review"]+" for "+r["baseline_population"]+" at "+r["baseline_timepoint"]+
                    "; sourced comparator risk "+r["baseline_risk_per_1000"]+" per 1000; intervention risk "+
                    (r["intervention_risk_per_1000"]+" per 1000" if r["intervention_risk_per_1000"] else "not computed")+
                    "; source "+r["baseline_evidence"]+"; basis "+r["baseline_applicability_basis"])
    else:record("method_sof","NOT_SUPPORTED_FOR_ROUTE" if family=="pairwise" else "NOT_SUPPLIED",
                None,family,
                "Pairwise uses its bound quality SoF" if family=="pairwise" else
                "No checked method-specific SoF attachment was supplied")
    if a.official_rob:
        if method_paper:lit.fail("external RoB binding currently requires its pairwise quality packet")
        import official_rob_binding as rob
        root=Path(a.official_rob).resolve();rob.verify(root)
        receipt=root/"official_rob_binding_receipt.json";claim=load(receipt)
        quality_receipt=load(Path(claim["quality_dir"])/"quality_receipt.json")
        if Path(quality_receipt["packet_dir"]).resolve()!=Path(a.packet).resolve():
            lit.fail("external RoB binding belongs to another article packet")
        if document["synthetic"]!=(claim["mode"]=="synthetic_test"):
            lit.fail("external RoB binding mode differs from manuscript mode")
        for name in ("official_rob_assessments.csv","official_rob_binding.md","official_rob_binding.docx"):
            shutil.copyfile(root/name,stage/name)
        record("official_rob","BOUND_EXTERNAL_NON_FINAL",receipt,
               str(claim["study_count"])+" reviewed study references; "+claim["outcome"]+" at "+claim["timepoint"],
               "External assessment files self-declared; questionnaire and official algorithm not verified")
        notes.append("External RoB: "+str(claim["study_count"])+" study references for "+claim["outcome"]+
                     " at "+claim["timepoint"]+"; source receipt "+str(receipt)+" sha256="+lit.sha256(receipt)+
                     ". Judgment and file references: official_rob_assessments.csv; not official algorithm output.")
    else:record("official_rob","NOT_LINKABLE_FOR_METHOD_ROUTE" if method_paper else "NOT_SUPPLIED",
                None,document.get("method_family","pairwise"),
                "The pairwise quality-packet RoB binder does not accept method papers; network/rare use method_rob" if method_paper
                else "No externally completed official RoB binding supplied")
    if a.method_rob:
        if not method_paper or family not in {"network","rare"}:
            lit.fail("method RoB binding supports network/rare intervention manuscripts only")
        import method_rob_bridge as method_rob
        root=Path(a.method_rob).resolve();claim=method_rob.verify(root)
        receipt=root/"method_rob_receipt.json"
        if Path(claim["paper_dir"]).resolve()!=paper or claim["paper_manifest_sha256"]!=lit.sha256(paper/"manifest.json") or claim["method"]!=family:
            lit.fail("method RoB binding belongs to another manuscript/method")
        if document["synthetic"]!=(claim["mode"]=="synthetic_test"):
            lit.fail("method RoB binding mode differs from manuscript mode")
        for name in ("method_rob_assessments.csv","method_rob_binding.md","method_rob_binding.docx"):
            shutil.copyfile(root/name,stage/name)
        records=rows(root/"method_rob_assessments.csv",method_rob.official.FIELDS)
        record("method_rob","BOUND_EXTERNAL_NON_FINAL",receipt,
               family+"; "+str(claim["study_count"])+" analyzed study references; "+claim["outcome"]+" at "+claim["timepoint"],
               "Reviewer-supplied external intervention assessments; official questions and algorithms not verified")
        notes.append("External intervention RoB for "+family+": "+str(claim["study_count"])+
                     " study references at "+claim["timepoint"]+"; source receipt "+str(receipt)+
                     " sha256="+lit.sha256(receipt)+". Supplied overall judgments: "+
                     "; ".join(r["study_id"]+" / "+r["record_id"]+" = "+r["overall_judgment"] for r in records)+
                     ". Detailed links: method_rob_assessments.csv; official algorithm not run.")
    else:record("method_rob","NOT_SUPPLIED" if family in {"network","rare"} else "NOT_APPLICABLE_TO_ROUTE",
                None,family,"No method-specific external intervention RoB binding supplied")
    if a.quadas3_binding:
        if not method_paper or document["method_family"]!="diagnostic":
            lit.fail("QUADAS-3 selected-estimate binding requires single-threshold diagnostic manuscript")
        import quadas3_paper_binding as quadas
        root=Path(a.quadas3_binding).resolve();quadas.verify(root)
        receipt=root/"quadas3_paper_receipt.json";claim=load(receipt)
        if Path(claim["paper_dir"]).resolve()!=paper or claim["paper_manifest_sha256"]!=lit.sha256(paper/"manifest.json"):
            lit.fail("QUADAS-3 binding belongs to another diagnostic manuscript")
        if document["synthetic"]!=(claim["status"]=="SYNTHETIC_ESTIMATE_LINKS"):
            lit.fail("QUADAS-3 binding mode differs from manuscript mode")
        for name in ("quadas3_estimate_links.csv","quadas3_paper_binding.md","quadas3_paper_binding.docx"):
            shutil.copyfile(root/name,stage/name)
        shutil.copyfile(Path(claim["quadas_dir"])/"quadas3_judgments.csv",stage/"quadas3_judgments.csv")
        record("quadas3","BOUND_EXTERNAL_NON_FINAL",receipt,
               str(claim["study_count"])+" studies; "+str(claim["estimate_count"])+" selected estimates",
               "Supplied QUADAS-3 judgments; official questions and algorithms not run")
        notes.append("QUADAS-3: "+str(claim["estimate_count"])+" selected estimates from "+
                     str(claim["study_count"])+" studies; source receipt "+str(receipt)+
                     " sha256="+lit.sha256(receipt)+". Threshold/record links: quadas3_estimate_links.csv; "
                     "supplied judgments: quadas3_judgments.csv. Non-final; official scoring not run.")
    else:record("quadas3","NOT_SUPPLIED" if document.get("method_family")=="diagnostic" else "NOT_APPLICABLE_TO_ROUTE",
                None,document.get("method_family","pairwise"),"No matching QUADAS-3 selected-estimate binding supplied")
    lit.write_csv(stage/"evidence_attachment_inventory.csv",EVIDENCE_FIELDS,inventory)
    return inventory,notes,inputs


def build(a):
    manuscript_schema=load(Path(a.manuscript)/"manuscript.json").get("schema")
    method_paper=manuscript_schema in METHOD_SCHEMAS
    if method_paper:
        context,n,source_rows,reason_rows,document,verified,method_counts,method_receipt=recheck_method(a)
    else:
        if not a.packet:lit.fail("pairwise article needs bound report packet")
        context,n,source_rows,reason_rows,document=recheck(a.packet,a.manuscript)
        verified=None;method_counts=None;method_receipt=None
    _,records,dedup,stages,mapping,_,methods,retrieval=flow.validate(context,verified)
    batches_out=batches(a.search_batches,source_rows,rows(context.source_methods,("source_label","source_name","searched_on")))
    prior,history=previous(a.prior_included,mapping)
    if history["review_kind"]=="updated" and not any(r["phase"]=="update" for r in batches_out):
        lit.fail("updated review needs a documented update search batch")
    indexed={r["record_id"]:r for r in records};excluded=[]
    for rid,row in retrieval.items():
        why=(row["reason"] if row["status"]=="not_retrieved" else
             stages[(rid,"full_text")]["reason"] if stages[(rid,"full_text")]["decision"]=="exclude" else "")
        if why:
            r=indexed[rid];excluded.append({"record_id":rid,"title":r["title"],"authors":r["authors"],"year":r["year"],
                              "doi":r["doi"],"pmid":r["pmid"],"stage":"not_retrieved" if row["status"]=="not_retrieved" else "full_text_excluded",
                              "reason":why,"potentially_eligible":"HUMAN_REVIEW_REQUIRED"})
    if len([r for r in excluded if r["stage"]=="full_text_excluded"])!=n["reports_excluded"]:
        lit.fail("excluded report detail differs from flow")
    report_rows=[]
    for sid in sorted({r["study_id"] for r in mapping}):
        m=[r for r in mapping if r["study_id"]==sid]
        report_rows.append({"study_id":sid,"report_count":len(m),"report_ids":"; ".join(r["report_id"] for r in m),
                            "record_ids":"; ".join(r["record_id"] for r in m),
                            "prior_report_count":sum(r["report_id"] in {p["report_id"] for p in prior if p["current_status"]=="retained"} for r in m)})
    item_rows=locations(a.locations,document)
    out=Path(a.out).resolve()
    if out.exists():lit.fail("PRISMA article bundle output exists")
    out.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".prisma-article-",dir=out.parent) as tmp:
        stage=Path(tmp)/"result";stage.mkdir()
        lit.write_csv(stage/"search_batch_counts.csv",list(batches_out[0]),batches_out)
        lit.write_csv(stage/"updated_review_counts.csv",["metric","count"],[{"metric":k,"count":v} for k,v in history.items() if k!="review_kind"])
        lit.write_csv(stage/"prior_review_reconciliation.csv",PRIOR_FIELDS,prior)
        lit.write_csv(stage/"excluded_reports.csv",["record_id","title","authors","year","doi","pmid","stage","reason","potentially_eligible"],excluded)
        lit.write_csv(stage/"included_study_reports.csv",["study_id","report_count","report_ids","record_ids","prior_report_count"],report_rows)
        lit.write_csv(stage/"prisma_item_locations.csv",list(item_rows[0]),item_rows)
        (stage/"prisma_accounting.svg").write_text(svg(n,history),encoding="utf-8")
        for name,source in (("article_draft.docx",Path(a.manuscript)/"manuscript.docx"),("article_draft.md",Path(a.manuscript)/"manuscript.md")):
            shutil.copyfile(source,stage/name)
        evidence_inventory,evidence_notes,evidence_inputs=checked_evidence(
            a,method_paper,Path(a.manuscript).resolve(),document,stage)
        evidence_status=[r["component"]+": "+r["status"]+". "+r["interpretation"]
                         for r in evidence_inventory]
        append_word_evidence(stage/"article_draft.docx",
            ["Evidence and certainty attachments (draft; author review required)",*evidence_status,*evidence_notes])
        with (stage/"article_draft.md").open("a",encoding="utf-8") as file:
            file.write("\n## Evidence and certainty attachments (draft; author review required)\n\n"+
                       "\n\n".join([*evidence_status,*evidence_notes])+"\n")
        if method_paper:
            for name,source in (("method_selection_counts.json",Path(a.manuscript)/"selection_counts.json"),
                                ("method_analysis_plan.json",Path(a.manuscript)/"analysis_plan.json"),
                                ("method_statistics_receipt.json",method_receipt)):
                shutil.copyfile(source,stage/name)
            (stage/"selection_flow_original.svg").write_text(flow.diagram(n),encoding="utf-8")
            lit.write_csv(stage/"selection_flow_counts.csv",["unit","metric","count"],
                [{"unit":"study" if key=="included_studies" else "report" if key.startswith("report") or key in {"retrieval_pending","assessment_pending","included_reports"} else "record",
                  "metric":key,"count":value} for key,value in n.items()])
            lit.write_csv(stage/"selection_reason_counts.csv",["stage","reason","report_count"],reason_rows)
        else:
            for name,source in (("selection_flow_original.svg",Path(a.packet)/"prisma_flow.svg"),
                                ("selection_flow_counts.csv",Path(a.packet)/"prisma_flow_counts.csv"),
                                ("selection_reason_counts.csv",Path(a.packet)/"reason_counts.csv")):
                shutil.copyfile(source,stage/name)
        def md_table(data,keys):
            return " | ".join(keys)+"\n"+" | ".join("---" for _ in keys)+"\n"+"\n".join(" | ".join(str(r.get(k,"")).replace("|","/").replace("\n"," ") for k in keys) for r in data)
        lines=["# PRISMA 2020 local reporting supplement (draft)","",
               "This is an original local accounting/locator supplement, not the official template or an automatic PRISMA compliance certificate. Source coverage, eligibility, original-article interpretation and author reporting decisions require review.","",
               "Official checklist: "+flow.OFFICIAL_CHECKLIST,"Official flow formats: "+flow.OFFICIAL_FLOW,
               "Checklist/flow attribution: Page MJ et al. BMJ 2021;372:n71. DOI 10.1136/bmj.n71. CC BY 4.0.","",
               "## search_batches","",md_table(batches_out,("batch_id","source_label","phase","update_of","search_date","identified_records","removed_duplicates","reports_sought","included_reports","query_reference","status")),"",
               "Search batch status and query references are user-entered. A strategy reference is not a complete query or authenticated database response.","",
               "## selection","",f"Current identified records {n['identified_records']}; duplicate removals {n['removed_duplicates']}; other pre-screen removals {n['removed_other']}; screened {n['screened_records']}; reports sought {n['reports_sought']}; not retrieved {n['reports_not_retrieved']}; retrieval pending {n['retrieval_pending']}; assessed {n['reports_assessed']}; excluded at full text {n['reports_excluded']}; current included reports {n['included_reports']}; distinct studies {n['included_studies']}.","",
               "Previous-version reports/studies: "+str(history["prior_reports"])+" / "+str(history["prior_studies"])+". Removed on update: "+str(history["prior_reports_removed_on_update"])+" reports / "+str(history["prior_studies_removed_on_update"])+" studies. New included reports/studies: "+str(history["new_reports"])+" / "+str(history["new_studies"])+". Final included reports/studies: "+str(history["final_reports"])+" / "+str(history["final_studies"])+". Multiple reports of one study are not multiple studies.","",
               "See `prisma_accounting.svg` and `selection_flow_original.svg`; both are locally generated, not official template copies. Updates here require prior retained reports to remain in the current mapping; removed prior reports require a reason.","",
               "## prior_review","",md_table(prior,("study_id","report_id","current_status","change_reason","source_reference")) if prior else "New review: no previous-version included reports were supplied.","",
               "## excluded_reports","",md_table(excluded,("record_id","title","year","stage","reason","potentially_eligible")) if excluded else "No retrieved full-text exclusions or nonretrievals in this local ledger.","",
               "Potentially eligible exclusions under PRISMA item 16b must be identified by an author; this table preserves all such candidates without inventing a judgment.","",
               "## included_studies","",md_table(report_rows,("study_id","report_count","report_ids","record_ids","prior_report_count")),"",
               "## item_locations","","Forty-two checklist item/subitem IDs are mapped to actual manuscript paragraph IDs or supplement sections only where supported. Pending items and candidates are not reported/compliant claims. See `prisma_item_locations.csv` for each author decision and missing location.","",
               "Unresolved items: "+", ".join(r["item_id"] for r in item_rows if r["author_applicability_claim"]=="pending")+"."]
        lines.extend(("", "## Evidence and certainty attachment inventory", "",
            md_table(evidence_inventory,("component","status","scope","interpretation")), "",
            "Bound entries are copied or selected from checked local receipts; absent entries are not implied to have been assessed. Exact source receipt paths/hashes are in `evidence_attachment_inventory.csv`. The article draft includes the bounded summary; official algorithms and clinical judgments were not recomputed.", ""))
        if evidence_notes:lines.extend(evidence_notes)
        if method_paper:
            lines.extend(("", "## Method-specific units and applicability", "",
                "Method family: `"+document["method_family"]+"`. The selection flow counts records, reports and distinct studies. It does not count diagnostic cutoff rows, network contrasts, dose categories, event denominators, or dependent effects as additional studies.",
                "The original `method_selection_counts.json`, analysis plan and statistics receipt are attached separately; method-specific units remain as recorded by that method. No participant totals or searches are inferred from them.",
                "Standard PRISMA 2020 item IDs are navigation aids. Diagnostic accuracy, network, dose-response, single-group and related-effect reporting may need method-specific extensions and author applicability decisions; this bundle does not certify those extensions."))
        (stage/"article_supplement.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
        receipt={"schema":"meta-prisma-article-bundle-v1","review_kind":history["review_kind"],"method_family":document.get("method_family","pairwise"),"status":"DRAFT_SYNTHETIC" if document["synthetic"] else "DRAFT_AUTHOR_REVIEW_REQUIRED",
                 "automatic_prisma_compliance":False,"real_search_authenticated":False,"human_item_review_pending":sum(r["author_applicability_claim"]=="pending" for r in item_rows),
                 "input_sha256":{name:lit.sha256(path) for name,path in (("paper_manifest",Path(a.manuscript)/"manifest.json"),("search_batches",a.search_batches))},
                 "output_sha256":{p.name:lit.sha256(p) for p in stage.iterdir() if p.is_file()}}
        if method_paper:
            receipt["input_sha256"].update({"method_confirmation":lit.sha256(a.confirmation),
                "source_methods":lit.sha256(a.source_methods),"retrieval":lit.sha256(a.retrieval)})
        else:receipt["input_sha256"]["packet_manifest"]=lit.sha256(Path(a.packet)/"report_manifest.csv")
        if a.prior_included:receipt["input_sha256"]["prior_included"]=lit.sha256(a.prior_included)
        if a.locations:receipt["input_sha256"]["locations"]=lit.sha256(a.locations)
        receipt["input_sha256"].update(evidence_inputs)
        receipt["evidence_attachment_status"]={r["component"]:r["status"] for r in evidence_inventory}
        (stage/"prisma_bundle_receipt.json").write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        os.replace(stage,out)
    print(receipt["status"],history["review_kind"],n["included_reports"],"reports",n["included_studies"],"studies",out)


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    for key in ("packet","confirmation","source_methods","retrieval","manuscript","search_batches","out"):
        p.add_argument("--"+key.replace("_","-"),required=key in {"manuscript","search_batches","out"})
    p.add_argument("--prior-included");p.add_argument("--locations")
    p.add_argument("--method-sof");p.add_argument("--official-rob");p.add_argument("--method-rob");p.add_argument("--quadas3-binding")
    a=p.parse_args()
    try:build(a)
    except (OSError,ValueError,KeyError,TypeError,json.JSONDecodeError,csv.Error,zipfile.BadZipFile) as error:p.exit(2,f"Validation: {error}\n")
