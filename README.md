# TradeforAgents-minimal

面向中国 A 股的 AI 交易分析与模拟工作台。

当前仓库已经不是“单只股票分析脚本”，而是一个带网页入口的组合系统：

- `8600`：AI 实时决策首页
- `研究中心`：自动选股、单股分析、候选卡片、分享页
- `复盘中心`：交易计划、模拟盘、复盘结果
- `8610`：调试面板

它适合：

- 中国 A 股 / ETF
- 个人使用
- 无券商 API
- 盘后研究、盘中观察、模拟交易、人工执行

它不适合：

- 全自动实盘下单
- 高频 / 秒级交易
- 券商账户自动同步

## 当前产品结构

### 1. AI 实时决策首页

地址：

```text
http://127.0.0.1:8600/
```

这是默认入口。打开后应该在几秒内回答 3 件事：

1. 系统现在在干嘛
2. 现在能不能交易
3. AI 建议做什么

首页会显示：

- 系统运行状态
- 当前交易日与交易阶段
- 当前执行权限
- AI 当前策略
- 实时动作
- 账户摘要
- 动作意图 vs 实际成交

首页还内置一张“用户设置”卡：

- 绑定大模型平台
- 绑定模型
- 设置 Base URL
- 设置 API Key

当前默认推荐平台是：

- `DeepSeek`

当前网页端的用户绑定配置，也按下面这个约束理解：

- 当前只支持 `DeepSeek`
- 第一次使用时需要先填写 `API Key`
- 如果不填写页面里的 `API Key`，系统可能会回退到本地 `.env` 或 `decision.json` 研究缓存
- 如果你希望以“当前浏览器会话里的用户配置”为准，就应该在首页先明确填写并保存 `DeepSeek API Key`

首页会明确显示“AI 来源”，区分当前决策来自：

- 首页绑定配置
- 本地 `.env`
- `decision.json` 研究缓存
- 规则引擎降级

### 2. 研究中心

地址：

```text
http://127.0.0.1:8600/research
```

这里负责：

- 自动选股
- 单股 AI 分析
- 股票池批量分析
- 候选卡片
- 分享页索引

研究中心不再重复展示用户设置卡，默认复用首页保存的 AI 配置。

### 3. 复盘中心

地址：

```text
http://127.0.0.1:8600/evaluation
```

这里负责：

- 交易计划
- 模拟盘结果
- 复盘摘要
- 历史结果查看

### 4. 调试面板

地址：

```text
http://127.0.0.1:8610/
```

这里是工程视图，不是默认用户入口。主要看：

- AI 决策输入摘要
- 特征层
- 市场状态机
- 策略权重
- AI 审核员 / AI 决策引擎
- 风控结果
- 动作计划
- 日志与异常

## 仓库内的两个核心子系统

### `ai_trade_system/`

更偏盘后分析与计划：

- 读取 `results/.../decision.json`
- 转结构化信号
- A 股风控
- 模拟盘
- 自动选股
- 交易计划
- 复盘报告

### `ai_stock_sim/`

更偏实时观察与模拟：

- 东财实时快照
- 六套公开规则策略
- AI 审核员
- AI 主动组合管理器
- AI 决策引擎
- A 股规则模拟撮合
- 交易日历与交易阶段驱动
- Streamlit 调试面板
- 周期评估、策略评分、日报、人工回填

## 快速开始

### 方式一：网页入口

```bash
git clone https://github.com/TATDistance/TradeforAgents-minimal.git
cd TradeforAgents-minimal
bash start.sh web
```

然后打开：

```text
http://127.0.0.1:8600/
```

推荐使用顺序：

1. 先看 AI 首页，确认系统状态、当前阶段、AI 动作
2. 想追溯候选来源时，再进入研究中心
3. 想看计划与复盘时，再进入复盘中心
4. 想看底层输入和日志时，再打开 8610 调试面板

### 方式二：命令行

单股分析：

```bash
bash start.sh cli 600028 --quick
bash start.sh cli 000630 --deep
```

盘后自动选股与计划：

```bash
python3 -m ai_trade_system.scripts.run_auto_pipeline --mode quick --execute-sim
python3 -m ai_trade_system.scripts.run_daily_plan --limit 20
python3 -m ai_trade_system.scripts.run_review
```

实时引擎与控制台：

```bash
cd ai_stock_sim
bash scripts/bootstrap.sh
bash scripts/run_engine.sh
bash scripts/run_dashboard.sh
```

## 现在的运行逻辑

当前系统同时保留两条链路：

### 旧链路

```text
策略出候选信号
-> AI 审批
-> 风控
-> 模拟执行
```

### 新链路

```text
实时行情
-> 特征构建
-> AI 决策引擎
-> 风控
-> 模拟执行
```

并支持：

- `legacy_review_mode`
- `ai_decision_engine_mode`
- `compare_mode`

## A 股交易时段约束

当前系统已经受交易日历与交易阶段驱动：

- 非交易日：不新增真实模拟成交
- 午休：不成交
- 收盘后：只做分析、复盘、明日准备动作
- 上午 / 下午连续竞价：才允许真实模拟成交

首页和 8610 会显示：

- 今天是否交易日
- 当前处于哪个交易阶段
- 现在是否允许开仓
- 现在是否允许真实模拟成交

## 常用输出目录

单股/批量分析结果：

```text
results/<symbol>/<date>/
```

自动选股与交易计划：

```text
ai_trade_system/reports/
```

实时模拟数据库：

```text
ai_stock_sim/data/db.sqlite3
```

日报 / 周报 / 月报：

```text
ai_stock_sim/data/reports/
```

## 常见问题

### 1. 没在页面里填 API Key，为什么首页还有 AI？

因为当前 AI 可能来自以下任一来源：

- 首页已保存的浏览器本地配置
- 仓库根目录 `.env`
- 以前生成的 `decision.json` 研究缓存

首页现在会直接显示“AI 来源”，不要只看有没有动作。

### 2. 为什么首页会显示东财错误？

东财公开接口偶尔会有 DNS、网络或限流问题。系统现在会：

- 自动重试
- 尽量回退缓存 / 本地结果
- 不把旧错误一直挂成当前故障

### 3. 为什么现在不能成交？

先看首页里的：

- 交易日
- 当前阶段
- 允许成交

如果是非交易日、午休或收盘后，系统可以继续分析，但不会新增真实模拟成交。

## 当前限制

- 不接券商 API，不做实盘自动下单
- 东财是公开行情源，不等于机构专线
- `decision.json` 仍然是研究缓存的重要来源
- Streamlit 调试面板更偏工程视图，不是最终用户界面

## 项目结构

```text
TradeforAgents-minimal/
├── ai_stock_sim/
├── ai_trade_system/
├── docs/
├── results/
├── scripts/
├── start.sh
└── README.md
```

## 文档

- [AI 交易工作流](docs/ai_trade_workflow.md)
- [云端部署说明](docs/minimal_cloud_deploy.md)
