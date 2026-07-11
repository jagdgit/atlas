"""Task handler registry.

A task handler is a callable ``(payload: dict) -> dict | None``. Future work
(embedding, ingestion, etc.) registers handlers by task type; the scheduler
looks them up when a task of that type is claimed.
"""

from __future__ import annotations

from typing import Any, Callable

TaskHandler = Callable[[dict[str, Any]], dict[str, Any] | None]


class HandlerRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, TaskHandler] = {}

    def register(self, task_type: str, handler: TaskHandler) -> None:
        self._handlers[task_type] = handler

    def get(self, task_type: str) -> TaskHandler | None:
        return self._handlers.get(task_type)

    def has(self, task_type: str) -> bool:
        return task_type in self._handlers

    def types(self) -> list[str]:
        return sorted(self._handlers)
