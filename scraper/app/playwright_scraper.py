#!/usr/bin/env python3
"""
CLI entry point for the Playwright website crawler.

Reads crawl arguments, delegates to crawler.crawl_with_playwright,
and writes the result JSON to stdout (or a file if --output is given).
Progress events are emitted to stderr as one JSON object per line.
"""

import argparse
import json
import sys

try:
    from playwright.sync_api import sync_playwright  # noqa: F401
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False

from crawler import crawl_with_playwright


def main():
    parser = argparse.ArgumentParser(description="Playwright recursive website crawler")
    parser.add_argument("--url", required=True)
    parser.add_argument("--output", default=None)
    parser.add_argument("--max-pages", type=int, default=100)
    parser.add_argument("--max-depth", type=int, default=3)
    parser.add_argument("--deep", action="store_true")
    parser.add_argument("--parallel", action="store_true", default=True)
    parser.add_argument("--no-parallel", action="store_false", dest="parallel")
    parser.add_argument("--max-parallel-pages", type=int, default=1)
    parser.add_argument("--no-robots", action="store_true")
    parser.add_argument("--no-headless", action="store_true")
    parser.add_argument(
        "--job-json",
        default=None,
        help="JSON file with resumeCheckpoint and skipUrls for crawl resume",
    )
    args = parser.parse_args()

    if not HAS_PLAYWRIGHT:
        print(json.dumps({"error": "playwright_not_installed"}), flush=True)
        return

    job: dict = {}
    if args.job_json:
        try:
            with open(args.job_json, encoding="utf-8") as jf:
                job = json.load(jf)
            if not isinstance(job, dict):
                job = {}
        except Exception:
            job = {}

    resume_ck = job.get("resumeCheckpoint") if isinstance(job.get("resumeCheckpoint"), dict) else None
    skip_list = job.get("skipUrls") if isinstance(job.get("skipUrls"), list) else None

    result = crawl_with_playwright(
        args.url,
        args.max_pages,
        args.max_depth,
        respect_robots=not args.no_robots,
        headless=not args.no_headless,
        deep=args.deep,
        parallel=getattr(args, "parallel", False),
        resume_checkpoint=resume_ck,
        skip_urls=[str(u) for u in skip_list] if skip_list else None,
        max_parallel_pages=args.max_parallel_pages,
    )

    if args.output:
        with open(args.output, "w") as f:
            json.dump(result, f, indent=2)
    else:
        print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()