"""Render already reviewed generic RoB evidence as a labeled figure and Word appendix."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

import diagnostic_word
import evidence_quality as quality
import literature as lit

FIELDS=("study_id","design_type","instrument_name","instrument_version","instrument_reference",
        "domain","judgment","rationale","evidence_file","evidence_sha256","evidence_locator",
        "reviewer","assessed_at")


def run(a):
    root=Path(a.quality_dir).resolve();receipt=quality.verify_quality(root)
    if receipt["status"] not in {"EXPLORATORY_DRAFT","FORMAL_REVIEWED"}:
        lit.fail("completed reviewer judgments required for RoB figure")
    audit=root/"risk_of_bias_design_audit.csv"
    rows,_=lit.read_csv(audit,FIELDS)
    if not rows:lit.fail("no reviewed RoB rows")
    seen=set();by_study={}
    for row in rows:
        key=(row["study_id"],row["domain"])
        if key in seen:lit.fail("duplicate study/domain RoB row")
        seen.add(key);by_study.setdefault(row["study_id"],set()).add(row["domain"])
        if not Path(row["evidence_file"]).is_file() or lit.sha256(row["evidence_file"])!=row["evidence_sha256"]:
            lit.fail("reviewed RoB source changed")
    if any("overall" not in domains for domains in by_study.values()):lit.fail("per-study overall judgment missing")
    binary=shutil.which(a.rscript) or str(Path(a.rscript).resolve())
    if not Path(binary).is_file():lit.fail("Rscript unavailable")
    out=Path(a.out).resolve()
    if out.exists():lit.fail("RoB figure output exists")
    out.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".rob-visual-",dir=out.parent) as temp:
        stage=Path(temp)/"result";stage.mkdir()
        image=stage/"rob_judgments.png"
        child=subprocess.run([binary,str(Path(__file__).with_suffix(".R")),str(audit),str(image)],
                             capture_output=True,text=True)
        if child.returncode or not image.is_file() or image.stat().st_size==0:
            lit.fail("RoB visual failed: "+(child.stderr.strip() or child.stdout.strip()))
        mode=receipt["status"]
        study_count=len(by_study)
        lines=["# Reviewer-entered risk-of-bias judgments", "",
            f"Source quality status: {mode}. Studies: {study_count}; domain rows: {len(rows)}.",
            "The figure displays existing reviewed ledger values only. It does not apply an official instrument algorithm, authenticate reviewer identity, or infer low risk.",
            f"Original evidence ledger: {audit}; SHA-256 {lit.sha256(audit)}."]
        (stage/"rob_visual.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
        diagnostic_word.write(stage/"rob_visual.docx",[
            dict(text="Risk-of-bias evidence display",style="Title"),
            dict(text=lines[2]+" "+lines[3],figures=[(1,"Reviewer-entered domain judgments",image)]),
            dict(text=lines[4])],[(1,"Reviewer-entered domain judgments",image)])
        (stage/"rob_visual_receipt.json").write_text(json.dumps(dict(schema="meta-rob-visual-v1",
            status="DRAFT_REVIEWED_JUDGMENT_DISPLAY" if mode=="FORMAL_REVIEWED" else "DRAFT_EXPLORATORY_JUDGMENT_DISPLAY",
            final=False,quality_receipt_sha256=lit.sha256(root/"quality_receipt.json"),
            audit_sha256=lit.sha256(audit),input_paths={"quality_dir":str(root)},
            outputs={p.name:lit.sha256(p) for p in stage.iterdir() if p.is_file()},
            instrument_scoring_applied=False),indent=2)+"\n",encoding="utf-8")
        os.replace(stage,out)
    print("DRAFT_ROB_DISPLAY",study_count,out)


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    for key in ("quality-dir","rscript","out"):p.add_argument("--"+key,required=True)
    a=p.parse_args()
    try:run(a)
    except (OSError,ValueError,KeyError,TypeError) as exc:p.exit(2,"Validation: "+str(exc)+"\n")
