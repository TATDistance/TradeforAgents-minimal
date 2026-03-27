# TradeforAgents Minimal

一个可独立部署的极简股票分析工具，现在同时包含：
- 输入股票代码
- 调用 DeepSeek 生成多模块报告（支持 quick/deep 双模式）
- 导出可转发分享页（HTML/Word）
- 盘后自动选股
- 交易计划、模拟盘与复盘

## 快速上手（推荐）

仓库地址：

`https://github.com/TATDistance/TradeforAgents-minimal`

在 Ubuntu / WSL 终端执行：

```bash
git clone https://github.com/TATDistance/TradeforAgents-minimal.git
cd TradeforAgents-minimal
bash start.sh web
```

然后浏览器打开：

`http://127.0.0.1:8600`

在页面里填写：
- 股票代码（例如 `600028`）
- API Key（自己的）
- Base URL（下拉选择）
- 模式（`quick` 或 `deep`）

点击“开始分析”即可。

分析完成后结果在：

`results/<股票代码>/<日期>/`

分享文件在：

`results/<股票代码>/<日期>/share/<股票代码>_<日期>_share.html`

如果要从同局域网其他设备访问（例如手机）：
- 先查运行机器 IP（例如 `192.168.6.239`）
- 访问 `http://192.168.6.239:8600`

如果提示 `8600` 端口被占用，可先执行：

```bash
pkill -f "minimal_web_app.py" || true
bash start.sh web
```

## 目录

- `scripts/minimal_deepseek_report.py`：命令行分析器
- `scripts/minimal_web_app.py`：极简 Web 界面（手机可访问）
- `scripts/run_minimal_deepseek.sh`：CLI 启动脚本
- `scripts/run_minimal_web_app.sh`：Web 启动脚本
- `scripts/one_click_start.sh`：本地一键初始化+启动
- `start.sh`：根目录快捷入口
- `scripts/cloud_bootstrap_minimal.sh`：云端一键部署脚本
- `docs/minimal_cloud_deploy.md`：部署说明
- `ai_trade_system/`：自动选股、交易计划、模拟盘、复盘源码

## 集成后的推荐流程

现在 Web 首页已经接入一条更完整的盘后工作流：

1. 自动选股
2. AI 分析候选股
3. 生成次日交易计划
4. 模拟盘验证
5. 人工确认实盘

访问 `http://127.0.0.1:8600` 后，直接使用首页的：

- `步骤 1：自动选股与生成计划`
- `步骤 3：交易计划、模拟盘与复盘`

如果只是临时分析个股，再展开页面底部的“高级工具”。

## AI Trade System CLI

仓库内已经集成 `ai_trade_system`，常用命令如下：

初始化本地模拟账户：

```bash
python3 -m ai_trade_system.scripts.bootstrap_db --cash 100000
```

根据已有分析结果生成交易计划：

```bash
python3 -m ai_trade_system.scripts.run_daily_plan --limit 20
```

跑自动选股流水线：

```bash
python3 -m ai_trade_system.scripts.run_auto_pipeline --mode quick --execute-sim
```

生成复盘报告：

```bash
python3 -m ai_trade_system.scripts.run_review
```

## 一键运行（推荐）

```bash
bash start.sh web
```

首次运行会自动：
- 创建 `.venv`
- 安装 `requirements.txt`
- 生成 `.env`（若不存在）

访问：`http://127.0.0.1:8600`

说明：
- 可以直接在 Web 页面填写 `API Key`（无需先改 `.env`）
- 页面可选 `quick`（更快）/`deep`（更深度）

## 一键 CLI

```bash
bash start.sh cli 600028 --quick
bash start.sh cli 518880 --deep
bash start.sh cli 000630 --mode deep --final-model deepseek-reasoner --request-timeout 120 --retries 2
```

## 传统方式（手动）

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
cp .env.example .env
```

编辑 `.env`：

```bash
DEEPSEEK_API_KEY=sk-xxxx
DEEPSEEK_BASE_URL=https://api.deepseek.com
```

Web：

```bash
bash scripts/run_minimal_web_app.sh
```

CLI：

```bash
bash scripts/run_minimal_deepseek.sh 600028 --request-timeout 120 --retries 2
bash scripts/run_minimal_deepseek.sh 600028 --quick
bash scripts/run_minimal_deepseek.sh 600028 --deep
```

## 输出

报告默认在：

`results/<股票代码>/<日期>/`

核心文件：

- `analysis_metadata.json`
- `decision.json`
- `message_tool.log`
- `module_metrics.json`
- `module_metrics_summary.json`

分享文件在（个股+日期命名）：

- `results/<股票代码>/<日期>/share/<股票代码>_<日期>_share.html`
- `results/<股票代码>/<日期>/share/<股票代码>_<日期>_share.md`
- `results/<股票代码>/<日期>/share/<股票代码>_<日期>_share.docx`

模块统计表在：

- `results/<股票代码>/<日期>/reports/module_metrics.md`

缓存文件在：

`results/_cache/`

## 速度与稳定性策略

- `quick` 模式：默认更快（建议日常用）
- `deep` 模式：最终决策默认用 `deepseek-reasoner`
- 分析师模块并行执行（市场/基本面/新闻）
- 模块失败自动降级继续输出（可用 `--strict` 改为失败即退出）
