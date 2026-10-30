"""Method-aware, non-final Summary of Findings from checked method papers and entered certainty."""
import argparse
from datetime import date
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import tempfile

import diagnostic_word
import literature as lit

METHODS={
    "rare":("meta-rare-event-manuscript-v1","rare_receipt.json","meta-rare-event-result-v1"),
    "diagnostic":("meta-diagnostic-manuscript-v1","diagnostic_receipt.json","meta-diagnostic-result-v1"),
    "multithreshold":("meta-multithreshold-manuscript-v1","multithreshold_receipt.json","meta-multithreshold-result-v1"),
    "network":("meta-network-manuscript-v1","network_receipt.json","meta-network-result-v1"),
    "dose":("meta-dose-manuscript-v1","dose_receipt.json","meta-dose-result-v1"),
    "single_arm":("meta-single-arm-manuscript-v1","single_receipt.json","meta-single-arm-result-v1"),
    "dependent":("meta-dependent-manuscript-v1","dependent_receipt.json","meta-dependent-result-v1"),
}
INPUT=("outcome_id","method","paper_dir","selector","participants","participants_scope",
       "participants_evidence_file","participants_evidence_sha256","participants_locator",
       "certainty","certainty_status","certainty_evidence_file","certainty_evidence_sha256",
       "certainty_locator","reviewer","review_date","comment")
RARE_BASELINE_INPUT=("baseline_risk_per_1000","baseline_evidence_file","baseline_evidence_sha256",
    "baseline_locator","baseline_timepoint","baseline_population","baseline_applicability_review",
    "baseline_applicability_basis","baseline_reviewer","baseline_review_date")
OUTPUT=("outcome_id","method","outcome","timepoint","selector","metric","effect_scale","unit",
        "estimate","ci_lower","ci_upper","ci_status","studies","study_count_scope","participants",
        "participants_scope","participants_evidence","model","source_result_file","source_result_sha256",
        "paper_manifest_sha256","confirmation_sha256","certainty","certainty_status","certainty_evidence",
        "reviewer","review_date","comment")
RARE_OUTPUT=("identified_studies","informative_studies","double_zero_excluded","double_all_excluded",
    "peto_status","peto_warning","pooled_zero_correction","display_zero_correction",
    "baseline_risk_per_1000","baseline_evidence","baseline_timepoint","baseline_population",
    "baseline_applicability_review","baseline_applicability_basis","baseline_reviewer","baseline_review_date",
    "intervention_risk_per_1000","intervention_ci_lower_per_1000","intervention_ci_upper_per_1000",
    "absolute_difference_per_1000","absolute_difference_ci_lower_per_1000",
    "absolute_difference_ci_upper_per_1000","absolute_assumption")


def read(path,fields,empty=False):return lit.read_csv(path,fields,allow_empty=empty)[0]
def load(path):return json.loads(Path(path).read_text(encoding="utf-8"))
def one(path,fields):
    rows=read(path,fields)
    if len(rows)!=1:lit.fail("expected one method summary row: "+str(path))
    return rows[0]
def resolved_entries(path):
    entries=read(path,INPUT);base=Path(path).resolve().parent
    for row in entries:
        for key in RARE_BASELINE_INPUT:row.setdefault(key,"")
        for key in ("paper_dir","participants_evidence_file","certainty_evidence_file","baseline_evidence_file"):
            if row[key]:
                file=Path(row[key]).expanduser()
                row[key]=str((file if file.is_absolute() else base/file).resolve())
    return entries
def checked_number(value,label,lo=None,hi=None):
    try:n=Decimal(str(value))
    except (InvalidOperation,TypeError):lit.fail(label+" must be numeric")
    if not n.is_finite() or lo is not None and n<lo or hi is not None and n>hi:
        lit.fail(label+" outside allowed finite range")
    return n


def checked_paper(path,method):
    root=Path(path).resolve();manifest=load(root/"manifest.json")
    if not isinstance(manifest.get("files"),dict) or not manifest["files"]:
        lit.fail("method paper manifest missing files")
    for name,digest in manifest["files"].items():
        file=(root/name).resolve()
        if not file.is_relative_to(root) or not file.is_file() or lit.sha256(file)!=digest:
            lit.fail("method paper file changed: "+name)
    manuscript=load(root/"manuscript.json")
    expected,receipt_name,receipt_schema=METHODS[method]
    if manuscript.get("schema")!=expected or manuscript.get("final") is not False:
        lit.fail("paper method/schema/final state mismatch")
    stats=root/"statistics";receipt=load(stats/receipt_name)
    if receipt.get("schema")!=receipt_schema or receipt.get("final" if method=="rare" else "final_report") is not False:
        lit.fail("statistical receipt method/final state mismatch")
    if manuscript.get("fact_sources",{}).get("statistics_receipt_sha256")!=lit.sha256(stats/receipt_name):
        lit.fail("paper does not bind these statistical facts")
    for name,digest in receipt.get("outputs",{}).items():
        file=stats/name
        if not file.is_file() or lit.sha256(file)!=digest:lit.fail("statistical output changed: "+name)
    plan=root/"analysis_plan.json"
    if receipt.get("plan_sha256")!=lit.sha256(plan):lit.fail("method plan differs from statistical receipt")
    confirmation_hash=manuscript["fact_sources"].get("confirmation_sha256")
    candidates=[p for child in root.parent.iterdir() if child.is_dir() for p in child.glob("*confirmation.json")
                if lit.sha256(p)==confirmation_hash]
    if len(candidates)!=1:lit.fail("bound method confirmation missing or ambiguous")
    confirmation=load(candidates[0]);input_paths=confirmation.get("input_paths",{})
    hashes=confirmation.get("hashes",{})
    if not isinstance(input_paths,dict) or not isinstance(hashes,dict):lit.fail("method confirmation input hashes missing")
    for key,value in input_paths.items():
        if key not in hashes or not Path(value).is_file() or lit.sha256(value)!=hashes[key]:
            lit.fail("method confirmation original input changed: "+key)
    for key,value in hashes.items():
        if key.endswith("_bytes") and isinstance(value,dict):
            for source,digest in value.items():
                if not Path(source).is_file() or lit.sha256(source)!=digest:
                    lit.fail("method evidence file changed: "+source)
    return root,stats,load(plan),receipt,lit.sha256(root/"manifest.json"),confirmation_hash


def data_rows(method,stats,plan,receipt,selector):
    output=[]
    def add(metric,scale,unit,estimate,low,high,studies,scope,model,source,ci_kind="REPORTED"):
        unavailable=method=="rare" and ci_kind=="NOT_ESTIMABLE" and estimate==low==high==""
        if not str(studies).isdigit() or int(studies)<(0 if unavailable else 1):lit.fail("positive study count required")
        point=None if unavailable else checked_number(estimate,metric+" estimate")
        if unavailable:
            pass
        elif low=="" or high=="":
            if low!="" or high!="":lit.fail("partial interval cannot be displayed")
            low=high="";ci_kind="NOT_REPORTED"
        else:
            lower=checked_number(low,metric+" lower");upper=checked_number(high,metric+" upper")
            if not lower<=point<=upper:lit.fail("estimate outside reported confidence interval")
        if unavailable:
            pass
        elif scale in {"fraction","proportion"}:
            checked_number(point,metric+" fraction",Decimal(0),Decimal(1))
            if low:checked_number(low,metric+" lower",Decimal(0),Decimal(1));checked_number(high,metric+" upper",Decimal(0),Decimal(1))
        elif scale in {"RR","OR","incidence_rate"}:
            if point<=0 or low and checked_number(low,metric+" lower")<=0:
                lit.fail("ratio/rate must be positive")
        output.append(dict(metric=metric,effect_scale=scale,unit=unit,estimate=str(estimate),ci_lower=str(low),
            ci_upper=str(high),ci_status=ci_kind,studies=str(studies),study_count_scope=scope,
            model=str(model),source_result_file=str(source.resolve()),source_result_sha256=lit.sha256(source)))
    if method=="diagnostic":
        file=stats/"diagnostic_summary.csv";r=one(file,("k","model","threshold_policy","sensitivity","sensitivity_lower","sensitivity_upper","specificity","specificity_lower","specificity_upper"))
        if selector:lit.fail("single-threshold diagnostic SoF has no selector")
        for metric in ("sensitivity","specificity"):
            add(metric,"fraction","fraction of cases" if metric=="sensitivity" else "fraction of non-cases",
                r[metric],r[metric+"_lower"],r[metric+"_upper"],r["k"],"same_diagnostic_studies_not_additive",
                r["model"]+"; threshold policy "+r["threshold_policy"],file)
    elif method=="multithreshold":
        file=stats/"multithreshold_summary.csv";r=one(file,("n_studies","model","threshold_unit","optimal_cutoff","fit_status",
            "sensitivity_optimal","sensitivity_lower","sensitivity_upper","specificity_optimal","specificity_lower","specificity_upper"))
        if selector:lit.fail("multithreshold SoF uses model optimum, not an arbitrary selected cutoff")
        model=r["model"]+"; model-selected cutoff "+r["optimal_cutoff"]+" "+r["threshold_unit"]+"; "+r["fit_status"]+"; clinical utility unreviewed"
        for metric in ("sensitivity","specificity"):
            add(metric+" at model-selected cutoff","fraction","fraction of cases" if metric=="sensitivity" else "fraction of non-cases",
                r[metric+"_optimal"],r[metric+"_lower"],r[metric+"_upper"],r["n_studies"],
                "same_multithreshold_studies_not_additive",model,file)
    elif method=="network":
        file=stats/"league_table.csv";summary=one(stats/"network_summary.csv",("n_studies","model","effect_type","reference"))
        parts=selector.split("|")
        if len(parts)!=2 or not all(parts) or parts[0]==parts[1]:lit.fail("network selector must be treatment1|treatment2")
        rows=[r for r in read(file,("treat1","treat2","estimate","ci_lower","ci_upper","scale"))
              if (r["treat1"],r["treat2"])==tuple(parts)]
        if len(rows)!=1:lit.fail("network comparison missing or ambiguous")
        r=rows[0];effect=summary["effect_type"]
        if effect not in {"MD","RR","OR"}:lit.fail("network effect scale unsupported in SoF")
        if effect=="MD":
            if r["scale"]!="mean_difference":lit.fail("network MD league scale mismatch")
            point,lower,upper=r["estimate"],r["ci_lower"],r["ci_upper"]
            interval_status="REPORTED"
        else:
            if r["scale"]!="log_ratio":lit.fail("network ratio league scale mismatch")
            point=str(checked_number(r["estimate"],"network log ratio").exp())
            lower=str(checked_number(r["ci_lower"],"network log lower").exp()) if r["ci_lower"] else ""
            upper=str(checked_number(r["ci_upper"],"network log upper").exp()) if r["ci_upper"] else ""
            interval_status="EXP_OF_REPORTED_LOG_INTERVAL" if lower and upper else "NOT_REPORTED"
        add(parts[0]+" versus "+parts[1],effect,"UNIT_NOT_SUPPLIED" if effect=="MD" else "ratio",
            point,lower,upper,summary["n_studies"],
            "whole_network_not_comparison_specific",summary["model"]+"; league orientation as stored",file)
        output[-1]["ci_status"]=interval_status
    elif method=="dose":
        file=stats/"dose_predictions.csv";summary=one(stats/"dose_summary.csv",("n_studies","model","reference_dose","dose_unit"))
        wanted=checked_number(selector,"dose selector")
        rows=[r for r in read(file,("dose","reference_dose","RR","ci_lower","ci_upper","dose_unit","model"))
              if checked_number(r["dose"],"prediction dose")==wanted]
        if len(rows)!=1:lit.fail("dose prediction missing or repeated")
        r=rows[0]
        if r["reference_dose"]!=summary["reference_dose"] or r["dose_unit"]!=summary["dose_unit"]:
            lit.fail("dose prediction/reference unit differs from plan")
        reference=wanted==checked_number(summary["reference_dose"],"reference dose")
        add("dose "+r["dose"]+" versus "+r["reference_dose"],"RR","ratio at "+r["dose_unit"],r["RR"],
            r["ci_lower"],r["ci_upper"],summary["n_studies"],"same_dose_studies_not_additive",
            r["model"]+"; explicit reference",file,"DEFINITIONAL_REFERENCE_NOT_ESTIMATED" if reference else "REPORTED")
    elif method=="single_arm":
        file=stats/"single_summary.csv";r=one(file,("measure","model","display_unit","n_studies","pooled_display","ci_lower","ci_upper"))
        if selector:lit.fail("single-arm SoF has no selector")
        if r["measure"] not in {"proportion","incidence_rate"}:lit.fail("single-arm measure unsupported")
        scale="proportion" if r["measure"]=="proportion" else "incidence_rate"
        add(r["measure"],scale,r["display_unit"],r["pooled_display"],r["ci_lower"],r["ci_upper"],
            r["n_studies"],"same_single_arm_studies_not_additive",r["model"],file)
    elif method=="rare":
        file=stats/"rare_summary.csv";r=one(file,("effect_type","model","k_identified","k_informative",
            "k_double_zero","k_double_all","mh_ratio","mh_ci_lower","mh_ci_upper",
            "iv_corrected_ratio","iv_corrected_ci_lower","iv_corrected_ci_upper",
            "peto_ratio","peto_ci_lower","peto_ci_upper","peto_status","peto_warning",
            "mh_zero_correction","individual_display_and_iv_correction"))
        if selector:lit.fail("rare-event SoF uses its confirmed MH primary, not a selected study")
        if r["effect_type"] not in {"RR","OR"} or r["effect_type"]!=plan.get("effect_type"):
            lit.fail("rare-event effect scale differs from confirmed plan")
        trace=read(stats/"study_trace.csv",("study_id","events_t","n_t","events_c","n_c",
            "in_relative_pool","exclusion_reason"))
        counts=(int(r["k_identified"]),int(r["k_informative"]),int(r["k_double_zero"]),int(r["k_double_all"]))
        if counts[0]!=len(trace) or counts[1]!=sum(x["in_relative_pool"]=="TRUE" for x in trace) or \
                counts[0]!=counts[1]+counts[2]+counts[3]:
            lit.fail("rare-event identified/informative/double-boundary counts disagree with source trace")
        if counts[2]!=sum(int(x["events_t"])==0 and int(x["events_c"])==0 for x in trace) or \
                counts[3]!=sum(int(x["events_t"])==int(x["n_t"]) and
                               int(x["events_c"])==int(x["n_c"]) for x in trace):
            lit.fail("rare-event double-boundary counts disagree with raw events")
        for x in trace:
            is_zero=int(x["events_t"])==0 and int(x["events_c"])==0
            is_all=int(x["events_t"])==int(x["n_t"]) and int(x["events_c"])==int(x["n_c"])
            if (x["in_relative_pool"]=="TRUE")!=(not(is_zero or is_all)) or \
                    (is_zero or is_all)!=bool(x["exclusion_reason"]):
                lit.fail("rare-event study contribution trace contradicts raw counts")
        import rare_events
        resolved=rare_events.checked_plan_data(plan)
        label="0.5 to all four cells of studies with any zero cell; arm totals +1"
        pooled_label="none" if resolved["pooled_MH_correction"]=="none" else label
        if r["mh_zero_correction"]!=pooled_label or r["individual_display_and_iv_correction"]!=label:
            lit.fail("rare-event zero-correction label differs from confirmed plan")
        scope="informative_relative_pool_not_all_identified"
        model=r["model"]+"; pooled correction: "+pooled_label+"; double-zero/all explicitly excluded"
        add("MH primary",r["effect_type"],"ratio",r["mh_ratio"],r["mh_ci_lower"],r["mh_ci_upper"],
            r["k_informative"],scope,model,file,"REPORTED" if r["mh_ratio"] else "NOT_ESTIMABLE")
        add("inverse-variance sensitivity",r["effect_type"],"ratio",r["iv_corrected_ratio"],
            r["iv_corrected_ci_lower"],r["iv_corrected_ci_upper"],r["k_informative"],scope,
            "fixed-effect sensitivity; "+label,file,"REPORTED" if r["iv_corrected_ratio"] else "NOT_ESTIMABLE")
        if r["peto_status"]=="SENSITIVITY_ONLY":
            if r["effect_type"]!="OR":lit.fail("Peto sensitivity cannot use RR")
            add("Peto OR sensitivity","OR","ratio",r["peto_ratio"],r["peto_ci_lower"],
                r["peto_ci_upper"],r["k_informative"],scope,
                "Peto sensitivity only; "+r["peto_warning"],file)
        elif r["peto_status"] not in {"NOT_REQUESTED","NOT_ESTIMABLE"}:
            lit.fail("rare-event Peto status invalid")
        for item in output:
            item.update(identified_studies=r["k_identified"],informative_studies=r["k_informative"],
                double_zero_excluded=r["k_double_zero"],double_all_excluded=r["k_double_all"],
                peto_status=r["peto_status"],peto_warning=r["peto_warning"],
                pooled_zero_correction=r["mh_zero_correction"],
                display_zero_correction=r["individual_display_and_iv_correction"])
    elif method=="dependent":
        file=stats/"dependent_results.csv";rows=[r for r in read(file,("rho","primary","n_studies","n_effects",
            "display_estimate","display_lower","display_upper","inference_status")) if r["primary"].upper()=="TRUE"]
        plan_rows=read(stats/"engine_plan.csv",("effect_type","outcome","timepoint","effect_unit"))
        if len(rows)!=1 or len(plan_rows)!=1 or selector:lit.fail("dependent SoF needs one primary rho and no selector")
        r=rows[0];effect=plan_rows[0]["effect_type"]
        if effect not in {"MD","SMD","RR","OR","HR"}:lit.fail("dependent effect scale unsupported")
        add("primary rho "+r["rho"],effect,plan_rows[0]["effect_unit"] if effect=="MD" else "SD units" if effect=="SMD" else "ratio",
            r["display_estimate"],r["display_lower"],r["display_upper"],r["n_studies"],
            "independent_study_clusters_not_effect_rows",r["inference_status"]+"; "+r["n_effects"]+" related effects",file)
    else:lit.fail("unsupported method SoF family")
    return output


def evidence(value,file,digest,locator,label,needed):
    if not needed:
        if any((file,digest,locator)):lit.fail(label+" evidence without value")
        return "NOT_SUPPLIED"
    path=Path(file).resolve()
    if not path.is_file() or lit.sha256(path)!=digest or not locator.strip():
        lit.fail(label+" requires existing source bytes, SHA-256 and locator")
    return str(path)+" ["+locator+"]; sha256="+digest


def build(a):
    inputs=Path(a.inputs).resolve();entries=resolved_entries(inputs)
    if not 1<=len(entries)<=50:lit.fail("method SoF needs 1-50 input rows")
    result=[];used=set();bound={}
    for entry in entries:
        oid=entry["outcome_id"].strip();method=entry["method"]
        if not oid or oid in used or method not in METHODS:lit.fail("distinct outcome ID and supported method required")
        if method!="rare" and any(entry[key] for key in RARE_BASELINE_INPUT):
            lit.fail("rare-event baseline fields cannot be applied to another method")
        used.add(oid)
        paper,stats,plan,receipt,manifest_hash,confirmation_hash=checked_paper(entry["paper_dir"],method)
        key=(str(paper),entry["selector"])
        if key in bound:lit.fail("same paper/selector repeated; do not double count an outcome")
        bound[key]=oid
        study_rows=data_rows(method,stats,plan,receipt,entry["selector"])
        if entry["participants"]:
            if not entry["participants"].isdigit() or int(entry["participants"])<1:
                lit.fail("participants must be a positive non-pooled integer")
            if entry["participants_scope"] not in {"outcome_specific","model_population","whole_network_not_comparison_specific"}:
                lit.fail("participant denominator scope required")
            if method=="network" and entry["participants_scope"]!="whole_network_not_comparison_specific":
                lit.fail("network participant count cannot be claimed comparison-specific")
        elif entry["participants_scope"]:lit.fail("participant scope without count")
        people=evidence(entry["participants"],entry["participants_evidence_file"],
            entry["participants_evidence_sha256"],entry["participants_locator"],"participants",bool(entry["participants"]))
        certainty=entry["certainty"].upper();status=entry["certainty_status"]
        if status not in {"reviewer_claim","synthetic_test","agent_suggestion","not_assessed"}:
            lit.fail("certainty status invalid")
        if status=="not_assessed":
            if certainty!="NOT_ASSESSED" or any(entry[k] for k in ("certainty_evidence_file","certainty_evidence_sha256",
                "certainty_locator","reviewer","review_date")):lit.fail("not_assessed cannot carry a grade or reviewer")
            certainty_evidence="NOT_SUPPLIED"
        else:
            if certainty not in {"HIGH","MODERATE","LOW","VERY_LOW"} or not entry["reviewer"].strip():
                lit.fail("graded certainty needs explicit source and reviewer/Agent label")
            try:date.fromisoformat(entry["review_date"])
            except ValueError:lit.fail("certainty review date needs YYYY-MM-DD")
            if status=="agent_suggestion" and not entry["reviewer"].startswith("AGENT_"):
                lit.fail("Agent suggestion must retain AGENT_ reviewer label")
            if status=="reviewer_claim" and entry["reviewer"].startswith("AGENT_"):
                lit.fail("Agent suggestion cannot masquerade as reviewer judgment")
            certainty_evidence=evidence(certainty,entry["certainty_evidence_file"],
                entry["certainty_evidence_sha256"],entry["certainty_locator"],"certainty",True)
        baseline={}
        state="not_supplied"
        if method=="rare":
            baseline={key:"" for key in RARE_OUTPUT if key not in study_rows[0]}
            state=entry["baseline_applicability_review"] or "not_supplied"
            if state not in {"not_supplied","applicable","not_applicable","uncertain"}:
                lit.fail("rare-event baseline applicability invalid")
            supplied=any(entry[key] for key in RARE_BASELINE_INPUT if key!="baseline_applicability_review")
            if state=="not_supplied":
                if supplied:lit.fail("rare-event baseline evidence needs an applicability review")
                baseline["baseline_applicability_review"]=state
            else:
                needed=("baseline_risk_per_1000","baseline_timepoint","baseline_population",
                        "baseline_applicability_basis","baseline_reviewer","baseline_review_date")
                if not all(entry[key] for key in needed):lit.fail("rare-event baseline needs risk, population/timepoint and review")
                try:date.fromisoformat(entry["baseline_review_date"])
                except ValueError:lit.fail("rare-event baseline review date needs YYYY-MM-DD")
                if entry["baseline_reviewer"].startswith("AGENT_"):
                    lit.fail("Agent suggestion cannot be a completed rare-event baseline applicability review")
                risk=checked_number(entry["baseline_risk_per_1000"],"baseline risk per 1000",Decimal(0),Decimal(1000))
                if risk<=0 or risk>=1000:lit.fail("rare-event baseline risk must be within 0-1000")
                if entry["baseline_timepoint"]!=plan["timepoint"]:
                    lit.fail("rare-event baseline timepoint differs from analyzed endpoint")
                source=evidence(entry["baseline_risk_per_1000"],entry["baseline_evidence_file"],
                    entry["baseline_evidence_sha256"],entry["baseline_locator"],"rare-event baseline",True)
                baseline.update(baseline_risk_per_1000=entry["baseline_risk_per_1000"],baseline_evidence=source,
                    baseline_timepoint=entry["baseline_timepoint"],baseline_population=entry["baseline_population"],
                    baseline_applicability_review=state,baseline_applicability_basis=entry["baseline_applicability_basis"],
                    baseline_reviewer=entry["baseline_reviewer"],baseline_review_date=entry["baseline_review_date"])
        for row in study_rows:
            outcome=plan.get("outcome","");timepoint=plan.get("timepoint","")
            if not outcome or not timepoint:lit.fail("method plan needs an outcome and timepoint")
            extra=dict(baseline)
            if method=="rare" and row["ci_status"]=="NOT_ESTIMABLE":
                extra["absolute_assumption"]="Configured relative effect not estimable; no absolute-risk conversion"
            elif method=="rare" and row["metric"]=="MH primary" and state=="applicable":
                import sof_multi
                extra.update(sof_multi.absolute_effect(row["effect_scale"],row["estimate"],
                    row["ci_lower"],row["ci_upper"],entry["baseline_risk_per_1000"]))
            elif method=="rare" and row["metric"]!="MH primary":
                extra["absolute_assumption"]="Sensitivity estimate; no separate absolute-risk conversion"
            result.append(dict(outcome_id=oid,method=method,outcome=outcome,timepoint=timepoint,
                selector=entry["selector"] or "NONE",**row,**extra,participants=entry["participants"] or "NOT_SUPPLIED",
                participants_scope=entry["participants_scope"] or "NOT_SUPPLIED",participants_evidence=people,
                paper_manifest_sha256=manifest_hash,confirmation_sha256=confirmation_hash,
                certainty=certainty if status!="agent_suggestion" else "NOT_ASSESSED",
                certainty_status=status,certainty_evidence=certainty_evidence,
                reviewer=entry["reviewer"] or "NOT_SUPPLIED",review_date=entry["review_date"] or "NOT_SUPPLIED",
                comment=entry["comment"]+("; Agent suggested "+certainty+" only" if status=="agent_suggestion" else "")))
    out=Path(a.out).resolve()
    if out.exists():lit.fail("method SoF output exists")
    out.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".method-sof-",dir=out.parent) as temp:
        stage=Path(temp)/"result";stage.mkdir()
        lit.write_csv(stage/"method_sof.csv",OUTPUT+RARE_OUTPUT if any(r["method"]=="rare" for r in result) else OUTPUT,result)
        display=[["Outcome / method","Metric and comparison","Estimate (reported CI)","Evidence count","Certainty"]]
        for r in result:
            interval="not estimable" if r["ci_status"]=="NOT_ESTIMABLE" else "not reported" if r["ci_status"]=="NOT_REPORTED" else \
                ("reference definition" if r["ci_status"]=="DEFINITIONAL_REFERENCE_NOT_ESTIMATED" else
                 r["ci_lower"]+" to "+r["ci_upper"])
            display.append([r["outcome"]+" at "+r["timepoint"]+" / "+r["method"],
                r["metric"]+(" ["+r["selector"]+"]" if r["selector"]!="NONE" else ""),
                r["effect_scale"]+" "+r["estimate"]+" ("+interval+") "+r["unit"]+
                    ("; comparator "+r["baseline_risk_per_1000"]+"/1000; intervention "+r["intervention_risk_per_1000"]+
                     "/1000" if r["method"]=="rare" and r["metric"]=="MH primary" and
                     r.get("intervention_risk_per_1000") else ""),
                r["studies"]+" studies: "+r["study_count_scope"]+"; people "+r["participants"]+
                    " ("+r["participants_scope"]+")",
                r["certainty"]+" / "+r["certainty_status"]+
                    ("; baseline "+r["baseline_applicability_review"]+"; identified "+r["identified_studies"]+
                     ", informative "+r["informative_studies"] if r["method"]=="rare" else "")])
        def short(value):
            return format(Decimal(value), ".4g") if value else "not estimable"
        word_display=[["Outcome and metric", "Result and unit", "Evidence and certainty"]]
        for r in result:
            interval=("not estimable" if r["ci_status"]=="NOT_ESTIMABLE" else "CI not reported" if r["ci_status"]=="NOT_REPORTED" else
                      "reference definition" if r["ci_status"]=="DEFINITIONAL_REFERENCE_NOT_ESTIMATED" else
                      short(r["ci_lower"])+" to "+short(r["ci_upper"]))
            word_display.append([
                r["outcome_id"]+" / "+r["method"]+": "+r["metric"],
                r["effect_scale"]+" "+short(r["estimate"])+" ("+interval+") "+r["unit"]+
                    ("; comparator "+r["baseline_risk_per_1000"]+"/1000; intervention "+r["intervention_risk_per_1000"]+
                     "/1000" if r["method"]=="rare" and r["metric"]=="MH primary" and
                     r.get("intervention_risk_per_1000") else ""),
                r["studies"]+" studies; "+("participants not supplied" if r["participants"]=="NOT_SUPPLIED" else r["participants"]+" people")+"; "+
                r["certainty"]+" / "+r["certainty_status"]+
                    ("; baseline "+r["baseline_applicability_review"]+"; identified "+r["identified_studies"]+
                     ", informative "+r["informative_studies"] if r["method"]=="rare" else "")])
        sections=[dict(text="Method-specific Summary of Findings — draft",style="Title"),
            dict(text="Method-native metrics and intervals are retained. Only a rare-event MH primary RR/OR with a sourced and explicitly applicable comparator risk may show a conditional absolute effect. Study totals are not added across outcomes. Certainty is supplied evidence, not automatically graded."),
            dict(text="Method-specific findings",style="Heading1",table={"title":"Table 1. Draft method-specific findings","rows":word_display})]
        sections.append(dict(text="Word values are rounded for reading. The accompanying CSV and Markdown retain full precision, outcome and timepoint, study-count scope, complete source paths and hashes, evidence locators, reviewer details and comments. The receipt binds those local files; no original article was verified by this display."))
        lines=["# Method-specific Summary of Findings — draft","",
            "Only a rare-event MH primary RR/OR with a sourced, reviewed-applicable comparator risk has a conditional absolute effect. No confidence interval is invented. Study and participant counts are not summed across rows.","",
            "| Outcome / method | Metric | Estimate / CI | Evidence count | Certainty |",
            "|---|---|---|---|---|"]
        for row in display[1:]:lines.append("| "+" | ".join(x.replace("|","/") for x in row)+" |")
        for r in result:
            detail=(r["outcome_id"]+" / "+r["metric"]+": model "+r["model"]+"; CI status "+r["ci_status"]+
                "; method result "+r["source_result_file"]+" sha256="+r["source_result_sha256"]+
                "; participant source "+r["participants_evidence"]+"; certainty source "+r["certainty_evidence"]+
                "; certainty entry "+r["certainty_status"]+" by "+r["reviewer"]+" on "+r["review_date"]+
                "; confirmation sha256="+r["confirmation_sha256"]+". "+r["comment"])
            if r["method"]=="rare":
                detail+=(" Identified "+r["identified_studies"]+"; informative "+r["informative_studies"]+
                    "; double-zero/all excluded "+r["double_zero_excluded"]+"/"+r["double_all_excluded"]+
                    "; pooled correction "+r["pooled_zero_correction"]+"; display correction "+r["display_zero_correction"]+
                    "; Peto "+r["peto_status"]+" ("+r["peto_warning"]+"). Baseline applicability "+
                    r["baseline_applicability_review"]+" for "+r["baseline_population"]+" at "+r["baseline_timepoint"]+
                    "; source "+r["baseline_evidence"]+"; basis "+r["baseline_applicability_basis"]+
                    "; absolute intervention risk "+(r["intervention_risk_per_1000"]+" per 1000; " if
                    r["intervention_risk_per_1000"] else "not computed; ")+r["absolute_assumption"])
            lines.extend(["",detail])
        diagnostic_word.write(stage/"method_sof.docx",sections,[])
        (stage/"method_sof.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
        receipt={"schema":"meta-method-sof-v1","status":"DRAFT_METHOD_SPECIFIC_NOT_FINAL",
            "input_path":str(inputs),"input_sha256":lit.sha256(inputs),"rows":len(result),
            "methods":sorted({r["method"] for r in result}),
            "outputs":{p.name:lit.sha256(p) for p in stage.iterdir() if p.is_file()},
            "certainty_automatically_calculated":False,"official_instrument_score":False,
            "absolute_risk_conversion_performed":any(r.get("intervention_risk_per_1000") for r in result),
            "cross_outcome_participants_summed":False}
        (stage/"method_sof_receipt.json").write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        os.replace(stage,out)
    print(receipt["status"],len(result),"metric rows",out)


def verify(path):
    root=Path(path).resolve();receipt=load(root/"method_sof_receipt.json")
    if receipt.get("schema")!="meta-method-sof-v1" or receipt.get("status")!="DRAFT_METHOD_SPECIFIC_NOT_FINAL":
        lit.fail("invalid method SoF receipt")
    inputs=Path(receipt["input_path"])
    if not inputs.is_file() or lit.sha256(inputs)!=receipt["input_sha256"]:
        lit.fail("method SoF inputs changed")
    for entry in resolved_entries(inputs):
        checked_paper(entry["paper_dir"],entry["method"])
        for label in ("participants","certainty","baseline"):
            file=entry[label+"_evidence_file"]
            digest=entry[label+"_evidence_sha256"]
            if file and (not Path(file).is_file() or lit.sha256(file)!=digest):
                lit.fail("method SoF evidence changed: "+label)
    for name,digest in receipt["outputs"].items():
        file=root/name
        if not file.is_file() or lit.sha256(file)!=digest:lit.fail("method SoF output changed: "+name)
    return receipt


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--inputs");p.add_argument("--out");p.add_argument("--verify")
    a=p.parse_args()
    try:
        if a.verify:
            if a.inputs or a.out:lit.fail("--verify cannot be combined with --inputs/--out")
            print("VERIFIED",verify(a.verify)["status"],Path(a.verify).resolve())
        else:
            if not a.inputs or not a.out:lit.fail("build needs --inputs and --out")
            build(a)
    except (OSError,ValueError,KeyError,TypeError) as exc:p.exit(2,"Validation: "+str(exc)+"\n")
