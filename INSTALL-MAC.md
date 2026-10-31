# Apple Silicon macOS 联网安装

适用于 Apple M1/M2/M3/M4 及后续 arm64 芯片，macOS 14 或更新版本。Intel Mac 不适用此安装入口。统计脚本与 Windows 共用。

让 Agent 获取本分支源码或 Mac 联网 ZIP，阅读本文件，然后在源码目录执行：

```bash
bash setup-online.sh "$HOME/Ye1 Meta Runtime" standard I_ACCEPT
bash launch.sh "$HOME/Ye1 Meta Runtime" standard check
```

首次安装需联网，standard 的固定文件合计 328,985,895 字节（约 314 MiB），不含网络协议开销。运行目录建议预留至少 2 GB。`core` 仅安装两两统计核心；频率学网络、诊断、多阈值、剂量反应、相关效应、单组和常用 PDF 解析使用 `standard`。

安装器从 Python、CRAN、PyPI 官方文件服务器获取固定版本，逐文件核验 SHA256。Python 3.14.5 与 R 4.6.1 使用官方签名 macOS PKG，通过系统安装器写入 `/Library/Frameworks`，需要正常管理员授权；它们不是完全隔离的应用内运行时。若该电脑已有其他版本，请先让 Agent 说明同版本框架可能被安装器更新，再由用户确认。此操作不修改安全策略或全局环境变量。

Python 包位于运行目录的 `python/standard`，R 包位于 `libraries/r-extended`，启动时仅为子进程配置路径。安装器核验所有锁定 R 包的实际加载位置及 Python 包版本和导入路径；`READY` 表示校验完成。依赖锁在 `dependencies/macos-arm64-lock.json`。

下载中断后对同一目录重新运行原安装命令，缓存文件按 SHA256 校验并复用，已签收的框架不重复安装。失败日志保留在 `setup-logs`。依赖锁改变时选新目录，不覆盖旧环境。若系统拒绝安装或签名校验失败，保留原错误交给 Agent，不关闭 Gatekeeper 或修改权限。

开始分析：

```bash
bash launch.sh "$HOME/Ye1 Meta Runtime" standard meta --help
bash launch.sh "$HOME/Ye1 Meta Runtime" standard meta run --project /path/to/project.json --rscript /Library/Frameworks/R.framework/Versions/4.6-arm64/Resources/bin/Rscript --out /path/to/new-result
```

全文仍优先 XML/HTML，并保留 PDF 解析。standard 提供 pdfplumber/pdfminer/pypdfium2；缺少全文时由用户补充。可选 Docling 的 Windows 安装方案和模型清单保留，Mac Docling 模型安装不包含在本次 standard 入口中，不能假称已完成模型推理验收。

第三方软件保留其原许可：Python 使用 PSF 及内含声明，R 与各 R 包保留各自 GPL/其他许可，Python wheels 保留各自许可。此联网 ZIP 不包含这些原生安装包、编译依赖或模型；自有代码使用仓库 MIT。官方文件的版本、来源、SHA256、字节数和许可摘要在锁文件中，安装后的原许可保留在各包目录。Windows 安装入口及下载文件保持不变。

维护者 CI 使用 GitHub 官方 `macos-15` 标准 runner，并同时断言 `uname -m=arm64` 与 `RUNNER_ARCH=ARM64`。安装不调用 setup-python、setup-r 或 runner 包缓存，实际经过上述客户入口。
