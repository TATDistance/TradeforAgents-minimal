# TradeforAgents Minimal

一个可独立部署的极简股票分析工具：
- 输入股票代码
- 调用 DeepSeek 生成多模块报告
- 导出可转发分享页（HTML/Word）

## 目录

- `scripts/minimal_deepseek_report.py`：命令行分析器
- `scripts/minimal_web_app.py`：极简 Web 界面（手机可访问）
- `scripts/run_minimal_deepseek.sh`：CLI 启动脚本
- `scripts/run_minimal_web_app.sh`：Web 启动脚本
- `scripts/one_click_start.sh`：本地一键初始化+启动
- `start.sh`：根目录快捷入口
- `scripts/cloud_bootstrap_minimal.sh`：云端一键部署脚本
- `docs/minimal_cloud_deploy.md`：部署说明

## 一键运行（推荐）

```bash
bash start.sh web
```

首次运行会自动：
- 创建 `.venv`
- 安装 `requirements.txt`
- 生成 `.env`（若不存在）

然后你只需要在 `.env` 填入：
- `DEEPSEEK_API_KEY=sk-xxxx`

再次运行：

```bash
bash start.sh web
```

访问：`http://127.0.0.1:8600`

## 一键 CLI

```bash
bash start.sh cli 600028
bash start.sh cli 518880 --reasoner --request-timeout 120 --retries 2
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
```

## 输出

报告默认在：

`results/<股票代码>/<日期>/`

分享文件在：

`results/<股票代码>/<日期>/share/wechat_share.html`
