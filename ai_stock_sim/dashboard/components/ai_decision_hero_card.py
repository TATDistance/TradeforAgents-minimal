from __future__ import annotations


def render_ai_decision_hero_card() -> str:
    return """
      <div class="hero ai-hero-card">
        <div class="hero-main">
          <div class="hero-kicker">AI 实时交易前台</div>
          <h2 id="summaryText">正在读取当前 AI 决策摘要…</h2>
          <p id="summarySub">打开首页就能先回答三件事：现在能不能交易、AI 在干什么、当前最重要的机会是谁。</p>
          <div class="summary">
            <strong>系统状态</strong>
            <div id="systemStatus"></div>
            <div class="hero-actions">
              <button id="homeStartAll" type="button" class="small-btn">一键启动 AI 实时决策（会自动补监控池）</button>
              <a href="/debug" class="small-btn" style="text-decoration:none">打开高级调试面板</a>
            </div>
            <div id="homeStartStatus" class="setting-status" style="margin-top:12px">首页不会自动启动引擎；如需开始实时模拟，直接点“ 一键启动 AI 实时决策（会自动补监控池） ”即可。</div>
            <div id="homeTaskLog" class="log-box" style="display:none"></div>
            <div id="systemHint" class="hint-box" style="display:none"></div>
            <div id="systemError" class="error-box" style="display:none"></div>
          </div>
        </div>
        <div class="status-box hero-side">
          <div class="hero-side-title">当前运行总览</div>
          <div class="state-row" id="statusTags"></div>
          <div class="footer-note" id="lastUpdated">最近更新时间：-</div>
        </div>
      </div>
    """
