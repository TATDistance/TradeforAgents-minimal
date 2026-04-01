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
    .hint-box{margin-top:12px;padding:12px 14px;border-radius:14px;background:rgba(59,130,246,.08);border:1px solid rgba(96,165,250,.18);color:#d7e3f4;font-size:14px;line-height:1.7}
    .hint-box a{color:#93c5fd;text-decoration:none;font-weight:700}
    .log-box{margin-top:12px;padding:12px 14px;border-radius:14px;background:#09111f;border:1px solid rgba(59,130,246,.16);color:#d7e3f4;font-size:13px;line-height:1.65;white-space:pre-wrap;overflow-wrap:anywhere;max-height:220px;overflow:auto}
    .form-grid{display:grid;grid-template-columns:repeat(12,1fr);gap:10px}
    .col-3{grid-column:span 3}
    .col-6{grid-column:span 6}
    .field label{display:block;color:var(--muted);font-size:13px;margin-bottom:8px}
    .field input,.field select{width:100%;padding:12px 14px;border-radius:14px;border:1px solid var(--line);background:rgba(15,23,42,.92);color:var(--text);outline:none}
    .field input::placeholder{color:#7589a8}
    .setting-note{margin-top:10px;color:#9fb2cf;font-size:13px;line-height:1.65}
    .setting-status{margin-top:10px;padding:12px 14px;border-radius:14px;background:rgba(15,23,42,.8);border:1px solid rgba(59,130,246,.12);color:#d7e3f4;font-size:14px}
    .small-btn{display:inline-flex;align-items:center;justify-content:center;padding:10px 14px;border-radius:12px;border:1px solid rgba(96,165,250,.2);background:rgba(59,130,246,.14);color:#d9e8ff;font-weight:700;cursor:pointer}
    .hero-actions{display:flex;gap:10px;flex-wrap:wrap;margin-top:14px}
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
          <div class="hero-actions">
            <button id="homeAutoPipeline" type="button" class="small-btn">自动选股并生成计划</button>
            <button id="homeStartAll" type="button" class="small-btn">一键启动 AI 实时决策</button>
            <a href="http://127.0.0.1:8610/" target="_blank" class="small-btn" style="text-decoration:none">打开 8610 调试面板</a>
          </div>
          <div id="homeStartStatus" class="setting-status" style="margin-top:12px">首页不会自动启动引擎；如需开始实时模拟，请手动点击上面的按钮。</div>
          <div id="homeTaskLog" class="log-box" style="display:none"></div>
          <div id="systemHint" class="hint-box" style="display:none"></div>
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

      <div class="card span-6">
        <h3>可执行机会摘要</h3>
        <div class="kv" id="opportunityGrid"></div>
      </div>

      <div class="card span-6">
        <h3>分数拆解面板</h3>
        <div id="scoreBreakdowns" class="action-list"></div>
      </div>

      <div class="card span-8">
        <h3>实时动作</h3>
        <div id="actionList" class="action-list"></div>
      </div>

      <div class="card span-4">
        <h3>账户信息</h3>
        <div class="kv" id="accountGrid"></div>
      </div>

      <div class="card span-12">
        <h3>为什么现在没有买入</h3>
        <div id="noBuyReasons" class="action-list"></div>
      </div>

      <div class="card span-12">
        <h3>观察股距离买入还差什么</h3>
        <div class="subvalue" style="margin-bottom:12px">这里会同时展示两类分数：`静态候选分` 来自自动选股结果，盘中不会变化；`实时综合分` 来自实时引擎，会随行情、阶段、风险模式和 AI 决策动态更新。</div>
        <div id="observeCandidates" class="action-list"></div>
      </div>
    </div>
  </div>

  <script>
    const summaryText = document.getElementById('summaryText');
    const systemStatus = document.getElementById('systemStatus');
    const systemHint = document.getElementById('systemHint');
    const systemError = document.getElementById('systemError');
    const statusTags = document.getElementById('statusTags');
    const lastUpdated = document.getElementById('lastUpdated');
    const phaseGrid = document.getElementById('phaseGrid');
    const strategyGrid = document.getElementById('strategyGrid');
    const accountGrid = document.getElementById('accountGrid');
    const statsGrid = document.getElementById('statsGrid');
    const opportunityGrid = document.getElementById('opportunityGrid');
    const scoreBreakdowns = document.getElementById('scoreBreakdowns');
    const actionList = document.getElementById('actionList');
    const noBuyReasons = document.getElementById('noBuyReasons');
    const observeCandidates = document.getElementById('observeCandidates');
    const bindProvider = document.getElementById('bindProvider');
    const bindModel = document.getElementById('bindModel');
    const bindBaseUrl = document.getElementById('bindBaseUrl');
    const bindApiKey = document.getElementById('bindApiKey');
    const saveBinding = document.getElementById('saveBinding');
    const homeAutoPipeline = document.getElementById('homeAutoPipeline');
    const bindingStatus = document.getElementById('bindingStatus');
    const homeStartAll = document.getElementById('homeStartAll');
    const homeStartStatus = document.getElementById('homeStartStatus');
    const homeTaskLog = document.getElementById('homeTaskLog');

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

    async function fetchJsonSafe(url, options){
      const resp = await fetch(url, options || {});
      const text = await resp.text();
      try{
        return {resp, data: text ? JSON.parse(text) : {}};
      }catch(_err){
        return {resp, data: {detail: text || '空响应'}};
      }
    }

    function formatErrorDetail(detail){
      if(typeof detail === 'string') return detail;
      if(detail && typeof detail === 'object'){
        if(Array.isArray(detail)) return detail.map(item => formatErrorDetail(item)).join('; ');
        if(detail.msg) return String(detail.msg);
        try{
          return JSON.stringify(detail);
        }catch(_err){
          return String(detail);
        }
      }
      return String(detail || '未知错误');
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

    function renderNoBuyReasons(items){
      if(!items || !items.length){
        noBuyReasons.innerHTML = '<div class="empty">当前没有额外解释，默认视为：系统未发现足够强的可执行买入条件。</div>';
        return;
      }
      noBuyReasons.innerHTML = items.map(item => (
        '<div class="action-card">' +
        '<div class="action-top">' +
        '<div class="action-title">原因说明</div>' +
        '<div class="badge badge-warning">观察</div>' +
        '</div>' +
        '<div class="action-reason">' + item + '</div>' +
        '</div>'
      )).join('');
    }

    function renderObserveCandidates(items){
      if(!items || !items.length){
        observeCandidates.innerHTML = '<div class="empty">当前没有可解释的观察股，通常表示还没有生成候选池，或本轮没有重点观察标的。</div>';
        return;
      }
      observeCandidates.innerHTML = items.map(item => (
        '<div class="action-card">' +
        '<div class="action-top">' +
        '<div><div class="action-title">' + item.symbol + ' ' + (item.name || '') + '</div><div class="subvalue">' + (item.stance || '观察') + ' ｜ 静态候选分 ' + Number(item.score || 0).toFixed(2) + ' ｜ setup ' + Number(item.setup_score || 0).toFixed(2) + ' ｜ execution ' + Number(item.execution_score || 0).toFixed(2) + '</div></div>' +
        '<div class="badge badge-neutral">' + (item.current_action || 'HOLD') + '</div>' +
        '</div>' +
        '<div class="action-meta">' +
        '<span>AI 加分 ' + Number(item.ai_score || 0).toFixed(2) + '</span>' +
        '</div>' +
        '<div class="action-reason">' + (item.reasons || []).map(reason => '· ' + reason).join('<br>') + '</div>' +
        '</div>'
      )).join('');
    }

    function renderScoreBreakdowns(items){
      if(!items || !items.length){
        scoreBreakdowns.innerHTML = '<div class="empty">当前没有可展示的实时分数拆解，通常表示实时引擎尚未完成本轮决策。</div>';
        return;
      }
      scoreBreakdowns.innerHTML = items.map(item => (
        '<div class="action-card">' +
        '<div class="action-top">' +
        '<div><div class="action-title">' + item.symbol + ' ' + (item.name || '') + '</div><div class="subvalue">AI 动作 ' + (item.action || 'HOLD') + '</div></div>' +
        '<div class="badge badge-neutral">execution ' + Number(item.execution_score || 0).toFixed(2) + '</div>' +
        '</div>' +
        '<div class="action-meta">' +
        '<span>setup ' + Number(item.setup_score || 0).toFixed(2) + '</span>' +
        '<span>feature ' + Number(item.feature_score || 0).toFixed(2) + '</span>' +
        '<span>AI ' + Number(item.ai_score || 0).toFixed(2) + '</span>' +
        '<span>市场惩罚 ' + Number(item.market_risk_penalty || 0).toFixed(2) + '</span>' +
        '<span>组合惩罚 ' + Number(item.portfolio_risk_penalty || 0).toFixed(2) + '</span>' +
        '<span>阶段惩罚 ' + Number(item.phase_penalty || 0).toFixed(2) + '</span>' +
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
        if(status.state === 'stopped'){
          systemHint.style.display = 'block';
          systemHint.innerHTML = '实时引擎当前未运行。你可以直接使用首页的“ 一键启动 AI 实时决策 ”重新启动；如果需要排查原因，再前往 <a href="/debug">调试总览</a> 查看 8610 调试面板入口和最近错误。';
        }else if(status.state === 'error'){
          systemHint.style.display = 'block';
          systemHint.innerHTML = '实时引擎当前处于异常状态。你可以直接点击首页的“ 一键启动 AI 实时决策 ”尝试恢复；如果仍有异常，再去 <a href="/debug">调试总览</a> 查看 8610 调试面板入口和最近错误。';
        }else{
          systemHint.style.display = 'none';
          systemHint.innerHTML = '';
        }
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
          '<span class="state-tag">引擎模式：' + (data.engine_mode || '-') + '</span>',
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
        const opportunities = data.opportunities || {};
        renderStatGrid(opportunityGrid, [
          {label:'可建仓机会', value: String(opportunities.buy_count || 0), subvalue: (opportunities.top_limitations || [])[0] || '当前暂无高优先级建仓机会'},
          {label:'可减仓机会', value: String(opportunities.reduce_count || 0), subvalue: (opportunities.top_limitations || [])[1] || '当前暂无高优先级减仓机会'}
        ]);

        renderActions(data.actions || []);
        renderNoBuyReasons(data.no_buy_reasons || []);
        renderScoreBreakdowns(data.score_breakdowns || []);
        renderObserveCandidates(data.observe_candidates || []);
      }catch(err){
        summaryText.textContent = '首页加载失败';
        systemStatus.innerHTML = '<span class="status-pill status-error">运行异常</span>';
        systemError.style.display = 'block';
        systemError.textContent = String(err);
      }
    }

    async function runHomeQuickStart(){
      homeStartAll.disabled = true;
      homeAutoPipeline.disabled = true;
      homeStartStatus.textContent = '正在准备环境并启动实时 AI 决策...';
      try{
        let result = await fetchJsonSafe('/api/ai-stock-sim/status');
        let resp = result.resp;
        let data = result.data;
        if(!resp.ok){
          throw new Error(formatErrorDetail(data.detail));
        }

        result = await fetchJsonSafe('/api/ai-stock-sim/sync-watchlist', {method:'POST'});
        resp = result.resp;
        data = result.data;
        if(!resp.ok){
          homeStartStatus.textContent = '候选池同步提示：' + formatErrorDetail(data.detail);
        }else{
          homeStartStatus.textContent = data.message || '已同步最新候选池';
        }

        if(!data.bootstrap_ready){
          result = await fetchJsonSafe('/api/ai-stock-sim/bootstrap', {method:'POST'});
          resp = result.resp;
          data = result.data;
          if(!resp.ok){
            throw new Error(formatErrorDetail(data.detail));
          }
        }

        result = await fetchJsonSafe('/api/ai-stock-sim/engine/start', {method:'POST'});
        resp = result.resp;
        data = result.data;
        if(!resp.ok){
          throw new Error(formatErrorDetail(data.detail));
        }

        result = await fetchJsonSafe('/api/ai-stock-sim/dashboard/start', {method:'POST'});
        resp = result.resp;
        data = result.data;
        if(!resp.ok){
          throw new Error(formatErrorDetail(data.detail));
        }

        homeStartStatus.textContent = '实时 AI 决策中心已启动。现在可以继续看首页状态，或点“打开 8610 调试面板”。';
        await loadHome();
      }catch(err){
        homeStartStatus.textContent = '一键启动失败：' + String(err);
      }finally{
        homeStartAll.disabled = false;
        homeAutoPipeline.disabled = false;
      }
    }

    async function pollTask(taskId, successMessage){
      let done = false;
      homeTaskLog.style.display = 'block';
      while(!done){
        const resp = await fetch('/api/task/' + taskId + '?ts=' + Date.now(), {cache:'no-store'});
        const data = await resp.json();
        const elapsed = data.started_at
          ? '（已运行 ' + Math.max(0, Math.floor((Date.now() - Date.parse(data.started_at)) / 1000)) + 's）'
          : '';
        homeStartStatus.textContent = '任务状态：' + data.status + ' ' + elapsed;
        homeTaskLog.textContent = data.output || '后台任务已创建，等待输出...';
        homeTaskLog.scrollTop = homeTaskLog.scrollHeight;
        if(data.status === 'done'){
          homeStartStatus.textContent = successMessage;
          if(data.report_url){
            homeStartStatus.textContent += ' 你可以去研究中心或复盘中心查看结果。';
          }
          await loadHome();
          done = true;
        }else if(data.status === 'failed'){
          homeStartStatus.textContent = '任务失败：' + String(data.error || '请查看日志');
          if(!data.output){
            homeTaskLog.textContent = '任务失败，但后端没有返回详细输出。';
          }
          done = true;
        }else{
          await new Promise(resolve => setTimeout(resolve, 3000));
        }
      }
    }

    async function runHomeAutoPipeline(){
      homeAutoPipeline.disabled = true;
      homeStartAll.disabled = true;
      homeStartStatus.textContent = '正在启动自动选股并生成计划...';
      try{
        const payload = {
          scan_limit: 300,
          top_n: 12,
          bar_limit: 120,
          mode: 'quick',
          request_timeout: 120,
          retries: 1,
          direction_cache_days: 3,
          execute_sim: true,
          skip_ai: false,
          force_refresh_universe: false,
          force_full_analysis: false,
          api_key: (bindApiKey.value || '').trim(),
          base_url: bindBaseUrl.value || ''
        };
        const result = await fetchJsonSafe('/api/auto-pipeline', {
          method:'POST',
          headers:{'Content-Type':'application/json'},
          body: JSON.stringify(payload)
        });
        const resp = result.resp;
        const data = result.data;
        if(!resp.ok){
          throw new Error(formatErrorDetail(data.detail));
        }
        homeStartStatus.textContent = '自动选股任务已创建，正在执行...';
        await pollTask(data.task_id, '自动选股并生成计划已完成。现在首页启动实时 AI 决策会优先沿用最新候选池。');
      }catch(err){
        homeStartStatus.textContent = '自动选股失败：' + String(err);
      }finally{
        homeAutoPipeline.disabled = false;
        homeStartAll.disabled = false;
      }
    }

    bindProvider.addEventListener('change', saveBindingConfig);
    bindModel.addEventListener('change', saveBindingConfig);
    bindBaseUrl.addEventListener('change', saveBindingConfig);
    bindApiKey.addEventListener('change', saveBindingConfig);
    saveBinding.addEventListener('click', saveBindingConfig);
    homeAutoPipeline.addEventListener('click', runHomeAutoPipeline);
    homeStartAll.addEventListener('click', runHomeQuickStart);

    loadBindingConfig();
    loadHome();
    setInterval(loadHome, 5000);
  </script>
</body>
</html>""".replace("__WEB_BUILD_TAG__", build_tag)
