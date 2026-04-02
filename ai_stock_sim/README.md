# AI 股票模拟交易系统

`ai_stock_sim` 是当前仓库里的实时模拟交易引擎与调试子系统。

它的定位不是实盘下单器，而是：

- A 股实时观察
- AI 决策与对照
- A 股规则模拟撮合
- 账户与持仓更新
- 周期评估、评分、日报、人工回填

## 当前能力

### 第十一阶段：学习层

这一版开始，`ai_stock_sim` 不再只是“会执行决策”的引擎，也开始具备“会根据历史结果调整自己”的能力。

新增能力包括：

- 策略表现评估
  - 最近窗口胜率
  - 平均收益
  - 最大回撤
  - 交易次数
- 决策归因
  - 记录每次决策时的分数、市场状态、风格和理由
  - 方便后续分析“为什么这笔交易亏了”
- 自适应权重调整
  - 自动调整策略权重
  - 自动调整 AI 加分倍率
  - 自动调整风险惩罚倍率
- 风格自适应
  - `short_term`
  - `trend_following`
  - `balanced`

这些结果会同时输出到：

- `8600` 首页：给客户/日常使用者看简化摘要
- `8610` 调试面板：给开发者看详细分析、权重历史和错误决策

### 实时层

- 东财实时快照
- 监控池 / 候选池
- watchlist 生命周期管理
- 交易日历与交易阶段驱动
- 动作意图与真实成交分离
- 分时图 / K 线图 / 收益曲线数据缓存
- 前导 `0` 股票代码的稳定字符串处理（避免 `002155 -> 1133` 这类 YAML 解析错误）
- 图表数据回退链路：
  - 分时图优先读 intraday 缓存，其次最近 quote
  - K 线优先读本地历史缓存，其次按需补拉最近日线

### 策略层

当前已接入 6 套公开规则策略：

- `momentum`
- `dual_ma`
- `macd_trend`
- `mean_reversion`
- `breakout`
- `trend_pullback`

它们在新模式下主要输出：

- 分数
- 方向
- strength
- 子特征

### AI 层

当前保留三种角色：

- `AI 审核员`
- `AI 主动组合管理器`
- `AI 决策引擎`

并支持：

- `legacy_review_mode`
- `ai_decision_engine_mode`
- `compare_mode`

### 执行层

- A 股规则风控
- 100 股整数倍
- T+1
- 印花税 / 佣金 / 滑点
- 模拟撮合与账户记账

### 评估层

- 日 / 周 / 月 / 滚动窗口评估
- 胜率、盈亏比、利润因子、期望收益、最大回撤
- 策略评分
- 模式对照
- 日报 / 周报 / 月报导出
- 人工实盘成交回填

## 启动

### 1. 初始化

```bash
cd /home/alientek/workspace/tools/TradeforAgents-minimal/ai_stock_sim
bash scripts/bootstrap.sh
```

### 2. 启动实时引擎

```bash
bash scripts/run_engine.sh
```

### 3. 启动调试面板

```bash
bash scripts/run_dashboard.sh
```

打开：

```text
http://127.0.0.1:8610/
```

如果你已经从仓库根目录启动了：

```bash
cd /home/alientek/workspace/tools/TradeforAgents-minimal
bash start.sh web
```

那也可以：

- 在 `8600` 首页先看结果
- 在 `8610` 调试面板再看底层输入和日志

现在首页点击：

- `一键启动 AI 实时决策`

会自动尝试完成：

```text
检查当前 watchlist
-> 若缺失 / 过期 / 仅有默认观察池，则先自动选股
-> 同步 runtime watchlist
-> 启动实时引擎
-> 启动 8610 调试面板
```

图表相关说明：

- 分时图依赖当天盘中缓存的 intraday 点；如果当天没有积累到足够点位，页面会优先回退展示最近可用 quote
- K 线图不依赖当天是否开市；只要本地历史缓存或候补历史数据可用，就应该能在闭市后继续查看

## 运行模式

### 旧模式

```text
策略出候选信号
-> AI 审批
-> 风控
-> 模拟执行
```

### 新模式

```text
实时行情
-> 特征构建
-> AI 决策引擎
-> 风控
-> 模拟执行
```

### 事件驱动模式

第七阶段之后，实时引擎支持：

- `event_driven_mode`
- `polling_mode`

默认建议使用：

- `event_driven_mode`

它的特点是：

- 不再每轮对所有 symbol 全量重算
- 只有当价格、特征、市场状态、持仓状态、账户状态发生明显变化时，才触发该 symbol 的实时决策链
- 出错时仍可回退到旧的轮询模式

### 对照模式

```text
同一轮行情
-> 旧模式决策
-> 新模式决策
-> 记录差异
```

## 当前版本 AI 单次轮询

```text
实时行情
-> 监控池 / 候选池更新
-> 六套策略输出特征与分数
-> 决策上下文构建
-> AI 决策引擎
-> 风控
-> 动作计划
-> 模拟执行（仅允许成交时）
-> 账户更新
-> 实时展示
```

在 `event_driven_mode` 下，更准确的主链是：

```text
行情变化事件
-> 触发器判断是否值得重算
-> 仅对受影响 symbol 重新构建特征
-> AI 决策引擎
-> 风控
-> 动作计划
-> 模拟执行
```

## 双分体系

当前不再只靠一个 `final_score` 判断“观察”和“执行”。

系统现在同时维护：

- `setup_score`
  - 这只股票是否值得继续观察
- `execution_score`
  - 这只股票当前是否值得立刻执行

可以这样理解：

- `setup_score` 高但 `execution_score` 低
  - 说明票不差，但当前阶段/风险/账户状态不支持动手
- `execution_score` 过阈值
  - 说明当前具备真正执行的条件

默认阈值：

```yaml
scoring:
  min_setup_score_to_watch: 0.35
  min_execution_score_to_buy: 0.55
  min_execution_score_to_reduce: 0.45
```

首页和 8610 都会展示：

- `setup_score`
- `execution_score`
- `ai_score`
- 市场风险惩罚
- 账户/阶段惩罚

这样用户可以直接看懂：

- 为什么现在没有动作
- 为什么现在只能观察
- 为什么这只票接近可以买/减仓

## 交易阶段约束

当前系统严格区分：

- `PRE_OPEN`
- `OPEN_CALL_AUCTION`
- `CONTINUOUS_AUCTION_AM`
- `MIDDAY_BREAK`
- `CONTINUOUS_AUCTION_PM`
- `CLOSING_AUCTION`
- `POST_CLOSE`
- `NON_TRADING_DAY`

其中：

- 只有上午 / 下午连续竞价阶段允许真实模拟成交
- 午休不成交
- 收盘后不新增真实成交
- 收盘后只保留观察、明日准备动作、日报

## 第八阶段：监控池闭环与首页图表化

这一阶段主要补了两件事。

### 1. watchlist 闭环

系统现在会把当前监控池当成一个有生命周期的对象管理：

```json
{
  "symbols": ["300750", "688525"],
  "source": "auto_selector_today",
  "generated_at": "2026-04-01T09:31:22",
  "valid_until": "2026-04-01T15:00:00",
  "trading_day": "2026-04-01"
}
```

优先级是：

1. 今日自动选股结果
2. 最近一次有效候选池
3. 默认观察池（最后兜底）

这样即使用户不先进研究中心，首页一键启动时也能自动获得合理监控池。

### 2. 首页图表层

首页现在会展示：

- 当前监控池与持仓池
- 最近买入 / 卖出解释
- 分时图
- K 线图
- 账户收益曲线
- 动作时间线

这些图表不是纯静态占位，而是由服务层读取：

- `data/cache/charts/` 的分时点
- 历史行情缓存
- `account_snapshots`
- 最近 `orders` / 风控拒绝动作

所以首页会更像“AI 实时交易前台”，而不是只是一堆状态卡片。

## 第十阶段：盘中动态选股 + watchlist 自进化

第十阶段继续往“盘中主动发现机会”推进，目标不是推翻已有实时引擎，而是在它上面补一层中频扫描与监控池演化。

### 盘中动态扫描

系统现在在连续竞价阶段会按配置的分钟级间隔执行轻量扫描：

- 上午 / 下午连续竞价允许扫描
- 午休、收盘后、非交易日不执行盘中扫描
- 扫描频率低于实时决策频率，不会每几秒全市场重算

### 新机会池

盘中发现的新机会会先进入 `opportunity_pool`，而不是直接写进 runtime watchlist。

这样做的目的是：

- 避免 watchlist 因为一瞬间异动频繁抖动
- 给演化规则一个缓冲层
- 让首页和报表能解释“这只票是怎么进池的”

### watchlist 自进化

watchlist 现在不再只是静态列表，而是按规则增量演化：

- 当前持仓永远保留
- execution_score / setup_score 高的股票优先保留
- 新强票按阈值加入
- 长期低分且无持仓的旧票逐步移出
- 监控池总容量受配置限制

### 首页与报表

首页和日报现在会额外看到：

- 最近一次盘中扫描时间
- 当前监控池来源
- 新增 / 移除股票数量
- 动态选股事件摘要

这样你可以区分：

- 当前是“启动时初始选股”
- 还是“盘中动态扫描并入的新机会”

## 首页与用户设置

`8600` 首页现在有一个“模型与 API 设置”折叠区，用来确认：

- 大模型平台
- 模型名称
- Base URL
- API Key

研究中心默认复用首页的这套本地配置，不再重复显示设置卡。

需要注意：

- 首页显示的“AI 来源”可能来自首页配置
- 也可能来自本地 `.env`
- 也可能来自 `decision.json` 研究缓存

所以判断 AI 是否真的在实时调用时，要看“AI 来源”，不要只看有没有动作。

## 配置

主要配置文件：

- `config/settings.yaml`
- `config/symbols.yaml`
- `config/runtime_symbols.yaml`

常改的项包括：

- 初始资金
- 刷新周期
- 决策模式
- 是否允许盘后纸面执行
- 评估窗口
- 评分权重

例如：

```yaml
decision_engine:
  mode: ai_decision_engine_mode

market_session:
  allow_post_close_paper_execution: false
```

第八阶段新增的常用项包括：

```yaml
watchlist:
  enable_auto_refresh_on_start: true
  use_recent_candidates_as_fallback: true
  use_default_watchlist_as_last_resort: true

ui:
  show_intraday_chart: true
  show_kline_chart: true
  show_equity_curve: true
  show_action_timeline: true
  default_symbol_selection_mode: priority_based

watchlist_evolution:
  enabled: true
  scan_interval_minutes: 30
  max_watchlist_size: 30
  max_new_symbols_per_scan: 10
  max_remove_symbols_per_scan: 5
  min_score_to_add: 0.55
  min_score_to_keep: 0.30
  grace_period_minutes: 60
```

## 数据输出

数据库：

```text
data/db.sqlite3
```

日志：

```text
data/logs/
```

日报 / 周报 / 月报：

```text
data/reports/daily/
data/reports/weekly/
data/reports/monthly/
```

实时快照缓存：

```text
data/cache/
```

## 常用命令

回测：

```bash
bash scripts/run_backtest.sh 600036 momentum strategy_plus_ai
```

最小测试：

```bash
bash scripts/smoke_test.sh
```

完整测试：

```bash
.venv310/bin/pytest tests -q
```

## 当前限制

- 不连接真实券商 API
- 东财公开行情存在网络、限流、DNS 波动
- `decision.json` 仍然是研究缓存的重要输入
- 当前更适合模拟研究与人工执行支持，不等于实盘自动交易系统

## 建议使用方式

最推荐的方式是：

1. 从 `8600` 首页看系统状态、当前阶段、AI 动作
2. 想追溯候选来源时，再去研究中心
3. 想看底层输入、模式对照、日志时，再去 `8610`

这样最符合当前产品结构，也最不容易被“工程细节”淹没。 
