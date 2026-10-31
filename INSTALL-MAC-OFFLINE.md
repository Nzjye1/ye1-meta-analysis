# Apple 芯片 Mac 离线安装

适用于 macOS 14 及更新版本的 Apple 芯片 Mac。离线包中的 `offline-payload/cache` 与源码应完整放在同一目录；首次安装需要管理员授权来安装官方 Python 和 R 框架。系统框架可能更新已有同版本安装及命令行链接。

解压完整包，交给 Agent 进入解压目录后执行：

```bash
bash setup-offline.sh "$HOME/Ye1 Meta Offline Runtime" I_ACCEPT
bash launch.sh "$HOME/Ye1 Meta Offline Runtime" docling check
```

缺失或哈希不符的文件会中止安装，不会自动联网补齐。离线入口包含标准分析依赖、Docling CPU PDF 解析及固定模型；全文优先 XML/HTML，PDF 输出仍是待核对候选，缺全文请用户提供合法文件。

安装器将官方框架安装到系统框架目录，将 Python 包、R 包、模型和日志放到指定运行目录。重复使用必须保持同一依赖锁。`setup-logs` 保存安装回执；不要修改系统安全设置来解决错误。

第三方 wheel、R 包和模型保留原许可与内含声明。`thirdparty-sources` 包含对应版本源码与补充材料；`WHEEL-LICENSE-INVENTORY.json` 列出 wheel 中的许可元数据及文件。源码自有部分使用 MIT，其他材料按各自许可。
