# 已有二分类汇总数据分析报告

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


当客户已有独立研究的二分类计数，只需分析报告时，先用 `meta rare` 生成统计，再走本页的汇总数据报告出口。不需要也不得虚构 bibliography、筛选、RoB 或真人审核记录。这是已有汇总数据的条件性重算报告，不是新系统综述。原 `rare-confirm` / `rare-paper` 的完整综述审核门槛没有改变。

## 建立报告项目

`project.json` 使用独立 schema `meta-rare-aggregate-project-v1`，`mode=existing_summary_data`，不能含 `stages`。字段如下：

```json
{
  "schema": "meta-rare-aggregate-project-v1",
  "mode": "existing_summary_data",
  "project_id": "YOUR_PROJECT",
  "question": "Your actual analysis question",
  "population": "Must exactly match the bound MH plan population",
  "direction": "State treatment relative to comparator and event direction",
  "independence_assumption": "State independence assumption and what remains unverified",
  "source": {
    "citation": "Actual supplied source citation or description",
    "locator": "Actual source table locator",
    "supplied_data_description": "Describe supplied author-extracted aggregate counts",
    "verification_status": "not_independently_verified"
  },
  "unit": {"status": "unverified", "value": ""},
  "limitations": ["State actual denominator, follow-up, extraction and independence limitations"],
  "statistics": "../EXISTING_MH_RESULT",
  "original_inputs": ["../ACTUAL_ORIGINAL_COUNT_INPUT.csv", "../ACTUAL_PLAN.json"]
}
```

所有相对路径相对于 project.json。`original_inputs` 必须包含 MH receipt 指向的原计数输入，可另外列明原转录、来源说明等文件。原始 MH input、plan、source 文件和所有统计输出均须存在且哈希匹配。`population` 必须与 MH plan 一致。项目的方向、单位和限制仍由使用者填写，软件不验证科学真伪。

RR/OR 是无量纲比值；`unit` 描述源计数的分母或来源单位，不能把疝修补次数擅称患者数。未核实时保持 `status=unverified,value=""`；明确有来源时，可用 `status=reported,value=实际单位,reference=来源定位`。报告保留该状态和来源限制。

## 正式客户入口

```powershell
# 按 INSTALL.md 明确选择 Python、R 和只读 library 后，先生成新的 MH 统计结果
& './launch.cmd' meta rare --input 'COUNTS.csv' --plan 'PLAN.json' --rscript $env:META_RSCRIPT --out 'FRESH_MH_STATS'

# 使用上述统计结果建立 project.json，然后生成 Word 分析报告
& './launch.cmd' meta run --project 'project.json' --out 'FRESH_REPORT'
& './launch.cmd' meta rare-aggregate-verify --run 'FRESH_REPORT'

# 等价的显式报告命令
& './launch.cmd' meta rare-aggregate-report --project 'project.json' --out 'ANOTHER_FRESH_REPORT'
```

`report_binding.json` 绑定原始文件和本次输出哈希；`rare-aggregate-verify` 核对这些绑定。原统计、来源、项目或报告被修改后验证失败。修改后应建立新项目或新结果目录，不能覆盖旧结果，不支持 resume。`workflow_receipt.json` 的 COMPLETED 仅表示报告文件完整生成，`final=false`，不代表临床审核通过。Word 分页目视与结构、嵌图、结果绑定核查分别记录；未目视不得标为已验收。

## 本地复验
