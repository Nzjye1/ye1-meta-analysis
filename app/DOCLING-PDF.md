# 本地 Docling PDF 小功能

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


此入口读取已合法持有并登记的本地 PDF，一次最多三篇。它是全文证据候选解析器；不负责下载论文、判断纳入、医学语义确认、统计计算或论文结论。已有的全文登记、来源链、`fulltext-template`、`fulltext-resolve` 继续使用。

## Windows 调用

本次实测环境是 Windows x64、Python 3.14.5、Docling 2.145.0、PyTorch 2.15.0+cpu。可选依赖单独安装，现有 R/Python 分析运行时无需更改。`docling-dependencies/requirements.txt` 锁定本次官方 PyPI wheel 的版本和 SHA-256，具有 Windows/Python 版本限制；不能直接当作 Mac 或其他 Python 版本的已验收安装包。

```powershell
# 首次安装或为本安装器已有目录添加 Docling；先按 INSTALL.md 确认原许可与安装授权。
./setup-online.cmd 'C:/Meta Runtime' docling I_ACCEPT
$runtime = 'C:/Meta Runtime'
$env:META_PYTHON = Join-Path $runtime 'native/python/python.exe'
$env:META_RSCRIPT = Join-Path $runtime 'native/R/bin/Rscript.exe'
$env:META_R_LIBRARY = Join-Path $runtime 'libraries/r-extended'
$env:META_METHOD_PYTHON_LIBRARY = Join-Path $runtime 'python/docling'
$env:META_FRONTEND_PYTHON_LIBRARY = Join-Path $runtime 'python/standard'
$env:PYTHONPATH = $env:META_METHOD_PYTHON_LIBRARY + ';' + $env:META_FRONTEND_PYTHON_LIBRARY
./launch.cmd meta fulltext-docling scan --records 'C:/Meta Studies/records.csv' --documents 'C:/Meta Studies/documents.csv' --models 'C:/Meta Runtime/models' --out 'C:/Meta Studies/fresh-docling-scan'
./launch.cmd meta fulltext-docling verify --scan 'C:/Meta Studies/fresh-docling-scan'
./launch.cmd meta fulltext-template --scan 'C:/Meta Studies/fresh-docling-scan' --targets 'C:/Meta Studies/targets.csv' --out 'C:/Meta Studies/fresh-review-template'
```

`documents.csv` 必需列为 `record_id,source_document,file_path,format,rights_basis`，format 必须为 pdf。登记必须引用 records 中已有的唯一 record_id；文件大小上限 25 MB、物理页数上限 500。已有输出目录拒绝覆盖；修订时使用新目录。全文获取与原始文献身份/版本/许可审核仍按 [来源链说明](OFFLINE-SOURCE-CHAIN.md) 执行。解析成功不会更改全文筛选状态。

## 输出和审核

- 每份 `DOC-…/document.json` 是完整 DoclingDocument，不删减表格结构；`table-N.json` 保留原表的 data/table_cells、行列 offset、row_span/col_span、模型表头标记及来源。`table-N.html` 是保留 rowspan/colspan 的阅读预览；Markdown 仅供阅读，不作为结构化证据。
- `blocks.json` 保留 block/self_ref、文字和原始 prov。`document.txt` 按内容块显示物理页号；表格文字查独立表格 JSON/HTML 和完整 Markdown。`table_cells.json` 保留每个单元格及表格级来源。
- `numeric_candidates.csv` 沿用原候选合同，增加 block/table/cell id、完整原文、源 PDF SHA-256、物理页、原 bbox、行列表头候选、图表标题/脚注引用及同页内容块引用。坐标为 Docling PDF 点数，必须结合 `coord_origin` 解读，不得假定 top-left。页号从 1 起，不等于期刊印刷页。多个来源页无法可靠分配单元格时，page 留空并标记 ambiguous pages。
- 含逗号、分组、比较边界、区间/组合及未知符号的候选带 `numeric_ambiguity`，无法按固定规则解释时 parsed 留空。例如 `0,09` 整串保留，既不拆为 `0`/`09`，也不自动猜为小数；`1,000` 不自动选择小数或千分位；`<0.001` 不视为精确点值。确认入口拒绝直接 `accept`，需要明确 `correct` 值和解释。原文证据不变。
- `semantic_candidates.csv` 为研究、cohort、组别、结局、时间点、单位、n/events/mean/SD/SE/value 提供分开的空字段。原文与 candidate_id/定位已填；缺失不推算、不把 SD 当 SE、不从相邻数字自动决定组别。填写后保存为新的映射审阅文件，保持扫描原件不变。这张表本身不会产生已确认效应值。
- `scan_receipt.json` 绑定原文件、登记表、书目、完整结构证据和候选表哈希，记录模型 manifest、包版本、耗时和进程内存。`verify` 与既有 template/resolve 入口都会复查结构化证据是否改变。哈希是本地一致性检查，不认证人员身份或出版来源。

按 [既有逐值确认流程](FULLTEXT-EXTRACTION.md) 准备 targets 和 reviewer 文件，再运行 `fulltext-resolve`。审核定位应写真实 `page N table N`，并核对原文数字、组别、结局、统计量、单位、脚注和时间点；`#/tables/0` 只是解析器内部 id，不是论文 Table 1。现有 RR/OR/HR/MD/SMD 的 estimate/CI 审核和正式双审要求不变。原始两组计数或均值/SD 仍走已有 derive_effects 路线，适配器不重写统计。

## 已知边界

本轮仅验收带文字层的真实原始研究 PDF，`do_ocr=False`。图片扫描、OCR 数字准确性、公式、图中取数和跨页复杂表格尚未验收。模型没有找到表头/脚注时，完整正文块仍被保存，但不推定关联已正确。跨页续表不自动合并；同页上下文引用只是待人工核对的线索。

推理使用 CPU，关闭远程服务和外部插件，并设置本 worker 的 Hugging Face/Transformers offline 参数；模型在独立安装步骤从官方仓库预取。未调用付费 API，也不需要账户凭据。这些配置不是对宿主软件、外部模型或整台机器的隐私保证。全文及潜在标识始终保留在用户本地工作目录，不提交 Git 或外部聊天。

Docling 代码许可证 MIT；本次 Heron 为 Apache-2.0，TableFormer 模型仓库为 CDLA-Permissive-2.0。具体模型 commit、来源、是否实际用于推理见 `docling-dependencies/model-sources.json`；105 个安装包的来源、许可证元数据和 wheel 哈希见 `pypi-lock.json`。许可证清单是上游元数据记录，不替代客户自己的许可核对。

## 数字证据 v2 与来源冲突

修复版使用 `docling-numeric-evidence-v2`，新增 `source_char_start/end`（零起点、右端不含、Unicode 字符偏移）、`context_sha256`、`numeric_policy`、`normalization_rule` 和 `numeric_evidence_sha256`。逗号/分组、区间、±组合、比例和未知/损坏符号不自动规范化，parsed 留空；简单点小数与明确负号按固定词法规则处理。`verify/template/resolve` 都从绑定原 JSON 重建候选并比较，resolve 不只检查一个可编辑的歧义标记。审阅 vote/audit 保留该证据引用。

旧 Docling 扫描存在未经拦截的 `0,09` 碎片，修复版不接受旧 policy。请用相同原 PDF/records/documents 重扫至新输出目录；旧文件保持原样。新的 candidate ID 含 policy 与原文偏移，不能沿用旧 candidate ID。

已由原页审阅发现的冲突可用 `--source-conflicts LOCAL_CSV` 输入。必需列：`conflict_id,record_id,source_document,source_sha256,field,left_ref,left_quote,right_ref,right_quote,reason`。两处 ref 为本次 Docling JSON 的 `#/texts/N` 或 `#/tables/N/data/table_cells/N`，quote 必须真实存在，PDF hash 必须匹配。产品保留双方文字与页码/prov 到 `source_conflicts.json`，关联候选为 `HOLD_ORIGINAL_SOURCE_CONFLICT`，不得 accept/correct。这里只保存和暴露人工提出的矛盾，不自动识别所有医学矛盾，也不裁定哪一个值正确。
