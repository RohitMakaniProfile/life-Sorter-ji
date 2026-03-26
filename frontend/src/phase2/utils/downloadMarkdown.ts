function slugify(name: string): string {
  const raw = String(name || '').trim().toLowerCase();
  const slug = raw
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/(^-|-$)+/g, '')
    .slice(0, 80);
  return slug || 'ikshan-report';
}

export function downloadMarkdownAsFile(markdown: string, filenameBase = 'ikshan-report'): void {
  const safeBase = slugify(filenameBase);
  const ts = new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-'); // YYYY-MM-DD-HH-MM-SS
  const filename = `${safeBase}-${ts}.md`;

  const blob = new Blob([String(markdown ?? '')], { type: 'text/markdown;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  try {
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.rel = 'noopener';
    document.body.appendChild(a);
    a.click();
    a.remove();
  } finally {
    URL.revokeObjectURL(url);
  }
}

