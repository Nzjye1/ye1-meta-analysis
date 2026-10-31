# 第三方软件、数据与模型

本仓库自有源码、说明和安装工具采用 [MIT](LICENSE)。源码与小安装 ZIP 不携带第三方解释器、编译 wheel、R 二进制库或模型。首次使用时由安装器从固定官方来源取得依赖，并保留原许可、版权、模型卡与 NOTICE。

逐组件名称、版本、官方 URL、字节数、SHA256 与原许可标签记录在 [online-lock.json](dependencies/online-lock.json)；补充原文来源在 [notice-source-lock.json](dependencies/notice-source-lock.json)。

| 下载组件 | 原许可与保留材料 |
|---|---|
| CPython 3.14.5 Windows x64 | PSF 及内含第三方/Microsoft Windows 二进制附加条件，LICENSE.txt 保留在原生目录 |
| R 4.6.1 与 CRAN R 包 | R GPL-2/GPL-3；各包按 DESCRIPTION、COPYING、LICENSE、NOTICE 中原条款，包括 GPL/LGPL/MIT/BSD 等 |
| 标准 Python distribution | 各官方 wheel 的 METADATA、licenses/NOTICE 与内嵌组件条款保留 |
| 可选 Docling distribution | 各原条款保留；固定获取 Docling/latex2mathml MIT 原文及 LPPL 文本，unimathsymbols 的 LPPL 单独保留 |
| Heron / TableFormer 模型 | 固定官方 repo commit 与逐文件 SHA；分别 Apache-2.0 / CDLA-Permissive-2.0，保留模型卡与原许可 |

下载至个人专用目录并不改变任何第三方的原许可。使用安装参数 I_ACCEPT 前，用户应已允许本次安装并接受适用条款；软件组件、研究数据、论文与模型均保留各自权利。

Mac arm64 的官方安装包与二进制依赖固定记录在 [macos-arm64-lock.json](dependencies/macos-arm64-lock.json)，对应 Python 官方 universal2 PKG、CRAN arm64 R PKG/tgz 和 PyPI arm64/universal wheels。Mac 联网 ZIP 同样不内含这些第三方原生文件；安装后保留原软件包许可。
