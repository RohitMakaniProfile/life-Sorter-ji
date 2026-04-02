/** Shape tool rows from JSON for `UrlStage` / early tools carousel. */
export function mapToolsToEarlyTools(tools) {
  if (!tools?.length) return [];
  return tools.map((t) => {
    const rawDesc = t.best_use_case || t.description || '';
    const desc = rawDesc.length > 120 ? `${rawDesc.slice(0, 117)}...` : rawDesc;
    let bullets = [];
    if (t.key_pros) {
      const raw = Array.isArray(t.key_pros)
        ? t.key_pros
        : t.key_pros
            .split('\n')
            .map((s) => s.replace(/^[•\-\s]+/, '').trim())
            .filter(Boolean);
      bullets = raw.slice(0, 3).map((b) => (b.length > 70 ? `${b.slice(0, 67)}...` : b));
    }
    return {
      name: t.name,
      rating: t.rating || null,
      description: desc,
      bullets,
      tag: t.category || 'RECOMMENDED',
      url: t.url,
    };
  });
}
