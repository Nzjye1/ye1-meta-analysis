"""Apple Silicon installer: official frameworks and isolated, locked libraries."""
import argparse
import csv
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parent))
from online_setup import load_lock, read, write, sha, download, cache_path, check_file

SOURCE = Path(__file__).resolve().parents[1]
LOCK = SOURCE / 'dependencies/macos-arm64-lock.json'


def run(root, name, args, env=None):
    args = [str(x) for x in args]
    result = subprocess.run(args, env=env, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, timeout=1800)
    (root / 'setup-logs' / (name + '.txt')).write_text(result.stdout, encoding='utf-8')
    print(result.stdout, end='', flush=True)
    if result.returncode:
        raise RuntimeError(f'{name} exited {result.returncode}; original log retained')
    return result.stdout


def environment(root, library):
    env = os.environ.copy()
    for key in ('PYTHONHOME', 'PYTHONPATH', 'R_HOME', 'R_LIBS', 'R_LIBS_USER', 'R_LIBS_SITE'):
        env.pop(key, None)
    env.update(PYTHONNOUSERSITE='1', PYTHONDONTWRITEBYTECODE='1', PYTHONUTF8='1',
               R_LIBS_USER=str(library), R_LIBS_SITE=str(root / 'no-site-library'),
               R_ENVIRON_USER=str(root / 'no-renviron'), R_PROFILE_USER=str(root / 'no-profile'))
    return env


def probe(root, lock, items, library, label):
    target = root / 'setup-logs' / (label + '-lock.csv')
    with target.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['name', 'version'])
        writer.writeheader()
        writer.writerows({k: a[k] for k in ('name', 'version')} for a in items)
    output = root / 'setup-logs' / (label + '-probe.csv')
    run(root, label, [lock['system_rscript'], '--vanilla', SOURCE / 'app/scripts/probe_locked_packages.R',
                      target, output, 'YES', library], environment(root, library))
    rows = list(csv.DictReader(output.open(encoding='utf-8-sig')))
    if len(rows) != len(items) or any(r['load_ok'] != 'TRUE' or r['r_version'] != lock['r']
            or r['r_arch'] not in ('arm64', 'aarch64')
            or not Path(r['path']).resolve().is_relative_to(library.resolve()) for r in rows):
        raise ValueError('R locked namespace/version/architecture/path verification failed; see probe CSV')
    return rows


def install(root, profile, lock):
    if platform.system() != 'Darwin' or platform.machine() != 'arm64':
        raise ValueError('Apple Silicon macOS is required')
    if int(platform.mac_ver()[0].split('.')[0]) < 14:
        raise ValueError('macOS 14 or newer is required')
    if sys.version.split()[0] != lock['python'] or Path(sys.base_prefix).resolve() != Path(lock['system_python']).parents[1].resolve():
        raise ValueError('Use setup-online.sh and its pinned official framework Python')
    if (root / '.mac-bootstrap').read_text().strip() != sha(LOCK):
        raise ValueError('Runtime bootstrap ownership mismatch')
    write(root / 'python-installed.json', dict(version=sys.version.split()[0], executable=sys.executable,
          base_prefix=sys.base_prefix, platform=platform.platform(), installer='official signed Python pkg'))
    items = [a for a in lock['artifacts'] if profile in a['profiles']]
    receipts = [download(a, root / 'cache', True) for a in items]
    write(root / 'download-receipts.json', receipts)
    r_pkg = next(a for a in items if a['kind'] == 'native-r-pkg')
    if not (root / 'r-installed.json').exists():
        path = cache_path(root / 'cache', r_pkg)
        signature = run(root, 'r-signature', ['/usr/sbin/pkgutil', '--check-signature', path])
        # CRAN's official macOS builder signs as Simon Urbanek, not the
        # organizational display name. Keep exact identity + Apple trust + SHA.
        if 'Developer ID Installer: Simon Urbanek (VZLD955F6P)' not in signature:
            raise ValueError('Unexpected R installer signing identity')
        command = ['/usr/sbin/installer', '-pkg', path, '-target', '/']
        if os.geteuid() != 0:
            command.insert(0, 'sudo')
        run(root, 'r-official-install', command)
        write(root / 'r-installed.json', dict(sha256=r_pkg['sha256'], installer='official signed R pkg'))
    venv = root / 'python/venv'
    if not (venv / 'bin/python').exists():
        run(root, 'python-venv', [lock['system_python'], '-I', '-m', 'venv', venv])
    python = venv / 'bin/python'
    pyitems = [a for a in items if a['kind'] == 'python-wheel']
    pylib = root / 'python/standard'
    if pyitems:
        wheels = root / 'wheel-files'; wheels.mkdir(exist_ok=True)
        for a in pyitems:
            src = cache_path(root / 'cache', a); check_file(src, a)
            dest = wheels / a['filename']
            if not dest.exists(): shutil.copyfile(src, dest)
            check_file(dest, a)
        if not (root / 'python-packages-installed.json').exists():
            stage = root / 'python/standard.staging'; stage.mkdir(exist_ok=True)
            # No dependency resolver, source builds, package index or runner packages.
            run(root, 'python-wheels', [python, '-I', '-m', 'pip', 'install', '--no-index', '--no-deps',
                '--no-compile', '--disable-pip-version-check', '--target', stage,
                *[wheels / a['filename'] for a in pyitems]])
            if pylib.exists(): raise ValueError('Unexpected existing Python target; preserved')
            stage.rename(pylib)
            write(root / 'python-packages-installed.json', dict(packages=len(pyitems)))
        code = "import sys,json,importlib,importlib.metadata as m;sys.path.insert(0,sys.argv[1]);names=json.loads(sys.argv[2]);print(json.dumps({'versions':{n:m.version(n) for n in names},'imports':{n:importlib.import_module(n).__file__ for n in ['bib_dedupe','pdfplumber','numpy','pandas','PIL','requests','pypdfium2']}}))"
        result = json.loads(run(root, 'python-package-probe', [python, '-I', '-c', code, pylib,
                            json.dumps([a['name'] for a in pyitems])]))
        if any(result['versions'][a['name']] != a['version'] for a in pyitems) or any(
                not Path(p).resolve().is_relative_to(pylib.resolve()) for p in result['imports'].values()):
            raise ValueError('Python locked package/path verification failed')
    ritems = [a for a in items if a['kind'] == 'r-mac-binary']
    library = root / 'libraries' / ('r-core' if profile == 'core' else 'r-extended')
    if not library.exists():
        stage = library.with_name(library.name + '.staging'); stage.mkdir(parents=True, exist_ok=True)
        archives = root / 'r-binary-files'; archives.mkdir(exist_ok=True)
        for a in ritems:
            dest = archives / a['filename']
            if not dest.exists(): shutil.copyfile(cache_path(root / 'cache', a), dest)
            check_file(dest, a)
        script = root / 'setup-logs/install-r.R'
        script.write_text('a<-commandArgs(TRUE);install.packages(a[-1],lib=a[1],repos=NULL,type="mac.binary")\n', encoding='utf-8')
        run(root, 'r-binary-install', [lock['system_rscript'], '--vanilla', script, stage,
              *[archives / a['filename'] for a in ritems]], environment(root, stage))
        probe(root, lock, ritems, stage, 'r-staging')
        stage.rename(library)
    rows = probe(root, lock, ritems, library, 'r-final')
    write(root / 'macos-runtime.json', dict(schema='meta-macos-runtime-v1', lock_sha256=sha(LOCK),
        profile=profile, python=str(python), python_library=str(pylib), rscript=lock['system_rscript'],
        r_library=str(library), r_packages=len(rows), source=str(SOURCE)))
    (root / 'READY').write_text(sha(LOCK) + '\n', encoding='utf-8')
    print('READY: ' + str(root), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['install', 'launch'])
    parser.add_argument('--root', required=True)
    parser.add_argument('--profile', choices=['core', 'standard'], default='standard')
    args, rest = parser.parse_known_args()
    root = Path(args.root).expanduser().resolve()
    lock = load_lock(LOCK)
    if root == SOURCE or root.is_relative_to(SOURCE) or SOURCE.is_relative_to(root):
        raise ValueError('Runtime must be separate from source')
    if args.action == 'install':
        install(root, args.profile, lock)
    else:
        if (root / 'READY').read_text().strip() != sha(LOCK): raise ValueError('Runtime is not ready for this lock')
        config = read(root / 'macos-runtime.json')
        if config['profile'] != args.profile: raise ValueError('Installed profile differs')
        env = environment(root, config['r_library'])
        env.update(META_RSCRIPT=config['rscript'], META_R_LIBRARY=config['r_library'])
        if args.profile == 'standard':
            env['META_METHOD_PYTHON_LIBRARY'] = config['python_library']
            env['META_FRONTEND_PYTHON_LIBRARY'] = config['python_library']
        return subprocess.run([config['python'], '-I', '-B', str(SOURCE / 'candidate_entry.py'),
                              *([*rest[1:]] if rest and rest[0] == '--' else rest)], env=env).returncode
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(2)
