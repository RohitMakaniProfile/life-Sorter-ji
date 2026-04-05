"""
Task implementations registered into the task-stream registry.

Importing this package is what activates the `@register_task_stream(...)`
decorators for production tasks.
"""

from app.task_stream.tasks.crawl import crawl_task  # noqa: F401
from app.task_stream.tasks.onboarding_playbook_generate import onboarding_playbook_generate_task  # noqa: F401
from app.task_stream.tasks.plan_execute import plan_execute_task  # noqa: F401

