# AI 交易工作流

## 概览

当前仓库已经内置一套面向中国 A 股盘后场景的实用工作流：

1. 收盘后自动选股
2. 对候选股执行 AI 分析
3. 将 AI 结果转成结构化信号
4. 应用 A 股风控规则
5. 生成次日交易计划
6. 运行模拟盘验证
7. 人工查看结果并在券商 APP 中执行

这套方案刻意面向以下场景：

- 中国 A 股
- 没有券商 API
- 先做模拟盘验证
- 最终人工实盘执行

它不打算解决：

- 全自动实盘交易
- 秒级/高频交易
- 券商账户自动同步

## 主要组成部分

### 1. TradeforAgents-minimal

主要职责：

- 单只股票 AI 分析
- 股票池批量分析
- 分享页生成
- Web 界面展示

核心文件：

- `scripts/minimal_deepseek_report.py`
- `scripts/minimal_web_app.py`

### 2. 内嵌 `ai_trade_system`

主要职责：

- 信号导入
- 风控检查
- 模拟盘执行
- 交易计划生成
- 复盘报告生成
- 自动选股流水线

核心模块：

- `ai_trade_system/engine/bridge_service.py`
- `ai_trade_system/engine/risk_engine.py`
- `ai_trade_system/engine/mock_broker.py`
- `ai_trade_system/engine/plan_center.py`
- `ai_trade_system/engine/review_service.py`
- `ai_trade_system/engine/universe_service.py`
- `ai_trade_system/scripts/run_auto_pipeline.py`

## 默认用户流程

### 推荐路径

打开 Web 页面后，建议按这个顺序使用：

1. 先在首页填写并保存 `DeepSeek API Key`
2. 运行 `自动选股与生成计划`
3. 查看 `自动选股摘要`
4. 查看 `候选卡片`
5. 查看 `交易计划`
6. 打开你想重点查看的分享页
7. 如果交易计划里有可执行信号，再去券商 APP 手动下单

当前这套网页用户配置有一个明确边界：

- 当前只支持 `DeepSeek`
- 页面里的模型选择也是围绕 `DeepSeek` 系列模型
- 因此第一次进入系统时，应该先确认首页“用户设置”卡中的：
  - 平台：`DeepSeek`
  - 模型：`deepseek-chat` 或 `deepseek-reasoner`
  - `API Key`

### 日常最该看什么

如果你是每天盘后使用，最重要的输出是：

- `自动选股一句话总结`
- `数据源状态`
- `今日可执行清单`
- `今日结论`

如果页面显示：

```text
今日无可执行交易
```

通常就意味着今天最合适的动作是“不操作，继续观察下一轮”。

## 自动选股逻辑

自动选股流水线主要分两层：

### 1. 基础行情筛选

- 以东财风格公开行情为主
- 用日线数据做趋势和流动性筛选
- 如果在线行情不可用，允许回退到本地已有快照

### 2. 增强维度

- 资金流
- 公告
- 财报
- 行业信息

这些增强维度失败时不会终止整条流水线。  
界面上会用简化后的“数据源状态”告诉用户，而不是直接把整次流程判成失败。

## 风控与执行模型

### 页面里会看到的信号状态

- `可执行`
- `观察`
- `仅持仓者处理`
- `风控拦截`

### 已建模的 A 股规则

- 100 股整数倍
- T+1 卖出限制
- 单票仓位上限
- 止损风险上限
- 没有可卖仓位时拒绝卖出

### 模拟盘执行方式

- 使用接近 next-bar 的验证逻辑
- 维护本地现金、持仓和权益
- 在不接触真实账户的前提下生成复盘结果

## 关键目录

TradeforAgents 输出：

- `results/<symbol>/<date>/`

分享页目录：

- `results/<symbol>/<date>/share/`

模拟盘数据库：

- `ai_trade_system/data/db.sqlite3`

自动选股报告：

- `ai_trade_system/reports/auto_candidates_YYYY-MM-DD.md`

每日交易计划：

- `ai_trade_system/reports/daily_plan_YYYY-MM-DD.md`

复盘报告：

- `ai_trade_system/reports/paper_review.md`

## 常用命令

初始化模拟账户：

```bash
python3 -m ai_trade_system.scripts.bootstrap_db --cash 100000
```

生成交易计划：

```bash
python3 -m ai_trade_system.scripts.run_daily_plan --limit 20
```

运行完整盘后流程：

```bash
python3 -m ai_trade_system.scripts.run_auto_pipeline --mode quick --execute-sim
```

生成复盘报告：

```bash
python3 -m ai_trade_system.scripts.run_review
```

## 使用建议

- `quick` 是默认推荐模式
- `deep` 更适合候选股较少、且你愿意等待更久的时候
- 这套系统是“容错型”的
- 批量分析里单只股票失败，不再会让整条流水线整体失效
