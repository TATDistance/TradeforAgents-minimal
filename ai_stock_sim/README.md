# AI 股票模拟交易系统

`ai_stock_sim` 是当前仓库里的实时模拟交易引擎与调试子系统。

它的定位不是实盘下单器，而是：

- A 股实时观察
- AI 决策与对照
- A 股规则模拟撮合
- 账户与持仓更新
- 周期评估、评分、日报、人工回填

## 当前能力

### 实时层

- 东财实时快照
- 监控池 / 候选池
- 交易日历与交易阶段驱动
- 动作意图与真实成交分离

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

## 首页与用户设置

`8600` 首页现在有一张“用户设置”卡，用来确认：

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
