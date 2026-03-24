import React from 'react';
import type { TokenUsage, TokenUsageEntry } from '../../types';

/** USD per token (input / output). */
export const MODEL_PRICING: Record<string, { input: number; output: number }> = {
  'gpt-4.1': {
    input: 5 / 1_000_000,
    output: 15 / 1_000_000,
  },
  'claude-opus-4-6': {
    input: 15 / 1_000_000,
    output: 75 / 1_000_000,
  },
};

const USD_TO_INR = 94;

function getPricingForModel(model: string): { input: number; output: number } | null {
  const m = (model || '').trim();
  if (!m) return null;
  if (MODEL_PRICING[m]) return MODEL_PRICING[m];
  const lower = m.toLowerCase();
  for (const key of Object.keys(MODEL_PRICING)) {
    if (lower === key.toLowerCase() || lower.includes(key.toLowerCase())) {
      return MODEL_PRICING[key];
    }
  }
  if (lower.includes('gpt-4.1')) return MODEL_PRICING['gpt-4.1'];
  if (lower.includes('claude-opus-4-6') || lower.includes('opus-4-6')) {
    return MODEL_PRICING['claude-opus-4-6'];
  }
  return null;
}

type ModelAggregate = {
  model: string;
  inputTokens: number;
  outputTokens: number;
};

function aggregateByModel(entries: TokenUsageEntry[]): ModelAggregate[] {
  const map = new Map<string, { in: number; out: number }>();
  for (const e of entries) {
    const key = (e.model || 'unknown').trim() || 'unknown';
    const cur = map.get(key) ?? { in: 0, out: 0 };
    cur.in += Number(e.inputTokens) || 0;
    cur.out += Number(e.outputTokens) || 0;
    map.set(key, cur);
  }
  return Array.from(map.entries())
    .map(([model, v]) => ({
      model,
      inputTokens: v.in,
      outputTokens: v.out,
    }))
    .sort((a, b) => a.model.localeCompare(b.model));
}

export type LiveTokenEstimate = {
  outputChars: number;
  outputTokensEstimated: number;
};

export default function TokenUsagePanel({
  messageId,
  tokenUsage,
  usageLoading,
  liveTokenEstimate,
}: {
  messageId?: string;
  tokenUsage: TokenUsage | null;
  usageLoading: boolean;
  liveTokenEstimate: LiveTokenEstimate | null;
}) {
  const entries = tokenUsage?.entries ?? [];
  const byModel = aggregateByModel(entries);

  const modelCosts = byModel.map((row) => {
    const rates = getPricingForModel(row.model);
    const costUsd =
      rates != null
        ? row.inputTokens * rates.input + row.outputTokens * rates.output
        : null;
    const totalTokens = row.inputTokens + row.outputTokens;
    return { ...row, totalTokens, costUsd };
  });

  const totalUsd = modelCosts.reduce((s, r) => s + (r.costUsd ?? 0), 0);
  const hasUnknownPricing = modelCosts.some((r) => r.costUsd == null);
  const totalInr = totalUsd * USD_TO_INR;

  return (
    <div>
      <h3 className="text-sm font-semibold mb-2">Token usage</h3>
      {messageId ? (
        usageLoading ? (
          <p className="text-xs text-slate-500">Loading token usage…</p>
        ) : tokenUsage ? (
          <div className="space-y-3">
            <div className="border rounded-lg overflow-hidden">
              <div className="px-3 py-2 text-xs font-semibold flex items-center justify-between bg-slate-50">
                <span>Total</span>
                <span className="text-[11px] text-slate-600">
                  {tokenUsage.totalInputTokens.toLocaleString()} in /{' '}
                  {tokenUsage.totalOutputTokens.toLocaleString()} out
                </span>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-[11px] border-collapse">
                  <thead className="bg-white">
                    <tr>
                      <th className="text-left px-2 py-1 border">Stage</th>
                      <th className="text-left px-2 py-1 border">Provider</th>
                      <th className="text-left px-2 py-1 border">Model</th>
                      <th className="text-right px-2 py-1 border">In</th>
                      <th className="text-right px-2 py-1 border">Out</th>
                    </tr>
                  </thead>
                  <tbody>
                    {entries.map((r, i) => (
                      <tr key={i} className="hover:bg-slate-50">
                        <td className="px-2 py-1 border">{r.stage}</td>
                        <td className="px-2 py-1 border">{r.provider}</td>
                        <td className="px-2 py-1 border">{r.model}</td>
                        <td className="px-2 py-1 border text-right">
                          {r.inputTokens.toLocaleString()}
                        </td>
                        <td className="px-2 py-1 border text-right">
                          {r.outputTokens.toLocaleString()}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="border rounded-lg overflow-hidden">
              <div className="px-3 py-2 text-xs font-semibold bg-slate-50 border-b">
                Cost by model (USD × {USD_TO_INR} = INR)
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-[11px] border-collapse">
                  <thead className="bg-white">
                    <tr>
                      <th className="text-left px-2 py-1 border">Model</th>
                      <th className="text-right px-2 py-1 border">In</th>
                      <th className="text-right px-2 py-1 border">Out</th>
                      <th className="text-right px-2 py-1 border">Total tokens</th>
                      <th className="text-right px-2 py-1 border">USD</th>
                      <th className="text-right px-2 py-1 border">INR (×{USD_TO_INR})</th>
                    </tr>
                  </thead>
                  <tbody>
                    {modelCosts.map((r) => (
                      <tr key={r.model} className="hover:bg-slate-50">
                        <td className="px-2 py-1 border font-mono text-[10px]">{r.model}</td>
                        <td className="px-2 py-1 border text-right">
                          {r.inputTokens.toLocaleString()}
                        </td>
                        <td className="px-2 py-1 border text-right">
                          {r.outputTokens.toLocaleString()}
                        </td>
                        <td className="px-2 py-1 border text-right">
                          {r.totalTokens.toLocaleString()}
                        </td>
                        <td className="px-2 py-1 border text-right">
                          {r.costUsd != null ? `$${r.costUsd.toFixed(4)}` : '—'}
                        </td>
                        <td className="px-2 py-1 border text-right">
                          {r.costUsd != null
                            ? `₹${(r.costUsd * USD_TO_INR).toFixed(2)}`
                            : '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                  <tfoot className="bg-slate-50 font-semibold">
                    <tr>
                      <td className="px-2 py-1 border" colSpan={4}>
                        Sum (priced models only)
                        {hasUnknownPricing && (
                          <span className="font-normal text-slate-500 ml-1">
                            — excludes models without a rate
                          </span>
                        )}
                      </td>
                      <td className="px-2 py-1 border text-right">${totalUsd.toFixed(4)}</td>
                      <td className="px-2 py-1 border text-right">
                        ₹{totalInr.toFixed(2)}
                      </td>
                    </tr>
                  </tfoot>
                </table>
              </div>
            </div>
          </div>
        ) : (
          <p className="text-xs text-slate-500">No token usage recorded.</p>
        )
      ) : liveTokenEstimate ? (
        <div className="border rounded-lg overflow-hidden">
          <div className="px-3 py-2 text-xs font-semibold flex items-center justify-between bg-slate-50">
            <span>Live estimate</span>
            <span className="text-[11px] text-slate-600">
              ~{liveTokenEstimate.outputTokensEstimated.toLocaleString()} out
            </span>
          </div>
          <div className="px-3 py-2 text-[11px] text-slate-600">
            Output chars streamed: {liveTokenEstimate.outputChars.toLocaleString()}
          </div>
        </div>
      ) : (
        <p className="text-xs text-slate-500">Token usage appears after the run completes.</p>
      )}
    </div>
  );
}
