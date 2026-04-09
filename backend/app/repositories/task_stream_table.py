from __future__ import annotations


def cleanup_stale_running_streams_sql() -> str:
    return (
        "UPDATE task_stream_streams "
        "SET status = 'error', "
        "    expires_at = NOW() + INTERVAL '1 hour' "
        "WHERE status = 'running' "
        "  AND created_at < NOW() - ($1::int * INTERVAL '1 minute')"
    )
