"""Local allowlisted stage runner for the customer research workflow; no shell execution."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import os
import literature as lit
from environment_check import resolve_r

ALLOWED={"research_plan.py":{None},"literature.py":{"import","screen","link"},
    "import_ris.py":{None},"merge_sources.py":{None},"source_chain.py":{None},
    "local_retrieval.py":{None},"dual_screen.py":{None},
    "oa_fulltext.py":{None},"europe_pmc_search.py":{None},"oa_bridge.py":{None},
    "registration_draft.py":{"build"},
    "method_sof.py":{None},
    "fulltext_extract.py":{"scan","template","resolve"},
    "docling_pdf.py":{"scan","verify"},
    "evidence_quality.py":{"plan","suggest","resolve"},"sof_multi.py":{None},
    "rob_visual.py":{None},
    "review.py":{"confirm","verify","count"},
    "run_protocol.py":{None},"prisma2020_flow.py":{None},"prisma_reporting.py":{None},"report.py":{None},
    "small_study_diagnostics.py":{None},
    "rare_events.py":{None},"rare_event_project.py":{"confirm","build"},
    "method_draft_revision.py":{None},
    "manuscript.py":{"build","revise"},
    "diagnostic_project.py":{"confirm","build"},
    "multithreshold_project.py":{"confirm","build"},
    "network_project.py":{"confirm","build"},
    "dose_project.py":{"confirm","build"},
    "single_arm_project.py":{"confirm","build"},
    "dependent_project.py":{"confirm","build"}}


def tree(path):
    return {str(p.relative_to(path)).replace("\\","/"):lit.sha256(p)
            for p in Path(path).rglob("*") if p.is_file()}


def run(a):
    config_path=Path(a.project).resolve(); config=json.loads(config_path.read_text(encoding="utf-8"))
    if config.get("schema") == "meta-rare-aggregate-project-v1":
        import rare_aggregate_report
        return rare_aggregate_report.run(a)
    if config.get("schema") == "meta-aggregate-project-v1":
        import aggregate_workflow
        return aggregate_workflow.run(a)
    if config.get("mode") == "existing_summary_data":
        lit.fail("existing_summary_data requires schema meta-aggregate-project-v1")
    stages=config.get("stages",[]); ids=set()
    for stage in stages:
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,48}",stage.get("id","")) or stage["id"] in ids:
            lit.fail("invalid/repeated stage ID")
        ids.add(stage["id"])
        if stage.get("script") not in ALLOWED or stage.get("command") not in ALLOWED[stage["script"]]:
            lit.fail("unsupported script/command")
        if not isinstance(stage.get("args"),dict) or "out" in stage["args"]:
            lit.fail("stage args object required; output is assigned by the runner")
    if not stages: lit.fail("no stages")
    root=Path(a.out).resolve(); receipt_path=root/"workflow_receipt.json"
    if root.exists():
        if not a.resume: lit.fail("output already exists; explicit --resume required")
        receipt=json.loads(receipt_path.read_text(encoding="utf-8"))
        if receipt["project_sha256"]!=lit.sha256(config_path): lit.fail("project changed; use new output")
        if receipt["status"]=="COMPLETED": lit.fail("completed workflow cannot be overwritten")
        for sid,files in receipt["completed"].items():
            if tree(root/sid)!=files:lit.fail("completed stage changed: "+sid)
        for path,digest in receipt.get("completed_inputs",{}).items():
            if not Path(path).is_file() or lit.sha256(path)!=digest:lit.fail("completed-stage input changed: "+path)
    else:
        root.mkdir(parents=True)
        receipt=dict(schema="meta-customer-workflow-v1",project_sha256=lit.sha256(config_path),
                     status="RUNNING",completed={},completed_inputs={},events=[])
    def save():
        pending=receipt_path.with_suffix(".tmp")
        pending.write_text(json.dumps(receipt,indent=2),encoding="utf-8"); pending.replace(receipt_path)
    def resolve(value):
        if not isinstance(value,str):lit.fail("argument values must be strings")
        if value=="{rscript}":
            binary=resolve_r(a.rscript)
            if not binary or not Path(binary).is_file():lit.fail("Rscript unavailable: supply --rscript or META_RSCRIPT")
            return binary
        if value.startswith("@"):
            rel=value[1:]; sid=rel.split("/")[0]
            p=(root/rel).resolve()
            if sid not in receipt["completed"] or not p.is_relative_to(root):lit.fail("invalid/uncompleted stage reference")
            return str(p)
        return str(Path(value.replace("{project_dir}",str(config_path.parent))).expanduser()) if value.startswith(("~","{project_dir}")) else value
    for stage in stages:
        sid=stage["id"]
        if sid in receipt["completed"]:continue
        output=root/sid
        resume_review = bool(output.exists() and a.resume and (
            stage["script"] == "dual_screen.py" or
            stage["script"] == "fulltext_extract.py" and stage.get("command") == "resolve" or
            stage["script"] == "evidence_quality.py" and stage.get("command") == "resolve"))
        if output.exists() and not resume_review:
            lit.fail("failed-stage output retained; inspect it and choose a new stage/output plan")
        cmd=[sys.executable,str(Path(__file__).with_name(stage["script"]))]
        if stage.get("command"):cmd.append(stage["command"])
        input_hashes={}
        for key,value in stage["args"].items():
            if not re.fullmatch(r"[a-z][a-z0-9-]*",key):lit.fail("invalid argument name")
            for item in value if isinstance(value,list) else [value]:
                resolved=resolve(item)
                # Both execution and hashing use the child's project directory.
                path=Path(resolved)
                candidate=path if path.is_absolute() else config_path.parent/path
                if candidate.is_file():
                    resolved=str(candidate.resolve());input_hashes[resolved]=lit.sha256(resolved)
                cmd += ["--"+key,resolved]
        cmd += ["--out",str(output)]
        if resume_review:cmd += ["--resume"]
        receipt["status"]="RUNNING";save()
        child_env=os.environ.copy()
        if a.rscript:child_env["META_RSCRIPT"]=resolve_r(a.rscript)
        proc=subprocess.run(cmd,capture_output=True,text=True,cwd=config_path.parent,env=child_env)
        receipt["events"].append(dict(stage=sid,returncode=proc.returncode,stdout=proc.stdout[-4000:],stderr=proc.stderr[-4000:]))
        if proc.returncode:
            receipt["status"]="NEEDS_ATTENTION";receipt["blocked_stage"]=sid;save()
            lit.fail("stage failed: "+sid+"; see workflow_receipt.json")
        files=tree(output)
        if not files:lit.fail("stage produced no files")
        receipt["completed"][sid]=files;receipt["completed_inputs"].update(input_hashes);save()
    receipt["status"]="COMPLETED";receipt.pop("blocked_stage",None);save()
    print("Completed local stages; scientific approval and manuscript finalization remain human decisions")


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--project",required=True);p.add_argument("--out",required=True);p.add_argument("--resume",action="store_true");p.add_argument("--rscript")
    a=p.parse_args()
    try:run(a)
    except (OSError,ValueError,KeyError,TypeError) as e:p.exit(2,f"Validation: {e}\n")
