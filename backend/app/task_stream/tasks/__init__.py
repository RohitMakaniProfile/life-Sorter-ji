"""
Task implementations registered into the task-stream registry.

Importing this package is what activates the `@register_task_stream(...)`
decorators for production tasks.
"""

from app.task_stream.tasks.playbook_generate import playbook_generate_task  # noqa: F401

