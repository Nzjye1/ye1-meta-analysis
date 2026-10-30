# Generic review-registration worksheet

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


`registration-draft` creates **author-review material only** from a local protocol JSON. It does not log in to, submit to, or reproduce the current field schema of PROSPERO, OSF, or any other registry. It never generates a registration number or submission date. The draft is labeled `DRAFT_NOT_SUBMITTED_NOT_REGISTERED`. No platform form text is copied into this project.

```text
./launch.cmd meta registration-draft build --protocol protocol.json --out fresh-registration-draft
./launch.cmd meta registration-draft verify --draft fresh-registration-draft
```

Optional `--search-candidate search_candidate.json` preserves a proposed query as **unreviewed**. Optional `--source-chain EXISTING_CHAIN` calls the existing `source_chain.checked_prior` gate and copies its dated batch metadata into the worksheet. If batches are already recorded, the output explicitly forbids a prospective-registration claim. Omitting a chain is not proof that no searches occurred. Inputs and outputs are hashed in `draft_receipt.json`; changes require a new draft directory. Local hashes do not authenticate people or registry status.

Outputs: `registration_draft.json`, `registration_draft.md`, `field_status.csv`, `missing_items.csv`, `draft_receipt.json`. The worksheet carries original question/PICO, eligible designs, outcome, analysis and sensitivity text when supplied. It leaves contact, team, funding, competing interests, ethics applicability, planned dates, full source-specific search strategies, screening/extraction process and certainty methods missing unless the protocol actually contains them. A populated field is still an unreviewed source claim. The author must check every item and use the chosen platform's current requirements separately. Human scientific approval and any eventual submission are outside this command.
