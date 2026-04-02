from __future__ import annotations

from typing import Callable, TypeVar

from app.task_stream.service import TaskFn

TASK_STREAM_REGISTRY: dict[str, TaskFn] = {}

F = TypeVar("F", bound=TaskFn)


def register_task_stream(task_type: str) -> Callable[[F], F]:
    """
    Decorator to register a background task function for a given `task_type`.

    Usage:
        from app.task_stream.registry import register_task_stream

        @register_task_stream("my-task")
        async def my_task(send, payload):
            ...
            return {"result": ...}
    """

    def _decorator(fn: F) -> F:
        TASK_STREAM_REGISTRY[task_type] = fn
        return fn

    return _decorator

