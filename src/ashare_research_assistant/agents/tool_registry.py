"""Tool Registry — 工具的自注册机制。

核心思想：
- 每个工具在 tools.py 里用 @tool_registry.register(SCHEMA) 装饰器一次性声明
- ToolExecutor.execute() 不再维护 dispatch dict，直接调 tool_registry.execute()
- 新增工具 = 新增一个函数 + 一行装饰器，不改任何已有代码

Handler 签名：
    def handler(inp: dict, providers: ProviderBundle, ctx: dict) -> str
    - inp      : LLM 传来的工具参数
    - providers: 当前请求的数据源集合（由 ProviderContainer.bundle() 提供）
    - ctx      : 请求级 side-effect 字典（目前用于传递 last_price 等状态）

示例 — 新增工具：
    from agents.tool_registry import tool_registry

    MY_TOOL_SCHEMA = {"name": "my_tool", "description": "...", "input_schema": {...}}

    @tool_registry.register(MY_TOOL_SCHEMA)
    def _handle_my_tool(inp: dict, providers, ctx: dict) -> str:
        data = providers.market.some_method(inp["symbol"])
        return f"结果：{data}"

    # 然后在 skills.py 对应 Skill 的 tool_names 里加上 "my_tool" 即可
"""

import logging
from dataclasses import dataclass
from typing import Callable, Optional

logger = logging.getLogger(__name__)


@dataclass
class ToolEntry:
    schema: dict
    handler: Callable  # (inp, providers, ctx) -> str


class ToolRegistry:
    """工具注册表。

    - register(schema) → 装饰器，把函数注册为工具 handler
    - execute(name, inp, providers, ctx) → 路由到对应 handler
    - get_schemas(names) → 按名返回 Anthropic 格式 schema list
    - all_schemas() → 返回全部已注册 schema
    """

    def __init__(self) -> None:
        self._tools: dict[str, ToolEntry] = {}

    # ── 注册 ──────────────────────────────────────────────────────────────────

    def register(self, schema: dict):
        """装饰器：将函数注册为工具 handler。

        用法::

            @tool_registry.register(TOOL_SCHEMA)
            def _handle_xxx(inp: dict, providers: ProviderBundle, ctx: dict) -> str:
                ...
        """
        def decorator(fn: Callable) -> Callable:
            name = schema["name"]
            if name in self._tools:
                logger.warning(f"工具 '{name}' 已注册，将被覆盖")
            self._tools[name] = ToolEntry(schema=schema, handler=fn)
            return fn
        return decorator

    # ── 执行 ──────────────────────────────────────────────────────────────────

    def execute(
        self,
        name: str,
        inp: dict,
        providers,
        ctx: Optional[dict] = None,
    ) -> str:
        """执行已注册工具，返回 LLM 可读的字符串结果。

        ctx 字典用于工具向调用方传递 side-effect（如 last_price）。
        """
        entry = self._tools.get(name)
        if entry is None:
            return f"未知工具：{name}"
        try:
            return entry.handler(inp, providers, ctx if ctx is not None else {})
        except Exception as e:
            logger.error(f"工具执行失败 [{name}]: {e}", exc_info=True)
            return f"工具执行失败：{e}"

    # ── 查询 ──────────────────────────────────────────────────────────────────

    def get_schema(self, name: str) -> Optional[dict]:
        entry = self._tools.get(name)
        return entry.schema if entry else None

    def get_schemas(self, names: list[str]) -> list[dict]:
        """按名称列表返回 schema，跳过未注册的名称。"""
        schemas = []
        for n in names:
            entry = self._tools.get(n)
            if entry:
                schemas.append(entry.schema)
            else:
                logger.warning(f"get_schemas: 工具 '{n}' 未在 registry 中注册")
        return schemas

    def all_schemas(self) -> list[dict]:
        """返回全部已注册工具的 schema。"""
        return [e.schema for e in self._tools.values()]

    def names(self) -> list[str]:
        return list(self._tools.keys())

    def has(self, name: str) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)

    def __repr__(self) -> str:
        return f"ToolRegistry({list(self._tools.keys())})"


# ── 全局单例 ──────────────────────────────────────────────────────────────────
# tools.py 导入后通过 @tool_registry.register(SCHEMA) 注册所有 handler
tool_registry = ToolRegistry()
