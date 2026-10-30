# Search-query and BibDedupe front end (Windows development source)

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


This route reuses `search-query==0.15.0` for **local syntax checking and draft translation** and `bib-dedupe==0.11.0` for **candidate citation pairs**. It does not search a database through search-query, delete a report because BibDedupe labeled it duplicate, or equate two reports with one underlying study. The established source chain remains the authority for imported bytes, stable record IDs, review history, and per-record dispositions. Source packages and transitives are in the project-private `frontend-python-library`; exact installed versions, local metadata/license-file hashes and PyPI source links are in `FRONTEND-PRIVATE-LOCK-20261028.json`. `rispy` was not installed: the existing bounded RIS importer already preserves raw bytes and repeated fields.

## Agent route

1. From a structured idea, run `./launch.cmd meta prepare --idea IDEA.json --out NEW_DIR`. Review the PICO and `search_candidate.json`. For an existing local candidate, run:

   `./launch.cmd meta front-query --candidate search_candidate.json --platform pubmed --translate wos --out NEW_QUERY_CHECK`

   Inspect `query_review.json` and `parser_diagnostics.txt`. A syntax error creates `QUERY_SYNTAX_REVIEW_REQUIRED` with exit code 2; a successful parse remains `PENDING_HUMAN_REVIEW`. Translation is a draft that must be checked against the target database, including subject headings, limits and platform-specific behavior. It does not execute PubMed, WoS or EBSCOHost.

2. Import lawful CSV or RIS using `literature.py import` or `import_ris.py`; retain their original import directories. Use `meta.py source-update --source IMPORT_DIR --batch-ledger BATCHES.csv --out NEW_CHAIN` for an initial or updated search. Its source ledger and original bytes are checked. `NEEDS_DEDUP_REVIEW` is expected before decisions.

3. Run `./launch.cmd meta front-dedupe --chain NEW_CHAIN --out NEW_CANDIDATE_DIR`. The overlay calls BibDedupe `prep -> block -> match` with one CPU, combines its cross-source suggestions with existing exact DOI/PMID/title candidates, and writes `candidate_pairs.csv`, `pair_decisions_template.csv`, `pair_review_current.csv`, `pair_decision_history.csv`, `source_chain_disposition_template.csv`, and a receipt. Every candidate has a stable pair ID; labels `duplicate` or `maybe` are still **candidates**, never automatic removals. BibDedupe's `search_set` is the imported source label. Same-source exact matches remain available from the existing matcher. Original records stay untouched.

4. Review each pair as `same_report`, `different_report`, or `uncertain` with reason/reviewer/date. For `same_report`, identify which of the two **record IDs** is retained. Submit a complete decision-history CSV with `--decisions HISTORY.csv --prior-review PREVIOUS_CANDIDATE_DIR --out NEXT_CANDIDATE_DIR`. The new version checks that earlier rows are preserved exactly; a changed decision needs `revision_of`, a reason and nondecreasing date. An unfinished review remains `NEEDS_PAIR_REVIEW`. An all-resolved pair review is only `PAIR_REVIEW_COMPLETE_RECORD_DISPOSITIONS_REQUIRED`.

5. Make explicit reviewer-attested decisions for **every record** in the source-chain disposition format; labels are not identity authentication. Use `source_chain_disposition_template.csv` as an empty template and the pair audit as evidence; never auto-fill keep/remove from package labels. Run `meta.py source-update --prior OLD_CHAIN --dispositions COMPLETED_RECORD_DECISIONS.csv --out NEXT_CHAIN`, then verify `READY_FOR_SCREENING` or inspect unresolved state. The existing source-chain checks retained IDs, exact/suspected match evidence and ordered reversals. `front-verify --out DIR` checks adapter receipts and source/decision bytes. Multi-report same-cohort assessment happens later at the study/effect stage, not during bibliographic deduplication.

## Bounded online technical validation

## Directed tests and boundaries

Package source and API references: https://pypi.org/project/search-query/0.15.0/ ; https://pypi.org/project/bib-dedupe/0.11.0/ ; https://colrev-environment.github.io/bib-dedupe/api.html ; https://colrev-environment.github.io/bib-dedupe/usage.html . Installed package metadata and license files are local claims about the selected library, not independent PyPI artifact signatures. Any redistribution needs notice review.
