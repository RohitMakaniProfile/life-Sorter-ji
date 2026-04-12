from __future__ import annotations

import argparse
import asyncio
from decimal import Decimal
from typing import Iterable

from app.db import close_db, connect_db, get_pool
from app.doable_claw_agent.stores import _decode_token_usage_model
from app.utils.token_cost import _compute_cost_usd_inr
from app.constants import USD_TO_INR


def _as_int(value: object) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def _as_float(value: object) -> float:
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value or 0)
    except Exception:
        return 0.0


def _parse_overrides(items: Iterable[str]) -> dict[str, tuple[float, float]]:
    """
    Parse --rate values with format:
      model=input_usd_per_million,output_usd_per_million
    Example:
      --rate "z-ai/glm-5=0.8,2.4"
    """
    out: dict[str, tuple[float, float]] = {}
    for raw in items:
        entry = str(raw or "").strip()
        if not entry or "=" not in entry:
            continue
        model, rates = entry.split("=", 1)
        if "," not in rates:
            continue
        in_m, out_m = rates.split(",", 1)
        try:
            in_rate = float(in_m.strip()) / 1_000_000
            out_rate = float(out_m.strip()) / 1_000_000
        except Exception:
            continue
        key = model.strip().lower()
        if key:
            out[key] = (in_rate, out_rate)
    return out


def _compute_with_override(
    model_name: str,
    input_tokens: int,
    output_tokens: int,
    overrides: dict[str, tuple[float, float]],
) -> tuple[float | None, float | None]:
    usd, inr = _compute_cost_usd_inr(model_name, input_tokens, output_tokens)
    if usd is not None and inr is not None:
        return usd, inr
    key = (model_name or "").strip().lower()
    if not key:
        return None, None
    match = overrides.get(key)
    if not match:
        # Also allow partial key match for vendor-prefixed names.
        for k, rates in overrides.items():
            if k in key:
                match = rates
                break
    if not match:
        return None, None
    in_rate, out_rate = match
    usd = (max(0, int(input_tokens)) * in_rate) + (max(0, int(output_tokens)) * out_rate)
    return round(usd, 6), round(usd * USD_TO_INR, 2)


async def run(*, apply: bool, limit: int, overrides: dict[str, tuple[float, float]]) -> None:
    await connect_db()
    pool = get_pool()
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, model, model_name, input_tokens, output_tokens "
                "FROM token_usage "
                "WHERE cost_inr IS NULL "
                "ORDER BY id ASC "
                "LIMIT $1",
                limit,
            )

        known_updates: list[tuple[float, float, int]] = []
        unknown_count = 0
        total_rows = len(rows)
        estimate_inr = 0.0

        unknown_models: dict[str, int] = {}
        for r in rows:
            model_name = str(r.get("model_name") or "").strip()
            if not model_name:
                decoded = _decode_token_usage_model(str(r.get("model") or ""))
                model_name = str(decoded.get("model") or "").strip()

            cost_usd, cost_inr = _compute_with_override(
                model_name,
                _as_int(r.get("input_tokens")),
                _as_int(r.get("output_tokens")),
                overrides,
            )
            if cost_usd is None or cost_inr is None:
                unknown_count += 1
                unknown_models[model_name or "unknown"] = unknown_models.get(model_name or "unknown", 0) + 1
                continue

            estimate_inr += _as_float(cost_inr)
            known_updates.append((cost_usd, cost_inr, int(r["id"])))

        print(f"Scanned rows: {total_rows}")
        print(f"Known priced rows: {len(known_updates)}")
        print(f"Unknown model rows (still NULL): {unknown_count}")
        print(f"Estimated INR fill: {estimate_inr:.2f}")
        if unknown_models:
            print("Unknown models:")
            for name, cnt in sorted(unknown_models.items(), key=lambda x: (-x[1], x[0])):
                print(f"  - {name}: {cnt}")

        if not apply:
            print("Dry run only. Re-run with --apply to persist updates.")
            return

        if not known_updates:
            print("No rows to update.")
            return

        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.executemany(
                    "UPDATE token_usage SET cost_usd = $1, cost_inr = $2 WHERE id = $3 AND cost_inr IS NULL",
                    known_updates,
                )
        print(f"Updated rows: {len(known_updates)}")
    finally:
        await close_db()


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill token_usage cost_usd/cost_inr for NULL-cost rows.")
    parser.add_argument("--apply", action="store_true", help="Persist updates. Default is dry-run.")
    parser.add_argument("--limit", type=int, default=50000, help="Max NULL-cost rows to scan.")
    parser.add_argument(
        "--rate",
        action="append",
        default=[],
        help="Custom pricing override: model=input_usd_per_million,output_usd_per_million (repeatable).",
    )
    args = parser.parse_args()
    overrides = _parse_overrides(args.rate or [])
    if overrides:
        print(f"Loaded custom pricing overrides: {len(overrides)}")
    asyncio.run(run(apply=bool(args.apply), limit=max(1, int(args.limit)), overrides=overrides))


if __name__ == "__main__":
    main()
