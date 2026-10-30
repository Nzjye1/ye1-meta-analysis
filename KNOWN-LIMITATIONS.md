# 方法与运行条件

当前安装流程面向 Windows x64。使用固定官方依赖及用户选择的专用目录；core 是最小核心依赖选项，全部八条路线使用 standard，可选结构化 PDF 解析追加 docling。

全文以合法取得的 XML/HTML 或用户提供的 PDF 为输入，文本层、表头/脚注、原文单位与数值复核按 [全文流程](app/FULLTEXT-EXTRACTION.md) 和 [Docling](app/DOCLING-PDF.md) 处理。当前 Docling 流程使用本地 CPU 模型，OCR/VLM 需按材料和宿主实际能力另行组织。

每条方法路线的数据结构、模型条件和来源审核要求见相应 app 教程。患者资料和研究输出保留在本地；首次依赖安装、在线检索按具体任务联网。恢复命令和错误处理见 [INSTALL.md](INSTALL.md)。
