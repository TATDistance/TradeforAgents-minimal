# TradeforAgents-minimal

这是一个面向中国 A 股盘后场景的 AI 交易分析工作台。

它现在已经不只是“单只股票分析工具”，还整合了：

- 单股 AI 分析
- 股票池批量分析
- 自动选股
- 交易计划生成
- 模拟盘验证
- 复盘报告
- 分享页导出

这套仓库当前最推荐的使用路径是：

`收盘后自动选股 -> AI 分析候选股 -> 生成次日计划 -> 模拟盘验证 -> 人工实盘执行`

## 适用场景

适合：

- 中国 A 股
- 没有券商 API
- 个人使用
- 收盘后选股
- 次日人工执行

不适合：

- 全自动实盘交易
- 高频或秒级交易
- 券商账户自动同步

## 主要能力

### 1. Web 页面

启动：

```bash
bash start.sh web
```

打开：

```text
http://127.0.0.1:8600
```

首页现在支持：

- 推荐模式：自动选股与生成计划
- 单只股票 AI 分析
- 股票池批量分析
- 候选卡片查看
- 交易计划 / 模拟盘 / 复盘中心
- 持续监控中心（沿用最新候选池）

页面中的 4 个步骤是联动关系，不是 4 套独立功能：

1. `步骤 1` 先自动选股并生成计划
2. `步骤 2` 把步骤 1 的候选结果渲染成卡片
3. `步骤 3` 展示同一批候选对应的交易计划、模拟盘和复盘
4. `步骤 4` 继续沿用步骤 1 的候选池做持续监控与 AI 模拟交易

页面里涉及股票代码的位置，都会尽量显示为“代码 + 股票名”。
如果你打开 `8610` 控制台，还能继续看到第二阶段新增的策略评分、周期统计、对照实验和人工回填。

### 2. AI 分析

支持：

- `quick`
- `deep`

分析结果输出到：

```text
results/<股票代码>/<日期>/
```

其中常见文件包括：

- `analysis_metadata.json`
- `decision.json`
- `message_tool.log`
- `share/<股票代码>_<日期>_share.html`

### 3. 内嵌交易工作流

仓库中已经内嵌：

```text
ai_trade_system/
```

它负责：

- 读取 `decision.json`
- 转成结构化交易信号
- 做 A 股风控
- 运行模拟盘
- 生成每日交易计划
- 生成复盘报告
- 跑自动选股流水线

另外仓库中还内嵌：

```text
ai_stock_sim/
```

它负责：

- 东财实时快照监控
- 三套基础策略实时出信号
- AI 二次审批
- A 股规则模拟撮合
- Streamlit 实时控制台
- 策略评分与周期统计
- 日报导出
- 人工实盘成交回填

`ai_stock_sim` 第二阶段已经补齐：

- 日 / 周 / 月 / 滚动窗口评估
- 胜率、盈亏比、利润因子、期望收益、最大回撤等指标
- 策略综合评分
- `strategy_only` / `strategy_plus_ai` / `strategy_plus_risk` / `strategy_plus_ai_plus_risk` 对照
- Markdown / HTML / JSON 日报导出
- Streamlit 中文评估面板与人工回填入口

## 快速开始

### 方式一：直接用网页

```bash
git clone https://github.com/TATDistance/TradeforAgents-minimal.git
cd TradeforAgents-minimal
bash start.sh web
```

然后在页面里按这个顺序用：

1. 填 `API Key`
2. 使用“步骤 1：自动选股与生成计划”
3. 看“自动选股摘要”
4. 看“候选卡片”
5. 看“步骤 3：交易计划、模拟盘与复盘”
6. 如需持续盯盘，再看“步骤 4：持续监控中心”
7. 最后点卡片里的“打开分享页”

### 方式二：命令行

单股分析：

```bash
bash start.sh cli 600028 --quick
bash start.sh cli 000630 --deep
```

初始化模拟账户：

```bash
python3 -m ai_trade_system.scripts.bootstrap_db --cash 100000
```

生成交易计划：

```bash
python3 -m ai_trade_system.scripts.run_daily_plan --limit 20
```

执行自动选股全流程：

```bash
python3 -m ai_trade_system.scripts.run_auto_pipeline --mode quick --execute-sim
```

生成复盘报告：

```bash
python3 -m ai_trade_system.scripts.run_review
```

## 推荐的日常流程

对于个人 A 股使用者，最实用的日常流程是：

1. 收盘后运行自动选股
2. 让系统自动分析候选股
3. 阅读一句话总结
4. 看今天是否存在可执行交易
5. 如果有，再手动去券商 APP 下单
6. 用模拟盘和复盘报告验证信号质量

如果页面显示：

```text
今日无可执行交易
```

通常就意味着今天不需要人工下单。

如果步骤 4 显示：

```text
当前处于 market_closed，已跳过实时股票池更新
```

这是正常现象，表示当前不是 A 股交易时段。系统会继续展示账户、持仓和日志，但不会新开模拟成交。

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

核心文件：

- `scripts/minimal_web_app.py`
- `scripts/minimal_deepseek_report.py`
- `ai_stock_sim/dashboard/dashboard_app.py`
- `ai_stock_sim/app/scheduler.py`
- `ai_trade_system/scripts/run_auto_pipeline.py`
- `ai_trade_system/scripts/run_daily_plan.py`
- `ai_trade_system/scripts/run_review.py`

## 输出目录

AI 分析结果：

```text
results/<symbol>/<date>/
```

自动选股报告：

```text
ai_trade_system/reports/auto_candidates_YYYY-MM-DD.md
```

每日交易计划：

```text
ai_trade_system/reports/daily_plan_YYYY-MM-DD.md
```

模拟盘复盘报告：

```text
ai_trade_system/reports/paper_review.md
```

模拟盘数据库：

```text
ai_trade_system/data/db.sqlite3
```

实时模拟交易数据库：

```text
ai_stock_sim/data/db.sqlite3
```

第二阶段评估报表：

```text
ai_stock_sim/data/reports/daily/
ai_stock_sim/data/reports/weekly/
ai_stock_sim/data/reports/monthly/
```

## 数据与稳定性说明

- 主行情筛选优先使用东财风格公开数据
- 增强维度可以接入 AKShare
- 系统支持部分失败降级继续运行
- 股票池里单只失败，不会再导致整条流水线整体失败

## 文档

- [AI 交易工作流](docs/ai_trade_workflow.md)
- [云端部署说明](docs/minimal_cloud_deploy.md)
