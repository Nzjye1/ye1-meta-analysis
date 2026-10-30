"""Windows source candidate launcher; external native runtime, process-local environment."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
APP = ROOT / "app"


def environment():
    env = os.environ.copy()
    # Ported from rc2 / Issue 1: Windows children must not inherit POSIX locales.
    for key in tuple(env):
        if key.upper() in ("LANG", "LANGUAGE") or key.upper().startswith("LC_"):
            env.pop(key)
    for key in ("PYTHONHOME", "PYTHONPATH", "R_HOME", "R_LIBS", "R_LIBS_USER", "R_LIBS_SITE"):
        env.pop(key, None)
    for key, filename in (("R_ENVIRON_USER", "no-user-renviron"), ("R_PROFILE_USER", "no-user-profile")):
        env[key] = str(ROOT / filename)
    env.update(PYTHONNOUSERSITE="1", PYTHONDONTWRITEBYTECODE="1",
               PYTHONUTF8="1", PYTHONIOENCODING="utf-8",
               R_LIBS_SITE=str(ROOT / "no-site-library"))
    runtime = env.get("META_RSCRIPT") or shutil.which("Rscript")
    if runtime:
        env["META_RSCRIPT"] = str(Path(runtime).resolve())
    library = env.get("META_R_LIBRARY")
    if library:
        env["META_R_LIBRARY"] = str(Path(library).resolve())
        env["R_LIBS_USER"] = env["META_R_LIBRARY"]
    else:
        env["R_LIBS_USER"] = str(ROOT / "no-user-library")
    optional = [env[k] for k in ("META_METHOD_PYTHON_LIBRARY", "META_FRONTEND_PYTHON_LIBRARY") if env.get(k)]
    if optional:
        env["PYTHONPATH"] = os.pathsep.join(str(Path(p).resolve()) for p in optional)
    return env


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "meta", "demo"))
    option = parser.parse_args(sys.argv[1:2])
    rest = sys.argv[2:]
    env = environment()
    if option.command == "check":
        if rest:
            parser.error("check takes no options; configure META_RSCRIPT and META_R_LIBRARY")
        status = subprocess.run([sys.executable, "-B", str(ROOT / "tools/check_source.py")], env=env).returncode
        if status:
            return status
        if not env.get("META_RSCRIPT") or not env.get("META_R_LIBRARY"):
            parser.error("set META_RSCRIPT and META_R_LIBRARY; read INSTALL.md")
        cmd = [sys.executable, "-B", str(APP / "scripts/meta.py"), "setup", "--mode", "check",
               "--rscript", env["META_RSCRIPT"], "--library", env["META_R_LIBRARY"], "--work-dir", str(ROOT)]
    elif option.command == "demo":
        demo = argparse.ArgumentParser(description="Wholly synthetic local workflow; fresh output only")
        demo.add_argument("--workspace", required=True)
        args = demo.parse_args(rest)
        if Path(args.workspace).exists():
            parser.error("workspace exists; choose a fresh output")
        if not env.get("META_RSCRIPT") or not env.get("META_R_LIBRARY"):
            parser.error("set META_RSCRIPT and META_R_LIBRARY; read INSTALL.md")
        cmd = [sys.executable, "-B", str(APP / "scripts/meta.py"), "run", "--project",
               str(APP / "validation/project.json"), "--out", str(Path(args.workspace).resolve()),
               "--rscript", env["META_RSCRIPT"]]
    else:
        if not rest:
            parser.error("supply a meta command; read app/CUSTOMER-WORKFLOW.md")
        script = APP / "scripts/meta.py"
        if rest[0] == "pubmed-search":
            script = APP / "scripts/pubmed_search.py"
            rest = rest[1:]
        cmd = [sys.executable, "-B", str(script), *rest]
    return subprocess.run(cmd, env=env).returncode


if __name__ == "__main__":
    sys.exit(main())
