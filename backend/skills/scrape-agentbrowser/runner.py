#!/usr/bin/env python3
import json
import os
import re
import subprocess
import sys
from collections import deque
from typing import Any, Deque, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse


def _load_payload() -> Dict[str, Any]:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}


def _extract_args(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalise args coming from the TS backend.

    - When invoked from run.sh, payload is: { args: { url, instructions? } }
    - When invoked from the generic skill runner, payload may contain:
        { message, history, skillId, runId, args? }
    """
    raw_args = payload.get("args") or {}
    if not isinstance(raw_args, dict):
        raw_args = {}

    url = raw_args.get("url") or payload.get("url")
    instructions = raw_args.get("instructions") or payload.get("instructions")

    # As a fallback, try to infer a URL from the message text.
    if not url:
        msg = payload.get("message") or ""
        if isinstance(msg, str) and "http" in msg:
            for token in msg.split():
                if token.startswith("http://") or token.startswith("https://"):
                    url = token.strip(".,;:()[]{}\"'")
                    break

    # Crawl controls — mirror scrape-playwright semantics:
    #   maxPages: int, default 9999
    #   maxDepth: int, default 10
    #   deep: bool, default True
    def _to_int(val: Any, default: int) -> int:
        try:
            if val is None:
                return default
            return int(val)
        except Exception:
            return default

    max_pages = _to_int(raw_args.get("maxPages"), 9999)
    max_depth = _to_int(raw_args.get("maxDepth"), 10)

    deep_val = raw_args.get("deep")
    if isinstance(deep_val, bool):
        deep = deep_val
    elif isinstance(deep_val, str):
        deep = deep_val.lower() in ("1", "true", "yes", "y")
    elif deep_val is None:
        deep = True
    else:
        deep = True

    return {
        "url": url,
        "instructions": instructions,
        "maxPages": max_pages,
        "maxDepth": max_depth,
        "deep": deep,
    }


def _build_agent_browser_command(url: str, instructions: Optional[str]) -> str:
    """
    Build the agent-browser CLI command.

    Configuration:
      - AGENT_BROWSER_BIN: override the CLI name/path (default: 'agent-browser')
      - AGENT_BROWSER_EXTRA_ARGS: optional extra args, space-separated
    """
    bin_name = os.environ.get("AGENT_BROWSER_BIN", "agent-browser")

    # Core sequence: open the URL, then take a JSON snapshot of the page.
    base_cmd = f'{bin_name} open "{url}" && {bin_name} snapshot --json --compact'

    # Allow extra flags (e.g. --headed, --max-output) via env.
    extra = os.environ.get("AGENT_BROWSER_EXTRA_ARGS")
    if extra:
        base_cmd = f"{base_cmd} {extra}"

    return base_cmd


def _run_single_page(url: str) -> Tuple[bool, Optional[Dict[str, Any]], str, str]:
    """
    Run agent-browser for a single page and return:
      (ok, data, text, stderr)

    Does NOT emit any PROGRESS events; the caller (crawler) handles that.
    """
    cmd = _build_agent_browser_command(url, None)

    try:
        proc = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            shell=True,
        )
    except FileNotFoundError:
        text = (
            "agent-browser CLI not found.\n\n"
            "Set AGENT_BROWSER_BIN to the path of your agent-browser binary, "
            "or add it to PATH inside the Ikshan backend environment."
        )
        return False, None, text, ""
    except Exception as e:
        return False, None, f"Failed to invoke agent-browser: {e}", ""

    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()

    if proc.returncode != 0:
        text = (
            "agent-browser exited with a non-zero status.\n\n"
            f"Command: {cmd}\n\n"
            f"Stdout:\n{stdout}\n\nStderr:\n{stderr}"
        ).strip()
        return False, None, text, stderr

    # agent-browser prints a colored summary line + JSON; take the last
    # non-empty line and try to parse it as JSON.
    data: Optional[Any] = None
    lines = [ln for ln in stdout.splitlines() if ln.strip()]
    json_candidate = lines[-1] if lines else ""

    if json_candidate:
        try:
            data = json.loads(json_candidate)
        except Exception:
            # Not JSON; fall back to treating all stdout as plain text.
            data = None

    # Fallback: raw stdout as text.
    text = stdout or "agent-browser completed but produced no output."

    return True, data if isinstance(data, dict) else None, text, stderr


def _run_agent_browser(url: str, instructions: Optional[str]) -> Dict[str, Any]:
    """
    Run agent-browser and emit simple progress events compatible with the
    Ikshan skill progress protocol:

      PROGRESS:{"event":"started", ...}
      PROGRESS:{"event":"page", "url": "...", "status":"done", ...}
      PROGRESS:{"event":"done", ...}

    These lines are printed to stdout so the TS loader can forward them as
    ProgressEvent meta, just like the playwright/bs4 scrapers.
    """
    cmd = _build_agent_browser_command(url, instructions)

    try:
        proc = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            shell=True,
        )
    except FileNotFoundError:
        return {
            "status": "error",
            "text": (
                "agent-browser CLI not found.\n\n"
                "Set AGENT_BROWSER_BIN to the path of your agent-browser binary, "
                "or add it to PATH inside the Ikshan backend environment."
            ),
        }
    except Exception as e:
        return {
            "status": "error",
            "text": f"Failed to invoke agent-browser: {e}",
        }

    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()

    if proc.returncode != 0:
        # Emit a failure progress event so the UI can show context.
        err_meta = {
            "event": "page",
            "url": url,
            "status": "failed",
            "error": stderr or f"agent-browser exited with code {proc.returncode}",
        }
        print("PROGRESS:" + json.dumps(err_meta), flush=True)
        return {
            "status": "error",
            "text": (
                "agent-browser exited with a non-zero status.\n\n"
                f"Command: {cmd}\n\n"
                f"Stdout:\n{stdout}\n\nStderr:\n{stderr}"
            ).strip(),
        }

    # agent-browser prints a colored summary line + JSON; take the last
    # non-empty line and try to parse it as JSON.
    data: Optional[Any] = None
    text: str
    lines = [ln for ln in stdout.splitlines() if ln.strip()]
    json_candidate = lines[-1] if lines else ""

    if json_candidate:
        try:
            parsed = json.loads(json_candidate)
            data = parsed
        except Exception:
            # Not JSON; fall back to treating all stdout as plain text.
            data = None

    # Build a human-readable summary text.
    if isinstance(data, dict):
        origin = data.get("data", {}).get("origin") or data.get("origin") or url
        success = data.get("success", True)
        snapshot_str = data.get("data", {}).get("snapshot") or data.get("snapshot") or ""
        # Truncate very long snapshots for the main text; full content is in data.
        max_snapshot = 4000
        if len(snapshot_str) > max_snapshot:
            snapshot_str = snapshot_str[:max_snapshot] + "\n[... truncated ...]"
        status_str = "success" if success else "error"
        text_parts = [
            f"agent-browser snapshot for {origin} ({status_str}).",
        ]
        if instructions:
            text_parts.append(f"Instructions: {instructions}")
        if snapshot_str:
            text_parts.append("\nSnapshot:\n" + snapshot_str)
        text = "\n".join(text_parts).strip()
    else:
        # Fallback: raw stdout as text.
        text = stdout or "agent-browser completed but produced no output."

    if stderr:
        text = f"{text}\n\n[agent-browser stderr]\n{stderr}"

    # Emit progress events: started → page → done
    started_meta = {
        "event": "started",
        "url": url,
        "status": "running",
    }
    print("PROGRESS:" + json.dumps(started_meta), flush=True)

    page_meta = {
        "event": "page",
        "url": url,
        "status": "done",
        "length": len(text),
    }
    print("PROGRESS:" + json.dumps(page_meta), flush=True)

    done_meta = {
        "event": "done",
        "url": url,
        "status": "done",
    }
    print("PROGRESS:" + json.dumps(done_meta), flush=True)

    return {
        "status": "ok",
        "text": text,
        "data": data,
    }


def _discover_links(base_url: str, snapshot: str) -> List[str]:
    """
    Heuristic link discovery from the snapshot string.
    Extracts '/url: ...' entries and normalises them to absolute URLs,
    staying on the same domain as base_url.
    """
    urls: List[str] = []
    base = urlparse(base_url)
    for match in re.finditer(r"/url:\s+(\S+)", snapshot):
        href = match.group(1)
        if href.startswith("mailto:") or href.startswith("tel:"):
            continue
        abs_url = urljoin(base_url, href)
        parsed = urlparse(abs_url)
        if parsed.scheme not in ("http", "https"):
            continue
        if parsed.netloc and parsed.netloc != base.netloc:
            continue
        # Skip blog routes (prevent deep content crawl into blog section)
        path_lower = (parsed.path or "").lower()
        if "blog" in path_lower:
            continue
        urls.append(abs_url)
    return urls


def _crawl_agent_browser(
    start_url: str,
    instructions: Optional[str],
    max_pages: int,
    max_depth: int,
    deep: bool,
) -> Dict[str, Any]:
    """
    Multi-page crawl built on top of agent-browser, loosely mirroring the
    scrape-playwright semantics:

      - url: required start URL
      - maxPages: max number of pages to visit
      - maxDepth: max link depth from the start URL
      - deep: when false, only scrape the start URL

    Emits PROGRESS events similar to the Playwright scraper:

      PROGRESS:{"event":"started", "url": "..."}
      PROGRESS:{"event":"page", "url": "...", "status":"done"|"failed", ...}
      PROGRESS:{"event":"done", "url": "..."}
    """
    # Global "started" event.
    print(
        "PROGRESS:" + json.dumps({"event": "started", "url": start_url, "status": "running"}),
        flush=True,
    )

    seen = set([start_url])
    queue: Deque[Tuple[str, int]] = deque([(start_url, 0)])
    pages: List[Dict[str, Any]] = []
    base_url = start_url

    while queue and len(pages) < max_pages:
        url, depth = queue.popleft()

        ok, data, text, stderr = _run_single_page(url)
        if not ok or data is None:
            meta = {
                "event": "page",
                "url": url,
                "status": "failed",
                "error": stderr or text,
                "depth": depth,
            }
            print("PROGRESS:" + json.dumps(meta), flush=True)
            continue

        inner = data.get("data") or {}
        origin = inner.get("origin") or data.get("origin") or url
        snapshot_str = inner.get("snapshot") or data.get("snapshot") or ""
        refs = inner.get("refs") or data.get("refs") or {}

        if not pages:
            base_url = origin or url

        pages.append(
            {
                "url": origin or url,
                "snapshot": snapshot_str,
                "refs": refs,
                "depth": depth,
            }
        )

        # Emit page_data BEFORE marking the page as done so the UI doesn't show
        # "done" while content is still arriving.
        if snapshot_str:
            page_data_meta = {
                "event": "page_data",
                "url": origin or url,
                "body_text": snapshot_str,
            }
            print("PROGRESS:" + json.dumps(page_data_meta), flush=True)

        page_meta = {
            "event": "page",
            "url": origin or url,
            "status": "done",
            "depth": depth,
            "length": len(snapshot_str) if snapshot_str else len(text),
        }
        print("PROGRESS:" + json.dumps(page_meta), flush=True)

        # If not deep, still do link discovery from the FIRST page so callers can
        # see what URLs exist without scraping them.
        if (not deep) and depth == 0 and snapshot_str:
            discovered_urls = _discover_links(origin or url, snapshot_str)
            total = len(discovered_urls)
            for i, du in enumerate(discovered_urls, start=1):
                print(
                    "PROGRESS:"
                    + json.dumps({"event": "discovered", "url": du, "index": i, "total": total}),
                    flush=True,
                )
            print(
                "PROGRESS:" + json.dumps({"event": "discovery_done", "total_pages": total}),
                flush=True,
            )

        if deep and depth < max_depth and snapshot_str:
            for discovered in _discover_links(origin or url, snapshot_str):
                if discovered in seen or len(pages) + len(queue) >= max_pages:
                    continue
                seen.add(discovered)
                queue.append((discovered, depth + 1))

    # Final "done" event.
    print(
        "PROGRESS:"
        + json.dumps(
            {
                "event": "done",
                "url": base_url,
                "status": "done",
                "pages": len(pages),
            }
        ),
        flush=True,
    )

    n = len(pages)
    summary_lines = [
        f"agent-browser crawl for {base_url} — {n} page(s) scraped.",
    ]
    if instructions:
        summary_lines.append(f"Instructions: {instructions}")

    if pages:
        snap0 = pages[0].get("snapshot") or ""
        if snap0:
            max_preview = 1500
            if len(snap0) > max_preview:
                snap0 = snap0[:max_preview] + "\n[... truncated ...]"
            summary_lines.append("\nFirst page snapshot:\n" + snap0)

    text = "\n".join(summary_lines).strip()

    out_data = {
        "base_url": base_url,
        "pages": pages,
        "stats": {
            "total_pages": n,
            "max_depth": max_depth,
        },
    }

    # When not deep, also include a discovered URL list from the first page.
    if (not deep) and pages:
        try:
            snap0 = pages[0].get("snapshot") or ""
            if snap0:
                out_data["discovered_urls"] = _discover_links(base_url, snap0)
        except Exception:
            pass

    return {
        "text": text,
        "data": out_data,
    }


def main() -> None:
    payload = _load_payload()
    args = _extract_args(payload)
    url = args.get("url")
    instructions = args.get("instructions")
    max_pages = int(args.get("maxPages") or 9999)
    max_depth = int(args.get("maxDepth") or 10)
    deep = bool(args.get("deep"))

    if not url:
        out: Dict[str, Any] = {
            "text": "scrape-agentbrowser: url is required but was not provided.",
            "error": "missing_url",
        }
        print(json.dumps(out))
        return

    result = _crawl_agent_browser(url, instructions, max_pages, max_depth, deep)
    print(json.dumps(result))


if __name__ == "__main__":
    main()

