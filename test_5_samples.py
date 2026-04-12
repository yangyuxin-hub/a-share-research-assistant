"""
临时测试脚本：测试 5 个样例的 router + orchestrator 流程。
运行方式：在项目根目录下执行
  .venv/Scripts/python test_5_samples.py
"""

import sys
import os
import time
import logging
from datetime import datetime, timezone

# 加入 src 到 sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

# 加载 .env（pydantic-settings 会自动读，但保险起见手动也加载一次）
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"), override=False)
except ImportError:
    pass  # 如果没有 python-dotenv，pydantic-settings 自己读

# ── 日志配置：WARNING 级别，捕获 ERROR ─────────────────────────────────────────

class ErrorCapture(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.ERROR)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


error_capture = ErrorCapture()

logging.basicConfig(
    level=logging.WARNING,
    format="%(levelname)s [%(name)s] %(message)s",
)
logging.getLogger().addHandler(error_capture)

# ── 初始化组件 ─────────────────────────────────────────────────────────────────

print("初始化组件...")

import anthropic as anthropic_sdk
from ashare_research_assistant.config.settings import settings
from ashare_research_assistant.core.models import SessionState
from ashare_research_assistant.agents.main_agent import MainAgent
from ashare_research_assistant.agents.orchestrator import Orchestrator
from ashare_research_assistant.providers.tushare import TushareMarketDataProvider
from ashare_research_assistant.providers.cninfo import CninfoAnnouncementProvider
from ashare_research_assistant.providers.akshare import AKShareNewsProvider
from ashare_research_assistant.providers.akshare.hotlist_provider import AKShareHotlistProvider
from ashare_research_assistant.providers.web_search_provider import WebSearchProvider
from ashare_research_assistant.services.clarification_engine import ClarificationEngine
from ashare_research_assistant.services.trace_store import TraceStore

# 确保本地目录存在
settings.ensure_local_dirs()

# LLM 客户端
client_kwargs = {"api_key": settings.anthropic_api_key}
if settings.anthropic_base_url:
    client_kwargs["base_url"] = settings.anthropic_base_url

client = anthropic_sdk.Anthropic(**client_kwargs)

# Providers
market = TushareMarketDataProvider(token=settings.tushare_token or None)
announcement = CninfoAnnouncementProvider(token=settings.tushare_token or None)
news = AKShareNewsProvider()
web_search = WebSearchProvider()
hotlist = AKShareHotlistProvider()

# Services
trace_store = TraceStore(path=settings.trace_store_path)
clarification_engine = ClarificationEngine()

# Agents
orchestrator = Orchestrator(
    market_data_provider=market,
    announcement_provider=announcement,
    news_provider=news,
    anthropic_client=client,
    clarification_engine=clarification_engine,
    trace_store=trace_store,
    web_search=web_search,
    hotlist_provider=hotlist,
)

print("初始化完成。\n")
print("=" * 70)

# ── 测试样例 ──────────────────────────────────────────────────────────────────

SAMPLES = [
    "600519",
    "贵州茅台",
    "茅台现在多少钱",
    "大盘今天怎么样",
    "PE是什么意思",
]

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


results = []

for idx, user_input in enumerate(SAMPLES, 1):
    print(f"\n[样例 {idx}] 输入：{user_input!r}")
    print("-" * 50)

    # 清空 error_capture
    error_capture.records.clear()

    # 创建初始会话状态
    state = SessionState(created_at=_now_iso(), updated_at=_now_iso())
    state = state.new_turn(user_input)

    t0 = time.perf_counter()

    # MainAgent via Orchestrator
    output_summary = ""
    stage = "N/A"
    intent_type = "N/A"
    confidence = "N/A"
    try:
        state = orchestrator.run(state)
        stage = state.stage
        # 从 trace 里推断 intent（MainAgent 不再暴露 intent_type）
        intent_type = getattr(state, "intent", None) or "N/A"
        confidence = f"{getattr(state, 'intent_confidence', None) or 0.0:.2f}"
        print(f"  Stage             : {stage}")

        if stage == "completed" and state.output_draft:
            card = state.output_draft
            output_summary = f"stance={card.stance_label} | {card.one_liner}"
            print(f"  stance_label      : {card.stance_label}")
            print(f"  one_liner         : {card.one_liner}")

        elif stage == "answered" and state.direct_answer:
            ans = state.direct_answer[:100]
            output_summary = ans
            print(f"  direct_answer[:100]: {ans}")

        elif stage == "degraded":
            if state.trace:
                last = state.trace[-1].summary
                output_summary = last
                print(f"  last trace summary : {last}")

        elif stage == "clarifying":
            q = state.clarification.question or ""
            output_summary = f"clarifying: {q[:80]}"
            print(f"  clarification Q   : {q[:80]}")

        elif stage == "running":
            print(f"  (still running)")

    except Exception as e:
        print(f"  [ERROR] {e}")
        stage = "exception"
        output_summary = str(e)

    elapsed = time.perf_counter() - t0
    print(f"  耗时               : {elapsed:.2f}s")

    # 收集本样例的 ERROR 日志
    errs = [logging.Formatter().format(r) for r in error_capture.records]
    if errs:
        print(f"  ERROR 日志 ({len(errs)} 条):")
        for e in errs:
            print(f"    {e}")
    else:
        print("  ERROR 日志          : (无)")

    results.append({
        "idx": idx,
        "input": user_input,
        "intent": intent_type,
        "confidence": confidence,
        "stage": stage,
        "output_summary": output_summary[:60] if output_summary else "",
        "elapsed": elapsed,
        "errors": errs,
    })


# ── 汇总表格 ──────────────────────────────────────────────────────────────────

print("\n" + "=" * 70)
print("汇总表格")
print("=" * 70)
header = f"{'#':<3} {'输入':<18} {'intent':<30} {'conf':<6} {'stage':<12} {'耗时(s)':<8}"
print(header)
print("-" * 70)
for r in results:
    print(f"{r['idx']:<3} {r['input']:<18} {r['intent']:<30} {r['confidence']:<6} {r['stage']:<12} {r['elapsed']:<8.2f}")

print("\n输出摘要：")
for r in results:
    print(f"  [{r['idx']}] {r['input']!r:20s} → {r['output_summary']}")

print("\n所有 ERROR 日志汇总：")
any_error = False
for r in results:
    if r["errors"]:
        any_error = True
        print(f"  [样例 {r['idx']} - {r['input']!r}]")
        for e in r["errors"]:
            print(f"    {e}")
if not any_error:
    print("  (无)")
