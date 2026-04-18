"""RouterAgent — 已归档，不再使用。

原职责：独立的意图识别层，通过一次额外 LLM 调用将用户输入分类为
intent_type 枚举值（single_stock_analysis / hot_candidate_discovery 等），
再路由到对应的下游 Agent。

废弃原因：
MainAgent 已将所有工具（resolve_stock、数据工具、commit_*）统一暴露给模型，
由模型根据 system prompt 中的工具说明自主决策调用顺序，不再需要独立的意图分类步骤。
工具的 description 即路由规则，调用哪个工具本身就是意图的表达。
"""
