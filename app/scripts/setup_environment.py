"""Locked native dependency check/private preparation. Local caches or explicit native libraries only; no network."""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path,PurePosixPath
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from environment_check import resolve_r

ROOT=Path(__file__).resolve().parents[1]
class SetupError(ValueError):pass
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def probe(binary,lock,target,sources,strict=False,work_dir=None):
    with tempfile.TemporaryDirectory(prefix=".meta-dependency-probe-",dir=work_dir or ROOT) as tmp:
        table=Path(tmp)/"lock.csv";output=Path(tmp)/"probe.csv"
        with table.open("w",newline="",encoding="utf-8") as f:
            w=csv.DictWriter(f,fieldnames=["name","version"]);w.writeheader();w.writerows({k:p[k] for k in ("name","version")} for p in lock["packages"])
        command=[binary,"--vanilla",str(ROOT/"scripts/probe_locked_packages.R"),str(table),str(output),"YES" if strict else "NO",str(target),*map(str,sources)]
        p=subprocess.run(command,capture_output=True,text=True,timeout=60)
        if p.returncode or not output.is_file():raise SetupError("R dependency probe failed: "+p.stderr[-3000:])
        with output.open(encoding="utf-8-sig",newline="") as f:rows=list(csv.DictReader(f))
        return rows,p.stderr[-3000:]
def compatible(rows,lock):
    return bool(rows) and all(r["load_ok"]=="TRUE" and r["r_version"]==lock["r_version"] and normalize_arch(r["r_arch"])==normalize_arch(platform.machine()) for r in rows)
def normalize_arch(arch):
    arch=arch.lower()
    return "x86_64" if arch in {"amd64","x86_64","x64"} else "arm64" if arch in {"arm64","aarch64"} else arch
def cache_entries(cache,lock,host):
    if cache is None:return {}
    folder=Path(cache).expanduser().resolve();index=folder/"cache-index.json"
    if not index.is_file():raise SetupError("Explicit cache needs cache-index.json with local archive hashes and declared CRAN source")
    content=json.loads(index.read_text(encoding="utf-8"));result={};expected={p["name"]:p["version"] for p in lock["packages"]}
    for row in content.get("packages",[]):
        name=row["name"]
        if name not in expected:continue
        if name in result or row.get("version")!=expected[name] or row.get("host")!=host:raise SetupError("Cache name/version/host mismatch: "+name)
        if not row.get("source_url","").startswith(("https://cran.r-project.org/","https://cloud.r-project.org/")):raise SetupError("Cache requires a declared official CRAN source URL; it is not downloaded or authenticated here")
        filename=row["filename"]
        if Path(filename).name!=filename or "/" in filename or "\\" in filename:raise SetupError("Cache archive must be a simple local filename")
        path=folder/filename
        if not path.is_file() or sha(path)!=row.get("sha256"):raise SetupError("Cached archive missing/hash mismatch: "+name)
        suffix=".zip" if host.startswith("win32:") else ".tgz"
        if not filename.endswith(suffix):raise SetupError("Only matching native binary archives are supported; source compilation is not automatic")
        if filename!=name+"_"+expected[name]+suffix:raise SetupError("Cache filename must retain the native R package_name_version archive convention")
        if suffix==".zip":
            with zipfile.ZipFile(path) as z:
                if z.testzip():raise SetupError("Cached ZIP CRC failure")
                for item in z.infolist():
                    rel=PurePosixPath(item.filename)
                    if rel.is_absolute() or ".." in rel.parts or "\\" in item.filename or not rel.parts or rel.parts[0]!=name or (item.external_attr>>16)&0o170000==0o120000:raise SetupError("Unsafe cached ZIP member")
                desc=z.read(name+"/DESCRIPTION").decode("utf-8")
        else:
            with tarfile.open(path,"r:gz") as z:
                for item in z.getmembers():
                    rel=PurePosixPath(item.name)
                    if rel.is_absolute() or ".." in rel.parts or "\\" in item.name or not rel.parts or rel.parts[0]!=name or item.issym() or item.islnk():raise SetupError("Unsafe cached TGZ member")
                f=z.extractfile(name+"/DESCRIPTION")
                if f is None:raise SetupError("Missing cached DESCRIPTION")
                desc=f.read().decode("utf-8")
        fields=dict(line.split(":",1) for line in desc.splitlines() if line and not line[0].isspace() and ":" in line)
        if fields.get("Package","").strip()!=name or fields.get("Version","").strip()!=expected[name]:raise SetupError("Archive DESCRIPTION disagrees with dependency lock")
        result[name]=dict(path=str(path),sha256=sha(path),declared_source=row["source_url"],origin_independently_authenticated=False)
    return result
def host_key():
    return sys.platform+":"+normalize_arch(platform.machine())
def run(a):
    lock_path=ROOT/"dependencies.lock.json";lock=json.loads(lock_path.read_text(encoding="utf-8"))
    if sys.version_info<(3,10):raise SetupError("Native Python >=3.10 required; setup does not install Python")
    host=host_key()
    if host not in lock["supported_hosts"]:raise SetupError("Host not in this candidate lock: "+host)
    binary=resolve_r(a.rscript)
    if not binary or not Path(binary).is_file():raise SetupError("Native Rscript required: --rscript, META_RSCRIPT or PATH; no system installation is performed")
    target=Path(a.library or os.environ.get("META_R_LIBRARY") or ROOT/"r-library").expanduser().resolve()
    sources=[Path(p).expanduser().resolve() for p in a.source_library]
    if any(not p.is_dir() for p in sources):raise SetupError("An explicitly supplied source-library directory does not exist")
    work=Path(a.work_dir).expanduser().resolve() if a.work_dir else ROOT
    if not work.is_dir():raise SetupError("--work-dir must be an existing writable customer directory")
    result=dict(mode=a.mode,host=host,rscript=binary,target_library=str(target),lock_sha256=sha(lock_path),network_requested=False,system_modified=False,runtime_included=False)
    rows,warnings=probe(binary,lock,target,[],strict=True,work_dir=work)
    result.update(packages=rows,warnings=warnings)
    protected={Path(row["r_home"]).resolve() for row in rows}
    protected.update(Path(p).resolve() for row in rows for p in row["r_system_libraries"].split("|") if p)
    if any(target==p or target.is_relative_to(p) for p in protected):
        result["status"]="BLOCKED_TARGET_IS_SYSTEM_R_DIRECTORY";return result,2
    if compatible(rows,lock):result["status"]="READY_EXISTING_LOCKED_PRIVATE_LIBRARY";return result,0
    if any(r["r_version"]!=lock["r_version"] for r in rows):result["status"]="BLOCKED_R_VERSION_MISMATCH";result["required_r_version"]=lock["r_version"];return result,2
    if any(normalize_arch(r["r_arch"])!=normalize_arch(platform.machine()) for r in rows):result["status"]="BLOCKED_NATIVE_R_ARCHITECTURE_MISMATCH";return result,2
    if a.mode=="check":result["status"]="NEEDS_LOCKED_PRIVATE_DEPENDENCIES";return result,2
    if target.exists():raise SetupError("Existing library is not lock-ready; preserve it and choose a fresh --library target")
    archives=cache_entries(a.cache,lock,host)
    available,source_warnings=probe(binary,lock,target,sources,strict=False,work_dir=work);by_name={r["name"]:r for r in available}
    missing=[p["name"] for p in lock["packages"] if p["name"] not in archives and by_name[p["name"]]["load_ok"]!="TRUE"]
    if missing:
        result.update(status="BLOCKED_MISSING_LOCAL_DEPENDENCIES",missing=missing,available_sources=available,
            next_action="Provide exact-version native official cache with cache-index.json, or explicit compatible --source-library. No online fetch is attempted.")
        return result,2
    target.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".meta-native-library-",dir=target.parent) as tmp:
        stage=Path(tmp)/"library";stage.mkdir();origins={}
        for package in lock["packages"]:
            name=package["name"]
            if name in archives:origins[name]=dict(kind="declared_cran_native_cache",**archives[name]);continue
            source=Path(by_name[name]["path"])
            if any(p.is_symlink() for p in source.rglob("*")):raise SetupError("Installed package symlink requires separate review: "+name)
            shutil.copytree(source,stage/name)
            for file in source.rglob("*"):
                if file.is_file() and sha(file)!=sha(stage/name/file.relative_to(source)):raise SetupError("Private copy mismatch: "+name)
            origins[name]=dict(kind="existing_native_locked_package",source=str(source),description_sha256=sha(source/"DESCRIPTION"),origin_independently_authenticated=False)
        for package in lock["packages"]:
            name=package["name"]
            if name in archives:
                p=subprocess.run([binary,"--vanilla",str(ROOT/"scripts/install_cached_native.R"),str(stage),archives[name]["path"]],capture_output=True,text=True,timeout=180)
                if p.returncode:raise SetupError("Local binary installation failed: "+p.stderr[-3000:])
        verified,stage_warnings=probe(binary,lock,stage,[],strict=True,work_dir=work)
        if not compatible(verified,lock):raise SetupError("Staged private library failed exact-version/native namespace check")
        receipt=dict(schema="meta-private-prepare-v1",host=host,r_version=lock["r_version"],lock_sha256=sha(lock_path),sources=origins,
            network_requested=False,system_library_modified=False,package_versions={p["name"]:p["version"] for p in lock["packages"]})
        (stage/"meta-prepare-receipt.json").write_text(json.dumps(receipt,indent=2),encoding="utf-8")
        if target.exists():raise SetupError("Library target appeared before commit")
        stage.replace(target)
    rows,warnings=probe(binary,lock,target,[],strict=True,work_dir=work)
    ok=compatible(rows,lock)
    result.update(status="READY_PREPARED_LOCKED_PRIVATE_LIBRARY" if ok else "BLOCKED_POST_COMMIT_LIBRARY_CHECK",packages=rows,sources=origins,warnings=warnings)
    return result,0 if ok else 2
if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--mode",choices=("check","prepare"),default="check")
    p.add_argument("--rscript");p.add_argument("--library");p.add_argument("--source-library",action="append",default=[]);p.add_argument("--cache");p.add_argument("--work-dir")
    a=p.parse_args()
    try:r,code=run(a)
    except (SetupError,OSError,KeyError,ValueError,TypeError,AttributeError,zipfile.BadZipFile,tarfile.TarError,subprocess.TimeoutExpired) as e:r=dict(status="BLOCKED",error=str(e),network_requested=False,system_modified=False);code=2
    print(json.dumps(r,indent=2));sys.exit(code)
