# Dependencies and license inventory

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


Current customer source delivery uses `dependencies.lock.json` and the local-only `meta.py setup` entry described in `CLIENT-SETUP.md`. Default check performs no library modification; explicit prepare uses exact-version native local archives or existing compatible native package libraries, writes only a fresh project-private target, verifies loading and records provenance. There is no online fallback or dependency on development Skill directories. Historical `tools/install.R`/unversioned preparation helpers are not in the customer candidate. Official-source URLs in a cache index are declarations with local hash checks, not independent CRAN authentication.

The bounded PubMed module uses Python's standard library and NCBI's public [E-utilities](https://www.ncbi.nlm.nih.gov/books/NBK25497/) ESearch/EFetch endpoints. It needs no paid API, account, API key, or new installed library. NCBI documents a no-key limit of 3 requests/second; this module spaces requests by at least 0.42 seconds in one process and caps its own retrieval at 500 records. Multiple simultaneous callers would need coordination before deployment. The [ESearch/EFetch parameter reference](https://www.ncbi.nlm.nih.gov/books/NBK25499/) describes history-based paging and PubMed retrieval. NCBI access on the current Windows host failed with local `WinError 10013`; no live search result was obtained or claimed.

Windows tested: `E:/Tools/R/R-4.6.1/bin/Rscript.exe` (R 4.6.1) and Python 3.14 standard library. The project-local `r-library/` holds these official CRAN Windows binaries; versions and `License` fields were read from each installed `DESCRIPTION`:

| Package | Version | License field |
|---|---:|---|
| metafor | 5.2-1 | GPL (>= 2) |
| metadat | 1.6-0 | GPL (>= 2) |
| mathjaxr | 2.0-0 | GPL-3 |
| pbapply | 1.7-5 | GPL (>= 2) |
| numDeriv | 2016.8-1.1 | GPL-2 |
| digest | 0.6.39 | GPL (>= 2) |

R's recommended/base packages such as `Matrix` and `nlme` come from the local R installation; they were not copied into this directory. `meta` is not installed; it imports `metafor`, so it is not an independent numerical validator. Python scripts use only the standard library. No RoB questionnaire, published instrument text, article PDF, or third-party literature database is bundled. `rob_plan.json` records a user-supplied tool name/version and domain names; permission for reproducing an actual instrument must be checked at its official source before adding any restricted text.

`derive_effects.R` uses the installed `metafor::escalc` for 2x2 RR/OR and group-summary MD/SMD; `digest` computes SHA-256 from local bytes. The RIS parser uses only Python's standard library. The public numeric demonstration reads `metadat::dat.bcg` from the already installed package (13 rows, metadat 1.6-0, GPL (>= 2)) and does not bundle article PDFs. The validation against a separate `escalc` call is a reproducibility check of the same engine; the first RR and synthetic RR/OR/MD/SMD point values are additionally checked by analytic arithmetic. These checks do not validate any original study interpretation. Official references: [metafor escalc](https://wviechtb.github.io/metafor/reference/escalc.html), [metadat dat.bcg](https://wviechtb.github.io/metadat/reference/dat.bcg.html), and [EndNote RIS export structure](https://support.clarivate.com/Endnote/s/article/EndNote-Directions-for-implementing-EndNote-Direct-Export).

These are development runtime files, not a release bundle. Do not redistribute them without checking the corresponding package licenses and dependencies. The numerical package is [metafor on CRAN](https://cran.r-project.org/package=metafor); [meta on CRAN](https://cran.r-project.org/package=meta) is noted for future workflow work.
