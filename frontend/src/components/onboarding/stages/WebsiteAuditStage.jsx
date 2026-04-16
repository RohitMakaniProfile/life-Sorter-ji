import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

const formatSectionMarkdown = (text) => {
  let r = text;
  r = r.replace(/^\*\*([A-Z][A-Z &\-\/():'0-9,.]+?)\*\*\s*$/gm, (_, l) => `### ${l.trim()}`);
  r = r.replace(/^(?![#>|*\-])([A-Z][A-Z &\-\/():'0-9,.]{7,})\s*$/gm, (_, l) => `### ${l.trim()}`);
  return r;
};

const parseOverallScore = (audit) => {
  const m = audit.match(/\*\*Overall(?:\s+Score)?:\s*(\d+(?:\.\d+)?)\/10\*\*/i);
  return m ? parseFloat(m[1]) : null;
};

const scoreColor = (score) => {
  if (score >= 7) return '#16a34a';
  if (score >= 5) return '#d97706';
  return '#dc2626';
};

const T = {
  panelBg: '#0f172a',
  border: '#23314a',
  primaryText: '#f8fafc',
  secondaryText: '#d1d5db',
  mutedText: '#94a3b8',
  shadow: '0 1px 3px rgba(2, 8, 23, 0.55)',
};

export default function WebsiteAuditStage({ auditText, loading, onContinue }) {
  const overallScore = !loading && auditText ? parseOverallScore(auditText) : null;

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
      <div className="min-h-0 flex-1 overflow-y-auto px-5 pb-6 [scrollbar-color:rgba(255,255,255,0.08)_transparent] [scrollbar-width:thin]">
        <div style={{ maxWidth: 720, margin: '0 auto' }}>
          {loading && !auditText ? (
            <div className="flex flex-col items-center justify-center py-20 gap-4">
              <div className="h-10 w-10 animate-spin rounded-full border-2 border-white/20 border-t-violet-500" />
              <p className="text-sm text-white/50">Analysing your website…</p>
            </div>
          ) : auditText ? (
            <div style={{ fontFamily: 'inherit' }}>
              {/* Overall score badge — only shown after streaming completes and score parses */}
              {overallScore !== null && (
                <div style={{
                  background: T.panelBg, borderRadius: 16, border: `1px solid ${T.border}`,
                  padding: '1.4rem', marginBottom: 10, textAlign: 'center', boxShadow: T.shadow,
                }}>
                  <div style={{ fontSize: 10, color: T.mutedText, fontWeight: 500, letterSpacing: '.08em', textTransform: 'uppercase', marginBottom: 10 }}>
                    Website Health Score
                  </div>
                  <div style={{ fontSize: 56, fontWeight: 900, color: scoreColor(overallScore), lineHeight: 1 }}>
                    {overallScore}
                    <span style={{ fontSize: 18, color: '#d1d5db', fontWeight: 400 }}>/10</span>
                  </div>
                  <div style={{ marginTop: 6, fontSize: 12, fontWeight: 600, color: scoreColor(overallScore) }}>
                    {overallScore < 5 ? 'Critical — Needs Immediate Attention' : overallScore < 7 ? 'Needs Improvement' : 'Good — Keep Optimizing'}
                  </div>
                </div>
              )}

              {/* Full audit — always rendered so no content is lost */}
              <div style={{
                background: T.panelBg, borderRadius: 16, border: `1px solid ${T.border}`,
                padding: '1.25rem', marginBottom: 10, boxShadow: T.shadow,
              }}>
                {loading && (
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
                    <div style={{ width: 8, height: 8, borderRadius: '50%', background: '#8b5cf6', animation: 'pulse 1.2s ease-in-out infinite' }} />
                    <span style={{ fontSize: 11, color: T.mutedText }}>Analysing your website…</span>
                  </div>
                )}
                <div className="playbook-markdown" style={{ fontSize: '0.875rem', color: T.secondaryText, lineHeight: 1.8 }}>
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{formatSectionMarkdown(auditText)}</ReactMarkdown>
                </div>
              </div>

              {/* Continue button — only shown when streaming is complete */}
              {!loading && (
                <button
                  type="button"
                  onClick={onContinue}
                  style={{
                    width: '100%', padding: '13px 24px',
                    background: 'linear-gradient(135deg, #7c3aed, #8b5cf6)',
                    border: 'none', borderRadius: 12, cursor: 'pointer',
                    fontSize: 13.5, fontWeight: 700, color: '#fff', fontFamily: 'inherit',
                    boxShadow: '0 4px 20px rgba(124,58,237,.25)',
                  }}
                >
                  Continue to Next Step →
                </button>
              )}
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center py-20 gap-4">
              <p className="text-sm text-white/40">No audit available — continuing.</p>
              <button
                type="button"
                onClick={onContinue}
                style={{
                  padding: '12px 28px', background: 'linear-gradient(135deg, #7c3aed, #8b5cf6)',
                  border: 'none', borderRadius: 12, cursor: 'pointer',
                  fontSize: 13, fontWeight: 700, color: '#fff', fontFamily: 'inherit',
                }}
              >
                Continue →
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}