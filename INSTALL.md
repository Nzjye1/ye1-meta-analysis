# 安装与使用

Apple 芯片 macOS 请读 [Mac 联网安装说明](INSTALL-MAC.md)，使用 `setup-online.sh` 与 `launch.sh`。以下为 Windows x64 步骤。

在 Windows x64 上，将仓库或安装 ZIP 完整解压，交给具备本地文件读写和命令执行能力的 Agent，先读 SKILL.md。本目录需要保持 app、tools、dependencies 与入口文件的相对位置。

## 官方依赖准备

安装器会从固定官方 HTTPS 来源准备 Python 3.14.5 x64、R 4.6.1 x64 和私有依赖库；版本、文件大小、SHA256 见 dependencies/online-lock.json。首次需要联网及本机可用的 curl.exe、tar.exe、certutil.exe，Agent 按客户允许的目录和原许可执行安装。

| 选项 | 内容 | 下载大小 |
|---|---|---:|
| core | Python/R 与 6 个核心 R 包 | 137,884,398 字节 |
| standard（默认） | 全部八类路线，76 个 R 包、24 个 Python distribution，含 pdfplumber | 276,542,214 字节 |
| docling（按需） | standard 加 Docling、固定 Heron/TableFormer 模型及原许可 | 约 1,150,650,112 字节 |

core/standard 大小来自实际文件；Docling 合计按固定 wheel、模型和许可文本大小计算。建议 standard 预留 3 GB，Docling 预留 8 GB，供解压、缓存与恢复使用。

在源码根目录，选择全新的专用目录（下面使用当前用户目录），客户已允许安装并接受原许可时执行：

```powershell
$runtime = Join-Path $env:LOCALAPPDATA 'Ye1Meta/Runtime'
./setup-online.cmd $runtime standard I_ACCEPT
```

I_ACCEPT 记录本次安装授权及适用原条款接受。引导解释器在 bootstrap 目录，分析解释器在 native/python，互不覆盖。官方 R 安装器使用当前用户模式，关闭当前版本注册、文件关联和图标任务；可能创建该安装的当前用户卸载登记。安装器不更改全局 PATH、执行策略、权限或凭据。

## 自检与开始研究

```powershell
& "$runtime/native/python/python.exe" -I -B tools/online_setup.py verify --root $runtime --profile standard
$env:META_PYTHON = Join-Path $runtime 'native/python/python.exe'
$env:META_RSCRIPT = Join-Path $runtime 'native/R/bin/Rscript.exe'
$env:META_R_LIBRARY = Join-Path $runtime 'libraries/r-extended'
$env:META_METHOD_PYTHON_LIBRARY = Join-Path $runtime 'python/standard'
$env:META_FRONTEND_PYTHON_LIBRARY = $null
./launch.cmd check
```

Agent 读取 READY.json、runtime.json 与安装日志，确认环境后，按 [两两研究流程](app/CUSTOMER-WORKFLOW.md) 或相应方法教程使用 `./launch.cmd meta ...`。你提供研究问题、方案、题录、合法全文或研究级汇总数据，成果写到新的研究目录。需要先熟悉流程时可运行 `./launch.cmd demo --workspace NEW_SYNTHETIC_DIRECTORY`，该示例明确使用合成材料。

## 按需添加 Docling

```powershell
./setup-online.cmd $runtime docling I_ACCEPT
```

已有固定下载会核验复用，Docling 依赖与模型独立准备。具体进程配置和数值候选复核见 [Docling PDF](app/DOCLING-PDF.md)。原 XML/HTML 与 pdfplumber 路线继续可用。

## 中断恢复与排错

使用同一源码、目录和选项重运行原安装命令，已核验缓存会复用；后续文件支持 HTTP Range，服务器不支持时重取该文件后再核全文件 SHA。首个约 36 MB Python 引导 ZIP 中断时重新获取。不同锁、未知目录、不同字节或安装文件被改变会停止并保留原件；为新版本选择新的专用目录。

读取 last-setup-attempt.json、current-phase.json 与 setup-logs 的具体错误。遇到系统策略或权限拒绝，Agent 停止该动作并报告，不改策略、提权或切换入口绕过。R 版本按 R 自身 package_version 语义比较，真实错版仍拒绝。READY 只在完整验证通过后更新。

本仓库下载目录中的 ZIP 与源码使用相同安装流程，下载链接和 SHA256 见 [downloads](downloads/README.md)。
