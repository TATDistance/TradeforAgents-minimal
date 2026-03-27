# AI 股票模拟交易系统

`ai_stock_sim` 是一个面向中国 A 股与 ETF 的模拟交易 MVP，目标是把以下链路先跑通：

- 东财实时行情
- 公开量化策略
- TradeforAgents-minimal AI 二次审批
- A 股规则风控
- 模拟撮合与账户
- Streamlit 实时控制台
- 盘后复盘与基础回测

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
bash scripts/run_backtest.sh 600036 momentum
```

### 5. 运行最小测试

```bash
bash scripts/smoke_test.sh
```

## 运行逻辑

每一轮主循环会执行：

1. 抓取东财实时行情
2. 筛选股票池
3. 运行动量、均值回归、突破三类策略
4. 至少两个策略同向后，交给 AI 审批
5. 进入 A 股风控
6. 通过后执行模拟撮合
7. 更新账户、持仓、日志和权益曲线

需要注意：

- 交易时段内才会新开模拟成交
- 收盘后与非交易时段只会刷新状态、账户和日志
- 持续监控中心会优先沿用网页“步骤 1”生成的最新候选池；若没有最新候选池，则回退到默认观察池
- 控制台和网页中，股票默认显示为“代码 + 股票名”

## 核心模块

- `app/market_data_service.py`
  东财实时行情和日线数据服务，AKShare 作为补充来源
- `app/universe_service.py`
  股票池筛选，过滤 ST、低流动性、上市不足天数
- `app/strategy_engine.py`
  统一调度公开策略
- `app/ai_decision_service.py`
  读取 `TradeforAgents-minimal/results/.../decision.json`，必要时可调用 subprocess
- `app/risk_engine.py`
  执行 A 股交易规则和仓位风险限制
- `app/mock_broker.py`
  维护模拟成交、账户和持仓
- `dashboard/dashboard_app.py`
  Streamlit 实时控制台

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

其中：

- `config/symbols.yaml` 是默认观察池
- `config/runtime_symbols.yaml` 会在网页自动选股后由系统自动写入，用于给实时监控继承最新候选池

## 数据输出

- SQLite：`data/db.sqlite3`
- 日志：`data/logs/`
- 回测报告：`data/reports/backtest/`
- 复盘报告：`data/reports/`

## 当前限制

- 第一版回测是“本地简化回测 + vn.py 工作区预留”，优先保证可跑通
- 东财公开接口属于免费公开数据，稳定性不等同于机构专线
- AI 审批依赖当前仓库里的 `TradeforAgents-minimal` 结果目录；不可用时会自动降级为无 AI 模式
- 当前默认交易日判断只做工作日与时段判断，尚未接入完整节假日日历

## 下一阶段建议

1. 把 `vn.py` 回测适配补成正式策略类
2. 为实时引擎增加分钟级缓存层
3. 扩展 AI 审批输入，让它读取候选信号明细而不是只读单股报告
4. 增加手工实盘成交回填
