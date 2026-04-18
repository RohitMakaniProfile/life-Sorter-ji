"""HTML text extraction and DOM element parsing (sync and async Playwright pages)."""

import re

_ELEMENTS_EVAL_JS = """
(maxItems) => {
  const out = [];
  const nodes = document.querySelectorAll('h1,h2,h3,p,li,img[alt]');
  for (const node of nodes) {
    if (out.length >= (maxItems || 500)) break;
    const tag = (node.tagName || '').toLowerCase();
    let type = tag;
    let content = '';
    if (tag === 'img') {
      type = 'img_alt';
      content = (node.getAttribute('alt') || '').trim();
    } else {
      content = (node.innerText || node.textContent || '').replace(/\\s+/g, ' ').trim();
    }
    if (!content) continue;
    out.push({ type, content });
  }
  return out;
}
"""


def extract_text_from_html(html: str) -> str:
    html = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", html, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", text).strip()[:50000]


def extract_content_elements(html: str, max_items: int = 500) -> list[dict]:
    """Regex fallback: extracts typed elements in approximate DOM order."""
    html = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", html, flags=re.I | re.S)
    token_re = re.compile(
        r"(?is)"
        r"(<h[1-3][^>]*>.*?</h[1-3]>)|"
        r"(<p[^>]*>.*?</p>)|"
        r"(<li[^>]*>.*?</li>)|"
        r"(<img[^>]*alt=[\"'][^\"']+[\"'][^>]*>)"
    )
    out: list[dict] = []
    for m in token_re.finditer(html):
        token = m.group(0)
        if not token:
            continue
        low = token.lower()
        if low.startswith("<img"):
            am = re.search(r'(?is)alt=["\']([^"\']+)["\']', token)
            val = re.sub(r"\s+", " ", (am.group(1) if am else "")).strip()
            if val:
                out.append({"type": "img_alt", "content": val})
        else:
            text = re.sub(r"<[^>]+>", " ", token)
            text = re.sub(r"\s+", " ", text).strip()
            if text:
                tag = "text"
                if low.startswith("<h1"):
                    tag = "h1"
                elif low.startswith("<h2"):
                    tag = "h2"
                elif low.startswith("<h3"):
                    tag = "h3"
                elif low.startswith("<p"):
                    tag = "p"
                elif low.startswith("<li"):
                    tag = "li"
                out.append({"type": tag, "content": text})
        if len(out) >= max_items:
            break
    return out


def extract_content_elements_from_page(page, html: str, max_items: int = 500) -> list[dict]:
    """Primary extractor: ordered DOM traversal via sync Playwright evaluate."""
    try:
        data = page.evaluate(_ELEMENTS_EVAL_JS, max_items)
        if isinstance(data, list):
            cleaned: list[dict] = []
            for item in data:
                if not isinstance(item, dict):
                    continue
                t = str(item.get("type") or "").strip().lower()
                c = re.sub(r"\s+", " ", str(item.get("content") or "")).strip()
                if not t or not c:
                    continue
                cleaned.append({"type": t, "content": c})
                if len(cleaned) >= max_items:
                    break
            if cleaned:
                return cleaned
    except Exception:
        pass
    return extract_content_elements(html, max_items=max_items)