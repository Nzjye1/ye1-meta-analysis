# Europe PMC open-full-text candidate adapter

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


`./launch.cmd meta oa-fulltext --records SOUGHT_RECORDS.csv --metadata EUROPE_PMC_RESPONSE.json --local-base-url http://127.0.0.1:PORT/ --out NEW_DIR` runs the **offline/local HTTP** test mode. The records should be the title/abstract included reports sought for full text, with stable `record_id`, DOI and/or PMID. The metadata file has the Europe PMC REST search-response shape `resultList.result[]` with `pmid`, `doi`, `pmcid` and `isOpenAccess`. It is a locally supplied response snapshot, not independently authenticated as a live Europe PMC result. At most 20 distinct records are accepted per run.

The response must have an XML MIME type, at most 16,000,000 bytes, a consistent Content-Length when present, and a JATS article root. Article-meta PMCID and at least one bibliography DOI/PMID must match. An article-level license under front/article-meta/permissions/license must be explicit CC BY 3.0/4.0 or CC0 1.0. Original XML and a plain-text derivative are saved with SHA-256 only after validation; absent, conflicting, noncommercial, or unrecognized license remains blocked. Attribution and downstream reuse duties remain with the user.

`oa_attempts.csv` records every candidate and precise no-match, no-OA, HTTP/MIME/size, JATS/identity/license failure. `local_retrieval_attempts_template.csv` marks a saved file `alternative_candidate`, **never retrieved_primary or human verified**. In `fulltext-access` it counts as a file obtained for PRISMA retrieval, with assessment pending and no extraction document exported. Acceptance requires a new identity conclusion/evidence and version conclusion/evidence; a status-only revision cannot promote the pending template. `formal_review` is reviewer-declared and may export to `documents.csv`; `exploratory_agent` remains in an explicitly labeled separate file and cannot enter the formal extraction list or mark full-text assessment complete. See `OFFLINE-SOURCE-CHAIN.md` for columns. Each actual article's reuse terms must be checked; the software enforces an explicit CC allowlist without requiring a person to approve every OA file individually. Import the template only when its IDs exactly match sought records. The adapter cannot determine eligibility, add page numbers to JATS text, or finish a systematic review. The original XML remains the source for any later section/element locator review.
