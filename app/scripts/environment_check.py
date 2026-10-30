"""Read-only local Python/R/package/path checks. Never installs or accesses the network."""
import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys


def resolve_r(explicit=None):
    candidate=explicit or os.environ.get("META_RSCRIPT") or shutil.which("Rscript")
    if not candidate:return None
    return shutil.which(candidate) or str(Path(candidate).expanduser().resolve())


def check(explicit=None,library=None):
    root=Path(__file__).resolve().parents[1]
    binary=resolve_r(explicit);chosen=library or os.environ.get("META_R_LIBRARY")
    library=Path(chosen).expanduser().resolve() if chosen else root/"r-library"
    result=dict(platform=platform.platform(),python=sys.version.split()[0],python_executable=sys.executable,
        project_root=str(root),library=str(library),rscript=binary,network_probed=False,
        free_bytes=shutil.disk_usage(root).free,checks={})
    result["checks"]["python_supported"]=sys.version_info>=(3,10)
    result["checks"]["configured_library_exists"]=not chosen or library.is_dir()
    result["checks"]["entry_files"]=all((root/"scripts"/name).is_file() for name in
        ("customer_workflow.py","manuscript.py","run_protocol.py","run_meta.R","research_plan.py","runtime_library.R","render_forest.R"))
    result["word_renderer_on_path"]=shutil.which("soffice") or shutil.which("libreoffice")
    if binary and Path(binary).is_file():
        # JSON string escaping is valid for this R string literal; no shell is involved.
        expr='.libPaths(c('+json.dumps(library.as_posix())+',.libPaths())); cat(R.version.string,"\\n"); for(p in c("metafor","digest","metadat")){cat(p,if(requireNamespace(p,quietly=TRUE)) paste(as.character(packageVersion(p)),find.package(p)) else "MISSING","\\n")}'
        try:
            p=subprocess.run([binary,"--vanilla","-e",expr],capture_output=True,text=True,timeout=40)
            result["r_probe"]=p.stdout.strip();result["r_error"]=p.stderr[-3000:]
            result["checks"]["r_packages"]=p.returncode==0 and "MISSING" not in p.stdout
        except (OSError,subprocess.TimeoutExpired) as e:
            result["checks"]["r_packages"]=False;result["r_error"]=str(e)
    else:result["checks"]["r_packages"]=False;result["r_error"]="Supply --rscript, META_RSCRIPT, or Rscript on PATH"
    result["status"]="READY_LOCAL_ANALYSIS" if all(result["checks"].values()) else "NEEDS_ATTENTION"
    result["word_visual_status"]="NOT_VALIDATED";result["mac_validation"]="NOT_PERFORMED"
    return result


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--rscript");p.add_argument("--library")
    a=p.parse_args();r=check(a.rscript,a.library);print(json.dumps(r,indent=2));sys.exit(0 if r["status"]=="READY_LOCAL_ANALYSIS" else 2)
