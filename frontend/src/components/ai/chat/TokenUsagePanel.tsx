import React from 'react';
import type { TokenUsage, TokenUsageEntry } from '../../../api/types';

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
      <h3 className="text-sm font-semibold mb-2 text-slate-100">Token usage</h3>
      {messageId ? (
        usageLoading ? (
          <p className="text-xs text-slate-500">Loading token usage…</p>
        ) : tokenUsage ? (
          <div className="space-y-3">
            <div className="border border-slate-700 rounded-lg overflow-hidden bg-slate-900">
              <div className="px-3 py-2 text-xs font-semibold text-slate-100 flex items-center justify-between bg-slate-800 border-b border-slate-700">
                <span>Total</span>
                <span className="text-[11px] text-slate-300">
                  {tokenUsage.totalInputTokens.toLocaleString()} in /{' '}
                  {tokenUsage.totalOutputTokens.toLocaleString()} out
                </span>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-[11px] border-collapse">
                  <thead className="bg-slate-800 text-slate-200">
                    <tr>
                      <th className="text-left px-2 py-1 border border-slate-700">Stage</th>
                      <th className="text-left px-2 py-1 border border-slate-700">Provider</th>
                      <th className="text-left px-2 py-1 border border-slate-700">Model</th>
                      <th className="text-right px-2 py-1 border border-slate-700">In</th>
                      <th className="text-right px-2 py-1 border border-slate-700">Out</th>
                    </tr>
                  </thead>
                  <tbody>
                    {entries.map((r, i) => (
                      <tr key={i} className="text-slate-100 hover:bg-slate-800/60">
                        <td className="px-2 py-1 border border-slate-700">{r.stage}</td>
                        <td className="px-2 py-1 border border-slate-700">{r.provider}</td>
                        <td className="px-2 py-1 border border-slate-700">{r.model}</td>
                        <td className="px-2 py-1 border border-slate-700 text-right">
                          {r.inputTokens.toLocaleString()}
                        </td>
                        <td className="px-2 py-1 border border-slate-700 text-right">
                          {r.outputTokens.toLocaleString()}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="border border-slate-700 rounded-lg overflow-hidden bg-slate-900">
              <div className="px-3 py-2 text-xs text-slate-100 font-semibold bg-slate-800 border-b border-slate-700">
                Cost by model (USD × {USD_TO_INR} = INR)
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-[11px] border-collapse">
                  <thead className="bg-slate-800 text-slate-200">
                    <tr>
                      <th className="text-left px-2 py-1 border border-slate-700">Model</th>
                      <th className="text-right px-2 py-1 border border-slate-700">In</th>
                      <th className="text-right px-2 py-1 border border-slate-700">Out</th>
                      <th className="text-right px-2 py-1 border border-slate-700">Total tokens</th>
                      <th className="text-right px-2 py-1 border border-slate-700">USD</th>
                      <th className="text-right px-2 py-1 border border-slate-700">INR (×{USD_TO_INR})</th>
                    </tr>
                  </thead>
                  <tbody>
                    {modelCosts.map((r) => (
                      <tr key={r.model} className="text-slate-100 hover:bg-slate-800/60">
                        <td className="px-2 py-1 border border-slate-700 font-mono text-[10px]">{r.model}</td>
                        <td className="px-2 py-1 border border-slate-700 text-right">
                          {r.inputTokens.toLocaleString()}
                        </td>
                        <td className="px-2 py-1 border border-slate-700 text-right">
                          {r.outputTokens.toLocaleString()}
                        </td>
                        <td className="px-2 py-1 border border-slate-700 text-right">
                          {r.totalTokens.toLocaleString()}
                        </td>
                        <td className="px-2 py-1 border border-slate-700 text-right">
                          {r.costUsd != null ? `$${r.costUsd.toFixed(4)}` : '—'}
                        </td>
                        <td className="px-2 py-1 border border-slate-700 text-right">
                          {r.costUsd != null
                            ? `₹${(r.costUsd * USD_TO_INR).toFixed(2)}`
                            : '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                  <tfoot className="bg-slate-800 text-slate-100 font-semibold">
                    <tr>
                      <td className="px-2 py-1 border border-slate-700" colSpan={4}>
                        Sum (priced models only)
                        {hasUnknownPricing && (
                          <span className="font-normal text-slate-500 ml-1">
                            — excludes models without a rate
                          </span>
                        )}
                      </td>
                      <td className="px-2 py-1 border border-slate-700 text-right">${totalUsd.toFixed(4)}</td>
                      <td className="px-2 py-1 border border-slate-700 text-right">
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
        <div className="border border-slate-700 rounded-lg overflow-hidden bg-slate-900">
          <div className="px-3 py-2 text-xs text-slate-100 font-semibold flex items-center justify-between bg-slate-800 border-b border-slate-700">
            <span>Live estimate</span>
            <span className="text-[11px] text-slate-300">
              ~{liveTokenEstimate.outputTokensEstimated.toLocaleString()} out
            </span>
          </div>
          <div className="px-3 py-2 text-[11px] text-slate-300">
            Output chars streamed: {liveTokenEstimate.outputChars.toLocaleString()}
          </div>
        </div>
      ) : (
        <p className="text-xs text-slate-500">Token usage appears after the run completes.</p>
      )}
    </div>
  );
}
