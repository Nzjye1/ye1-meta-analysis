"""Pinned official online setup for a dedicated Windows x64 Meta runtime.

plan is read-only; download never executes payloads; install/verify execute native
code only when explicitly selected. No policy, PATH, credential or elevation edits.
"""
import argparse
import csv
import datetime as dt
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import stat
import subprocess
import sys
import traceback
import urllib.parse
import urllib.request
import zipfile

SOURCE = Path(__file__).resolve().parents[1]
LOCK = SOURCE / 'dependencies/online-lock.json'
PROFILES = ('core', 'standard', 'docling')


def read(p):
    return json.loads(Path(p).read_text(encoding='utf-8-sig'))


def write(p, obj):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    temporary = p.with_name(p.name + '.new')
    temporary.write_text(json.dumps(obj, indent=2) + '\n', encoding='utf-8')
    temporary.replace(p)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def allowed_url(url, model=False):
    u = urllib.parse.urlsplit(url)
    host = (u.hostname or '').lower()
    return (u.scheme == 'https' and not u.username and not u.password and u.port in (None, 443)
            and (host in {'www.python.org', 'cran.r-project.org', 'files.pythonhosted.org', 'huggingface.co',
                         'raw.githubusercontent.com', 'www.apache.org', 'www.latex-project.org'}
                 or (model and (host.endswith('.hf.co') or host.endswith('.huggingface.co')))))


class OfficialRedirects(urllib.request.HTTPRedirectHandler):
    def __init__(self, model=False):
        self.model = model

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not allowed_url(newurl, self.model):
            raise ValueError('unapproved redirect origin: ' + newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def load_lock(path=LOCK):
    lock = read(path)
    if lock.get('schema') != 'meta-official-online-lock-v1':
        raise ValueError('unsupported online lock')
    ids = set()
    for a in lock['artifacts']:
        if a['id'] in ids:
            raise ValueError('duplicate artifact id')
        ids.add(a['id'])
        if not re.fullmatch('[a-f0-9]{64}', a['sha256']):
            raise ValueError('missing fixed SHA256: ' + a['id'])
        if not isinstance(a.get('bytes'), int) or not 0 < a['bytes'] < 4 * 1024 ** 3:
            raise ValueError('missing/invalid exact size: ' + a['id'])
        if not allowed_url(a['url'], a['kind'] == 'model-file'):
            raise ValueError('unapproved official URL: ' + a['id'])
        if Path(a['filename']).name != a['filename'] or any(c in a['filename'] for c in '/\\:'):
            raise ValueError('unsafe cache filename')
        if a.get('model_path'):
            safe_rel(a['model_path'])
    return lock


def selected(lock, profile):
    return [a for a in lock['artifacts'] if profile in a['profiles']]


def safe_rel(name):
    p = PurePosixPath(name)
    if p.is_absolute() or '..' in p.parts or '\\' in name or ':' in name or not p.parts:
        raise ValueError('unsafe relative payload path: ' + name)
    return p


def safe_directory(path):
    p = Path(path).expanduser().absolute()
    for part in [p, *p.parents]:
        if part.is_symlink() or (hasattr(part, 'is_junction') and part.is_junction()):
            raise ValueError('symlink/junction directory refused: ' + str(part))
    return p.resolve()


def managed_root(path, lock_sha, create=False):
    root = safe_directory(path)
    if root == SOURCE or root.is_relative_to(SOURCE) or SOURCE.is_relative_to(root):
        raise ValueError('runtime must be separate from source')
    marker = root / 'online-owner.json'
    if marker.exists():
        if read(marker).get('lock_sha256') != lock_sha:
            raise ValueError('different lock owns this runtime; choose a fresh directory')
    elif create:
        # Bootstrap may have extracted only the exact Python archive before this tool.
        stamp = root / '.official-python-bootstrap'
        if root.exists() and any(root.iterdir()) and not stamp.exists():
            raise ValueError('existing unowned runtime refused')
        if stamp.exists() and stamp.read_text(encoding='utf-8-sig').strip() != next(x for x in load_lock()['artifacts'] if x['kind'] == 'python-runtime')['sha256']:
            raise ValueError('bootstrap owner hash differs from official Python lock')
        root.mkdir(parents=True, exist_ok=True)
        write(marker, dict(schema='meta-online-owner-v1', lock_sha256=lock_sha))
    else:
        raise ValueError('runtime is not owned by this installer')
    return root


def cache_path(cache, item):
    return cache / (item['sha256'] + '_' + item['filename'])


def check_file(path, item):
    if path.is_symlink() or path.stat().st_size != item['bytes'] or sha(path) != item['sha256']:
        raise ValueError('artifact size/hash mismatch; original kept: ' + str(path))


def download(item, cache, allow_network=False, opener=None):
    cache = safe_directory(cache)
    cache.mkdir(parents=True, exist_ok=True)
    target = cache_path(cache, item)
    if target.exists():
        check_file(target, item)
        return dict(id=item['id'], reused=True, bytes=item['bytes'], sha256=item['sha256'])
    if not allow_network:
        raise ValueError('network not enabled and fixed artifact missing: ' + item['id'])
    partial = target.with_name(target.name + '.part')
    if partial.is_symlink():
        raise ValueError('symlink partial file refused')
    offset = partial.stat().st_size if partial.exists() else 0
    if offset > item['bytes']:
        raise ValueError('oversized partial retained; move it aside before retry')
    if offset == item['bytes']:
        check_file(partial, item)
        partial.replace(target)
        return dict(id=item['id'], reused=False, resumed_bytes=offset, bytes=item['bytes'], sha256=item['sha256'])
    request = urllib.request.Request(item['url'], headers={'User-Agent': 'Ye1-Meta-Pinned-Setup/1'})
    if offset:
        request.add_header('Range', 'bytes=%d-' % offset)
    open_fn = opener or urllib.request.build_opener(OfficialRedirects(item['kind'] == 'model-file')).open
    with open_fn(request, timeout=60) as response:
        append = offset and response.status == 206
        if append and not response.headers.get('Content-Range', '').startswith('bytes %d-' % offset):
            raise ValueError('resume range mismatch')
        if not append:
            offset = 0
        total = offset
        with partial.open('ab' if append else 'wb') as output:
            while True:
                block = response.read(1024 * 1024)
                if not block:
                    break
                total += len(block)
                if total > item['bytes']:
                    raise ValueError('download exceeded fixed size')
                output.write(block)
    check_file(partial, item)
    partial.replace(target)
    return dict(id=item['id'], reused=False, resumed_bytes=offset, bytes=item['bytes'], sha256=item['sha256'])


def extract_python(archive, target):
    target = safe_directory(target)
    target.mkdir(parents=True, exist_ok=True)
    reused = []
    missing = []
    with zipfile.ZipFile(archive) as z:
        expected_files = set()
        for info in z.infolist():
            rel = safe_rel(info.filename.rstrip('/'))
            if stat.S_ISLNK(info.external_attr >> 16):
                raise ValueError('archive symlink refused')
            dest = target.joinpath(*rel.parts)
            safe_directory(dest.parent)
            if dest.is_symlink():
                raise ValueError('destination symlink refused')
            if not info.is_dir():
                expected_files.add(rel.as_posix())
                if dest.exists():
                    if not dest.is_file() or dest.read_bytes() != z.read(info):
                        raise ValueError('existing Python file differs; no payload files written; kept: ' + str(dest))
                    reused.append(rel.as_posix())
                else:
                    missing.append(rel.as_posix())
        # Preflight the entire tree before writing any missing payload. Unknown or
        # differing files are preserved, rather than repaired over a live process.
        for existing in target.rglob('*'):
            if existing.is_symlink() or (hasattr(existing, 'is_junction') and existing.is_junction()):
                raise ValueError('existing Python payload link refused')
            if existing.is_file() and existing.relative_to(target).as_posix() not in expected_files:
                raise ValueError('unknown existing Python file; kept: ' + str(existing))
        for info in z.infolist():
            rel = safe_rel(info.filename.rstrip('/'))
            dest = target.joinpath(*rel.parts)
            if info.is_dir():
                dest.mkdir(parents=True, exist_ok=True)
            elif rel.as_posix() in missing:
                dest.parent.mkdir(parents=True, exist_ok=True)
                # Never truncate an existing file, even if it appeared after the
                # preflight. An occupied/racing target stops this attempt.
                with dest.open('xb') as output:
                    output.write(z.read(info))
    if not (target / 'python.exe').is_file():
        raise ValueError('official Python archive layout unsupported')
    return dict(written_files=missing, reused_files=reused, existing_files_opened_for_write=0)


def prepare_python(root, cache, items):
    target = root / 'native/python'
    current = Path(sys.executable).resolve()
    write(root / 'current-phase.json', dict(phase='prepare-target-python', installer_executable=str(current), target_python=str(target / 'python.exe')))
    if current.is_relative_to(target.resolve()):
        raise ValueError('BOOTSTRAP_TARGET_OVERLAP: installer is running from the target Python; '
                         'no target write attempted. Use the corrected setup-online.cmd bootstrap entry.')
    item = next(a for a in items if a['kind'] == 'python-runtime')
    archive = cache_path(cache, item)
    check_file(archive, item)
    (root / 'setup-logs').mkdir(exist_ok=True)
    receipt = root / 'installed-python-runtime.json'
    if receipt.exists():
        check_snapshot(target, read(receipt)['files'])
    extraction = extract_python(archive, target)
    result = json.loads(run([target / 'python.exe', '-I', '-B', '-c',
                             'import sys,struct,json;print(json.dumps([sys.version.split()[0],struct.calcsize("P")*8]))'],
                            root, 'prepared-python-version'))
    if result != ['3.14.5', 64]:
        raise ValueError('prepared Python version/architecture mismatch')
    if not receipt.exists():
        write(receipt, dict(files=snapshot(target), archive_sha256=item['sha256']))
    preparation = dict(schema='meta-python-preparation-v2', status='PYTHON_PREPARED_NOT_FULL_INSTALL',
                       bootstrap_executable=str(current), bootstrap_pid=os.getpid(),
                       target_executable=str(target / 'python.exe'), separate_bootstrap=True,
                       archive_sha256=item['sha256'], version=result, extraction=extraction,
                       r_installer_started=False, ready_written=False)
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%f')
    write(root / 'setup-logs' / (stamp + '-python-preparation.json'), preparation)
    write(root / 'python-preparation.json', preparation)
    return preparation


def process_env(root, python_path=None):
    env = os.environ.copy()
    for key in tuple(env):
        if key.upper() in {'PYTHONHOME', 'PYTHONPATH', 'PYTHONSTARTUP', 'R_HOME', 'R_LIBS', 'R_LIBS_USER', 'R_LIBS_SITE', 'LANG', 'LANGUAGE', 'META_METHOD_PYTHON_LIBRARY', 'META_FRONTEND_PYTHON_LIBRARY'} or key.upper().startswith('LC_'):
            env.pop(key, None)
    env.update(PYTHONNOUSERSITE='1', PYTHONDONTWRITEBYTECODE='1', PYTHONUTF8='1', PYTHONIOENCODING='utf-8',
               R_LIBS_USER=str(root / 'libraries/r-extended'), R_LIBS_SITE=str(root / 'no-site-library'),
               R_ENVIRON_USER=str(root / 'no-user-renviron'), R_PROFILE_USER=str(root / 'no-user-profile'),
               PIP_DISABLE_PIP_VERSION_CHECK='1', PIP_NO_INPUT='1', PIP_CONFIG_FILE=os.devnull)
    if python_path:
        env['PYTHONPATH'] = str(python_path)
    return env


def run(command, root, label, python_path=None):
    logs = root / 'setup-logs'
    logs.mkdir(exist_ok=True)
    write(root / 'current-phase.json', dict(phase=label, command=[str(x) for x in command], installer_executable=sys.executable))
    result = subprocess.run([str(x) for x in command], cwd=root, env=process_env(root, python_path),
                            capture_output=True, encoding='utf-8', errors='replace', timeout=1800)
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%f')
    write(logs / (stamp + '-' + label + '.json'), dict(command=[str(x) for x in command], exit_code=result.returncode,
          stdout=result.stdout, stderr=result.stderr, policy_changed=False))
    if result.returncode:
        raise ValueError('%s failed, exit %d; inspect setup-logs; no fallback/elevation/policy change' % (label, result.returncode))
    return result.stdout


def r_command(exe, destination, log):
    return [str(exe), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/CURRENTUSER', '/SP-',
            '/NOICONS', '/TASKS=', '/MERGETASKS=!desktopicon,!quicklaunchicon,!recordversion,!associate',
            '/DIR=' + str(destination), '/LOG=' + str(log)]


def expected_versions(items, kind):
    return {a['name']: a['version'] for a in items if a['kind'] == kind}


def verify_r(root, items, library):
    rs = root / 'native/R/bin/Rscript.exe'
    ritems = [a for a in items if a['kind'] == 'r-binary']
    plan = root / 'setup-logs/r-expected.csv'
    with plan.open('w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f);writer.writerow(['name', 'version'])
        writer.writerows((a['name'], a['version']) for a in ritems)
    script = root / 'setup-logs/verify-r.R'
    script.write_text('''a <- commandArgs(TRUE)
lib <- normalizePath(a[1], winslash="/", mustWork=TRUE)
.libPaths(c(lib, .Library))
p <- read.csv(a[2])
stopifnot(as.character(getRversion()) == "4.6.1", .Machine$sizeof.pointer == 8)
for (i in seq_len(nrow(p))) {
    n <- p$name[i]
    stopifnot(requireNamespace(n, quietly=TRUE))
    observed <- packageVersion(n)
    expected <- package_version(p$version[i])
    if (!isTRUE(observed == expected)) {
        stop(sprintf("R package version mismatch: %s expected %s (%s), got %s",
                     n, p$version[i], as.character(expected), as.character(observed)))
    }
    actual <- normalizePath(find.package(n), winslash="/")
    stopifnot(startsWith(tolower(actual), paste0(tolower(lib), "/")))
    cat(n, p$version[i], as.character(observed), actual, sep="\\t")
    cat("\\n")
}
''', encoding='utf-8')
    return run([rs, '--vanilla', script, library, plan], root, 'r-namespaces')


def verify(root, items):
    py = root / 'native/python/python.exe'
    actual = run([py, '-I', '-B', '-c', 'import sys,struct,json;print(json.dumps([sys.version.split()[0],struct.calcsize("P")*8]))'], root, 'python-version')
    if json.loads(actual) != ['3.14.5', 64]:
        raise ValueError('Python version/architecture mismatch')
    for kind, folder in [('python-runtime', 'native/python'), ('r-installer', 'native/R')]:
        check_snapshot(root / folder, read(root / ('installed-' + kind + '.json'))['files'])
    for kind, folder in [('python-wheel', 'python/standard'), ('docling-wheel', 'python/docling')]:
        expect = expected_versions(items, kind)
        if not expect:
            continue
        code = 'import importlib.metadata as m,json,sys;print(json.dumps({d.metadata["Name"].lower().replace("_","-"):d.version for d in m.distributions(path=[sys.argv[1]])}))'
        actual = json.loads(run([py, '-I', '-B', '-c', code, root / folder], root, kind + '-versions'))
        for name, version in expect.items():
            if actual.get(name.lower().replace('_', '-')) != version:
                raise ValueError('installed wheel version mismatch: ' + name)
        receipt = root / ('installed-' + kind + '.json')
        check_snapshot(root / folder, read(receipt)['files'])
        modules = ['numpy', 'pandas', 'cryptography', 'pdfplumber', 'bib_dedupe', 'search_query', 'pypdfium2'] if kind == 'python-wheel' else ['docling', 'torch', 'cv2', 'pypdfium2']
        code = ('import sys,json,importlib;from pathlib import Path;'
                'root=Path(sys.argv[1]).resolve();sys.path.insert(0,str(root));out={};'
                '\nfor name in sys.argv[2:]:\n m=importlib.import_module(name);p=Path(m.__file__).resolve();'
                'assert p.is_relative_to(root),(name,str(p));out[name]=str(p)\nprint(json.dumps(out))')
        run([py, '-I', '-B', '-c', code, root / folder, *modules], root, kind + '-imports')
    ritems = [a for a in items if a['kind'] == 'r-binary']
    result = verify_r(root, items, root / 'libraries/r-extended')
    check_snapshot(root / 'libraries/r-extended', read(root / 'installed-r-binary.json')['files'])
    for item in items:
        if item['kind'] in {'model-file', 'notice-file'}:
            check_file(root / ('models' if item['kind'] == 'model-file' else 'licences') / item.get('model_path', item['filename']), item)
    return dict(status='EXACT_NATIVE_COMPONENTS_VERIFIED', r_packages=len(ritems), r_output=result,
                python='3.14.5-x64', r='4.6.1-x64', analysis_not_run=True)


def snapshot(folder):
    result = {}
    for path in sorted(folder.rglob('*')):
        if path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()):
            raise ValueError('installed payload link refused')
        if path.is_file():
            result[path.relative_to(folder).as_posix()] = dict(bytes=path.stat().st_size, sha256=sha(path))
    return result


def check_snapshot(folder, expected):
    if snapshot(folder) != expected:
        raise ValueError('installed files changed; preserve this runtime and choose a fresh root: ' + str(folder))


def commit_stage(stage, target, root):
    if target.exists():
        history = root / 'setup-history'
        history.mkdir(exist_ok=True)
        target.rename(history / (target.name + '-' + dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%f')))
    stage.rename(target)


def install(root, cache, items, profile):
    if sys.platform != 'win32' or platform.machine().lower() not in {'amd64', 'x86_64'}:
        raise ValueError('this installer supports Windows x64 only')
    py = root / 'native/python/python.exe'
    prepare_python(root, cache, items)
    rs = root / 'native/R/bin/Rscript.exe'
    (root / 'setup-logs').mkdir(exist_ok=True)
    if not (root / 'installed-r-installer.json').exists():
        r = next(a for a in items if a['kind'] == 'r-installer')
        run(r_command(cache_path(cache, r), rs.parents[1], root / 'setup-logs/native-r-installer.log'), root, 'r-installer')
        write(root / 'installed-r-installer.json', dict(files=snapshot(rs.parents[1])))
    else:
        check_snapshot(rs.parents[1], read(root / 'installed-r-installer.json')['files'])
    # Official full runtime ZIP already contains pip; never fetch get-pip.py.
    run([py, '-I', '-B', '-m', 'pip', '--version'], root, 'bundled-pip-version')
    check_snapshot(py.parent, read(root / 'installed-python-runtime.json')['files'])
    for kind, folder in [('python-wheel', 'python/standard'), ('docling-wheel', 'python/docling')]:
        wheels = [cache_path(cache, a) for a in items if a['kind'] == kind]
        if not wheels:
            continue
        target = root / folder
        # pip needs valid wheel basenames; download storage is content addressed.
        wheelhouse = root / ('wheelhouse-' + kind)
        wheelhouse.mkdir(exist_ok=True)
        for item in [a for a in items if a['kind'] == kind]:
            path = wheelhouse / item['filename']
            if path.exists():
                check_file(path, item)
            else:
                import shutil
                shutil.copyfile(cache_path(cache, item), path)
        receipt = root / ('installed-' + kind + '.json')
        if receipt.exists():
            if read(receipt)['versions'] != expected_versions(items, kind):
                raise ValueError('wheel lock changed; choose fresh root')
            check_snapshot(target, read(receipt)['files'])
        else:
            if target.exists():
                raise ValueError('unreceipted wheel target retained; choose fresh root')
            stage = root / (folder + '-stage-' + dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%f'))
            stage.parent.mkdir(parents=True, exist_ok=True)
            run([py, '-I', '-B', '-m', 'pip', '--isolated', 'install', '--no-index', '--no-deps', '--no-compile', '--no-cache-dir', '--target', stage,
                 *[wheelhouse / a['filename'] for a in items if a['kind'] == kind]], root, kind)
            files = snapshot(stage)
            stage.rename(target)
            write(receipt, dict(versions=expected_versions(items, kind), files=files))
    library = root / 'libraries/r-extended'
    library.parent.mkdir(parents=True, exist_ok=True)
    r_archives = root / 'package-archives/r'
    r_archives.mkdir(parents=True, exist_ok=True)
    for item in [a for a in items if a['kind'] == 'r-binary']:
        dest = r_archives / item['filename']
        if dest.exists():
            check_file(dest, item)
        else:
            import shutil
            shutil.copyfile(cache_path(cache, item), dest)
    archives = root / 'setup-logs/r-archives.txt'
    archives.write_text('\n'.join(str(r_archives / a['filename']).replace('\\', '/') for a in items if a['kind'] == 'r-binary') + '\n', encoding='utf-8')
    script = root / 'setup-logs/install-r.R'
    script.write_text('a<-commandArgs(TRUE);.libPaths(c(a[1],.Library));f<-readLines(a[2]);install.packages(f,lib=a[1],repos=NULL,type="win.binary");\n', encoding='utf-8')
    rreceipt = root / 'installed-r-binary.json'
    current = read(rreceipt) if rreceipt.exists() else None
    if current:
        check_snapshot(library, current['files'])
    elif library.exists():
        raise ValueError('unreceipted R library retained; choose fresh root')
    if not current or current['versions'] != expected_versions(items, 'r-binary'):
        stage = library.with_name('r-stage-' + dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%f'))
        stage.mkdir()
        run([rs, '--vanilla', script, stage, archives], root, 'r-binary-install')
        verify_r(root, items, stage)
        files = snapshot(stage)
        commit_stage(stage, library, root)
        write(rreceipt, dict(versions=expected_versions(items, 'r-binary'), files=files))
    model_files = {}
    for item in items:
        if item['kind'] in {'model-file', 'notice-file'}:
            dest = root / ('models' if item['kind'] == 'model-file' else 'licences') / item.get('model_path', item['filename'])
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists():
                check_file(dest, item)
            else:
                import shutil
                shutil.copyfile(cache_path(cache, item), dest)
            if item['kind'] == 'model-file':
                model_files[item['model_path']] = item['sha256']
    if model_files:
        write(root / 'models/model_manifest.json', dict(schema='meta-docling-models-v1', files=model_files,
              sources=read(SOURCE / 'app/docling-dependencies/model-sources.json'), scope='pinned CPU layout/TableFormer; optional'))
    result = verify(root, items)
    optional = bool(model_files)
    write(root / 'runtime.json', dict(schema='meta-persistent-runtime-v1', python='native/python/python.exe', rscript='native/R/bin/Rscript.exe',
          core_r='libraries/r-extended', extended_r='libraries/r-extended', standard_python='python/standard',
          docling_python='python/docling' if optional else None, docling_models='models' if optional else None))
    write(root / 'READY.json', dict(result, lock_sha256=sha(LOCK), optional_docling=optional,
                                  profile=profile,
                                  python_distributions=sum(a['kind'] == 'python-wheel' for a in items),
                                  docling_distributions=sum(a['kind'] == 'docling-wheel' for a in items)))
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['plan', 'download', 'prepare-python', 'install', 'verify'])
    p.add_argument('--profile', choices=PROFILES, default='standard')
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--cache', type=Path)
    p.add_argument('--allow-network', action='store_true')
    p.add_argument('--accept-third-party-terms', action='store_true')
    a = p.parse_args()
    root = None
    try:
        lock = load_lock(); items = selected(lock, a.profile)
        if a.action == 'prepare-python':
            items = [x for x in items if x['kind'] == 'python-runtime']
        plan = dict(profile=a.profile, artifacts=len(items), download_bytes=sum(x['bytes'] for x in items),
                    root=str(a.root.absolute()), native_binaries_shipped=False, optional_docling=a.profile == 'docling',
                    first_network_required=True, lock_sha256=sha(LOCK), r_installer_effects='dedicated current-user R install; HKCU uninstall bookkeeping may be created; PATH/associations/current R registration disabled')
        if a.action == 'plan':
            print(json.dumps(plan, indent=2)); return 0
        if a.action in {'install', 'prepare-python'} and not a.accept_third_party_terms:
            raise ValueError('install requires actual acceptance of third-party terms; use --accept-third-party-terms after review')
        cache = safe_directory(a.cache or (a.root / 'downloads'))
        root = managed_root(a.root, sha(LOCK), create=a.action != 'verify')
        if a.action in {'install', 'prepare-python'}:
            write(root / 'last-setup-attempt.json', dict(status='INSTALLING', action=a.action, profile=a.profile, lock_sha256=sha(LOCK), installer_executable=sys.executable))
        if a.action in {'download', 'install', 'prepare-python'}:
            write(root / 'current-phase.json', dict(phase='verify-downloads', action=a.action, installer_executable=sys.executable))
            receipts = [download(x, cache, a.allow_network) for x in items]
            write(root / 'download-receipt.json', dict(plan=plan, files=receipts, payloads_executed=False))
        if a.action == 'download':
            print(json.dumps(dict(status='FIXED_DOWNLOADS_VERIFIED_NO_EXECUTION', **plan), indent=2)); return 0
        if a.action == 'prepare-python':
            result = prepare_python(root, cache, items)
            write(root / 'last-setup-attempt.json', dict(status='PYTHON_PREPARED_NOT_FULL_INSTALL', action=a.action, profile=a.profile, installer_executable=sys.executable))
            print(json.dumps(result, indent=2)); return 0
        result = install(root, cache, items, a.profile) if a.action == 'install' else verify(root, items)
        if a.action == 'install':
            write(root / 'last-setup-attempt.json', dict(status='VERIFIED', profile=a.profile, lock_sha256=sha(LOCK)))
        print(json.dumps(result, indent=2)); return 0
    except (OSError, ValueError, KeyError, zipfile.BadZipFile, subprocess.SubprocessError) as error:
        details = dict(status='BLOCKED', action=a.action, profile=a.profile, error=str(error), error_type=type(error).__name__,
                       errno=getattr(error, 'errno', None), winerror=getattr(error, 'winerror', None),
                       installer_executable=sys.executable, policy_changed=False, no_fallback=True)
        if root is not None and a.action in {'install', 'prepare-python'}:
            try:
                details['target_python'] = str(root / 'native/python/python.exe')
                phase_file = root / 'current-phase.json'
                details['phase'] = read(phase_file).get('phase') if phase_file.exists() else 'entry'
                stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%f')
                log = root / 'setup-logs' / (stamp + '-failure.json')
                write(log, dict(details, traceback=traceback.format_exc()))
                details['failure_log'] = str(log)
                write(root / 'last-setup-attempt.json', details)
            except OSError:
                pass
        print(json.dumps(details, indent=2))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
