from __future__ import annotations

from app.constants import MODEL_PRICING_USD_PER_TOKEN, USD_TO_INR


def _pricing_for_model(model_name: str) -> tuple[float, float] | None:
    name = (model_name or "").strip().lower()
    if not name:
        return None
    if name in MODEL_PRICING_USD_PER_TOKEN:
        return MODEL_PRICING_USD_PER_TOKEN[name]
    for key, val in MODEL_PRICING_USD_PER_TOKEN.items():
        if key in name:
            return val
    return None


def _compute_cost_usd_inr(model_name: str, input_tokens: int, output_tokens: int) -> tuple[float | None, float | None]:
    pricing = _pricing_for_model(model_name)
    if not pricing:
        return None, None
    in_rate, out_rate = pricing
    usd = (max(0, int(input_tokens)) * in_rate) + (max(0, int(output_tokens)) * out_rate)
    return round(usd, 6), round(usd * USD_TO_INR, 2)
