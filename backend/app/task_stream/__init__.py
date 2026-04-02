"""Redis-backed task stream infrastructure.

This package is meant to be reusable for any background task that:
- emits incremental progress (stage/token/etc) for frontend streaming,
- can be re-attached after frontend refresh using `stream_id` or actor keys,
- persists errors/final outcome so late/renewed clients still see them.
"""

