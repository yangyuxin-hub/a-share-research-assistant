"""
Codex Provider：以 Anthropic 兼容接口调用 ChatGPT Codex 后端。

外部用法（与 anthropic.Anthropic 完全相同，agent 代码零改动）：

    from ashare_research_assistant.llm.codex_provider import CodexClient

    client = CodexClient.from_token_path(".local/chatgpt_tokens.json", model="codex-mini-latest")

    response = client.messages.create(
        model="...",          # 可忽略，使用 client 初始化时指定的 model
        max_tokens=2048,
        system="...",
        tools=[...],          # Anthropic tool 格式（含 input_schema）
        tool_choice={"type": "tool", "name": "X"},
        messages=[...],
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == "X":
            result = block.input   # dict

技术细节：
- 后端：https://chatgpt.com/backend-api/codex/responses  (OpenAI Responses API)
- 认证：ChatGPT Plus/Pro OAuth token（与官方 Codex CLI 相同）
- 请求格式：Anthropic → Responses API（工具格式、消息格式）
- 响应格式：SSE 流 → response.done 事件 → 模拟 Anthropic 响应对象
- 无状态（store: false），每次携带完整历史
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

from .chatgpt_oauth import ensure_valid_token

logger = logging.getLogger(__name__)

CODEX_RESPONSES_URL = "https://chatgpt.com/backend-api/codex/responses"
DEFAULT_MODEL = "codex-mini-latest"


# ── 模拟 Anthropic 响应对象 ──────────────────────────────────────────────────

@dataclass
class ToolUseBlock:
    """模拟 anthropic.types.ToolUseBlock"""
    name: str
    input: dict
    type: str = "tool_use"
    id: str = ""


@dataclass
class FakeMessagesResponse:
    """模拟 anthropic.types.Message，只保留 agents 实际用到的字段。"""
    content: list[ToolUseBlock] = field(default_factory=list)
    stop_reason: str = "tool_use"


# ── 格式转换 ─────────────────────────────────────────────────────────────────

def _convert_tools(anthropic_tools: list[dict]) -> list[dict]:
    """
    Anthropic tool 格式 → OpenAI Responses API function 格式。

    Anthropic:
        {"name": "X", "description": "...", "input_schema": {...}}
    OpenAI:
        {"type": "function", "name": "X", "description": "...", "parameters": {...}}
    """
    result = []
    for t in anthropic_tools:
        result.append({
            "type": "function",
            "name": t["name"],
            "description": t.get("description", ""),
            "parameters": t.get("input_schema", {}),
            "strict": False,
        })
    return result


def _build_input(system: str | None, messages: list[dict]) -> list[dict]:
    """
    合并 system prompt 和消息列表为 Responses API input 格式。

    Anthropic messages 格式与 OpenAI input 格式基本相同，
    system 放在 input 首条 system role 消息里。
    """
    input_messages = []
    if system:
        input_messages.append({"role": "system", "content": system})
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            input_messages.append({"role": msg["role"], "content": content})
        elif isinstance(content, list):
            # Anthropic 多模态 content block → 简化为文本
            text_parts = [
                b.get("text", "") for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            ]
            input_messages.append({"role": msg["role"], "content": " ".join(text_parts)})
    return input_messages


# ── SSE 解析 ─────────────────────────────────────────────────────────────────

def _parse_sse_response(resp: httpx.Response) -> dict | None:
    """
    解析 Codex 后端的 SSE 流，返回 response.done 事件中的完整 response 对象。
    只需要最后一条 response.done 即可拿到完整 output。
    """
    final_response: dict | None = None

    for raw_line in resp.iter_lines():
        line = raw_line.strip()
        if not line or not line.startswith("data:"):
            continue
        data_str = line[len("data:"):].strip()
        if data_str == "[DONE]":
            break
        try:
            event = json.loads(data_str)
        except json.JSONDecodeError:
            continue

        event_type = event.get("type", "")
        if event_type == "response.done":
            final_response = event.get("response")
        elif event_type == "error":
            err = event.get("error", {})
            raise RuntimeError(f"Codex API 错误: {err.get('message', event)}")

    return final_response


# ── HTTP 调用 ─────────────────────────────────────────────────────────────────

class _MessagesNamespace:
    """
    模拟 anthropic.Anthropic.messages，提供 create() 方法。
    由 CodexClient 持有。
    """

    def __init__(self, token_path: str, model: str) -> None:
        self._token_path = token_path
        self._model = model

    def _get_headers(self) -> dict:
        tokens = ensure_valid_token(self._token_path)
        return {
            "Authorization": f"Bearer {tokens['access_token']}",
            "chatgpt-account-id": tokens.get("account_id", ""),
            "OpenAI-Beta": "responses=experimental",
            "originator": "codex_cli_rs",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }

    def create(
        self,
        *,
        model: str | None = None,
        max_tokens: int = 2048,
        system: str | None = None,
        tools: list[dict] | None = None,
        tool_choice: dict | None = None,
        messages: list[dict] | None = None,
        **_kwargs: Any,
    ) -> FakeMessagesResponse:
        """
        Anthropic-compatible 接口。
        model 参数会被忽略，使用 CodexClient 初始化时指定的模型。
        """
        body: dict[str, Any] = {
            "model": self._model,
            "input": _build_input(system, messages or []),
            "store": False,
            "stream": True,
        }

        if tools:
            body["tools"] = _convert_tools(tools)
            # Anthropic tool_choice={"type":"tool","name":"X"} → 强制使用工具
            # Responses API: tool_choice="required" 或指定函数名
            if tool_choice and tool_choice.get("type") == "tool":
                forced_name = tool_choice.get("name")
                if forced_name:
                    body["tool_choice"] = {"type": "function", "name": forced_name}
                else:
                    body["tool_choice"] = "required"

        try:
            headers = self._get_headers()
            with httpx.stream(
                "POST",
                CODEX_RESPONSES_URL,
                json=body,
                headers=headers,
                timeout=90,
            ) as resp:
                if resp.status_code != 200:
                    # 读取错误体
                    error_text = resp.read().decode("utf-8", errors="replace")
                    raise RuntimeError(
                        f"Codex 后端返回 HTTP {resp.status_code}: {error_text[:300]}"
                    )
                final = _parse_sse_response(resp)
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"Codex 请求失败: {e}") from e

        return _build_fake_response(final)


def _build_fake_response(response_obj: dict | None) -> FakeMessagesResponse:
    """将 Responses API response 对象转换为 FakeMessagesResponse。"""
    if not response_obj:
        return FakeMessagesResponse()

    content_blocks: list[ToolUseBlock] = []
    for item in response_obj.get("output", []):
        if item.get("type") == "function_call":
            try:
                args = json.loads(item.get("arguments", "{}"))
            except json.JSONDecodeError:
                args = {}
            content_blocks.append(
                ToolUseBlock(
                    name=item.get("name", ""),
                    input=args,
                    id=item.get("id", ""),
                )
            )

    return FakeMessagesResponse(content=content_blocks)


# ── 公开入口 ──────────────────────────────────────────────────────────────────

class CodexClient:
    """
    ChatGPT Codex 客户端，对外暴露与 anthropic.Anthropic 相同的 .messages 接口。

    用法：
        client = CodexClient.from_token_path(".local/chatgpt_tokens.json")
        # 然后像使用 anthropic.Anthropic 一样使用 client
    """

    def __init__(self, token_path: str, model: str = DEFAULT_MODEL) -> None:
        self.messages = _MessagesNamespace(token_path=token_path, model=model)

    @classmethod
    def from_token_path(cls, token_path: str, model: str = DEFAULT_MODEL) -> "CodexClient":
        return cls(token_path=token_path, model=model)
