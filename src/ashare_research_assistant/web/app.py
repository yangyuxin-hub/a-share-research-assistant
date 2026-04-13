"""Gradio Web 界面。

启动方式：
  uv run ashare web                   # 本地 http://localhost:7860
  uv run ashare web --share           # 生成公网临时链接（无需服务器）
  uv run ashare web --port 8080       # 自定义端口
"""

import logging
import queue
import threading
from datetime import datetime, timezone
from typing import Generator, Optional

import anthropic
import gradio as gr

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
    "resolve_stock":        "解析股票",
    "commit_intent":        "确认意图",
    "get_stock_profile":    "基本面",
    "get_price_snapshot":   "价格快照",
    "get_daily_bars":       "历史 K 线",
    "get_financial_factors": "财务因子",
    "search_announcements": "公告搜索",
    "search_news":          "新闻搜索",
    "search_web":           "网络搜索",
    "get_hot_list":         "热门榜单",
    "commit_opinion":       "生成结论",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── 全局 Orchestrator（无状态，所有 session 共享）────────────────────────────
_orchestrator: Optional[Orchestrator] = None


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
        web_search = WebSearchProvider()
        hotlist = AKShareHotlistProvider()
        _orchestrator = Orchestrator(
            market_data_provider=market,
            announcement_provider=ann,
            news_provider=news,
            anthropic_client=client,
            clarification_engine=ClarificationEngine(),
            trace_store=TraceStore(path=settings.trace_store_path),
            web_search=web_search,
            hotlist_provider=hotlist,
        )
        logger.info("Orchestrator 初始化完成")
    return _orchestrator


def _new_session() -> SessionState:
    return SessionState(created_at=_now_iso(), updated_at=_now_iso())


# ── 流式推进状态文本 ──────────────────────────────────────────────────────────

def _build_progress_text(tool_calls: list[tuple[str, str]], done: bool = False) -> str:
    """把已完成工具列表渲染为单条 assistant 消息（实时更新用）。"""
    if not tool_calls:
        return "*正在分析...*"
    lines = []
    for i, (name, brief) in enumerate(tool_calls):
        label = _TOOL_LABEL.get(name, name)
        suffix = f" — {brief}" if brief else ""
        # 最后一条如果还没结束，显示旋转提示
        if not done and i == len(tool_calls) - 1:
            lines.append(f"⏳ **{label}**{suffix}")
        else:
            lines.append(f"✅ **{label}**{suffix}")
    status = "" if done else "\n\n*处理中...*"
    return "\n\n".join(lines) + status


# ── Gradio 界面构建 ───────────────────────────────────────────────────────────

def build_demo() -> gr.Blocks:
    with gr.Blocks(title="A 股投研助手") as demo:

        gr.Markdown(
            "# 📊 A 股投研助手\n"
            "输入股票代码、名称或自然语言问题，获取 AI 投研分析。\n"
            "> 输入 **帮助** 查看使用说明"
        )

        session_state = gr.State(_new_session)

        chatbot = gr.Chatbot(
            value=[],
            height=560,
            show_label=False,
            render_markdown=True,
        )

        with gr.Row():
            msg_input = gr.Textbox(
                placeholder="输入股票代码（如 600519）或名称（如 贵州茅台）...",
                show_label=False,
                scale=9,
                container=False,
                autofocus=True,
            )
            send_btn = gr.Button("发送", variant="primary", scale=1, min_width=60)

        clear_btn = gr.Button("🗑️ 清空对话", variant="secondary", size="sm")

        # ── 核心流式处理 ──────────────────────────────────────────────────────

        def respond(
            message: str,
            history: list,
            state: SessionState,
        ) -> Generator:
            if not message.strip():
                yield "", history, state
                return

            history = list(history)
            history.append({"role": "user", "content": message})

            # ── 内置命令（立即返回，不需要流式）────────────────────────────
            lower = message.strip().lower()

            if lower in ("退出", "exit", "quit"):
                history.append({"role": "assistant", "content": "再见，欢迎随时回来。"})
                yield "", history, _new_session()
                return

            if lower in ("帮助", "help"):
                help_md = (
                    "**A 股投研助手 使用说明**\n\n"
                    "- 输入股票代码（如 `600519`）或名称（如 `贵州茅台`）开始分析\n"
                    "- 输入自然语言问题（如 `AI 板块怎么样`）\n"
                    "- 输入 `展开` 查看上一次分析的完整证据链\n"
                    "- 点击 **清空对话** 开始新会话"
                )
                history.append({"role": "assistant", "content": help_md})
                yield "", history, state
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
                history.append({"role": "assistant", "content": resp})
                yield "", history, state
                return

            # ── 正常对话：用线程跑 Orchestrator，主线程流式 yield ────────────

            # 先插入一条占位 assistant 消息
            history.append({"role": "assistant", "content": "*正在分析...*"})
            yield "", history, state  # 立即显示用户消息 + 加载提示

            orch = _get_orchestrator()
            new_state_holder: list[SessionState] = []
            exc_holder: list[Exception] = []
            ev_queue: queue.Queue = queue.Queue()

            def progress_cb(tool_name: str, brief: str) -> None:
                ev_queue.put(("tool", tool_name, brief))

            def worker() -> None:
                try:
                    s = state.new_turn(message)
                    if s.clarification.status == "pending":
                        result = orch.handle_clarification_answer(s, message)
                    else:
                        result = orch.run(s, progress_cb=progress_cb)
                    new_state_holder.append(result)
                except Exception as e:
                    exc_holder.append(e)
                finally:
                    ev_queue.put(("done",))

            t = threading.Thread(target=worker, daemon=True)
            t.start()

            tool_calls: list[tuple[str, str]] = []

            # 消费队列事件，每次有新工具调用就 yield 一次
            while True:
                try:
                    event = ev_queue.get(timeout=30)
                except queue.Empty:
                    # 超时保护
                    history[-1] = {"role": "assistant", "content": "*分析超时，请重试。*"}
                    yield "", history, state
                    return

                if event[0] == "tool":
                    _, name, brief = event
                    tool_calls.append((name, brief))
                    history[-1] = {
                        "role": "assistant",
                        "content": _build_progress_text(tool_calls, done=False),
                    }
                    yield "", history, state

                elif event[0] == "done":
                    break

            t.join()

            if exc_holder:
                logger.error("Orchestrator 异常", exc_info=exc_holder[0])
                history[-1] = {"role": "assistant", "content": f"*分析出错：{exc_holder[0]}*"}
                yield "", history, state
                return

            final_state = new_state_holder[0]

            # 工具调用摘要（折叠）+ 最终结论
            progress_summary = _build_progress_text(tool_calls, done=True) if tool_calls else ""
            conclusion = md_renderer.render_state(final_state, tool_calls=[])

            if progress_summary and conclusion:
                full_response = (
                    "<details><summary>📊 分析过程（点击展开）</summary>\n\n"
                    + progress_summary
                    + "\n\n</details>\n\n"
                    + conclusion
                )
            else:
                full_response = conclusion or progress_summary or "*未能生成结论，请换种方式提问。*"

            history[-1] = {"role": "assistant", "content": full_response}
            yield "", history, final_state

        # ── 绑定事件 ─────────────────────────────────────────────────────────

        submit_inputs = [msg_input, chatbot, session_state]
        submit_outputs = [msg_input, chatbot, session_state]

        msg_input.submit(respond, inputs=submit_inputs, outputs=submit_outputs)
        send_btn.click(respond, inputs=submit_inputs, outputs=submit_outputs)

        clear_btn.click(
            fn=lambda: ([], _new_session()),
            outputs=[chatbot, session_state],
        )

    return demo


# ── 入口 ─────────────────────────────────────────────────────────────────────

def launch(share: bool = False, port: int = 7860, host: str = "127.0.0.1") -> None:
    """启动 Gradio Web 服务。"""
    settings.ensure_local_dirs()

    if not settings.anthropic_api_key:
        raise RuntimeError("请在 .env 中配置 ASHARE_API_KEY")

    _get_orchestrator()

    demo = build_demo()
    demo.launch(
        server_name=host,
        server_port=port,
        share=share,
        show_error=True,
        favicon_path=None,
        theme=gr.themes.Soft(primary_hue="blue", neutral_hue="slate"),
    )
