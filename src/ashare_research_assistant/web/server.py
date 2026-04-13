"""FastAPI Web 服务。

提供：
  GET  /          → 前端 HTML
  POST /api/chat  → SSE 流式响应（工具调用进度 + 最终结论）
"""

import asyncio
import json
import logging
import queue
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator, Optional

import anthropic
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

from ashare_research_assistant.config.settings import settings
from ashare_research_assistant.core.models import SessionState
from ashare_research_assistant.agents.orchestrator import Orchestrator
from ashare_research_assistant.providers.tushare import TushareMarketDataProvider
from ashare_research_assistant.providers.cninfo import CninfoAnnouncementProvider
from ashare_research_assistant.providers.akshare import AKShareNewsProvider
from ashare_research_assistant.providers.akshare.hotlist_provider import AKShareHotlistProvider
from ashare_research_assistant.providers.web_search_provider import WebSearchProvider
from ashare_research_assistant.services.clarification_engine import ClarificationEngine
from ashare_research_assistant.services.trace_store import TraceStore
from ashare_research_assistant.web import md_renderer

logger = logging.getLogger(__name__)

_TOOL_LABEL: dict[str, str] = {
    "resolve_stock":         "解析股票",
    "commit_intent":         "确认意图",
    "get_stock_profile":     "基本面",
    "get_price_snapshot":    "价格快照",
    "get_daily_bars":        "历史 K 线",
    "get_financial_factors": "财务因子",
    "search_announcements":  "公告搜索",
    "search_news":           "新闻搜索",
    "search_web":            "网络搜索",
    "get_hot_list":          "热门榜单",
    "commit_opinion":        "生成结论",
}

_STATIC_DIR = Path(__file__).parent / "static"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── 全局单例 ──────────────────────────────────────────────────────────────────

_orchestrator: Optional[Orchestrator] = None
_sessions: dict[str, SessionState] = {}


def _get_orchestrator() -> Orchestrator:
    global _orchestrator
    if _orchestrator is None:
        client = anthropic.Anthropic(
            api_key=settings.anthropic_api_key,
            **({"base_url": settings.anthropic_base_url} if settings.anthropic_base_url else {}),
        )
        market = TushareMarketDataProvider(token=settings.tushare_token)
        ann = CninfoAnnouncementProvider(token=settings.tushare_token or None)
        news = AKShareNewsProvider()
        _orchestrator = Orchestrator(
            market_data_provider=market,
            announcement_provider=ann,
            news_provider=news,
            anthropic_client=client,
            clarification_engine=ClarificationEngine(),
            trace_store=TraceStore(path=settings.trace_store_path),
            web_search=WebSearchProvider(),
            hotlist_provider=AKShareHotlistProvider(),
        )
        logger.info("Orchestrator 初始化完成")
    return _orchestrator


# ── FastAPI 应用工厂 ───────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    session_id: str


def create_app() -> FastAPI:
    app = FastAPI(title="A股投研助手", docs_url=None, redoc_url=None)

    @app.get("/")
    async def index() -> HTMLResponse:
        return HTMLResponse((_STATIC_DIR / "index.html").read_text(encoding="utf-8"))

    @app.post("/api/chat")
    async def chat(req: ChatRequest) -> StreamingResponse:
        if req.session_id not in _sessions:
            _sessions[req.session_id] = SessionState(
                created_at=_now_iso(), updated_at=_now_iso()
            )

        state = _sessions[req.session_id]

        return StreamingResponse(
            _stream(req.message.strip(), req.session_id, state),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    return app


# ── SSE 流式生成器 ────────────────────────────────────────────────────────────

async def _stream(
    message: str, session_id: str, state: SessionState
) -> AsyncGenerator[str, None]:

    def sse(data: dict) -> str:
        return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

    lower = message.lower()

    # ── 内置命令（立即返回）────────────────────────────────────────────────
    if lower in ("退出", "exit", "quit"):
        _sessions[session_id] = SessionState(created_at=_now_iso(), updated_at=_now_iso())
        yield sse({"type": "result", "content": "再见，欢迎随时回来。"})
        yield "data: [DONE]\n\n"
        return

    if lower in ("帮助", "help"):
        yield sse({"type": "result", "content": (
            "**使用说明**\n\n"
            "- 输入股票代码（如 `600519`）或名称（如 `贵州茅台`）开始分析\n"
            "- 输入自然语言问题（如 `AI 板块怎么样`）\n"
            "- 输入 `展开` 查看上一次分析的完整证据链\n"
            "- 点击 **新对话** 重置会话"
        )})
        yield "data: [DONE]\n\n"
        return

    if lower in ("展开", "expand"):
        from ashare_research_assistant.core.models import ExpandedOpinionCard
        if state.working_memory.active_task:
            try:
                expanded = ExpandedOpinionCard.model_validate_json(
                    state.working_memory.active_task
                )
                resp = md_renderer.render_opinion_card(expanded)
            except Exception as e:
                resp = f"*展开失败：{e}*"
        else:
            resp = "*暂无可展开的分析结果。*"
        yield sse({"type": "result", "content": resp})
        yield "data: [DONE]\n\n"
        return

    # ── 正常流程：后台线程跑 Orchestrator，队列传事件 ──────────────────────
    orch = _get_orchestrator()
    q: queue.Queue = queue.Queue()
    result_holder: list = []

    def progress_cb(tool_name: str, brief: str) -> None:
        label = _TOOL_LABEL.get(tool_name, tool_name)
        q.put(("tool", label, brief))

    def worker() -> None:
        try:
            s = state.new_turn(message)
            if s.clarification.status == "pending":
                result = orch.handle_clarification_answer(s, message)
            else:
                result = orch.run(s, progress_cb=progress_cb)
            result_holder.append(result)
        except Exception as e:
            logger.error("Orchestrator 异常", exc_info=e)
            result_holder.append(e)
        finally:
            q.put(("done",))

    t = threading.Thread(target=worker, daemon=True)
    t.start()

    loop = asyncio.get_event_loop()

    while True:
        try:
            event = await loop.run_in_executor(None, lambda: q.get(timeout=120))
        except queue.Empty:
            yield sse({"type": "error", "content": "分析超时，请重试。"})
            yield "data: [DONE]\n\n"
            return

        if event[0] == "tool":
            _, label, brief = event
            yield sse({"type": "tool", "label": label, "brief": brief})
            await asyncio.sleep(0)
        elif event[0] == "done":
            break

    t.join()

    if not result_holder:
        yield sse({"type": "error", "content": "未能生成结论，请重试。"})
    elif isinstance(result_holder[0], Exception):
        yield sse({"type": "error", "content": str(result_holder[0])})
    else:
        final_state: SessionState = result_holder[0]
        _sessions[session_id] = final_state
        content = md_renderer.render_state(final_state, tool_calls=[])
        yield sse({"type": "result", "content": content})

    yield "data: [DONE]\n\n"
