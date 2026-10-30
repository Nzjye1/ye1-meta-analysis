# 源码与本地运行

Ye1 Meta 的自有程序以 Python/R 源码运行。读取 [安装说明](INSTALL.md)，由 Agent 在独立目录取得固定官方依赖并完成自检，然后使用原入口 `launch.cmd` 和 `meta` 子命令。

[下载目录](downloads/README.md) 提供完整的 Skill、源码与联网安装脚本 ZIP；文件 SHA256 见下载清单。该 ZIP 保留源码基线 `af3e3419481ff1a9c024e84a5d3893f50d43b251` 的原字节，内部 SOURCE-MANIFEST 记录其源码指纹；本仓库来源记录见 SOURCE-ORIGIN.json。

自有代码采用 [MIT](LICENSE)，官方依赖与模型保留 [各自原许可](THIRD-PARTY.md)。
