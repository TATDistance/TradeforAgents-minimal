# 第十五阶段任务书（Codex 执行版）

## 主题：主线识别 + 龙头过滤 + 结构化买点系统

---

## 0. 总目标

将当前系统从：

```text
规则策略 + AI终审 + 风控
```

升级为：

```text
主线识别
→ 龙头过滤
→ 弱票淘汰
→ 结构化买点判断
→ 结构化卖点判断
→ AI终审
→ 风控
→ 执行
→ 收益归因
→ 参数与权重反馈
```

本阶段重点不是新增“更多策略”，而是提高三件事：

1. 选股质量
2. 买点质量
3. 卖点质量

并且把这些改进纳入已有学习层，让系统在后续交易日持续修正。

---

## 1. 本阶段要解决的核心问题

### 问题 A：候选池质量不够高

当前问题：

- 主线/非主线混在一起
- 龙头/跟风混在一起
- 弱趋势票、低质量票会混入候选池
- 高波动但无持续性的票会误入 watchlist

结果：

- 后面的 AI 终审和风控只能“少犯错”
- 不能从源头提高收益质量

### 问题 B：买点不够结构化

当前问题：

- 有时买在冲高后
- 有时买在高波动噪音中
- “观察票”和“可执行票”边界不够清晰
- 没有明确区分“试仓点”和“加仓点”

### 问题 C：卖点不够结构化

当前问题：

- 减仓和清仓区分不够清楚
- 卖点容易过早或过晚
- 对“结构坏了”和“正常回撤”区分不够
- 盈利单的持有逻辑不够聪明

### 问题 D：这些改进还没有稳定反哺学习层

目前学习层已经能做：

- 策略评估
- 调权
- 风格切换
- AI 终审反馈

但还没把：

- 主线识别效果
- 龙头过滤效果
- 买点/卖点结构化效果

纳入反馈回路。

---

## 2. 强约束

### 2.1 禁止事项

- 禁止直接删除现有规则策略
- 禁止让 LLM 全量实时接管选股
- 禁止用纯自然语言替代结构化过滤
- 禁止把所有过滤逻辑硬编码进单一大函数
- 禁止买点和卖点只用单一涨跌幅阈值判断
- 禁止候选池只靠“当前分数高”而不考虑市场主线与成交质量
- 禁止对已有学习层做破坏式重构
- 禁止引入会阻塞 `event_driven_mode` 主链的同步高频 LLM 调用
- 禁止破坏双账户并行运行能力：`paper_main` 与 `paper_small_1w`

### 2.2 必须坚持

- 规则策略仍然是快速、低成本骨架
- AI 负责更高层的筛选、修正和反馈总结
- 所有新增过滤和结构判断必须可解释
- 所有新指标都必须进入评估层
- 必须区分：
  - 观察价值
  - 执行价值
  - 结构性买点
  - 结构性卖点
- 必须复用现有主链：
  - `intraday_selector_service.py`
  - `watchlist_evolution_service.py`
  - `decision_context_builder.py`
  - `ai_decision_engine.py`
  - `realtime_ai_review_service.py`
  - `adaptive_weight_service.py`

---

## 3. 新增与修改文件

### 3.1 新增文件

```text
ai_stock_sim/app/theme_detection_service.py
ai_stock_sim/app/leader_selection_service.py
ai_stock_sim/app/candidate_quality_service.py
ai_stock_sim/app/entry_structure_service.py
ai_stock_sim/app/exit_structure_service.py
ai_stock_sim/app/trade_timing_feedback_service.py
ai_stock_sim/tests/test_theme_detection_service.py
ai_stock_sim/tests/test_leader_selection_service.py
ai_stock_sim/tests/test_candidate_quality_service.py
ai_stock_sim/tests/test_entry_structure_service.py
ai_stock_sim/tests/test_exit_structure_service.py
ai_stock_sim/tests/test_trade_timing_feedback_service.py
docs/taskbooks/stage-15-mainline-leader-entry-codex.md
```

### 3.2 修改文件

```text
ai_stock_sim/app/intraday_selector_service.py
ai_stock_sim/app/watchlist_evolution_service.py
ai_stock_sim/app/decision_context_builder.py
ai_stock_sim/app/score_service.py
ai_stock_sim/app/ai_decision_engine.py
ai_stock_sim/app/realtime_ai_review_service.py
ai_stock_sim/app/realtime_ai_review_tracking_service.py
ai_stock_sim/app/strategy_evaluation_service.py
ai_stock_sim/app/adaptive_weight_service.py
ai_stock_sim/app/strategy_weight_service.py
ai_stock_sim/app/style_profile_service.py
ai_stock_sim/app/evaluation_service.py
ai_stock_sim/app/report_service.py
ai_stock_sim/app/db.py
ai_stock_sim/app/scheduler.py
ai_stock_sim/dashboard/services/ui_home_service.py
ai_stock_sim/dashboard/pages/ai_trading_home.py
ai_stock_sim/dashboard/dashboard_app.py
ai_stock_sim/config/settings.yaml
README.md
ai_stock_sim/README.md
```

---

## 4. 阶段 15A：主线识别服务

## 目标

新增主线识别服务，让候选池优先来自当前市场主线，而不是全市场平均抽样。

### 新增文件

`ai_stock_sim/app/theme_detection_service.py`

### 必须识别的内容

- 当前强势板块
- 当前弱势板块
- 板块热度变化
- 主线是否集中
- 当前市场是否存在明确主线

### 输入建议

- 板块/行业涨跌幅
- 板块成交额变化
- 板块内强势股数量
- 板块持续性（近 3 日 / 5 日）
- 现有 snapshot、runtime watchlist、opportunity pool、chart cache

### 输出结构

```python
{
    "top_themes": [
        {
            "name": "AI算力",
            "strength": 0.82,
            "breadth": 0.71,
            "persistence": 0.66
        }
    ],
    "market_theme_mode": "concentrated"  # concentrated / mixed / weak
}
```

### 仓库接入要求

- 输出必须进入 `decision_context_builder.py`
- 输出必须能被 `intraday_selector_service.py` 和 `watchlist_evolution_service.py` 消费
- 输出必须能进入 `8610` 调试视图与 `8600` 首页摘要

### 验收标准

- 系统能输出当前主线板块列表
- 候选池生成时能使用主线信息
- 主线信息可显示到 8610

---

## 5. 阶段 15B：龙头过滤服务

## 目标

在候选层增加“龙头优先，跟风降权”的过滤机制。

### 新增文件

`ai_stock_sim/app/leader_selection_service.py`

### 必须实现

对候选股票打标签：

- `leader`
- `strong_follower`
- `weak_follower`
- `non_theme`

### 参考因素

- 所属板块强度
- 个股成交额/换手率排名
- 涨幅排名
- 连续强势程度
- 是否为板块核心辨识度个股
- 在主线主题内的相对强弱与持续性

### 输出结构

```python
{
    "symbol": "300750",
    "theme": "新能源",
    "leader_rank_score": 0.88,
    "role": "leader"
}
```

### 仓库接入要求

- `leader_rank_score` 和 `role` 必须进入候选排序
- `weak_follower` / `non_theme` 必须支持降权或过滤
- 结果必须能进入 `score_service.py`、`decision_context_builder.py`、`realtime_ai_review_service.py`

### 验收标准

- 候选池中优先保留 leader 和 strong_follower
- weak_follower 和 non_theme 默认降权或过滤
- 首页可选展示“核心关注来自主线龙头”

---

## 6. 阶段 15C：候选质量过滤服务

## 目标

新增统一候选质量过滤层，减少“看起来不错但不值得交易”的股票进入 watchlist。

### 新增文件

`ai_stock_sim/app/candidate_quality_service.py`

### 必须过滤的类型

- 弱趋势票
- 低成交质量票
- 高波动但无持续性票
- 与当前市场风格不匹配的票
- 非主线边缘票

### 必须实现的过滤器

#### 1. 弱趋势过滤

例如：

- `trend_slope_20d <= 0`
- `ma20_bias` 过低
- `ret_20d` 过弱

#### 2. 成交质量过滤

例如：

- 成交额太低
- 换手率异常但不可持续
- 量能脉冲后迅速衰减

#### 3. 高波动噪音过滤

例如：

- 波动率高但 trend 不清晰
- RSI / MACD 反复打脸
- 价格位置远离合理介入区

#### 4. 风格不匹配过滤

例如：

- 当前风格为 `trend_following`
- 但个股更像纯反抽型

### 输出结构

```python
{
    "symbol": "002594",
    "quality_score": 0.73,
    "passed": True,
    "filter_reasons": [
        "主线匹配",
        "趋势清晰",
        "成交质量合格"
    ]
}
```

### 仓库接入要求

- `intraday_selector_service.py` 和 `watchlist_evolution_service.py` 必须接这层
- `quality_score` 必须进入 `score_service.py`
- `filter_reasons` 必须能进入 `decision_context_builder.py` 和 `8610`

### 验收标准

- `intraday_selector_service` 和 `watchlist_evolution_service` 都能接这层过滤
- 不合格票不进入高优先级池
- 过滤原因可追踪

---

## 7. 阶段 15D：结构化买点系统

## 目标

让系统区分“观察机会”和“可执行买点”，避免追高和噪音买入。

### 新增文件

`ai_stock_sim/app/entry_structure_service.py`

### 必须实现的买点分类

#### 1. 观察点（watch_point）

说明：

- 值得继续观察
- 还不适合下单

#### 2. 试仓点（probe_entry）

说明：

- 小仓位试探
- 风险仍高，但位置尚可

#### 3. 加仓点（add_entry）

说明：

- 趋势进一步确认
- 可以在已有仓位基础上加仓

#### 4. 禁止追高（chase_block）

说明：

- 当前价格位置不佳
- 即使 execution_score 高，也不允许 BUY

### 必须加入的判断逻辑

#### 不追高

例如：

- 当日涨幅过高
- 距离短期均线过远
- 短时波动异常拉升

#### 回踩确认

例如：

- 上涨后回踩 MA5/MA10/关键支撑
- 回踩不破结构
- 再次放量企稳

#### 分时确认

例如：

- 分时不是尖顶脉冲
- 有持续承接
- 不是单纯情绪拉高

### 输出结构

```python
{
    "symbol": "300750",
    "entry_type": "probe_entry",
    "entry_quality_score": 0.76,
    "allow_buy": True,
    "entry_reason": "回踩确认后再企稳，适合小仓试仓"
}
```

### 仓库接入要求

- BUY 不能只看 `execution_score`
- `entry_type`、`entry_quality_score`、`entry_reason` 必须进入：
  - `score_service.py`
  - `decision_context_builder.py`
  - `ai_decision_engine.py`
  - `realtime_ai_review_service.py`

### 验收标准

- BUY 不能只看 execution_score
- 必须结合 entry_type
- UI 能显示“观察点 / 试仓点 / 加仓点”

---

## 8. 阶段 15E：结构化卖点系统

## 目标

让系统更聪明地区分：

- 正常回撤
- 趋势衰减
- 结构破坏
- 应减仓
- 应清仓

### 新增文件

`ai_stock_sim/app/exit_structure_service.py`

### 必须实现的卖点分类

#### 1. `hold_on_structure`

结构未坏，继续持有

#### 2. `reduce_on_weakening`

趋势减弱，先减仓

#### 3. `sell_on_break`

结构破坏，清仓

#### 4. `take_profit_partial`

盈利单分批兑现

### 必须加入的判断逻辑

#### 结构破坏

例如：

- 跌破关键均线且无回收
- 趋势斜率转负
- MACD / 量能共振走坏

#### 趋势衰减

例如：

- 还没完全坏，但持续走弱
- execution_score 下滑
- leader 角色丧失

#### 卖飞保护

例如：

- 趋势仍强，不允许机械 SELL
- 盈利单优先 REDUCE 而不是全卖

### 输出结构

```python
{
    "symbol": "600036",
    "exit_type": "reduce_on_weakening",
    "exit_quality_score": 0.71,
    "suggested_action": "REDUCE",
    "exit_reason": "趋势衰减但结构未完全破坏，先减仓"
}
```

### 仓库接入要求

- 必须优先接入持仓复核与 `realtime_ai_review_service.py`
- 必须能影响：
  - `PortfolioManagerAction`
  - `REDUCE / SELL / HOLD`
  - `trade_timing_feedback_service.py`

### 验收标准

- SELL / REDUCE 不再主要依赖固定亏损/盈利阈值
- 结构判断能进入持仓复核与终审链路
- 首页和 8610 能看出卖点类型

---

## 9. 阶段 15F：把新结构信号接入评分与终审

## 目标

把主线识别、龙头过滤、买点/卖点结构判断纳入主链，而不是做成旁路展示。

### 修改文件

```text
ai_stock_sim/app/score_service.py
ai_stock_sim/app/decision_context_builder.py
ai_stock_sim/app/realtime_ai_review_service.py
ai_stock_sim/app/ai_decision_engine.py
```

### 必须实现

#### 对 setup_score 的增强

加入：

- 主线匹配度
- 龙头角色得分
- 候选质量得分

#### 对 execution_score 的增强

加入：

- `entry_type / exit_type`
- `entry_quality_score / exit_quality_score`

#### 对 LLM 终审的增强

把以下字段加入 payload：

- `theme`
- `leader_role`
- `quality_score`
- `entry_type`
- `exit_type`
- `entry_reason`
- `exit_reason`

### 验收标准

- 新系统不只是“先算完再展示”
- 而是会真正改变 BUY / REDUCE / SELL 的发生概率

---

## 10. 阶段 15G：学习层接入新反馈

## 目标

让主线、龙头、买点、卖点的效果进入学习层，稳定反哺参数和策略权重。

### 新增文件

`ai_stock_sim/app/trade_timing_feedback_service.py`

### 必须统计的内容

#### 买点反馈

- 哪类 entry_type 胜率更高
- 哪类 entry_type 更容易追高失败
- 哪类市场状态下 probe_entry 表现最好

#### 卖点反馈

- 哪类 exit_type 更能减少回撤
- 哪类 exit_type 更容易卖飞
- REDUCE 和 SELL 的长期收益差异

#### 主线 / 龙头反馈

- leader 表现 vs follower 表现
- 主线股 vs 非主线股表现
- 动态扫描加入的主线股票后续表现

### 输出结构

```python
{
    "entry_feedback": {...},
    "exit_feedback": {...},
    "theme_feedback": {...},
    "leader_feedback": {...}
}
```

### 修改文件

```text
ai_stock_sim/app/adaptive_weight_service.py
ai_stock_sim/app/style_profile_service.py
ai_stock_sim/app/strategy_evaluation_service.py
ai_stock_sim/app/strategy_weight_service.py
ai_stock_sim/app/realtime_ai_review_tracking_service.py
```

### 必须实现

学习层在调权时，除已有策略绩效外，还要参考：

- 主线过滤效果
- 龙头过滤效果
- 买点结构效果
- 卖点结构效果

### 仓库接入要求

- 反馈必须进入：
  - `adaptive_weights.json`
  - `adaptive_weight_history`
  - 8600 首页摘要
  - 8610 权重 / 反馈页签

### 验收标准

- 调权不再只看策略胜率
- 会看“哪个 entry / exit / theme / leader 组合更有效”

---

## 11. 阶段 15H：首页与 8610 展示

## 目标

把这些新增能力分成：

- 客户可读层（8600）
- 深度分析层（8610）

### 8600 首页新增卡片

修改：

```text
ai_stock_sim/dashboard/services/ui_home_service.py
ai_stock_sim/dashboard/pages/ai_trading_home.py
```

#### 必须新增

1. 当前市场主线
   - 当前主线板块
   - 当前市场模式（主线集中 / 混合 / 弱主线）

2. 当前核心关注来源
   - 来自主线龙头
   - 来自主线强跟随
   - 来自持仓保留

3. 当前买点质量摘要
   - 试仓点数量
   - 加仓点数量
   - 观察点数量
   - 禁追高拦截数量

4. 当前卖点质量摘要
   - 继续持有
   - 趋势减弱待减仓
   - 结构破坏待卖出

### 8610 深度页签新增

修改：

`ai_stock_sim/dashboard/dashboard_app.py`

#### 必须新增分析页

- 主线识别与板块强度
- 龙头/跟风分层
- 买点结构分析
- 卖点结构分析
- 新增结构反馈与学习层关联

### 验收标准

- 客户在 8600 能看到“为什么今天重点盯这些票”
- 你在 8610 能看到“哪些 entry/exit 真的提升了收益”

---

## 12. 阶段 15I：配置项

### 修改文件

`ai_stock_sim/config/settings.yaml`

### 必须新增

```yaml
theme_detection:
  enabled: true
  min_theme_strength: 0.55

leader_filter:
  enabled: true
  leader_priority: true
  suppress_weak_followers: true

candidate_quality:
  enabled: true
  min_quality_score: 0.50

entry_structure:
  enabled: true
  chase_block_enabled: true
  require_pullback_confirmation: true

exit_structure:
  enabled: true
  prefer_reduce_before_sell: true
  structure_break_required_for_full_sell: true
```

---

## 13. 阶段 15J：测试要求

### 新增测试

- `ai_stock_sim/tests/test_theme_detection_service.py`
- `ai_stock_sim/tests/test_leader_selection_service.py`
- `ai_stock_sim/tests/test_candidate_quality_service.py`
- `ai_stock_sim/tests/test_entry_structure_service.py`
- `ai_stock_sim/tests/test_exit_structure_service.py`
- `ai_stock_sim/tests/test_trade_timing_feedback_service.py`

### 关键测试点

1. 主线识别能输出强主题
2. 龙头识别能区分 leader / follower
3. 弱趋势、低质量票被过滤
4. 追高会被禁止
5. 回踩确认能产出试仓/加仓点
6. 卖点能区分减仓与清仓
7. 新结构信号会影响最终动作
8. 学习层能读取 entry/exit/theme/leader 的反馈
9. `paper_main` 与 `paper_small_1w` 能并行运行且不串数据
10. 新反馈写库不阻塞主引擎

---

## 14. 验收标准（全部满足才算完成）

1. 候选池优先来自主线与龙头
2. 弱趋势票、低质量票明显减少
3. BUY 不再只看 execution_score，而要看结构化买点
4. SELL / REDUCE 不再只看机械阈值，而要看结构化卖点
5. LLM 终审 payload 中包含主线、龙头、买卖点结构信息
6. 学习层能对主线/龙头/买点/卖点效果做反馈
7. 8600 能让客户看懂“为什么是这些票、为什么是这些动作”
8. 8610 能深挖“哪些 entry/exit/theme/leader 真赚钱”
9. 两个模拟账户并行稳定运行
10. 本阶段新增能力不会把实时引擎重新拖回同步阻塞链

---

## 15. 开发优先级

严格按这个顺序推进：

1. `theme_detection_service.py`
2. `leader_selection_service.py`
3. `candidate_quality_service.py`
4. `entry_structure_service.py`
5. `exit_structure_service.py`
6. 接入 `score_service.py` / `decision_context_builder.py`
7. 接入 `realtime_ai_review_service.py`
8. `trade_timing_feedback_service.py`
9. 学习层接入
10. 首页与 8610 展示
11. 测试与 README

---

## 16. 最终执行要求

将系统升级为“主线驱动 + 龙头优先 + 结构化买卖点”的 AI 交易系统，让 AI 不只是做终审和风控，而是真正改善选股质量、买点质量和卖点质量，并把这些改进稳定反馈到参数和策略权重里。

额外要求：

1. 必须优先提升候选池质量与买点质量，而不是只加强终审文案
2. 必须保证两个模拟账户并行稳定，不因反馈写库再次出现主链阻塞
3. 必须让 AI 真正对“少犯错”负责，最终能看出：
   - 少买错票
   - 少追高
   - 少卖飞
   - 少在弱结构里反复试错
