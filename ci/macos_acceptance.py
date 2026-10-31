"""Run shared customer entrypoints with public aggregates and synthetic network inputs."""
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys

source = Path(__file__).resolve().parents[1]
runtime = Path(sys.argv[1]).resolve()
out = Path(sys.argv[2]).resolve(); out.mkdir(parents=True, exist_ok=False)
config = json.loads((runtime / 'macos-runtime.json').read_text())


def call(label, args, cwd=None):
    command = ['bash', str(source / 'launch.sh'), str(runtime), 'standard', *args]
    r = subprocess.run(command, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (out / (label + '.log')).write_text(r.stdout, encoding='utf-8')
    print(r.stdout, end='', flush=True)
    if r.returncode: raise RuntimeError(f'{label} failed with exit {r.returncode}')


call('source-and-runtime-check', ['check'])
plos = source / 'ci/fixtures/plos2024'
call('plos-real-public-case', ['meta', 'run', '--project', str(plos / 'project.json'),
                             '--rscript', config['rscript'], '--out', str(out / 'plos')])
call('plos-verify', ['meta', 'aggregate-verify', '--run', str(out / 'plos')])
row = list(csv.DictReader((out / 'plos/statistics/pooled_result.csv').open()))[0]
assert row['k'] == '3' and row['tau_method'] == 'DL'
assert math.isclose(float(row['pooled']), -0.166782152494964, abs_tol=1e-10)
assert math.isclose(float(row['tau2']), 0.00329444175361757, abs_tol=1e-10)
pngs = list((out / 'plos').rglob('*.png'))
assert pngs and all(p.read_bytes().startswith(b'\x89PNG\r\n\x1a\n') for p in pngs)
assert (out / 'plos/paper/manuscript.docx').is_file()
net = source / 'ci/fixtures/network-synthetic'
for tau in ['DL', 'REML']:
    call('network-' + tau, ['meta', 'network', '--input', str(net / ('network-' + tau + '.csv')),
         '--plan', str(net / ('network-' + tau + '.json')), '--rscript', config['rscript'],
         '--out', str(out / ('network-' + tau))], cwd=net)
    r = list(csv.DictReader((out / ('network-' + tau) / 'network_summary.csv').open()))[0]
    assert r['tau_method'] == tau and r['n_treatments'] == '3'
    assert (out / ('network-' + tau) / 'network_graph.png').stat().st_size > 1000
    receipt = json.loads((out / ('network-' + tau) / 'network_receipt.json').read_text())
    assert receipt['planned_tau_method'] == receipt['actual_tau_method'] == tau
    assert receipt['status'] == 'METHOD_EXAMPLE_OR_SYNTHETIC'
summary = dict(status='PASS', platform=sys.platform, machine=os.uname().machine,
    r_packages=config['r_packages'], real_case='PLOS ONE 10.1371/journal.pone.0314334 pain RE/DL',
    network='Synthetic DL and REML parameter isolation; BMJ dependency stack',
    plos_pooled=float(row['pooled']), plos_tau2=float(row['tau2']),
    outputs={str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in out.rglob('*') if p.is_file()})
(out / 'RESULT.json').write_text(json.dumps(summary, indent=2) + '\n')
print(json.dumps(summary, indent=2))
