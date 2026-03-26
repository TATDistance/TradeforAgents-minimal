#!/usr/bin/env python3
from __future__ import annotations

import os
import re
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import uvicorn


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "minimal_deepseek_report.py"
RESULTS_DIR = PROJECT_ROOT / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


class AnalyzeRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=64)
    model: str = Field(default="deepseek-chat")
    request_timeout: float = Field(default=120.0, ge=10.0, le=600.0)
    retries: int = Field(default=2, ge=0, le=5)
    api_key: str = Field(default="", max_length=256)
    base_url: str = Field(default="", max_length=256)


@dataclass
class TaskState:
    task_id: str
    symbol: str
    model: str
    status: str = "queued"  # queued|running|done|failed
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    exit_code: Optional[int] = None
    output: str = ""
    error: str = ""
    share_url: Optional[str] = None


TASKS: Dict[str, TaskState] = {}
TASK_LOCK = threading.Lock()

app = FastAPI(title="TradingAgents-CN Minimal Web")
app.mount("/results", StaticFiles(directory=str(RESULTS_DIR)), name="results")


def _python_bin() -> str:
    venv_python = PROJECT_ROOT / ".venv" / "bin" / "python"
    if venv_python.exists():
        return str(venv_python)
    return "python3"


def _append_output(task_id: str, text: str) -> None:
    with TASK_LOCK:
        task = TASKS.get(task_id)
        if task is None:
            return
        task.output = (task.output + text)[-50000:]


def _run_task(task_id: str, req: AnalyzeRequest) -> None:
    with TASK_LOCK:
        task = TASKS[task_id]
        task.status = "running"
        task.started_at = datetime.now().isoformat()

    analysis_date = datetime.now().strftime("%Y-%m-%d")
    cmd = [
        _python_bin(),
        str(SCRIPT_PATH),
        req.symbol.strip(),
        "--date",
        analysis_date,
        "--model",
        req.model.strip(),
        "--request-timeout",
        str(req.request_timeout),
        "--retries",
        str(req.retries),
    ]
    if req.api_key.strip():
        cmd.extend(["--api-key", req.api_key.strip()])
    if req.base_url.strip():
        cmd.extend(["--base-url", req.base_url.strip()])

    env = os.environ.copy()
    # 若没有导出，尝试读项目 .env
    if not env.get("DEEPSEEK_API_KEY") and not req.api_key.strip():
        env_file = PROJECT_ROOT / ".env"
        if env_file.exists():
            for raw in env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
                if raw.startswith("DEEPSEEK_API_KEY="):
                    key = raw.split("=", 1)[1].strip().strip('"').strip("'")
                    if key:
                        env["DEEPSEEK_API_KEY"] = key
                        break

    if not env.get("DEEPSEEK_API_KEY") and not req.api_key.strip():
        with TASK_LOCK:
            task = TASKS[task_id]
            task.status = "failed"
            task.error = "未设置 DEEPSEEK_API_KEY（可在页面填写或配置 .env）"
            task.finished_at = datetime.now().isoformat()
        return

    env["PYTHONUNBUFFERED"] = "1"
    max_task_seconds = int(os.getenv("MINIMAL_TASK_MAX_SECONDS", "1800"))
    start_ts = time.time()

    proc = subprocess.Popen(
        cmd,
        cwd=str(PROJECT_ROOT),
        env=env,
        stdout=subprocess.PIPE,  # type: ignore[arg-type]
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    _append_output(task_id, f"[web] 任务开始: {req.symbol.strip().upper()} model={req.model}\n")

    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            _append_output(task_id, line)
            if time.time() - start_ts > max_task_seconds:
                proc.kill()
                _append_output(task_id, f"\n[web] 超时终止: 超过 {max_task_seconds} 秒\n")
                break
    except Exception as e:
        _append_output(task_id, f"\n[web] 读取子进程输出异常: {e}\n")

    proc.wait()

    symbol = req.symbol.strip().upper()
    share_rel = f"/results/{symbol}/{analysis_date}/share/wechat_share.html"
    share_abs = RESULTS_DIR / symbol / analysis_date / "share" / "wechat_share.html"

    with TASK_LOCK:
        task = TASKS[task_id]
        task.exit_code = proc.returncode
        task.finished_at = datetime.now().isoformat()
        if proc.returncode == 0 and share_abs.exists():
            task.status = "done"
            task.share_url = share_rel
        else:
            task.status = "failed"
            task.error = "分析失败，请查看日志输出"


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>股票分析（极简版）</title>
  <style>
    body{font-family:-apple-system,BlinkMacSystemFont,'PingFang SC','Microsoft YaHei',sans-serif;max-width:840px;margin:0 auto;padding:20px;background:#f8fafc;color:#0f172a}
    .card{background:#fff;border-radius:14px;padding:18px;box-shadow:0 8px 24px rgba(15,23,42,.08)}
    input,select,button{width:100%;padding:10px 12px;font-size:16px;border:1px solid #cbd5e1;border-radius:10px;box-sizing:border-box}
    button{background:#2563eb;color:#fff;border:none;font-weight:600;cursor:pointer}
    button:disabled{opacity:.5;cursor:not-allowed}
    .row{display:grid;grid-template-columns:1fr 1fr;gap:12px}
    pre{background:#0f172a;color:#e2e8f0;border-radius:10px;padding:12px;overflow:auto;max-height:300px}
    .ok{color:#16a34a;font-weight:700}
    .err{color:#dc2626;font-weight:700}
  </style>
</head>
<body>
  <h2>TradingAgents-CN 极简版</h2>
  <div class="card">
    <label>股票代码</label>
    <input id="symbol" placeholder="例如 000630 / 600028 / 518880" />
    <p style="margin:6px 0 0;color:#64748b;font-size:13px;">这里只填股票代码，不要输入命令。示例：<code>600028</code></p>
    <div class="row" style="margin-top:10px">
      <div>
        <label>模型</label>
        <select id="model">
          <option value="deepseek-chat">deepseek-chat</option>
          <option value="deepseek-reasoner">deepseek-reasoner</option>
        </select>
      </div>
      <div>
        <label>超时(秒)</label>
        <input id="timeout" type="number" value="120" />
      </div>
    </div>
    <div class="row" style="margin-top:10px">
      <div>
        <label>API Key（必填）</label>
        <input id="apiKey" type="password" placeholder="sk-..." />
      </div>
      <div>
        <label>Base URL（下拉选择）</label>
        <select id="baseUrl">
          <option value="https://api.deepseek.com" selected>DeepSeek 官方（推荐）</option>
          <option value="https://api.deepseek.com/v1">DeepSeek 兼容 /v1</option>
          <option value="https://newapi.baosiapi.com/v1">OpenAI 中转示例（newapi.baosiapi.com）</option>
        </select>
      </div>
    </div>
    <button id="go" style="margin-top:12px">开始分析</button>
    <p id="status"></p>
    <p id="link"></p>
    <pre id="log"></pre>
  </div>

  <script>
    const go = document.getElementById('go');
    const symbol = document.getElementById('symbol');
    const model = document.getElementById('model');
    const timeout = document.getElementById('timeout');
    const apiKey = document.getElementById('apiKey');
    const baseUrl = document.getElementById('baseUrl');
    const statusEl = document.getElementById('status');
    const linkEl = document.getElementById('link');
    const logEl = document.getElementById('log');

    function formatErrorDetail(detail){
      if(!detail) return 'unknown error';
      if(typeof detail === 'string') return detail;
      if(Array.isArray(detail)){
        return detail.map(x => x.msg || JSON.stringify(x)).join('; ');
      }
      if(typeof detail === 'object'){
        return detail.msg || JSON.stringify(detail);
      }
      return String(detail);
    }

    function normalizeSymbolInput(raw){
      return (raw || '').trim().toUpperCase();
    }

    function validateSymbolInput(sym){
      // 允许示例: 600028 / 000630 / 518880 / AAPL / 0700.HK / 600028.SS
      return /^[A-Z0-9.\-]{1,20}$/.test(sym);
    }

    // 浏览器本地保存（仅当前浏览器）
    apiKey.value = localStorage.getItem('ta_min_api_key') || '';
    const savedBaseUrl = localStorage.getItem('ta_min_base_url');
    if(savedBaseUrl){
      const exists = Array.from(baseUrl.options).some(opt => opt.value === savedBaseUrl);
      if(exists) baseUrl.value = savedBaseUrl;
    }
    apiKey.onchange = () => localStorage.setItem('ta_min_api_key', apiKey.value.trim());
    baseUrl.onchange = () => localStorage.setItem('ta_min_base_url', baseUrl.value);

    function elapsedText(startedAt){
      if(!startedAt) return '';
      const s = Math.max(0, Math.floor((Date.now() - Date.parse(startedAt)) / 1000));
      return `（已运行 ${s}s）`;
    }

    async function poll(taskId){
      let done = false;
      while(!done){
        const r = await fetch('/api/task/' + taskId);
        const data = await r.json();
        statusEl.textContent = '状态: ' + data.status + ' ' + elapsedText(data.started_at);
        logEl.textContent = data.output || '';
        logEl.scrollTop = logEl.scrollHeight;
        if(data.status === 'done'){
          statusEl.className = 'ok';
          const htmlUrl = data.share_url;
          const docxUrl = data.share_url ? data.share_url.replace('.html', '.docx') : '';
          linkEl.innerHTML =
            '<a href="' + htmlUrl + '" target="_blank">打开分享页</a>' +
            ' | <a href="' + htmlUrl + '" download>下载HTML</a>' +
            (docxUrl ? ' | <a href="' + docxUrl + '" download>下载Word</a>' : '');
          done = true;
          go.disabled = false;
        } else if(data.status === 'failed'){
          statusEl.className = 'err';
          linkEl.textContent = data.error || '失败';
          done = true;
          go.disabled = false;
        } else {
          await new Promise(r => setTimeout(r, 3000));
        }
      }
    }

    go.onclick = async () => {
      const normalizedSymbol = normalizeSymbolInput(symbol.value);
      if(!normalizedSymbol){
        alert('请输入股票代码');
        return;
      }
      if(!validateSymbolInput(normalizedSymbol)){
        alert('股票代码格式错误。请只输入代码，例如 600028 或 AAPL');
        return;
      }
      if(!apiKey.value.trim()){
        alert('请填写 API Key');
        return;
      }
      go.disabled = true;
      statusEl.className = '';
      statusEl.textContent = '提交中...';
      linkEl.textContent = '';
      logEl.textContent = '';

      const resp = await fetch('/api/analyze', {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({
          symbol: normalizedSymbol,
          model: model.value,
          request_timeout: Number(timeout.value || 120),
          retries: 2,
          api_key: apiKey.value.trim(),
          base_url: baseUrl.value
        })
      });
      const data = await resp.json();
      if(!resp.ok){
        statusEl.className = 'err';
        statusEl.textContent = '提交失败';
        linkEl.textContent = formatErrorDetail(data.detail);
        go.disabled = false;
        return;
      }
      statusEl.textContent = '任务已创建: ' + data.task_id;
      poll(data.task_id);
    };
  </script>
</body>
</html>"""


@app.post("/api/analyze")
def analyze(req: AnalyzeRequest) -> Dict[str, str]:
    symbol = req.symbol.strip().upper()
    if not symbol:
        raise HTTPException(status_code=400, detail="股票代码不能为空")
    if not re.fullmatch(r"[A-Z0-9.\-]{1,20}", symbol):
        raise HTTPException(
            status_code=400,
            detail="股票代码格式错误。请只输入代码，例如 600028 / 000630 / 518880 / AAPL / 0700.HK",
        )
    task_id = uuid.uuid4().hex[:12]
    state = TaskState(task_id=task_id, symbol=symbol, model=req.model)
    with TASK_LOCK:
        TASKS[task_id] = state
    thread = threading.Thread(target=_run_task, args=(task_id, req), daemon=True)
    thread.start()
    return {"task_id": task_id}


@app.get("/api/task/{task_id}")
def get_task(task_id: str) -> Dict[str, object]:
    with TASK_LOCK:
        task = TASKS.get(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="任务不存在")
        return asdict(task)


if __name__ == "__main__":
    host = os.getenv("MINIMAL_WEB_HOST", "0.0.0.0")
    port = int(os.getenv("MINIMAL_WEB_PORT", "8600"))
    uvicorn.run(app, host=host, port=port, reload=False)
