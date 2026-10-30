"""Rare-event protocol/source confirmation and evidence-bound MH/Peto Word draft."""
import argparse
import csv
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from types import SimpleNamespace

import diagnostic_project as shared
import diagnostic_word
import literature as lit
import rare_events

CORE=("protocol","records","dedup","decisions","report_map","input","study_review")
REVIEW_FIELDS=("study_id","record_id","review_status","reviewer","reviewed_at","risk_tool",
               "risk_judgment","risk_basis","source_file","source_sha256","source_location")


def protocol(path):
    p=shared.read_json(path)
    if p.get("schema")!="meta-rare-event-project-v1" or p.get("mode") not in {"synthetic_test","real"}:
        lit.fail("invalid rare-event project schema/mode")
    for key in ("project_id","question","search_status"):
        if not shared.nonblank(p.get(key)):lit.fail("rare-event protocol needs "+key)
    pico=p.get("pico",{})
    for key in ("population","intervention","comparator","outcome","timepoint"):
        if not shared.nonblank(pico.get(key)):lit.fail("rare-event PICO needs "+key)
    if not isinstance(p.get("eligible_designs"),list) or not p["eligible_designs"]:
        lit.fail("eligible designs required")
    analysis=p.get("analysis",{})
    p["analysis"]=analysis=rare_events.checked_plan_data(analysis)
    if any(analysis[k]!=pico[k] for k in ("population","outcome","timepoint")) or \
            analysis["contrast"]!=pico["intervention"]+" vs "+pico["comparator"]:
        lit.fail("rare-event PICO and analysis disagree")
    if p["mode"]=="real":
        if analysis["source_kind"]!="reviewed_extraction" or p["search_status"]=="complete_verified_by_software":
            lit.fail("real rare-event project needs reviewed extraction and cannot claim software-verified complete search")
        approval=p.get("approval",{})
        if any(not shared.nonblank(approval.get(k)) for k in ("reviewer","reference","date","declaration")):
            lit.fail("real protocol needs actual human approval claim")
        shared.date(approval["date"])
    elif analysis["source_kind"]!="synthetic_fixture":lit.fail("synthetic project needs synthetic inputs")
    return p


def checked(a):
    p=protocol(a.protocol)
    from dual_screen import verify_if_marked
    verify_if_marked(a.records,a.dedup,a.decisions)
    records,_=lit.read_csv(a.records,("record_id","title","authors","year","doi","pmid"))
    if len({r["record_id"] for r in records})!=len(records):lit.fail("repeated bibliographic ID")
    dedup=lit.load_dedup(records,a.dedup)
    active={rid for rid,r in dedup.items() if r["disposition"]=="keep"}
    decisions,_=lit.read_csv(a.decisions,("record_id","stage","decision","reason","reviewer","decision_date"))
    _,included=lit.validate_screening(records,decisions,active)
    mapping,_=lit.read_csv(a.report_map,("record_id","report_id","study_id"))
    if len(mapping)!=len(included) or {r["record_id"] for r in mapping}!=included or \
            len({r["report_id"] for r in mapping})!=len(mapping):
        lit.fail("rare-event report map needs each included report once")
    by_record={r["record_id"]:r["study_id"] for r in mapping}
    rows=rare_events.checked_data(a.input,p["analysis"])
    if {r["study_id"] for r in rows}!={m["study_id"] for m in mapping} or \
            any(r["record_id"] not in by_record or by_record[r["record_id"]]!=r["study_id"] for r in rows):
        lit.fail("rare-event analyzed studies/reports differ from included mapping")
    reviews,_=lit.read_csv(a.study_review,REVIEW_FIELDS)
    if len(reviews)!=len(rows) or {r["study_id"] for r in reviews}!={r["study_id"] for r in rows}:
        lit.fail("one source/risk review row per analyzed study required")
    by_study={r["study_id"]:r for r in rows}
    status="human_reviewed_claim" if p["mode"]=="real" else "synthetic_test"
    for r in reviews:
        raw=by_study[r["study_id"]]
        if r["record_id"]!=raw["record_id"] or any(r[k]!=raw[k] for k in ("source_file","source_sha256","source_location")):
            lit.fail("rare-event review source/report differs from statistical input")
        if r["review_status"]!=status or any(not shared.nonblank(r[k]) for k in ("reviewer","risk_tool","risk_basis")) or \
                r["risk_judgment"] not in {"low","some_concerns","high","unclear"}:
            lit.fail("risk review status, evidence or reviewer incomplete")
        shared.date(r["reviewed_at"])
        if p["mode"]=="real" and not re.search(r"(?i)(page|p\.|table|figure)\s*[A-Za-z0-9]",r["risk_basis"]):
            lit.fail("real risk basis needs original page/table locator")
    return p,records,dedup,included,mapping,rows,reviews


def hashes(a,rows):
    result={key:lit.sha256(getattr(a,key)) for key in CORE}
    for name in ("rare_events.py","rare_events.R","rare_event_project.py","diagnostic_word.py"):
        result[name]=lit.sha256(Path(__file__).with_name(name))
    result["source_bytes"]={str(Path(r["source_file"]).resolve()):r["source_sha256"] for r in rows}
    return result


def confirm(a):
    p,_,_,_,_,rows,_=checked(a)
    out=Path(a.out).resolve()
    if out.exists():lit.fail("rare-event confirmation output exists")
    out.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".rare-confirm-",dir=out.parent) as temp:
        stage=Path(temp)/"result";stage.mkdir()
        receipt=dict(schema="meta-rare-event-confirmation-v1",mode=p["mode"],
            status="SYNTHETIC_TEST_CONFIRMATION" if p["mode"]=="synthetic_test" else "HUMAN_APPROVAL_CLAIM_FILE_CONSISTENCY",
            approval=p.get("approval",{}),input_paths={k:str(Path(getattr(a,k)).resolve()) for k in CORE},
            hashes=hashes(a,rows),human_identity_authenticated=False,original_extraction_verified_by_software=False,final=False)
        (stage/"rare_confirmation.json").write_text(json.dumps(receipt,indent=2)+"\n",encoding="utf-8")
        os.replace(stage,out)
    print(receipt["status"],out)


def build(a):
    p,records,dedup,included,mapping,rows,reviews=checked(a)
    confirmation=Path(a.confirmation)/"rare_confirmation.json"
    receipt=shared.read_json(confirmation)
    if receipt.get("schema")!="meta-rare-event-confirmation-v1" or receipt.get("mode")!=p["mode"] or \
            receipt.get("input_paths")!={k:str(Path(getattr(a,k)).resolve()) for k in CORE} or \
            receipt.get("hashes")!=hashes(a,rows):
        lit.fail("rare-event confirmation stale or invalid")
    narrative=shared.narrative_check(a.narrative,records,p["mode"])
    out=Path(a.out).resolve()
    if out.exists():lit.fail("rare-event manuscript output exists")
    out.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".rare-paper-",dir=out.parent) as temp:
        stage=Path(temp)/"result";stage.mkdir();stats=stage/"statistics"
        plan=stage/"analysis_plan.json";plan.write_text(json.dumps(p["analysis"],indent=2)+"\n",encoding="utf-8")
        rare_events.run(SimpleNamespace(input=a.input,plan=str(plan),rscript=a.rscript,out=str(stats)))
        summary=lit.read_csv(stats/"rare_summary.csv",("mh_ratio","mh_ci_lower","mh_ci_upper","k_informative","peto_status"))[0][0]
        trace=lit.read_csv(stats/"study_trace.csv",("study_id","events_t","n_t","events_c","n_c","in_relative_pool"))[0]
        counts=dict(records_imported=len(records),pre_screen_removed=sum(r["disposition"]!="keep" for r in dedup.values()),
            included_reports=len(included),included_studies=len(rows),informative_studies=int(summary["k_informative"]),
            local_selection_subset_not_complete_prisma=True)
        counts.update(records_removed_before_screening=counts["pre_screen_removed"],
                      reports_included=counts["included_reports"],studies_analyzed=counts["included_studies"])
        (stage/"selection_counts.json").write_text(json.dumps(counts,indent=2)+"\n",encoding="utf-8")
        shutil.copyfile(a.study_review,stage/"study_review.csv")
        status="DRAFT_SYNTHETIC" if p["mode"]=="synthetic_test" else "DRAFT_EVIDENCE_RECORDED_NOT_FINAL"
        used=[];by_record={r["record_id"]:r for r in records};sections=[]
        def add(text,style=None,table=None,figures=None):
            sections.append(dict(text=text,**({"style":style} if style else {}),
                **({"table":table} if table else {}),**({"figures":figures} if figures else {})))
        def prose(entries):
            for item in entries:
                for rid in item["record_ids"]:
                    if rid not in used:used.append(rid)
                cite=" ["+", ".join(str(used.index(rid)+1) for rid in item["record_ids"])+"]" if p["mode"]=="real" and item["record_ids"] else ""
                add(item["text"]+cite)
        add(narrative["title"],"Title");add(status+": rare-event method draft; clinical interpretation requires review.")
        add("Introduction","Heading1");prose(narrative["Introduction"])
        add("Methods","Heading1")
        add(f"Question: {p['question']} Population: {p['pico']['population']}. Intervention: {p['pico']['intervention']}; comparator: {p['pico']['comparator']}. Outcome: {p['pico']['outcome']} at {p['pico']['timepoint']}. Search status: {p['search_status']}.")
        add(f"Prespecified fixed-effect Mantel-Haenszel {p['analysis']['effect_type']} used independent 2x2 counts. individual_effect_correction={summary['individual_effect_correction']}: 0.5 to all four cells of a study with any zero, arm totals +1. pooled_MH_correction={summary['pooled_MH_correction']}: {summary['mh_zero_correction']}. double_zero_policy={summary['double_zero_policy']}: double-zero and double-all studies excluded with trace. The RevMan-compatible option is not evidence of the authors' original project settings. CMH test correction={summary['cmh_test_correction']} controls the test only. Peto was {'an OR-only sensitivity' if p['analysis']['peto_sensitivity'] else 'not planned'}.")
        add("Results","Heading1")
        add(f"The local ledger identified {counts['records_imported']} records and {counts['included_reports']} included reports mapped to {counts['included_studies']} studies; {counts['informative_studies']} contributed to the relative pool. These are local selection counts, not complete PRISMA coverage.",figures=[(1,"MH forest; individual display correction and excluded double-boundary count labeled",stats/"rare_forest.png")])
        review_by={r["study_id"]:r for r in reviews}
        table=[["Study","Events treatment / control","Relative pool","Risk evidence"]]
        for r in trace:
            table.append([r["study_id"],f"{r['events_t']}/{r['n_t']} vs {r['events_c']}/{r['n_c']}",
                r["in_relative_pool"],review_by[r["study_id"]]["risk_judgment"]])
        add("Raw source counts and reviewer-entered risk judgments.",table={"title":"Table 1  Included rare-event study tables","rows":table})
        level=100*(1-float(p["analysis"]["alpha"]))
        def num(key):
            return f"{float(summary[key]):.4g}" if summary[key] else "not estimable / not applicable"
        add(f"Configured MH status: {summary['estimation_status']}. MH {p['analysis']['effect_type']} {num('mh_ratio')} ({level:g}% CI {num('mh_ci_lower')} to {num('mh_ci_upper')}); inverse-variance corrected sensitivity {num('iv_corrected_ratio')} ({num('iv_corrected_ci_lower')} to {num('iv_corrected_ci_upper')}). Peto status: {summary['peto_status']}; {summary['peto_warning']}. The source trace retains all excluded double-boundary rows and correction details.")
        add(f"Heterogeneity status: {summary['heterogeneity_status']}; MH-centered Q={num('Q')}, df={num('Q_df')}, p={num('Q_p')}, I2={num('I2_percent')}%. Q uses inverse individual log-variance weights, distinct from MH pooling weights. tau2 is fixed at zero by the model, not an estimated absence of heterogeneity. Single-study heterogeneity is not applicable.")
        loo=lit.read_csv(stats/"rare_leave_one_out.csv",("omitted_study","estimation_status","mh_ratio","mh_ci_lower","mh_ci_upper","heterogeneity_status"))[0]
        def loo_display(v):
            status={"ESTIMABLE":"estimable","SINGLE_STUDY_ESTIMABLE":"single study",
                    "NOT_ESTIMABLE_MH":"not estimable","NOT_ESTIMABLE_NO_INFORMATIVE_STUDIES":"no informative studies"}[v["estimation_status"]]
            interval=(f"{float(v['mh_ratio']):.4g} ({float(v['mh_ci_lower']):.4g} to {float(v['mh_ci_upper']):.4g})"
                      if v["mh_ratio"] else "not estimable")
            heterogeneity="not applicable" if v["heterogeneity_status"].startswith("NOT_APPLICABLE") else v["heterogeneity_status"].replace("_"," ").lower()
            return [v["omitted_study"],status,interval,heterogeneity]
        add("Leave-one-out retains the selected correction configuration. Non-estimable configured MH results have blank values and intervals; corrected single-study display effects remain separate in the statistical CSV. Engine warnings are retained in engine_warnings.csv.",
            table={"title":"Table 2  Leave-one-out configured MH", "rows":[["Omitted study","MH status","Ratio (CI)","Heterogeneity"]]+[
                loo_display(v) for v in loo]},
            figures=[(2,"Leave-one-out configured MH; non-estimable omissions labeled",stats/"rare_leave_one_out.png")])
        add("Discussion","Heading1");prose(narrative["Discussion"])
        add("Limitations","Heading1");add("A small-event count does not by itself establish design comparability. Peto can mislead under allocation imbalance, nonrare events or large effects. Risk judgments, source extraction, cohort independence and choice of effect scale require original-article review. This draft is not a clinical conclusion.")
        add("References","Heading1")
        if p["mode"]=="real":
            for m in mapping:
                if m["record_id"] not in used:used.append(m["record_id"])
            for i,rid in enumerate(used,1):
                r=by_record[rid];add(f"[{i}] {r['authors']}. {r['title']}. {r['year']}."+(f" doi:{r['doi']}" if r['doi'] else "")+(f" PMID:{r['pmid']}" if r['pmid'] else ""))
        else:add("Fully synthetic example; no real literature citation is asserted.")
        def markdown_section(s):
            prefix="# " if s.get("style")=="Title" else "## " if s.get("style")=="Heading1" else ""
            body=prefix+s["text"]
            if "table" in s:
                cells=s["table"]["rows"]
                body+=("\n\n"+s["table"]["title"]+"\n\n"+" | ".join(cells[0])+"\n"+
                       " | ".join(["---"]*len(cells[0]))+"\n"+"\n".join(" | ".join(row) for row in cells[1:]))
            return body
        (stage/"manuscript.md").write_text("\n\n".join(markdown_section(s) for s in sections)+"\n",encoding="utf-8")
        diagnostic_word.write(stage/"manuscript.docx",sections,[(1,"MH forest",stats/"rare_forest.png"),(2,"Leave-one-out MH",stats/"rare_leave_one_out.png")])
        (stage/"manuscript.json").write_text(json.dumps(dict(schema="meta-rare-event-manuscript-v1",
            status=status,final=False,sections=[{k:s[k] for k in ("text","style") if k in s} for s in sections],
            fact_sources=dict(confirmation_sha256=lit.sha256(confirmation),
                              statistics_receipt_sha256=lit.sha256(stats/"rare_receipt.json"))),
            ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        (stage/"status.json").write_text(json.dumps(dict(schema="meta-rare-event-draft-v1",status=status,final=False,
            source_meaning_verified_by_software=False,word_visual_reviewed=False,
            confirmation_sha256=lit.sha256(confirmation),narrative_sha256=lit.sha256(a.narrative)),indent=2)+"\n",encoding="utf-8")
        (stage/"manifest.json").write_text(json.dumps(dict(files={str(f.relative_to(stage)).replace('\\','/'):lit.sha256(f)
            for f in stage.rglob('*') if f.is_file()}),indent=2)+"\n",encoding="utf-8")
        os.replace(stage,out)
    print(status,out)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("command",choices=("confirm","build"))
    for key in CORE:parser.add_argument("--"+key.replace("_","-"),required=True)
    for key in ("confirmation","narrative","rscript"):parser.add_argument("--"+key)
    parser.add_argument("--out",required=True);a=parser.parse_args()
    try:
        if a.command=="confirm":confirm(a)
        else:
            if not all((a.confirmation,a.narrative,a.rscript)):lit.fail("build needs confirmation, narrative and Rscript")
            build(a)
    except (OSError,ValueError,KeyError,TypeError,csv.Error) as exc:parser.exit(2,"Validation: "+str(exc)+"\n")
