"""Real public PLOS PDF plus existing numeric safeguards on the offline runtime."""
import csv
import json
import os
from pathlib import Path
import subprocess
import sys

source = Path(__file__).resolve().parents[1]
runtime = Path(sys.argv[1]).resolve()
out = Path(sys.argv[2]).resolve(); out.mkdir(parents=True, exist_ok=False)
fixture = source / 'ci/fixtures/plos2024/original.pdf'
records = out / 'records.csv'; records.write_text('record_id,title\nPLOS2024,PLOS ONE 0314334\n')
docs = out / 'documents.csv'
with docs.open('w', newline='') as f:
    w = csv.DictWriter(f, fieldnames=['record_id','source_document','file_path','format','rights_basis'])
    w.writeheader(); w.writerow(dict(record_id='PLOS2024', source_document='PLOS-0314334', file_path=fixture,
                                   format='pdf', rights_basis='PLOS ONE CC BY 4.0'))
env = os.environ.copy(); env.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', DO_NOT_TRACK='1')
cmd = ['bash', str(source/'launch.sh'), str(runtime), 'docling', 'meta', 'fulltext-docling', 'scan',
       '--records', str(records), '--documents', str(docs), '--models', str(runtime/'models'),
       '--out', str(out/'scan'), '--threads', '3']
subprocess.run(cmd, env=env, check=True, timeout=1200)
subprocess.run(['bash', str(source/'launch.sh'), str(runtime), 'docling', 'meta', 'fulltext-docling',
                'verify', '--scan', str(out/'scan')], env=env, check=True)
receipt=json.loads((out/'scan/scan_receipt.json').read_text())
assert receipt['metrics'][0]['physical_pages'] > 0 and receipt['metrics'][0]['tables'] > 0
assert receipt['candidate_count'] > 0 and list((out/'scan').rglob('document.txt'))
print(json.dumps({'status':'PASS','receipt':receipt['metrics'],'numeric_candidates':receipt['candidate_count'],
                  'review':'AI extraction candidates; no human review claimed'},indent=2))
