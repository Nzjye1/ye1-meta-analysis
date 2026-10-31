"""Build a source-only macOS online ZIP from one committed tree; no runtime binaries."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import zipfile

SOURCE = Path(__file__).resolve().parents[1]


def git(*args):
    return subprocess.check_output(['git', '-C', str(SOURCE), *args])


def build(output, tested_commit):
    commit = git('rev-parse', 'HEAD').decode().strip()
    names = git('ls-tree', '-rz', '--name-only', commit).decode().rstrip('\0').split('\0')
    files = {}
    for name in names:
        if name.startswith(('.github/', 'ci/')) or name in ('.gitignore', '.gitattributes'):
            continue
        if name.endswith('.zip') or name.startswith('downloads/MACOS-'):
            continue
        if Path(name).suffix.lower() in ('.exe', '.dll', '.pkg', '.tgz', '.whl', '.dylib'):
            raise ValueError('Unexpected native payload: ' + name)
        files[name] = git('show', commit + ':' + name)
    metadata = dict(schema='meta-macos-online-build-v1', source_commit=commit,
        tested_code_commit=tested_commit, platform='darwin:arm64', minimum_macos='14.0',
        native_runtime_included=False, files={name: dict(bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest()) for name, data in sorted(files.items())})
    files['SOURCE-MANIFEST.json'] = (json.dumps(metadata, indent=2) + '\n').encode()
    output = Path(output).resolve(); output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists(): raise ValueError('Build output already exists; choose a new file')
    with zipfile.ZipFile(output, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(name, (2026, 10, 31, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            z.writestr(info, data)
    with zipfile.ZipFile(output) as z:
        assert z.testzip() is None and set(z.namelist()) == set(files)
        with tempfile.TemporaryDirectory(prefix='meta-macos-zip-', dir=output.parent) as temp:
            z.extractall(temp)
            for name, data in files.items():
                assert (Path(temp) / name).read_bytes() == data
    result = dict(path=str(output), bytes=output.stat().st_size,
        sha256=hashlib.sha256(output.read_bytes()).hexdigest(), source_commit=commit,
        tested_code_commit=tested_commit, members=len(files), crc='PASS', full_extract='PASS')
    print(json.dumps(result, indent=2))
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', required=True)
    p.add_argument('--tested-commit', required=True)
    a = p.parse_args()
    build(a.output, a.tested_commit)
