# Pairwise 客户流程：本地源码候选

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


本教程补齐 rc2 Issue #2 所缺的主客户路线。适用一个结局/时间点、每项独立研究一个可比效应的 RR、OR、HR、MD 或 SMD。原始运行时包不被修改；本教程配合当前源码目录的 `launch.cmd` 使用。先完成仓库根 [INSTALL.md](../INSTALL.md)，所有下列命令从仓库根执行，输出用全新目录。

客户已经提供作者提取的连续结局研究级汇总数据、仅要求复算时，使用 [已有汇总数据分析](AGGREGATE-WORKFLOW.md) 的显式模式，从 `launch.cmd meta run` 到数值、森林图、留一法、事实报告及 Word，无须编造检索筛选或新综述批准。下面的完整综述流程和实际审核要求继续保留。

## 一、先跑明确的合成演练

这是虚构高血压试验的开发回归，无真实患者或论文，不需要也不声称真人研究审核。它验证代码链条，不能代替下一轮独立论文复现。

```powershell
& './launch.cmd' check
& './launch.cmd' meta method-prepare --idea 'app/validation/pairwise-idea.json' --out 'C:/Meta Study/Synthetic Route'
```

提案产生 `route.json`、`routing_guide.md`、`choice_template.json` 与待审 `protocol_outline.json`。route 的 guide 是本文件。此时没有统计运算；待审 choice 会拒绝后续执行。仅对本附带合成 fixture，可明确写一份 synthetic choice：

```powershell
& $env:META_PYTHON -c "import json,pathlib; p=pathlib.Path('C:/Meta Study/Synthetic Route'); c=json.loads((p/'choice_template.json').read_text(encoding='utf-8')); c['status']='synthetic_test'; (p/'choice.json').write_text(json.dumps(c),encoding='utf-8')"
& './launch.cmd' meta method --route 'C:/Meta Study/Synthetic Route/route.json' --choice 'C:/Meta Study/Synthetic Route/choice.json' --phase workflow --project 'app/validation/project.json' --rscript $env:META_RSCRIPT --out 'C:/Meta Study/Synthetic Run'
& './launch.cmd' meta method-verify --receipt 'C:/Meta Study/Synthetic Run.method-route-receipt.json'
```

10 个阶段依次为 prepare、import、screen、link、freeze、counts、statistics、flow、packet、paper。预期合成 MD 为 -4 mmHg，95% CI 约 -5.1315857341 至 -2.8684142659；5 条输入记录，经显式去重后 4 份报告映射为 3 项独立试验。`statistics/pooled_result.csv`、`statistics/forest.png`、`statistics/fact_report.md`、`paper/manuscript.docx` 和 `workflow_receipt.json` 应存在。COMPLETED 只表示配置的本地程序成功。

也可运行 `launch.cmd demo --workspace FRESH_DIRECTORY` 直接演练相同合成项目；该入口不替代研究方法选择。全部回归脚本见 [BUILD.md](../BUILD.md)。

## 二、真实公开汇总数据或真实研究怎样开始

先保留合法本地来源及许可证/来源记录，明确是已发表汇总数据复算还是一项新系统综述。复算不能冒称完成新检索、原文阅读或完整系统综述。原文未核对、来源不足、独立性未解决时停止相应研究判断，不能用合成确认绕过。

1. 写本地 `idea.json`：必需 `schema="meta-method-idea-v1"`、`project_id`、`question`、`population`、`outcome`、`question_type="comparative_effect"`、`data_shape="one_independent_effect_per_study"`、`effect_type`、`intervention`、`comparator`、`timepoint`、`direction`；后续研究规划还需要非空列表 `eligible_designs` 和同义词列表的列表 `search_concepts`。结构可参考 [合成 idea](validation/pairwise-idea.json)，必须全部换成实际研究问题。
2. 用 `launch.cmd meta method-prepare --idea IDEA_JSON --out FRESH_ROUTE` 生成提案。实际研究者审核方法、效应方向、单位、时间点、可比调整及研究/队列独立性。
3. 实际批准后，复制 choice template 为独立文件；保留原 route SHA-256，填 `status="human_confirmed_claim"`、实际 `reviewer`、ISO `decision_date`、可追溯的实际 `reference`。它只是本地审核声明，不认证身份。没有实际批准就维持 pending。
4. 可用 `launch.cmd meta method --route ROUTE --choice CHOICE --phase prepare --out FRESH_PLAN` 生成 PICO、检索式与分析候选。它们仍待审，不能把 `protocol_outline.json` 或含 `planning_status=PENDING_HUMAN_REVIEW` 的候选当成确认协议。
5. 在独立研究目录建立实际 protocol 和输入文件。用 [真实项目空审核框架](templates/pairwise/project.json) 配置阶段，参考 [可运行合成配置](validation/project.json) 理解 `@stage/file`。框架没有 inputs，也没有填入真人审核声明；先完成真实输入和审核再执行。患者级行、标识、原文全文及客户提取行留本地，不粘贴聊天或网页审阅。

## 三、输入合同和研究审核

输入字段与可运行示例在 [Clinical Inputs With Spaces](validation/Clinical%20Inputs%20With%20Spaces/)；命令的精确参数可用 `launch.cmd meta COMMAND --help`，独立模块可用 `META_PYTHON app/scripts/MODULE.py --help` 查看。

| 文件/阶段 | 必需内容及下一步 |
|---|---|
| bibliography.csv → literature import | 必需列 `source_record_id,title,authors,year,doi,pmid`，可补 journal、abstract、source_database 等元数据。以 `python app/scripts/literature.py import --input FILE --source LABEL --out FRESH_IMPORT` 生成稳定 `record_id` 与去重候选；后续表须引用其真实 ID。RIS 用 `app/scripts/import_ris.py`。不得把候选重复自动当成已删除。 |
| dedup | `record_id,disposition,retained_record_id,reason,reviewer,decision_date`；每条记录显式 keep 或 remove_duplicate，删除需所保留记录及原因。 |
| decisions → screen | `record_id,stage,decision,reason,reviewer,decision_date`；stage 是 title_abstract/full_text，decision 为 include/exclude/pending；排除写原因，不跳过前序审核。修订使用 `revision_of,revision_reason`。 |
| effects → link | `record_id,study_id,cohort_id,effect_type,estimate,ci_lower,ci_upper,outcome,timepoint,contrast,adjustment,source_document,source_location`。每研究/独立队列一条；定位到 page/table/figure；实际核对数据、效应方向、Wald CI/SE假设及重叠队列。 |
| report_map | `record_id,report_id,study_id`，每份纳入报告恰好一行。伴随报告可以归同一 study，不能重复计入效应。 |
| analysis.csv | 单行：`confirmed,effect_type,outcome,timepoint,contrast,adjustment,model,tau_method,test,alpha`。实际审核后才填 YES；FE/NONE、RE/REML 或预先确定的 RE/DL，test=z，alpha 如 0.05；不能混用效应量、单位、结局或时间点。 |
| protocol.json | 非空 `protocol_id,question`；`pico` 含 population/intervention/comparator；非空列表 eligible_designs/inclusion_criteria/exclusion_criteria/sensitivity_plan；`outcome` 含 name/timepoint/effect_type/direction；`analysis` 含 contrast/adjustment/model/tau_method/test/alpha。与 analysis/effects 完全一致。明确选择 exploratory_single 或 formal_dual；后者须用已完成的双审筛选与提取导出，不能把单人结果改标签。 |
| 报告输入 | source-methods、retrieval、source-review、corrections、rob-plan/rob-ledger 及 narrative 各文件结构见附带 fixture 和 `app/scripts/report.py --help`。必须如实记录未检索、未获取、未复核或待判状态；不能照抄合成值。 |

`literature.py screen/link` 和工作流只检查本地一致性；填定位字段不证明读过原文。人工应核对筛选、提取、源值、重复研究和风险偏倚。需要正式双审时，先读 [双审和证据说明](FULLTEXT-EXTRACTION.md) 与 [证据质量合同](QUALITY-EVIDENCE.md)，执行对应 review 阶段后再绑定。任何方法不适配（相关效应、网络、稀有事件、诊断等）应回到对应方法路线，不能强行并入本 pairwise 流程。

真实框架的 freeze 阶段 `mode` 为 real，reviewer、approval-reference、declaration 默认均空。实际审核通过后由获授权操作者填入实际 reviewer/reference，declaration 必须准确为 `I reviewed and approve the protocol and linked inputs`。这不是建议自动代填的批准语句。程序以九项输入哈希绑定 protocol、records、dedup、decisions、ledger、source-effects、effects、analysis、report-map。

## 四、运行、复核与继续

```powershell
& './launch.cmd' meta method --route ROUTE_JSON --choice REVIEWED_CHOICE_JSON --phase workflow --project ACTUAL_PROJECT_JSON --rscript $env:META_RSCRIPT --out FRESH_RUN
& './launch.cmd' meta method-verify --receipt RUN_PATH.method-route-receipt.json
```

工作流阶段输出目录由 runner 分配；`@stage/file` 仅能引用已完成阶段。`{project_dir}` 是配置文件目录，`{rscript}` 是显式原生 R。run_protocol 在确认哈希核对后调用 metafor，保存统计 receipt；manuscript 再核对报告与统计文件。RR/OR/HR 用 log 尺度合并；MD 要同单位、SMD 要同标准化约定；CI 应在分析尺度近似对称。计算用同一 metafor 引擎，不构成独立第二引擎验证。

核对 pooled CSV、study trace、forest、留一法与事实报告数值；检查报告/研究数量、源定位和输入版本。Word 是未最终审定的草稿；本轮只检查 OOXML/附件，不声称 Word GUI 或分页目视验收。Introduction/Discussion 需要实际来源支持：narrative 段落含 text、record_ids、source_locator、review_status；真实引用必须存在于 bibliography。自动生成 Methods/Results 也需科学审核，不自动获得低 RoB、GRADE、PRISMA 合规或可发表结论。

缺少外部输入时 `workflow_receipt.json` 标记 NEEDS_ATTENTION。补齐缺失文件后可在同一命令追加 `--resume`，但 project 和已完成阶段的输入/输出必须保持哈希一致；已完成工作流不能覆盖。改协议、统计输入或已完成证据后建立新运行，不编辑旧 receipt。数值变更应重建证据；文字修订使用 `launch.cmd meta revise` 并保留历史。原始源文件和所有旧结果只读保留。
