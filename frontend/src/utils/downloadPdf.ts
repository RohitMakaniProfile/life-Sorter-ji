/**
 * Opens a styled print window from markdown text so the user can
 * save it as a PDF via the browser's native Print → Save as PDF.
 *
 * Uses marked (if available) or a lightweight inline renderer to
 * convert the markdown to HTML before printing.
 */

function markdownToHtml(md: string): string {
  return md
    // Headings
    .replace(/^#{6}\s+(.+)$/gm, '<h6>$1</h6>')
    .replace(/^#{5}\s+(.+)$/gm, '<h5>$1</h5>')
    .replace(/^#{4}\s+(.+)$/gm, '<h4>$1</h4>')
    .replace(/^#{3}\s+(.+)$/gm, '<h3>$1</h3>')
    .replace(/^#{2}\s+(.+)$/gm, '<h2>$1</h2>')
    .replace(/^#{1}\s+(.+)$/gm, '<h1>$1</h1>')
    // Bold / italic
    .replace(/\*\*\*(.+?)\*\*\*/g, '<strong><em>$1</em></strong>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    // Inline code
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    // Horizontal rule
    .replace(/^---+$/gm, '<hr>')
    // GFM tables — convert | col | col | rows
    .replace(
      /(\|.+\|\n)((?:\|[-:| ]+\|\n))((?:\|.+\|\n?)*)/gm,
      (_, header, _sep, body) => {
        const parseRow = (row: string, tag: string) =>
          '<tr>' +
          row
            .split('|')
            .slice(1, -1)
            .map((c) => `<${tag}>${c.trim()}</${tag}>`)
            .join('') +
          '</tr>';
        const headerHtml = parseRow(header.trim(), 'th');
        const bodyHtml = body
          .trim()
          .split('\n')
          .filter(Boolean)
          .map((r: string) => parseRow(r, 'td'))
          .join('');
        return `<table><thead>${headerHtml}</thead><tbody>${bodyHtml}</tbody></table>`;
      }
    )
    // Unordered lists
    .replace(/^[\-\*]\s+(.+)$/gm, '<li>$1</li>')
    .replace(/(<li>.*<\/li>\n?)+/g, (m) => `<ul>${m}</ul>`)
    // Ordered lists
    .replace(/^\d+\.\s+(.+)$/gm, '<li>$1</li>')
    // Blockquote
    .replace(/^>\s+(.+)$/gm, '<blockquote>$1</blockquote>')
    // Paragraphs — wrap lines that aren't already wrapped in a block tag
    .replace(/^(?!<[a-z]).+$/gm, (line) => (line.trim() ? `<p>${line}</p>` : ''))
    // Clean up blank lines
    .replace(/\n{3,}/g, '\n\n');
}

export function downloadReportAsPdf(markdownContent: string, companyName = 'Business Strategy Report') {
  const html = markdownToHtml(markdownContent);
  const today = new Date().toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' });

  const printWindow = window.open('', '_blank', 'width=900,height=700');
  if (!printWindow) {
    alert('Pop-up blocked. Please allow pop-ups for this site and try again.');
    return;
  }

  printWindow.document.write(`<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <title>${companyName}</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

    body {
      font-family: 'Georgia', serif;
      font-size: 11pt;
      line-height: 1.65;
      color: #1a1a2e;
      background: #fff;
      padding: 0;
    }

    .cover {
      display: flex;
      flex-direction: column;
      justify-content: center;
      align-items: flex-start;
      min-height: 100vh;
      padding: 80px 72px;
      background: linear-gradient(135deg, #1e1b4b 0%, #312e81 60%, #4c1d95 100%);
      color: white;
      page-break-after: always;
    }
    .cover-label {
      font-size: 9pt;
      letter-spacing: 0.2em;
      text-transform: uppercase;
      color: #a5b4fc;
      margin-bottom: 24px;
      font-family: 'Arial', sans-serif;
    }
    .cover-title {
      font-size: 32pt;
      font-weight: bold;
      line-height: 1.2;
      margin-bottom: 16px;
      color: #fff;
    }
    .cover-subtitle {
      font-size: 13pt;
      color: #c7d2fe;
      margin-bottom: 48px;
    }
    .cover-date {
      font-size: 9pt;
      color: #818cf8;
      font-family: 'Arial', sans-serif;
      border-top: 1px solid rgba(255,255,255,0.2);
      padding-top: 16px;
      width: 100%;
    }

    .content {
      padding: 56px 72px;
      max-width: 800px;
      margin: 0 auto;
    }

    h1 {
      font-size: 20pt;
      color: #1e1b4b;
      margin: 40px 0 12px;
      padding-bottom: 8px;
      border-bottom: 2px solid #e0e7ff;
      page-break-after: avoid;
    }
    h2 {
      font-size: 14pt;
      color: #312e81;
      margin: 28px 0 8px;
      page-break-after: avoid;
    }
    h3 {
      font-size: 11pt;
      color: #4c1d95;
      font-weight: bold;
      margin: 20px 0 6px;
      page-break-after: avoid;
    }
    h4, h5, h6 {
      font-size: 10pt;
      color: #5b21b6;
      margin: 16px 0 4px;
    }

    p { margin: 0 0 10px; }

    ul, ol {
      margin: 6px 0 12px 24px;
    }
    li { margin-bottom: 4px; }

    table {
      width: 100%;
      border-collapse: collapse;
      margin: 16px 0 20px;
      font-size: 9.5pt;
      page-break-inside: avoid;
    }
    thead { background: #ede9fe; }
    th {
      padding: 8px 12px;
      text-align: left;
      font-weight: bold;
      color: #3730a3;
      border: 1px solid #c4b5fd;
      font-size: 8.5pt;
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }
    td {
      padding: 7px 12px;
      border: 1px solid #e0e7ff;
      vertical-align: top;
    }
    tr:nth-child(even) td { background: #f5f3ff; }

    code {
      background: #f1f5f9;
      padding: 1px 5px;
      border-radius: 3px;
      font-family: 'Courier New', monospace;
      font-size: 9pt;
      color: #5b21b6;
    }

    blockquote {
      border-left: 3px solid #818cf8;
      padding: 4px 16px;
      color: #64748b;
      margin: 12px 0;
      font-style: italic;
    }

    hr {
      border: none;
      border-top: 1px solid #e0e7ff;
      margin: 28px 0;
    }

    strong { color: #1e1b4b; }

    @media print {
      body { print-color-adjust: exact; -webkit-print-color-adjust: exact; }
      .cover { min-height: 100vh; }
      h1, h2, h3 { page-break-after: avoid; }
      table { page-break-inside: avoid; }
      .no-print { display: none; }
    }
  </style>
</head>
<body>

  <!-- Cover page -->
  <div class="cover">
    <div class="cover-label">Business Strategy Report · Ikshan AI</div>
    <div class="cover-title">${companyName}</div>
    <div class="cover-subtitle">AI-Powered Website Audit & Market Intelligence</div>
    <div class="cover-date">Generated on ${today} &nbsp;·&nbsp; Confidential</div>
  </div>

  <!-- Report content -->
  <div class="content">
    ${html}
  </div>

  <!-- Print trigger -->
  <script>
    window.onload = function() {
      setTimeout(function() { window.print(); }, 400);
    };
  </script>
</body>
</html>`);

  printWindow.document.close();
}
