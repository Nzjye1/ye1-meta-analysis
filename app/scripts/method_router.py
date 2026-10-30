"""Choose a compatible Meta method from study data shape, then dispatch a reviewed choice."""
import argparse
from datetime import date
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

import literature as lit

METHODS={
    "pairwise":{"question_type":"comparative_effect","data_shape":"one_independent_effect_per_study","effects":["RR","OR","HR","MD","SMD"],"guide":"CUSTOMER-WORKFLOW.md","phases":{"prepare":("research_plan.py",None),"workflow":("customer_workflow.py",None)}},
    "dependent":{"question_type":"comparative_effect","data_shape":"several_related_effects_per_study","effects":["RR","OR","HR","MD","SMD"],"guide":"DEPENDENT-PROJECT.md","phases":{"analyze":("dependent_effects.py",None),"confirm":("dependent_project.py","confirm"),"paper":("dependent_project.py","build")}},
    "network":{"question_type":"comparative_effect","data_shape":"connected_treatment_network","effects":["RR","OR","MD"],"guide":"NETWORK-PROJECT.md","phases":{"analyze":("network_meta.py",None),"confirm":("network_project.py","confirm"),"paper":("network_project.py","build")}},
    "diagnostic":{"question_type":"diagnostic_accuracy","data_shape":"one_cutoff_per_study","effects":[],"guide":"DIAGNOSTIC-PROJECT.md","phases":{"analyze":("diagnostic_meta.py",None),"confirm":("diagnostic_project.py","confirm"),"paper":("diagnostic_project.py","build")}},
    "multithreshold":{"question_type":"diagnostic_accuracy","data_shape":"several_cutoffs_per_study","effects":[],"guide":"MULTITHRESHOLD-PROJECT.md","phases":{"analyze":("multithreshold_diag.py",None),"confirm":("multithreshold_project.py","confirm"),"paper":("multithreshold_project.py","build")}},
    "dose":{"question_type":"exposure_response","data_shape":"several_dose_categories_per_study","effects":["RR"],"guide":"DOSE-PROJECT.md","phases":{"analyze":("dose_response.py",None),"confirm":("dose_project.py","confirm"),"paper":("dose_project.py","build")}},
    "single_arm":{"question_type":"event_frequency","data_shape":"events_over_people_or_person_time","effects":["proportion","incidence_rate"],"guide":"SINGLE-PROJECT.md","phases":{"analyze":("single_arm.py",None),"confirm":("single_arm_project.py","confirm"),"paper":("single_arm_project.py","build")}},
    "rare":{"question_type":"comparative_effect","data_shape":"independent_sparse_two_arm_event_counts","effects":["RR","OR"],"guide":"RARE-EVENT.md","phases":{"analyze":("rare_events.py",None),"confirm":("rare_event_project.py","confirm"),"paper":("rare_event_project.py","build")}},
}
PROJECT_INPUTS={
    "diagnostic":["protocol","records","dedup","decisions","report_map","input","source_review","quadas"],
    "multithreshold":["protocol","records","dedup","decisions","report_map","input","threshold_review","quadas"],
    "network":["protocol","records","dedup","decisions","report_map","input","assumptions"],
    "dose":["protocol","records","dedup","decisions","report_map","input","category_review"],
    "single_arm":["protocol","records","dedup","decisions","report_map","input","study_review"],
    "dependent":["protocol","records","dedup","decisions","report_map","input","effect_review"],
    "rare":["protocol","records","dedup","decisions","report_map","input","study_review"],
}
METHOD_QUESTIONS={
    "pairwise":["Which single outcome/timepoint and effect direction are prespecified?","Are effect estimates adjusted in a compatible way?","Which FE/NONE, RE/REML or RE/DL configuration and sensitivity analyses are justified?"],
    "dependent":["Do related estimates measure the same construct and share participants?","What working within-study correlation range and cluster definition will be examined?","Which effect scale, unit and adjustment are common?"],
    "network":["Which treatment nodes and reference treatment form a connected network?","How were transitivity, multi-arm trials and effect direction reviewed?","Which effect scale and inconsistency checks are prespecified?"],
    "diagnostic":["What is the reference standard, target condition and case design?","Is the single cutoff comparable across studies, or must studies be split?","Who will review four-cell counts and diagnostic bias evidence?"],
    "multithreshold":["What are the cutoff unit, positive direction and reference standard?","Are denominators constant and counts monotone within each study?","Which cutoffs and sensitivity weight are prespecified, and how will clinical utility be judged?"],
    "dose":["What is the common dose unit and reference exposure category?","How are category representative doses and open intervals justified?","Are within-study category covariance inputs and spline knots prespecified?"],
    "single_arm":["Is the target a proportion of people or an incidence rate over person-time?","What denominator unit and effect scale will be used?","How are zero events, repeated cohorts and follow-up differences handled?"],
    "rare":["Are counts unadjusted and independent on the same event/timepoint scale?","Is fixed-effect MH appropriate and how will double-boundary rows be documented?","For OR, is Peto sensitivity suitable given allocation balance, rarity and effect size?"],
}

def phase_inputs(name):
    if name=="pairwise":return {"prepare":[],"workflow":["project"]}
    core=PROJECT_INPUTS[name]
    return {"analyze":["input","plan","rscript"],"confirm":core,"paper":core+["confirmation","narrative","rscript"]}

def idea_check(path):
    p=Path(path).resolve();idea=json.loads(p.read_text(encoding="utf-8"))
    if idea.get("schema")!="meta-method-idea-v1":lit.fail("method idea schema must be meta-method-idea-v1")
    for k in ("project_id","question","population","outcome","question_type","data_shape"):
        if not isinstance(idea.get(k),str) or not idea[k].strip():lit.fail("method idea needs "+k)
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,60}",idea["project_id"]):lit.fail("invalid project ID")
    match=[(name,m) for name,m in METHODS.items() if (m["question_type"],m["data_shape"])==(idea["question_type"],idea["data_shape"])]
    if len(match)!=1:
        lit.fail("unsupported or ambiguous question/data shape; specify one of the documented shapes, never mix independent, related, network, cutoff or frequency data")
    name,m=match[0];effect=idea.get("effect_type")
    if m["effects"] and effect not in m["effects"]:lit.fail(f"{name} supports effect_type: "+", ".join(m["effects"]))
    if not m["effects"] and effect not in (None,""):lit.fail(f"{name} uses TP/FN/FP/TN, not a comparative effect_type")
    if name=="pairwise" and not all(isinstance(idea.get(k),str) and idea[k].strip() for k in ("intervention","comparator","timepoint","direction")):
        lit.fail("pairwise idea needs intervention, comparator, timepoint and direction")
    return p,idea,name,m

def prepare(a):
    source,idea,name,m=idea_check(a.idea);out=Path(a.out).resolve()
    if not (Path(__file__).resolve().parents[1]/m["guide"]).is_file():
        lit.fail("method guide missing from this installation: "+m["guide"])
    if out.exists():lit.fail("method route output exists")
    out.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".method-route-",dir=out.parent) as tmp:
        stage=Path(tmp)/"result";stage.mkdir()
        route={"schema":"meta-method-route-v1","source_idea":str(source),"source_idea_sha256":lit.sha256(source),
               "proposed_method":name,"question_type":idea["question_type"],"data_shape":idea["data_shape"],
               "effect_type":idea.get("effect_type"),"guide":m["guide"],"phases":list(m["phases"]),
               "phase_required_options":phase_inputs(name),"protocol_review_questions":METHOD_QUESTIONS[name],
               "selection_status":"pending_human_review","does_not_run_search_or_analysis":True}
        route_path=stage/"route.json";route_path.write_text(json.dumps(route,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        choice={"schema":"meta-method-choice-v1","route_sha256":lit.sha256(route_path),"method":name,
                "status":"pending_human_review","reviewer":"","decision_date":"","reference":""}
        (stage/"choice_template.json").write_text(json.dumps(choice,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        (stage/"protocol_outline.json").write_text(json.dumps({"schema":"meta-method-protocol-outline-v1","status":"pending_human_review",
            "project_id":idea["project_id"],"question":idea["question"],"population":idea["population"],"outcome":idea["outcome"],
            "method":name,"effect_type":idea.get("effect_type"),"source_idea_sha256":lit.sha256(source),
            "questions_to_resolve":METHOD_QUESTIONS[name],"not_a_confirmed_method_protocol":True},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        guide=("# Method routing proposal\n\nQuestion: "+idea["question"]+"\n\nProposed method: `"+name+"` from `"+idea["question_type"]+"` / `"+idea["data_shape"]+"`.\n"
               "Read `"+m["guide"]+"` for actual input fields and analysis assumptions. `protocol_outline.json` lists unresolved design questions and is not an executable confirmed protocol. Available phases and required CLI options, excluding --out: "+json.dumps(phase_inputs(name))+".\n\n"
               "The choice template is pending. A real user must review method suitability and write `status=human_confirmed_claim`, reviewer, date and an actual approval reference. Synthetic tests may use `status=synthetic_test`. Both statuses are local claims, not identity authentication.\n\n"
               "Run `python scripts/meta.py method --route ROUTE --choice CHOICE --phase PHASE [phase input options] --out FRESH_DIR`. The selected method still validates its own plan, data and evidence; routing does not perform search, clinical judgment, or final approval.\n")
        (stage/"routing_guide.md").write_text(guide,encoding="utf-8")
        os.replace(stage,out)
    print("PENDING_HUMAN_REVIEW",name,out)

def checked_choice(route_path,choice_path):
    route_file=Path(route_path).resolve();route=json.loads(route_file.read_text(encoding="utf-8"))
    if route.get("schema")!="meta-method-route-v1":lit.fail("invalid method route schema")
    _,idea,name,m=idea_check(route["source_idea"])
    if route["source_idea_sha256"]!=lit.sha256(route["source_idea"]) or route["proposed_method"]!=name or (route["question_type"],route["data_shape"],route["effect_type"],route["guide"],route["phases"],route.get("phase_required_options"),route.get("protocol_review_questions"))!=(idea["question_type"],idea["data_shape"],idea.get("effect_type"),m["guide"],list(m["phases"]),phase_inputs(name),METHOD_QUESTIONS[name]):
        lit.fail("method route stale or changed")
    choice=json.loads(Path(choice_path).read_text(encoding="utf-8"))
    if choice.get("schema")!="meta-method-choice-v1" or choice.get("route_sha256")!=lit.sha256(route_file) or choice.get("method")!=name:
        lit.fail("method choice stale or mismatched")
    if choice.get("status") not in {"human_confirmed_claim","synthetic_test"}:lit.fail("method choice still pending human review")
    if choice["status"]=="human_confirmed_claim":
        if any(not isinstance(choice.get(k),str) or not choice[k].strip() for k in ("reviewer","decision_date","reference")):
            lit.fail("real method choice needs reviewer, date and approval reference")
        date.fromisoformat(choice["decision_date"])
    return route_file,choice,name,m

def dispatch(a,rest):
    route_path,choice,name,m=checked_choice(a.route,a.choice)
    route= json.loads(route_path.read_text(encoding="utf-8"))
    if a.phase not in m["phases"]:lit.fail(f"{name} does not support phase {a.phase}")
    if a.idea and not (name=="pairwise" and a.phase=="prepare"):lit.fail("--idea is only accepted for pairwise preparation")
    if a.receipt:lit.fail("--receipt is only accepted for verification")
    if any(x=="--out" or x.startswith("--out=") or x=="--phase" or x=="--route" or x=="--choice" for x in rest):lit.fail("reserved route/output option in phase arguments")
    required={"--"+key.replace("_","-") for key in phase_inputs(name)[a.phase]}
    if name=="pairwise" and a.phase=="prepare":required.discard("--idea")
    if not required.issubset(set(rest)):lit.fail("method phase needs "+", ".join(sorted(required-set(rest))))
    selected_effect=route.get("effect_type");actual_effect=None
    if name!="pairwise":
        bound_flag="--plan" if a.phase=="analyze" else "--protocol"
        try:bound_file=Path(rest[rest.index(bound_flag)+1])
        except (ValueError,IndexError):lit.fail("method phase lacks bound plan/protocol")
        bound=json.loads(bound_file.read_text(encoding="utf-8"))
        observed=bound.get("source_kind") if a.phase=="analyze" else bound.get("mode")
        expected={"synthetic_fixture","package_method_example"} if choice["status"]=="synthetic_test" else {"reviewed_extraction"}
        if a.phase!="analyze":expected={"synthetic_test"} if choice["status"]=="synthetic_test" else {"real"}
        if observed not in expected:lit.fail("method choice status and plan/protocol source mode disagree")
        analysis=bound if a.phase=="analyze" else bound.get("analysis",{})
        actual_effect=analysis.get("measure" if name=="single_arm" else "effect_type")
        if selected_effect!=actual_effect:lit.fail("method route effect_type differs from actual plan/protocol measure")
    elif a.phase=="workflow":
        project=Path(rest[rest.index("--project")+1]).resolve()
        stages=json.loads(project.read_text(encoding="utf-8")).get("stages",[])
        protocols=[stage.get("args",{}).get("protocol") for stage in stages if stage.get("script")=="review.py" and stage.get("command")=="confirm"]
        if len(protocols)!=1 or not isinstance(protocols[0],str) or protocols[0].startswith("@"):
            lit.fail("pairwise workflow needs one explicit protocol for route effect check")
        protocol_path=protocols[0].replace("{project_dir}",str(project.parent))
        protocol_path=Path(protocol_path)
        if not protocol_path.is_absolute():protocol_path=project.parent/protocol_path
        actual_effect=json.loads(protocol_path.read_text(encoding="utf-8")).get("outcome",{}).get("effect_type")
        if selected_effect!=actual_effect:lit.fail("pairwise route effect_type differs from workflow protocol")
    elif name=="pairwise":actual_effect=selected_effect
    out=Path(a.out).resolve();sidecar=out.parent/(out.name+".method-route-receipt.json")
    resume=(name=="pairwise" and a.phase=="workflow" and "--resume" in rest)
    if (out.exists() and not resume) or sidecar.exists():lit.fail("method output/receipt exists")
    out.parent.mkdir(parents=True,exist_ok=True)
    script,command=m["phases"][a.phase]
    phase_args=rest
    if name=="pairwise" and a.phase=="prepare":
        if a.idea and str(Path(a.idea).resolve())!=json.loads(route_path.read_text(encoding="utf-8"))["source_idea"]:
            lit.fail("pairwise preparation idea differs from route")
        phase_args=["--idea",json.loads(route_path.read_text(encoding="utf-8"))["source_idea"]]+rest
    argv=[sys.executable,str(Path(__file__).with_name(script))]+([command] if command else [])+phase_args+["--out",str(out)]
    result=subprocess.run(argv)
    if result.returncode:return result.returncode
    if not out.exists():lit.fail("selected method returned success without output")
    files={str(p.relative_to(out)).replace("\\","/"):lit.sha256(p) for p in out.rglob("*") if p.is_file()}
    receipt={"schema":"meta-method-dispatch-v1","method":name,"phase":a.phase,"selected_effect_type":selected_effect,"actual_effect_type":actual_effect,
             "route_file":str(route_path),"choice_file":str(Path(a.choice).resolve()),
             "route_sha256":lit.sha256(route_path),"choice_sha256":lit.sha256(a.choice),"choice_status":choice["status"],"output":str(out),"files":files,
             "meaning":"local method routing and file consistency only; underlying protocol and human gates still apply"}
    sidecar.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("METHOD_DISPATCHED",name,a.phase,out)
    return 0

def verify(a):
    receipt=json.loads(Path(a.receipt).read_text(encoding="utf-8"))
    if receipt.get("schema")!="meta-method-dispatch-v1":lit.fail("invalid dispatch receipt")
    if lit.sha256(receipt["route_file"])!=receipt["route_sha256"] or lit.sha256(receipt["choice_file"])!=receipt["choice_sha256"]:
        lit.fail("method route/choice changed")
    checked_choice(receipt["route_file"],receipt["choice_file"])
    out=Path(receipt["output"])
    actual={str(p.relative_to(out)).replace("\\","/"):lit.sha256(p) for p in out.rglob("*") if p.is_file()}
    if not out.is_dir() or actual!=receipt["files"]:lit.fail("method output changed or missing")
    print("METHOD_OUTPUT_FILES_MATCH",out)

if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("command",choices=("prepare","dispatch","verify"))
    parser.add_argument("--idea");parser.add_argument("--route");parser.add_argument("--choice");parser.add_argument("--phase");parser.add_argument("--receipt");parser.add_argument("--out")
    a,rest=parser.parse_known_args()
    try:
        if a.command=="prepare":
            if rest or not a.idea or not a.out:lit.fail("prepare needs --idea and --out")
            prepare(a)
        elif a.command=="dispatch":
            if not all((a.route,a.choice,a.phase,a.out)):lit.fail("dispatch needs route, choice, phase and output")
            sys.exit(dispatch(a,rest))
        else:
            if rest or not a.receipt:lit.fail("verify needs --receipt")
            verify(a)
    except (OSError,ValueError,KeyError,TypeError,json.JSONDecodeError) as error:parser.exit(2,f"Validation: {error}\n")
