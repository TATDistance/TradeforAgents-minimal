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

也可以先在 `http://127.0.0.1:8600` 的“步骤 4：持续监控中心”里启动和查看这套实时模拟交易系统。

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

## 运行逻辑

每一轮主循环会执行：

1. 抓取东财实时行情
2. 筛选股票池
3. 运行动量、双均线、MACD 趋势、均值回归、突破、趋势回踩六类策略
4. 至少两个策略同向后，交给 AI 审批
5. 进入 A 股风控
6. 通过后执行模拟撮合
7. 更新账户、持仓、日志和权益曲线
8. 按条件刷新评估记录与日报

需要注意：

- 默认只有交易时段内才会新开模拟成交
- 收盘后与非交易时段默认只会刷新状态、账户和日志
- 如果你需要做盘后纸面回放，可以把 `config/settings.yaml` 中的 `market_session.allow_post_close_paper_execution` 打开
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
  Streamlit 实时控制台，支持策略横向比较、卖出策略评分、模式对照和人工回填

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
- 控制台刷新与日志筛选

其中：

- `config/symbols.yaml` 是默认观察池
- `config/runtime_symbols.yaml` 会在网页自动选股后由系统自动写入，用于给实时监控继承最新候选池

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
