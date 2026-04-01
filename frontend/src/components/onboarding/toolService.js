import toolsData from './data/tools_by_q1_q2_q3.json';

/**
 * Look up tools for a given Q1 outcome, Q2 domain, Q3 task.
 * Uses exact match first, then falls back to domain-level aggregation.
 * Returns { tools, matchType }.
 */
export function getToolsForSelection(outcomeId, domain, task, limit = 10) {
  const outcomeData = toolsData[outcomeId];
  if (!outcomeData) return { tools: [], matchType: 'none' };

  const domainData = outcomeData[domain];
  if (!domainData) return { tools: [], matchType: 'none' };

  // Exact task match
  if (domainData[task]) {
    return {
      tools: domainData[task].slice(0, limit),
      matchType: 'exact',
    };
  }

  // Case-insensitive fuzzy task match
  const taskLower = task.toLowerCase();
  for (const key of Object.keys(domainData)) {
    if (key.toLowerCase() === taskLower) {
      return {
        tools: domainData[key].slice(0, limit),
        matchType: 'fuzzy_task',
      };
    }
  }

  // Domain fallback: aggregate top tools across all tasks in this domain
  const allTools = [];
  const seen = new Set();
  for (const taskTools of Object.values(domainData)) {
    for (const tool of taskTools) {
      if (!seen.has(tool.name)) {
        seen.add(tool.name);
        allTools.push(tool);
      }
    }
  }
  allTools.sort((a, b) => (b.composite_score || 0) - (a.composite_score || 0));
  return {
    tools: allTools.slice(0, limit),
    matchType: 'domain_fallback',
  };
}
