# Release Notes

这个目录用于存放仓库内的版本说明草稿与发布索引。

主入口请优先查看：

- GitHub Releases: https://github.com/TATDistance/TradeforAgents-minimal/releases

建议之后的发布说明都按版本号维护，例如：

- `v1.0.0.md`
- `v1.0.1.md`
- `v1.1.0.md`
- `GITHUB_RELEASE_TEMPLATE.md`

推荐每个 release 至少包含：

1. 本版新增能力
2. 兼容性 / 配置变更
3. 已知限制
4. 升级方式
5. 截图或界面变化

## 当前说明

当前仓库已经把原先堆在主 README 中的阶段更新说明迁出。

后续请优先在 GitHub Releases 发布：

- 版本摘要
- 关键改动
- 风险提示
- 升级说明

主 README 只保留：

- 部署
- 启动
- 使用说明
- 文档入口

## Windows 发布补充

Windows 相关发布建议统一附带：

- `tradeforagents-windows-installer-vX.Y.Z.exe`
- `tradeforagents-windows-noinstall-vX.Y.Z.zip`
- `tradeforagents-release-notes-vX.Y.Z.md`

发布策略建议：

- 不要只发 installer
- installer 给普通用户
- noinstall zip 给测试、排错、权限受限环境
- `.bat` 保留在压缩包或安装目录中，但不作为单独资产上传

GitHub Release 文案模板见：

- [GITHUB_RELEASE_TEMPLATE.md](/home/alientek/workspace/tools/TradeforAgents-minimal/docs/releases/GITHUB_RELEASE_TEMPLATE.md)
