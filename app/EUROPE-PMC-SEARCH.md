# Europe PMC search to local source and OA candidate

> 从源码根目录执行命令。`$runtime` 是用户已确认可用的依赖目录；源码 ZIP 不含该目录。路径均为可替换的示例。

```powershell
$runtime = 'C:/Meta Runtime'
$rscript = Join-Path $runtime 'native/R/bin/Rscript.exe'
$env:META_PYTHON = Join-Path $runtime 'native/python/python.exe'
$env:META_RSCRIPT = $rscript
$env:META_R_LIBRARY = Join-Path $runtime 'libraries/r-extended'
$env:META_METHOD_PYTHON_LIBRARY = Join-Path $runtime 'python/standard'
$env:META_FRONTEND_PYTHON_LIBRARY = $null
$env:PYTHONPATH = $env:META_METHOD_PYTHON_LIBRARY
$env:PYTHONUTF8 = '1'
```


This bounded adapter calls the official public Europe PMC REST `search` endpoint with **public query terms only**. It saves the exact query, UTC request times, cursor pages, returned count, response bytes and SHA-256 hashes, stable `source:id` identifiers, a standard bibliographic CSV, and the existing `literature.py` import. A local hash is a file-consistency check, not authentication of Europe PMC or a claim that the search strategy is comprehensive. Europe PMC includes PubMed-indexed records, so these routes have overlapping coverage and are not two independent complete database searches.

```text
./launch.cmd meta europe-pmc-search --query 'TITLE:"vitamin D" AND OPEN_ACCESS:Y AND FIRST_PDATE:[2024 TO 2024]' --source-label EPMC-VITD-2024-TECH --max-records 4 --page-size 2 --online --out fresh-search
./launch.cmd meta source-update --source fresh-search/bibliography --batch-ledger batches.csv --out fresh-chain
```

`--max-records` and `--page-size` are each limited to 1–20. `--fixture-dir` reads `page_000.json`, `page_001.json`, etc. instead of calling the service. The program does not retry, follow redirects, or download full text. It preserves each raw response. A capped result is `LIVE_QUERY_LIMITED` or `FIXTURE_QUERY_LIMITED`; a failed response is `FAILED` and has no ready bibliography. For a protocol claim of a complete local result set, the locally recorded hit count must reconcile, and real mode additionally requires an explicitly reviewed query and matching PICO hash. Even then, the scientific scope and actual database origin still require review. Title, year, and author strings are source metadata, not validated original articles; one returned title contained inline HTML.

The `bibliography` folder can enter `source-update` or `merge_sources`. Duplicates remain candidates until reviewed; source-update without dispositions remains pending. Screening and full-text inclusion are separate decisions. CSV/RIS imports from other services remain manual and must not be labeled as complete online searches.

To link a **previously obtained** Europe PMC OA JATS candidate to a search record, use:

```text
./launch.cmd meta oa-bridge --search fresh-search --oa existing-oa-output --out fresh-bridge
```

This checks the saved search and OA receipts, DOI/PMID identity and source bytes, then writes a record crosswalk and a `local_retrieval_attempts_template.csv` using the imported stable `record_id`. It makes no network request and does not accept the candidate as the assessed full text, extracted source, or included study. Identity/version suitability, screening, rights, and value review retain their existing explicit stages. See `OA-FULLTEXT.md` and `OFFLINE-SOURCE-CHAIN.md`.
