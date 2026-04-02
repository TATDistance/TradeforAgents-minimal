# GitHub Release 模板

## 版本命名规范

统一使用：

```text
vMAJOR.MINOR.PATCH
```

示例：

```text
v1.0.0
v1.1.0
v1.1.1
v1.0.0-beta.1
v1.0.0-rc.1
```

规则：

- `v1.0.0`：首个正式可用版本
- `v1.1.0`：新增功能但不破坏兼容
- `v1.1.1`：仅修复问题
- 若版本未达到正式发布标准，优先使用 `beta / rc / preview`

要求：

- Tag 必须和 Release 版本一致
- Release title 必须包含版本号
- 不使用 `final / latest / newest` 这类随意标签

## Release 标题模板

正式版：

```text
TradeforAgents v1.0.0 - AI实时决策系统首个正式版本
```

功能迭代版：

```text
TradeforAgents v1.1.0 - 动态选股与自适应学习升级
```

修复版：

```text
TradeforAgents v1.1.1 - 稳定性修复与部署优化
```

预发布版：

```text
TradeforAgents v1.2.0-beta.1 - Windows安装包预发布版
```

## Release Notes 模板

```md
# 🚀 TradeforAgents {{VERSION}}

TradeforAgents 的{{RELEASE_KIND}}版本。

## 本版本包含

### 核心能力

* AI 实时决策引擎
* A 股交易日历与交易阶段驱动
* 盘中动态选股 + watchlist 自进化
* 策略评估 + AI 自适应权重调整
* 自动切换短线 / 趋势 / 平衡风格
* 类证券账户 UI（图表 + 动作时间线）

### 产品入口

* `8600`：AI 实时决策首页
* `8610`：高级调试面板

### 使用方式

#### Windows 用户

1. 下载 `windows-installer.exe` 或 `windows-noinstall.zip`
2. 启动后打开首页
3. 完成 API 配置
4. 点击“一键启动 AI 实时决策”

#### Docker 用户

使用 `docker compose up -d` 启动服务

#### 研究模式用户

可直接进入研究与计划中心，查看自动选股、候选池与计划结果

## 本版本重点升级

* 从固定轮询升级到事件驱动实时决策
* 从静态 watchlist 升级到盘中动态选股
* 从单一评分升级到 setup/execution 双分体系
* 从固定权重升级到自适应学习

## 适合谁使用

* 想观察 AI 实时决策过程的用户
* 想研究盘中机会发现与模拟交易的用户
* 想部署本地/服务器版本的高级用户

## 已知限制

* 当前仍为模拟交易系统，不接真实券商实盘下单
* 行情更新为秒级到十秒级近实时，不是逐笔 Tick
* Windows 安装包优先保障可用性，不以极限精简为目标

## 后续规划

* 日报推送系统
* 多用户部署模式
* 更完整的 Windows 分发体验
* 更强的策略学习与收益优化
```

## 资产命名规范

Release 附件统一使用：

```text
tradeforagents-windows-installer-{{VERSION}}.exe
tradeforagents-windows-noinstall-{{VERSION}}.zip
tradeforagents-docker-bundle-{{VERSION}}.zip
tradeforagents-release-notes-{{VERSION}}.md
```

规则：

- 全小写
- 使用连字符 `-`
- 文件名中包含平台
- 文件名中包含版本号
- 不使用空格
- 不使用中文文件名

## Release 附件要求

正式版至少上传：

```text
windows-installer.exe
windows-noinstall.zip
可选 docker bundle
可选 README_RELEASE.md
```

Windows 分发策略要求：

- 不要只留 installer
- 至少同时提供：
  - 安装版：`TradeforAgents-minimal-windows-installer.exe`
  - 免安装版：`TradeforAgents-minimal-windows-noinstall.zip`
- `start.bat` / `debug_console.bat` 应包含在 zip 或 installer 安装目录内
- `.bat` 不作为单独 GitHub Release 资产上传

若该版本没有完整的双分发产物，或尚未完成关键验证，不建议发布正式版，优先使用：

```text
pre-release
```

## GitHub Release 页面操作规范

- Tag：填写完整版本号，例如 `{{VERSION}}`
- Target：选择 `main`
- Release title：使用上面的标题模板
- Release notes：粘贴上面的 notes 模板
- 上传二进制文件到附件区
- 若版本还不稳定，勾选 `Set as a pre-release`

## 正式版判定规则

满足以下条件，才允许发布正式版：

- Windows installer 可启动
- Windows noinstall zip 可启动
- Windows 包可启动
- `8600` 首页可访问
- 一键启动链路可用
- 关键测试通过
- README 已更新

否则建议使用：

```text
pre-release
```

并在标题中带上：

```text
beta
rc
preview
```
