"""Bound influence/funnel and cautious small-study asymmetry appendix for independent pairwise effects."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

import literature as lit


def run(a):
    source=Path(a.stats_dir).resolve();receipt_path=source/"protocol_run_receipt.json"
    receipt=json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("schema")!="meta-protocol-run-v1" or not receipt.get("result_sha256"):
        lit.fail("protocol-bound statistics receipt required")
    if lit.sha256(a.confirmation)!=receipt.get("confirmation_sha256") or \
            lit.sha256(Path(__file__).with_name("run_meta.R"))!=receipt.get("run_meta_sha256"):
        lit.fail("statistics confirmation or base R script changed")
    for name,digest in receipt["result_sha256"].items():
        if Path(name).name!=name or not (source/name).is_file() or lit.sha256(source/name)!=digest:
            lit.fail("bound statistical output changed: "+name)
    for name in ("study_effects_trace.csv","pooled_result.csv","confirmed_analysis.csv"):
        if name not in receipt["result_sha256"]:lit.fail("bound statistical output missing: "+name)
    binary=shutil.which(a.rscript) or str(Path(a.rscript).resolve())
    if not Path(binary).is_file():lit.fail("Rscript unavailable")
    out=Path(a.out).resolve()
    if out.exists():lit.fail("output exists; use a fresh diagnostic directory")
    out.parent.mkdir(parents=True,exist_ok=True)
    script=Path(__file__).with_suffix(".R")
    with tempfile.TemporaryDirectory(prefix=".small-study-",dir=out.parent) as temp:
        stage=Path(temp)/"result";stage.mkdir()
        child=subprocess.run([binary,str(script),str(source),str(stage)],capture_output=True,text=True)
        if child.returncode:lit.fail("metafor diagnostics failed: "+(child.stderr.strip() or child.stdout.strip()))
        asym,_=lit.read_csv(stage/"small_study_test.csv",("status","reason","k","predictor","model"))
        influence,_=lit.read_csv(stage/"influence.csv",("study_id","cook_distance","metafor_influence_flag"))
        if len(asym)!=1 or len(influence)!=int(asym[0]["k"]) or not (stage/"funnel.png").is_file():
            lit.fail("diagnostic output incomplete")
        report=["# Exploratory influence and small-study diagnostics","",
            f"Bound protocol run: {source}; mode {receipt['mode']}; {asym[0]['k']} independent studies.",
            f"Funnel/asymmetry status: {asym[0]['status']}. {asym[0]['reason']}",
            "The standard-error slope is the asymmetry test coefficient (z/p); the regression's SE-to-zero limit effect and its CI are distinct descriptive fields.",
            f"SE slope: {asym[0]['asymmetry_slope']}; z: {asym[0]['z']}; p: {asym[0]['p_value']}; SE-to-zero limit effect: {asym[0]['limit_effect']} ({asym[0]['limit_ci_lower']} to {asym[0]['limit_ci_upper']}).",
            f"metafor influence flags: {sum(r['metafor_influence_flag']=='TRUE' for r in influence)} of {len(influence)} studies.",
            "See influence.csv for studentized residual, DFFITS, Cook distance, covariance ratio, leverage and weight by study. A flag is a sensitivity prompt, not a study exclusion.",
            "Funnel asymmetry can arise from heterogeneity, chance, selection, or bias. A non-significant test does not establish absence of publication bias. The base pooled estimate is unchanged."]
        (stage/"diagnostic_report.md").write_text("\n".join(report)+"\n",encoding="utf-8")
        audit=dict(schema="meta-small-study-diagnostics-v1",status="SYNTHETIC_APPENDIX" if receipt["mode"]=="synthetic_test" else "DRAFT_REQUIRES_INTERPRETATION",
            stats_dir=str(source),stats_receipt_sha256=lit.sha256(receipt_path),
            confirmation_sha256=lit.sha256(a.confirmation),script_sha256=lit.sha256(script),
            rscript=str(Path(binary).resolve()),outputs={p.name:lit.sha256(p) for p in stage.iterdir() if p.is_file()},
            final_publication_bias_judgment=False)
        (stage/"diagnostic_receipt.json").write_text(json.dumps(audit,indent=2)+"\n",encoding="utf-8")
        os.replace(stage,out)
    print(audit["status"],asym[0]["status"],out)


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    for name in ("stats-dir","confirmation","rscript","out"):p.add_argument("--"+name,required=True)
    args=p.parse_args()
    try:run(args)
    except (OSError,ValueError,KeyError,TypeError) as exc:p.exit(2,"Validation: "+str(exc)+"\n")
