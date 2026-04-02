from __future__ import annotations

try:
    from ai_stock_sim.dashboard.components.ai_decision_hero_card import render_ai_decision_hero_card
    from ai_stock_sim.dashboard.components.action_timeline_panel import render_action_timeline_panel
    from ai_stock_sim.dashboard.components.equity_curve_panel import render_equity_curve_panel
    from ai_stock_sim.dashboard.components.kline_panel import render_kline_panel
except ModuleNotFoundError:  # pragma: no cover - test/runtime import compatibility
    from dashboard.components.ai_decision_hero_card import render_ai_decision_hero_card
    from dashboard.components.action_timeline_panel import render_action_timeline_panel
    from dashboard.components.equity_curve_panel import render_equity_curve_panel
    from dashboard.components.kline_panel import render_kline_panel


def render_ai_trading_home(build_tag: str) -> str:
    hero_panel = render_ai_decision_hero_card()
    kline_panel = render_kline_panel()
    equity_curve_panel = render_equity_curve_panel()
    action_timeline_panel = render_action_timeline_panel()
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
    .hero h2{margin:0 0 10px;font-size:38px;line-height:1.25}
    .hero p{margin:0;color:#c5d4ea;line-height:1.7}
    .hero-kicker{font-size:12px;font-weight:800;letter-spacing:.12em;color:#9cc2ff;text-transform:uppercase;margin-bottom:10px}
    .hero-side-title{font-size:15px;font-weight:700;color:#cfe1ff;margin-bottom:10px}
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
    .watchlist-meta{display:flex;gap:10px;flex-wrap:wrap;margin:8px 0 14px;color:#9fb2cf;font-size:13px}
    .watchlist-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}
    .watch-section{display:grid;gap:12px;margin-bottom:14px}
    .watch-section-head{display:flex;justify-content:space-between;align-items:flex-end;gap:12px;flex-wrap:wrap}
    .watch-section-title{font-size:17px;font-weight:800}
    .watch-section-desc{color:#90a4c4;font-size:13px;line-height:1.6}
    .watch-item{border:1px solid rgba(59,130,246,.12);background:rgba(15,23,42,.78);border-radius:16px;padding:14px}
    .watch-item-top{display:flex;justify-content:space-between;gap:10px;align-items:flex-start}
    .watch-item h4{margin:0;font-size:16px}
    .watch-item .subvalue{margin-top:4px}
    .watch-item .meta{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px;color:#9fb2cf;font-size:12px}
    .watch-sections{display:grid;grid-template-columns:1.5fr 1fr;gap:16px}
    .watch-side{display:grid;gap:12px}
    .chart-toolbar{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:12px}
    .chart-toolbar select{min-width:220px;padding:10px 12px;border-radius:12px;border:1px solid var(--line);background:rgba(15,23,42,.92);color:var(--text)}
    .chart-focus{display:flex;justify-content:space-between;align-items:flex-end;gap:16px;flex-wrap:wrap}
    .chart-focus .focus-meta{display:grid;gap:6px}
    .chart-focus .focus-title{font-size:20px;font-weight:700}
    .chart-focus .focus-sub{color:#9fb2cf;font-size:13px;line-height:1.6}
    .chart-focus select{min-width:240px;padding:10px 12px;border-radius:12px;border:1px solid var(--line);background:rgba(15,23,42,.92);color:var(--text)}
    .chart-combo-grid{display:grid;grid-template-columns:1fr;gap:16px;margin-top:16px}
    .chart-panel-shell{background:rgba(15,23,42,.35);border:1px dashed rgba(59,130,246,.18);border-radius:18px;padding:14px}
    .chart-box{background:rgba(7,14,26,.9);border:1px solid rgba(59,130,246,.14);border-radius:16px;padding:12px;min-height:300px}
    .chart-svg{width:100%;height:280px;display:block}
    .chart-note{margin-top:10px;color:#9fb2cf;font-size:12px;line-height:1.6}
    .axis-text{fill:#8da2c0;font-size:12px}
    .grid-line{stroke:rgba(148,163,184,.16);stroke-width:1}
    .axis-line{stroke:rgba(148,163,184,.35);stroke-width:1.2}
    .chart-point-buy{fill:#22c55e}
    .chart-point-sell{fill:#ef4444}
    .chart-point-reduce{fill:#f59e0b}
    .chart-point-hold{fill:#94a3b8}
    .timeline-list{display:grid;gap:10px}
    .timeline-item{display:grid;grid-template-columns:88px 110px 90px 1fr;gap:12px;align-items:flex-start;padding:12px;border-radius:14px;border:1px solid rgba(59,130,246,.1);background:rgba(15,23,42,.78)}
    .timeline-status-intent{color:#93c5fd}
    .timeline-status-filled{color:#86efac}
    .timeline-status-rejected{color:#fca5a5}
    .legend{display:flex;gap:10px;flex-wrap:wrap;color:#9fb2cf;font-size:12px;margin:8px 0 0}
    .legend span{display:inline-flex;align-items:center;gap:6px}
    .dot{width:10px;height:10px;border-radius:999px;display:inline-block}
    .dot-buy{background:#22c55e}.dot-sell{background:#ef4444}.dot-reduce{background:#f59e0b}.dot-hold{background:#94a3b8}
    .decision-hero-grid{display:grid;grid-template-columns:1.15fr .85fr;gap:16px}
    .hero-summary-block{background:rgba(10,20,38,.82);border:1px solid rgba(59,130,246,.18);border-radius:18px;padding:18px}
    .hero-summary-label{font-size:13px;color:#9cc2ff;font-weight:700;margin-bottom:8px}
    .hero-summary-main{font-size:28px;font-weight:800;line-height:1.35}
    .hero-summary-explain{margin-top:10px;color:#cad7ea;font-size:15px;line-height:1.7}
    .decision-strip{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-top:16px}
    .decision-chip{background:rgba(15,23,42,.82);border:1px solid rgba(59,130,246,.14);border-radius:16px;padding:14px}
    .decision-chip .label{margin-bottom:6px}
    .decision-chip .value{font-size:18px}
    .hero-action-buy{color:#bbf7d0}
    .hero-action-sell{color:#fecaca}
    .hero-action-wait{color:#fde68a}
    .hero-action-hold{color:#bfdbfe}
    .core-symbol-card{display:grid;grid-template-columns:1.2fr .8fr;gap:16px}
    .core-symbol-main{display:grid;gap:10px}
    .core-symbol-title{font-size:28px;font-weight:800;line-height:1.2}
    .core-score-strip{display:flex;gap:10px;flex-wrap:wrap}
    .core-score-pill{padding:8px 12px;border-radius:999px;background:rgba(59,130,246,.12);border:1px solid rgba(96,165,250,.16);color:#dbeafe;font-size:13px;font-weight:700}
    .core-symbol-reason{font-size:15px;line-height:1.75;color:#dbe7f6}
    .monitoring-grid{display:grid;grid-template-columns:1.35fr .65fr;gap:16px}
    .holding-pool-card{background:rgba(15,23,42,.45);border:1px dashed rgba(59,130,246,.18);border-radius:18px;padding:14px}
    .chart-stack{display:grid;gap:16px}
    .opportunity-summary-list{display:grid;gap:12px}
    .opportunity-item{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;background:rgba(15,23,42,.78);border:1px solid rgba(59,130,246,.1);border-radius:16px;padding:14px}
    .muted-note{color:#90a4c4;font-size:13px;line-height:1.6}
    details.settings-card summary{cursor:pointer;list-style:none;font-weight:700}
    details.settings-card summary::-webkit-details-marker{display:none}
    @media (max-width: 980px){
      .hero{grid-template-columns:1fr}
      .span-4,.span-6,.span-8,.span-12{grid-column:span 12}
      .kv{grid-template-columns:1fr}
      .col-3,.col-6{grid-column:span 12}
      .topbar{flex-direction:column;align-items:flex-start}
      .watchlist-grid,.watch-sections,.chart-combo-grid,.decision-hero-grid,.core-symbol-card,.monitoring-grid{grid-template-columns:1fr}
      .timeline-item{grid-template-columns:1fr}
      .decision-strip{grid-template-columns:1fr}
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

    __HERO_PANEL__

    <div class="grid">
      <div class="card span-12">
        <h3>账户信息</h3>
        <div class="kv" id="accountGrid"></div>
      </div>

      <div class="card span-4">
        <h3>当前交易状态</h3>
        <div class="kv" id="phaseGrid"></div>
      </div>
      <div class="card span-4">
        <h3>执行权限与风险模式</h3>
        <div class="kv" id="strategyGrid"></div>
      </div>
      <div class="card span-4">
        <h3>当前动作统计</h3>
        <div class="kv" id="statsGrid"></div>
      </div>

      <div class="card span-12">
        <h3>AI 结论主卡</h3>
        <div class="decision-hero-grid">
          <div class="hero-summary-block">
            <div class="hero-summary-label">今日 AI 决策总结</div>
            <div class="hero-summary-main" id="heroAdviceMain">正在分析当前市场…</div>
            <div class="hero-summary-explain" id="heroAdviceExplain">系统会把当前能否交易、风险模式和最重要动作浓缩成一句清楚的人话总结。</div>
            <div class="decision-strip">
              <div class="decision-chip">
                <div class="label">市场状态</div>
                <div class="value" id="heroMarketState">读取中</div>
              </div>
              <div class="decision-chip">
                <div class="label">当前建议</div>
                <div class="value" id="heroActionAdvice">读取中</div>
              </div>
              <div class="decision-chip">
                <div class="label">是否可交易</div>
                <div class="value" id="heroTradeReady">读取中</div>
              </div>
            </div>
          </div>
          <div class="hero-summary-block">
            <div class="hero-summary-label">当前最重要的股票</div>
            <div id="coreSymbolCard" class="empty">正在计算当前最重要标的…</div>
          </div>
        </div>
      </div>

      <div class="card span-12">
        <h3>当前监控池</h3>
        <div class="watchlist-meta" id="watchlistMeta"></div>
        <div id="watchlistEvents" class="hint-box" style="display:none"></div>
        <div class="monitoring-grid">
          <div id="watchlistSections" class="watch-section"></div>
          <div class="holding-pool-card">
            <h3 style="margin-bottom:10px">持仓池</h3>
            <div id="holdingsPool" class="action-list"></div>
          </div>
        </div>
      </div>

      <div class="card span-12">
        <h3>最近买入 / 卖出解释</h3>
        <div class="monitoring-grid">
          <div>
            <h3 style="margin-bottom:10px">为什么买入</h3>
            <div id="buyExplainList" class="action-list"></div>
          </div>
          <div>
            <h3 style="margin-bottom:10px">为什么卖出 / 暂未卖出</h3>
            <div id="sellExplainList" class="action-list"></div>
          </div>
        </div>
      </div>

      <div class="card span-12">
        <div class="chart-focus">
          <div class="focus-meta">
            <div class="focus-title" id="chartFocusTitle">正在选择图表观察标的…</div>
            <div class="focus-sub" id="chartFocusSub">系统会优先展示当前持仓标的、execution_score 最高标的或最近有动作的标的。</div>
          </div>
          <div>
            <div class="label" style="margin-bottom:8px">观察标的</div>
            <select id="chartSymbolSelect"></select>
          </div>
        </div>
        <div class="chart-combo-grid">
          <div class="chart-panel-shell">
            <h3>分时图</h3>
            <div class="subvalue" style="margin-bottom:10px">优先展示当前最重要标的的盘中变化，并把买入、卖出、减仓动作直接叠加在图上。</div>
            <div id="intradayPanel" class="empty">正在加载图表数据…</div>
          </div>
        </div>
      </div>

      __EQUITY_PANEL__
      __KLINE_PANEL__
      __TIMELINE_PANEL__

      <div class="card span-12">
        <h3>可执行机会摘要</h3>
        <div class="kv" id="opportunityGrid"></div>
        <div class="opportunity-summary-list" id="opportunityCandidates" style="margin-top:14px"></div>
      </div>

      <div class="card span-12">
        <h3>实时动作</h3>
        <div id="actionList" class="action-list"></div>
      </div>

      <div class="card span-12">
        <h3>为什么现在没有买入</h3>
        <div id="noBuyReasons" class="action-list"></div>
      </div>

      <div class="card span-6">
        <h3>分数拆解面板</h3>
        <div id="scoreBreakdowns" class="action-list"></div>
      </div>

      <details class="card span-12 settings-card">
        <summary>模型与 API 设置</summary>
        <div class="form-grid" style="margin-top:16px">
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
            <div class="setting-note">配置项已经收进折叠区，避免打断前台决策视图。首页与研究中心共用这套浏览器本地配置。</div>
          </div>
        </div>
      </details>
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
    const opportunityCandidates = document.getElementById('opportunityCandidates');
    const scoreBreakdowns = document.getElementById('scoreBreakdowns');
    const actionList = document.getElementById('actionList');
    const noBuyReasons = document.getElementById('noBuyReasons');
    const watchlistMeta = document.getElementById('watchlistMeta');
    const watchlistEvents = document.getElementById('watchlistEvents');
    const watchlistSections = document.getElementById('watchlistSections');
    const holdingsPool = document.getElementById('holdingsPool');
    const buyExplainList = document.getElementById('buyExplainList');
    const sellExplainList = document.getElementById('sellExplainList');
    const chartSymbolSelect = document.getElementById('chartSymbolSelect');
    const intradayPanel = document.getElementById('intradayPanel');
    const klinePanel = document.getElementById('klinePanel');
    const equityCurvePanel = document.getElementById('equityCurvePanel');
    const actionTimelinePanel = document.getElementById('actionTimelinePanel');
    const chartFocusTitle = document.getElementById('chartFocusTitle');
    const chartFocusSub = document.getElementById('chartFocusSub');
    const heroAdviceMain = document.getElementById('heroAdviceMain');
    const heroAdviceExplain = document.getElementById('heroAdviceExplain');
    const heroMarketState = document.getElementById('heroMarketState');
    const heroActionAdvice = document.getElementById('heroActionAdvice');
    const heroTradeReady = document.getElementById('heroTradeReady');
    const coreSymbolCard = document.getElementById('coreSymbolCard');
    const bindProvider = document.getElementById('bindProvider');
    const bindModel = document.getElementById('bindModel');
    const bindBaseUrl = document.getElementById('bindBaseUrl');
    const bindApiKey = document.getElementById('bindApiKey');
    const saveBinding = document.getElementById('saveBinding');
    const bindingStatus = document.getElementById('bindingStatus');
    const homeStartAll = document.getElementById('homeStartAll');
    const homeStartStatus = document.getElementById('homeStartStatus');
    const homeTaskLog = document.getElementById('homeTaskLog');
    let latestHomePayload = null;
    let activeChartSymbol = '';

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

    function actionCn(action){
      const mapping = {
        BUY: '买入',
        SELL: '卖出',
        REDUCE: '减仓',
        HOLD: '持有',
        WAIT: '观望',
        AVOID: '观望',
        WATCH_NEXT_DAY: '观望',
        HOLD_FOR_TOMORROW: '持有',
        PREPARE_BUY: '买入准备',
        PREPARE_REDUCE: '减仓准备',
        AVOID_NEW_BUY: '观望'
      };
      return mapping[String(action || '').toUpperCase()] || String(action || '持有');
    }

    function riskModeCn(mode){
      const mapping = {NORMAL:'正常', DEFENSIVE:'防守', AGGRESSIVE:'进攻', RISK_OFF:'风险关闭'};
      return mapping[String(mode || '').toUpperCase()] || (mode || '正常');
    }

    function statusYesNo(ok){
      return ok ? '✔ 可以' : '✘ 不可';
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
        actionList.innerHTML = '<div class="empty">当前暂无高优先级动作。系统会继续监控关键标的，一旦出现可执行买入、减仓或卖出机会，会优先显示在这里。</div>';
        return;
      }
      actionList.innerHTML = actions.map(item => (
        '<div class="action-card">' +
        '<div class="action-top">' +
        '<div><div class="action-title">' + item.symbol + ' ' + (item.name || '') + '</div><div class="subvalue">' + item.category_label + '</div></div>' +
        '<div class="badge ' + cardBadgeClass(item.category_color) + '">' + actionCn(item.display_action || item.action) + '</div>' +
        '</div>' +
        '<div class="action-meta">' +
        (item.position_pct ? '<span>仓位 ' + fmtPct(item.position_pct) + '</span>' : '') +
        (item.reduce_pct ? '<span>减仓 ' + fmtPct(item.reduce_pct) + '</span>' : '') +
        (item.planned_qty ? '<span>计划数量 ' + item.planned_qty + ' 股</span>' : '') +
        (item.phase ? '<span>阶段 ' + item.phase + '</span>' : '') +
        '</div>' +
        '<div class="action-reason">' + (item.reason || '暂无说明') + '</div>' +
        '</div>'
      )).join('');
    }

    function renderCoreSymbol(core){
      if(!core || !core.symbol){
        coreSymbolCard.innerHTML = '<div class="empty">当前还没有明确的核心标的，系统会在持仓、最高 execution_score 或最近动作股票中自动选择。</div>';
        return;
      }
      coreSymbolCard.innerHTML =
        '<div class="core-symbol-card">' +
          '<div class="core-symbol-main">' +
            '<div class="core-symbol-title">' + core.symbol + ' ' + (core.name || '') + '</div>' +
            '<div class="subvalue">当前价格 ' + fmtNum(core.latest_price || 0) + ' ｜ 涨跌幅 ' + fmtPct(core.pct_change || 0) + '</div>' +
            '<div class="core-score-strip">' +
              '<span class="core-score-pill">AI 动作：' + actionCn(core.action || 'HOLD') + '</span>' +
              '<span class="core-score-pill">setup ' + Number(core.setup_score || 0).toFixed(2) + '</span>' +
              '<span class="core-score-pill">execution ' + Number(core.execution_score || 0).toFixed(2) + '</span>' +
            '</div>' +
            '<div class="core-symbol-reason">' + (core.reason || '当前仍在等待更明确的盘中动作信号。') + '</div>' +
          '</div>' +
          '<div class="kv">' +
            '<div class="item"><div class="label">是否持仓</div><div class="value">' + (core.has_position ? '是' : '否') + '</div>' + (core.has_position ? '<div class="subvalue">数量 ' + (core.position_qty || 0) + ' 股</div>' : '') + '</div>' +
            '<div class="item"><div class="label">AI 置信度</div><div class="value">' + fmtPct(core.confidence || 0) + '</div></div>' +
          '</div>' +
        '</div>';
    }

    function renderWatchlist(watchlist, sections){
      const entries = (watchlist && watchlist.entries) || [];
      const holdings = (watchlist && watchlist.holdings) || [];
      const evolution = (watchlist && watchlist.evolution) || {};
      const events = (watchlist && watchlist.events) || [];
      const chartEntriesMap = new Map();
      entries.forEach(item => {
        if(item && item.symbol){
          chartEntriesMap.set(item.symbol, item);
        }
      });
      holdings.forEach(item => {
        if(item && item.symbol && !chartEntriesMap.has(item.symbol)){
          chartEntriesMap.set(item.symbol, {
            symbol: item.symbol,
            name: item.name || item.symbol,
            latest_price: item.last_price || 0,
            pct_change: 0,
            action: 'HOLD',
            setup_score: 0,
            execution_score: 0,
            has_position: true,
            position_qty: item.qty || 0,
          });
        }
      });
      const chartEntries = Array.from(chartEntriesMap.values());
      watchlistMeta.innerHTML = [
        '<span class="state-tag">来源：' + (watchlist && watchlist.source || '-') + '</span>',
        '<span class="state-tag">生成时间：' + (watchlist && watchlist.generated_at || '暂无') + '</span>',
        '<span class="state-tag">有效期至：' + (watchlist && watchlist.valid_until || '暂无') + '</span>',
        '<span class="state-tag">交易日：' + (watchlist && watchlist.trading_day || '暂无') + '</span>',
        '<span class="state-tag">最近扫描：' + (watchlist && watchlist.last_scan_at || '暂无') + '</span>',
        '<span class="state-tag">本次新增：' + (((evolution.added || []).length) || 0) + '</span>',
        '<span class="state-tag">本次移除：' + (((evolution.removed || []).length) || 0) + '</span>'
      ].join('');
      if(events.length){
        watchlistEvents.style.display = 'block';
        watchlistEvents.innerHTML = '<strong style="display:block;margin-bottom:8px">监控池刚刚发生了什么</strong>' + events.map(item => (
          '<div style="margin-top:6px">' +
          String(item.ts || '').slice(11,16) + ' ' +
          ((item.action || '') === 'ADD' ? '新增 ' : '移除 ') +
          item.symbol + '：' + (item.reason || '监控池已更新') +
          '</div>'
        )).join('');
      }else{
        watchlistEvents.style.display = 'none';
        watchlistEvents.innerHTML = '';
      }
      if(!entries.length){
        watchlistSections.innerHTML = '<div class="empty">当前监控池为空；一键启动时会优先尝试自动选股并补齐监控池。</div>';
      }else{
        watchlistSections.innerHTML = (sections || []).map(section => (
          '<div class="watch-section">' +
            '<div class="watch-section-head">' +
              '<div><div class="watch-section-title">' + section.title + '</div><div class="watch-section-desc">' + section.description + '</div></div>' +
            '</div>' +
            '<div class="watchlist-grid">' +
              (section.items || []).map(item => (
                '<div class="watch-item">' +
                  '<div class="watch-item-top">' +
                    '<div><h4>' + item.symbol + ' ' + (item.name || '') + '</h4><div class="subvalue">最新价 ' + fmtNum(item.latest_price) + ' ｜ 涨跌幅 ' + fmtPct(item.pct_change) + '</div></div>' +
                    '<div class="badge ' + cardBadgeClass(item.action === 'BUY' ? 'success' : (item.action === 'SELL' || item.action === 'REDUCE' ? 'warning' : (item.action && item.action.indexOf('WATCH') === 0 ? 'muted' : 'neutral'))) + '">' + actionCn(item.action || 'HOLD') + '</div>' +
                  '</div>' +
                  '<div class="meta"><span>setup ' + Number(item.setup_score || 0).toFixed(2) + '</span><span>execution ' + Number(item.execution_score || 0).toFixed(2) + '</span>' + (item.has_position ? '<span>持仓 ' + item.position_qty + ' 股</span>' : '<span>当前未持仓</span>') + '</div>' +
                '</div>'
              )).join('') +
            '</div>' +
          '</div>'
        )).join('');
      }
      if(!holdings.length){
        holdingsPool.innerHTML = '<div class="empty">当前没有持仓。若实时引擎触发 BUY，持仓池会在这里显示。</div>';
      }else{
        holdingsPool.innerHTML = holdings.map(item => (
          '<div class="action-card">' +
          '<div class="action-top"><div class="action-title">' + item.symbol + ' ' + (item.name || '') + '</div><div class="badge badge-warning">持仓</div></div>' +
          '<div class="action-meta"><span>数量 ' + item.qty + '</span><span>最新价 ' + fmtNum(item.last_price) + '</span><span>市值 ' + fmtNum(item.market_value) + '</span></div>' +
          '<div class="action-reason">浮盈亏 ' + fmtNum(item.unrealized_pnl) + ' ｜ 可卖 ' + item.can_sell_qty + ' 股</div>' +
          '</div>'
        )).join('');
      }
      const options = chartEntries.map(item => '<option value="' + item.symbol + '">' + item.symbol + ' ' + (item.name || '') + '</option>');
      chartSymbolSelect.innerHTML = options.join('');
      const chartSymbol = activeChartSymbol || ((latestHomePayload || {}).charts || {}).selected_symbol || (chartEntries[0] && chartEntries[0].symbol) || '';
      const focusEntry = chartEntries.find(item => item.symbol === chartSymbol) || chartEntries[0] || null;
      if(focusEntry){
        chartFocusTitle.textContent = focusEntry.symbol + ' ' + (focusEntry.name || '');
        chartFocusSub.textContent = '最新价 ' + fmtNum(focusEntry.latest_price || 0) + ' ｜ 涨跌幅 ' + fmtPct(focusEntry.pct_change || 0) + ' ｜ AI 动作 ' + (focusEntry.action || 'HOLD') + ' ｜ setup ' + Number(focusEntry.setup_score || 0).toFixed(2) + ' ｜ execution ' + Number(focusEntry.execution_score || 0).toFixed(2);
        activeChartSymbol = focusEntry.symbol;
      }else{
        chartFocusTitle.textContent = '当前暂无图表观察标的';
        chartFocusSub.textContent = '系统会优先展示当前持仓标的、execution_score 最高标的或最近有动作的标的。';
        activeChartSymbol = '';
      }
    }

    function renderTradeExplanations(payload){
      const buys = (payload && payload.recent_buys) || [];
      const sells = (payload && payload.recent_sells) || [];
      const holds = (payload && payload.hold_reasons) || [];

      if(!buys.length){
        buyExplainList.innerHTML = '<div class="empty">今天还没有新的真实买入成交。后续一旦出现新开仓，这里会直接解释为什么买。</div>';
      }else{
        buyExplainList.innerHTML = buys.map(item => (
          '<div class="action-card">' +
          '<div class="action-top"><div class="action-title">' + item.symbol + ' ' + (item.name || '') + '</div><div class="badge badge-success">买入</div></div>' +
          '<div class="action-meta"><span>' + String(item.ts || '').slice(11,16) + '</span><span>价格 ' + fmtNum(item.price || 0) + '</span><span>数量 ' + (item.qty || 0) + ' 股</span></div>' +
          '<div class="action-reason">' + (item.reason || '满足多因子和风险条件，触发模拟买入。') + '</div>' +
          '</div>'
        )).join('');
      }

      if(sells.length){
        sellExplainList.innerHTML = sells.map(item => (
          '<div class="action-card">' +
          '<div class="action-top"><div class="action-title">' + item.symbol + ' ' + (item.name || '') + '</div><div class="badge badge-warning">' + actionCn(item.action || 'SELL') + '</div></div>' +
          '<div class="action-meta"><span>' + String(item.ts || '').slice(11,16) + '</span><span>价格 ' + fmtNum(item.price || 0) + '</span><span>数量 ' + (item.qty || 0) + ' 股</span></div>' +
          '<div class="action-reason">' + (item.reason || '满足退出条件，触发模拟卖出。') + '</div>' +
          '</div>'
        )).join('');
        return;
      }

      if(holds.length){
        sellExplainList.innerHTML = holds.map(item => (
          '<div class="action-card">' +
          '<div class="action-top"><div class="action-title">' + item.symbol + ' ' + (item.name || '') + '</div><div class="badge badge-neutral">继续持有</div></div>' +
          '<div class="action-meta"><span>setup ' + Number(item.setup_score || 0).toFixed(2) + '</span><span>execution ' + Number(item.execution_score || 0).toFixed(2) + '</span></div>' +
          '<div class="action-reason">' + (item.reason || '当前持仓仍与市场状态匹配，暂不减仓或卖出。') + '</div>' +
          '</div>'
        )).join('');
      }else{
        sellExplainList.innerHTML = '<div class="empty">今天还没有卖出或减仓成交，当前也没有明确的卖出解释。</div>';
      }
    }

    function chartLayout(){
      return {width:720, height:280, left:64, right:16, top:16, bottom:34};
    }

    function buildPolyline(points, minValue, maxValue, valueKey){
      if(!points || !points.length){
        return '';
      }
      const {width, height, left, right, top, bottom} = chartLayout();
      const span = Math.max(1e-6, maxValue - minValue);
      return points.map((item, index) => {
        const x = left + ((width - left - right) * index / Math.max(1, points.length - 1));
        const y = height - bottom - ((Number(item[valueKey] || 0) - minValue) / span) * (height - top - bottom);
        return x.toFixed(1) + ',' + y.toFixed(1);
      }).join(' ');
    }

    function buildAxisMarkup(minValue, maxValue, labels){
      const {width, height, left, right, top, bottom} = chartLayout();
      const midValue = (minValue + maxValue) / 2;
      const yRows = [
        {y: top, value: maxValue},
        {y: (top + height - bottom) / 2, value: midValue},
        {y: height - bottom, value: minValue}
      ];
      const xRows = labels.map((label, index) => {
        const x = index === 0 ? left : index === labels.length - 1 ? width - right : (left + width - right) / 2;
        const anchor = index === 0 ? 'start' : index === labels.length - 1 ? 'end' : 'middle';
        return '<text x="' + x + '" y="' + (height - 10) + '" text-anchor="' + anchor + '" class="axis-text">' + label + '</text>';
      }).join('');
      const yMarkup = yRows.map(item => (
        '<line x1="' + left + '" y1="' + item.y + '" x2="' + (width - right) + '" y2="' + item.y + '" class="grid-line"></line>' +
        '<text x="' + (left - 10) + '" y="' + (item.y + 4) + '" text-anchor="end" class="axis-text">' + fmtNum(item.value) + '</text>'
      )).join('');
      return (
        '<line x1="' + left + '" y1="' + top + '" x2="' + left + '" y2="' + (height - bottom) + '" class="axis-line"></line>' +
        '<line x1="' + left + '" y1="' + (height - bottom) + '" x2="' + (width - right) + '" y2="' + (height - bottom) + '" class="axis-line"></line>' +
        yMarkup +
        xRows
      );
    }

    function nearestPointIndex(points, targetLabel){
      if(!targetLabel){
        return 0;
      }
      const targetTs = Date.parse(targetLabel);
      if(Number.isNaN(targetTs)){
        return 0;
      }
      let bestIndex = 0;
      let bestDiff = Number.MAX_SAFE_INTEGER;
      points.forEach((item, index) => {
        const raw = item.label || item.ts || item.date || '';
        const ts = Date.parse(raw);
        if(Number.isNaN(ts)){
          return;
        }
        const diff = Math.abs(ts - targetTs);
        if(diff < bestDiff){
          bestDiff = diff;
          bestIndex = index;
        }
      });
      return bestIndex;
    }

    function buildActionMarkers(points, minValue, maxValue, valueKey, actions){
      if(!actions || !actions.length){
        return '';
      }
      const {width, height, left, right, top, bottom} = chartLayout();
      const span = Math.max(1e-6, maxValue - minValue);
      return actions.map(item => {
        const idx = Math.max(0, Math.min(points.length - 1, Number(item.index || 0)));
        const point = points[idx] || points[0];
        const x = left + ((width - left - right) * idx / Math.max(1, points.length - 1));
        const y = height - bottom - ((Number(point[valueKey] || 0) - minValue) / span) * (height - top - bottom);
        const action = String(item.action || '').toUpperCase();
        const klass = action === 'BUY' ? 'chart-point-buy' : action === 'SELL' ? 'chart-point-sell' : action === 'REDUCE' ? 'chart-point-reduce' : 'chart-point-hold';
        return '<circle cx="' + x.toFixed(1) + '" cy="' + y.toFixed(1) + '" r="4.5" class="' + klass + '"></circle>';
      }).join('');
    }

    function renderIntradayChart(payload){
      const points = (payload && payload.points) || [];
      if(!points.length){
        intradayPanel.innerHTML = '<div class="empty">当前还没有可用的分时数据。实时引擎启动并积累几轮行情后，这里会显示盘中走势。</div>';
        return;
      }
      const prices = points.map(item => Number(item.price || 0));
      const minValue = Math.min.apply(null, prices);
      const maxValue = Math.max.apply(null, prices);
      const polyline = buildPolyline(points, minValue, maxValue, 'price');
      const labels = [
        String((points[0] || {}).label || (points[0] || {}).ts || '').slice(11, 16) || '开盘',
        String((points[Math.floor(points.length / 2)] || {}).label || (points[Math.floor(points.length / 2)] || {}).ts || '').slice(11, 16) || '中段',
        String((points[points.length - 1] || {}).label || (points[points.length - 1] || {}).ts || '').slice(11, 16) || '最新'
      ];
      const markers = buildActionMarkers(
        points,
        minValue,
        maxValue,
        'price',
        ((payload && payload.actions) || []).map(item => ({
          index: nearestPointIndex(points, item.ts || item.label || ''),
          action: item.action || ''
        }))
      );
      intradayPanel.innerHTML = '<div class="chart-box">' +
        '<svg viewBox="0 0 720 280" class="chart-svg">' +
        buildAxisMarkup(minValue, maxValue, labels) +
        '<polyline fill="none" stroke="#60a5fa" stroke-width="3" points="' + polyline + '"></polyline>' +
        markers +
        '</svg>' +
        '<div class="legend"><span><i class="dot dot-buy"></i>最新分时价</span><span>点数 ' + points.length + '</span><span>区间 ' + fmtNum(minValue) + ' - ' + fmtNum(maxValue) + '</span></div>' +
        '<div class="chart-note">横轴为盘中时间，纵轴为价格。动作点会按最近意图/成交时间叠加在分时图上。</div>' +
        '</div>';
    }

    function renderKlineChart(payload){
      const rows = (payload && payload.rows) || [];
      if(!rows.length){
        klinePanel.innerHTML = '<div class="empty">当前还没有可用的 K 线缓存。实时引擎加载历史日线后，这里会自动显示最近区间。</div>';
        return;
      }
      const prices = rows.map(item => Number(item.close || 0));
      const minValue = Math.min.apply(null, prices);
      const maxValue = Math.max.apply(null, prices);
      const polyline = buildPolyline(rows, minValue, maxValue, 'close');
      const labels = [
        String((rows[0] || {}).date || '').slice(5) || '起点',
        String((rows[Math.floor(rows.length / 2)] || {}).date || '').slice(5) || '中段',
        String((rows[rows.length - 1] || {}).date || '').slice(5) || '最近'
      ];
      const {width, height, left, right, top, bottom} = chartLayout();
      const span = Math.max(1e-6, maxValue - minValue);
      const candles = rows.map((item, index) => {
        const x = left + ((width - left - right) * index / Math.max(1, rows.length - 1));
        const open = Number(item.open || item.close || 0);
        const close = Number(item.close || open);
        const high = Number(item.high || Math.max(open, close));
        const low = Number(item.low || Math.min(open, close));
        const yOpen = height - bottom - ((open - minValue) / span) * (height - top - bottom);
        const yClose = height - bottom - ((close - minValue) / span) * (height - top - bottom);
        const yHigh = height - bottom - ((high - minValue) / span) * (height - top - bottom);
        const yLow = height - bottom - ((low - minValue) / span) * (height - top - bottom);
        const bodyTop = Math.min(yOpen, yClose);
        const bodyHeight = Math.max(2, Math.abs(yOpen - yClose));
        const fill = close >= open ? '#22c55e' : '#ef4444';
        return '<line x1="' + x.toFixed(1) + '" y1="' + yHigh.toFixed(1) + '" x2="' + x.toFixed(1) + '" y2="' + yLow.toFixed(1) + '" stroke="' + fill + '" stroke-width="1.5"></line>' +
          '<rect x="' + (x - 4).toFixed(1) + '" y="' + bodyTop.toFixed(1) + '" width="8" height="' + bodyHeight.toFixed(1) + '" fill="' + fill + '" rx="1"></rect>';
      }).join('');
      const markers = buildActionMarkers(
        rows,
        minValue,
        maxValue,
        'close',
        ((payload && payload.actions) || []).map(item => ({
          index: nearestPointIndex(rows, item.ts || item.date || ''),
          action: item.action || ''
        }))
      );
      klinePanel.innerHTML = '<div class="chart-box">' +
        '<svg viewBox="0 0 720 280" class="chart-svg">' +
        buildAxisMarkup(minValue, maxValue, labels) +
        candles +
        '<polyline fill="none" stroke="#93c5fd" stroke-width="2" points="' + polyline + '"></polyline>' +
        markers +
        '</svg>' +
        '<div class="legend"><span><i class="dot dot-hold"></i>收盘线</span><span>K 线数量 ' + rows.length + '</span><span><i class="dot dot-buy"></i>动作点</span></div>' +
        '<div class="chart-note">横轴为日期，纵轴为价格；最近动作会同步叠加到价格走势上，便于对照入场和持仓管理时点。</div>' +
        '</div>';
    }

    function renderEquityCurve(payload){
      const points = (payload && payload.points) || [];
      if(!points.length){
        equityCurvePanel.innerHTML = '<div class="empty">当前没有账户曲线数据。实时引擎写入 account_snapshots 后，这里会显示总资产变化。</div>';
        return;
      }
      const equities = points.map(item => Number(item.equity || 0));
      const minValue = Math.min.apply(null, equities);
      const maxValue = Math.max.apply(null, equities);
      const polyline = buildPolyline(points, minValue, maxValue, 'equity');
      const labels = [
        String((points[0] || {}).ts || '').slice(11, 16) || '开始',
        String((points[Math.floor(points.length / 2)] || {}).ts || '').slice(11, 16) || '中段',
        String((points[points.length - 1] || {}).ts || '').slice(11, 16) || '最新'
      ];
      equityCurvePanel.innerHTML = '<div class="chart-box">' +
        '<svg viewBox="0 0 720 280" class="chart-svg">' +
        buildAxisMarkup(minValue, maxValue, labels) +
        '<polyline fill="none" stroke="#f59e0b" stroke-width="3" points="' + polyline + '"></polyline>' +
        '</svg>' +
        '<div class="legend"><span><i class="dot dot-reduce"></i>总资产</span><span>最新 ' + fmtNum(equities[equities.length - 1]) + '</span><span>区间 ' + fmtNum(minValue) + ' - ' + fmtNum(maxValue) + '</span></div>' +
        '<div class="chart-note">横轴为账户快照时间，纵轴为总资产变化。现在已经能直接看到账户波动，不需要只盯数字卡片。</div>' +
        '</div>';
    }

    function renderTimeline(items){
      if(!items || !items.length){
        actionTimelinePanel.innerHTML = '<div class="empty">当前还没有动作时间线。引擎记录意图、成交或被拦截动作后，会在这里逐条显示。</div>';
        return;
      }
      const statusLabelMap = {intent:'意图', filled:'已成交', rejected:'被拦截'};
      actionTimelinePanel.innerHTML = '<div class="timeline-list">' + items.map(item => (
        '<div class="timeline-item">' +
        '<div>' + String(item.ts || '').slice(11, 16) + '</div>' +
        '<div>' + item.symbol + ' ' + ((item.name && item.name !== item.symbol) ? item.name : '') + '</div>' +
        '<div class="timeline-status-' + (item.status || 'intent') + '">' + actionCn(item.action || '-') + ' ' + (statusLabelMap[item.status || 'intent'] || '状态未知') + '</div>' +
        '<div>' + (item.reason || '暂无说明') + '</div>' +
        '</div>'
      )).join('') + '</div>';
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

    function renderOpportunityCandidates(items){
      if(!items || !items.length){
        opportunityCandidates.innerHTML = '<div class="empty">当前没有接近执行阈值的股票。后续一旦有股票接近建仓线，这里会优先提示。</div>';
        return;
      }
      opportunityCandidates.innerHTML = items.map(item => (
        '<div class="opportunity-item">' +
          '<div>' +
            '<div class="action-title">' + item.symbol + ' ' + (item.name || '') + '</div>' +
            '<div class="muted-note">当前动作 ' + actionCn(item.action || 'HOLD') + ' ｜ execution ' + Number(item.execution_score || 0).toFixed(2) + '</div>' +
          '</div>' +
          '<div class="badge badge-warning">还差 ' + Number(item.gap_to_buy || 0).toFixed(2) + '</div>' +
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
        const strategyStatus = data.strategy_status || {};
        const coreSymbol = data.core_symbol || {};
        const opportunityData = data.opportunities || {};
        heroAdviceMain.textContent = data.summary || '当前暂无明确结论';
        heroAdviceExplain.textContent = (coreSymbol.reason || (opportunityData.top_limitations || [])[0] || '系统会在满足交易阶段、执行权限和风险约束时自动放大可执行机会。');
        heroMarketState.textContent = (strategyStatus.strategy_style || '') + ' / ' + riskModeCn(strategyStatus.risk_mode || 'NORMAL');
        heroActionAdvice.textContent = actionCn((coreSymbol.action || (((data.actions || [])[0] || {}).action) || 'HOLD'));
        heroTradeReady.textContent = execution.can_execute_fill ? '✔ 当前可成交' : '✘ 当前不可成交';
        statusTags.innerHTML = [
          '<span class="state-tag">交易日：' + ((phase.is_trading_day ? '是' : '否')) + '</span>',
          '<span class="state-tag">阶段：' + (phase.phase_label || phase.phase || '-') + '</span>',
          '<span class="state-tag">允许成交：' + (execution.can_execute_fill ? 'YES' : 'NO') + '</span>',
          '<span class="state-tag">允许开仓：' + (execution.can_open_position ? 'YES' : 'NO') + '</span>',
          '<span class="state-tag">风险模式：' + riskModeCn(strategyStatus.risk_mode || 'NORMAL') + '</span>'
        ].join('');

        renderStatGrid(phaseGrid, [
          {label:'交易日', value: phase.is_trading_day ? '是' : '否'},
          {label:'当前阶段', value: phase.phase_label || phase.phase || '-'},
          {label:'允许开仓', value: execution.can_open_position ? '✔ 可开仓' : '✘ 不可开仓'},
          {label:'允许成交', value: execution.can_execute_fill ? '✔ 可成交' : '✘ 不可成交'}
        ]);

        renderStatGrid(strategyGrid, [
          {label:'风险模式', value: riskModeCn(strategyStatus.risk_mode || '-')},
          {label:'策略风格', value: strategyStatus.strategy_style || '-'},
          {label:'仓位策略', value: strategyStatus.position_strategy || '-'},
          {label:'AI 状态', value: strategyStatus.ai_status || '-'}
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
          {label:'动作意图', value: String(stats.intent_count || 0)},
          {label:'真实成交', value: String(stats.executed_count || 0)},
          {label:'被拦截', value: String(stats.blocked_count || 0)}
        ]);
        renderStatGrid(opportunityGrid, [
          {label:'可建仓机会', value: String(opportunityData.buy_count || 0), subvalue: (opportunityData.top_limitations || [])[0] || '当前暂无高优先级建仓机会'},
          {label:'可减仓机会', value: String(opportunityData.reduce_count || 0), subvalue: (opportunityData.top_limitations || [])[1] || '当前暂无高优先级减仓机会'}
        ]);

        renderCoreSymbol(coreSymbol);
        renderActions(data.actions || []);
        renderNoBuyReasons(data.no_buy_reasons || []);
        renderScoreBreakdowns(data.score_breakdowns || []);
        renderOpportunityCandidates(opportunityData.top_candidates || []);
        renderWatchlist(data.watchlist || {}, data.watchlist_sections || []);
        renderTimeline(data.timeline || []);
        renderTradeExplanations(data.trade_explanations || {});
        latestHomePayload = data;
        const entries = ((data.watchlist || {}).entries) || [];
        const holdings = ((data.watchlist || {}).holdings) || [];
        const availableSymbols = Array.from(new Set(entries.map(item => item.symbol).concat(holdings.map(item => item.symbol))));
        const selectedSymbol = activeChartSymbol && availableSymbols.includes(activeChartSymbol)
          ? activeChartSymbol
          : ((data.charts || {}).selected_symbol || availableSymbols[0] || '');
        if(selectedSymbol && chartSymbolSelect.value !== selectedSymbol){
          chartSymbolSelect.value = selectedSymbol;
        }
        if(selectedSymbol){
          await loadChart(selectedSymbol);
        }else{
          renderIntradayChart((data.charts || {}).intraday || {});
          renderKlineChart((data.charts || {}).kline || {});
          renderEquityCurve((data.charts || {}).equity || {});
        }
        const selectedEntry = entries.find(item => item.symbol === selectedSymbol) || entries[0] || null;
        if(selectedEntry){
          chartFocusTitle.textContent = selectedEntry.symbol + ' ' + (selectedEntry.name || '');
          chartFocusSub.textContent = '最新价 ' + fmtNum(selectedEntry.latest_price || 0) + ' ｜ 涨跌幅 ' + fmtPct(selectedEntry.pct_change || 0) + ' ｜ AI 动作 ' + (selectedEntry.action || 'HOLD') + ' ｜ setup ' + Number(selectedEntry.setup_score || 0).toFixed(2) + ' ｜ execution ' + Number(selectedEntry.execution_score || 0).toFixed(2);
        }
      }catch(err){
        summaryText.textContent = '首页加载失败';
        systemStatus.innerHTML = '<span class="status-pill status-error">运行异常</span>';
        systemError.style.display = 'block';
        systemError.textContent = String(err);
      }
    }

    async function loadChart(symbol){
      if(!symbol){
        return;
      }
      activeChartSymbol = symbol;
      try{
        const resp = await fetch('/api/ui/chart?symbol=' + encodeURIComponent(symbol) + '&ts=' + Date.now(), {cache:'no-store'});
        const data = await resp.json();
        if(!resp.ok){
          throw new Error(data.detail || '读取图表失败');
        }
        renderIntradayChart(data.intraday || {});
        renderKlineChart(data.kline || {});
        renderEquityCurve(data.equity || {});
      }catch(err){
        intradayPanel.innerHTML = '<div class="empty">分时图加载失败：' + String(err) + '</div>';
      }
    }

    async function runHomeQuickStart(){
      homeStartAll.disabled = true;
      homeStartStatus.textContent = '正在准备监控池并启动实时 AI 决策...';
      try{
        const watchlist = (latestHomePayload && latestHomePayload.watchlist) || {};
        const shouldRunSelector = !watchlist.entries || !watchlist.entries.length || watchlist.stale || watchlist.source === 'default_fallback';
        if(shouldRunSelector){
          homeStartStatus.textContent = '当前监控池缺失或已过期，先自动选股并刷新 watchlist...';
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
          const pipeline = await fetchJsonSafe('/api/auto-pipeline', {
            method:'POST',
            headers:{'Content-Type':'application/json'},
            body: JSON.stringify(payload)
          });
          if(pipeline.resp.ok){
            await pollTask(pipeline.data.task_id, '自动选股已完成，正在同步监控池并启动实时引擎...');
          }else{
            homeStartStatus.textContent = '自动选股失败，将回退最近候选池或默认观察池继续启动：' + formatErrorDetail(pipeline.data.detail);
          }
        }

        const result = await fetchJsonSafe('/api/ai-stock-sim/start-all', {method:'POST'});
        if(!result.resp.ok){
          throw new Error(formatErrorDetail(result.data.detail));
        }
        homeStartStatus.textContent = '实时 AI 决策中心已启动，监控池来源：' + (((result.data || {}).watchlist || {}).source || '未知') + '。';
        await loadHome();
      }catch(err){
        homeStartStatus.textContent = '一键启动失败：' + String(err);
      }finally{
        homeStartAll.disabled = false;
      }
    }

    async function pollTask(taskId, successMessage){
      let done = false;
      homeTaskLog.style.display = 'block';
      while(!done){
        const result = await fetchJsonSafe('/api/task/' + taskId + '?ts=' + Date.now(), {cache:'no-store'});
        const resp = result.resp;
        const data = result.data || {};
        if(!resp.ok && !data.status){
          homeStartStatus.textContent = '任务状态读取失败：' + formatErrorDetail(data.detail);
          if(data.detail){
            homeTaskLog.textContent = String(data.detail);
          }
          break;
        }
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

    bindProvider.addEventListener('change', saveBindingConfig);
    bindModel.addEventListener('change', saveBindingConfig);
    bindBaseUrl.addEventListener('change', saveBindingConfig);
    bindApiKey.addEventListener('change', saveBindingConfig);
    saveBinding.addEventListener('click', saveBindingConfig);
    homeStartAll.addEventListener('click', runHomeQuickStart);
    chartSymbolSelect.addEventListener('change', (event) => {
      const symbol = event.target.value;
      activeChartSymbol = symbol;
      const entries = ((((latestHomePayload || {}).watchlist) || {}).entries) || [];
      const holdings = ((((latestHomePayload || {}).watchlist) || {}).holdings) || [];
      const selectedEntry = entries.find(item => item.symbol === symbol) || holdings.find(item => item.symbol === symbol);
      if(selectedEntry){
        chartFocusTitle.textContent = selectedEntry.symbol + ' ' + (selectedEntry.name || '');
        const latestPrice = selectedEntry.latest_price || selectedEntry.last_price || 0;
        chartFocusSub.textContent = '最新价 ' + fmtNum(latestPrice) + ' ｜ 涨跌幅 ' + fmtPct(selectedEntry.pct_change || 0) + ' ｜ AI 动作 ' + (selectedEntry.action || 'HOLD') + ' ｜ setup ' + Number(selectedEntry.setup_score || 0).toFixed(2) + ' ｜ execution ' + Number(selectedEntry.execution_score || 0).toFixed(2);
      }
      loadChart(symbol);
    });

    loadBindingConfig();
    loadHome();
    setInterval(loadHome, 5000);
  </script>
</body>
</html>""".replace("__WEB_BUILD_TAG__", build_tag).replace("__HERO_PANEL__", hero_panel).replace("__KLINE_PANEL__", kline_panel).replace("__EQUITY_PANEL__", equity_curve_panel).replace("__TIMELINE_PANEL__", action_timeline_panel)
