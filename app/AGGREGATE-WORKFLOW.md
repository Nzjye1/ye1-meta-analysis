# 已有汇总数据分析

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


本入口用于客户已提供研究级汇总数据时的连续结局 MD 复算。它只复现所提供的作者提取数据，不执行新的检索、筛选、全文提取核验、纳入判断或风险偏倚评估，不生成 PRISMA 流程，不构成新系统综述。原 [完整综述客户流程](CUSTOMER-WORKFLOW.md) 及其方法选择、协议和来源审核门槛继续适用完整综述项目。

## 建立项目

先按 [INSTALL.md](../INSTALL.md) 显式选择原生 Python、R 和隔离 library。复制 [汇总数据项目框架](templates/aggregate/project.json) 到独立客户目录，填入真实研究问题、总体、方向、独立性假设、来源 citation 和 locator、输入描述及未解决限制。模板中的占位说明必须替换，不代表科学审核。无须建立虚构 bibliography、筛选决定、reviewer 或批准声明。

必须显式保留 `schema="meta-aggregate-project-v1"`、`mode="existing_summary_data"`；该项目不能包含 `stages`。程序不自动识别缺文件而降级成此模式。当前只覆盖独立、同尺度、同单位、同结局和时间点的连续 MD；相关效应、重复队列、多臂试验、SMD 或二分类须使用相应方法和额外证据。本轮没有修改二分类 MH 算法。

配置中的相对路径以 project.json 所在目录解析。`original_inputs` 至少包含一个真正提供的原始汇总文件，也可列出原表转录、来源说明和原先分析计划，程序逐字节留存。`effects` 每行的 `source_document` 必须指向该清单中的一个文件；相对 source_document 以 effects.csv 目录解析。来源行的 page/table/figure 定位保留在统计 trace。保存来源不证明原文或研究独立性已核实。

`source.verification_status` 固定为 `not_independently_verified`。`unit.status="reported"` 时提供非空 `value` 与 `reference`；来源不明确时用 `{"status":"unverified","value":""}`。例如未核实的活动恢复时间单位必须留空，不能自动写成天；报告及展示森林图会标注单位未核实。不同单位不能据此混合合并。

## 固定效应与模型

`effects.csv` 必需列为 `study_id,cohort_id,effect_type,estimate,ci_lower,ci_upper,outcome,timepoint,contrast,adjustment,source_document,source_location`。每个 study_id 和 cohort_id 只出现一次；`effect_type=MD`，CI 必须有限且包含点估计，在 MD 尺度近似对称。CI 的置信水平须与 analysis.alpha 一致。若从两组 n/均数/SD 得到效应，先按确定的方向计算 MD 和 SE，并保留派生规则、原始输入及作者已有转换，不能再次转换作者已换算的数值。

`analysis.csv` 必须恰好一行，列为 `confirmed,effect_type,outcome,timepoint,contrast,adjustment,model,tau_method,test,alpha`。运行前明确设定 `confirmed=YES`；这仅确认本次数值配置，不是新综述的协议或来源批准。效应量、结局、时间点、比较与调整必须与 effects 一致。

| 预先确定的方法 | model | tau_method | test |
|---|---|---|---|
| 逆方差固定效应 | FE | NONE | z |
| 随机效应 DerSimonian-Laird | RE | DL | z |
| 原随机效应路径 | RE | REML | z |

alpha 需在 0 与 0.5 之间，常用 0.05。FE/DL、RE/NONE、未知估计器及自动选择均拒绝。协议确认和 R 引擎同样支持显式 RE/DL；完整综述仍需实际审核。程序按运行前指定的估计器计算一次，留一法保持同一估计器，不按异质性、参考答案或拟合结果自动切换方法。方法选择理由由研究者负责。

## 从正式客户入口运行

以下命令从候选根目录运行，路径换成实际值。输出必须为全新目录。

```powershell
& './launch.cmd' meta run --project 'C:/Meta Study/project.json' --rscript $env:META_RSCRIPT --out 'C:/Meta Study/Fresh Aggregate Run'
& './launch.cmd' meta aggregate-verify --run 'C:/Meta Study/Fresh Aggregate Run'
```

运行前先验证模式、来源、配置与研究 ID，再将 project、effects、analysis 和所有原始输入逐字节存入 `inputs/`，生成 `analysis_binding.json` 的 SHA256 和固定配置后才调用原生 metafor。来源与生成文件改变会使 verify 失败；它只核对本地文件绑定，不认证研究判断或审核身份。原件需保留在原路径，移动或改变后应按新输入建立新运行。

成功输出包括 `statistics/pooled_result.csv`、`study_effects_trace.csv`、原引擎 `forest.png`、带模式与单位的 `forest_display.png`、`leave_one_out.csv`、`fact_report.md`、软件版本和配置；`paper/manuscript.docx` 与 Markdown、JSON、附件均表达作者提取数据复算边界。留一法在至少三项效应时运行；只有两项时明确说明不计算，不把单项分析冒充合并结果。
