# AI 股票模拟交易系统

`ai_stock_sim` 是一个面向中国 A 股与 ETF 的 AI 模拟交易系统，当前已经完成两层能力：

- 东财实时行情
- 公开量化策略
- TradeforAgents-minimal AI 二次审批
- A 股规则风控
- 模拟撮合与账户
- Streamlit 实时控制台
- 盘后复盘与基础回测
- 多周期评估与策略评分
- 模式对照实验
- 盘后日报导出
- 人工实盘成交回填
- 市场状态机与动态策略权重
- AI 审核员与 AI 主动组合管理器
- 最终动作计划与组合级风控
- AI 决策引擎与新旧模式对照
- A 股交易日历与交易阶段驱动执行

项目不会接入任何真实券商 API，也不会模拟点击券商 APP。

## 目录结构

```text
ai_stock_sim/
├── README.md
├── requirements.txt
├── .env.example
├── config/
├── data/
├── external/
├── app/
├── strategies/
├── dashboard/
├── scripts/
└── tests/
```

## 快速开始

### 1. 初始化

```bash
cd /home/alientek/workspace/tools/TradeforAgents-minimal/ai_stock_sim
bash scripts/bootstrap.sh
```

说明：

- 脚本会优先使用 `python3.10`
- 虚拟环境默认创建在 `ai_stock_sim/.venv310`
- 如果系统没有 `python3.10`，会回退到 `python3`，但 `AKShare` 在 Python 3.9+ 下更稳定

### 2. 启动交易引擎

```bash
bash scripts/run_engine.sh
```

### 3. 启动实时控制台

```bash
bash scripts/run_dashboard.sh
```

浏览器访问：

```text
http://127.0.0.1:8610
```

如果你已经在仓库根目录跑了：

```bash
bash start.sh web
```

也可以先在 `http://127.0.0.1:8600` 的“步骤 4：实时 AI 决策中心”里启动和查看这套实时模拟交易系统。

### 4. 运行回测

```bash
bash scripts/run_backtest.sh 600036 momentum strategy_plus_ai
```

### 5. 运行最小测试

```bash
bash scripts/smoke_test.sh
```

## 第二阶段新增能力

### 1. 周期评估与策略评分

系统现在会把模拟盘评估拆成：

- 日评估
- 周评估
- 月评估
- 最近 20/50 笔交易
- 最近 20/60 个交易日

核心指标包括：

- 总收益率
- 胜率
- 盈亏比
- 利润因子
- 每笔期望收益
- 最大回撤
- 收益回撤比
- 月度盈利占比

同时会为策略输出综合评分：

- 收益能力
- 风险控制
- 稳定性
- 执行质量

控制台里还会额外拆开两类比较：

- 入场策略横向比较
- 卖出策略评分比较

评分结果会写入：

```text
data/db.sqlite3
```

对应表：

- `strategy_evaluations`
- `mode_comparisons`
- `manual_execution_logs`

### 2. 模式对照实验

控制台现在可以同时查看：

- `strategy_only`
- `strategy_plus_ai`
- `strategy_plus_risk`
- `strategy_plus_ai_plus_risk`

当前第一版对照结果采用“信号前瞻收益代理 + 实际模拟成交”混合方式，用来判断 AI 和风控是否真的在改善策略质量。

### 3. 日报导出

收盘后会自动导出：

- `data/reports/daily/`
- `data/reports/weekly/`
- `data/reports/monthly/`

格式包括：

- Markdown
- HTML
- JSON

### 4. 人工实盘回填

Streamlit 控制台新增“人工回填”页，可以记录：

- 是否执行
- 实际成交价
- 实际成交数量
- 备注和未执行原因

## 第四阶段新增能力

第四阶段开始，系统不再只有“策略主导 + AI 审批”这一条链。

现在支持三种模式：

- `legacy_review_mode`
- `ai_decision_engine_mode`
- `compare_mode`

其中：

- 旧模式：策略先出候选，AI 做审核
- 新模式：策略只提供特征与分数，AI 决策引擎成为中央决策器
- 对照模式：同一轮行情下同时产出旧模式和新模式决策，用于研究差异

8610 控制台现在可以直接看到：

- 当前运行模式
- AI 决策输入摘要
- AI 审核员
- AI 决策中心
- 执行结果
- 实时模式对照

### 当前版本 AI 单次轮询流程图

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

## 第五阶段新增能力

第五阶段开始，系统不再只是“按循环一直跑”，而是明确受 A 股交易日历和交易阶段驱动。

现在新增了：

- `trading_calendar_service.py`
- `market_phase_service.py`
- `execution_gate_service.py`
- 本地 2026 年 A 股交易日历
- 午休 / 收盘后 / 非交易日的真实成交拦截
- 动作意图与真实成交分离
- 收盘后日报与明日准备动作衔接

### 第五阶段主链

```text
交易日历判断
 -> 当前交易阶段判断
 -> 执行权限网关
 -> 行情更新
 -> 特征构建
 -> AI 决策
 -> 风控
 -> 动作计划
 -> 模拟执行（仅连续竞价阶段）
 -> 账户更新
 -> 盘后日报 / 明日准备动作
```

### 当前支持的 A 股阶段

- `PRE_OPEN`
- `OPEN_CALL_AUCTION`
- `CONTINUOUS_AUCTION_AM`
- `MIDDAY_BREAK`
- `CONTINUOUS_AUCTION_PM`
- `CLOSING_AUCTION`
- `POST_CLOSE`
- `NON_TRADING_DAY`

### 第五阶段的关键行为变化

- 只有 `CONTINUOUS_AUCTION_AM / CONTINUOUS_AUCTION_PM` 才会真实写入模拟成交
- 午休、盘前、收盘后只会保留动作意图，不会落地真实订单
- 收盘后 AI 仍会输出明日观察与准备动作
- 订单表新增 `intent_only / phase` 字段，可区分“动作意图”和“真实成交”
- 8610 控制台新增：
  - 交易日历状态
  - 当前交易阶段
  - 当前执行权限
  - 动作意图 vs 实际成交
  - 盘后模式

## 运行逻辑

### 旧主链

1. 抓取东财实时行情
2. 筛选股票池
3. 运行动量、双均线、MACD 趋势、均值回归、突破、趋势回踩六类策略
4. 候选信号交给 AI 审核
5. 进入 A 股风控
6. 通过后执行模拟撮合
7. 更新账户、持仓、日志和权益曲线

### 第四阶段新主链

1. 抓取东财实时行情
2. 六套策略不再直接主导交易，而是输出结构化特征与分数
3. 构建统一决策上下文：
   - 行情
   - 策略特征
   - 技术指标
   - 市场状态
   - 账户状态
   - 当前持仓状态
4. 交给 `AI 决策引擎`
5. 进入 A 股风控
6. 通过后执行模拟撮合
7. 更新账户、持仓、日志和权益曲线
8. compare_mode 下同时记录旧模式和新模式差异

需要注意：

- 默认只有上午和下午连续竞价阶段才会新开模拟成交
- 午休、收盘后与非交易日不会新增真实模拟订单
- 如果你把 `config/settings.yaml` 中的 `market_session.allow_post_close_paper_execution` 打开，收盘后会保留更明确的 `PREPARE_BUY / PREPARE_REDUCE` 明日准备动作；即使打开，也不会在盘后新增真实成交
- 持续监控中心会优先沿用网页“步骤 1”生成的最新候选池；若没有最新候选池，则回退到默认观察池
- 控制台和网页中，股票默认显示为“代码 + 股票名”
- 收盘后自动生成日报
- 控制台可查看周期统计、策略评分、模式对照与日志筛选

## 核心模块

- `app/market_data_service.py`
  东财实时行情和日线数据服务，AKShare 作为补充来源
- `app/universe_service.py`
  股票池筛选，过滤 ST、低流动性、上市不足天数
- `app/strategy_engine.py`
  统一调度公开策略，当前已接入 `momentum`、`dual_ma`、`macd_trend`、`mean_reversion`、`breakout`、`trend_pullback`
- `app/feature_service.py`
  将六套策略统一转成结构化特征与分数
- `app/decision_context_builder.py`
  为 AI 决策引擎构建统一上下文
- `app/ai_decision_engine.py`
  第四阶段新增的中央决策器
- `app/decision_mode_router.py`
  管理旧模式、新模式和对照模式
- `app/ai_decision_service.py`
  读取 `TradeforAgents-minimal/results/.../decision.json`，必要时可调用 subprocess
- `app/risk_engine.py`
  执行 A 股交易规则和仓位风险限制
- `app/mock_broker.py`
  维护模拟成交、账户和持仓
- `app/metrics_service.py`
  统一指标计算层
- `app/evaluation_service.py`
  日/周/月/滚动窗口评估与模式对照
- `app/scoring_service.py`
  策略综合评分
- `app/report_service.py`
  日报、周报、月报导出
- `app/manual_execution_service.py`
  人工实盘成交回填
- `app/vnpy_adapter.py`
  vn.py CTA/Alpha 参数导出、桥接 stub 生成与结果回流适配
- `dashboard/dashboard_app.py`
  Streamlit 实时控制台，支持策略横向比较、卖出策略评分、模式对照、人工回填和 AI 决策中心

## 配置

默认配置在：

- `config/settings.yaml`
- `config/symbols.yaml`

可以按需修改：

- 初始资金
- 刷新周期
- 单票仓位上限
- 单日总开仓上限
- 最大回撤限制
- 手续费、滑点、印花税
- 观察池
- 评估窗口
- 评分权重
- 决策模式
- 控制台刷新与日志筛选

其中：

- `config/symbols.yaml` 是默认观察池
- `config/runtime_symbols.yaml` 会在网页自动选股后由系统自动写入，用于给实时监控继承最新候选池
- `config/settings.yaml -> decision_engine.mode` 可以直接切模式

### 第四阶段最常用的配置项

```yaml
decision_engine:
  mode: ai_decision_engine_mode
  use_decision_json_as_research_cache: true
  fallback_to_legacy_mode_on_failure: true

feature_layer:
  use_strategy_scores: true
  use_market_regime: true
  use_portfolio_state: true
  use_position_state: true

compare_mode:
  enabled: true
  record_mode_differences: true
```

## 数据输出

- SQLite：`data/db.sqlite3`
- 日志：`data/logs/`
- 回测报告：`data/reports/backtest/`
- 日报：`data/reports/daily/`
- 周报：`data/reports/weekly/`
- 月报：`data/reports/monthly/`
- 复盘报告：`data/reports/`

## 当前限制

- 当前回测仍以“本地简化回测 + vn.py CTA/Alpha 桥接导出” 为主，尚未完全迁移到 vn.py 原生引擎
- 东财公开接口属于免费公开数据，稳定性不等同于机构专线
- AI 审批依赖当前仓库里的 `TradeforAgents-minimal` 结果目录；不可用时会自动降级为无 AI 模式
- 当前默认交易日判断只做工作日与时段判断，尚未接入完整节假日日历
- 模式对照实验当前包含“前瞻收益代理”，适合作为质量评估参考，不应等同于真实实盘收益

## 常用验收命令

```bash
bash scripts/bootstrap.sh
bash scripts/run_engine.sh
bash scripts/run_dashboard.sh
bash scripts/run_backtest.sh 600036 momentum strategy_plus_ai
bash scripts/smoke_test.sh
```

## 下一阶段建议

1. 把 `vn.py` 回测适配补成正式策略类和结果导入器
2. 接入完整 A 股交易日日历
3. 为模式对照实验增加更严格的历史撮合模拟
4. 让 8600 页面直接查看阶段二评估报表
