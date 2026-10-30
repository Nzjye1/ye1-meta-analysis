"""Only protocol-bound R entry: verify confirmation, run R, bind results, then commit."""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import literature as lit
import review


def run(a):
    receipt, _, _, _, _, effects = review.checked_receipt(a)
    if len(effects) < 2:
        lit.fail("protocol-bound meta-analysis needs at least two linked effects")
    binary = shutil.which(a.rscript) or str(Path(a.rscript).resolve())
    if not Path(binary).is_file():
        lit.fail("Rscript executable not found")
    r_script = Path(__file__).with_name("run_meta.R")
    final = Path(a.out)
    if final.exists():
        lit.fail(f"output already exists: {final}")
    final.parent.mkdir(parents=True, exist_ok=True)
    pending = Path(tempfile.mkdtemp(prefix=f".{final.name}.pending-", dir=final.parent))
    try:
        r_out = pending / "r_output"
        cmd = [binary, str(r_script), str(a.effects), str(a.analysis), str(r_out)]
        process = subprocess.run(cmd, text=True, capture_output=True)
        if process.returncode != 0:
            lit.fail("R run failed: " + (process.stderr.strip() or process.stdout.strip()))
        expected = ("pooled_result.csv", "study_effects_trace.csv", "forest.png",
                    "reproducibility_manifest.csv", "fact_report.md", "confirmed_analysis.csv")
        if any(not (r_out / name).is_file() for name in expected):
            lit.fail("R output incomplete")
        for source in r_out.iterdir():
            if not source.is_file():
                lit.fail("Unexpected nested R output")
            source.replace(pending / source.name)
        r_out.rmdir()
        bound_files = {p.name: lit.sha256(p) for p in pending.iterdir() if p.is_file()}
        run_receipt = {
            "schema": "meta-protocol-run-v1",
            "mode": receipt["mode"],
            "protocol_id": receipt["protocol_id"],
            "confirmation_sha256": lit.sha256(a.confirmation),
            "confirmed_input_sha256": receipt["input_sha256"],
            "run_meta_sha256": lit.sha256(r_script),
            "rscript_binary": str(Path(binary).resolve()),
            "result_sha256": bound_files,
            "meaning": "bound synthetic test" if receipt["mode"] == "synthetic_test" else "bound local run; not final review approval",
        }
        (pending / "protocol_run_receipt.json").write_text(json.dumps(run_receipt, indent=2) + "\n", encoding="utf-8")
        if final.exists():
            lit.fail("output path appeared before commit")
        os.replace(pending, final)
    finally:
        if pending.exists():
            shutil.rmtree(pending)
    print(f"Wrote protocol-bound {receipt['mode']} R run: {final}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in review.INPUTS:
        parser.add_argument("--" + key.replace("_", "-"), dest=key, required=True)
    for key in ("confirmation", "rscript", "out"):
        parser.add_argument("--" + key, required=True)
    a = parser.parse_args()
    try:
        run(a)
    except (ValueError, OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        print(f"Validation: {error}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
