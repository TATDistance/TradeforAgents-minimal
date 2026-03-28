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

- `AI 实时决策首页`：默认入口，直接看系统状态、当前阶段、AI 动作和账户摘要
- `研究中心`：自动选股、单股分析、候选卡片、分享页
- `复盘中心`：交易计划、模拟盘、复盘结果
- `调试总览`：查看 8610 调试面板状态并跳转

AI 首页现在还负责“用户设置”：

- 在首页直接绑定当前使用的大模型平台、模型、Base URL 和 API Key
- 当前推荐平台是 `DeepSeek`
- 首页和研究中心共用同一套浏览器本地配置
- 研究中心不再重复展示用户设置卡，只负责研究与计划流程
- 首页会明确展示“AI 来源”，区分：
  - 当前来自首页绑定配置
  - 当前来自本地 `.env`
  - 当前来自 `decision.json` 研究缓存
  - 当前已经降级为规则引擎 / 无 AI

当前产品入口已经从“步骤式工具页”切到“双模式结构”：

1. 默认先看 `AI 实时决策首页`
2. 想追溯候选来源和单股分析时，再进入 `研究中心`
3. 想看计划、复盘和历史结果时，再进入 `复盘中心`
4. 调试和工程视图统一放到 `8610` 调试面板

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
- 六套公开规则策略实时出信号
- AI 二次审批
- AI 主动组合管理
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

第三阶段已经继续补齐：

- 市场状态机
- 动态策略权重
- AI 审核员增强上下文
- AI 主动组合管理器
- 最终动作计划：`BUY / SELL / REDUCE / HOLD`
- 账户状态回流

第四阶段已经新增：

- `legacy_review_mode`
- `ai_decision_engine_mode`
- `compare_mode`
- 六套策略从“直接买卖信号”升级为“特征层 + 分数层”
- `AI 决策引擎` 成为新的中央决策器
- `8610` 控制台升级为“AI 决策中心”
- 新旧模式对照与实时差异展示

第五阶段已经新增：

- `A 股交易日历服务`
- `交易阶段服务`
- `执行权限网关`
- 午休与收盘后不再新增真实模拟成交
- 盘后只保留观察 / 明日准备动作 / 日报
- `8610` 新增交易日历、当前阶段、执行权限、动作意图 vs 真实成交面板

第四阶段当前版本里，AI 单次轮询的大致流程是：

```text
旧模式：
实时行情
 -> 股票池筛选
 -> 六套策略输出候选信号
 -> AI 审核员复核
 -> 风控
 -> 模拟成交
 -> 更新账户

新模式：
实时行情
 -> 股票池筛选
 -> 六套策略输出特征与分数
 -> 决策上下文构建
 -> AI 决策引擎
 -> 风控
 -> 模拟成交
 -> 更新账户

对照模式：
同一轮行情
 -> 旧模式产出动作
 -> 新模式产出动作
 -> 记录差异
 -> 控制台展示对照结果
```

## 快速开始

### 方式一：直接用网页

```bash
git clone https://github.com/TATDistance/TradeforAgents-minimal.git
cd TradeforAgents-minimal
bash start.sh web
```

然后在页面里按这个顺序用：

1. 打开 `http://127.0.0.1:8600/`
2. 先看首页的 AI 实时决策摘要、当前阶段和账户状态
3. 如果想追溯依据，再进入 `研究中心`
4. 如果想看计划和复盘，再进入 `复盘中心`
5. 如果想看完整调试信息，再打开 `http://127.0.0.1:8610/`

如果你想直接体验当前版本的实时 AI 决策，更推荐这样：

1. 先打开 `http://127.0.0.1:8600`
2. 直接查看首页的当前阶段、执行权限和 AI 动作
3. 再打开 `http://127.0.0.1:8610`
4. 在 `8610` 顶部切换：
   - 旧模式：策略主导 + AI 审批
   - 新模式：AI 决策引擎
   - 对照模式：新旧同时输出
5. 直接观察：
   - 今天是不是交易日
   - 当前处于哪个 A 股交易阶段
   - 现在是否允许真实模拟成交
   - AI 决策输入摘要
   - AI 审核员
   - AI 决策中心
   - 执行结果
   - 模式对照

第五阶段之后，盘中与盘后的行为已经明确分开：

- `PRE_OPEN / OPEN_CALL_AUCTION / MIDDAY_BREAK / POST_CLOSE`
  系统可以分析、生成动作意图或次日准备动作，但不会写真实成交
- `CONTINUOUS_AUCTION_AM / CONTINUOUS_AUCTION_PM`
  系统才允许真实模拟成交
- `NON_TRADING_DAY`
  系统只展示状态、历史结果和复盘，不会新增模拟订单

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

如果 AI 首页或调试面板显示：

```text
当前处于 market_closed，已跳过实时股票池更新
```

这是正常现象，表示当前不是 A 股交易时段。系统会继续展示账户、持仓和日志，但不会新开模拟成交。

如果你需要做盘后纸面回放，可以在 [ai_stock_sim/config/settings.yaml](/home/alientek/workspace/tools/TradeforAgents-minimal/ai_stock_sim/config/settings.yaml) 里把：

```yaml
market_session:
  allow_post_close_paper_execution: true
```

打开。默认仍然保持 `false`，这样更接近真实 A 股节奏，也更安全。

如果你想切换第四阶段的决策模式，也可以在 [ai_stock_sim/config/settings.yaml](/home/alientek/workspace/tools/TradeforAgents-minimal/ai_stock_sim/config/settings.yaml) 里修改：

```yaml
decision_engine:
  mode: ai_decision_engine_mode
```

支持：

- `legacy_review_mode`
- `ai_decision_engine_mode`
- `compare_mode`

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
