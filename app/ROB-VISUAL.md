# Reviewed RoB evidence display

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


Run `./launch.cmd meta rob-visual --quality-dir COMPLETED_QUALITY_DIR --rscript $rscript --out NEW_DIR` after `quality-resolve` has produced a complete exploratory or formal review ledger. The entry calls `evidence_quality.verify_quality`, checks every existing per-domain source file hash, and makes `rob_judgments.png`, `rob_visual.docx`, a short Markdown explanation, and a hash receipt. The figure prints the reviewer-entered judgment text in each cell; blank domain cells stay blank. It does not assign any new risk category, authenticate a reviewer, or convert an Agent suggestion to a decision. Exploratory review remains labeled draft.

The installed `robvis` package was inspected for reuse. Its chart entry assumes official instrument-specific columns and captions; this project currently records generic design-specific evidence slots, so forcing those values into a RoB 2 or QUADAS graphic would mislabel domains. This bounded display uses base R graphics and the existing standard-library Word renderer until a correctly licensed official instrument contract is implemented. It is not an official RoB 2/ROBINS-I/QUADAS chart or score.
