"""Progress event emitter — writes one JSON object per line to stderr."""

import json
import sys
from threading import Lock

_PROGRESS_LOCK = Lock()


def _progress(obj: dict) -> None:
    # streamKind hint for backend: "data" = page payload to store, "info" = runtime status only
    if "streamKind" not in obj:
        evt = str(obj.get("event") or "").strip().lower()
        obj["streamKind"] = "data" if evt == "page_data" else "info"
    # Parallel workers emit concurrently; lock serialises writes so each line is valid JSON.
    with _PROGRESS_LOCK:
        print(json.dumps(obj), file=sys.stderr, flush=True)