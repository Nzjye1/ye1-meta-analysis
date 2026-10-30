"""Evidence-bound English IMRaD draft and Word export with explicit revision history."""
import argparse
import csv
import datetime as dt
import difflib
import json
import os
from pathlib import Path
import tempfile
import zipfile
import shutil
import struct
from collections import Counter
from types import SimpleNamespace
import report as evidence_report
import subprocess
from environment_check import resolve_r
from xml.sax.saxutils import escape
import literature as lit

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def text_run(text):
    return '<w:r><w:t xml:space="preserve">' + escape(str(text)) + '</w:t></w:r>'


def docx(path, document, prior=None):
    paragraphs = []
    before = {p["id"]: p["text"] for p in (prior or {}).get("paragraphs", [])}
    for number,p in enumerate(document["paragraphs"],1):
        style = p.get("style", "Normal")
        body = text_run(p["text"])
        if p["id"] in before and before[p["id"]] != p["text"]:
            body = ('<w:del w:id="'+str(number*2)+'" w:author="' + escape(document["revision"]["reviewer"], {'"': '&quot;'}) +
                    '" w:date="' + document["revision"]["date"] + '"><w:r><w:delText>' +
                    escape(before[p["id"]]) + '</w:delText></w:r></w:del>' +
                    '<w:ins w:id="'+str(number*2+1)+'" w:author="' + escape(document["revision"]["reviewer"], {'"': '&quot;'}) +
                    '" w:date="' + document["revision"]["date"] + '">' + body + '</w:ins>')
        paragraphs.append('<w:p><w:pPr><w:pStyle w:val="' + style + '"/></w:pPr>' + body + '</w:p>')
    for table in document.get("tables",[]):
        paragraphs.append('<w:p><w:pPr><w:keepNext/></w:pPr>'+text_run(table["title"])+ '</w:p><w:tbl><w:tblPr><w:tblBorders>'+''.join('<w:'+edge+' w:val="single" w:sz="4"/>' for edge in ("top","left","bottom","right","insideH","insideV"))+'</w:tblBorders></w:tblPr>'+''.join('<w:tr><w:trPr><w:cantSplit/>'+('<w:tblHeader/>' if i==0 else '')+'</w:trPr>'+''.join('<w:tc><w:p>'+text_run(cell)+'</w:p></w:tc>' for cell in row)+'</w:tr>' for i,row in enumerate(table["rows"]))+ '</w:tbl>')
    image_path=document.get("attachments",{}).get("forest.png")
    if image_path:
        raw=Path(image_path).read_bytes()
        if raw[:8]!=b'\x89PNG\r\n\x1a\n':lit.fail("forest image is not PNG")
        width,height=struct.unpack('>II',raw[16:24]);cx=5500000;cy=int(cx*height/width)
        if cy>6500000:cx=int(cx*6500000/cy);cy=6500000
        paragraphs.append('<w:p><w:pPr><w:keepNext/></w:pPr>'+text_run('Figure 1 Forest plot drawn from the bound statistical values')+'</w:p><w:p><w:pPr><w:keepLines/></w:pPr><w:r><w:drawing><wp:inline xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"><wp:extent cx="'+str(cx)+'" cy="'+str(cy)+'"/><wp:docPr id="1" name="Forest plot"/><a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:nvPicPr><pic:cNvPr id="0" name="forest.png"/><pic:cNvPicPr/></pic:nvPicPr><pic:blipFill><a:blip xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" r:embed="forest"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill><pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="'+str(cx)+'" cy="'+str(cy)+'"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>')
    xml = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="' + W + '"><w:body>' + ''.join(paragraphs) + '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1134" w:bottom="1134" w:left="1134" w:right="1134"/></w:sectPr></w:body></w:document>'
    styles = ('<w:styles xmlns:w="' + W + '"><w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/><w:sz w:val="22"/><w:color w:val="000000"/></w:rPr></w:rPrDefault><w:pPrDefault><w:pPr><w:spacing w:after="120" w:line="276" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>' +
        ''.join('<w:style w:type="paragraph" w:styleId="'+name+'"><w:name w:val="'+name+'"/><w:rPr><w:b/><w:sz w:val="'+size+'"/><w:color w:val="000000"/></w:rPr></w:style>' for name,size in (("Title","34"),("Heading1","28"))) + '</w:styles>')
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="png" ContentType="image/png"/><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/><Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/></Types>')
        z.writestr("_rels/.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        z.writestr("word/_rels/document.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="styles" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'+('<Relationship Id="forest" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/forest.png"/>' if image_path else '')+'</Relationships>')
        z.writestr("word/document.xml", xml); z.writestr("word/styles.xml", styles)
        if image_path:z.write(image_path,"word/media/forest.png")


def write_output(target, document, prior=None):
    final = Path(target)
    if final.exists(): lit.fail("output already exists")
    final.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".manuscript-", dir=final.parent) as tmp:
        stage = Path(tmp)/"result"; stage.mkdir()
        (stage/"manuscript.json").write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
        (stage/"manuscript.md").write_text("\n\n".join(("# " if p.get("style")=="Title" else "## " if p.get("style")=="Heading1" else "")+p["text"] for p in document["paragraphs"]), encoding="utf-8")
        for name,path in document.get("attachments",{}).items():
            if Path(name).name!=name:lit.fail("invalid attachment name")
            shutil.copyfile(path,stage/name)
        presentation=json.loads(json.dumps(document))
        renderer=Path(__file__).with_name("render_forest.R")
        if document.get("presentation"):
            settings=document["presentation"]
            process=subprocess.run([settings["rscript"],str(renderer),str(stage/"study_effects_trace.csv"),
                str(stage/"pooled_result.csv"),str(stage/"forest_display.png"),settings["unit"],
                settings["direction"],"SYNTHETIC DATA" if document["synthetic"] else "Review draft"],capture_output=True,text=True)
            if process.returncode:lit.fail("presentation-only forest rendering failed: "+process.stderr)
            presentation["attachments"]["forest.png"]=str(stage/"forest_display.png")
            (stage/"figure_provenance.json").write_text(json.dumps(dict(renderer_sha256=lit.sha256(renderer),
                source_trace_sha256=lit.sha256(stage/"study_effects_trace.csv"),pooled_sha256=lit.sha256(stage/"pooled_result.csv"),
                display_sha256=lit.sha256(stage/"forest_display.png"),model_refitted=False),indent=2),encoding="utf-8")
        docx(stage/"manuscript.docx", presentation)
        if prior:
            docx(stage/"tracked_changes.docx", presentation, prior)
            (stage/"revision.diff").write_text("\n".join(difflib.unified_diff(
                [p["text"] for p in prior["paragraphs"]], [p["text"] for p in document["paragraphs"]],
                fromfile="prior", tofile="revised")), encoding="utf-8")
        (stage/"status.json").write_text(json.dumps(dict(status="DRAFT_SYNTHETIC" if document["synthetic"] else "DRAFT_FOR_HUMAN_REVIEW",
            final=False, source_semantics_verified=False, word_render_verified=False,
            pending_claims=sum(p.get("review_status")=="pending" for p in document["paragraphs"])), indent=2), encoding="utf-8")
        (stage/"manifest.json").write_text(json.dumps({p.name:lit.sha256(p) for p in stage.iterdir()}, indent=2), encoding="utf-8")
        os.replace(stage, final)


def build(a):
    packet, stats = Path(a.packet), Path(a.stats)
    if not (packet/"report_inputs.json").is_file():lit.fail("packet requires fresh report_inputs.json; regenerate evidence report")
    context=read(packet/"report_inputs.json")
    # Recompute from confirmed original inputs, not hashes asserted by a changed output table.
    with tempfile.TemporaryDirectory(prefix=".paper-recheck-",dir=packet.parent) as temp:
        checked=Path(temp)/"packet"
        evidence_report.assemble(SimpleNamespace(**context,out=str(checked)))
        for path in checked.iterdir():
            if path.name=="report_inputs.json":continue
            if not (packet/path.name).is_file() or lit.sha256(path)!=lit.sha256(packet/path.name):
                lit.fail("evidence packet artifact differs from confirmed source recomputation: "+path.name)
    status = read(packet/"report_status.json")
    manifest = dict((r["key"],r["value"]) for r in lit.read_csv(packet/"report_manifest.csv", ["key","value"])[0])
    run = read(stats/"protocol_run_receipt.json")
    if status["confirmation_mode"]!=run["mode"]:lit.fail("packet/run mode mismatch")
    for key,path in (("protocol",a.protocol),("records",a.records),("pooled_result",stats/"pooled_result.csv")):
        if manifest.get(key+"_sha256") != lit.sha256(path): lit.fail("packet input changed: "+key)
    if manifest.get("confirmation_sha256") != run["confirmation_sha256"]:
        lit.fail("packet and statistical run use different confirmations")
    for name,digest in run["result_sha256"].items():
        if Path(name).name != name or lit.sha256(stats/name) != digest: lit.fail("statistical output changed")
    protocol = read(a.protocol); narrative=read(a.narrative)
    synthetic = status["confirmation_mode"] == "synthetic_test"
    records = {r["record_id"]:r for r in lit.read_csv(a.records,["record_id","title","authors","year"])[0]}
    paragraphs = []; refs = []
    def add(pid,text,style="Normal",**extra): paragraphs.append(dict(id=pid,text=str(text),style=style,**extra))
    add("title", narrative.get("title", protocol["question"]), "Title")
    add("draft", "SYNTHETIC DEVELOPMENT DRAFT No real article review is claimed." if synthetic else
        "DRAFT FOR HUMAN REVIEW Source claims, literature interpretation and conclusions require verification.")
    for section in ("Introduction","Discussion"):
        if not isinstance(narrative.get(section),list) or not narrative[section]: lit.fail(section+" paragraphs required")
    add("introduction_heading","Introduction","Heading1")
    def narrative_section(section,require_sources=True):
        for i,row in enumerate(narrative[section]):
            if not row.get("text") or row.get("review_status") not in {"pending","human_verified","synthetic_test"}:
                lit.fail("narrative text and explicit review_status required")
            ids=row.get("record_ids",[])
            if any(rid not in records for rid in ids): lit.fail("unknown reference record ID")
            if not synthetic and ((require_sources and not ids) or not row.get("source_locator")): lit.fail("real narrative needs existing reference IDs and source locator")
            if not synthetic and row["review_status"]=="synthetic_test": lit.fail("synthetic status in real narrative")
            cite=[]
            for rid in ids:
                if rid not in refs: refs.append(rid)
                cite.append(str(refs.index(rid)+1))
            add(section.lower()+str(i+1), row["text"]+(" ["+", ".join(cite)+"]" if cite and not synthetic else ""),
                record_ids=ids, source_locator=row.get("source_locator",""), review_status=row["review_status"])
    narrative_section("Introduction")
    add("methods_heading","Methods","Heading1")
    add("methods_pico", "The planned question was: "+protocol["question"]+" Population: "+protocol["pico"]["population"]+
        ". Intervention or exposure: "+protocol["pico"]["intervention"]+". Comparator: "+protocol["pico"]["comparator"]+".")
    add("methods_eligibility", "Eligible designs: "+"; ".join(protocol["eligible_designs"])+". Inclusion criteria: "+"; ".join(protocol["inclusion_criteria"])+". Exclusion criteria: "+"; ".join(protocol["exclusion_criteria"])+".")
    plan=protocol["analysis"]
    add("methods_analysis", "The analysis used "+("a fixed-effect inverse-variance model" if plan["model"]=="FE" else "a random-effects model with REML heterogeneity estimation")+f", a {plan['test']} test and {100*(1-float(plan['alpha'])):g}% confidence intervals. The outcome was "+protocol["outcome"]["name"]+" at "+protocol["outcome"]["timepoint"]+". Effect direction: "+protocol["outcome"]["direction"]+". Planned sensitivity: "+"; ".join(protocol["sensitivity_plan"])+".")
    add("methods_limits", "Search, selection, extraction and risk of bias were recorded in the accompanying evidence packet. These records do not establish comprehensive searching, independent reviewer agreement or original-source correctness. "+
        "Packet status: "+status["status"]+". See report.md and the source and risk-of-bias audit tables for actual unresolved statuses.")
    for paragraph in paragraphs:
        if paragraph["id"].startswith("methods_") and paragraph["style"]!="Heading1":paragraph["locked_fact"]=True
    if narrative.get("Methods"):narrative_section("Methods",require_sources=False)
    add("results_heading","Results","Heading1")
    flow_path=packet/"prisma_flow_counts.csv"
    if flow_path.is_file():
        counts={r["metric"]:r["count"] for r in lit.read_csv(flow_path,["metric","count"])[0]}
        add("results_selection", f"The local selection ledger contained {counts['identified_records']} identified records, {counts['removed_duplicates']} duplicate removals and {counts['removed_other']} other pre-screen removals. There were {counts['reports_sought']} reports sought, {counts['reports_not_retrieved']} not retrieved, {counts['reports_assessed']} assessed, {counts['reports_excluded']} excluded after assessment, and {counts['included_reports']} included reports corresponding to {counts['included_studies']} unique studies. Retrieval pending: {counts['retrieval_pending']}; assessment pending: {counts['assessment_pending']}.",locked_fact=True)
    source_states=Counter(r["status"] for r in lit.read_csv(packet/"source_verification_audit.csv",["status"])[0])
    rob_states=Counter(r["status"] for r in lit.read_csv(packet/"risk_of_bias_audit.csv",["status"])[0])
    def status_sentence(counts):return "; ".join(str(n)+" "+name.replace("_"," ")+" entries" for name,n in sorted(counts.items()))
    add("results_review", "Source review contained "+status_sentence(source_states)+". Risk-of-bias records contained "+status_sentence(rob_states)+". These are recorded review statuses, not independent verification of source reading or bias judgments.",locked_fact=True)
    result=lit.read_csv(stats/"pooled_result.csv",["k","effect_type","pooled","ci_lower","ci_upper","alpha","Q","I2_percent","tau2"])[0][0]
    unit=getattr(a,"unit",None) or protocol["outcome"].get("unit","")
    add("results_numeric", f"The synthesis contained {result['k']} effect estimates. The pooled {result['effect_type']} was {float(result['pooled']):.2f}{(' '+unit) if unit else ''} ({100*(1-float(result['alpha'])):g}% CI {float(result['ci_lower']):.2f} to {float(result['ci_upper']):.2f}). Q was {float(result['Q']):.2f} and I2 was {float(result['I2_percent']):.1f}%. "+("Between-study variance tau2 was constrained to zero by the fixed-effect model; it was not estimated." if result["model"]=="FE" else f"Estimated tau2 was {float(result['tau2']):.3g}."), locked_fact=True)
    if (stats/"leave_one_out.csv").is_file():
        loo=lit.read_csv(stats/"leave_one_out.csv",["pooled","ci_lower","ci_upper"])[0]
        vals=[float(r["pooled"]) for r in loo]
        add("results_sensitivity",f"Leave-one-study-out pooled estimates ranged from {min(vals):.2f} to {max(vals):.2f}{(' '+unit) if unit else ''}. Across these analyses, the confidence interval limits ranged from {min(float(r['ci_lower']) for r in loo):.2f} to {max(float(r['ci_upper']) for r in loo):.2f}. Individual omissions and intervals are retained in leave_one_out.csv.",locked_fact=True)
    add("results_evidence", "Study characteristics and report mappings are in included_studies.csv; source verification and risk-of-bias judgments remain as recorded in their audit tables. Forest and sensitivity outputs are in the accompanying statistical directory. No clinical conclusion follows automatically from these numerical results.")
    add("discussion_heading","Discussion","Heading1"); narrative_section("Discussion")
    add("discussion_limits", "Limitations include the review and source-verification statuses recorded in the evidence packet. Interpretation, certainty of evidence, reporting bias and implications require researcher review; they were not inferred from a pooled p value.")
    add("declarations_heading","Declarations","Heading1")
    add("declarations", narrative.get("declarations", "PENDING Registration, protocol amendments, funding, conflicts of interest, author contributions and data availability must be supplied by the authors."))
    add("references_heading","References","Heading1")
    if synthetic: add("references_synthetic","Synthetic fixture metadata are not real references. No references are generated for this demonstration.")
    else:
        for i,rid in enumerate(refs,1):
            r=records[rid]
            add("reference_"+rid, f"[{i}] {r['authors']}. {r['title']}. {r['year']}."+
                (" DOI "+r["doi"] if r.get("doi") else "")+(" PMID "+r["pmid"] if r.get("pmid") else ""))
    included=lit.read_csv(packet/"included_studies.csv",["study_id","report_count","effect_rows"])[0]
    document=dict(schema="meta-manuscript-v1",synthetic=synthetic,paragraphs=paragraphs,
        tables=[dict(title="Table 1 Included study report mapping",rows=[["Study","Reports","Effects"]]+[[r["study_id"],r["report_count"],r["effect_rows"]] for r in included])],
        attachments={name:str((stats/name).resolve()) for name in ("forest.png","study_effects_trace.csv","pooled_result.csv")},
        source_sha256={str(Path(p).resolve()):lit.sha256(p) for p in (a.protocol,a.records,a.narrative,packet/"report_manifest.csv",stats/"protocol_run_receipt.json")},
        revision_history=[])
    for name in ("included_studies.csv","source_verification_audit.csv","risk_of_bias_audit.csv",
                 "prisma_flow.svg","prisma_flow_counts.csv","report.md"):
        if (packet/name).is_file():document["attachments"][name]=str((packet/name).resolve())
    if (stats/"leave_one_out.csv").is_file():document["attachments"]["leave_one_out.csv"]=str((stats/"leave_one_out.csv").resolve())
    binary=resolve_r(getattr(a,"rscript",None))
    if not binary or not Path(binary).is_file():lit.fail("forest display needs native Rscript: supply --rscript or META_RSCRIPT")
    document["presentation"]=dict(rscript=binary,unit=unit,direction=protocol["outcome"]["direction"])
    document["attachment_sha256"]={name:lit.sha256(path) for name,path in document["attachments"].items()}
    if narrative.get("study_characteristics"):
        known={r["study_id"] for r in included}; seen=set(); table=[]
        for row in narrative["study_characteristics"]:
            if row["study_id"] not in known or row["study_id"] in seen:lit.fail("unknown/repeated study characteristics ID")
            seen.add(row["study_id"])
            table.append([row["study_id"],row["design"],str(row["n_intervention"]),str(row["n_control"]),row["followup"]])
        document["tables"].append(dict(title="Table 2 Author supplied study characteristics pending source review",rows=[["Study","Design","Intervention n","Control n","Follow up"]]+table))
    write_output(a.out,document)


def revise(a):
    document=read(a.input); changes=read(a.changes); prior=read(a.input)
    for path,digest in document["source_sha256"].items():
        if lit.sha256(path)!=digest:lit.fail("manuscript source changed; rebuild before revision")
    for name,path in document.get("attachments",{}).items():
        if lit.sha256(path)!=document["attachment_sha256"][name]:lit.fail("manuscript figure/table source changed")
    if changes.get("prior_sha256")!=lit.sha256(a.input) or not changes.get("reviewer") or not changes.get("reason"):
        lit.fail("revision requires matching prior_sha256, reviewer and reason")
    by_id={p["id"]:p for p in document["paragraphs"]}; seen=set()
    for edit in changes.get("edits",[]):
        pid=edit["id"]
        if pid not in by_id or pid in seen or not edit.get("text"): lit.fail("invalid/repeated paragraph edit")
        if by_id[pid].get("locked_fact") or pid.startswith("reference_"): lit.fail("recompute evidence or reference metadata before editing locked facts/references")
        by_id[pid]["text"]=edit["text"]; by_id[pid]["review_status"]="pending"; seen.add(pid)
    if not seen: lit.fail("no revision edits")
    document["revision"]=dict(reviewer=changes["reviewer"],reason=changes["reason"],date=dt.datetime.now(dt.timezone.utc).isoformat(),prior_sha256=lit.sha256(a.input))
    document["revision_history"].append(document["revision"])
    write_output(a.out,document,prior)


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__); sub=p.add_subparsers(dest="command",required=True)
    b=sub.add_parser("build")
    for key in ("packet","stats","protocol","records","narrative","out"): b.add_argument("--"+key,required=True)
    b.add_argument("--rscript");b.add_argument("--unit")
    b.set_defaults(func=build); r=sub.add_parser("revise")
    for key in ("input","changes","out"): r.add_argument("--"+key,required=True)
    r.set_defaults(func=revise); a=p.parse_args()
    try: a.func(a)
    except (OSError,ValueError,KeyError,TypeError) as e:p.exit(2,f"Validation: {e}\n")
