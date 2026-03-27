这个目录用于说明 AI 审批层依赖当前仓库根目录的 `TradeforAgents-minimal` 能力。

由于 `ai_stock_sim` 已经嵌入到同一仓库内，默认会直接使用上层项目根目录：

- `../results`
- `../scripts/run_minimal_deepseek.sh`

因此这里不再复制一份源码，避免递归嵌套。
