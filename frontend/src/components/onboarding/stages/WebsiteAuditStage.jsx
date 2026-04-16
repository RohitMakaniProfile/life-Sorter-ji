import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

// ─── Strip section delimiters left over from old playbook format ───────────
const stripSectionDelimiters = (text) =>
  (text || '').replace(/---SECTION:[a-z_]+---/g, '').trim();

// ─── Parse structured sections out of the audit text ─────────────────────
// Splits on ━━ N. TITLE ━━ headers produced by the new audit prompt.
const parseSections = (text) => {
  const clean = stripSectionDelimiters(text);

  // Match ━━ N. TITLE ━━  or  ━━ TITLE ━━
  const sectionRegex = /━━\s*(?:\d+\.\s*)?([^━]+?)━━/g;
  const titles = [];
  let m;
  while ((m = sectionRegex.exec(clean)) !== null) {
    titles.push({ title: m[1].trim().toUpperCase(), idx: m.index, end: m.index + m[0].length });
  }

  if (titles.length === 0) return { raw: clean };

  const sections = {};
  titles.forEach((t, i) => {
    const start = t.end;
    const end = i + 1 < titles.length ? titles[i + 1].idx : clean.length;
    sections[t.title] = clean.slice(start, end).trim();
  });
  return sections;
};

// ─── Score helpers ────────────────────────────────────────────────────────
const parseOverallScore = (text) => {
  const m = (text || '').match(/\*\*OVERALL\*\*\s*\|\s*\*\*(\d+(?:\.\d+)?)\/10\*\*/i)
    || (text || '').match(/\*\*Overall(?:\s+Score)?:\s*(\d+(?:\.\d+)?)\/10\*\*/i)
    || (text || '').match(/OVERALL[^|]*\|\s*(\d+(?:\.\d+)?)\/10/i);
  return m ? parseFloat(m[1]) : null;
};

const scoreColor = (s) => s >= 7 ? '#16a34a' : s >= 5 ? '#d97706' : '#ef4444';
const scoreLabel = (s) => s < 5 ? 'Critical' : s < 7 ? 'Needs Work' : 'Good';

// ─── Parse "Where You Lose" friction points ───────────────────────────────
const parseFrictions = (text) => {
  if (!text) return [];
  // Each friction starts with **Title** | Impact: HIGH/MED/LOW
  const blocks = text.split(/(?=\*\*[^*]+\*\*\s*\|)/);
  return blocks
    .map((b) => b.trim())
    .filter(Boolean)
    .map((b) => {
      const titleMatch = b.match(/^\*\*([^*]+)\*\*\s*\|\s*Impact:\s*(HIGH|MED|MEDIUM|LOW)/i);
      if (!titleMatch) return null;
      const title = titleMatch[1].trim();
      const impact = titleMatch[2].toUpperCase().replace('MEDIUM', 'MED');
      const rest = b.slice(titleMatch[0].length).trim();
      const observedMatch = rest.match(/OBSERVED:\s*([\s\S]*?)(?=\nCOST:|$)/i);
      const costMatch = rest.match(/COST:\s*([\s\S]*?)(?=\n\*\*|$)/i);
      return {
        title,
        impact,
        observed: observedMatch ? observedMatch[1].trim() : '',
        cost: costMatch ? costMatch[1].trim() : '',
      };
    })
    .filter(Boolean);
};

// ─── Parse "First 10 Seconds" bullets ─────────────────────────────────────
const parseFirst10 = (text) => {
  if (!text) return [];
  return ['WHO lands here', 'THEY SEE', 'THEY NEED'].map((key) => {
    const re = new RegExp(`${key}:\\s*([^\\n]+)`, 'i');
    const m = text.match(re);
    return { key, value: m ? m[1].trim() : '' };
  }).filter((x) => x.value);
};

// ─── Palette ──────────────────────────────────────────────────────────────
const C = {
  bg: '#0d1117',
  card: '#0f172a',
  cardAlt: '#111827',
  border: '#1e293b',
  borderHover: '#334155',
  text: '#f1f5f9',
  muted: '#94a3b8',
  subtle: '#64748b',
  amber: '#f59e0b',
  amberBg: 'rgba(245,158,11,0.07)',
  red: '#ef4444',
  redBg: 'rgba(239,68,68,0.07)',
  green: '#22c55e',
  greenBg: 'rgba(34,197,94,0.07)',
  violet: '#8b5cf6',
  violetBg: 'rgba(139,92,246,0.07)',
};

const impactStyle = {
  HIGH:   { bg: 'rgba(239,68,68,0.12)',  color: '#f87171',  label: '↑ HIGH' },
  MED:    { bg: 'rgba(245,158,11,0.12)', color: '#fbbf24',  label: '~ MED'  },
  LOW:    { bg: 'rgba(100,116,139,0.12)',color: '#94a3b8',  label: '↓ LOW'  },
};

const card = (extra = {}) => ({
  background: C.card,
  borderRadius: 14,
  border: `1px solid ${C.border}`,
  padding: '1.25rem 1.4rem',
  marginBottom: 10,
  ...extra,
});

// ─── Section label chip ───────────────────────────────────────────────────
const SectionLabel = ({ children, color = C.muted }) => (
  <div style={{
    display: 'inline-flex', alignItems: 'center', gap: 6,
    fontSize: 10, fontWeight: 700, letterSpacing: '.1em',
    textTransform: 'uppercase', color, marginBottom: 10,
  }}>
    {children}
  </div>
);

// ─── Inline markdown (no block elements) ─────────────────────────────────
const Md = ({ children, style = {} }) => (
  <div className="audit-md" style={{ fontSize: '0.85rem', color: C.muted, lineHeight: 1.75, ...style }}>
    <ReactMarkdown remarkPlugins={[remarkGfm]}>{children || ''}</ReactMarkdown>
  </div>
);

// ─── SCORE BADGE ─────────────────────────────────────────────────────────
const ScoreBadge = ({ score }) => (
  <div style={{
    ...card({ textAlign: 'center', padding: '1.6rem', marginBottom: 10 }),
    background: `radial-gradient(ellipse at top, rgba(139,92,246,0.06) 0%, ${C.card} 70%)`,
  }}>
    <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: '.12em', textTransform: 'uppercase', color: C.subtle, marginBottom: 8 }}>
      Website Health Score
    </div>
    <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'center', gap: 4 }}>
      <span style={{ fontSize: 64, fontWeight: 900, color: scoreColor(score), lineHeight: 1 }}>{score}</span>
      <span style={{ fontSize: 20, color: C.subtle, fontWeight: 400 }}>/10</span>
    </div>
    <div style={{ marginTop: 8, fontSize: 11, fontWeight: 700, color: scoreColor(score), letterSpacing: '.06em', textTransform: 'uppercase' }}>
      {scoreLabel(score)}
    </div>
  </div>
);

// ─── CORE DISCONNECT ─────────────────────────────────────────────────────
const CoreDisconnect = ({ text }) => (
  <div style={{
    ...card({ borderLeft: `3px solid ${C.amber}`, background: C.amberBg, padding: '1.2rem 1.3rem' }),
  }}>
    <SectionLabel color={C.amber}>⚡ Core Disconnect</SectionLabel>
    <Md style={{ color: '#fcd34d', fontSize: '0.88rem', fontStyle: 'italic' }}>{text}</Md>
  </div>
);

// ─── FIRST 10 SECONDS ────────────────────────────────────────────────────
const First10Sec = ({ text }) => {
  const items = parseFirst10(text);
  const kicker = { 'WHO LANDS HERE': 'Who', 'THEY SEE': 'See', 'THEY NEED': 'Need' };
  const kickerColor = { 'WHO LANDS HERE': C.violet, 'THEY SEE': '#38bdf8', 'THEY NEED': C.green };

  return (
    <div style={card()}>
      <SectionLabel color={C.violet}>👁 Buyer's First 10 Seconds</SectionLabel>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {items.map(({ key, value }) => {
          const k = key.toUpperCase();
          return (
            <div key={k} style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
              <div style={{
                flexShrink: 0, width: 44, height: 22, borderRadius: 6,
                background: `${kickerColor[k]}18`,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: 9, fontWeight: 800, color: kickerColor[k] || C.muted,
                letterSpacing: '.06em', textTransform: 'uppercase', marginTop: 2,
              }}>
                {kicker[k] || key}
              </div>
              <p style={{ margin: 0, fontSize: '0.85rem', color: C.text, lineHeight: 1.65 }}>{value}</p>
            </div>
          );
        })}
        {items.length === 0 && <Md>{text}</Md>}
      </div>
    </div>
  );
};

// ─── FRICTION CARDS ──────────────────────────────────────────────────────
const FrictionCards = ({ text }) => {
  const frictions = parseFrictions(text);
  if (frictions.length === 0) return (
    <div style={card()}>
      <SectionLabel color={C.red}>🎯 Where You Lose The Sale</SectionLabel>
      <Md>{text}</Md>
    </div>
  );

  return (
    <div>
      <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: '.1em', textTransform: 'uppercase', color: C.red, marginBottom: 8 }}>
        🎯 Where You Lose The Sale
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {frictions.map(({ title, impact, observed, cost }, i) => {
          const imp = impactStyle[impact] || impactStyle.MED;
          return (
            <div key={i} style={{
              background: C.card, borderRadius: 12, border: `1px solid ${C.border}`,
              overflow: 'hidden', marginBottom: 0,
            }}>
              {/* Header */}
              <div style={{
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                padding: '0.75rem 1rem', borderBottom: `1px solid ${C.border}`,
                background: C.cardAlt,
              }}>
                <span style={{ fontSize: '0.85rem', fontWeight: 700, color: C.text }}>{title}</span>
                <span style={{
                  fontSize: 10, fontWeight: 700, letterSpacing: '.06em', textTransform: 'uppercase',
                  padding: '2px 8px', borderRadius: 6,
                  background: imp.bg, color: imp.color,
                }}>
                  {imp.label}
                </span>
              </div>
              {/* Body */}
              <div style={{ padding: '0.75rem 1rem', display: 'flex', flexDirection: 'column', gap: 8 }}>
                {observed && (
                  <div style={{ display: 'flex', gap: 8 }}>
                    <span style={{ flexShrink: 0, fontSize: 10, fontWeight: 800, color: C.subtle, textTransform: 'uppercase', letterSpacing: '.06em', paddingTop: 3 }}>Observed</span>
                    <p style={{ margin: 0, fontSize: '0.82rem', color: C.muted, lineHeight: 1.65 }}>{observed}</p>
                  </div>
                )}
                {cost && (
                  <div style={{ display: 'flex', gap: 8, paddingTop: observed ? 4 : 0, borderTop: observed ? `1px solid ${C.border}` : 'none' }}>
                    <span style={{ flexShrink: 0, fontSize: 10, fontWeight: 800, color: '#f87171', textTransform: 'uppercase', letterSpacing: '.06em', paddingTop: 3 }}>Cost</span>
                    <p style={{ margin: 0, fontSize: '0.82rem', color: '#fca5a5', lineHeight: 1.65, fontStyle: 'italic' }}>{cost}</p>
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};

// ─── SCORECARD ───────────────────────────────────────────────────────────
const parseScorecardRows = (text) => {
  if (!text) return [];
  const rows = [];
  const lines = text.split('\n');
  for (const line of lines) {
    if (!line.includes('|')) continue;
    const cells = line.split('|').map((c) => c.trim()).filter(Boolean);
    if (cells.length < 2) continue;
    // skip header and separator rows
    if (/^[-:]+$/.test(cells[0])) continue;
    if (/check/i.test(cells[0]) && /score/i.test(cells[1])) continue;
    const check = cells[0].replace(/\*\*/g, '').trim();
    const scoreRaw = (cells[1] || '').replace(/\*\*/g, '').trim();
    const why = (cells[2] || '').replace(/\*\*/g, '').trim();
    const scoreNum = parseFloat(scoreRaw);
    if (!check) continue;
    rows.push({ check, scoreRaw, scoreNum: isNaN(scoreNum) ? null : scoreNum, why });
  }
  return rows;
};

const ScoreChip = ({ scoreRaw, scoreNum, large = false }) => {
  const color = scoreNum != null ? scoreColor(scoreNum) : C.muted;
  const bg = scoreNum != null
    ? scoreNum >= 7 ? 'rgba(34,197,94,0.12)' : scoreNum >= 5 ? 'rgba(245,158,11,0.12)' : 'rgba(239,68,68,0.12)'
    : 'rgba(148,163,184,0.12)';
  return (
    <div style={{
      display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
      minWidth: large ? 62 : 52, padding: large ? '5px 10px' : '3px 8px',
      borderRadius: 8, background: bg,
      fontSize: large ? '0.95rem' : '0.8rem', fontWeight: 800, color,
      letterSpacing: '-0.01em', flexShrink: 0,
    }}>
      {scoreRaw || '—'}
    </div>
  );
};

const Scorecard = ({ text }) => {
  const rows = parseScorecardRows(text);
  const overall = rows.find((r) => /overall/i.test(r.check));
  const checks = rows.filter((r) => !/overall/i.test(r.check));

  // Fallback to markdown table if parse fails
  if (rows.length === 0) return (
    <div style={card()}>
      <SectionLabel color={C.muted}>📊 Scorecard</SectionLabel>
      <div className="audit-md" style={{ fontSize: '0.83rem', color: C.muted, lineHeight: 1.7 }}>
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{text || ''}</ReactMarkdown>
      </div>
    </div>
  );

  return (
    <div style={card({ padding: '1.1rem 1.2rem' })}>
      <SectionLabel color={C.muted}>📊 Scorecard</SectionLabel>

      {/* Column headers */}
      <div style={{
        display: 'grid', gridTemplateColumns: '1fr 58px 1fr',
        gap: 8, padding: '0 4px 6px', marginBottom: 4,
        borderBottom: `1px solid ${C.border}`,
      }}>
        {['CHECK', 'SCORE', 'WHY'].map((h) => (
          <div key={h} style={{ fontSize: 9, fontWeight: 800, color: C.subtle, letterSpacing: '.1em', textTransform: 'uppercase' }}>{h}</div>
        ))}
      </div>

      {/* Rows */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
        {checks.map(({ check, scoreRaw, scoreNum, why }, i) => (
          <div key={i} style={{
            display: 'grid', gridTemplateColumns: '1fr 58px 1fr',
            gap: 8, padding: '9px 4px',
            borderBottom: `1px solid ${C.border}`,
            alignItems: 'flex-start',
          }}>
            <span style={{ fontSize: '0.82rem', fontWeight: 600, color: C.text, lineHeight: 1.5 }}>{check}</span>
            <ScoreChip scoreRaw={scoreRaw} scoreNum={scoreNum} />
            <span style={{ fontSize: '0.78rem', color: C.muted, lineHeight: 1.6 }}>{why}</span>
          </div>
        ))}
      </div>

      {/* Overall row */}
      {overall && (
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          marginTop: 10, padding: '10px 14px',
          background: overall.scoreNum != null
            ? overall.scoreNum >= 7 ? 'rgba(34,197,94,0.07)' : overall.scoreNum >= 5 ? 'rgba(245,158,11,0.07)' : 'rgba(239,68,68,0.07)'
            : 'rgba(139,92,246,0.07)',
          borderRadius: 10,
          border: `1px solid ${overall.scoreNum != null ? overall.scoreNum >= 7 ? 'rgba(34,197,94,0.2)' : overall.scoreNum >= 5 ? 'rgba(245,158,11,0.2)' : 'rgba(239,68,68,0.2)' : C.border}`,
        }}>
          <span style={{ fontSize: '0.88rem', fontWeight: 800, color: C.text, letterSpacing: '.02em' }}>OVERALL</span>
          <ScoreChip scoreRaw={overall.scoreRaw} scoreNum={overall.scoreNum} large />
        </div>
      )}
    </div>
  );
};

// ─── FIX RIGHT NOW ────────────────────────────────────────────────────────
const FixNow = ({ text }) => (
  <div style={{
    ...card({ borderLeft: `3px solid ${C.green}`, background: C.greenBg }),
  }}>
    <SectionLabel color={C.green}>⚡ Fix Right Now — Zero Dev Work</SectionLabel>
    <Md style={{ color: '#bbf7d0', fontSize: '0.87rem' }}>{text}</Md>
  </div>
);

// ─── THE ONE THING ────────────────────────────────────────────────────────
const TheOneThing = ({ text }) => (
  <div style={{
    ...card({ borderLeft: `3px solid ${C.violet}`, background: C.violetBg }),
  }}>
    <SectionLabel color={C.violet}>🔑 The One Thing</SectionLabel>
    <p style={{ margin: 0, fontSize: '0.95rem', fontWeight: 600, color: C.text, lineHeight: 1.65, fontStyle: 'italic' }}>
      {text.replace(/^["']|["']$/g, '')}
    </p>
  </div>
);

// ─── FALLBACK — plain markdown ─────────────────────────────────────────────
const RawAudit = ({ text }) => (
  <div style={card()}>
    <div className="playbook-markdown" style={{ fontSize: '0.875rem', color: C.muted, lineHeight: 1.8 }}>
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
    </div>
  </div>
);

// ─────────────────────────────────────────────────────────────────────────
export default function WebsiteAuditStage({ auditText, loading, onContinue }) {
  const cleaned = stripSectionDelimiters(auditText || '');
  const sections = cleaned ? parseSections(cleaned) : {};
  const hasStructure = Object.keys(sections).some(k => k !== 'raw');
  const overallScore = !loading && cleaned ? parseOverallScore(cleaned) : null;

  // Look up sections with flexible key matching
  const get = (...candidates) => {
    for (const c of candidates) {
      for (const k of Object.keys(sections)) {
        if (k.includes(c.toUpperCase())) return sections[k];
      }
    }
    return null;
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
      <div
        className="min-h-0 flex-1 overflow-y-auto px-5 pb-6"
        style={{ scrollbarColor: 'rgba(255,255,255,0.08) transparent', scrollbarWidth: 'thin' }}
      >
        <div style={{ maxWidth: 720, margin: '0 auto' }}>

          {/* ── Loading ── */}
          {loading && !cleaned && (
            <div className="flex flex-col items-center justify-center py-20 gap-4">
              <div className="h-10 w-10 animate-spin rounded-full border-2 border-white/20 border-t-violet-500" />
              <p className="text-sm" style={{ color: C.subtle }}>Analysing your website…</p>
            </div>
          )}

          {/* ── Streaming in-progress label ── */}
          {loading && cleaned && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
              <div style={{ width: 7, height: 7, borderRadius: '50%', background: C.violet, animation: 'pulse 1.2s ease-in-out infinite' }} />
              <span style={{ fontSize: 11, color: C.subtle }}>Analysing your website…</span>
            </div>
          )}

          {/* ── Audit content ── */}
          {cleaned && (
            <>
              {/* Score badge */}
              {overallScore !== null && !loading && <ScoreBadge score={overallScore} />}

              {hasStructure ? (
                <>
                  {get('CORE DISCONNECT') && <CoreDisconnect text={get('CORE DISCONNECT')} />}
                  {get('FIRST 10', "BUYER'S FIRST") && <First10Sec text={get('FIRST 10', "BUYER'S FIRST")} />}
                  {get('WHERE YOU LOSE', 'LOSE THE SALE') && (
                    <div style={{ marginBottom: 10 }}>
                      <FrictionCards text={get('WHERE YOU LOSE', 'LOSE THE SALE')} />
                    </div>
                  )}
                  {get('SCORECARD') && <Scorecard text={get('SCORECARD')} />}
                  {get('FIX RIGHT NOW', 'FIX NOW') && <FixNow text={get('FIX RIGHT NOW', 'FIX NOW')} />}
                  {get('THE ONE THING', 'ONE THING') && <TheOneThing text={get('THE ONE THING', 'ONE THING')} />}
                </>
              ) : (
                /* Fallback: no ━━ headers found — render as markdown */
                <RawAudit text={cleaned} />
              )}
            </>
          )}

          {/* ── Empty state ── */}
          {!loading && !cleaned && (
            <div className="flex flex-col items-center justify-center py-20 gap-4">
              <p className="text-sm" style={{ color: C.subtle }}>No audit available — continuing.</p>
            </div>
          )}

          {/* ── Continue button ── */}
          {!loading && (
            <button
              type="button"
              onClick={onContinue}
              style={{
                width: '100%', padding: '13px 24px', marginTop: 6,
                background: 'linear-gradient(135deg, #7c3aed, #8b5cf6)',
                border: 'none', borderRadius: 12, cursor: 'pointer',
                fontSize: 13.5, fontWeight: 700, color: '#fff', fontFamily: 'inherit',
                boxShadow: '0 4px 20px rgba(124,58,237,.25)',
              }}
            >
              Continue to Diagnosis →
            </button>
          )}

        </div>
      </div>
    </div>
  );
}
