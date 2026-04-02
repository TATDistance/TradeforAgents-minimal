# AI 股票模拟交易引擎

`ai_stock_sim` 是当前仓库里的实时模拟交易引擎与调试子系统。

它负责：

- watchlist / 持仓池实时跟踪
- AI 决策、风控、模拟成交
- 账户、持仓、动作、图表缓存
- 策略评估、决策归因、自适应权重、风格识别
- 8610 调试后台

它不负责：

- 券商实盘下单
- 券商账户同步
- 高频或逐笔撮合

## 快速启动

```bash
cd /home/alientek/workspace/tools/TradeforAgents-minimal/ai_stock_sim
bash scripts/bootstrap.sh
bash scripts/run_engine.sh
bash scripts/run_dashboard.sh
```

打开：

- `http://127.0.0.1:8610/`

如果你从仓库根目录启动：

```bash
cd /home/alientek/workspace/tools/TradeforAgents-minimal
bash start.sh web
```

那么通常只需要在 `8600` 首页点击：

- `一键启动 AI 实时决策（会自动补监控池）`

## 当前主链

```text
交易日历 / 交易阶段
-> watchlist / 持仓池
-> 行情变化事件
-> 特征构建
-> AI 决策引擎
-> 风控
-> 模拟成交
-> 账户更新
-> 首页 / 8610 展示
```

## 核心能力

### 实时层

- A 股交易日历与交易阶段驱动
- `event_driven_mode`
- 分时图 / K 线图 / 收益曲线缓存
- 东财实时快照与回退链路

### watchlist 层

- 启动时自动补监控池
- 盘中动态扫描新机会
- opportunity pool
- watchlist 自进化

### 决策层

- `ai_decision_engine_mode`
- `setup_score + execution_score`
- AI 风险模式
- AI 风格自适应

### 执行层

- 100 股整数倍
- T+1
- 交易阶段约束
- 模拟撮合、账户、持仓更新

### 学习层

- 策略表现评估
- 决策归因
- 自适应权重
- 风格切换

## 常用目录

- 数据库：
  - `data/db.sqlite3`
- 日志：
  - `data/logs/engine.log`
  - `data/logs/dashboard.log`
- 实时状态：
  - `data/cache/live_decision_state.json`
- 机会池：
  - `data/cache/opportunity_pool.json`
- 图表缓存：
  - `data/cache/charts/`

## 调试后台（8610）

8610 主要给开发与调试使用，重点看：

- 当前模式与市场总览
- 交易日历 / 当前阶段 / 执行权限
- 策略表现分析
- 决策归因
- 权重变化历史
- 市场状态与风格
- 错误交易分析

## 配置

主要配置在：

- [config/settings.yaml](/home/alientek/workspace/tools/TradeforAgents-minimal/ai_stock_sim/config/settings.yaml)

重点配置包括：

- 交易阶段
- 决策模式
- 引擎模式
- watchlist 演化参数
- adaptive / style 参数

## 文档与更新

- 主项目入口说明： [../README.md](/home/alientek/workspace/tools/TradeforAgents-minimal/README.md)
- Release Notes： [../docs/releases/README.md](/home/alientek/workspace/tools/TradeforAgents-minimal/docs/releases/README.md)
- GitHub Releases： https://github.com/TATDistance/TradeforAgents-minimal/releases
