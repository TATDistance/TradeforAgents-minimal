# 云端部署说明（安卓可访问）

本方案目标：
- 朋友在安卓手机浏览器打开网址
- 输入股票代码即可触发分析
- 自动生成并打开 `wechat_share.html`

当前云端网页侧的大模型接入约束：

- 当前只支持 `DeepSeek`
- 因此部署时必须准备可用的 `DeepSeek API Key`
- 页面里虽然会显示模型与 Base URL，但当前推荐和默认都围绕 `DeepSeek`

## 1. 云服务器准备

建议 Ubuntu 22.04，2C4G 起步。

开放端口：
- `8600`（先直连测试）
- `80/443`（后续反代 HTTPS）

## 0. 一键方式（推荐）

在云服务器执行（需要 root/sudo）：

```bash
cd /opt
git clone <你的仓库地址> TradeforAgents-minimal
cd TradeforAgents-minimal

sudo bash scripts/cloud_bootstrap_minimal.sh \
  --repo-url <你的仓库地址> \
  --api-key sk-xxxx \
  --domain your.domain.com \
  --email you@example.com
```

部署完成后直接把 `https://your.domain.com` 发给朋友即可（会有访问密码保护）。

## 2. 拉起项目

```bash
cd /opt
git clone <你的仓库地址> TradeforAgents-minimal
cd TradeforAgents-minimal

python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
```

配置 `.env`（至少要有）：

```bash
DEEPSEEK_API_KEY=sk-xxxx
DEEPSEEK_BASE_URL=https://api.deepseek.com
```

建议同步给使用者说明：

- 第一次打开网页时，仍应在首页确认 `DeepSeek` 绑定配置
- 如果网页端没有显式填写 `API Key`，系统可能会回退到服务器上的 `.env`
- 如果你希望不同用户各自使用自己的 key，不要只依赖服务器 `.env`

## 3. 启动极简 Web

```bash
bash scripts/run_minimal_web_app.sh
```

访问：

```text
http://<你的服务器IP>:8600
```

## 4. 配成 systemd（开机自启）

创建 `/etc/systemd/system/tradingagents-minimal.service`：

```ini
[Unit]
Description=TradingAgents Minimal Web
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/TradeforAgents-minimal
ExecStart=/opt/TradeforAgents-minimal/scripts/run_minimal_web_app.sh
Restart=always
RestartSec=3
Environment=MINIMAL_WEB_HOST=0.0.0.0
Environment=MINIMAL_WEB_PORT=8600

[Install]
WantedBy=multi-user.target
```

启用：

```bash
systemctl daemon-reload
systemctl enable --now tradingagents-minimal
systemctl status tradingagents-minimal
```

## 5. HTTPS（推荐）

建议用 Nginx/Caddy 反代到 `127.0.0.1:8600`，并配域名证书。

> 安全建议：最少加 BasicAuth，避免公网被滥用刷 API 费用。

---

## 常见问题

1. 分析任务经常超时  
建议在页面里把超时设为 `120` 以上，模型优先用 `deepseek-chat`。

2. `127.0.0.1` 请求返回 502  
通常是代理导致，请设置：

```bash
export NO_PROXY=127.0.0.1,localhost
```

3. 看不到分享页  
成功后应存在：
`results/<股票代码>/<日期>/share/wechat_share.html`
