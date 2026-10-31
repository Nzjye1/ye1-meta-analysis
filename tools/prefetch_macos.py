"""Prepare a content-addressed official payload; no native code is executed."""
import concurrent.futures
from pathlib import Path
import sys
from online_setup import download, load_lock

source = Path(__file__).resolve().parents[1]
cache = Path(sys.argv[1]).resolve(); cache.mkdir(parents=True, exist_ok=True)
lock = load_lock(source / 'dependencies/macos-arm64-lock.json')
items = [a for a in lock['artifacts'] if 'docling' in a['profiles']]
with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
    results = list(pool.map(lambda a: download(a, cache, True), items))
print('Official payload verified:', len(results), 'files,', sum(r['bytes'] for r in results), 'bytes')
