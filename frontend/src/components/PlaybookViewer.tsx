import { useEffect, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

// ── Markdown normaliser ──
const formatSectionMarkdown = (text: string) => {
  let r = text;
  r = r.replace(/^\*\*([A-Z][A-Z &\-\/():'0-9,.]+?)\*\*\s*$/gm, (_, l) => `### ${l.trim()}`);
  r = r.replace(/^(?![#>|*\-])([A-Z][A-Z &\-\/():'0-9,.]{7,})\s*$/gm, (_, l) => `### ${l.trim()}`);
  r = r.replace(
    /^(?:#{0,4}\s*)?(?:\*\*)?STEP\s+(\d{1,2})\s*[\u2192\->]+\s*(.+?)(?:\*\*)?\s*$/gm,
    (_, n, t) => `#### STEP ${n} → ${t.trim()}`
  );
  return r;
};

type ThemeMode = 'light' | 'dark';

const resolveThemeMode = (themeMode?: ThemeMode): ThemeMode => {
  if (themeMode) return themeMode;
  if (typeof document === 'undefined') return 'light';
  const docTheme = document.documentElement.getAttribute('data-theme');
  return docTheme === 'dark' || docTheme === 'blue' || docTheme === 'green' ? 'dark' : 'light';
};

const PLAYBOOK_THEME = {
  light: {
    pageText: '#1e293b',
    primaryText: '#111827',
    secondaryText: '#374151',
    mutedText: '#9ca3af',
    softMutedText: '#6b7280',
    panelBg: '#fff',
    raisedBg: '#fafafa',
    border: '#e5e7eb',
    softBorder: '#f0f0f0',
    accentBg: '#f5f3ff',
    accentBorder: '#ddd6fe',
    accentBgStrong: '#faf5ff',
    progressBg: '#f0effa',
    shadow: '0 1px 3px rgba(0,0,0,0.04)',
    shadowStrong: '0 2px 12px rgba(0,0,0,0.06)',
  },
  dark: {
    pageText: '#dbe5f5',
    primaryText: '#f8fafc',
    secondaryText: '#d1d5db',
    mutedText: '#94a3b8',
    softMutedText: '#a3b3c8',
    panelBg: '#0f172a',
    raisedBg: '#111827',
    border: '#23314a',
    softBorder: '#1f2937',
    accentBg: '#21123a',
    accentBorder: '#4c1d95',
    accentBgStrong: '#1b1330',
    progressBg: '#1f2338',
    shadow: '0 1px 3px rgba(2, 8, 23, 0.55)',
    shadowStrong: '0 4px 18px rgba(2, 8, 23, 0.6)',
  },
};

// ── Context Brief parser ──
const getContextSectionMeta = (isDark: boolean): Record<string, { icon: string; color: string; bg: string; border: string }> => ({
  'Company Snapshot': { icon: '🏢', color: '#60a5fa', bg: isDark ? '#12213d' : '#eff6ff', border: isDark ? '#1d4ed8' : '#bfdbfe' },
  'Goal':             { icon: '🎯', color: '#a78bfa', bg: isDark ? '#21123a' : '#f5f3ff', border: isDark ? '#6d28d9' : '#ddd6fe' },
  'Where They Stand': { icon: '📊', color: '#34d399', bg: isDark ? '#0d2b24' : '#f0fdf4', border: isDark ? '#047857' : '#bbf7d0' },
  'Website Read':     { icon: '🌐', color: '#fbbf24', bg: isDark ? '#35230c' : '#fffbeb', border: isDark ? '#b45309' : '#fde68a' },
  'What the Data Implies': { icon: '💡', color: '#f87171', bg: isDark ? '#381317' : '#fff8f8', border: isDark ? '#b91c1c' : '#fecaca' },
});

type ContextItem = { type: 'kv'; key: string; value: string } | { type: 'text'; text: string };
interface ContextSection {
  title: string; icon: string; color: string; bg: string; border: string;
  items: ContextItem[];
}

const parseContextBrief = (raw: string, isDark: boolean): ContextSection[] => {
  if (!raw) return [];
  const contextSectionMeta = getContextSectionMeta(isDark);
  const lines = raw.split('\n').map(l => l.trim()).filter(l => l && !/^business context brief$/i.test(l));
  const sections: ContextSection[] = [];
  let current: ContextSection | null = null;

  for (const line of lines) {
    const clean = line.replace(/\*\*/g, '').trim();
    const sectionKey = Object.keys(contextSectionMeta).find(k => clean === k);
    if (sectionKey) {
      current = { title: sectionKey, ...contextSectionMeta[sectionKey], items: [] };
      sections.push(current);
      continue;
    }
    if (!current) continue;
    const colonIdx = line.indexOf(':');
    if (colonIdx > 0 && colonIdx < 55 && !line.startsWith('-')) {
      const key = line.slice(0, colonIdx).replace(/\*\*/g, '').trim();
      const value = line.slice(colonIdx + 1).trim();
      if (key && value) { current.items.push({ type: 'kv', key, value }); continue; }
    }
    current.items.push({ type: 'text', text: line });
  }
  return sections;
};

// ── Parse playbook text into structured steps ──
const PRIORITY_ORDER = { HIGH: 0, MEDIUM: 1, LOW: 2 };

// Extract explicit [PRIORITY: X] tag from raw title; fallback to position-based
const detectPriority = (num: number, rawTitle: string): 'HIGH' | 'MEDIUM' | 'LOW' => {
  const m = rawTitle.match(/\[PRIORITY:\s*(HIGH|MEDIUM|LOW)\]/i);
  if (m) return m[1].toUpperCase() as 'HIGH' | 'MEDIUM' | 'LOW';
  // Fallback: position-based (for old playbooks without tag)
  if (num <= 3) return 'HIGH';
  if (num <= 7) return 'MEDIUM';
  return 'LOW';
};

const getSubPatterns = (isDark: boolean) => [
  { key: 'todo',    regex: /(?:#{0,4}\s*)?(?:\*\*)?(?:📌\s*)?WHAT TO DO(?:\*\*)?\s*\n/i,                icon: '📌', label: 'What To Do',        color: '#60a5fa', bg: isDark ? '#12213d' : '#eff6ff', border: isDark ? '#1d4ed8' : '#bfdbfe' },
  { key: 'tool',    regex: /(?:#{0,4}\s*)?(?:\*\*)?(?:🤖\s*)?TOOL\s*[+&]\s*AI SHORTCUT(?:\*\*)?\s*\n/i, icon: '🤖', label: 'Tool + AI Shortcut', color: '#a78bfa', bg: isDark ? '#21123a' : '#f5f3ff', border: isDark ? '#6d28d9' : '#ddd6fe' },
  { key: 'example', regex: /(?:#{0,4}\s*)?(?:\*\*)?(?:💡\s*)?REAL EXAMPLE(?:\*\*)?\s*\n/i,               icon: '💡', label: 'Real Example',       color: '#fbbf24', bg: isDark ? '#35230c' : '#fffbeb', border: isDark ? '#b45309' : '#fde68a' },
  { key: 'edge',    regex: /(?:#{0,4}\s*)?(?:\*\*)?(?:⚡\s*)?THE EDGE(?:\*\*)?\s*\n/i,                   icon: '⚡', label: 'The Edge',           color: '#34d399', bg: isDark ? '#0d2b24' : '#f0fdf4', border: isDark ? '#047857' : '#bbf7d0' },
];

const parseSubsections = (body: string, isDark: boolean) => {
  const positions: any[] = [];
  const subPatterns = getSubPatterns(isDark);
  for (const sub of subPatterns) {
    const m = body.search(sub.regex);
    if (m !== -1) positions.push({ pos: m, sub });
  }
  positions.sort((a, b) => a.pos - b.pos);

  const subsections: any[] = [];
  if (positions.length === 0) {
    subsections.push({ icon: '', label: '', content: body, color: isDark ? '#d1d5db' : '#374151', bg: 'transparent', border: 'transparent' });
  } else {
    const preText = body.slice(0, positions[0].pos).trim();
    if (preText) subsections.push({ icon: '', label: '', content: preText, color: isDark ? '#d1d5db' : '#374151', bg: 'transparent', border: 'transparent' });
    for (let j = 0; j < positions.length; j++) {
      const { sub } = positions[j];
      const start = positions[j].pos;
      const end = j + 1 < positions.length ? positions[j + 1].pos : body.length;
      const content = body.slice(start, end).replace(sub.regex, '').trim();
      subsections.push({ ...sub, content });
    }
  }
  return subsections;
};

const parsePlaybookSteps = (rawText: string, isDark: boolean) => {
  let text = rawText;
  let checklist = '';

  // Extract checklist — find it and cut text there
  const clIdx = text.search(/\n[\s]*WEEK\s*1\s*EXECUTION\s*CHECKLIST/i);
  if (clIdx !== -1) {
    const clBodyStart = text.indexOf('\n', clIdx + 1);
    checklist = clBodyStart !== -1 ? text.slice(clBodyStart + 1).trim() : '';
    text = text.slice(0, clIdx);
  }

  // ── Find step header positions ──
  // Strategy: only match a numbered line that is preceded by ≥2 newlines (blank line gap).
  // This prevents matching numbered sub-lists inside step content.
  // Format: N. [anything] or N) [anything] where N is 1–10.
  // Capture the entire line as the raw title.
  const STEP_HEADER = /\n{2,}(?:#{0,3}\s*)?(?:\*\*)?(\d{1,2})[.)]\s+([^\n]+?)(?:\*\*)?\s*(?=\n)/g;

  // Each marker: { num, rawTitle, title, headerStart, bodyStart }
  type Marker = { num: number; rawTitle: string; title: string; headerStart: number; bodyStart: number };
  const markers: Marker[] = [];
  let m: RegExpExecArray | null;

  const cleanTitle = (raw: string) => raw
    .replace(/\[PRIORITY:\s*(?:HIGH|MEDIUM|LOW)\]/gi, '')
    .replace(/\*\*/g, '')
    .replace(/^The\s+/i, '')
    .replace(/^["""'\u201C\u2018\u201E]+|["""'\u201D\u2019]+$/g, '')
    .trim();

  while ((m = STEP_HEADER.exec(text)) !== null) {
    const num = parseInt(m[1]);
    if (num < 1 || num > 10) continue;
    const rawTitle = m[2];
    const clean = cleanTitle(rawTitle);
    if (!clean || clean.length < 3) continue;
    markers.push({ num, rawTitle, title: clean, headerStart: m.index, bodyStart: m.index + m[0].length });
  }

  // ── Fallback: if ≤1 markers found, relax the double-newline requirement ──
  if (markers.length <= 1) {
    const STEP_RELAXED = /(?:^|\n)(?:#{0,3}\s*)?(?:\*\*)?(\d{1,2})[.)]\s+([^\n]+?)(?:\*\*)?\s*(?=\n)/g;
    markers.length = 0;
    while ((m = STEP_RELAXED.exec(text)) !== null) {
      const num = parseInt(m[1]);
      if (num < 1 || num > 10) continue;
      const rawTitle = m[2];
      const clean = cleanTitle(rawTitle);
      if (!clean || clean.length < 3) continue;
      markers.push({ num, rawTitle, title: clean, headerStart: m.index, bodyStart: m.index + m[0].length });
    }
  }

  // ── Extract step bodies by slicing between marker header positions ──
  const steps: any[] = [];
  for (let i = 0; i < markers.length; i++) {
    const { num, rawTitle, title, bodyStart } = markers[i];
    // Body ends where the NEXT step's header gap begins
    const bodyEnd = i + 1 < markers.length ? markers[i + 1].headerStart : text.length;
    const body = text.slice(bodyStart, bodyEnd).trim();
    const subsections = parseSubsections(body, isDark);
    const priority = detectPriority(num, rawTitle);
    steps.push({ num, title, subsections, priority });
  }

  // Sort: HIGH first, then MEDIUM, then LOW; within same priority keep original order
  steps.sort((a, b) => {
    const pd = PRIORITY_ORDER[a.priority as keyof typeof PRIORITY_ORDER] - PRIORITY_ORDER[b.priority as keyof typeof PRIORITY_ORDER];
    return pd !== 0 ? pd : a.num - b.num;
  });

  return { steps, checklist };
};

// ── Audit parse helpers ──
const parseOverallScore = (audit: string) => {
  const m = audit.match(/\*\*Overall:\s*(\d+(?:\.\d+)?)\/10\*\*/i);
  return m ? parseFloat(m[1]) : null;
};

const parseAuditScorecard = (audit: string) => {
  const rows: any[] = [];
  const tableMatch = audit.match(/\|[^\n]*Score[^\n]*\|[\s\S]*?(?=\n\*\*Overall|\n##)/i);
  if (!tableMatch) return rows;
  const lines = tableMatch[0].split('\n').filter(l => l.includes('|') && !l.includes('---'));
  for (const line of lines.slice(1)) {
    const cells = line.split('|').map(c => c.trim()).filter(Boolean);
    if (cells.length >= 2) {
      const scoreMatch = cells[1].match(/(\d+(?:\.\d+)?)/);
      if (scoreMatch) rows.push({ label: cells[0], score: parseFloat(scoreMatch[1]) });
    }
  }
  return rows;
};

const parseAuditSection = (audit: string, keyword: string) => {
  const pattern = new RegExp(`##[^#\\n]*(?:${keyword})[\\s\\S]*?(?=\\n##|$)`, 'i');
  const m = audit.match(pattern);
  if (!m) return '';
  return m[0].replace(/^##[^\n]*\n/, '').trim();
};

const parseAuditMessagingGaps = (audit: string) => {
  const section = parseAuditSection(audit, 'Site Loses|Messaging Gap|What Your Site Says|Where Your|Buyer');
  if (!section) return [];
  const gaps: any[] = [];
  const blocks = section.split(/(?=\n\*\*[^*\n]+\*\*)/).filter(Boolean);
  for (const block of blocks) {
    const titleMatch = block.match(/\*\*([^*\n]+)\*\*/);
    const impactMatch = block.match(/Revenue Impact:\s*(HIGH|MEDIUM|LOW)/i);
    if (titleMatch) {
      gaps.push({
        title: titleMatch[1].trim(),
        impact: impactMatch ? impactMatch[1].toUpperCase() : 'MEDIUM',
        content: block.replace(/^\*\*[^*\n]+\*\*\n?/, '').trim(),
      });
    }
  }
  return gaps.slice(0, 5);
};

const parsePlaybookTitle = (playbook: string) => {
  // Handle: THE "X" PLAYBOOK or **THE "X" PLAYBOOK** or THE 'X' PLAYBOOK
  const m = playbook.match(/(?:\*\*)?THE\s+[""\u201C']([^""'\u201D\n]+)[""\u201D']\s+PLAYBOOK(?:\*\*)?/im);
  return m ? `The "${m[1]}" Playbook` : '';
};

const parsePlaybookOneLever = (playbook: string) => {
  // Content between THE PLAYBOOK title and the first --- separator or first numbered step
  const m = playbook.match(/(?:\*\*)?THE\s+[""\u201C'][^""'\u201D\n]+[""\u201D']\s+PLAYBOOK(?:\*\*)?[\s\n]+([\s\S]*?)(?=\n---|\n\s*\n\s*\d{1,2}[.)]\s)/im);
  return m ? m[1].trim() : '';
};

const scoreColor = (score: number) => {
  if (score >= 7) return '#16a34a';
  if (score >= 5) return '#d97706';
  return '#dc2626';
};

// ── Copy prompt button ──
const CopyPromptBtn = ({ text, isDark }: { text: string; isDark: boolean }) => {
  const [copied, setCopied] = useState(false);
  return (
    <button
      onClick={(e) => {
        e.stopPropagation();
        navigator.clipboard.writeText(text);
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      }}
      style={{
        background: copied ? (isDark ? '#0f2f1b' : '#f0fdf4') : (isDark ? '#21123a' : '#f5f3ff'),
        border: `1px solid ${copied ? (isDark ? '#166534' : '#bbf7d0') : (isDark ? '#5b21b6' : '#ddd6fe')}`,
        color: copied ? '#16a34a' : (isDark ? '#c4b5fd' : '#7c3aed'),
        fontSize: 10, fontWeight: 600, borderRadius: 6, padding: '4px 10px',
        cursor: 'pointer', transition: 'all .2s', fontFamily: 'inherit', flexShrink: 0,
      }}
    >
      {copied ? '✓ Copied' : 'Copy Prompt'}
    </button>
  );
};

// ── Main PlaybookViewer component ──
export interface PlaybookData {
  playbook?: string;
  websiteAudit?: string;
  contextBrief?: string;
  icpCard?: string;
}

const PlaybookViewer = ({
  playbookData,
  initialPhase,
  phase: controlledPhase,
  onPhaseChange,
  themeMode,
}: {
  playbookData: PlaybookData;
  initialPhase?: 'verdict' | 'quickwin' | 'playbook';
  phase?: 'verdict' | 'quickwin' | 'playbook';
  onPhaseChange?: (phase: 'verdict' | 'quickwin' | 'playbook') => void;
  themeMode?: ThemeMode;
}) => {
  const [internalPhase, setInternalPhase] = useState<'verdict' | 'quickwin' | 'playbook'>(initialPhase ?? 'verdict');
  const phase = controlledPhase ?? internalPhase;
  const setPhase = (p: 'verdict' | 'quickwin' | 'playbook') => {
    setInternalPhase(p);
    onPhaseChange?.(p);
  };
  const [expandedStep, setExpandedStep] = useState<number | null>(null);
  const [checks, setChecks] = useState<Record<string, boolean>>({});
  const [contextBriefOpen, setContextBriefOpen] = useState(false);
  const [mode, setMode] = useState<ThemeMode>(() => resolveThemeMode(themeMode));

  useEffect(() => {
    setMode(resolveThemeMode(themeMode));
    if (themeMode || typeof document === 'undefined') return;
    const observer = new MutationObserver(() => setMode(resolveThemeMode(themeMode)));
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
    return () => observer.disconnect();
  }, [themeMode]);

  const isDark = mode === 'dark';
  const theme = PLAYBOOK_THEME[mode];

  const phases: Array<'verdict' | 'quickwin' | 'playbook'> = ['verdict', 'quickwin', 'playbook'];
  const phaseLabels = { verdict: 'The Verdict', quickwin: 'Quick Win', playbook: 'Full Playbook' };
  const pi = phases.indexOf(phase);

  const audit = playbookData.websiteAudit || '';
  const overallScore = parseOverallScore(audit);
  const scorecardRows = parseAuditScorecard(audit);
  const quickWinSection = parseAuditSection(audit, '30-Minute Fix');
  const bigBuildSection = parseAuditSection(audit, 'Big Build');
  const messagingGaps = parseAuditMessagingGaps(audit);

  const contextBrief = playbookData.contextBrief || '';
  const contextBriefSections = parseContextBrief(contextBrief, isDark);
  const playbookText = playbookData.playbook || '';
  const { steps, checklist } = parsePlaybookSteps(playbookText, isDark);
  const playbookTitle = parsePlaybookTitle(playbookText);
  const oneLever = parsePlaybookOneLever(playbookText);

  const toggleCheck = (k: string) => setChecks(p => ({ ...p, [k]: !p[k] }));

  const dayNames = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday'];
  const dayTasks = checklist
    ? dayNames.flatMap(day => {
        const m = checklist.match(new RegExp(`${day}:\\s*([^\\n]+)`, 'i'));
        return m ? [{ day: day.slice(0, 3).toUpperCase(), task: m[1].trim() }] : [];
      })
    : [];
  const checkCount = dayTasks.filter(d => checks[d.day]).length;

  return (
    <div style={{ fontFamily: 'inherit', color: theme.secondaryText }}>
      {/* Header banner */}
      <div style={{
        background: theme.panelBg, borderRadius: 20, padding: '1.1rem 1.4rem', marginBottom: 10,
        border: `1px solid ${theme.border}`, boxShadow: theme.shadowStrong,
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      }}>
        <div>
          <div style={{ fontSize: 10, color: '#7c3aed', fontWeight: 700, letterSpacing: '.08em', textTransform: 'uppercase', marginBottom: 3 }}>
            AI Growth Playbook
          </div>
          <div style={{ fontSize: '1.05rem', fontWeight: 900, color: theme.primaryText, letterSpacing: '-0.02em', lineHeight: 1.2 }}>
            {playbookTitle || 'Your Personalised Strategy'}
          </div>
        </div>
        <div style={{ fontSize: '2.2rem', lineHeight: 1, flexShrink: 0 }}>🚀</div>
      </div>

      {/* Tab navigation */}
      <div style={{
        background: theme.panelBg, borderRadius: 14, border: `1px solid ${theme.border}`,
        padding: 4, display: 'flex', gap: 3, marginBottom: 14,
        boxShadow: theme.shadow,
      }}>
        {phases.map((p, i) => (
          <button key={p} onClick={() => setPhase(p)} style={{
            flex: 1, border: 'none', cursor: 'pointer', fontFamily: 'inherit',
            display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 5,
            padding: '9px 6px', borderRadius: 10, transition: 'all .2s',
            background: phase === p ? 'linear-gradient(135deg, #7c3aed, #8b5cf6)' : 'transparent',
          }}>
            <span style={{
              width: 18, height: 18, borderRadius: '50%', flexShrink: 0,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 9, fontWeight: 700,
              background: phase === p ? 'rgba(255,255,255,0.25)' : i < pi ? '#7c3aed' : theme.border,
              color: phase === p ? '#fff' : i < pi ? '#fff' : '#9ca3af',
            }}>{i + 1}</span>
            <span style={{
              fontSize: 11.5, fontWeight: phase === p ? 700 : 500,
              color: phase === p ? '#fff' : theme.softMutedText,
            }}>{phaseLabels[p]}</span>
          </button>
        ))}
      </div>

      {/* ── VERDICT TAB ── */}
      {phase === 'verdict' && (
        <div>
          {overallScore !== null && (
            <div style={{
              background: theme.panelBg, borderRadius: 16, border: `1px solid ${theme.border}`,
              padding: '1.4rem', marginBottom: 10, textAlign: 'center',
              boxShadow: theme.shadow,
            }}>
              <div style={{ fontSize: 10, color: theme.mutedText, fontWeight: 500, letterSpacing: '.08em', textTransform: 'uppercase', marginBottom: 10 }}>
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

          {scorecardRows.length > 0 && (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(110px, 1fr))', gap: 8, marginBottom: 10 }}>
              {scorecardRows.map((row, i) => (
                <div key={i} style={{
                  background: theme.panelBg, borderRadius: 12, border: `1px solid ${theme.border}`,
                  padding: '12px 8px', textAlign: 'center', boxShadow: theme.shadow,
                }}>
                  <div style={{ fontSize: 24, fontWeight: 800, color: scoreColor(row.score), lineHeight: 1 }}>
                    {row.score}<span style={{ fontSize: 11, color: '#d1d5db' }}>/10</span>
                  </div>
                  <div style={{ fontSize: 9.5, color: theme.mutedText, marginTop: 3, fontWeight: 500, lineHeight: 1.3 }}>
                    {row.label.length > 38 ? row.label.slice(0, 36) + '…' : row.label}
                  </div>
                </div>
              ))}
            </div>
          )}

          {messagingGaps.length > 0 && (
            <div style={{
              background: theme.panelBg, borderRadius: 16, border: `1px solid ${theme.border}`,
              padding: '1.1rem 1.25rem', marginBottom: 10, boxShadow: theme.shadow,
            }}>
              <div style={{ fontSize: 10, color: '#dc2626', fontWeight: 700, letterSpacing: '.08em', textTransform: 'uppercase', marginBottom: 10 }}>
                Where You're Losing Buyers
              </div>
              {messagingGaps.map((gap: any, i: number) => (
                <div key={i} style={{
                  padding: '10px 12px', borderRadius: 10, marginBottom: 7,
                  background: gap.impact === 'HIGH' ? (isDark ? '#381317' : '#fff8f8') : (isDark ? '#35230c' : '#fffbeb'),
                  border: `1px solid ${gap.impact === 'HIGH' ? (isDark ? '#b91c1c' : '#fecaca') : (isDark ? '#b45309' : '#fde68a')}`,
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 5 }}>
                    <span style={{ fontSize: 12.5, fontWeight: 700, color: theme.primaryText, lineHeight: 1.3 }}>{gap.title}</span>
                    <span style={{
                      fontSize: 8, fontWeight: 700, letterSpacing: '.04em', flexShrink: 0, marginLeft: 8,
                      color: gap.impact === 'HIGH' ? '#dc2626' : '#d97706',
                      background: gap.impact === 'HIGH' ? '#fee2e2' : '#fef3c7',
                      padding: '3px 7px', borderRadius: 20,
                    }}>{gap.impact}</span>
                  </div>
                  <div className="playbook-markdown" style={{ fontSize: 11.5, color: theme.softMutedText, lineHeight: 1.6 }}>
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{gap.content}</ReactMarkdown>
                  </div>
                </div>
              ))}
            </div>
          )}

          {overallScore === null && scorecardRows.length === 0 && messagingGaps.length === 0 && audit && (
            <div style={{
              background: theme.panelBg, borderRadius: 16, border: `1px solid ${theme.border}`,
              padding: '1.25rem', marginBottom: 10, boxShadow: theme.shadow,
            }}>
              <div className="playbook-markdown" style={{ fontSize: '0.875rem', color: theme.pageText, lineHeight: 1.8 }}>
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{formatSectionMarkdown(audit)}</ReactMarkdown>
              </div>
            </div>
          )}

          <button onClick={() => setPhase('quickwin')} style={{
            width: '100%', padding: '13px 24px',
            background: 'linear-gradient(135deg, #7c3aed, #8b5cf6)',
            border: 'none', borderRadius: 12, cursor: 'pointer',
            fontSize: 13.5, fontWeight: 700, color: '#fff', fontFamily: 'inherit',
            boxShadow: '0 4px 20px rgba(124,58,237,.25)',
          }}>
            See What To Fix First →
          </button>
        </div>
      )}

      {/* ── QUICK WIN TAB ── */}
      {phase === 'quickwin' && (
        <div>
          {contextBriefSections.length > 0 && (
            <div style={{
              background: theme.panelBg, borderRadius: 16, border: `1px solid ${theme.border}`,
              marginBottom: 10, boxShadow: theme.shadow, overflow: 'hidden',
            }}>
              {/* Accordion header */}
              <div
                onClick={() => setContextBriefOpen(o => !o)}
                style={{
                  padding: '13px 16px', cursor: 'pointer', userSelect: 'none',
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                  background: contextBriefOpen ? theme.accentBgStrong : theme.panelBg,
                  borderBottom: contextBriefOpen ? `1px solid ${theme.accentBorder}` : 'none',
                  transition: 'background .2s',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ fontSize: '1rem' }}>📋</span>
                  <div>
                    <div style={{ fontSize: 10, color: '#7c3aed', fontWeight: 700, letterSpacing: '.08em', textTransform: 'uppercase' }}>About This Business</div>
                    <div style={{ fontSize: 13, fontWeight: 700, color: theme.primaryText, marginTop: 1 }}>Business Context</div>
                  </div>
                </div>
                <div style={{
                  fontSize: 12, color: theme.mutedText, flexShrink: 0,
                  transform: contextBriefOpen ? 'rotate(180deg)' : 'rotate(0)',
                  transition: 'transform .25s',
                }}>▾</div>
              </div>

              {/* Accordion body */}
              {contextBriefOpen && (
                <div style={{ padding: '12px 14px', display: 'flex', flexDirection: 'column', gap: 10 }}>
                  {contextBriefSections.map((section, si) => (
                    <div key={si} style={{
                      borderRadius: 10, border: `1px solid ${section.border}`,
                      background: section.bg, overflow: 'hidden',
                    }}>
                      {/* Section header */}
                      <div style={{
                        padding: '8px 12px', display: 'flex', alignItems: 'center', gap: 6,
                        borderBottom: `1px solid ${section.border}`,
                      }}>
                        <span style={{ fontSize: '0.9rem' }}>{section.icon}</span>
                        <span style={{ fontSize: 10, fontWeight: 800, color: section.color, letterSpacing: '.06em', textTransform: 'uppercase' }}>
                          {section.title}
                        </span>
                      </div>

                      {/* Section items */}
                      <div style={{ padding: '8px 12px', display: 'flex', flexDirection: 'column', gap: 5 }}>
                        {section.items.map((item, ii) => (
                          item.type === 'kv' ? (
                            <div key={ii} style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
                              <span style={{
                                fontSize: 10, fontWeight: 700, color: section.color,
                                minWidth: 110, flexShrink: 0, lineHeight: 1.6, paddingTop: 1,
                              }}>{item.key}</span>
                              <span style={{ fontSize: 12, color: theme.secondaryText, lineHeight: 1.6, flex: 1 }}>{item.value}</span>
                            </div>
                          ) : (
                            <p key={ii} style={{ margin: 0, fontSize: 12, color: theme.softMutedText, lineHeight: 1.7 }}>
                              {item.text}
                            </p>
                          )
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {quickWinSection ? (
            <div style={{
              background: theme.panelBg, borderRadius: 16, border: `1px solid ${theme.border}`,
              borderTop: '3px solid #7c3aed', padding: '1.1rem 1.4rem', marginBottom: 10,
              boxShadow: theme.shadow,
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
                <span style={{ fontSize: '1.1rem' }}>⚡</span>
                <div>
                  <div style={{ fontSize: 10, color: '#7c3aed', fontWeight: 700, letterSpacing: '.08em', textTransform: 'uppercase' }}>Do This Today — No Developer Needed</div>
                  <div style={{ fontSize: 14, fontWeight: 800, color: theme.primaryText, marginTop: 2 }}>The 30-Minute Fix</div>
                </div>
              </div>
              <div className="playbook-markdown" style={{ fontSize: '0.875rem', color: theme.secondaryText, lineHeight: 1.8 }}>
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{formatSectionMarkdown(quickWinSection)}</ReactMarkdown>
              </div>
            </div>
          ) : steps[0] && (
            <div style={{
              background: theme.panelBg, borderRadius: 16, border: `1px solid ${theme.border}`,
              borderTop: '3px solid #7c3aed', padding: '1.1rem 1.4rem', marginBottom: 10,
              boxShadow: theme.shadow,
            }}>
              <div style={{ fontSize: 10, color: '#7c3aed', fontWeight: 700, letterSpacing: '.08em', textTransform: 'uppercase', marginBottom: 6 }}>Start Here — Step 1</div>
              <div style={{ fontSize: 14, fontWeight: 800, color: theme.primaryText, marginBottom: 10 }}>{steps[0].title}</div>
              {steps[0].subsections.map((sub: any, i: number) => (
                <div key={i} style={{ marginBottom: 8 }}>
                  {sub.label && <div style={{ fontSize: 9, color: sub.color, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '.05em', marginBottom: 4 }}>{sub.icon} {sub.label}</div>}
                  <div className="playbook-markdown" style={{ fontSize: '0.845rem', color: theme.secondaryText, lineHeight: 1.75 }}>
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{formatSectionMarkdown(sub.content)}</ReactMarkdown>
                  </div>
                </div>
              ))}
            </div>
          )}

          {bigBuildSection && (
            <div style={{
              background: theme.panelBg, borderRadius: 16, border: `1px solid ${theme.border}`,
              borderTop: '3px solid #d97706', padding: '1.1rem 1.4rem', marginBottom: 10,
              boxShadow: theme.shadow,
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
                <span style={{ fontSize: '1.1rem' }}>🏗️</span>
                <div>
                  <div style={{ fontSize: 10, color: '#d97706', fontWeight: 700, letterSpacing: '.08em', textTransform: 'uppercase' }}>One Dev Change Worth Your Time</div>
                  <div style={{ fontSize: 14, fontWeight: 800, color: theme.primaryText, marginTop: 2 }}>The Big Build</div>
                </div>
              </div>
              <div className="playbook-markdown" style={{ fontSize: '0.875rem', color: theme.secondaryText, lineHeight: 1.8 }}>
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{formatSectionMarkdown(bigBuildSection)}</ReactMarkdown>
              </div>
            </div>
          )}

          <button onClick={() => setPhase('playbook')} style={{
            width: '100%', padding: '13px 24px',
            background: 'linear-gradient(135deg, #7c3aed, #8b5cf6)',
            border: 'none', borderRadius: 12, cursor: 'pointer',
            fontSize: 13.5, fontWeight: 700, color: '#fff', fontFamily: 'inherit',
            boxShadow: '0 4px 20px rgba(124,58,237,.25)',
          }}>
            Show Full 10-Step Playbook →
          </button>
        </div>
      )}

      {/* ── FULL PLAYBOOK TAB ── */}
      {phase === 'playbook' && (
        <div>
          {oneLever && (
            <div style={{
              background: theme.accentBg, borderRadius: 14, border: `1px solid ${theme.accentBorder}`,
              padding: '0.9rem 1.1rem', marginBottom: 12, borderLeft: '4px solid #7c3aed',
            }}>
              <div style={{ fontSize: 9, color: '#7c3aed', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '.08em', marginBottom: 5 }}>The One Lever</div>
              <div style={{ fontSize: 12.5, color: isDark ? '#c4b5fd' : '#3730a3', lineHeight: 1.7 }}>{oneLever}</div>
            </div>
          )}

          {steps.length > 0 && (
            <div style={{ display: 'flex', gap: 6, marginBottom: 10, flexWrap: 'wrap' }}>
              {(['HIGH', 'MEDIUM', 'LOW'] as const).map(p => {
                const count = steps.filter(s => s.priority === p).length;
                if (!count) return null;
                const clr = p === 'HIGH' ? '#dc2626' : p === 'MEDIUM' ? '#d97706' : '#16a34a';
                const bg  = p === 'HIGH' ? (isDark ? '#381317' : '#fff1f2') : p === 'MEDIUM' ? (isDark ? '#35230c' : '#fffbeb') : (isDark ? '#0d2b24' : '#f0fdf4');
                return (
                  <div key={p} style={{ display: 'flex', alignItems: 'center', gap: 4, padding: '4px 10px', borderRadius: 20, background: bg, border: `1px solid ${clr}22` }}>
                    <div style={{ width: 7, height: 7, borderRadius: '50%', background: clr }} />
                    <span style={{ fontSize: 10, fontWeight: 700, color: clr }}>{p}</span>
                    <span style={{ fontSize: 10, color: theme.mutedText }}>{count} step{count > 1 ? 's' : ''}</span>
                  </div>
                );
              })}
              <div style={{ marginLeft: 'auto', fontSize: 10, color: theme.mutedText, alignSelf: 'center' }}>
                {steps.length} total · sorted by priority
              </div>
            </div>
          )}

          {steps.length === 0 && !playbookText && (
            <div style={{ textAlign: 'center', padding: '2rem 0', color: theme.mutedText, fontSize: 13 }}>
              Generating your steps…
            </div>
          )}

          {steps.length > 0 ? steps.map((step: any) => {
            const isOpen = expandedStep === step.num;
            const toolSub = step.subsections.find((s: any) => s.key === 'tool');
            const promptMatch = toolSub?.content?.match(/Prompt:\s*"?([\s\S]+?)(?:"\s*$|"(?=\n)|$)/m);
            const promptText = promptMatch ? promptMatch[1].trim().replace(/^"|"$/g, '') : '';

            const priorityStyle: Record<string, { bg: string; color: string; border: string }> = {
              HIGH:   { bg: isDark ? '#381317' : '#fee2e2', color: '#dc2626', border: isDark ? '#b91c1c' : '#fca5a5' },
              MEDIUM: { bg: isDark ? '#35230c' : '#fef3c7', color: '#d97706', border: isDark ? '#b45309' : '#fcd34d' },
              LOW:    { bg: isDark ? '#0d2b24' : '#f0fdf4', color: '#16a34a', border: isDark ? '#047857' : '#86efac' },
            };
            const ps = priorityStyle[step.priority] || priorityStyle.LOW;

            return (
              <div key={step.num} style={{
                background: theme.panelBg, borderRadius: 13, marginBottom: 7,
                border: `1px solid ${isOpen ? theme.accentBorder : theme.border}`,
                boxShadow: isOpen ? '0 2px 14px rgba(124,58,237,.18)' : theme.shadow,
                overflow: 'hidden', transition: 'box-shadow .2s, border-color .2s',
              }}>
                <div onClick={() => setExpandedStep(isOpen ? null : step.num)} style={{
                  padding: '13px 15px', cursor: 'pointer',
                  display: 'flex', gap: 11, alignItems: 'center',
                  background: isOpen ? (isDark ? 'linear-gradient(135deg, #1b1330 0%, #21123a 100%)' : 'linear-gradient(135deg, #faf5ff 0%, #f5f3ff 100%)') : theme.panelBg,
                }}>
                  <div style={{
                    width: 28, height: 28, borderRadius: 8, flexShrink: 0,
                    background: '#7c3aed', color: '#fff',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    fontSize: 11, fontWeight: 800,
                  }}>{step.num}</div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 13, fontWeight: 700, color: theme.primaryText, lineHeight: 1.3 }}>
                      {step.title}
                    </div>
                    <span style={{
                      display: 'inline-block', marginTop: 4,
                      fontSize: 8.5, fontWeight: 800, letterSpacing: '.06em',
                      padding: '2px 7px', borderRadius: 20,
                      background: ps.bg, color: ps.color, border: `1px solid ${ps.border}`,
                    }}>{step.priority} PRIORITY</span>
                  </div>
                  <div style={{
                    fontSize: 11, color: theme.mutedText, flexShrink: 0,
                    transform: isOpen ? 'rotate(180deg)' : 'rotate(0)',
                    transition: 'transform .25s',
                  }}>▾</div>
                </div>

                {isOpen && (
                  <div style={{ padding: '0 13px 14px', borderTop: `1px solid ${theme.softBorder}` }}>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 7, marginTop: 10 }}>
                      {step.subsections.map((sub: any, subi: number) => (
                        <div key={subi} style={{
                          borderRadius: 9,
                          background: sub.bg === 'transparent' ? theme.raisedBg : sub.bg,
                          border: `1px solid ${sub.border === 'transparent' ? theme.softBorder : sub.border}`,
                          padding: '9px 11px',
                        }}>
                          {sub.label && (
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 7 }}>
                              <div style={{
                                display: 'inline-flex', alignItems: 'center', gap: 3,
                                fontSize: 9, fontWeight: 800, color: sub.color,
                                letterSpacing: '.05em', textTransform: 'uppercase',
                              }}>
                                {sub.icon} {sub.label}
                              </div>
                              {sub.key === 'tool' && promptText && <CopyPromptBtn text={promptText} isDark={isDark} />}
                            </div>
                          )}
                          <div className="playbook-markdown" style={{ fontSize: '0.84rem', color: theme.secondaryText, lineHeight: 1.75 }}>
                            <ReactMarkdown remarkPlugins={[remarkGfm]}>{formatSectionMarkdown(sub.content)}</ReactMarkdown>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            );
          }) : (
            <div className="playbook-markdown" style={{ fontSize: '0.875rem', color: theme.pageText, lineHeight: 1.8 }}>
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{formatSectionMarkdown(playbookText)}</ReactMarkdown>
            </div>
          )}

          {/* Week 1 Checklist */}
          {dayTasks.length > 0 && (
            <div style={{
              background: theme.panelBg, borderRadius: 16, border: `1px solid ${theme.border}`,
              padding: '1.1rem 1.25rem', marginTop: 10, boxShadow: theme.shadow,
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
                <div>
                  <div style={{ fontSize: 9, color: '#7c3aed', fontWeight: 700, letterSpacing: '.12em', textTransform: 'uppercase' }}>Week 1 Execution Checklist</div>
                  <div style={{ fontSize: 15, fontWeight: 800, color: theme.primaryText, marginTop: 2 }}>Monday — Friday</div>
                </div>
                <div style={{
                  background: checkCount === dayTasks.length ? (isDark ? '#0f2f1b' : '#dcfce7') : theme.accentBg,
                  borderRadius: 9, padding: '7px 11px', textAlign: 'center', minWidth: 46,
                }}>
                  <div style={{ fontSize: 18, fontWeight: 800, color: checkCount === dayTasks.length ? '#16a34a' : '#7c3aed' }}>
                    {checkCount}/{dayTasks.length}
                  </div>
                  <div style={{ fontSize: 8, color: theme.mutedText }}>Done</div>
                </div>
              </div>
              <div style={{ height: 5, borderRadius: 3, background: theme.progressBg, marginBottom: 10 }}>
                <div style={{
                  height: '100%', borderRadius: 3,
                  background: checkCount === dayTasks.length ? '#16a34a' : 'linear-gradient(90deg, #7c3aed, #8b5cf6)',
                  width: `${dayTasks.length ? (checkCount / dayTasks.length) * 100 : 0}%`,
                  transition: 'width .4s ease',
                }} />
              </div>
              {dayTasks.map((item: any) => (
                <div key={item.day} onClick={() => toggleCheck(item.day)} style={{
                  display: 'flex', gap: 11, alignItems: 'flex-start',
                  padding: '9px 11px', borderRadius: 9, marginBottom: 5, cursor: 'pointer',
                  background: checks[item.day] ? (isDark ? '#0d2b24' : '#f0fdf4') : theme.raisedBg,
                  border: `1px solid ${checks[item.day] ? (isDark ? '#047857' : '#bbf7d0') : theme.softBorder}`,
                  transition: 'all .2s',
                }}>
                  <div style={{
                    width: 18, height: 18, borderRadius: 5, flexShrink: 0, marginTop: 2,
                    border: checks[item.day] ? 'none' : `2px solid ${isDark ? '#64748b' : '#d1d5db'}`,
                    background: checks[item.day] ? '#16a34a' : theme.panelBg,
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    transition: 'all .2s',
                  }}>
                    {checks[item.day] && <span style={{ fontSize: 10, color: '#fff', fontWeight: 700 }}>✓</span>}
                  </div>
                  <div>
                    <span style={{ fontSize: 9, fontWeight: 700, color: '#7c3aed', letterSpacing: '.06em', marginRight: 6 }}>{item.day}</span>
                    <span style={{
                      fontSize: 12, color: checks[item.day] ? theme.mutedText : theme.secondaryText,
                      textDecoration: checks[item.day] ? 'line-through' : 'none', lineHeight: 1.5,
                    }}>{item.task}</span>
                  </div>
                </div>
              ))}
              {(() => {
                const quoteMatch = checklist.match(/"([^"]+)"/);
                return quoteMatch ? (
                  <div style={{ marginTop: 10, padding: '10px 12px', borderRadius: 9, borderLeft: '3px solid #7c3aed', background: theme.accentBgStrong }}>
                    <div style={{ fontSize: 11.5, color: isDark ? '#c4b5fd' : '#4c1d95', fontStyle: 'italic', lineHeight: 1.65 }}>"{quoteMatch[1]}"</div>
                  </div>
                ) : null;
              })()}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default PlaybookViewer;
