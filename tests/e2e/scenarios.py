"""E2E 测试场景定义。"""

from dataclasses import dataclass


@dataclass
class Scenario:
    id: str
    query: str
    expected_stage: str
    description: str


SCENARIOS = [
    Scenario(
        id="greeting",
        query="你好",
        expected_stage="answered",
        description="问候语，不应调任何数据工具",
    ),
    Scenario(
        id="knowledge_pe",
        query="PE是什么意思",
        expected_stage="answered",
        description="知识问题，不应调数据工具",
    ),
    Scenario(
        id="single_stock_code",
        query="600519",
        expected_stage="completed",
        description="股票代码直接输入，走完整分析链",
    ),
    Scenario(
        id="single_stock_name",
        query="帮我分析一下茅台",
        expected_stage="completed",
        description="股票名称，应先 resolve_stock 再分析",
    ),
    Scenario(
        id="quick_price",
        query="茅台现在多少钱",
        expected_stage="answered",
        description="快速价格查询，agent 正确识别为简单问题，用 commit_answer 直接回答",
    ),
    Scenario(
        id="ambiguous_name",
        query="平安",
        expected_stage="clarifying",
        description="歧义股票名，应触发 commit_clarification",
    ),
    Scenario(
        id="market_overview",
        query="今天大盘怎么样",
        expected_stage="answered",
        description="市场概览，应调 get_hot_list 或 search_web",
    ),
    Scenario(
        id="small_cap_sparse_data",
        query="301368",
        expected_stage="completed",
        description="小盘股，财务数据可能不完整，测试幻觉风险",
    ),
]
