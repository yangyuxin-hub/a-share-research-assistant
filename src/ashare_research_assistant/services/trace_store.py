"""Trace 持久化存储，本地 JSONL 文件。"""

import json
import logging
from pathlib import Path

from ashare_research_assistant.core.models import TraceEvent

logger = logging.getLogger(__name__)


class TraceStore:
    def __init__(self, path: str = ".local/trace.jsonl") -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, event: TraceEvent) -> None:
        try:
            with self._path.open("a", encoding="utf-8") as f:
                f.write(event.model_dump_json() + "\n")
        except Exception as e:
            logger.error(f"TraceStore.append 失败: {e}")

    def append_many(self, events: list[TraceEvent]) -> None:
        for e in events:
            self.append(e)

    def read_by_turn(self, turn_id: str) -> list[TraceEvent]:
        if not self._path.exists():
            return []
        events = []
        try:
            with self._path.open(encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    data = json.loads(line)
                    if data.get("turn_id") == turn_id:
                        events.append(TraceEvent.model_validate(data))
        except Exception as e:
            logger.error(f"TraceStore.read_by_turn 失败: {e}")
        return events
