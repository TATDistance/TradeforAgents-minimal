from __future__ import annotations


def render_ai_trading_home(build_tag: str) -> str:
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta http-equiv="Cache-Control" content="no-store, no-cache, must-revalidate, max-age=0" />
  <meta http-equiv="Pragma" content="no-cache" />
  <meta http-equiv="Expires" content="0" />
  <title>AI 实时决策首页</title>
  <style>
    :root{
      --bg:#09111f;--panel:#0f172a;--panel-soft:#111c33;--line:#1e2d4d;--text:#e5edf9;--muted:#8da2c0;
      --blue:#3b82f6;--blue-soft:#0f264d;--green:#22c55e;--amber:#f59e0b;--red:#ef4444;--gray:#94a3b8;
    }
    *{box-sizing:border-box}
    body{margin:0;font-family:-apple-system,BlinkMacSystemFont,'PingFang SC','Microsoft YaHei',sans-serif;background:radial-gradient(circle at top,#112449 0%,#09111f 55%,#060b14 100%);color:var(--text)}
    .shell{max-width:1200px;margin:0 auto;padding:18px}
    .topbar{display:flex;justify-content:space-between;align-items:center;gap:16px;margin-bottom:18px}
    .brand h1{margin:0;font-size:32px}
    .brand p{margin:6px 0 0;color:var(--muted);font-size:15px}
    .nav{display:flex;gap:10px;flex-wrap:wrap}
    .nav a{color:#cfe1ff;text-decoration:none;background:rgba(59,130,246,.12);border:1px solid rgba(96,165,250,.18);padding:10px 14px;border-radius:999px;font-weight:600}
    .hero{background:linear-gradient(140deg,rgba(37,99,235,.25),rgba(15,23,42,.9));border:1px solid rgba(96,165,250,.16);border-radius:22px;padding:22px;display:grid;grid-template-columns:1.5fr 1fr;gap:18px}
    .hero h2{margin:0 0 10px;font-size:30px}
    .hero p{margin:0;color:#c5d4ea;line-height:1.7}
    .status-box{background:rgba(8,15,30,.65);border:1px solid var(--line);border-radius:18px;padding:16px}
    .status-pill{display:inline-flex;align-items:center;padding:7px 12px;border-radius:999px;font-weight:700;font-size:13px}
    .status-running{background:rgba(34,197,94,.15);color:#b6f0c9;border:1px solid rgba(34,197,94,.28)}
    .status-stopped{background:rgba(148,163,184,.14);color:#d4deed;border:1px solid rgba(148,163,184,.24)}
    .status-error{background:rgba(239,68,68,.14);color:#fecaca;border:1px solid rgba(239,68,68,.28)}
    .summary{margin-top:16px;background:rgba(10,20,38,.9);border:1px solid rgba(59,130,246,.18);border-radius:18px;padding:18px}
    .summary strong{display:block;font-size:15px;color:#93c5fd;margin-bottom:8px}
    .summary-text{font-size:22px;line-height:1.5}
    .grid{display:grid;grid-template-columns:repeat(12,1fr);gap:16px;margin-top:18px}
    .card{background:rgba(10,18,34,.9);border:1px solid var(--line);border-radius:20px;padding:18px}
    .card h3{margin:0 0 14px;font-size:18px}
    .span-4{grid-column:span 4}
    .span-6{grid-column:span 6}
    .span-8{grid-column:span 8}
    .span-12{grid-column:span 12}
    .kv{display:grid;grid-template-columns:1fr 1fr;gap:10px}
    .kv .item{background:rgba(15,23,42,.8);border:1px solid rgba(59,130,246,.12);border-radius:16px;padding:14px}
    .label{color:var(--muted);font-size:13px;margin-bottom:8px}
    .value{font-size:20px;font-weight:700}
    .subvalue{margin-top:6px;font-size:13px;color:#9fb2cf}
    .action-list{display:grid;gap:12px}
    .action-card{border-radius:18px;padding:16px;border:1px solid transparent;background:rgba(15,23,42,.8)}
    .action-top{display:flex;justify-content:space-between;align-items:flex-start;gap:12px}
    .action-title{font-size:18px;font-weight:700}
    .badge{display:inline-flex;align-items:center;padding:5px 10px;border-radius:999px;font-size:12px;font-weight:700}
    .badge-success{background:rgba(34,197,94,.14);color:#bbf7d0}
    .badge-danger{background:rgba(239,68,68,.14);color:#fecaca}
    .badge-warning{background:rgba(245,158,11,.14);color:#fde68a}
    .badge-neutral{background:rgba(148,163,184,.14);color:#dbe4f3}
    .badge-muted{background:rgba(71,85,105,.28);color:#cbd5e1}
    .action-meta{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px;color:#a7bbd8;font-size:13px}
    .action-reason{margin-top:12px;color:#d7e3f4;line-height:1.65}
    .state-row{display:flex;gap:10px;flex-wrap:wrap}
    .state-tag{padding:6px 10px;border-radius:999px;background:rgba(59,130,246,.1);color:#bfdbfe;font-size:13px;font-weight:600}
    .error-box{margin-top:12px;padding:12px 14px;border-radius:14px;background:rgba(127,29,29,.28);border:1px solid rgba(239,68,68,.22);color:#fecaca;font-size:14px}
    .empty{padding:18px;border-radius:16px;border:1px dashed rgba(148,163,184,.24);color:#9fb2cf;background:rgba(15,23,42,.45)}
    .footer-note{margin-top:18px;color:#8da2c0;font-size:13px}
    .form-grid{display:grid;grid-template-columns:repeat(12,1fr);gap:10px}
    .col-3{grid-column:span 3}
    .col-6{grid-column:span 6}
    .field label{display:block;color:var(--muted);font-size:13px;margin-bottom:8px}
    .field input,.field select{width:100%;padding:12px 14px;border-radius:14px;border:1px solid var(--line);background:rgba(15,23,42,.92);color:var(--text);outline:none}
    .field input::placeholder{color:#7589a8}
    .setting-note{margin-top:10px;color:#9fb2cf;font-size:13px;line-height:1.65}
    .setting-status{margin-top:10px;padding:12px 14px;border-radius:14px;background:rgba(15,23,42,.8);border:1px solid rgba(59,130,246,.12);color:#d7e3f4;font-size:14px}
    .small-btn{display:inline-flex;align-items:center;justify-content:center;padding:10px 14px;border-radius:12px;border:1px solid rgba(96,165,250,.2);background:rgba(59,130,246,.14);color:#d9e8ff;font-weight:700;cursor:pointer}
    @media (max-width: 980px){
      .hero{grid-template-columns:1fr}
      .span-4,.span-6,.span-8,.span-12{grid-column:span 12}
      .kv{grid-template-columns:1fr}
      .col-3,.col-6{grid-column:span 12}
      .topbar{flex-direction:column;align-items:flex-start}
    }
  </style>
</head>
<body>
  <div class="shell">
    <div class="topbar">
      <div class="brand">
        <div style="font-size:12px;color:#8fb4ff;margin-bottom:6px">页面版本：__WEB_BUILD_TAG__</div>
        <h1>AI 实时决策首页</h1>
        <p>默认入口只回答三件事：系统现在在做什么、现在能不能交易、AI 建议做什么。</p>
      </div>
      <div class="nav">
        <a href="/research">研究中心</a>
        <a href="/evaluation">复盘中心</a>
        <a href="/debug">调试总览</a>
      </div>
    </div>

    <div class="hero">
      <div>
        <h2 id="summaryText">正在读取当前 AI 决策摘要…</h2>
        <p id="summarySub">首页不会自动启动实时引擎，也不会触发交易动作；这里只展示当前状态、最近结果和导航入口。</p>
        <div class="summary">
          <strong>系统状态</strong>
          <div id="systemStatus"></div>
          <div id="systemError" class="error-box" style="display:none"></div>
        </div>
      </div>
      <div class="status-box">
        <div class="state-row" id="statusTags"></div>
        <div class="footer-note" id="lastUpdated">最近更新时间：-</div>
      </div>
    </div>

    <div class="grid">
      <div class="card span-12">
        <h3>用户设置</h3>
        <div class="form-grid">
          <div class="field col-3">
            <label>绑定大模型平台</label>
            <select id="bindProvider">
              <option value="deepseek" selected>DeepSeek</option>
            </select>
          </div>
          <div class="field col-3">
            <label>绑定模型</label>
            <select id="bindModel">
              <option value="deepseek-chat" selected>deepseek-chat</option>
              <option value="deepseek-reasoner">deepseek-reasoner</option>
            </select>
          </div>
          <div class="field col-3">
            <label>Base URL</label>
            <select id="bindBaseUrl">
              <option value="https://api.deepseek.com" selected>DeepSeek 官方（推荐）</option>
              <option value="https://api.deepseek.com/v1">DeepSeek 兼容 /v1</option>
              <option value="https://newapi.baosiapi.com/v1">OpenAI 中转示例（newapi.baosiapi.com）</option>
            </select>
          </div>
          <div class="field col-3">
            <label>API Key</label>
            <input id="bindApiKey" type="password" placeholder="sk-...（仅保存在当前浏览器）" />
          </div>
          <div class="field col-6">
            <button id="saveBinding" type="button" class="small-btn">保存首页 AI 绑定</button>
            <div id="bindingStatus" class="setting-status">当前运行中的实时引擎来源，仍以首页“AI 来源”为准。</div>
            <div class="setting-note">这里是用户确认当前绑定哪种大模型 AI 的地方。首页与研究中心共用这套浏览器本地配置。你现在用的是 DeepSeek 时，这里就会显示 `DeepSeek + deepseek-chat` 或 `DeepSeek + deepseek-reasoner`。</div>
          </div>
        </div>
      </div>

      <div class="card span-4">
        <h3>当前交易状态</h3>
        <div class="kv" id="phaseGrid"></div>
      </div>
      <div class="card span-4">
        <h3>AI 当前策略</h3>
        <div class="kv" id="strategyGrid"></div>
      </div>
      <div class="card span-4">
        <h3>执行统计</h3>
        <div class="kv" id="statsGrid"></div>
      </div>

      <div class="card span-8">
        <h3>实时动作</h3>
        <div id="actionList" class="action-list"></div>
      </div>

      <div class="card span-4">
        <h3>账户信息</h3>
        <div class="kv" id="accountGrid"></div>
      </div>
    </div>
  </div>

  <script>
    const summaryText = document.getElementById('summaryText');
    const systemStatus = document.getElementById('systemStatus');
    const systemError = document.getElementById('systemError');
    const statusTags = document.getElementById('statusTags');
    const lastUpdated = document.getElementById('lastUpdated');
    const phaseGrid = document.getElementById('phaseGrid');
    const strategyGrid = document.getElementById('strategyGrid');
    const accountGrid = document.getElementById('accountGrid');
    const statsGrid = document.getElementById('statsGrid');
    const actionList = document.getElementById('actionList');
    const bindProvider = document.getElementById('bindProvider');
    const bindModel = document.getElementById('bindModel');
    const bindBaseUrl = document.getElementById('bindBaseUrl');
    const bindApiKey = document.getElementById('bindApiKey');
    const saveBinding = document.getElementById('saveBinding');
    const bindingStatus = document.getElementById('bindingStatus');

    function badgeClass(state){
      if(state === 'running') return 'status-running';
      if(state === 'error') return 'status-error';
      return 'status-stopped';
    }

    function cardBadgeClass(color){
      return {
        success: 'badge-success',
        danger: 'badge-danger',
        warning: 'badge-warning',
        muted: 'badge-muted',
        neutral: 'badge-neutral'
      }[color] || 'badge-neutral';
    }

    function fmtPct(value){
      return (Number(value || 0) * 100).toFixed(2) + '%';
    }

    function fmtNum(value){
      return Number(value || 0).toLocaleString('zh-CN', {minimumFractionDigits:2, maximumFractionDigits:2});
    }

    function renderStatGrid(target, rows){
      target.innerHTML = rows.map(row => (
        '<div class="item">' +
        '<div class="label">' + row.label + '</div>' +
        '<div class="value">' + row.value + '</div>' +
        (row.subvalue ? '<div class="subvalue">' + row.subvalue + '</div>' : '') +
        '</div>'
      )).join('');
    }

    function renderActions(actions){
      if(!actions || !actions.length){
        actionList.innerHTML = '<div class="empty">当前暂无高优先级动作。系统会继续显示阶段状态、账户信息和最近一次决策结果。</div>';
        return;
      }
      actionList.innerHTML = actions.map(item => (
        '<div class="action-card">' +
        '<div class="action-top">' +
        '<div><div class="action-title">' + item.symbol + ' ' + (item.name || '') + '</div><div class="subvalue">' + item.category_label + '</div></div>' +
        '<div class="badge ' + cardBadgeClass(item.category_color) + '">' + item.display_action + '</div>' +
        '</div>' +
        '<div class="action-meta">' +
        (item.position_pct ? '<span>仓位 ' + fmtPct(item.position_pct) + '</span>' : '') +
        (item.reduce_pct ? '<span>减仓 ' + fmtPct(item.reduce_pct) + '</span>' : '') +
        (item.planned_qty ? '<span>数量 ' + item.planned_qty + '</span>' : '') +
        (item.phase ? '<span>阶段 ' + item.phase + '</span>' : '') +
        '</div>' +
        '<div class="action-reason">' + (item.reason || '暂无说明') + '</div>' +
        '</div>'
      )).join('');
    }

    function loadBindingConfig(){
      bindProvider.value = localStorage.getItem('ta_home_provider') || 'deepseek';
      bindModel.value = localStorage.getItem('ta_min_model') || 'deepseek-chat';
      bindApiKey.value = localStorage.getItem('ta_min_api_key') || '';
      const savedBaseUrl = localStorage.getItem('ta_min_base_url') || 'https://api.deepseek.com';
      const exists = Array.from(bindBaseUrl.options).some(opt => opt.value === savedBaseUrl);
      if(exists) bindBaseUrl.value = savedBaseUrl;
      bindingStatus.textContent = '当前首页绑定：' + bindProvider.options[bindProvider.selectedIndex].text + ' / ' + bindModel.value;
    }

    function saveBindingConfig(){
      localStorage.setItem('ta_home_provider', bindProvider.value);
      localStorage.setItem('ta_min_model', bindModel.value);
      localStorage.setItem('ta_min_base_url', bindBaseUrl.value);
      localStorage.setItem('ta_min_api_key', bindApiKey.value.trim());
      bindingStatus.textContent = '已保存：' + bindProvider.options[bindProvider.selectedIndex].text + ' / ' + bindModel.value + '。研究中心会复用这套配置。';
    }

    async function loadHome(){
      try{
        const resp = await fetch('/api/ui/home?ts=' + Date.now(), {cache:'no-store'});
        const data = await resp.json();
        if(!resp.ok){
          throw new Error(data.detail || '读取首页失败');
        }
        summaryText.textContent = data.summary || '暂无摘要';
        const status = data.system_status || {};
        systemStatus.innerHTML = '<span class="status-pill ' + badgeClass(status.state) + '">' + (status.label || '未知') + '</span>';
        lastUpdated.textContent = '最近更新时间：' + (status.last_updated_at || '暂无');
        if(status.last_error){
          systemError.style.display = 'block';
          systemError.textContent = '最近错误：' + status.last_error;
        }else{
          systemError.style.display = 'none';
          systemError.textContent = '';
        }

        const phase = data.phase || {};
        const execution = data.execution || {};
        statusTags.innerHTML = [
          '<span class="state-tag">交易日：' + ((phase.is_trading_day ? '是' : '否')) + '</span>',
          '<span class="state-tag">阶段：' + (phase.phase_label || phase.phase || '-') + '</span>',
          '<span class="state-tag">允许成交：' + (execution.can_execute_fill ? 'YES' : 'NO') + '</span>',
          '<span class="state-tag">允许开仓：' + (execution.can_open_position ? 'YES' : 'NO') + '</span>'
        ].join('');

        renderStatGrid(phaseGrid, [
          {label:'交易日', value: phase.is_trading_day ? '是' : '否'},
          {label:'当前阶段', value: phase.phase_label || phase.phase || '-'},
          {label:'允许开仓', value: execution.can_open_position ? 'YES' : 'NO'},
          {label:'允许成交', value: execution.can_execute_fill ? 'YES' : 'NO'}
        ]);

        const strategyStatus = data.strategy_status || {};
        renderStatGrid(strategyGrid, [
          {label:'风险模式', value: strategyStatus.risk_mode || '-'},
          {label:'策略风格', value: strategyStatus.strategy_style || '-'},
          {label:'仓位策略', value: strategyStatus.position_strategy || '-'},
          {label:'AI 状态', value: strategyStatus.ai_status || '-'},
          {label:'AI 来源', value: strategyStatus.ai_source || '-', subvalue:'未在页面填写 API Key 时，可能来自本地 .env 或研究缓存'}
        ]);
        bindingStatus.textContent =
          '当前运行来源：' + (strategyStatus.ai_source || '未知') +
          '。当前首页绑定：' + bindProvider.options[bindProvider.selectedIndex].text + ' / ' + bindModel.value;

        const account = data.account || {};
        renderStatGrid(accountGrid, [
          {label:'总资产', value: fmtNum(account.equity)},
          {label:'现金比例', value: fmtPct(account.cash_ratio)},
          {label:'仓位', value: fmtPct(account.position_ratio)},
          {label:'浮盈亏', value: fmtNum(account.unrealized_pnl), subvalue: '回撤 ' + fmtPct(account.drawdown)}
        ]);

        const stats = data.stats || {};
        renderStatGrid(statsGrid, [
          {label:'意图数', value: String(stats.intent_count || 0)},
          {label:'成交数', value: String(stats.executed_count || 0)},
          {label:'被拦截数', value: String(stats.blocked_count || 0)}
        ]);

        renderActions(data.actions || []);
      }catch(err){
        summaryText.textContent = '首页加载失败';
        systemStatus.innerHTML = '<span class="status-pill status-error">运行异常</span>';
        systemError.style.display = 'block';
        systemError.textContent = String(err);
      }
    }

    bindProvider.addEventListener('change', saveBindingConfig);
    bindModel.addEventListener('change', saveBindingConfig);
    bindBaseUrl.addEventListener('change', saveBindingConfig);
    bindApiKey.addEventListener('change', saveBindingConfig);
    saveBinding.addEventListener('click', saveBindingConfig);

    loadBindingConfig();
    loadHome();
    setInterval(loadHome, 5000);
  </script>
</body>
</html>""".replace("__WEB_BUILD_TAG__", build_tag)
