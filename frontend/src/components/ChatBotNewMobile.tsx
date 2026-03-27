import { useState, useRef, useEffect, useCallback } from 'react';
import { Send, Bot, User, Mic, MicOff, Package, Box, Gift, ArrowLeft, Plus, MessageSquare, ShoppingCart, Scale, Users, Sparkles, Youtube, History, X, Menu, Edit3, Chrome, Zap, Brain, Copy, TrendingUp, FileText, Lock, Shield, CreditCard, BarChart3, Code } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import './ChatBotNewMobile.css';
import { getApiBaseRequired } from '../config/apiBase';
import { formatCompaniesForDisplay, analyzeMarketGaps } from '../utils/csvParser';

// ── Markdown normaliser — ensures consistent heading levels across LLM output ──
const formatSectionMarkdown = (text) => {
  let r = text;
  r = r.replace(/^\*\*([A-Z][A-Z &\-\/():'0-9,.]+?)\*\*\s*$/gm, (_, l) => `### ${l.trim()}`);
  r = r.replace(/^(?![#>|*\-])([A-Z][A-Z &\-\/():'0-9,.]{7,})\s*$/gm, (_, l) => `### ${l.trim()}`);
  r = r.replace(/^(?:#{0,4}\s*)?(?:\*\*)?STEP\s+(\d{1,2})\s*[\u2192\->]+\s*(.+?)(?:\*\*)?\s*$/gm,
    (_, n, t) => `#### STEP ${n} → ${t.trim()}`);
  return r;
};

// ── Parse playbook text into structured steps ──
const parsePlaybookSteps = (text) => {
  const steps = [];
  let checklist = '';
  const checklistMatch = text.match(/(?:#{0,4}\s*)?(?:\*\*)?\s*WEEK\s*1\s*EXECUTION\s*CHECKLIST(?:\*\*)?\s*\n([\s\S]*?)(?=\n(?:#{1,4}|\d+\.)|\Z)/i);
  if (checklistMatch) checklist = checklistMatch[1].trim();
  const normalized = text
    .replace(/^(?:#{0,3}\s*)?(?:\*\*)?STEP\s+(\d{1,2})\s*[—\-–:]\s*(.*?)(?:\*\*)?\s*$/gm, '___STEP_$1___$2')
    .replace(/^(?:#{0,3}\s*)?(?:\*\*)?(\d{1,2})\.\s*(?:\*\*\s*)?(?:The\s+)?[""\u201C]?([^""\u201D\n]+?)[""\u201D]?(?:\*\*)?\s*$/gm, '___STEP_$1___$2');
  const blocks = normalized.split(/^___STEP_(\d+)___(.*)$/m);
  for (let i = 1; i < blocks.length; i += 3) {
    const num = parseInt(blocks[i]);
    const title = blocks[i + 1]?.replace(/\*\*/g, '').trim() || '';
    const body = (blocks[i + 2] || '').trim();
    const SUB_PATTERNS = [
      { key: 'todo',    regex: /(?:#{0,4}\s*)?(?:\*\*)?(?:📌\s*)?WHAT TO DO(?:\*\*)?\s*\n/i,          icon: '📌', label: 'What To Do',       color: '#1d4ed8', bg: '#eff6ff', border: '#bfdbfe' },
      { key: 'tool',    regex: /(?:#{0,4}\s*)?(?:\*\*)?(?:🤖\s*)?TOOL\s*[+&]\s*AI SHORTCUT(?:\*\*)?\s*\n/i, icon: '🤖', label: 'Tool + AI Shortcut', color: '#7c3aed', bg: '#f5f3ff', border: '#ddd6fe' },
      { key: 'example', regex: /(?:#{0,4}\s*)?(?:\*\*)?(?:💡\s*)?REAL EXAMPLE(?:\*\*)?\s*\n/i,         icon: '💡', label: 'Real Example',      color: '#b45309', bg: '#fffbeb', border: '#fde68a' },
      { key: 'edge',    regex: /(?:#{0,4}\s*)?(?:\*\*)?(?:⚡\s*)?THE EDGE(?:\*\*)?\s*\n/i,             icon: '⚡', label: 'The Edge',         color: '#065f46', bg: '#f0fdf4', border: '#bbf7d0' },
    ];
    let remaining = body;
    const subsections = [];
    const positions = [];
    for (const sub of SUB_PATTERNS) {
      const m = remaining.search(sub.regex);
      if (m !== -1) positions.push({ pos: m, sub });
    }
    positions.sort((a, b) => a.pos - b.pos);
    if (positions.length === 0) {
      subsections.push({ icon: '', label: '', content: body, color: '#374151', bg: 'transparent', border: 'transparent' });
    } else {
      const preText = remaining.slice(0, positions[0].pos).trim();
      if (preText) subsections.push({ icon: '', label: '', content: preText, color: '#374151', bg: 'transparent', border: 'transparent' });
      for (let j = 0; j < positions.length; j++) {
        const { sub } = positions[j];
        const start = positions[j].pos;
        const end = j + 1 < positions.length ? positions[j + 1].pos : remaining.length;
        const raw = remaining.slice(start, end);
        const content = raw.replace(sub.regex, '').trim();
        subsections.push({ ...sub, content });
      }
    }
    steps.push({ num, title, subsections });
  }
  return { steps, checklist };
};

// ── Renders structured playbook steps — interactive accordion (mobile) ──
const PlaybookStepsRenderer = ({ content }) => {
  const { steps, checklist } = parsePlaybookSteps(content);
  const [openSteps, setOpenSteps] = useState(() => new Set([0]));
  const [doneSteps, setDoneSteps] = useState(() => new Set());
  const [copiedIdx, setCopiedIdx] = useState(null);

  if (!steps.length) {
    return (
      <div className="playbook-markdown" style={{ fontSize: '0.82rem', color: '#1e293b', lineHeight: 1.7 }}>
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{formatSectionMarkdown(content)}</ReactMarkdown>
      </div>
    );
  }

  const toggleOpen = (i) => setOpenSteps(prev => { const n = new Set(prev); n.has(i) ? n.delete(i) : n.add(i); return n; });
  const toggleDone = (e, i) => { e.stopPropagation(); setDoneSteps(prev => { const n = new Set(prev); n.has(i) ? n.delete(i) : n.add(i); return n; }); };
  const copyPrompt = (e, text, i) => { e.stopPropagation(); navigator.clipboard?.writeText(text).catch(() => {}); setCopiedIdx(i); setTimeout(() => setCopiedIdx(null), 2000); };
  const extractPrompt = (text) => { const m = text.match(/Prompt:\s*["""']?([\s\S]+?)(?:\s*["""']?\s*$)/im); return m ? m[1].trim().replace(/^[""\u201C]|[""\u201D]$/g, '') : null; };

  // Map step title to a Claw Agent name
  const getClawAgent = (title: string) => {
    const t = title.toLowerCase();
    if (/headline|h1|hero|copy|hook|messaging|text|word/i.test(t)) return 'Copy Claw';
    if (/cta|button|conversion|form|signup|book|demo/i.test(t)) return 'CTA Claw';
    if (/seo|google|search|rank|keyword|sitemap|meta/i.test(t)) return 'SEO Claw';
    if (/social|linkedin|twitter|instagram|youtube|content|post/i.test(t)) return 'Content Claw';
    if (/pricing|price|plan|offer|package|tier/i.test(t)) return 'Pricing Claw';
    if (/trust|review|testimonial|proof|case stud/i.test(t)) return 'Trust Claw';
    if (/compet|rival|market|position|differentiat/i.test(t)) return 'Intel Claw';
    if (/email|nurture|drip|sequence|follow.?up/i.test(t)) return 'Nurture Claw';
    if (/landing|page|website|redesign|ux|design/i.test(t)) return 'UX Claw';
    if (/lead|prospect|outreach|cold|pipeline/i.test(t)) return 'Lead Gen Claw';
    if (/automat|workflow|zapier|tool|integrat/i.test(t)) return 'Automation Claw';
    if (/brand|identity|story|narrative|authority/i.test(t)) return 'Brand Claw';
    if (/analytic|track|measure|data|metric|dashboard/i.test(t)) return 'Analytics Claw';
    if (/retention|churn|loyal|repeat|upsell/i.test(t)) return 'Retention Claw';
    if (/ad|paid|campaign|roas|spend|facebook|google ads/i.test(t)) return 'Ads Claw';
    return 'Growth Claw';
  };

  // Sort: HIGH priority steps first, then MEDIUM
  const getPriority = (step) => {
    const t = step.subsections.map((s: any) => s.content).join(' ').toLowerCase();
    return step.num <= 3 || /today|this week|immediately|right now|before anything|foundation/.test(t) ? 'HIGH' : 'MEDIUM';
  };
  const sortedSteps = [...steps].sort((a, b) => {
    const pa = getPriority(a) === 'HIGH' ? 0 : 1;
    const pb = getPriority(b) === 'HIGH' ? 0 : 1;
    return pa - pb;
  });

  const doneCount = doneSteps.size;
  const totalCount = steps.length;
  const pct = Math.round((doneCount / totalCount) * 100);

  return (
    <div>
      {/* Progress bar */}
      <div style={{ marginBottom: '0.85rem', padding: '0.7rem 0.85rem', background: 'linear-gradient(135deg, #faf5ff, #f5f3ff)', borderRadius: '10px', border: '1px solid #e9d5ff' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.4rem' }}>
          <span style={{ fontSize: '0.72rem', fontWeight: 700, color: '#5b21b6' }}>Playbook Progress</span>
          <span style={{ fontSize: '0.72rem', fontWeight: 800, color: doneCount === totalCount ? '#10b981' : '#7c3aed' }}>
            {doneCount === totalCount ? '🎉 All Done!' : `${doneCount} / ${totalCount} done`}
          </span>
        </div>
        <div style={{ height: '5px', background: '#e9d5ff', borderRadius: '99px', overflow: 'hidden' }}>
          <div style={{ height: '100%', width: `${pct}%`, background: doneCount === totalCount ? '#10b981' : 'linear-gradient(90deg, #7c3aed, #4f46e5)', borderRadius: '99px', transition: 'width 0.4s ease' }} />
        </div>
        <div style={{ display: 'flex', gap: '0.25rem', marginTop: '0.5rem', flexWrap: 'wrap' }}>
          {sortedSteps.map((s, i) => (
            <div key={i} title={`Step ${s.num}`} style={{
              width: '20px', height: '20px', borderRadius: '5px', border: '1.5px solid',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: '0.58rem', fontWeight: 700, cursor: 'pointer',
              background: doneSteps.has(i) ? '#10b981' : openSteps.has(i) ? '#f5f3ff' : '#fff',
              borderColor: doneSteps.has(i) ? '#10b981' : openSteps.has(i) ? '#7c3aed' : '#e5e7eb',
              color: doneSteps.has(i) ? '#fff' : openSteps.has(i) ? '#7c3aed' : '#9ca3af',
            }} onClick={() => toggleOpen(i)}>
              {doneSteps.has(i) ? '✓' : s.num}
            </div>
          ))}
        </div>
      </div>

      {/* Step cards */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
        {sortedSteps.map((step, si) => {
          const isOpen = openSteps.has(si);
          const isDone = doneSteps.has(si);
          const priority = getPriority(step);
          const priorityColor = priority === 'HIGH' ? '#dc2626' : '#f59e0b';
          const priorityBg    = priority === 'HIGH' ? '#fee2e2' : '#fef3c7';
          return (
            <div key={si} style={{
              background: '#fff', borderRadius: '12px', overflow: 'hidden',
              border: isDone ? '1.5px solid #10b981' : isOpen ? '1.5px solid #7c3aed' : '1px solid #e5e7eb',
              boxShadow: isOpen ? '0 3px 14px rgba(124,58,237,0.1)' : '0 1px 3px rgba(0,0,0,0.04)',
              transition: 'border-color 0.2s, box-shadow 0.2s',
            }}>
              <div style={{ height: '3px', background: isDone ? '#10b981' : isOpen ? 'linear-gradient(90deg,#7c3aed,#4f46e5)' : '#e5e7eb', transition: 'background 0.2s' }} />
              <div onClick={() => toggleOpen(si)} style={{
                padding: '0.75rem 0.85rem', display: 'flex', alignItems: 'center', gap: '0.6rem',
                cursor: 'pointer', userSelect: 'none',
                background: isDone ? '#f0fdf4' : isOpen ? 'linear-gradient(135deg,#faf5ff,#f5f3ff)' : '#fff',
                transition: 'background 0.2s',
              }}>
                <div onClick={(e) => toggleDone(e, si)} style={{
                  width: '20px', height: '20px', borderRadius: '6px', flexShrink: 0,
                  border: `2px solid ${isDone ? '#10b981' : '#d1d5db'}`,
                  background: isDone ? '#10b981' : '#fff',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  cursor: 'pointer', color: '#fff', fontSize: '0.65rem', fontWeight: 800,
                }}>{isDone ? '✓' : ''}</div>
                <div style={{
                  width: '28px', height: '28px', borderRadius: '8px', flexShrink: 0,
                  background: isDone ? '#10b981' : '#7c3aed', color: '#fff',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  fontSize: '0.72rem', fontWeight: 800,
                }}>{step.num}</div>
                <div style={{ flex: 1 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', flexWrap: 'wrap' }}>
                    <div style={{
                      fontSize: '0.82rem', fontWeight: 800,
                      color: isDone ? '#065f46' : '#1e1b4b',
                      textDecoration: isDone ? 'line-through' : 'none',
                      opacity: isDone ? 0.7 : 1, lineHeight: 1.3,
                    }}>"{step.title}"</div>
                    <span style={{ fontSize: '0.54rem', fontWeight: 800, padding: '1px 5px', borderRadius: '4px', background: priorityBg, color: priorityColor, letterSpacing: '.05em', flexShrink: 0 }}>
                      {priority}
                    </span>
                  </div>
                  <div style={{ fontSize: '0.63rem', color: '#9ca3af', marginTop: '0.1rem' }}>
                    {isOpen ? 'Tap to collapse' : 'Tap to expand'}
                  </div>
                </div>
                <div style={{
                  width: '24px', height: '24px', borderRadius: '50%',
                  background: isOpen ? '#7c3aed' : '#f3f4f6',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  color: isOpen ? '#fff' : '#9ca3af', fontSize: '0.6rem', flexShrink: 0,
                  transform: isOpen ? 'rotate(180deg)' : 'none', transition: 'all 0.25s',
                }}>▼</div>
              </div>

              {isOpen && (
                <div style={{ borderTop: '1px solid #f3f4f6', padding: '0.7rem', display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                  {step.subsections.map((sub, subi) => {
                    const prompt = sub.key === 'tool' ? extractPrompt(sub.content) : null;
                    return (
                      <div key={subi} style={{
                        borderRadius: '8px',
                        background: sub.bg === 'transparent' ? '#fafafa' : sub.bg,
                        border: `1px solid ${sub.border === 'transparent' ? '#f0f0f0' : sub.border}`,
                        padding: '0.65rem 0.75rem', overflow: 'hidden',
                      }}>
                        {sub.label && (
                          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.4rem' }}>
                            <div style={{
                              display: 'inline-flex', alignItems: 'center', gap: '0.3rem',
                              fontSize: '0.62rem', fontWeight: 800, color: sub.color,
                              letterSpacing: '0.06em', textTransform: 'uppercase',
                            }}>
                              <span>{sub.icon}</span> {sub.label}
                            </div>
                            {prompt && (
                              <button onClick={(e) => copyPrompt(e, prompt, si)} style={{
                                display: 'flex', alignItems: 'center', gap: '0.25rem',
                                fontSize: '0.62rem', fontWeight: 700, padding: '2px 7px',
                                borderRadius: '5px', border: 'none', cursor: 'pointer',
                                background: copiedIdx === si ? '#d1fae5' : '#ede9fe',
                                color: copiedIdx === si ? '#065f46' : '#5b21b6',
                              }}>
                                {copiedIdx === si ? '✓ Copied!' : '📋 Copy'}
                              </button>
                            )}
                          </div>
                        )}
                        {prompt && (
                          <div style={{
                            background: '#1e1b4b', color: '#c4b5fd', borderRadius: '7px',
                            padding: '0.55rem 0.7rem', fontSize: '0.72rem', lineHeight: 1.5,
                            marginBottom: '0.5rem', fontFamily: '"SF Mono","Fira Code",monospace',
                            border: '1px solid #4c1d95',
                          }}>
                            <span style={{ color: '#6b7280', fontSize: '0.6rem', display: 'block', marginBottom: '0.25rem' }}>COPY-PASTE PROMPT</span>
                            "{prompt}"
                          </div>
                        )}
                        <div className="playbook-markdown" style={{ fontSize: '0.78rem', color: '#374151', lineHeight: 1.7 }}>
                          <ReactMarkdown remarkPlugins={[remarkGfm]}>
                            {prompt ? sub.content.replace(/Prompt:\s*["""']?[\s\S]+?(?:["""']?\s*$)/im, '').trim() : formatSectionMarkdown(sub.content)}
                          </ReactMarkdown>
                        </div>
                      </div>
                    );
                  })}
                  <button onClick={(e) => toggleDone(e, si)} style={{
                    alignSelf: 'flex-end', padding: '0.4rem 0.85rem',
                    borderRadius: '7px', border: 'none', cursor: 'pointer', fontWeight: 700,
                    fontSize: '0.72rem', transition: 'all 0.2s',
                    background: isDone ? '#d1fae5' : '#7c3aed',
                    color: isDone ? '#065f46' : '#fff',
                  }}>
                    {isDone ? '✓ Marked Done — Undo?' : '✅ Mark as Done'}
                  </button>
                </div>
              )}
            </div>
          );
        })}
      </div>

      {checklist && (
        <div style={{
          marginTop: '0.85rem', background: '#fffbeb', border: '1px solid #fde68a',
          borderRadius: '12px', padding: '0.9rem 1rem',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', marginBottom: '0.6rem' }}>
            <span style={{ fontSize: '1rem' }}>📅</span>
            <span style={{ fontSize: '0.8rem', fontWeight: 800, color: '#92400e' }}>Week 1 Execution Checklist</span>
          </div>
          <div className="playbook-markdown" style={{ fontSize: '0.78rem', color: '#374151', lineHeight: 1.7 }}>
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{checklist}</ReactMarkdown>
          </div>
        </div>
      )}
    </div>
  );
};

// ── Renders website audit in structured visual sections (mobile) ──
const AuditRenderer = ({ content }) => {
  const [openSections, setOpenSections] = useState(() => new Set(['verdict', 'health', 'quickwins']));
  const toggle = (k) => setOpenSections(prev => { const n = new Set(prev); n.has(k) ? n.delete(k) : n.add(k); return n; });
  const SECTIONS = [
    { key: 'verdict',   label: 'Verdict',         icon: '🎯', regex: /VERDICT\s*\n([\s\S]+?)(?=\n(?:HEALTH SCORE|ICP MISMATCHES|QUICK WINS|STRATEGIC FIXES|THE ONE THING|##)|$)/i,  color: '#dc2626', bg: '#fff1f2', border: '#fecdd3' },
    { key: 'health',    label: 'Health Score',    icon: '📊', regex: /HEALTH SCORE\s*\n([\s\S]+?)(?=\n(?:ICP MISMATCHES|QUICK WINS|STRATEGIC FIXES|THE ONE THING|##)|$)/i,          color: '#7c3aed', bg: '#faf5ff', border: '#e9d5ff' },
    { key: 'icp',       label: 'ICP Mismatches',  icon: '👤', regex: /ICP MISMATCHES\s*\n([\s\S]+?)(?=\n(?:QUICK WINS|STRATEGIC FIXES|THE ONE THING|##)|$)/i,                      color: '#b45309', bg: '#fffbeb', border: '#fde68a' },
    { key: 'quickwins', label: 'Quick Wins',      icon: '⚡', regex: /QUICK WINS[^\n]*\n([\s\S]+?)(?=\n(?:STRATEGIC FIXES|THE ONE THING|##)|$)/i,                                  color: '#059669', bg: '#f0fdf4', border: '#bbf7d0' },
    { key: 'strategic', label: 'Strategic Fixes', icon: '🔧', regex: /STRATEGIC FIXES[^\n]*\n([\s\S]+?)(?=\n(?:THE ONE THING|##)|$)/i,                                             color: '#0284c7', bg: '#f0f9ff', border: '#bae6fd' },
    { key: 'onething',  label: 'The One Thing',   icon: '🏆', regex: /THE ONE THING\s*\n([\s\S]+?)(?=\n##|$)/i,                                                                     color: '#7c3aed', bg: '#f5f3ff', border: '#ddd6fe' },
  ];
  const parsed = SECTIONS.map(s => { const m = content.match(s.regex); return m ? { ...s, body: m[1].trim() } : null; }).filter(Boolean);
  if (parsed.length === 0) {
    return (
      <div className="playbook-markdown" style={{ fontSize: '0.82rem', color: '#1e293b', lineHeight: 1.7 }}>
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{formatSectionMarkdown(content)}</ReactMarkdown>
      </div>
    );
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.45rem' }}>
      {parsed.map((sec) => {
        const isOpen = openSections.has(sec.key);
        return (
          <div key={sec.key} style={{ borderRadius: '10px', overflow: 'hidden', border: `1px solid ${sec.border}`, background: '#fff' }}>
            <div style={{ height: '3px', background: sec.color }} />
            <div onClick={() => toggle(sec.key)} style={{
              padding: '0.65rem 0.85rem', cursor: 'pointer', userSelect: 'none',
              background: isOpen ? sec.bg : '#fff',
              display: 'flex', alignItems: 'center', gap: '0.5rem',
            }}>
              <span style={{ fontSize: '0.9rem' }}>{sec.icon}</span>
              <span style={{ fontSize: '0.78rem', fontWeight: 800, color: sec.color, flex: 1 }}>{sec.label}</span>
              <div style={{
                width: '20px', height: '20px', borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center',
                background: isOpen ? sec.color : '#f3f4f6', color: isOpen ? '#fff' : '#9ca3af',
                fontSize: '0.55rem', transform: isOpen ? 'rotate(180deg)' : 'none', transition: 'all 0.25s',
              }}>▼</div>
            </div>
            {isOpen && (
              <div style={{ padding: '0.7rem 0.85rem', borderTop: `1px solid ${sec.border}` }}>
                <div className="playbook-markdown" style={{ fontSize: '0.78rem', color: '#374151', lineHeight: 1.7 }}>
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{formatSectionMarkdown(sec.body)}</ReactMarkdown>
                </div>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
};

// ── Animated counter (mobile) ──
const AnimCounter = ({ target, duration = 1400, decimals = 1 }) => {
  const [val, setVal] = useState(0);
  useEffect(() => {
    const start = performance.now();
    const tick = (now) => {
      const p = Math.min((now - start) / duration, 1);
      setVal((1 - Math.pow(1 - p, 3)) * target);
      if (p < 1) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }, [target, duration]);
  return <span>{val.toFixed(decimals)}</span>;
};

// ── SVG score ring (mobile) ──
const ScoreRing = ({ score, max = 10, size = 110, color, bg = '#f0effa' }) => {
  const r = (size - 12) / 2, circ = 2 * Math.PI * r;
  return (
    <div style={{ position: 'relative', width: size, height: size }}>
      <svg width={size} height={size} style={{ transform: 'rotate(-90deg)' }}>
        <circle cx={size/2} cy={size/2} r={r} fill="none" stroke={bg} strokeWidth={8} />
        <circle cx={size/2} cy={size/2} r={r} fill="none" stroke={color}
          strokeWidth={8} strokeDasharray={circ}
          strokeDashoffset={circ * (1 - score / max)} strokeLinecap="round"
          style={{ transition: 'stroke-dashoffset 1.8s cubic-bezier(.4,0,.2,1)' }} />
      </svg>
      <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center' }}>
        <span style={{ fontSize: 28, fontWeight: 900, color: '#1a1a2e', lineHeight: 1 }}>
          <AnimCounter target={score} />
        </span>
        <span style={{ fontSize: 11, color: '#9ca3af', fontWeight: 500 }}>/{max}</span>
      </div>
    </div>
  );
};

// ── 3-phase container (mobile): Verdict → Quick Wins → Full Playbook ──
const PlaybookPhaseContainer = ({ playbookData }) => {
  const [phase, setPhase] = useState('verdict');
  const [expandedIssue, setExpandedIssue] = useState<number | null>(null);
  const audit = playbookData.websiteAudit || '';

  // Shared parser (same logic as desktop)
  const ex = (pat) => { const m = audit.match(pat); return m ? m[1].trim() : null; };
  const numSection = (n) => ex(new RegExp(`${n}\\.\\s[^\\n]+\\n([\\s\\S]+?)(?=\\n${n+1}\\.\\s|$)`, 'i'));

  const overallM = audit.match(/Overall[:\s]+(\d+(?:\.\d+)?)\s*\/\s*10/i);
  const anyScoreM = audit.match(/(\d+(?:\.\d+)?)\s*\/\s*10/);
  const score = overallM ? parseFloat(overallM[1]) : anyScoreM ? parseFloat(anyScoreM[1]) : null;

  const metricRows: { label: string; score: number }[] = [];
  for (const row of audit.matchAll(/^([^\t\n]{10,60})\t(\d+)\/10\t([^\n]+)/gm)) {
    const s = parseInt(row[2]);
    if (s > 0 && s <= 10) metricRows.push({ label: row[1].trim(), score: s });
  }

  const issueBlocks: { title: string; why: string; impact: string; who: string }[] = [];
  const issueSection = numSection(5) || ex(/ICP MISMATCHES\s*\n([\s\S]+?)(?=\n(?:QUICK WINS|STRATEGIC|THE ONE|##)|$)/i) || '';
  if (issueSection) {
    const blockRe = /^([^\n]+)\n+Your site says:[\s\S]+?Why you(?:['''\u2019]re|re) losing the deal:\s*([\s\S]+?)(?=\nRevenue Impact:)\nRevenue Impact:\s*(HIGH|MEDIUM|LOW)[^\n]*(?:\nWho this blocks:\s*([^\n]+))?/gim;
    for (const m of issueSection.matchAll(blockRe)) {
      issueBlocks.push({
        title: m[1].replace(/^[""'\u201C\u2018]|[""'\u201D\u2019]$/g, '').trim(),
        why: m[2].replace(/\n/g, ' ').trim().slice(0, 150),
        impact: m[3].toUpperCase(),
        who: m[4] ? m[4].trim() : '',
      });
    }
  }

  const isNumbered = /\d\.\s+(?:Who|Your Site|The 30|The Big|What Your)/i.test(audit);
  const quickFix  = isNumbered ? numSection(3) : ex(/QUICK WINS[^\n]*\n([\s\S]+?)(?=\n(?:STRATEGIC|THE ONE|##)|$)/i);
  const bigBuild  = isNumbered ? numSection(4) : ex(/STRATEGIC FIXES[^\n]*\n([\s\S]+?)(?=\n(?:THE ONE|##)|$)/i);
  const oneThing  = ex(/THE ONE THING\s*\n([\s\S]+?)(?=\n##|$)/i);
  const capsVerdict = ex(/^VERDICT\s*\n([\s\S]+?)(?=\n(?:HEALTH SCORE|ICP|QUICK|STRATEGIC|THE ONE)|$)/im);

  // Before/After H1 from quick fix
  const allQuotes = quickFix ? [...quickFix.matchAll(/["""\u201C]([^"""\u201D]{10,})["""\u201D]/gi)] : [];
  const beforeH1 = allQuotes.length > 0 ? allQuotes[0][1] : null;
  const afterH1 = allQuotes.length > 1 ? allQuotes[1][1] : null;

  // Week 1 checklist from playbook
  const weekDays: { day: string; task: string }[] = [];
  const weekM = (playbookData.playbook || '').match(/WEEK 1[^\n]*\n([\s\S]+?)(?=\nThe contract|$)/i);
  if (weekM) {
    for (const line of weekM[1].split('\n')) {
      const dm = line.match(/^(Monday|Tuesday|Wednesday|Thursday|Friday):\s*(.+)/i);
      if (dm) weekDays.push({ day: dm[1], task: dm[2].trim() });
    }
  }

  const scoreColor = !score ? '#6b7280' : score >= 7 ? '#10b981' : score >= 5 ? '#f59e0b' : '#dc2626';
  const scoreBg    = !score ? '#f3f4f6' : score >= 7 ? '#d1fae5' : score >= 5 ? '#fef3c7' : '#fee2e2';
  const scoreLabel = !score ? '' : score >= 8 ? 'Top 5% — you know what you\'re doing' : score >= 7 ? 'Good foundation, now execute' : score >= 5 ? 'Good bones, lazy execution' : score >= 3 ? 'Your competitors are thanking you' : 'Burning money every day this stays live';

  const highIssues = issueBlocks.filter(b => b.impact === 'HIGH');
  const medIssues  = issueBlocks.filter(b => b.impact === 'MEDIUM');
  const allIssues  = [...highIssues, ...medIssues];

  // Revenue leak estimate
  const revLeakMin = highIssues.length * 150000 + medIssues.length * 40000;
  const revLeakMax = highIssues.length * 350000 + medIssues.length * 100000;
  const formatINR = (n: number) => n >= 100000 ? `₹${(n / 100000).toFixed(1)}L` : `₹${(n / 1000).toFixed(0)}K`;

  // Projected score if HIGH issues fixed
  const projectedScore = score !== null ? Math.min(10, score + highIssues.length * 0.9 + medIssues.length * 0.3) : null;

  const PHASES = ['verdict', 'quickwins', 'playbook'];
  const phaseLabels = { verdict: 'Verdict', quickwins: 'Quick Wins', playbook: 'Playbook' };
  const pi = PHASES.indexOf(phase);

  const SCard = ({ label, color, border, children }) => (
    <div style={{ background: '#fff', borderRadius: 10, border: `1px solid ${border}`, borderLeft: `3px solid ${color}`, padding: '0.9rem 1rem', marginBottom: '0.65rem' }}>
      <div style={{ fontSize: '0.6rem', color, fontWeight: 800, letterSpacing: '.07em', textTransform: 'uppercase', marginBottom: '0.45rem' }}>{label}</div>
      <div className="playbook-markdown" style={{ fontSize: '0.78rem', color: '#374151', lineHeight: 1.7 }}>{children}</div>
    </div>
  );

  const NextBtn = ({ label, to }) => (
    <button onClick={() => setPhase(to)} style={{
      width: '100%', padding: '0.85rem', marginTop: '0.4rem',
      background: 'linear-gradient(135deg,#7c3aed,#4f46e5)',
      border: 'none', borderRadius: 12, cursor: 'pointer',
      fontSize: '0.82rem', fontWeight: 700, color: '#fff', fontFamily: 'inherit',
      boxShadow: '0 3px 14px rgba(124,58,237,.25)',
    }}>{label}</button>
  );

  return (
    <div>
      {/* Phase tabs */}
      <div style={{ display: 'flex', borderBottom: '2px solid #f3f4f6', marginBottom: '1rem' }}>
        {PHASES.map((p, i) => (
          <button key={p} onClick={() => setPhase(p)} style={{
            background: 'none', border: 'none', cursor: 'pointer', flex: 1,
            display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '0.3rem',
            padding: '0.6rem 0.5rem', borderBottom: phase === p ? '2px solid #7c3aed' : '2px solid transparent',
            marginBottom: '-2px', fontFamily: 'inherit',
          }}>
            <span style={{
              width: 18, height: 18, borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: '0.55rem', fontWeight: 800,
              background: i <= pi ? '#7c3aed' : '#e5e7eb', color: i <= pi ? '#fff' : '#9ca3af',
            }}>{i + 1}</span>
            <span style={{ fontSize: '0.72rem', fontWeight: phase === p ? 700 : 400, color: phase === p ? '#1e1b4b' : '#9ca3af' }}>
              {phaseLabels[p]}
            </span>
          </button>
        ))}
      </div>

      {/* ── VERDICT ── */}
      {phase === 'verdict' && (
        <div>
          {/* Score + label */}
          <div style={{ background: '#fff', borderRadius: 12, border: '1px solid #e5e7eb', padding: '1.1rem', marginBottom: '0.75rem', display: 'flex', alignItems: 'center', gap: '1rem' }}>
            {score !== null && <ScoreRing score={score} size={90} color={scoreColor} bg={scoreBg} />}
            <div>
              <div style={{ fontSize: '0.56rem', color: '#9ca3af', fontWeight: 600, letterSpacing: '.08em', textTransform: 'uppercase' }}>Health Score</div>
              <div style={{ fontSize: '0.88rem', fontWeight: 900, color: scoreColor, lineHeight: 1.2, marginTop: '0.1rem' }}>{scoreLabel}</div>
              {allIssues.length > 0 && (
                <div style={{ fontSize: '0.64rem', color: '#6b7280', marginTop: '0.25rem' }}>
                  <span style={{ color: '#dc2626', fontWeight: 700 }}>{highIssues.length} HIGH</span> · <span style={{ color: '#f59e0b', fontWeight: 700 }}>{medIssues.length} MEDIUM</span>
                </div>
              )}
              {revLeakMin > 0 && (
                <div style={{ fontSize: '0.66rem', color: '#dc2626', fontWeight: 700, marginTop: '0.2rem' }}>
                  Leak: {formatINR(revLeakMin)} – {formatINR(revLeakMax)}/mo
                </div>
              )}
              {projectedScore !== null && projectedScore > (score || 0) + 0.5 && (
                <div style={{ fontSize: '0.62rem', color: '#059669', marginTop: '0.15rem', fontWeight: 600 }}>
                  Fix HIGHs → {projectedScore.toFixed(1)}/10
                </div>
              )}
            </div>
          </div>

          {/* Metric pills */}
          {metricRows.length > 0 && (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(110px,1fr))', gap: '0.45rem', marginBottom: '0.75rem' }}>
              {metricRows.map((m, i) => {
                const c = m.score >= 7 ? '#10b981' : m.score >= 5 ? '#f59e0b' : '#dc2626';
                return (
                  <div key={i} style={{ background: '#fff', borderRadius: 10, border: '1px solid #e5e7eb', padding: '0.6rem 0.75rem' }}>
                    <div style={{ fontSize: '1.25rem', fontWeight: 900, color: c }}>{m.score}<span style={{ fontSize: '0.65rem', color: '#d1d5db' }}>/10</span></div>
                    <div style={{ fontSize: '0.62rem', color: '#6b7280', lineHeight: 1.3 }}>{m.label.length > 35 ? m.label.slice(0, 33) + '…' : m.label}</div>
                  </div>
                );
              })}
            </div>
          )}

          {/* Issue cards — expandable */}
          {allIssues.length > 0 ? (
            <>
              <div style={{ fontSize: '0.62rem', color: '#9ca3af', fontWeight: 700, letterSpacing: '.06em', textTransform: 'uppercase', marginBottom: '0.5rem' }}>Where You're Losing Deals</div>
              {allIssues.map((issue, i) => {
                const isHigh = issue.impact === 'HIGH';
                const ic = isHigh ? '#dc2626' : '#f59e0b';
                const iborder = isHigh ? '#fecdd3' : '#fde68a';
                const ib = isHigh ? '#fee2e2' : '#fef3c7';
                const isExp = expandedIssue === i;
                return (
                  <div key={i} onClick={() => setExpandedIssue(isExp ? null : i)} style={{ background: '#fff', borderRadius: 10, border: `1px solid ${iborder}`, padding: '0.75rem 0.9rem', marginBottom: '0.5rem', cursor: 'pointer', transition: 'all 0.2s' }}>
                    <div style={{ display: 'flex', gap: '0.6rem', alignItems: 'flex-start' }}>
                      <span style={{ fontSize: '0.58rem', fontWeight: 800, padding: '1px 5px', borderRadius: '4px', background: ib, color: ic, flexShrink: 0, marginTop: '0.1rem', letterSpacing: '.04em' }}>{issue.impact}</span>
                      <div style={{ flex: 1 }}>
                        <div style={{ fontSize: '0.78rem', fontWeight: 700, color: '#111827' }}>{issue.title}</div>
                        {issue.who && <div style={{ fontSize: '0.65rem', color: '#9ca3af', marginTop: '0.1rem' }}>Blocks: {issue.who}</div>}
                      </div>
                      <span style={{ fontSize: '0.55rem', color: '#9ca3af', transition: 'transform 0.2s', transform: isExp ? 'rotate(180deg)' : 'none', flexShrink: 0, marginTop: '0.15rem' }}>{'\u25BC'}</span>
                    </div>
                    {isExp && issue.why && (
                      <div style={{ fontSize: '0.72rem', color: '#6b7280', lineHeight: 1.5, marginTop: '0.5rem', paddingTop: '0.45rem', borderTop: '1px solid #f3f4f6' }}>
                        {issue.why}
                      </div>
                    )}
                  </div>
                );
              })}
            </>
          ) : capsVerdict ? (
            <SCard label="🎯 Verdict" color="#dc2626" border="#fecdd3">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{formatSectionMarkdown(capsVerdict)}</ReactMarkdown>
            </SCard>
          ) : (
            <AuditRenderer content={audit} />
          )}
          <NextBtn label="See What To Fix First →" to="quickwins" />
        </div>
      )}

      {/* ── QUICK WINS ── */}
      {phase === 'quickwins' && (
        <div>
          {quickFix && (
            <div style={{ background: '#fff', borderRadius: 10, border: '1px solid #bbf7d0', borderLeft: '3px solid #059669', padding: '0.9rem 1rem', marginBottom: '0.65rem' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', marginBottom: '0.55rem' }}>
                <span style={{ fontSize: '0.55rem', fontWeight: 800, padding: '1px 6px', borderRadius: '5px', background: '#d1fae5', color: '#065f46', letterSpacing: '.04em' }}>5 MIN</span>
                <span style={{ fontSize: '0.6rem', color: '#059669', fontWeight: 800, letterSpacing: '.07em', textTransform: 'uppercase' }}>The 30-Minute Fix</span>
              </div>
              {beforeH1 && afterH1 && (
                <div style={{ marginBottom: '0.7rem', background: '#f9fafb', borderRadius: 8, padding: '0.7rem 0.85rem' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.4rem' }}>
                    <span style={{ fontSize: '0.52rem', fontWeight: 800, color: '#dc2626', minWidth: 30, textAlign: 'right' }}>NOW</span>
                    <div style={{ flex: 1, padding: '0.4rem 0.6rem', borderRadius: 7, background: '#fef2f2', border: '1px solid #fecdd3', fontSize: '0.72rem', color: '#991b1b', textDecoration: 'line-through', fontStyle: 'italic' }}>
                      {'\u201C'}{beforeH1}{'\u201D'}
                    </div>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <span style={{ fontSize: '0.52rem', fontWeight: 800, color: '#059669', minWidth: 30, textAlign: 'right' }}>FIX</span>
                    <div style={{ flex: 1, padding: '0.4rem 0.6rem', borderRadius: 7, background: '#f0fdf4', border: '1px solid #bbf7d0', fontSize: '0.72rem', color: '#065f46', fontWeight: 600 }}>
                      {'\u201C'}{afterH1}{'\u201D'}
                    </div>
                  </div>
                </div>
              )}
              <div className="playbook-markdown" style={{ fontSize: '0.78rem', color: '#374151', lineHeight: 1.7 }}>
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{formatSectionMarkdown(quickFix)}</ReactMarkdown>
              </div>
            </div>
          )}
          {bigBuild && (
            <div style={{ background: '#fff', borderRadius: 10, border: '1px solid #bae6fd', borderLeft: '3px solid #0284c7', padding: '0.9rem 1rem', marginBottom: '0.65rem' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', marginBottom: '0.55rem' }}>
                <span style={{ fontSize: '0.55rem', fontWeight: 800, padding: '1px 6px', borderRadius: '5px', background: '#dbeafe', color: '#1e40af', letterSpacing: '.04em' }}>1-2 WEEKS</span>
                <span style={{ fontSize: '0.6rem', color: '#0284c7', fontWeight: 800, letterSpacing: '.07em', textTransform: 'uppercase' }}>The Big Build</span>
              </div>
              <div className="playbook-markdown" style={{ fontSize: '0.78rem', color: '#374151', lineHeight: 1.7 }}>
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{formatSectionMarkdown(bigBuild)}</ReactMarkdown>
              </div>
            </div>
          )}
          {oneThing && (
            <SCard label="🏆 The One Thing" color="#7c3aed" border="#ddd6fe">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{formatSectionMarkdown(oneThing)}</ReactMarkdown>
            </SCard>
          )}
          {playbookData.toolMatrix && (
            <SCard label="🛠 Tool Matrix" color="#059669" border="#bbf7d0">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{formatSectionMarkdown(playbookData.toolMatrix)}</ReactMarkdown>
            </SCard>
          )}
          {!quickFix && !bigBuild && audit && <AuditRenderer content={audit} />}
          <NextBtn label="View Full 10-Step Playbook →" to="playbook" />
        </div>
      )}

      {/* ── FULL PLAYBOOK ── */}
      {phase === 'playbook' && (
        <div>
          {/* Week 1 Blueprint */}
          {weekDays.length > 0 && (
            <div style={{ background: 'linear-gradient(135deg,#faf5ff,#f5f3ff)', borderRadius: 10, border: '1px solid #ddd6fe', padding: '0.85rem 1rem', marginBottom: '0.75rem' }}>
              <div style={{ fontSize: '0.6rem', color: '#7c3aed', fontWeight: 800, letterSpacing: '.07em', textTransform: 'uppercase', marginBottom: '0.5rem' }}>
                Your Week 1 Blueprint
              </div>
              {weekDays.map((d, i) => (
                <div key={i} style={{ display: 'flex', gap: '0.5rem', padding: '0.3rem 0', borderBottom: i < weekDays.length - 1 ? '1px solid #ede9fe' : 'none', alignItems: 'flex-start' }}>
                  <span style={{ fontSize: '0.65rem', fontWeight: 700, color: '#5b21b6', minWidth: 65 }}>{d.day}</span>
                  <span style={{ fontSize: '0.7rem', color: '#4b5563', lineHeight: 1.4 }}>{d.task}</span>
                </div>
              ))}
            </div>
          )}

          {playbookData.icpCard && (
            <div style={{ background: 'linear-gradient(135deg,#f0f9ff,#e0f2fe)', borderRadius: 10, border: '1px solid rgba(14,165,233,.25)', padding: '0.9rem 1rem', marginBottom: '0.75rem' }}>
              <div style={{ fontSize: '0.6rem', color: '#0284c7', fontWeight: 800, letterSpacing: '.07em', textTransform: 'uppercase', marginBottom: '0.5rem' }}>👤 Ideal Customer Profile</div>
              <div className="playbook-markdown" style={{ fontSize: '0.78rem', color: '#1e293b', lineHeight: 1.7 }}>
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{formatSectionMarkdown(playbookData.icpCard)}</ReactMarkdown>
              </div>
            </div>
          )}
          {playbookData.playbook && <PlaybookStepsRenderer content={playbookData.playbook} />}
          {playbookData.latencies && Object.keys(playbookData.latencies).length > 0 && (
            <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap', fontSize: '0.65rem', color: '#9ca3af', marginTop: '0.4rem' }}>
              {Object.entries(playbookData.latencies).map(([agent, ms]) => (
                <span key={agent}>{agent}: {(ms as number / 1000).toFixed(1)}s</span>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

// Generate unique message IDs to prevent React key conflicts
const generateUniqueId = () => `msg-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;

// ============================================
// SOLUTION RECOMMENDATIONS DATA
// ============================================

// Chrome Extensions & Plugins mapped to categories
const CHROME_EXTENSIONS_DATA = {
  'social-media': [
    { name: 'Buffer', url: 'https://chrome.google.com/webstore/detail/buffer', description: 'Schedule posts across all social platforms', free: true },
    { name: 'Hootsuite', url: 'https://chrome.google.com/webstore/detail/hootsuite', description: 'Social media management dashboard', free: false },
    { name: 'Canva', url: 'https://chrome.google.com/webstore/detail/canva', description: 'Create stunning social graphics instantly', free: true }
  ],
  'seo-leads': [
    { name: 'SEOquake', url: 'https://chrome.google.com/webstore/detail/seoquake', description: 'Instant SEO metrics for any page', free: true },
    { name: 'Keywords Everywhere', url: 'https://chrome.google.com/webstore/detail/keywords-everywhere', description: 'See search volume on Google', free: false },
    { name: 'Hunter.io', url: 'https://chrome.google.com/webstore/detail/hunter', description: 'Find email addresses from any website', free: true },
    { name: 'Ubersuggest', url: 'https://chrome.google.com/webstore/detail/ubersuggest', description: 'SEO insights and keyword ideas', free: true }
  ],
  'ads-marketing': [
    { name: 'Facebook Pixel Helper', url: 'https://chrome.google.com/webstore/detail/facebook-pixel-helper', description: 'Debug your Facebook pixel', free: true },
    { name: 'Google Tag Assistant', url: 'https://chrome.google.com/webstore/detail/tag-assistant', description: 'Verify Google tags are working', free: true },
    { name: 'Adblock (for competitor research)', url: 'https://chrome.google.com/webstore/detail/adblock', description: 'See ads competitors are running', free: true }
  ],
  'automation': [
    { name: 'Bardeen', url: 'https://chrome.google.com/webstore/detail/bardeen', description: 'Automate any repetitive browser task', free: true },
    { name: 'Zapier', url: 'https://chrome.google.com/webstore/detail/zapier', description: 'Connect apps and automate workflows', free: true },
    { name: 'Data Scraper', url: 'https://chrome.google.com/webstore/detail/data-scraper', description: 'Extract data from web pages', free: true }
  ],
  'productivity': [
    { name: 'Notion Web Clipper', url: 'https://chrome.google.com/webstore/detail/notion-web-clipper', description: 'Save anything to Notion', free: true },
    { name: 'Loom', url: 'https://chrome.google.com/webstore/detail/loom', description: 'Record quick video messages', free: true },
    { name: 'Grammarly', url: 'https://chrome.google.com/webstore/detail/grammarly', description: 'Write better emails and docs', free: true },
    { name: 'Otter.ai', url: 'https://chrome.google.com/webstore/detail/otter', description: 'AI meeting notes & transcription', free: true }
  ],
  'research': [
    { name: 'Similar Web', url: 'https://chrome.google.com/webstore/detail/similarweb', description: 'Website traffic insights', free: true },
    { name: 'Wappalyzer', url: 'https://chrome.google.com/webstore/detail/wappalyzer', description: 'See what tech websites use', free: true },
    { name: 'ChatGPT for Google', url: 'https://chrome.google.com/webstore/detail/chatgpt-for-google', description: 'AI answers alongside search', free: true }
  ],
  'finance': [
    { name: 'DocuSign', url: 'https://chrome.google.com/webstore/detail/docusign', description: 'E-sign documents from browser', free: false },
    { name: 'Expensify', url: 'https://chrome.google.com/webstore/detail/expensify', description: 'Capture receipts instantly', free: true }
  ],
  'support': [
    { name: 'Intercom', url: 'https://chrome.google.com/webstore/detail/intercom', description: 'Customer messaging platform', free: false },
    { name: 'Zendesk', url: 'https://chrome.google.com/webstore/detail/zendesk', description: 'Support ticket management', free: false },
    { name: 'Tidio', url: 'https://chrome.google.com/webstore/detail/tidio', description: 'Live chat + AI chatbot', free: true }
  ]
};

// Custom GPTs mapped to problem categories
const CUSTOM_GPTS_DATA = {
  'content-creation': [
    { name: 'Canva GPT', url: 'https://chat.openai.com/g/canva', description: 'Design social posts with AI', rating: '4.8' },
    { name: 'Copywriter GPT', url: 'https://chat.openai.com/g/copywriter', description: 'Write converting ad copy', rating: '4.7' },
    { name: 'Video Script Writer', url: 'https://chat.openai.com/g/video-script', description: 'Scripts for YouTube & Reels', rating: '4.6' }
  ],
  'seo-marketing': [
    { name: 'SEO GPT', url: 'https://chat.openai.com/g/seo', description: 'Keyword research & optimization', rating: '4.8' },
    { name: 'Blog Post Generator', url: 'https://chat.openai.com/g/blog-generator', description: 'SEO-optimized articles', rating: '4.7' },
    { name: 'Landing Page Expert', url: 'https://chat.openai.com/g/landing-page', description: 'High-converting page copy', rating: '4.5' }
  ],
  'sales-leads': [
    { name: 'Cold Email GPT', url: 'https://chat.openai.com/g/cold-email', description: 'Personalized outreach emails', rating: '4.6' },
    { name: 'Sales Pitch Creator', url: 'https://chat.openai.com/g/sales-pitch', description: 'Compelling sales scripts', rating: '4.5' },
    { name: 'LinkedIn Outreach', url: 'https://chat.openai.com/g/linkedin-outreach', description: 'Professional connection messages', rating: '4.4' }
  ],
  'automation': [
    { name: 'Automation Expert', url: 'https://chat.openai.com/g/automation', description: 'Design workflow automations', rating: '4.7' },
    { name: 'Zapier Helper', url: 'https://chat.openai.com/g/zapier-helper', description: 'Build Zaps step by step', rating: '4.5' },
    { name: 'Excel Formula GPT', url: 'https://chat.openai.com/g/excel-formula', description: 'Complex formulas explained', rating: '4.8' }
  ],
  'data-analysis': [
    { name: 'Data Analyst GPT', url: 'https://chat.openai.com/g/data-analyst', description: 'Analyze data & create charts', rating: '4.9' },
    { name: 'SQL Expert', url: 'https://chat.openai.com/g/sql-expert', description: 'Write & optimize queries', rating: '4.7' },
    { name: 'Dashboard Designer', url: 'https://chat.openai.com/g/dashboard', description: 'Plan effective dashboards', rating: '4.5' }
  ],
  'legal-contracts': [
    { name: 'Contract Reviewer', url: 'https://chat.openai.com/g/contract-review', description: 'Spot risky clauses', rating: '4.6' },
    { name: 'Legal Document Drafter', url: 'https://chat.openai.com/g/legal-drafter', description: 'Draft basic agreements', rating: '4.5' }
  ],
  'hr-recruiting': [
    { name: 'Job Description Writer', url: 'https://chat.openai.com/g/job-description', description: 'Compelling job posts', rating: '4.7' },
    { name: 'Interview Question GPT', url: 'https://chat.openai.com/g/interview-questions', description: 'Role-specific questions', rating: '4.6' },
    { name: 'Resume Reviewer', url: 'https://chat.openai.com/g/resume-reviewer', description: 'Screen candidates faster', rating: '4.5' }
  ],
  'customer-support': [
    { name: 'Support Response GPT', url: 'https://chat.openai.com/g/support-response', description: 'Draft customer replies', rating: '4.6' },
    { name: 'FAQ Generator', url: 'https://chat.openai.com/g/faq-generator', description: 'Build knowledge bases', rating: '4.5' }
  ],
  'personal-productivity': [
    { name: 'Task Prioritizer', url: 'https://chat.openai.com/g/task-prioritizer', description: 'Organize your to-dos', rating: '4.7' },
    { name: 'Meeting Summarizer', url: 'https://chat.openai.com/g/meeting-summarizer', description: 'Notes from transcripts', rating: '4.8' },
    { name: 'Learning Coach', url: 'https://chat.openai.com/g/learning-coach', description: 'Personalized study plans', rating: '4.6' }
  ]
};

// Function to get relevant extensions based on category
const getRelevantExtensions = (category, goal) => {
  const categoryLower = (category || '').toLowerCase();
  const goalLower = (goal || '').toLowerCase();

  let extensions = [];

  if (categoryLower.includes('social') || categoryLower.includes('content') || categoryLower.includes('post')) {
    extensions = [...(CHROME_EXTENSIONS_DATA['social-media'] || [])];
  }
  if (categoryLower.includes('seo') || categoryLower.includes('lead') || categoryLower.includes('google')) {
    extensions = [...extensions, ...(CHROME_EXTENSIONS_DATA['seo-leads'] || [])];
  }
  if (categoryLower.includes('ad') || categoryLower.includes('marketing') || categoryLower.includes('roi')) {
    extensions = [...extensions, ...(CHROME_EXTENSIONS_DATA['ads-marketing'] || [])];
  }
  if (categoryLower.includes('automate') || categoryLower.includes('workflow') || goalLower.includes('save-time')) {
    extensions = [...extensions, ...(CHROME_EXTENSIONS_DATA['automation'] || [])];
  }
  if (categoryLower.includes('meeting') || categoryLower.includes('email') || categoryLower.includes('draft')) {
    extensions = [...extensions, ...(CHROME_EXTENSIONS_DATA['productivity'] || [])];
  }
  if (categoryLower.includes('competitor') || categoryLower.includes('research') || categoryLower.includes('trend')) {
    extensions = [...extensions, ...(CHROME_EXTENSIONS_DATA['research'] || [])];
  }
  if (categoryLower.includes('finance') || categoryLower.includes('invoice') || categoryLower.includes('expense')) {
    extensions = [...extensions, ...(CHROME_EXTENSIONS_DATA['finance'] || [])];
  }
  if (categoryLower.includes('support') || categoryLower.includes('ticket') || categoryLower.includes('chat')) {
    extensions = [...extensions, ...(CHROME_EXTENSIONS_DATA['support'] || [])];
  }

  // Deduplicate and limit
  const unique = [...new Map(extensions.map(e => [e.name, e])).values()];
  return unique.slice(0, 4);
};

// Function to get relevant GPTs based on category
const getRelevantGPTs = (category, goal, role) => {
  const categoryLower = (category || '').toLowerCase();
  const goalLower = (goal || '').toLowerCase();
  const roleLower = (role || '').toLowerCase();

  let gpts = [];

  if (categoryLower.includes('content') || categoryLower.includes('social') || categoryLower.includes('video')) {
    gpts = [...(CUSTOM_GPTS_DATA['content-creation'] || [])];
  }
  if (categoryLower.includes('seo') || categoryLower.includes('blog') || categoryLower.includes('landing')) {
    gpts = [...gpts, ...(CUSTOM_GPTS_DATA['seo-marketing'] || [])];
  }
  if (categoryLower.includes('lead') || categoryLower.includes('sales') || categoryLower.includes('outreach')) {
    gpts = [...gpts, ...(CUSTOM_GPTS_DATA['sales-leads'] || [])];
  }
  if (categoryLower.includes('automate') || categoryLower.includes('excel') || goalLower.includes('save-time')) {
    gpts = [...gpts, ...(CUSTOM_GPTS_DATA['automation'] || [])];
  }
  if (categoryLower.includes('dashboard') || categoryLower.includes('data') || categoryLower.includes('analytics')) {
    gpts = [...gpts, ...(CUSTOM_GPTS_DATA['data-analysis'] || [])];
  }
  if (categoryLower.includes('contract') || categoryLower.includes('legal') || roleLower.includes('legal')) {
    gpts = [...gpts, ...(CUSTOM_GPTS_DATA['legal-contracts'] || [])];
  }
  if (categoryLower.includes('hire') || categoryLower.includes('interview') || categoryLower.includes('recruit') || roleLower.includes('hr')) {
    gpts = [...gpts, ...(CUSTOM_GPTS_DATA['hr-recruiting'] || [])];
  }
  if (categoryLower.includes('support') || categoryLower.includes('ticket') || categoryLower.includes('customer')) {
    gpts = [...gpts, ...(CUSTOM_GPTS_DATA['customer-support'] || [])];
  }
  if (goalLower.includes('personal') || categoryLower.includes('plan') || categoryLower.includes('learning')) {
    gpts = [...gpts, ...(CUSTOM_GPTS_DATA['personal-productivity'] || [])];
  }

  // Deduplicate and limit
  const unique = [...new Map(gpts.map(g => [g.name, g])).values()];
  return unique.slice(0, 3);
};

// Generate immediate action prompt based on context
const generateImmediatePrompt = (goal, role, category, requirement) => {
  const goalText = goal === 'lead-generation' ? 'generate more leads' :
    goal === 'sales-retention' ? 'improve sales and retention' :
      goal === 'save-time' ? 'save time and automate' :
        goal === 'business-strategy' ? 'make better business decisions' : 'improve and grow';

  return `Act as my expert AI consultant. I need to ${goalText}.

**My Context:**
- Domain: ${role || 'General'}
- Problem Area: ${category || 'General business improvement'}
- Specific Need: ${requirement || '[Describe your specific situation]'}

**Your Task:**
1. Analyze my situation and identify the TOP 3 quick wins I can implement TODAY
2. For each quick win, provide:
   - A clear 2-step action plan
   - Expected time to complete (be realistic)
   - Expected impact (low/medium/high)
3. Then suggest ONE longer-term solution worth investigating

Keep your response actionable and practical. No fluff - just tell me exactly what to do.`;
};

// ============================================
// Outcome → Domain → Task data structure (from CSV)
// Q1: Outcome, Q2: Domain, Q3: Task
// ============================================
const OUTCOME_DOMAINS = {
  'lead-generation': [
    'Content & Social Media',
    'SEO & Organic Visibility',
    'Paid Media & Ads',
    'B2B Lead Generation'
  ],
  'sales-retention': [
    'Sales Execution & Enablement',
    'Lead Management & Conversion',
    'Customer Success & Reputation',
    'Repeat Sales'
  ],
  'business-strategy': [
    'Business Intelligence & Analytics',
    'Market Strategy & Innovation',
    'Financial Health & Risk',
    'Org Efficiency & Hiring',
    'Improve Yourself'
  ],
  'save-time': [
    'Sales & Content Automation',
    'Finance Legal & Admin',
    'Customer Support Ops',
    'Recruiting & HR Ops',
    'Personal & Team Productivity'
  ]
};

const DOMAIN_TASKS = {
  'Content & Social Media': [
    'Generate social media posts captions & hooks',
    'Create AI product photography & video ads',
    'Build a personal brand on LinkedIn/Twitter',
    'Repurpose content for maximum reach',
    'Spot trending topics & viral content ideas'
  ],
  'SEO & Organic Visibility': [
    'Get more leads from Google & website (SEO)',
    'Google Business Profile visibility',
    'Improve Google Business Profile leads',
    'Write SEO Keyword blogs and landing pages',
    'Write product titles that rank SEO',
    'Ecommerce Listing SEO + upsell bundles'
  ],
  'Paid Media & Ads': [
    'Generate high-converting ad copy & visuals',
    'Auto-optimize campaigns to boost ROAS',
    'Find winning audiences & keywords',
    'Audit ad spend & spot wasted budget',
    'Spy on competitor ads & offers'
  ],
  'B2B Lead Generation': [
    'Find decision-maker emails & LinkedIn profiles',
    'Generate hyper-personalized cold outreach sequences',
    'Identify target companies by tech stack & intent',
    'Score & prioritize leads by ICP match',
    'Automate LinkedIn connection & engagement'
  ],
  'Sales Execution & Enablement': [
    'Selling on WhatsApp/Instagram',
    'Speed up deal closure with faster contract review',
    'Chat with past campaigns and assets'
  ],
  'Lead Management & Conversion': [
    'Qualify & route leads automatically (AI SDR)',
    'Lead Qualification Follow Up & Conversion',
    'Reduce missed leads with faster replies',
    'Find why customers don\'t convert',
    'Understanding why customers don\'t convert'
  ],
  'Customer Success & Reputation': [
    'Improve reviews and response quality',
    'Call Chat & Ticket Intelligence',
    'Improve retention and reduce churn',
    'Churn & retention insights',
    'Support SLA dashboard',
    'Call/chat/ticket intelligence insights',
    'Review sentiment + issue detection'
  ],
  'Repeat Sales': [
    'Upsell/cross-sell recommendations',
    'Create upsell/cross-sell messaging',
    'Improve order experience to boost repeats'
  ],
  'Business Intelligence & Analytics': [
    'Instant sales dashboard (daily/weekly)',
    'Marketing performance dashboard (ROI)',
    'Campaign performance tracking dashboard',
    'Track calls Clicks and form fills',
    'Call/chat/ticket insights from conversations',
    'Review sentiment → improvement ideas',
    'Review sentiment + competitor comparisons',
    'Ops dashboard (orders blacklog SLA)'
  ],
  'Market Strategy & Innovation': [
    'Business Idea Generation',
    'Trending Products',
    'Track competitors pricing and offers',
    'Market & industry trend summaries',
    'Predict demand & business outcomes',
    'Competitor monitoring & price alerts',
    'Market & trend research summaries',
    'AI research summaries for decisions',
    'Sales & revenue forecasting',
    'Predict demand and stock needs'
  ],
  'Financial Health & Risk': [
    'Spot profit leaks and improve margins',
    'Prevent revenue leakage from contracts (renewals pricing penalties)',
    'Cashflow + spend control dashboard',
    'Instant finance dashboard (monthly/weekly)',
    'Budget vs actual insights with variance alerts',
    'Cashflow forecast (30/60/90 days)',
    'Spend control alerts and trend insights',
    'Contract risk snapshot (high-risk clauses obligations renewals)',
    'Supplier risk and exposure tracking',
    'Supplier risk monitoring'
  ],
  'Org Efficiency & Hiring': [
    'Hire faster to support growth',
    'Build a knowledge base from SOPs',
    'Internal Q&A bot from SOPs/policies',
    'Industry best practice',
    'Delivery/logistics performance reporting',
    'Hiring funnel dashboard',
    'Improve hire quality insights',
    'Interview feedback summaries',
    'HR knowledge base from policies',
    'Internal Q&A bot for HR queries',
    'Organize resumes and candidate notes',
    'Brand monitoring & crisis alerts',
    'Search/chat across help docs',
    'Internal Q&A bot from SOPs',
    'Weekly goals + progress summary',
    'Chat with your personal documents',
    'Auto-tag and organize your files'
  ],
  'Improve Yourself': [
    'Plan weekly priorities and tasks',
    'Prep for pitches and presentations',
    'Personal branding content plan',
    'Create a learning plan + summaries',
    'Contract drafting & review support',
    'Team Spirit Action plan'
  ],
  'Sales & Content Automation': [
    'Automate lead capture into Sheets/CRM',
    'Auto-capture leads from forms/ads',
    'Draft proposals quotes and emails faster',
    'Mail + DM + influencer outreach automation',
    'Auto-reply + follow-up sequences',
    'Summarize calls/chats into CRM notes',
    'Repurpose long videos into shorts',
    'Schedule posts + reuse content ideas',
    'Bulk update product listings/catalog',
    'Generate A+ store content at scale',
    'Auto-create weekly content calendar'
  ],
  'Finance Legal & Admin': [
    'Automate procurement requests/approvals',
    'Automate procurement approvals',
    'Automate HR or Finance',
    'Extract invoice/order data from PDFs',
    'Extract invoices/receipts from PDFs into Sheets',
    'Classify docs (invoice/contract/report)',
    'Bookkeeping assistance + auto categorization',
    'Expense tracking + spend control automation',
    'Auto-generate client/vendor payment reminders',
    'Draft finance emails reports and summaries faster',
    'Extract key terms from contracts (payment renewal notice period)',
    'Automate contract approvals renewals and deadline reminders',
    'Compliance checklist summaries and policy Q&A'
  ],
  'Customer Support Ops': [
    '24/7 support assistant + escalation',
    'Automate order updates and tracking',
    'Auto-tag route and prioritize tickets',
    'Draft replies in brand voice',
    'Build a support knowledge base',
    'WhatsApp/Instagram instant replies',
    'Support ticket routing automation'
  ],
  'Recruiting & HR Ops': [
    'Automate interview scheduling',
    'Automate candidate follow-ups',
    'High-volume hiring coordination',
    'Onboarding checklists + HR support',
    'Draft job descriptions and outreach',
    'Find candidates faster (multi-source)',
    'Resume screening + shortlisting'
  ],
  'Personal & Team Productivity': [
    'Draft emails reports and proposals',
    'Summarize PDFs and long documents',
    'Extract data from PDFs/images to Sheets',
    'Organize notes automatically',
    'Summarize meetings + action items',
    'Excel and App script Automation',
    'Auto-tag and organize documents'
  ]
};

// LocalStorage keys
const STORAGE_KEYS = {
  CHAT_HISTORY: 'ikshan-chat-history',
  USER_NAME: 'ikshan-user-name',
  USER_EMAIL: 'ikshan-user-email'
};

// Helper to safely parse JSON from localStorage
const getFromStorage = (key, defaultValue) => {
  try {
    const item = localStorage.getItem(key);
    return item ? JSON.parse(item) : defaultValue;
  } catch {
    return defaultValue;
  }
};

// Helper to safely save to localStorage
const saveToStorage = (key, value) => {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch (error) {
    // Storage might be full or disabled - fail silently
  }
};

const IdentityForm = ({ onSubmit }) => {
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [error, setError] = useState('');

  const handleSubmit = (e) => {
    e.preventDefault();

    if (!name.trim()) {
      setError('Please enter your name');
      return;
    }

    if (!email.trim()) {
      setError('Please enter your email');
      return;
    }

    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!emailRegex.test(email)) {
      setError('Please enter a valid email address');
      return;
    }

    onSubmit(name, email);
  };

  return (
    <div style={{ width: '100%' }}>
      <form onSubmit={handleSubmit}>
        <div className="form-group">
          <input
            type="text"
            placeholder="Your Name"
            value={name}
            onChange={(e) => {
              setName(e.target.value);
              setError('');
            }}
            style={{ width: '100%', padding: '0.75rem', border: '1px solid #e5e7eb', borderRadius: '0.5rem', marginBottom: '0.5rem' }}
          />
        </div>
        <div className="form-group">
          <input
            type="email"
            placeholder="Your Email"
            value={email}
            onChange={(e) => {
              setEmail(e.target.value);
              setError('');
            }}
            style={{ width: '100%', padding: '0.75rem', border: '1px solid #e5e7eb', borderRadius: '0.5rem' }}
          />
        </div>
        {error && <div style={{ color: '#ef4444', fontSize: '0.85rem', marginBottom: '1rem' }}>{error}</div>}
        <button type="submit" style={{ width: '100%', padding: '0.75rem', background: 'var(--ikshan-purple)', color: 'white', border: 'none', borderRadius: '0.5rem', fontWeight: 600, cursor: 'pointer' }}>
          Continue →
        </button>
      </form>
    </div>
  );
};

const THINKING_PHRASES = [
  '🔍 Searching best tools...',
  '🧠 Analyzing your needs...',
  '⚡ Matching solutions...',
  '📊 Building your report...',
  '✨ Almost there...',
];

const ChatBotNewMobile = ({ onNavigate }) => {
  const [messages, setMessages] = useState<Record<string, any>[]>([
    {
      id: 'welcome-msg',
      text: "Welcome to Ikshan!\n\nLet's find the perfect AI solution for you.",
      sender: 'bot',
      timestamp: new Date(),
      showOutcomeOptions: true
    }
  ]);
  const [inputValue, setInputValue] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const [taskClickProcessing, setTaskClickProcessing] = useState(false);
  const [outcomeClickProcessing, setOutcomeClickProcessing] = useState(false);
  const [domainClickProcessing, setDomainClickProcessing] = useState(false);
  const [answerProcessing, setAnswerProcessing] = useState(false);
  const [thinkingPhraseIndex, setThinkingPhraseIndex] = useState(0);
  const [loadingPhase, setLoadingPhase] = useState('');
  const [selectedGoal, setSelectedGoal] = useState(null);
  const [selectedDomain, setSelectedDomain] = useState(null);
  const [selectedSubDomain, setSelectedSubDomain] = useState(null);
  const [selectedDomainName, setSelectedDomainName] = useState(null);
  const [userRole, setUserRole] = useState(null);
  const [requirement, setRequirement] = useState(null);
  const [userName, setUserName] = useState(null);
  const [userEmail, setUserEmail] = useState(null);
  const [flowStage, setFlowStage] = useState('outcome');

  // ── OTP Auth State ─────────────────────────────────────────
  const [otpPhone, setOtpPhone] = useState('');
  const [otpSessionId, setOtpSessionId] = useState(null);
  const [otpCode, setOtpCode] = useState('');
  const [otpStep, setOtpStep] = useState('phone'); // 'phone' | 'verify'
  const [otpLoading, setOtpLoading] = useState(false);
  const [otpError, setOtpError] = useState('');
  const [otpVerified, setOtpVerified] = useState(false);

  // AI Agent Session State
  const [sessionId, setSessionId] = useState(null);
  const sessionIdRef = useRef(null); // ref mirrors state — avoids React batching delays
  const pendingAuthActionRef = useRef(null); // 'recommendations' when auth-gate is active
  const [dynamicQuestions, setDynamicQuestions] = useState([]);
  const [currentDynamicQIndex, setCurrentDynamicQIndex] = useState(0);
  const [dynamicAnswers, setDynamicAnswers] = useState({});
  const [personaLoaded, setPersonaLoaded] = useState(null);
  const [dynamicFreeText, setDynamicFreeText] = useState('');
  const [rcaMode, setRcaMode] = useState(false); // Claude adaptive RCA mode
  const [crawlStatus, setCrawlStatus] = useState(''); // '', 'in_progress', 'complete', 'failed', 'skipped'
  const crawlPollRef = useRef(null);
  const crawlSummaryRef = useRef(null); // stash crawl summary to show at right time
  const pendingDiagnosticDataRef = useRef(null);
  const pendingReportDataRef = useRef(null); // stash {rcaSummary, crawlPoints} for post-auth

  // ── Scale Questions State ──────────────────────────────────
  const [scaleQuestions, setScaleQuestions] = useState([]);
  const [currentScaleQIndex, setCurrentScaleQIndex] = useState(0);
  const scaleAnswersRef = useRef({}); // ref to avoid stale closures
  const [scaleFormSelections, setScaleFormSelections] = useState({});
  const [scaleFormSubmitted, setScaleFormSubmitted] = useState(false);

  // ── Precision Questions State ──────────────────────────────
  const [precisionQuestions, setPrecisionQuestions] = useState([]);
  const [currentPrecisionQIndex, setCurrentPrecisionQIndex] = useState(0);
  const pendingPrecisionDataRef = useRef(null);

  // Business Intelligence Verdict (pre-RCA, crawl-powered)
  const [businessIntelVerdict, setBusinessIntelVerdict] = useState(null);

  // ── AI Playbook State ──────────────────────────────────────
  const [playbookStage, setPlaybookStage] = useState('');
  const [playbookGapQuestions, setPlaybookGapQuestions] = useState('');
  const [playbookGapAnswer, setPlaybookGapAnswer] = useState('');
  const [playbookGapSelections, setPlaybookGapSelections] = useState({});

  const API_BASE = getApiBaseRequired();

  // Helper: always get the latest session id (ref > state avoid React async gap)
  const getSessionId = () => sessionIdRef.current;

  // Helper: ensure a backend session exists, creating one if needed
  const ensureSession = async () => {
    let sid = sessionIdRef.current;
    if (sid) return sid;
    try {
      const res = await fetch(`${API_BASE}/api/v1/agent/session`, { method: 'POST' });
      const data = await res.json();
      sid = data.session_id;
      sessionIdRef.current = sid;
      setSessionId(sid);
      return sid;
    } catch (e) {
      console.error('Failed to create session:', e);
      return null;
    }
  };

  const [businessContext, setBusinessContext] = useState({
    businessType: null,
    industry: null,
    targetAudience: null,
    marketSegment: null
  });

  const [professionalContext, setProfessionalContext] = useState({
    roleAndIndustry: null,
    solutionFor: null,
    salaryContext: null
  });

  // Payment state
  const [paymentVerified, setPaymentVerified] = useState(() => {
    return localStorage.getItem('ikshan-rca-paid') === 'true';
  });
  const [paymentLoading, setPaymentLoading] = useState(false);
  const [paymentOrderId, setPaymentOrderId] = useState(null);

  const [isRecording, setIsRecording] = useState(false);
  const [voiceSupported, setVoiceSupported] = useState(false);
  const [showAuthModal, setShowAuthModal] = useState(false);
  const [isGoogleLoaded, setIsGoogleLoaded] = useState(false);
  const [showChatHistory, setShowChatHistory] = useState(false);
  const [speechError, setSpeechError] = useState(null);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  // Dashboard view state
  const [showDashboard, setShowDashboard] = useState(false);
  const [dashboardData, setDashboardData] = useState({
    goalLabel: '',
    roleLabel: '',
    category: '',
    companies: [],
    extensions: [],
    customGPTs: [],
    immediatePrompt: ''
  });
  const [copiedPrompt, setCopiedPrompt] = useState(false);

  // Load chat history from localStorage on mount
  const [chatHistory, setChatHistory] = useState(() => {
    const saved = getFromStorage(STORAGE_KEYS.CHAT_HISTORY, []);
    // Convert timestamp strings back to Date objects
    return saved.map(chat => ({
      ...chat,
      timestamp: new Date(chat.timestamp),
      messages: chat.messages.map(msg => ({
        ...msg,
        timestamp: new Date(msg.timestamp)
      }))
    }));
  });

  // Persist chat history to localStorage whenever it changes
  useEffect(() => {
    if (chatHistory.length > 0) {
      saveToStorage(STORAGE_KEYS.CHAT_HISTORY, chatHistory);
    }
  }, [chatHistory]);

  // Rotate thinking phrases during loading
  useEffect(() => {
    if (!taskClickProcessing) { setThinkingPhraseIndex(0); return; }
    const iv = setInterval(() => {
      setThinkingPhraseIndex(p => (p + 1) % THINKING_PHRASES.length);
    }, 2200);
    return () => clearInterval(iv);
  }, [taskClickProcessing]);

  const messagesEndRef = useRef(null);
  const messagesContainerRef = useRef(null);
  const recognitionRef = useRef(null);

  const domains = [
    { id: 'marketing', name: 'Marketing', emoji: '' },
    { id: 'sales-support', name: 'Sales and Customer Support', emoji: '' },
    { id: 'social-media', name: 'Social Media', emoji: '' },
    { id: 'legal', name: 'Legal', emoji: '' },
    { id: 'hr-hiring', name: 'HR and talent Hiring', emoji: '' },
    { id: 'finance', name: 'Finance', emoji: '' },
    { id: 'supply-chain', name: 'Supply chain', emoji: '' },
    { id: 'research', name: 'Research', emoji: '' },
    { id: 'data-analysis', name: 'Data Analysis', emoji: '' },
    { id: 'other', name: 'Other', emoji: '' }
  ];

  const outcomeOptions = [
    { id: 'lead-generation', text: 'Lead Generation', subtext: 'Marketing, SEO & Social', emoji: '' },
    { id: 'sales-retention', text: 'Sales & Retention', subtext: 'Calling, Support & Expansion', emoji: '' },
    { id: 'business-strategy', text: 'Business Strategy', subtext: 'Intelligence, Market & Org', emoji: '' },
    { id: 'save-time', text: 'Save Time', subtext: 'Automation Workflow, Extract PDF, Bulk Task', emoji: '' }
  ];

  // State for custom role input (kept for backward compatibility)
  const [customRole, setCustomRole] = useState('');
  const [selectedCategory, setSelectedCategory] = useState(null);
  const [customCategoryInput, setCustomCategoryInput] = useState('');

  // Get domains based on selected outcome
  const getDomainsForSelection = useCallback(() => {
    if (!selectedGoal) return [];
    return OUTCOME_DOMAINS[selectedGoal] || [];
  }, [selectedGoal]);

  // Get tasks based on selected domain
  const getTasksForSelection = useCallback(() => {
    if (!selectedDomainName) return [];
    return DOMAIN_TASKS[selectedDomainName] || [];
  }, [selectedDomainName]);

  const subDomains = {
    marketing: [
      'Getting more leads',
      'Replying to customers fast',
      'Following up properly',
      'Selling on WhatsApp/Instagram',
      'Reducing sales/agency cost',
      'Understanding why customers don\'t convert',
      'others'
    ],
    'sales-support': [
      'AI Sales Agent / SDR',
      'Customer Support Automation',
      'Conversational Chat & Voice Bots',
      'Lead Qualification & Conversion',
      'Customer Success & Retention',
      'Call, Chat & Ticket Intelligence',
      'others'
    ],
    'social-media': [
      'Content Creation & Scheduling',
      'Personal Branding & LinkedIn Growth',
      'Video Repurposing (Long → Short)',
      'Ad Creative & Performance',
      'Brand Monitoring & Crisis Alerts',
      'DM, Leads & Influencer Automation',
      'others'
    ],
    legal: [
      'Contract Drafting & Review AI',
      'CLM & Workflow Automation',
      'Litigation & eDiscovery AI',
      'Legal Research Copilot',
      'Legal Ops & Matter Management',
      'Case Origination & Lead Gen',
      'others'
    ],
    'hr-hiring': [
      'Find candidates faster',
      'Automate interviews',
      'High-volume hiring',
      'Candidate follow-ups',
      'Onboarding & HR help',
      'Improve hire quality',
      'others'
    ],
    finance: [
      'Bookkeeping & Accounting',
      'Expenses & Spend Control',
      'Virtual CFO & Insights',
      'Budgeting & Forecasting',
      'Finance Ops & Close',
      'Invoices & Compliance',
      'others'
    ],
    'supply-chain': [
      'Inventory & Demand',
      'Procurement Automation',
      'Supplier Risk',
      'Shipping & Logistics',
      'Track My Orders',
      'Fully Automated Ops',
      'others'
    ],
    research: [
      'Track My Competitors',
      'Find Market & Industry Trends',
      'Understand Customer Reviews & Sentiment',
      'Monitor Websites, Prices & Online Changes',
      'Predict Demand & Business Outcomes',
      'Get AI Research Summary & Insights',
      'others'
    ],
    'data-analysis': [
      'Lead Follow-up & Auto Reply',
      'Sales & Revenue Forecasting',
      'Customer Churn & Retention Insights',
      'Instant Business Dashboards',
      'Marketing & Campaign Performance Tracking',
      '24/7 Customer Support Assistant',
      'others'
    ]
  };

  // Use unique ID generator instead of counter to prevent key conflicts
  const getNextMessageId = () => generateUniqueId();

  const scrollToBottom = () => {
    setTimeout(() => {
      if (messagesEndRef.current) {
        messagesEndRef.current.scrollIntoView({ behavior: 'smooth', block: 'end' });
      }
    }, 100);
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  // Initialize voice recognition
  useEffect(() => {
    if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {
      const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
      const recognition = new SpeechRecognition();

      recognition.continuous = false;
      recognition.interimResults = false;
      recognition.lang = 'en-US';

      recognition.onresult = (event) => {
        const transcript = event.results[0][0].transcript;
        setInputValue(transcript);
        setIsRecording(false);
      };

      recognition.onerror = (event) => {
        setIsRecording(false);
        // Provide user-friendly error messages
        switch (event.error) {
          case 'no-speech':
            setSpeechError('No speech detected. Please try again.');
            break;
          case 'not-allowed':
            setSpeechError('Microphone access denied. Please enable microphone permissions.');
            break;
          case 'network':
            setSpeechError('Network error. Please check your connection.');
            break;
          default:
            setSpeechError('Voice recognition failed. Please try again.');
        }
        // Auto-clear error after 3 seconds
        setTimeout(() => setSpeechError(null), 3000);
      };

      recognition.onend = () => {
        setIsRecording(false);
      };

      recognitionRef.current = recognition;
      setVoiceSupported(true);
    }
  }, []);

  // Initialize Google Sign-In
  useEffect(() => {
    const checkGoogleLoaded = setInterval(() => {
      if (window.google?.accounts?.id) {
        setIsGoogleLoaded(true);
        clearInterval(checkGoogleLoaded);
      }
    }, 100);

    setTimeout(() => clearInterval(checkGoogleLoaded), 5000);

    return () => clearInterval(checkGoogleLoaded);
  }, []);

  const handleGoogleSignIn = () => {
    if (!isGoogleLoaded || !window.google?.accounts?.id) {
      // Show error message instead of causing infinite reload loop
      const errorMessage = {
        id: generateUniqueId(),
        text: '⚠️ Google Sign-In is not available right now. Please try again in a moment.',
        sender: 'bot',
        timestamp: new Date()
      };
      setMessages(prev => [...prev, errorMessage]);
      setShowAuthModal(false);
      return;
    }

    const clientId = import.meta.env.VITE_GOOGLE_CLIENT_ID;

    if (!clientId) {
      // Show configuration error instead of reloading
      const errorMessage = {
        id: generateUniqueId(),
        text: '⚠️ Sign-in is not configured. Please contact support.',
        sender: 'bot',
        timestamp: new Date()
      };
      setMessages(prev => [...prev, errorMessage]);
      setShowAuthModal(false);
      return;
    }

    window.google.accounts.id.initialize({
      client_id: clientId,
      callback: handleGoogleCallback,
    });

    window.google.accounts.id.prompt();
  };

  const handleGoogleCallback = (response) => {
    const payload = JSON.parse(atob(response.credential.split('.')[1]));
    setUserName(payload.name);
    setUserEmail(payload.email);
    setShowAuthModal(false);

    // If auth-gate before recommendations, proceed directly
    if (pendingAuthActionRef.current === 'recommendations') {
      pendingAuthActionRef.current = null;
      const welcomeMsg = {
        id: getNextMessageId(),
        text: `Welcome, ${payload.name}! Generating your **AI Growth Playbook**...`,
        sender: 'bot',
        timestamp: new Date(),
      };
      setMessages(prev => [...prev, welcomeMsg]);
      pendingReportDataRef.current = null;
      startPlaybook();
      return;
    }

    setSelectedDomain(null);
    setSelectedSubDomain(null);
    setUserRole(null);
    setRequirement(null);
    setBusinessContext({
      businessType: null,
      industry: null,
      targetAudience: null,
      marketSegment: null
    });
    setProfessionalContext({
      roleAndIndustry: null,
      solutionFor: null,
      salaryContext: null
    });
    setFlowStage('domain');

    const botMessage = {
      id: messageIdCounter.current++,
      text: `Welcome back, ${payload.name}! 🚀\n\nLet's explore another idea. Pick a domain to get started:`,
      sender: 'bot',
      timestamp: new Date()
    };
    setMessages(prev => [...prev, botMessage]);
  };

  // ── OTP Handlers ───────────────────────────────────────────
  const handleSendOtp = async () => {
    const phone = otpPhone.trim().replace(/[\s\-]/g, '');
    if (!/^(91)?\d{10}$/.test(phone)) {
      setOtpError('Enter a valid 10-digit Indian mobile number');
      return;
    }
    setOtpLoading(true);
    setOtpError('');
    try {
      const res = await fetch(`${API_BASE}/api/v1/auth/send-otp`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionIdRef.current, phone_number: phone }),
      });
      const data = await res.json();
      if (data.success) {
        setOtpSessionId(data.otp_session_id);
        setOtpStep('verify');
      } else {
        setOtpError(data.message || 'Failed to send OTP');
      }
    } catch {
      setOtpError('Network error — please try again');
    } finally {
      setOtpLoading(false);
    }
  };

  const handleVerifyOtp = async () => {
    const code = otpCode.trim();
    if (!/^\d{4,8}$/.test(code)) {
      setOtpError('Enter the 4-6 digit OTP sent to your phone');
      return;
    }
    setOtpLoading(true);
    setOtpError('');
    try {
      const res = await fetch(`${API_BASE}/api/v1/auth/verify-otp`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionIdRef.current, otp_session_id: otpSessionId, otp_code: code }),
      });
      const data = await res.json();
      if (data.verified) {
        setOtpVerified(true);
        setShowAuthModal(false);
        setOtpStep('phone');
        setOtpCode('');
        setOtpError('');

        if (pendingAuthActionRef.current === 'recommendations') {
          pendingAuthActionRef.current = null;
          const welcomeMsg = {
            id: getNextMessageId(),
            text: `Phone verified! ✅ Generating your **AI Growth Playbook**...`,
            sender: 'bot',
            timestamp: new Date(),
          };
          setMessages(prev => [...prev, welcomeMsg]);
          pendingReportDataRef.current = null;
          startPlaybook();
        }
      } else {
        setOtpError(data.message || 'Incorrect OTP — please try again');
      }
    } catch {
      setOtpError('Network error — please try again');
    } finally {
      setOtpLoading(false);
    }
  };

  const handleResendOtp = async () => {
    setOtpStep('phone');
    setOtpCode('');
    setOtpError('');
    setOtpSessionId(null);
  };

  // ============================================
  // PAYMENT HANDLERS
  // ============================================

  const handlePayForRCA = async () => {
    setPaymentLoading(true);
    try {
      const response = await fetch('/api/v1/payments/create-order', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          amount: 499,
          customer_id: userEmail || `guest_${Date.now()}`,
          customer_email: userEmail || '',
          customer_phone: '',
          return_url: `${window.location.origin}?payment_status=success`,
          description: 'Ikshan Root Cause Analysis — Premium Deep Dive',
          udf1: 'rca_unlock',
          udf2: selectedGoal || ''
        })
      });

      const data = await response.json();

      if (data.success && data.payment_links) {
        setPaymentOrderId(data.order_id);
        const paymentUrl = data.payment_links.web || data.payment_links.mobile || Object.values(data.payment_links)[0];
        if (paymentUrl) {
          window.location.href = paymentUrl;
        } else {
          throw new Error('No payment URL received');
        }
      } else {
        throw new Error(data.error || 'Failed to create payment order');
      }
    } catch (error) {
      console.error('Payment initiation failed:', error);
      setMessages(prev => [...prev, {
        id: getNextMessageId(),
        text: `⚠️ **Payment Error**\n\nSomething went wrong. Please try again.\n\n_Error: ${error.message}_`,
        sender: 'bot',
        timestamp: new Date(),
        showFinalActions: true
      }]);
    } finally {
      setPaymentLoading(false);
    }
  };

  // Check payment status on return
  useEffect(() => {
    const urlParams = new URLSearchParams(window.location.search);
    const paymentStatus = urlParams.get('payment_status');
    const orderId = urlParams.get('order_id');

    if (paymentStatus === 'success' && orderId) {
      const verifyPayment = async () => {
        try {
          const res = await fetch(`/api/v1/payments/status/${orderId}`);
          const data = await res.json();
          if (data.success && (data.status === 'CHARGED' || data.status === 'AUTO_REFUND')) {
            setPaymentVerified(true);
            localStorage.setItem('ikshan-rca-paid', 'true');
            setMessages(prev => [...prev, {
              id: getNextMessageId(),
              text: `✅ **Payment Successful!**\n\nYou now have full access to Root Cause Analysis.`,
              sender: 'bot',
              timestamp: new Date(),
              showFinalActions: true
            }]);
          }
        } catch (err) {
          console.error('Payment verification failed:', err);
        }
        window.history.replaceState({}, '', window.location.pathname);
      };
      verifyPayment();
    }
  }, []);

  const handleStartNewIdea = () => {
    // Save current chat to history if there are messages beyond the initial welcome
    if (messages.length > 1) {
      const userMessages = messages.filter(m => m.sender === 'user');
      const outcomeLabel = outcomeOptions.find(g => g.id === selectedGoal)?.text || '';
      const chatTitle = outcomeLabel || userMessages[0]?.text?.slice(0, 30) || 'New Chat';
      const lastUserMessage = userMessages[userMessages.length - 1]?.text || '';

      const newHistoryItem = {
        id: `chat-${Date.now()}`,
        title: chatTitle,
        preview: lastUserMessage.slice(0, 80) + (lastUserMessage.length > 80 ? '...' : ''),
        timestamp: new Date(),
        domain: selectedCategory || 'General',
        messages: [...messages]
      };

      setChatHistory(prev => [newHistoryItem, ...prev]);
    }

    // Reset all state for new chat
    setSelectedGoal(null);
    setSelectedDomain(null);
    setSelectedSubDomain(null);
    setSelectedDomainName(null);
    setUserRole(null);
    setRequirement(null);
    setUserName(null);
    setUserEmail(null);
    setCustomRole('');
    setSelectedCategory(null);
    setCustomCategoryInput('');
    setBusinessContext({
      businessType: null,
      industry: null,
      targetAudience: null,
      marketSegment: null
    });
    setProfessionalContext({
      roleAndIndustry: null,
      solutionFor: null,
      salaryContext: null
    });
    setFlowStage('outcome');
    setShowDashboard(false);
    setDashboardData({
      goalLabel: '',
      roleLabel: '',
      category: '',
      companies: [],
      extensions: [],
      customGPTs: [],
      immediatePrompt: ''
    });
    setCopiedPrompt(false);

    // Reset AI Agent session state
    setTaskClickProcessing(false);
    setOutcomeClickProcessing(false);
    setDomainClickProcessing(false);
    setAnswerProcessing(false);
    setSessionId(null);
    sessionIdRef.current = null;
    setDynamicQuestions([]);
    setCurrentDynamicQIndex(0);
    setDynamicAnswers({});
    setPersonaLoaded(null);
    setDynamicFreeText('');
    setRcaMode(false);

    // Start fresh with welcome message
    const welcomeMessage = {
      id: getNextMessageId(),
      text: "Welcome to Ikshan!\n\nLet's find the perfect AI solution for you.",
      sender: 'bot',
      timestamp: new Date(),
      showOutcomeOptions: true
    };
    setMessages([welcomeMessage]);
  };

  // Handle outcome selection (Question 1)
  const handleOutcomeClick = async (outcome) => {
    if (outcomeClickProcessing) return;
    setOutcomeClickProcessing(true);
    setSelectedGoal(outcome.id);

    const userMessage = {
      id: getNextMessageId(),
      text: `${outcome.text}`,
      sender: 'user',
      timestamp: new Date()
    };

    // Show domains based on selected outcome
    const domains = OUTCOME_DOMAINS[outcome.id] || [];
    const botMessage = {
      id: getNextMessageId(),
      text: `Great choice! You want to focus on **${outcome.text.toLowerCase()}**.\n\nNow, select the domain that best matches your need:`,
      sender: 'bot',
      timestamp: new Date(),
      showDomainOptions: true,
      domains: domains
    };

    setMessages(prev => [...prev, userMessage, botMessage]);
    setFlowStage('domain');

    // Create session and record outcome
    try {
      const sid = await ensureSession();
      if (sid) {
        await fetch(`${API_BASE}/api/v1/agent/session/outcome`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ session_id: sid, outcome: outcome.id, outcome_label: outcome.text })
        });
      }
    } catch (e) {
      console.log('Session tracking: outcome', e);
    }

    saveToSheet(`Selected Outcome: ${outcome.text}`, '', '', '');
    setOutcomeClickProcessing(false);
  };

  // Handle domain selection (Question 2)
  const handleDomainClickNew = async (domain) => {
    if (domainClickProcessing) return;
    setDomainClickProcessing(true);
    setSelectedDomainName(domain);

    const userMessage = {
      id: getNextMessageId(),
      text: `${domain}`,
      sender: 'user',
      timestamp: new Date()
    };

    // Show tasks based on selected domain
    setFlowStage('task');
    const tasks = DOMAIN_TASKS[domain] || [];
    const botMessage = {
      id: getNextMessageId(),
      text: `Perfect!\n\nHere are the tasks in **${domain}**:\n\n**Select one that best matches your need:**`,
      sender: 'bot',
      timestamp: new Date(),
      showTaskOptions: true,
      tasks: tasks
    };
    setMessages(prev => [...prev, userMessage, botMessage]);

    // Record domain in session
    try {
      const sid = getSessionId();
      if (sid) {
        await fetch(`${API_BASE}/api/v1/agent/session/domain`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ session_id: sid, domain })
        });
      }
    } catch (e) {
      console.log('Session tracking: domain', e);
    }

    saveToSheet(`Selected Domain: ${domain}`, '', '', '');
    setDomainClickProcessing(false);
  };

  // Handle task selection (Question 3) - Claude RCA or fallback
  const handleTaskClick = async (task) => {
    if (taskClickProcessing) return;
    setTaskClickProcessing(true);
    setSelectedCategory(task);

    const userMessage = {
      id: getNextMessageId(),
      text: `${task}`,
      sender: 'user',
      timestamp: new Date()
    };
    setMessages(prev => [...prev, userMessage]);
    saveToSheet(`Selected Task: ${task}`, '', '', '');

    // Always try backend — ensure session exists first
    setIsTyping(true);
    setLoadingPhase('tools');
    try {
      const sid = await ensureSession();
      if (sid) {
        setLoadingPhase('diagnostic');
        const res = await fetch(`${API_BASE}/api/v1/agent/session/task`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ session_id: sid, task })
        });
        const data = await res.json();

        if (data.questions && data.questions.length > 0) {
          const isRca = data.rca_mode === true;
          setRcaMode(isRca);
          setDynamicQuestions(data.questions);
          setCurrentDynamicQIndex(0);
          setDynamicAnswers({});
          setPersonaLoaded(data.persona_loaded);

          // ── Show early recommendations if available ──────────
          if (data.early_recommendations && data.early_recommendations.length > 0) {
            const earlyRecsMsg = {
              id: getNextMessageId(),
              text: data.early_recommendations_message || 'Based on your goal and task, here are some tools that could help you right away.',
              sender: 'bot',
              timestamp: new Date(),
              isEarlyRecommendation: true,
              earlyTools: data.early_recommendations,
            };
            setMessages(prev => [...prev, earlyRecsMsg]);
          }

          // ── Show URL input IMMEDIATELY after tool recommendations ──
          pendingDiagnosticDataRef.current = {
            data,
            isRca: data.rca_mode === true,
            task,
          };

          const urlPromptMsg = {
            id: getNextMessageId(),
            text: `Great — here are tools that match your space.\nNow let's look at **YOUR business** specifically.`,
            sender: 'bot',
            timestamp: new Date(),
            showBusinessUrlInput: true,
          };
          setMessages(prev => [...prev, urlPromptMsg]);
          setFlowStage('url-input');
          setIsTyping(false);
          setLoadingPhase('');
          return;
        }
      }
    } catch (e) {
      console.log('Dynamic question generation failed, falling back', e);
    }
    setIsTyping(false);
    setTaskClickProcessing(false);
    setLoadingPhase('');

    // Fallback: directly show solution stack if backend call fails
    showSolutionStack(task);
  };

  // ── Helper: proceed to playbook/auth after all questions done ──
  const proceedToReport = async (rcaSummaryText, crawlPoints) => {
    if (userEmail) {
      await startPlaybook();
    } else {
      pendingAuthActionRef.current = 'recommendations';
      pendingReportDataRef.current = { rcaSummary: rcaSummaryText, crawlPoints };
      const authMsg = {
        id: getNextMessageId(),
        text: `Your diagnostic is ready.\n\nSign in to unlock your **AI Growth Playbook**.`,
        sender: 'bot',
        timestamp: new Date(),
        showAuthGate: true,
      };
      setMessages(prev => [...prev, authMsg]);
      setFlowStage('auth-gate');
    }
  };

  // ── Handle precision question answers ──
  const handlePrecisionAnswer = async (answer) => {
    const currentPQ = precisionQuestions[currentPrecisionQIndex];

    const userMsg = {
      id: getNextMessageId(),
      text: answer,
      sender: 'user',
      timestamp: new Date(),
    };
    setMessages(prev => [...prev, userMsg]);

    try {
      const sid = getSessionId();
      if (sid) {
        await fetch(`${API_BASE}/api/v1/agent/session/answer`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            session_id: sid,
            question_index: 900 + currentPrecisionQIndex,
            answer: `[${currentPQ?.type || 'precision'}] ${answer}`,
          }),
        });
      }
    } catch (e) {
      console.log('Precision answer save failed (non-blocking)', e);
    }

    const nextIdx = currentPrecisionQIndex + 1;

    if (nextIdx < precisionQuestions.length) {
      setCurrentPrecisionQIndex(nextIdx);
      const nextPQ = precisionQuestions[nextIdx];

      const pqParts = [];
      if (nextPQ.insight) pqParts.push(`💡 *${nextPQ.insight}*`);
      pqParts.push(nextPQ.question);

      const botMsg = {
        id: getNextMessageId(),
        text: `**${nextPQ.section_label || 'Precision Question'}**\n\n${pqParts.join('\n\n')}`,
        sender: 'bot',
        timestamp: new Date(),
        diagnosticOptions: nextPQ.options || [],
        sectionIndex: nextIdx,
        sectionKey: `precision_${nextPQ.type}`,
        allowsFreeText: true,
        isPrecisionQuestion: true,
        precisionIndex: nextIdx,
      };
      setMessages(prev => [...prev, botMsg]);
    } else {
      const pendingData = pendingPrecisionDataRef.current;
      pendingPrecisionDataRef.current = null;
      const rcaSummary = pendingData?.rcaSummary || '';
      const crawlPoints = pendingData?.crawlPoints || [];
      await proceedToReport(rcaSummary, crawlPoints);
    }
  };

  // Handle dynamic question answer (option click) — supports RCA & fallback
  const handleDynamicAnswer = async (answer) => {
    if (answerProcessing) return;
    setAnswerProcessing(true);
    const currentQ = dynamicQuestions[currentDynamicQIndex];
    const newAnswers = { ...dynamicAnswers, [currentDynamicQIndex]: answer };
    setDynamicAnswers(newAnswers);
    setDynamicFreeText('');

    // Add user's selection as a chat message
    const userMsg = {
      id: getNextMessageId(),
      text: answer,
      sender: 'user',
      timestamp: new Date()
    };

    // ── RCA Mode: call backend → Claude generates next question ──
    if (rcaMode) {
      setMessages(prev => [...prev, userMsg]);
      setCurrentDynamicQIndex(prev => prev + 1);
      setIsTyping(true);

      try {
        const sid = getSessionId();
        if (sid) {
          const res = await fetch(`${API_BASE}/api/v1/agent/session/answer`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              session_id: sid,
              question_index: currentDynamicQIndex,
              answer: answer
            })
          });
          const data = await res.json();

          if (data.all_answered) {
            setIsTyping(false);

            const rcaSummaryText = data.acknowledgment
              ? `${data.acknowledgment}${data.rca_summary ? '\n\n' + data.rca_summary : ''}`
              : data.rca_summary || '';

            // Resolve crawl points
            let crawlPoints = [];
            if (crawlStatus === 'in_progress') {
              crawlPoints = await new Promise((resolve) => {
                const waitForCrawl = setInterval(async () => {
                  try {
                    const sid = getSessionId();
                    const statusRes = await fetch(`${API_BASE}/api/v1/agent/session/${sid}/crawl-status`);
                    const statusData = await statusRes.json();
                    if (statusData.crawl_status === 'complete' || statusData.crawl_status === 'failed') {
                      setCrawlStatus(statusData.crawl_status);
                      clearInterval(waitForCrawl);
                      const pts = (statusData.crawl_status === 'complete' && statusData.crawl_summary?.points)
                        ? statusData.crawl_summary.points : [];
                      resolve(pts);
                    }
                  } catch (e) {
                    console.log('Crawl wait poll failed', e);
                    clearInterval(waitForCrawl);
                    resolve([]);
                  }
                }, 2000);
              });
            } else {
              crawlPoints = crawlSummaryRef.current?.points || [];
              crawlSummaryRef.current = null;
            }

            // Try to fetch precision questions
            setIsTyping(true);
            try {
              const sid = getSessionId();
              const precRes = await fetch(`${API_BASE}/api/v1/agent/session/precision-questions`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ session_id: sid }),
              });
              const precData = await precRes.json();

              if (precData.available && precData.questions && precData.questions.length > 0) {
                setIsTyping(false);
                setPrecisionQuestions(precData.questions);
                setCurrentPrecisionQIndex(0);
                pendingPrecisionDataRef.current = { rcaSummary: rcaSummaryText, crawlPoints };
                setFlowStage('precision-questions');

                const transMsg = {
                  id: getNextMessageId(),
                  text: `I've cross-referenced your answers with what I found on your website. I have **3 precision questions** that dig into the gaps I spotted.`,
                  sender: 'bot',
                  timestamp: new Date(),
                };

                const pq = precData.questions[0];
                const pqParts = [];
                if (pq.insight) pqParts.push(`💡 *${pq.insight}*`);
                pqParts.push(pq.question);

                const pqMsg = {
                  id: getNextMessageId(),
                  text: `**${pq.section_label || 'Precision Question'}**\n\n${pqParts.join('\n\n')}`,
                  sender: 'bot',
                  timestamp: new Date(),
                  diagnosticOptions: pq.options || [],
                  sectionIndex: 0,
                  sectionKey: `precision_${pq.type}`,
                  allowsFreeText: true,
                  isPrecisionQuestion: true,
                  precisionIndex: 0,
                };

                setMessages(prev => [...prev, transMsg, pqMsg]);
                setAnswerProcessing(false);
                return;
              }
            } catch (e) {
              console.log('Precision questions failed, proceeding to report', e);
            }

            setIsTyping(false);
            setAnswerProcessing(false);
            await proceedToReport(rcaSummaryText, crawlPoints);
            return;
          }

          if (data.next_question) {
            const nextQ = data.next_question;
            setDynamicQuestions(prev => [...prev, nextQ]);

            // Build text: insight + question (no acknowledgment)
            const insight = nextQ.insight || data.insight || '';
            const parts = [];
            if (insight) parts.push(`💡 *${insight}*`);
            parts.push(nextQ.question);
            const botText = parts.join('\n\n');

            const botMsg = {
              id: getNextMessageId(),
              text: botText,
              sender: 'bot',
              timestamp: new Date(),
              diagnosticOptions: nextQ.options || [],
              sectionIndex: currentDynamicQIndex + 1,
              sectionKey: nextQ.section,
              allowsFreeText: nextQ.allows_free_text !== false,
              isRcaQuestion: true,
              insightText: insight,
            };
            setMessages(prev => [...prev, botMsg]);
            setIsTyping(false);
            setAnswerProcessing(false);
            return;
          }
        }
      } catch (e) {
        console.log('RCA answer submission failed', e);
      }

      setIsTyping(false);
      setAnswerProcessing(false);
      crawlSummaryRef.current = null;
      if (userEmail) {
        await startPlaybook();
      } else {
        pendingAuthActionRef.current = 'recommendations';
        pendingReportDataRef.current = { rcaSummary: '', crawlPoints: [] };
        const authMsg = {
          id: getNextMessageId(),
          text: `Your diagnostic is ready.\n\nSign in to unlock your **AI Growth Playbook**.`,
          sender: 'bot',
          timestamp: new Date(),
          showAuthGate: true,
        };
        setMessages(prev => [...prev, authMsg]);
        setFlowStage('auth-gate');
      }
      return;
    }

    // ── Fallback Mode: static pre-loaded questions ──────────────
    // Record answer in backend session
    try {
      const sid = getSessionId();
      if (sid) {
        await fetch(`${API_BASE}/api/v1/agent/session/answer`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            session_id: sid,
            question_index: currentDynamicQIndex,
            answer: answer
          })
        });
      }
    } catch (e) {
      console.log('Session tracking: dynamic answer', e);
    }

    // Move to next question or get recommendations
    if (currentDynamicQIndex < dynamicQuestions.length - 1) {
      const nextQ = dynamicQuestions[currentDynamicQIndex + 1];
      const sectionLabel = nextQ.section_label || 'Diagnostic';
      const botMsg = {
        id: getNextMessageId(),
        text: `**${sectionLabel}**\n\n${nextQ.question}`,
        sender: 'bot',
        timestamp: new Date(),
        diagnosticOptions: nextQ.options,
        sectionIndex: currentDynamicQIndex + 1,
        sectionKey: nextQ.section,
        allowsFreeText: nextQ.allows_free_text !== false,
      };
      setMessages(prev => [...prev, userMsg, botMsg]);
      setCurrentDynamicQIndex(currentDynamicQIndex + 1);
      setAnswerProcessing(false);
    } else {
      // All dynamic questions answered — gate behind auth
      setMessages(prev => [...prev, userMsg]);
      setCurrentDynamicQIndex(prev => prev + 1);
      crawlSummaryRef.current = null;

      if (userEmail) {
        await startPlaybook();
      } else {
        pendingAuthActionRef.current = 'recommendations';
        pendingReportDataRef.current = { rcaSummary: '', crawlPoints: [] };
        const authMsg = {
          id: getNextMessageId(),
          text: `Your diagnostic is ready.\n\nSign in to unlock your **AI Growth Playbook**.`,
          sender: 'bot',
          timestamp: new Date(),
          showAuthGate: true,
        };
        setMessages(prev => [...prev, authMsg]);
        setFlowStage('auth-gate');
        setAnswerProcessing(false);
      }
    }
  };

  // Handle free-text submission for dynamic question
  const handleDynamicFreeTextSubmit = () => {
    if (dynamicFreeText.trim()) {
      handleDynamicAnswer(dynamicFreeText.trim());
    }
  };

  // Handle website URL submission for audience analysis
  const handleWebsiteSubmit = async (websiteUrl) => {
    if (!websiteUrl || !websiteUrl.trim()) return;

    let url = websiteUrl.trim();
    if (!url.startsWith('http://') && !url.startsWith('https://')) {
      url = 'https://' + url;
    }

    const userMsg = {
      id: getNextMessageId(),
      text: url,
      sender: 'user',
      timestamp: new Date(),
    };
    setMessages(prev => [...prev, userMsg]);
    setIsTyping(true);

    try {
      const sid = getSessionId();
      if (sid) {
        const res = await fetch(`${API_BASE}/api/v1/agent/session/website`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ session_id: sid, website_url: url })
        });
        const data = await res.json();

        if (data.audience_insights) {
          let insightText = `## Audience Analysis for Your Business\n\n`;

          if (data.business_summary) {
            insightText += `${data.business_summary}\n\n`;
          }

          insightText += `---\n\n`;

          if (data.audience_insights.intended_audience) {
            insightText += `**🎯 Who you're targeting:**\n${data.audience_insights.intended_audience}\n\n`;
          }

          if (data.audience_insights.actual_audience) {
            insightText += `**👥 Who your content actually reaches:**\n${data.audience_insights.actual_audience}\n\n`;
          }

          if (data.audience_insights.mismatch_analysis) {
            insightText += `**⚡ The Gap:**\n${data.audience_insights.mismatch_analysis}\n\n`;
          }

          if (data.audience_insights.recommendations && data.audience_insights.recommendations.length > 0) {
            insightText += `**💡 Quick Wins:**\n`;
            data.audience_insights.recommendations.forEach((rec, i) => {
              insightText += `${i + 1}. ${rec}\n`;
            });
            insightText += `\n`;
          }

          insightText += `---\n\n`;
          insightText += `Now let me put together your **personalized tool recommendations** based on everything we've discussed.`;

          const insightMsg = {
            id: getNextMessageId(),
            text: insightText,
            sender: 'bot',
            timestamp: new Date(),
            isAudienceInsight: true,
          };
          setMessages(prev => [...prev, insightMsg]);
        }
      }
    } catch (e) {
      console.log('Website analysis failed, continuing to recommendations', e);
    }

    setIsTyping(false);

    // Proceed to auth gate or playbook
    crawlSummaryRef.current = null;
    if (userEmail) {
      await startPlaybook();
    } else {
      pendingAuthActionRef.current = 'recommendations';
      pendingReportDataRef.current = { rcaSummary: '', crawlPoints: [] };
      const authMsg = {
        id: getNextMessageId(),
        text: `Your diagnostic is ready.\n\nSign in to unlock your **AI Growth Playbook**.`,
        sender: 'bot',
        timestamp: new Date(),
        showAuthGate: true,
      };
      setMessages(prev => [...prev, authMsg]);
      setFlowStage('auth-gate');
    }
  };

  // ── Resume diagnostic questions after URL input ──────────────
  const resumeDiagnosticQuestions = () => {
    const pending = pendingDiagnosticDataRef.current;
    if (!pending) return;

    const { data, isRca, task } = pending;
    pendingDiagnosticDataRef.current = null;

    if (data.questions && data.questions.length > 0) {
      const firstQ = data.questions[0];
      const sectionLabel = firstQ.section_label || 'Diagnostic';
      const taskMatched = data.task_matched || task;

      // Build text: insight (if available) + question (no acknowledgment)
      const insight = firstQ.insight || data.insight || '';
      let botText = '';
      if (isRca) {
        const parts = [];
        if (insight) parts.push(`💡 *${insight}*`);
        parts.push(firstQ.question);
        botText = parts.join('\n\n');
      } else {
        botText = `**${sectionLabel}** for *${taskMatched}*\n\n${firstQ.question}`;
      }

      const botMsg = {
        id: getNextMessageId(),
        text: botText,
        sender: 'bot',
        timestamp: new Date(),
        diagnosticOptions: firstQ.options,
        sectionIndex: 0,
        sectionKey: firstQ.section,
        allowsFreeText: firstQ.allows_free_text !== false,
        isRcaQuestion: isRca,
        insightText: insight,
      };
      setMessages(prev => [...prev, botMsg]);
      setFlowStage('dynamic-questions');
    }
  };

  // ── Scale Questions — between URL input and Opus deep-dive ──────
  const startScaleQuestions = async () => {
    const sid = getSessionId();
    if (!sid) { resumeDiagnosticQuestions(); return; }

    try {
      const res = await fetch(`${API_BASE}/api/v1/agent/session/${sid}/scale-questions`);
      const data = await res.json();

      if (!data.questions || data.questions.length === 0) {
        resumeDiagnosticQuestions();
        return;
      }

      setScaleQuestions(data.questions);
      setCurrentScaleQIndex(0);
      scaleAnswersRef.current = {};
      setScaleFormSelections({});
      setScaleFormSubmitted(false);

      const introMsg = {
        id: getNextMessageId(),
        text: `Before we dive deep, a few quick questions to understand your business context better.`,
        sender: 'bot',
        timestamp: new Date(),
        showScaleForm: true,
      };
      setMessages(prev => [...prev, introMsg]);
      setFlowStage('scale-questions');
    } catch (e) {
      console.log('Failed to load scale questions, continuing to diagnostic', e);
      resumeDiagnosticQuestions();
    }
  };

  const handleScaleFormSubmit = async () => {
    const allAnswered = scaleQuestions.every(q => {
      const sel = scaleFormSelections[q.id];
      return q.multiSelect
        ? Array.isArray(sel) && sel.length > 0
        : !!sel;
    });
    if (!allAnswered) return;

    scaleAnswersRef.current = { ...scaleFormSelections };
    setScaleFormSubmitted(true);

    const summaryLines = scaleQuestions.map(q => {
      const val = scaleFormSelections[q.id];
      return `${q.icon} ${Array.isArray(val) ? val.join(', ') : val}`;
    });
    const userMsg = {
      id: getNextMessageId(),
      text: summaryLines.join('\n'),
      sender: 'user',
      timestamp: new Date(),
    };
    setMessages(prev => [...prev, userMsg]);

    {
      setFlowStage('dynamic-questions');
      setIsTyping(true);

      // Submit scale answers while fetching diagnostic question
      const sid = getSessionId();
      const submitScalePromise = (async () => {
        try {
          if (sid) {
            await fetch(`${API_BASE}/api/v1/agent/session/scale-answers`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                session_id: sid,
                answers: scaleAnswersRef.current,
              }),
            });
          }
        } catch (e) {
          console.log('Scale answers submission failed (non-blocking)', e);
        }
      })();

      // Wait for scale answers to submit
      await submitScalePromise;

      // ── Business Intelligence Verdict — DISABLED (removed from chat) ──

      const transitionMsg = {
        id: getNextMessageId(),
        text: `Now let me ask you some deeper diagnostic questions to pinpoint the exact bottleneck.`,
        sender: 'bot',
        timestamp: new Date(),
      };
      setMessages(prev => [...prev, transitionMsg]);

      try {
        if (sid) {
          const diagRes = await fetch(`${API_BASE}/api/v1/agent/session/start-diagnostic`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ session_id: sid }),
          });
          const diagData = await diagRes.json();

          if (diagData.question && diagData.rca_mode) {
            const firstQ = diagData.question;
            setRcaMode(true);
            setDynamicQuestions([firstQ]);
            setCurrentDynamicQIndex(0);
            setDynamicAnswers({});

            const insight = firstQ.insight || diagData.insight || '';
            const parts = [];
            if (insight) parts.push(`💡 *${insight}*`);
            parts.push(firstQ.question);

            const botMsg = {
              id: getNextMessageId(),
              text: parts.join('\n\n'),
              sender: 'bot',
              timestamp: new Date(),
              diagnosticOptions: firstQ.options,
              sectionIndex: 0,
              sectionKey: firstQ.section,
              allowsFreeText: firstQ.allows_free_text !== false,
              isRcaQuestion: true,
              insightText: insight,
            };
            setMessages(prev => [...prev, botMsg]);
            setIsTyping(false);
            pendingDiagnosticDataRef.current = null;
            return;
          }
        }
      } catch (e) {
        console.log('Context-aware diagnostic failed, using stashed question', e);
      }

      setIsTyping(false);
      resumeDiagnosticQuestions();
    }
  };

  // ── Business URL submission (right after tool recommendations) ──
  const handleBusinessUrlSubmit = async (urlInput) => {
    if (!urlInput || !urlInput.trim()) return;

    let url = urlInput.trim();
    if (!url.startsWith('http://') && !url.startsWith('https://')) {
      url = 'https://' + url;
    }

    const domainRegex = /^https?:\/\/[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?(\.[a-zA-Z]{2,})+/;
    if (!domainRegex.test(url)) {
      const errorMsg = {
        id: getNextMessageId(),
        text: `That doesn't look like a valid URL. Please enter a website address like **yourcompany.com**.`,
        sender: 'bot',
        timestamp: new Date(),
        isError: true,
        showBusinessUrlInput: true,
      };
      setMessages(prev => [...prev, errorMsg]);
      return;
    }

    const userMsg = {
      id: getNextMessageId(),
      text: url,
      sender: 'user',
      timestamp: new Date(),
    };
    setMessages(prev => [...prev, userMsg]);

    try {
      const sid = getSessionId();
      if (sid) {
        const res = await fetch(`${API_BASE}/api/v1/agent/session/url`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ session_id: sid, business_url: url })
        });
        const data = await res.json();

        if (data.crawl_started) {
          setCrawlStatus('in_progress');
          startCrawlPolling();
        }

        const confirmMsg = {
          id: getNextMessageId(),
          text: data.message || `Got it! I'm analyzing **${new URL(url).hostname}** in the background while we continue.`,
          sender: 'bot',
          timestamp: new Date(),
        };
        setMessages(prev => [...prev, confirmMsg]);
      }
    } catch (e) {
      console.log('URL submission failed', e);
      const fallbackMsg = {
        id: getNextMessageId(),
        text: `I'll analyze your website shortly. Let's continue with a few more questions.`,
        sender: 'bot',
        timestamp: new Date(),
      };
      setMessages(prev => [...prev, fallbackMsg]);
    }

    startScaleQuestions();
  };

  const handleSkipBusinessUrl = () => {
    const userMsg = {
      id: getNextMessageId(),
      text: "Skip for now",
      sender: 'user',
      timestamp: new Date(),
    };
    setMessages(prev => [...prev, userMsg]);

    try {
      const sid = getSessionId();
      if (sid) {
        fetch(`${API_BASE}/api/v1/agent/session/skip-url`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ session_id: sid })
        });
      }
    } catch (e) {
      console.log('Skip URL notification failed', e);
    }

    const skipMsg = {
      id: getNextMessageId(),
      text: `No problem — we'll give general recommendations. You can always add your URL later.\n\nLet's continue with a few questions to understand your needs better.`,
      sender: 'bot',
      timestamp: new Date(),
    };
    setMessages(prev => [...prev, skipMsg]);
    setCrawlStatus('skipped');
    startScaleQuestions();
  };

  const showCrawlSummaryMessage = (summaryData) => {
    if (!summaryData || !summaryData.points || summaryData.points.length === 0) return;
    const bullets = summaryData.points.map(p => `• ${p}`).join('\n');
    const summaryMsg = {
      id: getNextMessageId(),
      text: `**🔍 Website Analysis Complete**\n\n${bullets}`,
      sender: 'bot',
      timestamp: new Date(),
      crawlSummaryPoints: summaryData.points,
      showCrawlDetails: true,
    };
    setMessages(prev => [...prev, summaryMsg]);
  };

  const startCrawlPolling = () => {
    if (crawlPollRef.current) clearInterval(crawlPollRef.current);
    crawlPollRef.current = setInterval(async () => {
      try {
        const sid = getSessionId();
        if (!sid) return;
        const res = await fetch(`${API_BASE}/api/v1/agent/session/${sid}/crawl-status`);
        const data = await res.json();
        if (data.crawl_status === 'complete' || data.crawl_status === 'failed') {
          setCrawlStatus(data.crawl_status);
          clearInterval(crawlPollRef.current);
          crawlPollRef.current = null;

          // Stash crawl summary — will be shown after diagnostic completes
          if (data.crawl_status === 'complete' && data.crawl_summary) {
            crawlSummaryRef.current = data.crawl_summary;
          }
        }
      } catch (e) {
        console.log('Crawl status poll failed', e);
      }
    }, 3000);
  };

  // Skip website analysis and go directly to recommendations
  const handleSkipWebsite = async () => {
    const userMsg = {
      id: getNextMessageId(),
      text: "Skip for now",
      sender: 'user',
      timestamp: new Date(),
    };
    setMessages(prev => [...prev, userMsg]);

    startScaleQuestions();
  };

  // Handle "Skip" on auth gate — proceed without signing in
  const handleSkipAuth = () => {
    pendingAuthActionRef.current = null;
    pendingReportDataRef.current = null;
    startPlaybook();
  };

  // ── AI Playbook — replaces old diagnostic report ──
  const startPlaybook = async () => {
    setFlowStage('playbook');
    setPlaybookStage('starting');
    setIsTyping(true);

    const startMsg = {
      id: getNextMessageId(),
      text: '🚀 Building your **AI Growth Playbook**...\n\nAnalysing business context and ICP...',
      sender: 'bot',
      timestamp: new Date(),
    };
    setMessages(prev => [...prev, startMsg]);

    try {
      const sid = getSessionId();

      const startRes = await fetch(`${API_BASE}/api/v1/playbook/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sid }),
      });

      if (!startRes.ok) {
        const errBody = await startRes.json().catch(() => ({}));
        console.error('Playbook /start error:', startRes.status, errBody);
        throw new Error(errBody.detail || `Server error ${startRes.status}`);
      }

      const startData = await startRes.json();

      const parsedGaps = startData.gap_questions_parsed || [];
      if (startData.stage === 'gap_questions' && parsedGaps.length > 0) {
        setPlaybookStage('gap-questions');
        setPlaybookGapQuestions(startData.gap_questions);
        setPlaybookGapSelections({});
        setIsTyping(false);

        const gapMsg = {
          id: getNextMessageId(),
          text: '',
          sender: 'bot',
          timestamp: new Date(),
          isPlaybookGapQuestions: true,
          gapQuestionsText: startData.gap_questions,
          gapQuestionsParsed: parsedGaps,
          agent1Output: startData.agent1_output,
          agent2Output: startData.agent2_output,
        };
        setMessages(prev => [...prev, gapMsg]);
        return;
      }

      setPlaybookStage('generating');
      setMessages(prev => {
        const updated = [...prev];
        const lastBot = updated.reduce((acc, m, i) => m.sender === 'bot' ? i : acc, -1);
        if (lastBot >= 0) {
          updated[lastBot] = { ...updated[lastBot], text: '🚀 Building your **AI Growth Playbook**...\n\nContext parsed ✓ ICP built ✓\n\nGenerating 10-step playbook, tool matrix & website audit...' };
        }
        return updated;
      });

      // Fetch website snapshot (non-blocking) to show while playbook generates
      fetch(`${API_BASE}/api/v1/agent/session/${sid}/website-snapshot`)
        .then(r => r.json())
        .then(snap => {
          if (snap.available) {
            setMessages(prev => [...prev, {
              id: getNextMessageId(),
              text: '',
              sender: 'bot',
              timestamp: new Date(),
              showOutcomeOptions: false,
              isWebsiteSnapshot: true,
              snapshotData: snap,
            }]);
          }
        })
        .catch(() => {});

      const genRes = await fetch(`${API_BASE}/api/v1/playbook/generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sid }),
      });

      if (!genRes.ok) {
        const errBody = await genRes.json().catch(() => ({}));
        console.error('Playbook /generate error:', genRes.status, errBody);
        throw new Error(errBody.detail || `Server error ${genRes.status}`);
      }

      const genData = await genRes.json();

      setPlaybookStage('complete');
      setIsTyping(false);

      const playbookMsg = {
        id: getNextMessageId(),
        text: '',
        sender: 'bot',
        timestamp: new Date(),
        isPlaybook: true,
        playbookData: {
          contextBrief: genData.context_brief || '',
          icpCard: genData.icp_card || '',
          playbook: genData.playbook || '',
          toolMatrix: genData.tool_matrix || '',
          websiteAudit: genData.website_audit || '',
          latencies: genData.latencies || {},
        },
      };
      setMessages(prev => [...prev, playbookMsg]);

    } catch (error) {
      console.error('Playbook generation failed:', error);
      setIsTyping(false);
      setPlaybookStage('');
      const errMsg = {
        id: getNextMessageId(),
        text: `Sorry, something went wrong generating your playbook: ${error.message || 'Unknown error'}. Please try again.`,
        sender: 'bot',
        timestamp: new Date(),
      };
      setMessages(prev => [...prev, errMsg]);
    }
  };

  // ── Handle gap question answer submission ──
  const handlePlaybookGapSubmit = async () => {
    // Build answer text from selections if available, else fallback to textarea
    const answerText = Object.keys(playbookGapSelections).length > 0
      ? Object.entries(playbookGapSelections).map(([qId, opt]) => `${qId}: ${opt}`).join('\n')
      : playbookGapAnswer.trim();
    if (!answerText) return;

    const userMsg = {
      id: getNextMessageId(),
      text: answerText,
      sender: 'user',
      timestamp: new Date(),
    };
    setMessages(prev => [...prev, userMsg]);

    setPlaybookStage('generating');
    setIsTyping(true);
    setPlaybookGapAnswer('');

    const genMsg = {
      id: getNextMessageId(),
      text: '🚀 Got it! Now generating your **10-step playbook**, tool matrix & website audit...',
      sender: 'bot',
      timestamp: new Date(),
    };
    setMessages(prev => [...prev, genMsg]);

    try {
      const sid = getSessionId();

      const gapRes = await fetch(`${API_BASE}/api/v1/playbook/gap-answers`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sid, answers: answerText }),
      });

      if (!gapRes.ok) {
        const errBody = await gapRes.json().catch(() => ({}));
        throw new Error(errBody.detail || `Server error ${gapRes.status}`);
      }

      // Fetch website snapshot (non-blocking) to show while playbook generates
      fetch(`${API_BASE}/api/v1/agent/session/${sid}/website-snapshot`)
        .then(r => r.json())
        .then(snap => {
          if (snap.available) {
            setMessages(prev => [...prev, {
              id: getNextMessageId(),
              text: '',
              sender: 'bot',
              timestamp: new Date(),
              showOutcomeOptions: false,
              isWebsiteSnapshot: true,
              snapshotData: snap,
            }]);
          }
        })
        .catch(() => {});

      const genRes = await fetch(`${API_BASE}/api/v1/playbook/generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sid, gap_answers: answerText }),
      });

      if (!genRes.ok) {
        const errBody = await genRes.json().catch(() => ({}));
        throw new Error(errBody.detail || `Server error ${genRes.status}`);
      }

      const genData = await genRes.json();

      setPlaybookStage('complete');
      setIsTyping(false);

      const playbookMsg = {
        id: getNextMessageId(),
        text: '',
        sender: 'bot',
        timestamp: new Date(),
        isPlaybook: true,
        playbookData: {
          contextBrief: genData.context_brief || '',
          icpCard: genData.icp_card || '',
          playbook: genData.playbook || '',
          toolMatrix: genData.tool_matrix || '',
          websiteAudit: genData.website_audit || '',
          latencies: genData.latencies || {},
        },
      };
      setMessages(prev => [...prev, playbookMsg]);

    } catch (error) {
      console.error('Playbook generation failed:', error);
      setIsTyping(false);
      setPlaybookStage('');
      const errMsg = {
        id: getNextMessageId(),
        text: `Sorry, something went wrong generating your playbook: ${error.message || 'Unknown error'}. Please try again.`,
        sender: 'bot',
        timestamp: new Date(),
      };
      setMessages(prev => [...prev, errMsg]);
    }
  };

  // Get personalized recommendations from backend
  const showPersonalizedRecommendations = async () => {
    setFlowStage('complete');
    setIsTyping(true);

    try {
      const sid = getSessionId();
      const res = await fetch(`${API_BASE}/api/v1/agent/session/recommend`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sid })
      });
      const data = await res.json();

      const outcomeLabel = outcomeOptions.find(g => g.id === selectedGoal)?.text || selectedGoal;
      const domainLabel = selectedDomainName || 'General';

      let solutionResponse = `## Personalized Solution Pathways\n\n`;
      solutionResponse += `Based on your specific situation in **${domainLabel}** — **${selectedCategory}**, here are the tools I recommend for you.\n\n`;

      if (data.summary) {
        solutionResponse += `> ${data.summary}\n\n`;
      }

      solutionResponse += `---\n\n`;

      // Section 1: Extensions
      if (data.extensions && data.extensions.length > 0) {
        solutionResponse += `## Tools & Extensions\n\n`;
        data.extensions.forEach((ext) => {
          const freeTag = ext.free ? 'Free' : 'Paid';
          solutionResponse += `**${ext.name}** ${freeTag}\n`;
          solutionResponse += `> ${ext.description}\n`;
          if (ext.why_recommended) solutionResponse += `> **Why for you:** ${ext.why_recommended}\n`;
          if (ext.url) solutionResponse += `> [Visit](${ext.url})\n`;
          solutionResponse += `\n`;
        });
        solutionResponse += `---\n\n`;
      }

      // Section 2: GPTs
      if (data.gpts && data.gpts.length > 0) {
        solutionResponse += `## Custom GPTs\n\n`;
        data.gpts.forEach((gpt) => {
          solutionResponse += `**${gpt.name}**${gpt.rating ? ` ⭐${gpt.rating}` : ''}\n`;
          solutionResponse += `> ${gpt.description}\n`;
          if (gpt.why_recommended) solutionResponse += `> **Why for you:** ${gpt.why_recommended}\n`;
          if (gpt.url) solutionResponse += `> [Try it](${gpt.url})\n`;
          solutionResponse += `\n`;
        });
        solutionResponse += `---\n\n`;
      }

      // Section 3: Companies
      if (data.companies && data.companies.length > 0) {
        solutionResponse += `## AI Solution Providers\n\n`;
        data.companies.forEach((co) => {
          solutionResponse += `**${co.name}**\n`;
          solutionResponse += `> ${co.description}\n`;
          if (co.why_recommended) solutionResponse += `> **Why for you:** ${co.why_recommended}\n`;
          if (co.url) solutionResponse += `> [Learn more](${co.url})\n`;
          solutionResponse += `\n`;
        });
        solutionResponse += `---\n\n`;
      }

      solutionResponse += `### What would you like to do next?`;

      const immediatePrompt = generateImmediatePrompt(selectedGoal, domainLabel, selectedCategory, selectedCategory);

      const finalOutput = {
        id: getNextMessageId(),
        text: solutionResponse,
        sender: 'bot',
        timestamp: new Date(),
        showFinalActions: true,
        showCopyPrompt: true,
        immediatePrompt: immediatePrompt,
        companies: data.companies || [],
        extensions: data.extensions || [],
        customGPTs: data.gpts || [],
        userRequirement: selectedCategory
      };

      setMessages(prev => [...prev, finalOutput]);
      setIsTyping(false);
    } catch (error) {
      console.error('Personalized recommendations failed, falling back:', error);
      setIsTyping(false);
      // Fallback to original solution stack
      showSolutionStack(selectedCategory);
    }
  };

  // Handle "Type here" button click - skip category selection
  const handleTypeCustomProblem = () => {
    const userMessage = {
      id: getNextMessageId(),
      text: `I'll describe my problem`,
      sender: 'user',
      timestamp: new Date()
    };

    // For custom problems, still ask for details
    setFlowStage('requirement');
    const botMessage = {
      id: getNextMessageId(),
      text: `No problem!\n\n**Please describe what you're trying to achieve or the problem you want to solve:**\n\n_(Tell me in 2-3 lines so I can find the best solutions for you)_`,
      sender: 'bot',
      timestamp: new Date()
    };

    setMessages(prev => [...prev, userMessage, botMessage]);
    saveToSheet(`User chose to type custom problem`, '', '', '');
  };

  // Show solution stack directly after task selection - CHAT VERSION (Stage 1 Format)
  const showSolutionStack = async (category) => {
  setFlowStage('complete');
  setIsTyping(true);

  // FIX: Define these variables at the top so they are available everywhere in the function
  const outcomeLabel = outcomeOptions.find(g => g.id === selectedGoal)?.text || selectedGoal;
  const domainLabel = selectedDomainName || 'General';
  const roleLabel = selectedDomainName || 'General';

  try {
    // Search for relevant companies from CSV
    let relevantCompanies = [];
    try {
      // Get outcome and domain labels for display
      const outcomeLabel = outcomeOptions.find(g => g.id === selectedGoal)?.text || selectedGoal;
      const domainLabel = selectedDomainName || 'General';

      // Search for relevant companies from CSV
      let relevantCompanies = [];
      try {
        const searchResponse = await fetch('/api/search-companies', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            domain: category,
            subdomain: category,
            requirement: category,
            goal: selectedGoal,
            role: selectedDomainName,
            userContext: {
              goal: selectedGoal,
              domain: selectedDomainName,
              category: category
            }
          })
        });
        const searchData = await searchResponse.json();
        relevantCompanies = (searchData.companies || []).slice(0, 3);
      } catch (e) {
        console.log('Company search failed, using fallback');
        relevantCompanies = [
          { name: 'Bardeen', problem: 'Automate any browser workflow with AI', differentiator: 'No-code browser automation' },
          { name: 'Zapier', problem: 'Connect 5000+ apps without code', differentiator: 'Largest integration library' },
          { name: 'Make (Integromat)', problem: 'Visual automation builder', differentiator: 'Complex workflow scenarios' }
        ];
      }

      // Get relevant Chrome extensions and GPTs
      let extensions = getRelevantExtensions(category, selectedGoal);
      let customGPTs = getRelevantGPTs(category, selectedGoal, selectedDomainName);

      // Use fallbacks if empty
      if (extensions.length === 0) {
        extensions = [
          { name: 'Bardeen', description: 'Automate browser tasks with AI', free: true, source: 'Chrome Web Store' },
          { name: 'Notion Web Clipper', description: 'Save anything instantly', free: true, source: 'Chrome Web Store' },
          { name: 'Grammarly', description: 'Write better emails & docs', free: true, source: 'Chrome Web Store' }
        ];
      }

      if (customGPTs.length === 0) {
        customGPTs = [
          { name: 'Task Prioritizer GPT', description: 'Organize your to-dos efficiently', rating: '4.7' },
          { name: 'Data Analyst GPT', description: 'Analyze data & create charts', rating: '4.9' },
          { name: 'Automation Expert GPT', description: 'Design smart workflows', rating: '4.7' }
        ];
      }

      if (relevantCompanies.length === 0) {
        relevantCompanies = [
          { name: 'Bardeen', problem: 'Automate any browser workflow with AI', differentiator: 'No-code browser automation' },
          { name: 'Zapier', problem: 'Connect 5000+ apps without code', differentiator: 'Largest integration library' },
          { name: 'Make (Integromat)', problem: 'Visual automation builder', differentiator: 'Complex workflow scenarios' }
        ];
      }

      // Generate the immediate action prompt
      const immediatePrompt = generateImmediatePrompt(selectedGoal, roleLabel, category, category);

      // Build Stage 1 Desired Output Format - Chat Response
      let solutionResponse = `## Recommended Solution Pathways (Immediate Action)\n\n`;
      solutionResponse += `I recommend the following solution pathways that you can start implementing immediately, based on your current setup and goals.\n\n`;
      solutionResponse += `---\n\n`;

      // Section 1: Tools & Extensions (If Google Workspace Is Your Main Stack)
      solutionResponse += `## If Google Tools / Google Workspace Is Your Main Stack\n\n`;
      solutionResponse += `If Google Workspace is your primary tool stack, here are some tools and extensions that integrate well and can be implemented quickly.\n\n`;
      solutionResponse += `### Tools & Extensions\n\n`;

      extensions.slice(0, 3).forEach((ext) => {
        const freeTag = ext.free ? 'Free' : 'Paid';
        solutionResponse += `**${ext.name}** ${freeTag}\n`;
        solutionResponse += `> **Where this helps:** ${ext.description}\n`;
        solutionResponse += `> **Where to find:** ${ext.source || 'Chrome Web Store / Official Website'}\n\n`;
      });

      if (!searchResponse.ok) {
         throw new Error(`Server returned ${searchResponse.status}`);
      }

      // Section 2: Custom GPTs
      solutionResponse += `## Using Custom GPTs for Task Automation & Decision Support\n\n`;
      solutionResponse += `You can also leverage Custom GPTs to automate repetitive thinking tasks, research, analysis, and execution support.\n\n`;
      solutionResponse += `### Custom GPTs\n\n`;

      customGPTs.slice(0, 3).forEach((gpt) => {
        solutionResponse += `**${gpt.name}** ⭐${gpt.rating}\n`;
        solutionResponse += `> **What this GPT does:** ${gpt.description}\n\n`;
      });

      solutionResponse += `---\n\n`;

      // Section 3: AI Companies
      solutionResponse += `## AI Companies Offering Ready-Made Solutions\n\n`;
      solutionResponse += `If you are looking for AI-powered tools and well-structured, ready-made solutions, here are companies whose products align with your needs.\n\n`;
      solutionResponse += `### AI Solution Providers\n\n`;

      relevantCompanies.slice(0, 3).forEach((company) => {
        solutionResponse += `**${company.name}**\n`;
        solutionResponse += `> **What they do:** ${company.problem || company.description || 'AI-powered solution for your needs'}\n\n`;
      });

      solutionResponse += `---\n\n`;

      // Section 4: How to Use This Framework
      solutionResponse += `### How to Use This Framework\n\n`;
      solutionResponse += `1. **Start with Google Workspace tools** for quick wins\n`;
      solutionResponse += `2. **Add Custom GPTs** for intelligence and automation\n`;
      solutionResponse += `3. **Scale using specialized AI companies** when workflows mature\n\n`;

      solutionResponse += `---\n\n`;
      solutionResponse += `### What would you like to do next?`;

      const finalOutput = {
        id: getNextMessageId(),
        text: solutionResponse,
        sender: 'bot',
        timestamp: new Date(),
        showFinalActions: true,
        showCopyPrompt: true,
        immediatePrompt: immediatePrompt,
        companies: relevantCompanies,
        extensions: extensions,
        customGPTs: customGPTs,
        userRequirement: category
      };

      setMessages(prev => [...prev, finalOutput]);
      setIsTyping(false);

      saveToSheet('Solution Stack Generated', `Outcome: ${outcomeLabel}, Domain: ${domainLabel}, Task: ${category}`, category, category);
    } catch (error) {
      console.error('Error generating solution stack:', error);

      // Fallback response with Stage 1 format
      const outcomeLabel = outcomeOptions.find(g => g.id === selectedGoal)?.text || selectedGoal;
      const domainLabel = selectedDomainName || 'General';
      const fallbackPrompt = generateImmediatePrompt(selectedGoal, domainLabel, category, category);

      let fallbackResponse = `## 🎯 Recommended Solution Pathways (Immediate Action)\n\n`;
      fallbackResponse += `I recommend the following solution pathways that you can start implementing immediately.\n\n`;
      fallbackResponse += `---\n\n`;

      fallbackResponse += `## 🔌 If Google Tools / Google Workspace Is Your Main Stack\n\n`;
      fallbackResponse += `### Tools & Extensions\n\n`;
      fallbackResponse += `**🔧 Bardeen** 🆓 Free\n`;
      fallbackResponse += `> **Where this helps:** Automate browser tasks with AI\n`;
      fallbackResponse += `> **Where to find:** Chrome Web Store\n\n`;
      fallbackResponse += `**🔧 Notion Web Clipper** 🆓 Free\n`;
      fallbackResponse += `> **Where this helps:** Save anything instantly\n`;
      fallbackResponse += `> **Where to find:** Chrome Web Store\n\n`;
      fallbackResponse += `**🔧 Grammarly** 🆓 Free\n`;
      fallbackResponse += `> **Where this helps:** Write better emails & docs\n`;
      fallbackResponse += `> **Where to find:** Chrome Web Store\n\n`;

      fallbackResponse += `---\n\n`;
      fallbackResponse += `## 🤖 Using Custom GPTs for Task Automation & Decision Support\n\n`;
      fallbackResponse += `### Custom GPTs\n\n`;
      fallbackResponse += `**🧠 Data Analyst GPT** ⭐4.9\n`;
      fallbackResponse += `> **What this GPT does:** Analyze your data & create charts\n\n`;
      fallbackResponse += `**🧠 Task Prioritizer GPT** ⭐4.7\n`;
      fallbackResponse += `> **What this GPT does:** Plan and organize your work\n\n`;

      fallbackResponse += `---\n\n`;
      fallbackResponse += `## 🚀 AI Companies Offering Ready-Made Solutions\n\n`;
      fallbackResponse += `### AI Solution Providers\n\n`;
      fallbackResponse += `**🏢 Bardeen**\n`;
      fallbackResponse += `> **What they do:** Automate any browser workflow with AI\n\n`;
      fallbackResponse += `**🏢 Zapier**\n`;
      fallbackResponse += `> **What they do:** Connect 5000+ apps without code\n\n`;

      fallbackResponse += `---\n\n`;
      fallbackResponse += `### 📋 How to Use This Framework\n\n`;
      fallbackResponse += `1. **Start with Google Workspace tools** for quick wins\n`;
      fallbackResponse += `2. **Add Custom GPTs** for intelligence and automation\n`;
      fallbackResponse += `3. **Scale using specialized AI companies** when workflows mature\n\n`;
      fallbackResponse += `---\n\n### What would you like to do next?`;

      const fallbackOutput = {
        id: getNextMessageId(),
        text: fallbackResponse,
        sender: 'bot',
        timestamp: new Date(),
        showFinalActions: true,
        showCopyPrompt: true,
        immediatePrompt: fallbackPrompt,
        userRequirement: category
      };

      setMessages(prev => [...prev, fallbackOutput]);
      setIsTyping(false);
    }

    // Get relevant Chrome extensions and GPTs
    let extensions = getRelevantExtensions(category, selectedGoal);
    let customGPTs = getRelevantGPTs(category, selectedGoal, roleLabel);

    // Use fallbacks if empty
    if (extensions.length === 0) {
      extensions = [
        { name: 'Bardeen', description: 'Automate browser tasks with AI', free: true, source: 'Chrome Web Store' },
        { name: 'Notion Web Clipper', description: 'Save anything instantly', free: true, source: 'Chrome Web Store' },
        { name: 'Grammarly', description: 'Write better emails & docs', free: true, source: 'Chrome Web Store' }
      ];
    }

    if (customGPTs.length === 0) {
      customGPTs = [
        { name: 'Task Prioritizer GPT', description: 'Organize your to-dos efficiently', rating: '4.7' },
        { name: 'Data Analyst GPT', description: 'Analyze data & create charts', rating: '4.9' },
        { name: 'Automation Expert GPT', description: 'Design smart workflows', rating: '4.7' }
      ];
    }

    if (relevantCompanies.length === 0) {
      relevantCompanies = [
        { name: 'Bardeen', problem: 'Automate any browser workflow with AI', differentiator: 'No-code browser automation' },
        { name: 'Zapier', problem: 'Connect 5000+ apps without code', differentiator: 'Largest integration library' },
        { name: 'Make (Integromat)', problem: 'Visual automation builder', differentiator: 'Complex workflow scenarios' }
      ];
    }

    // Generate the immediate action prompt
    const immediatePrompt = generateImmediatePrompt(selectedGoal, roleLabel, category, category);

    // Build Stage 1 Desired Output Format - Chat Response
    let solutionResponse = `## 🎯 Recommended Solution Pathways (Immediate Action)\n\n`;
    solutionResponse += `I recommend the following solution pathways that you can start implementing immediately.\n\n`;
    solutionResponse += `---\n\n`;

    // Section 1: Tools & Extensions
    solutionResponse += `## 🔌 If Google Tools / Google Workspace Is Your Main Stack\n\n`;
    solutionResponse += `### Tools & Extensions\n\n`;

    extensions.slice(0, 3).forEach((ext) => {
      const freeTag = ext.free ? '🆓 Free' : '💰 Paid';
      solutionResponse += `**🔧 ${ext.name}** ${freeTag}\n`;
      solutionResponse += `> **Where this helps:** ${ext.description}\n`;
      solutionResponse += `> **Where to find:** ${ext.source || 'Chrome Web Store'}\n\n`;
    });

    solutionResponse += `---\n\n`;

    // Section 2: Custom GPTs
    solutionResponse += `## 🤖 Using Custom GPTs for Task Automation & Decision Support\n\n`;
    solutionResponse += `### Custom GPTs\n\n`;

    customGPTs.slice(0, 3).forEach((gpt) => {
      solutionResponse += `**🧠 ${gpt.name}** ⭐${gpt.rating}\n`;
      solutionResponse += `> **What this GPT does:** ${gpt.description}\n\n`;
    });

    solutionResponse += `---\n\n`;

    // Section 3: AI Companies
    solutionResponse += `## 🚀 AI Companies Offering Ready-Made Solutions\n\n`;
    solutionResponse += `### AI Solution Providers\n\n`;

    relevantCompanies.slice(0, 3).forEach((company) => {
      solutionResponse += `**🏢 ${company.name}**\n`;
      solutionResponse += `> **What they do:** ${company.problem || company.description || 'AI-powered solution'}\n\n`;
    });

    solutionResponse += `---\n\n`;

    // Section 4: How to Use This Framework
    solutionResponse += `### 📋 How to Use This Framework\n\n`;
    solutionResponse += `1. **Start with Google Workspace tools** for quick wins\n`;
    solutionResponse += `2. **Add Custom GPTs** for intelligence and automation\n`;
    solutionResponse += `3. **Scale using specialized AI companies** when workflows mature\n\n`;

    solutionResponse += `---\n\n`;
    solutionResponse += `### What would you like to do next?`;

    const finalOutput = {
      id: getNextMessageId(),
      text: solutionResponse,
      sender: 'bot',
      timestamp: new Date(),
      showFinalActions: true,
      showCopyPrompt: true,
      immediatePrompt: immediatePrompt,
      companies: relevantCompanies,
      extensions: extensions,
      customGPTs: customGPTs,
      userRequirement: category
    };

    setMessages(prev => [...prev, finalOutput]);
    setIsTyping(false);

    // FIX: Passing the now-defined labels to the sheet
    saveToSheet('Solution Stack Generated', `Outcome: ${outcomeLabel}, Domain: ${domainLabel}, Task: ${category}`, category, category);
  } catch (error) {
    console.error('Error generating solution stack:', error);

    // Fallback block now works because labels are defined at the top
    const fallbackPrompt = generateImmediatePrompt(selectedGoal, roleLabel, category, category);

    let fallbackResponse = `## 🎯 Recommended Solution Pathways (Immediate Action)\n\n`;
    fallbackResponse += `I recommend the following solution pathways that you can start implementing immediately.\n\n---\n\n`;
    fallbackResponse += `## 🔌 If Google Tools / Google Workspace Is Your Main Stack\n\n### Tools & Extensions\n\n`;
    fallbackResponse += `**🔧 Bardeen** 🆓 Free\n> **Where this helps:** Automate browser tasks with AI\n\n`;
    fallbackResponse += `**🔧 Notion Web Clipper** 🆓 Free\n> **Where this helps:** Save anything instantly\n\n`;
    fallbackResponse += `---\n\n## 🤖 Using Custom GPTs for Task Automation & Decision Support\n\n### Custom GPTs\n\n`;
    fallbackResponse += `**🧠 Data Analyst GPT** ⭐4.9\n> **What this GPT does:** Analyze your data & create charts\n\n`;
    fallbackResponse += `---\n\n### What would you like to do next?`;

    const fallbackOutput = {
      id: getNextMessageId(),
      text: fallbackResponse,
      sender: 'bot',
      timestamp: new Date(),
      showFinalActions: true,
      showCopyPrompt: true,
      immediatePrompt: fallbackPrompt,
      userRequirement: category
    };

    setMessages(prev => [...prev, fallbackOutput]);
    setIsTyping(false);
  }
};

  // Handle explore implementation - switch to chat mode
  const handleExploreImplementation = () => {
    setShowDashboard(false);

    // Add context message to chat
    const contextMessage = {
      id: getNextMessageId(),
      text: `Great! Let's explore how to implement solutions for **${dashboardData.category}**.\n\nI can help you with:\n- Setting up the recommended tools\n- Step-by-step implementation guides\n- Integration tips and best practices\n\n**What would you like to learn more about?**`,
      sender: 'bot',
      timestamp: new Date(),
      showFinalActions: true,
      companies: dashboardData.companies,
      userRequirement: dashboardData.category
    };

    setMessages(prev => [...prev, contextMessage]);
  };

  // Copy prompt to clipboard
  const handleCopyPrompt = async () => {
    try {
      await navigator.clipboard.writeText(dashboardData.immediatePrompt);
      setCopiedPrompt(true);
      setTimeout(() => setCopiedPrompt(false), 2000);
    } catch (err) {
      console.error('Failed to copy:', err);
    }
  };

  // Handle custom category input
  const handleCustomCategorySubmit = (customText) => {
    setSelectedCategory(customText);
    setCustomCategoryInput('');

    const userMessage = {
      id: getNextMessageId(),
      text: `${customText}`,
      sender: 'user',
      timestamp: new Date()
    };

    setFlowStage('requirement');
    const botMessage = {
      id: getNextMessageId(),
      text: `Got it!\n\nYou're looking to work on: **${customText}**\n\n**Please share more details about your specific problem:**\n\n_(Tell me in 2-3 lines so I can find the best solutions for you)_`,
      sender: 'bot',
      timestamp: new Date()
    };

    setMessages(prev => [...prev, userMessage, botMessage]);
    saveToSheet(`Custom Category: ${customText}`, '', '', '');
  };

  const toggleVoiceRecording = () => {
    if (!recognitionRef.current) return;

    if (isRecording) {
      recognitionRef.current.stop();
      setIsRecording(false);
    } else {
      try {
        recognitionRef.current.start();
        setIsRecording(true);
      } catch (error) {
        console.error('Error starting recognition:', error);
      }
    }
  };

  // Legacy domain/subdomain handlers - kept for backward compatibility but not used in new flow
  const handleDomainClick = (domain) => {
    setSelectedDomain(domain);
    // Domain selection is no longer part of main flow, but kept for potential future use
    saveToSheet(`Selected Domain: ${domain.name}`, '', domain.name, '');
  };

  const handleSubDomainClick = (subDomain) => {
    setSelectedSubDomain(subDomain);
    saveToSheet(`Selected Sub-domain: ${subDomain}`, '', selectedDomain?.name, subDomain);
  };

  const handleRoleQuestion = (answer) => {
    const userMessage = {
      id: getNextMessageId(),
      text: answer,
      sender: 'user',
      timestamp: new Date()
    };

    // Simplified role question handling for new flow
    setFlowStage('requirement');
    const botMessage = {
      id: getNextMessageId(),
      text: `Got it! 👍\n\n**What specific problem are you trying to solve right now?**\n\n_(Tell me in 2-3 lines what challenge you're facing and what success would look like for you)_`,
      sender: 'bot',
      timestamp: new Date()
    };
    setMessages(prev => [...prev, userMessage, botMessage]);
    saveToSheet(`Role Question Answer: ${answer}`, '', '', '');
  };

  const saveToSheet = async (userMessage, botResponse, domain = '', subdomain = '') => {
    try {
      await fetch(`${API_BASE}/api/save-idea`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          userMessage,
          botResponse,
          timestamp: new Date().toISOString(),
          userName: userName || 'Pending',
          userEmail: userEmail || 'Pending',
          domain: domain || selectedDomain?.name || '',
          subdomain: subdomain || selectedSubDomain || '',
          requirement: requirement || ''
        })
      });
    } catch (error) {
      console.error('Error saving to sheet:', error);
    }
  };

  const handleLearnImplementation = async (companies, userRequirement) => {
    setIsTyping(true);

    const loadingMessage = {
      id: getNextMessageId(),
      text: "Let me put together a comprehensive implementation guide with practical steps you can start using right away...",
      sender: 'bot',
      timestamp: new Date()
    };
    setMessages(prev => [...prev, loadingMessage]);

    const userType = selectedDomainName || 'General user';
    const businessType = businessContext.businessType || '[YOUR BUSINESS TYPE]';
    const industry = businessContext.industry || '[YOUR INDUSTRY]';
    const targetAudience = businessContext.targetAudience || '[YOUR TARGET AUDIENCE]';
    const marketSegment = businessContext.marketSegment || '[YOUR MARKET SEGMENT]';
    const roleAndIndustry = professionalContext.roleAndIndustry || '[YOUR ROLE & INDUSTRY]';
    const solutionFor = professionalContext.solutionFor || '[YOURSELF/TEAM/COMPANY]';
    const domainName = selectedDomain?.name || '[YOUR DOMAIN]';
    const subDomainName = selectedSubDomain || '[YOUR FOCUS AREA]';
    const topTool = companies[0];

    const contextForPrompts = `I'm exploring solutions in ${selectedDomainName || domainName}. My outcome goal is ${outcomeOptions.find(g => g.id === selectedGoal)?.text || 'business improvement'}.`;

    const starterPrompts = `
---

## START RIGHT NOW - Copy-Paste These Prompts into ChatGPT/Claude

**These prompts are pre-filled with YOUR context. Copy, paste, and get instant results!**

---

### Prompt 1: Clarify Your Problem (Decision-Ready Spec)

\`\`\`
You are my senior operations analyst. Convert my situation into a decision-ready one-page spec with zero fluff.

CONTEXT (messy notes): ${contextForPrompts} My problem: ${userRequirement}
GOAL (desired outcome): [DESCRIBE WHAT SUCCESS LOOKS LIKE]
WHO IT AFFECTS (users/teams): [WHO USES THIS]
CONSTRAINTS (time/budget/tools/policy): [LIST YOUR CONSTRAINTS]
WHAT I'VE TRIED (if any): [PAST ATTEMPTS OR "None yet"]
DEADLINE/URGENCY: [WHEN DO YOU NEED THIS SOLVED?]

Deliver exactly these sections:

1) One-sentence problem statement (include impact)
2) 3 user stories (Primary / Secondary / Admin)
3) Success metrics (3–5) with how to measure each
4) Scope:
   - In-scope (5 bullets)
   - Out-of-scope (5 bullets)
5) Requirements:
   - Must-have (top 5, testable)
   - Nice-to-have (top 5)
6) Constraints & assumptions (bulleted)
7) Top risks + mitigations (5)
8) "First 48 hours" plan (3 concrete actions)

Ask ONLY 3 clarifying questions if required. If not required, proceed with reasonable assumptions and list them.
\`\`\`

---

**Pro tip:** Run Prompt 1 first to clarify your problem. You'll have real, usable outputs within 30 minutes!
`;

    try {
      const apiKey = import.meta.env.VITE_OPENAI_API_KEY;

      const guideHeader = `## Your Implementation Guide for ${topTool?.name || 'Your Solution'}

### 1. Where This Fits in Your Workflow

This solution helps at the **${subDomainName}** stage of your ${domainName} operations.

### 2. What to Prepare Before You Start (Checklist)

- ☐ **3-5 example documents/data** you currently work with
- ☐ **Current workflow steps** written out
- ☐ **Edge cases list** - situations that don't fit the norm
- ☐ **Success metric** - What does "solved" look like?
- ☐ **Constraints** - Budget, timeline, compliance requirements
`;

      if (!apiKey) {
        const fallbackGuide = {
          id: getNextMessageId(),
          text: guideHeader + starterPrompts,
          sender: 'bot',
          timestamp: new Date()
        };
        setMessages(prev => [...prev, fallbackGuide]);
        setIsTyping(false);
        return;
      }

      const response = await fetch('https://api.openai.com/v1/chat/completions', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${apiKey}`
        },
        body: JSON.stringify({
          model: 'gpt-4o-mini',
          messages: [
            { role: 'system', content: `Create a brief implementation guide for ${topTool?.name || 'the solution'}` },
            { role: 'user', content: `Create an implementation guide for: "${userRequirement}"` }
          ],
          temperature: 0.7,
          max_tokens: 1000
        })
      });

      if (response.ok) {
        const data = await response.json();
        const personalizedHeader = data.choices[0]?.message?.content || guideHeader;

        const guideMessage = {
          id: getNextMessageId(),
          text: personalizedHeader + starterPrompts,
          sender: 'bot',
          timestamp: new Date()
        };
        setMessages(prev => [...prev, guideMessage]);
      } else {
        throw new Error('API request failed');
      }
    } catch (error) {
      console.error('Error generating implementation guide:', error);
      const errorMessage = {
        id: getNextMessageId(),
        text: guideHeader + starterPrompts,
        sender: 'bot',
        timestamp: new Date()
      };
      setMessages(prev => [...prev, errorMessage]);
    }

    setIsTyping(false);
  };

  const handleIdentitySubmit = async (name, email) => {
    setUserName(name);
    setUserEmail(email);
    setFlowStage('complete');

    const botMessage = {
      id: getNextMessageId(),
      text: `Thank you, ${name}! 🎯\n\nAnalyzing your requirements and finding the best solutions...`,
      sender: 'bot',
      timestamp: new Date()
    };

    setMessages(prev => [...prev, botMessage]);
    setIsTyping(true);

    await saveToSheet(`User Identity: ${name} (${email})`, '', selectedCategory, requirement);

    setTimeout(async () => {
      try {
        // Get outcome and domain labels for display
        const outcomeLabel = outcomeOptions.find(g => g.id === selectedGoal)?.text || selectedGoal;
        const domainLabel = selectedDomainName || 'General';

        // Search for relevant companies from CSV
        const searchResponse = await fetch('/api/search-companies', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            domain: selectedCategory,
            subdomain: selectedCategory,
            requirement: requirement,
            goal: selectedGoal,
            role: selectedDomainName,
            userContext: {
              goal: selectedGoal,
              domain: selectedDomainName,
              category: selectedCategory
            }
          })
        });

        const searchData = await searchResponse.json();
        let relevantCompanies = (searchData.companies || []).slice(0, 3);

        // Get relevant Chrome extensions and GPTs
        let extensions = getRelevantExtensions(selectedCategory, selectedGoal);
        let customGPTs = getRelevantGPTs(selectedCategory, selectedGoal, selectedDomainName);

        // Use fallbacks if empty
        if (extensions.length === 0) {
          extensions = [
            { name: 'Bardeen', description: 'Automate browser tasks with AI', free: true, source: 'Chrome Web Store' },
            { name: 'Notion Web Clipper', description: 'Save anything instantly', free: true, source: 'Chrome Web Store' },
            { name: 'Grammarly', description: 'Write better emails & docs', free: true, source: 'Chrome Web Store' }
          ];
        }

        if (customGPTs.length === 0) {
          customGPTs = [
            { name: 'Task Prioritizer GPT', description: 'Organize your to-dos efficiently', rating: '4.7' },
            { name: 'Data Analyst GPT', description: 'Analyze data & create charts', rating: '4.9' },
            { name: 'Automation Expert GPT', description: 'Design smart workflows', rating: '4.7' }
          ];
        }

        if (relevantCompanies.length === 0) {
          relevantCompanies = [
            { name: 'Bardeen', problem: 'Automate any browser workflow with AI', differentiator: 'No-code browser automation' },
            { name: 'Zapier', problem: 'Connect 5000+ apps without code', differentiator: 'Largest integration library' },
            { name: 'Make (Integromat)', problem: 'Visual automation builder', differentiator: 'Complex workflow scenarios' }
          ];
        }

        // Generate the immediate action prompt
        const immediatePrompt = generateImmediatePrompt(selectedGoal, roleLabel, selectedCategory, requirement);

        // Build Stage 1 Desired Output Format - Chat Response
        let solutionResponse = `## 🎯 Recommended Solution Pathways (Immediate Action)\n\n`;
        solutionResponse += `I recommend the following solution pathways that you can start implementing immediately, based on your current setup and goals.\n\n`;
        solutionResponse += `---\n\n`;

        // Section 1: Tools & Extensions (If Google Workspace Is Your Main Stack)
        solutionResponse += `## 🔌 If Google Tools / Google Workspace Is Your Main Stack\n\n`;
        solutionResponse += `If Google Workspace is your primary tool stack, here are some tools and extensions that integrate well and can be implemented quickly.\n\n`;
        solutionResponse += `### Tools & Extensions\n\n`;

        extensions.slice(0, 3).forEach((ext) => {
          const freeTag = ext.free ? '🆓 Free' : '💰 Paid';
          solutionResponse += `**🔧 ${ext.name}** ${freeTag}\n`;
          solutionResponse += `> **Where this helps:** ${ext.description}\n`;
          solutionResponse += `> **Where to find:** ${ext.source || 'Chrome Web Store / Official Website'}\n\n`;
        });

        solutionResponse += `---\n\n`;

        // Section 2: Custom GPTs
        solutionResponse += `## 🤖 Using Custom GPTs for Task Automation & Decision Support\n\n`;
        solutionResponse += `You can also leverage Custom GPTs to automate repetitive thinking tasks, research, analysis, and execution support.\n\n`;
        solutionResponse += `### Custom GPTs\n\n`;

        customGPTs.slice(0, 3).forEach((gpt) => {
          solutionResponse += `**🧠 ${gpt.name}** ⭐${gpt.rating}\n`;
          solutionResponse += `> **What this GPT does:** ${gpt.description}\n\n`;
        });

        solutionResponse += `---\n\n`;

        // Section 3: AI Companies
        solutionResponse += `## 🚀 AI Companies Offering Ready-Made Solutions\n\n`;
        solutionResponse += `If you are looking for AI-powered tools and well-structured, ready-made solutions, here are companies whose products align with your needs.\n\n`;
        solutionResponse += `### AI Solution Providers\n\n`;

        relevantCompanies.slice(0, 3).forEach((company) => {
          solutionResponse += `**🏢 ${company.name}**\n`;
          solutionResponse += `> **What they do:** ${company.problem || company.description || 'AI-powered solution for your needs'}\n\n`;
        });

        solutionResponse += `---\n\n`;

        // Section 4: How to Use This Framework
        solutionResponse += `### 📋 How to Use This Framework\n\n`;
        solutionResponse += `1. **Start with Google Workspace tools** for quick wins\n`;
        solutionResponse += `2. **Add Custom GPTs** for intelligence and automation\n`;
        solutionResponse += `3. **Scale using specialized AI companies** when workflows mature\n\n`;

        solutionResponse += `---\n\n`;
        solutionResponse += `### What would you like to do next?`;

        const finalOutput = {
          id: getNextMessageId(),
          text: solutionResponse,
          sender: 'bot',
          timestamp: new Date(),
          showFinalActions: true,
          showCopyPrompt: true,
          immediatePrompt: immediatePrompt,
          companies: relevantCompanies,
          extensions: extensions,
          customGPTs: customGPTs,
          userRequirement: requirement
        };

        setMessages(prev => [...prev, finalOutput]);
        setIsTyping(false);
        setFlowStage('complete');

        saveToSheet('Solution Stack Generated', `Outcome: ${selectedGoal}, Domain: ${selectedDomainName}, Task: ${selectedCategory}`, selectedCategory, requirement);
      } catch (error) {
        console.error('Error generating solution stack:', error);

        // Fallback response with Stage 1 format
        const outcomeLabel = outcomeOptions.find(g => g.id === selectedGoal)?.text || selectedGoal;
        const domainLabel = selectedDomainName || 'General';
        const fallbackPrompt = generateImmediatePrompt(selectedGoal, domainLabel, selectedCategory, requirement);

        let fallbackResponse = `## Recommended Solution Pathways (Immediate Action)\n\n`;
        fallbackResponse += `I recommend the following solution pathways that you can start implementing immediately.\n\n`;
        fallbackResponse += `---\n\n`;

        fallbackResponse += `## If Google Tools / Google Workspace Is Your Main Stack\n\n`;
        fallbackResponse += `### Tools & Extensions\n\n`;
        fallbackResponse += `**Bardeen** Free\n`;
        fallbackResponse += `> **Where this helps:** Automate browser tasks with AI\n`;
        fallbackResponse += `> **Where to find:** Chrome Web Store\n\n`;
        fallbackResponse += `**Notion Web Clipper** Free\n`;
        fallbackResponse += `> **Where this helps:** Save anything instantly\n`;
        fallbackResponse += `> **Where to find:** Chrome Web Store\n\n`;
        fallbackResponse += `**Grammarly** Free\n`;
        fallbackResponse += `> **Where this helps:** Write better emails & docs\n`;
        fallbackResponse += `> **Where to find:** Chrome Web Store\n\n`;

        fallbackResponse += `---\n\n`;
        fallbackResponse += `## Using Custom GPTs for Task Automation & Decision Support\n\n`;
        fallbackResponse += `### Custom GPTs\n\n`;
        fallbackResponse += `**Data Analyst GPT** ⭐4.9\n`;
        fallbackResponse += `> **What this GPT does:** Analyze your data & create charts\n\n`;
        fallbackResponse += `**Task Prioritizer GPT** ⭐4.7\n`;
        fallbackResponse += `> **What this GPT does:** Plan and organize your work\n\n`;

        fallbackResponse += `---\n\n`;
        fallbackResponse += `## AI Companies Offering Ready-Made Solutions\n\n`;
        fallbackResponse += `### AI Solution Providers\n\n`;
        fallbackResponse += `**Bardeen**\n`;
        fallbackResponse += `> **What they do:** Automate any browser workflow with AI\n\n`;
        fallbackResponse += `**Zapier**\n`;
        fallbackResponse += `> **What they do:** Connect 5000+ apps without code\n\n`;

        fallbackResponse += `---\n\n`;
        fallbackResponse += `### How to Use This Framework\n\n`;
        fallbackResponse += `1. **Start with Google Workspace tools** for quick wins\n`;
        fallbackResponse += `2. **Add Custom GPTs** for intelligence and automation\n`;
        fallbackResponse += `3. **Scale using specialized AI companies** when workflows mature\n\n`;
        fallbackResponse += `---\n\n### What would you like to do next?`;

        const fallbackOutput = {
          id: getNextMessageId(),
          text: fallbackResponse,
          sender: 'bot',
          timestamp: new Date(),
          showFinalActions: true,
          showCopyPrompt: true,
          immediatePrompt: fallbackPrompt,
          userRequirement: requirement
        };

        setMessages(prev => [...prev, fallbackOutput]);
        setIsTyping(false);
        setFlowStage('complete');
      }
    }, 2000);
  };

  const handleSend = async () => {
    if (!inputValue.trim()) return;

    const userMessage = {
      id: getNextMessageId(),
      text: inputValue,
      sender: 'user',
      timestamp: new Date()
    };

    setMessages(prev => [...prev, userMessage]);
    const currentInput = inputValue;
    setInputValue('');

    if (flowStage === 'domain') {
      const inputLower = currentInput.toLowerCase().trim();
      const matchedDomain = domains.find(d =>
        d.name.toLowerCase() === inputLower ||
        d.id.toLowerCase() === inputLower ||
        d.name.toLowerCase().includes(inputLower) ||
        inputLower.includes(d.name.toLowerCase())
      );

      if (matchedDomain) {
        handleDomainClick(matchedDomain);
        return;
      }

      setIsTyping(true);

      try {
        const response = await fetch('/api/chat', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            message: currentInput,
            persona: 'assistant',
            context: { isRedirecting: true }
          })
        });

        const data = await response.json();
        const aiAnswer = data.message || "I'm here to help!";

        const botMessage = {
          id: getNextMessageId(),
          text: `${aiAnswer}\n\nNow, to help you find the right business solution, please select a domain from the options below:`,
          sender: 'bot',
          timestamp: new Date()
        };

        setMessages(prev => [...prev, botMessage]);
      } catch (error) {
        console.error('Error calling AI:', error);

        const botMessage = {
          id: getNextMessageId(),
          text: `I'd love to help! To get started, please select a domain from the options below:`,
          sender: 'bot',
          timestamp: new Date()
        };

        setMessages(prev => [...prev, botMessage]);
      } finally {
        setIsTyping(false);
      }

      return;
    }

    if (flowStage === 'subdomain') {
      const inputLower = currentInput.toLowerCase().trim();
      const availableSubDomains = subDomains[selectedDomain?.id] || [];
      const matchedSubDomain = availableSubDomains.find(sd =>
        sd.toLowerCase() === inputLower ||
        sd.toLowerCase().includes(inputLower) ||
        inputLower.includes(sd.toLowerCase())
      );

      if (matchedSubDomain) {
        handleSubDomainClick(matchedSubDomain);
        return;
      }

      setIsTyping(true);

      try {
        const response = await fetch('/api/chat', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            message: currentInput,
            persona: 'assistant',
            context: { isRedirecting: true, domain: selectedDomain?.name }
          })
        });

        const data = await response.json();
        const aiAnswer = data.message || "Great question!";

        const botMessage = {
          id: getNextMessageId(),
          text: `${aiAnswer}\n\nNow, please choose a specific area from the options below:`,
          sender: 'bot',
          timestamp: new Date()
        };

        setMessages(prev => [...prev, botMessage]);
      } catch (error) {
        console.error('Error calling AI:', error);

        const botMessage = {
          id: getNextMessageId(),
          text: `Great! Now please choose a specific area from the options below:`,
          sender: 'bot',
          timestamp: new Date()
        };

        setMessages(prev => [...prev, botMessage]);
      } finally {
        setIsTyping(false);
      }

      return;
    }

    if (flowStage === 'other-domain') {
      setSelectedDomain({ id: 'other', name: currentInput, emoji: '✨' });
      setSelectedSubDomain(currentInput);
      setFlowStage('requirement');

      const botMessage = {
        id: getNextMessageId(),
        text: `Got it! **${currentInput}** - that's interesting! 🎯\n\n**Please describe what you're trying to achieve or the problem you want to solve:**\n\n_(Tell me in 2-3 lines so I can find the best solutions for you)_`,
        sender: 'bot',
        timestamp: new Date()
      };

      setMessages(prev => [...prev, botMessage]);
      saveToSheet(`Custom Domain: ${currentInput}`, '', currentInput, currentInput);
      return;
    }

    if (flowStage.startsWith('role-q')) {
      setMessages(prev => prev.slice(0, -1));
      handleRoleQuestion(currentInput);
      return;
    }

    if (flowStage === 'requirement') {
      setRequirement(currentInput);
      setFlowStage('identity');

      const botMessage = {
        id: getNextMessageId(),
        text: `Please share your name and email address.`,
        sender: 'bot',
        timestamp: new Date(),
        showIdentityForm: true
      };

      setMessages(prev => [...prev, botMessage]);
      saveToSheet(`Requirement: ${currentInput}`, '', selectedDomain?.name, selectedSubDomain);
      return;
    }

    if (flowStage === 'identity') {
      const botMessage = {
        id: getNextMessageId(),
        text: `Please use the form above to enter your name and email.`,
        sender: 'bot',
        timestamp: new Date()
      };

      setMessages(prev => [...prev, botMessage]);
      return;
    }

    if (flowStage === 'complete') {
      const botMessage = {
        id: getNextMessageId(),
        text: `Great! Feel free to explore more AI tools for different needs. Just click the button below to check another idea! 🚀`,
        sender: 'bot',
        timestamp: new Date(),
        showFinalActions: true
      };

      setMessages(prev => [...prev, botMessage]);
      return;
    }
  };

  const handleKeyPress = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const formatTime = (date) => {
    return date.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
  };

  const formatHistoryTime = (date) => {
    const now = new Date();
    const diff = now - date;
    const hours = Math.floor(diff / (1000 * 60 * 60));
    const days = Math.floor(hours / 24);

    if (hours < 1) return 'Just now';
    if (hours < 24) return `${hours}h ago`;
    if (days === 1) return 'Yesterday';
    if (days < 7) return `${days} days ago`;
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  };

  const handleLoadChat = (chat) => {
    setMessages(chat.messages);
    setShowChatHistory(false);
    setFlowStage('complete');
  };

  return (
    <div className="chatbot-container">
      {/* Header */}
      <header className="chatbot-header">
        <div className="logo-container">
          <img src="/android-chrome-192x192.png" alt="Ikshan" className="logo-img" />
          <h2>Ikshan</h2>
        </div>

        <div className="header-products">
          <div className="products-scroll">
            <div className="product-chip"><ShoppingCart size={14} /> <span>Ecom Listing SEO</span></div>
            <div className="product-chip"><TrendingUp size={14} /> <span>Learn from Competitors</span></div>
            <div className="product-chip"><Users size={14} /> <span>B2B Lead Gen</span></div>
            <div className="product-chip"><Youtube size={14} /> <span>Youtube Helper</span></div>
            <div className="product-chip"><Sparkles size={14} /> <span>AI Team</span></div>
            <div className="product-chip"><FileText size={14} /> <span>Content Creator</span></div>
          </div>
        </div>

        <div className="header-actions">
          <button onClick={() => onNavigate && onNavigate('about')} title="About"><FileText size={20} /></button>
          <button onClick={() => onNavigate && onNavigate('developer')} title="Developer" className="dev-header-btn"><Code size={20} /></button>
          <button onClick={() => setShowChatHistory(true)} title="History"><History size={20} /></button>
          <button onClick={handleStartNewIdea} title="New Chat"><Plus size={20} /></button>
        </div>
      </header>

      {/* Main Content */}
      <div className="chat-window">
        {/* Typeform / Flow Stages */}
        {['outcome', 'domain', 'task'].includes(flowStage) ? (
          <div className="empty-state">
            {flowStage === 'outcome' && (
              <>
                {/* Icon removed */}
                <h1>Professional expertise, on-demand—without the salary or recruiting.</h1>
                <p>Select what matters most to you right now</p>
                <div className="suggestions-grid">
                  {outcomeOptions.map((outcome, index) => (
                    <div
                      key={outcome.id}
                      className="suggestion-card"
                      onClick={() => !outcomeClickProcessing && handleOutcomeClick(outcome)}
                      style={{ animationDelay: `${index * 0.1}s`, animation: 'fadeIn 0.5s ease-out forwards' }}
                    >
                      <h3>{outcome.text}</h3>
                      {outcome.subtext && <p className="goal-subtext">{outcome.subtext}</p>}
                    </div>
                  ))}
                </div>
                <p style={{ marginTop: '3rem', fontSize: '0.8rem', fontStyle: 'italic', color: '#6b7280', opacity: 0.7, textAlign: 'center' }}>"I don't have time or team to figure out AI" - Netizen</p>
              </>
            )}

            {flowStage === 'domain' && (
              <>
                {/* Icon removed */}
                <h1>Which domain best matches your need?</h1>
                <p>Select a domain to see relevant tasks</p>
                <div className="suggestions-grid">
                  {getDomainsForSelection().map((domain, index) => (
                    <div
                      key={index}
                      className="suggestion-card"
                      onClick={() => !domainClickProcessing && handleDomainClickNew(domain)}
                      style={{ animationDelay: `${index * 0.1}s`, animation: 'fadeIn 0.5s ease-out forwards' }}
                    >
                      <h3>{domain}</h3>
                    </div>
                  ))}
                </div>
                <button
                  style={{ marginTop: '2rem', background: 'transparent', border: 'none', color: '#6b7280', cursor: 'pointer' }}
                  onClick={() => { setSelectedGoal(null); setSelectedDomainName(null); setFlowStage('outcome'); }}
                >
                  ← Back
                </button>
              </>
            )}

            {flowStage === 'task' && (
              <>
                {taskClickProcessing ? (
                  <div className="task-loading-state">
                    <div className="thinking-clean">
                      <div className="thinking-clean-spinner" />
                      <p key={thinkingPhraseIndex} className="thinking-clean-text">
                        {THINKING_PHRASES[thinkingPhraseIndex]}
                      </p>
                      <div className="thinking-clean-bar">
                        <div className="thinking-clean-bar-fill" />
                      </div>
                    </div>
                  </div>
                ) : (
                  <>
                    <h1>What task would you like help with?</h1>
                    <div className="suggestions-grid">
                      {getTasksForSelection().map((task, index) => (
                        <div
                          key={index}
                          className="suggestion-card"
                          onClick={() => handleTaskClick(task)}
                          style={{
                            animationDelay: `${index * 0.05}s`,
                            animation: 'fadeIn 0.3s ease-out forwards',
                          }}
                        >
                          <h3>{task}</h3>
                        </div>
                      ))}
                      <div
                        className="suggestion-card"
                        onClick={handleTypeCustomProblem}
                      >
                        <h3>Type my own problem...</h3>
                      </div>
                    </div>
                    <button
                      style={{ marginTop: '2rem', background: 'transparent', border: 'none', color: '#6b7280', cursor: 'pointer' }}
                      onClick={() => { setSelectedDomainName(null); setFlowStage('domain'); }}
                    >
                      ← Back
                    </button>
                  </>
                )}
              </>
            )}

          </div>
        ) : (
          /* Chat Message List */
          <div className="messages-wrapper">
            {messages.map((message) => (
              <div key={message.id} className={`message ${message.sender === 'user' ? 'user' : 'bot'}`}>
                <div className="avatar">
                  {message.sender === 'user' ? <User size={18} /> : <img src="/android-chrome-192x192.png" alt="bot" style={{ width: 18, height: 18, objectFit: 'contain', borderRadius: '2px' }} />}
                </div>
                <div className="message-content">
                  {message.sender === 'bot' ? (
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.text || ''}</ReactMarkdown>
                  ) : (
                    message.text
                  )}

                  {/* Identity Form Injection - Keep simplified logic */}
                  {message.showIdentityForm && (
                    <div className="identity-form" style={{ marginTop: '1rem', position: 'relative', animation: 'none', boxShadow: 'none', padding: '1.5rem', border: '1px solid #e5e7eb' }}>
                      <IdentityForm onSubmit={handleIdentitySubmit} />
                    </div>
                  )}

                  {/* Early Tool Recommendations — styled cards */}
                  {message.isEarlyRecommendation && message.earlyTools && (
                    <div className="early-recs-container" style={{ marginTop: '1rem' }}>
                      <div style={{
                        display: 'flex',
                        flexDirection: 'column',
                        gap: '0.6rem',
                        marginBottom: '1rem',
                      }}>
                        {message.earlyTools.map((tool, i) => (
                          <div
                            key={i}
                            className="early-rec-card"
                            style={{
                              background: 'linear-gradient(135deg, #fafaff 0%, #f5f3ff 100%)',
                              border: '1px solid rgba(124, 58, 237, 0.15)',
                              borderRadius: '12px',
                              padding: '0.875rem 1rem',
                              cursor: tool.url ? 'pointer' : 'default',
                              transition: 'all 0.25s ease',
                              opacity: 0,
                              animation: `fadeIn 0.4s ease-out ${i * 0.1}s forwards`,
                            }}
                            onClick={() => tool.url && window.open(tool.url, '_blank')}
                          >
                            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.4rem' }}>
                              <span style={{ fontSize: '0.9rem', fontWeight: 700, color: 'var(--ikshan-text-primary, #111827)' }}>
                                {tool.name}
                              </span>
                              {tool.rating && (
                                <span style={{
                                  fontSize: '0.72rem',
                                  fontWeight: 600,
                                  color: '#f59e0b',
                                  background: '#fef3c7',
                                  padding: '0.12rem 0.4rem',
                                  borderRadius: '6px',
                                }}>
                                  ⭐ {tool.rating}
                                </span>
                              )}
                            </div>
                            <p style={{
                              fontSize: '0.8rem',
                              color: 'var(--ikshan-text-secondary, #6b7280)',
                              lineHeight: 1.4,
                              margin: '0 0 0.4rem 0',
                            }}>
                              {tool.description}
                            </p>
                            {tool.why_relevant && (
                              <p style={{
                                fontSize: '0.75rem',
                                color: 'var(--ikshan-purple, #7c3aed)',
                                fontWeight: 500,
                                margin: 0,
                                lineHeight: 1.35,
                              }}>
                                {tool.why_relevant}
                              </p>
                            )}
                            {/* Enriched tool context: issue solved, stage, ease */}
                            {(tool.issue_solved || tool.implementation_stage || tool.ease_of_use) && (
                              <div style={{
                                marginTop: '0.45rem',
                                padding: '0.45rem 0.55rem',
                                background: 'rgba(124, 58, 237, 0.04)',
                                borderRadius: '8px',
                                fontSize: '0.72rem',
                                lineHeight: 1.5,
                                color: 'var(--ikshan-text-secondary, #4b5563)',
                              }}>
                                {tool.issue_solved && (
                                  <div style={{ marginBottom: '0.2rem' }}>
                                    <span style={{ fontWeight: 600, color: '#059669' }}>🎯 Solves: </span>
                                    {tool.issue_solved}
                                  </div>
                                )}
                                {tool.implementation_stage && (
                                  <div style={{ marginBottom: '0.2rem' }}>
                                    <span style={{ fontWeight: 600, color: '#3b82f6' }}>📅 When: </span>
                                    {tool.implementation_stage}
                                  </div>
                                )}
                                {tool.ease_of_use && (
                                  <div>
                                    <span style={{ fontWeight: 600, color: '#d97706' }}>⚡ Ease: </span>
                                    {tool.ease_of_use}
                                  </div>
                                )}
                              </div>
                            )}
                          </div>
                        ))}
                      </div>
                      <div style={{
                        padding: '0.65rem 0.875rem',
                        background: 'linear-gradient(90deg, rgba(124, 58, 237, 0.06) 0%, rgba(99, 102, 241, 0.06) 100%)',
                        borderRadius: '10px',
                        borderLeft: '3px solid var(--ikshan-purple, #7c3aed)',
                      }}>
                        <p style={{
                          fontSize: '0.82rem',
                          color: 'var(--ikshan-text-primary, #374151)',
                          margin: 0,
                          lineHeight: 1.45,
                        }}>
                          💡 <strong>Let's scope your problem more narrowly</strong> — a few more questions will help me find the <em>exact</em> tools for your specific situation.
                        </p>
                      </div>
                    </div>
                  )}

                  {/* Business URL Input — shown right after tool recommendations */}
                  {message.showBusinessUrlInput && (flowStage === 'url-input' || message.isError) && (
                    <div className="business-url-input-card" style={{
                      marginTop: '1rem',
                      padding: '1rem',
                      borderRadius: '12px',
                      border: '1px solid rgba(124, 58, 237, 0.2)',
                      background: 'linear-gradient(135deg, #fafaff 0%, #f0eeff 100%)',
                    }}>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem', marginBottom: '0.75rem' }}>
                        <input
                          type="url"
                          placeholder="Paste your website URL (e.g., yourcompany.com)"
                          style={{
                            width: '100%',
                            padding: '0.65rem 0.875rem',
                            borderRadius: '8px',
                            border: '1.5px solid var(--ikshan-border, #d1d5db)',
                            background: 'var(--ikshan-input-bg, #fff)',
                            color: 'var(--ikshan-text-primary, #1a1a1a)',
                            fontSize: '0.9rem',
                            outline: 'none',
                            boxSizing: 'border-box',
                          }}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter' && e.target.value.trim()) {
                              handleBusinessUrlSubmit(e.target.value);
                            }
                          }}
                          id="business-url-input-mobile"
                          autoFocus
                        />
                        <button
                          onClick={() => {
                            const input = document.getElementById('business-url-input-mobile');
                            if (input && input.value.trim()) {
                              handleBusinessUrlSubmit(input.value);
                            }
                          }}
                          style={{
                            width: '100%',
                            padding: '0.65rem 1rem',
                            borderRadius: '8px',
                            border: 'none',
                            background: 'linear-gradient(135deg, #7c3aed 0%, #6366f1 100%)',
                            color: '#fff',
                            fontSize: '0.85rem',
                            fontWeight: 700,
                            cursor: 'pointer',
                          }}
                        >
                          Analyze My Business &rarr;
                        </button>
                      </div>
                      <button
                        onClick={handleSkipBusinessUrl}
                        style={{
                          background: 'none',
                          border: 'none',
                          color: 'var(--ikshan-text-secondary, #9ca3af)',
                          fontSize: '0.78rem',
                          cursor: 'pointer',
                          padding: '0.25rem 0',
                        }}
                      >
                        Skip — we'll give general recommendations
                      </button>
                    </div>
                  )}

                  {/* Scale Questions — all-at-once form */}
                  {message.showScaleForm && flowStage === 'scale-questions' && !scaleFormSubmitted && scaleQuestions.length > 0 && (
                    <div className="scale-form-modern">
                      {scaleQuestions.map((q, qIdx) => (
                        <div key={q.id} className="scale-q-group">
                          <div className="scale-q-label">
                            <span>{q.icon}</span>
                            <span>{q.question}</span>
                            {q.multiSelect && <span className="scale-q-multi-hint">(select multiple)</span>}
                          </div>
                          <div className="scale-q-pills">
                            {q.options.map((opt, oIdx) => {
                              const sel = scaleFormSelections[q.id];
                              const isSelected = q.multiSelect
                                ? Array.isArray(sel) && sel.includes(opt)
                                : sel === opt;
                              return (
                                <button
                                  key={oIdx}
                                  className={`scale-pill ${isSelected ? 'selected' : ''}`}
                                  onClick={() => {
                                    if (q.multiSelect) {
                                      setScaleFormSelections(prev => {
                                        const curr = Array.isArray(prev[q.id]) ? prev[q.id] : [];
                                        return {
                                          ...prev,
                                          [q.id]: curr.includes(opt)
                                            ? curr.filter(v => v !== opt)
                                            : [...curr, opt],
                                        };
                                      });
                                    } else {
                                      setScaleFormSelections(prev => ({ ...prev, [q.id]: opt }));
                                    }
                                  }}
                                >
                                  {opt}
                                </button>
                              );
                            })}
                          </div>
                        </div>
                      ))}
                      <div className="scale-form-submit-row">
                        <button
                          onClick={handleScaleFormSubmit}
                          disabled={!scaleQuestions.every(q => {
                            const sel = scaleFormSelections[q.id];
                            return q.multiSelect
                              ? Array.isArray(sel) && sel.length > 0
                              : !!sel;
                          })}
                          className={`scale-submit-btn ${scaleQuestions.every(q => {
                            const sel = scaleFormSelections[q.id];
                            return q.multiSelect
                              ? Array.isArray(sel) && sel.length > 0
                              : !!sel;
                          }) ? 'ready' : ''}`}
                        >
                          Continue →
                        </button>
                      </div>
                    </div>
                  )}

                  {/* ── Business Intelligence Verdict Card — DISABLED ── */}
                  {false && message.isBusinessIntelVerdict && message.businessIntelData && (
                    <div className="bi-verdict-container">
                      {message.businessIntelData.verdict_line && (
                        <div className="bi-verdict-headline">
                          <span className="bi-verdict-headline-icon">⚡</span>
                          <span className="bi-verdict-headline-text">{message.businessIntelData.verdict_line}</span>
                        </div>
                      )}

                      {message.businessIntelData.icp_snapshot && (
                        <div className="bi-section bi-icp">
                          <div className="bi-section-label">
                            <span className="bi-section-icon">👤</span> Who Your Ideal Customer Is
                          </div>
                          <p className="bi-section-text">{message.businessIntelData.icp_snapshot}</p>
                        </div>
                      )}

                      {message.businessIntelData.seo_health && (
                        <div className="bi-section bi-seo">
                          <div className="bi-section-label">
                            <span className="bi-section-icon">🔍</span> SEO Health
                            <span className={`bi-seo-score ${message.businessIntelData.seo_health.score >= 7 ? 'good' : message.businessIntelData.seo_health.score >= 4 ? 'okay' : 'poor'}`}>
                              {message.businessIntelData.seo_health.score}/10
                            </span>
                          </div>
                          <div className="bi-seo-bar-track">
                            <div className="bi-seo-bar-fill" style={{ width: `${message.businessIntelData.seo_health.score * 10}%` }} />
                          </div>
                          <div className="bi-seo-details">
                            {message.businessIntelData.seo_health.working && (
                              <div className="bi-seo-row">
                                <span className="bi-seo-tag working">✓ Working</span>
                                <span>{message.businessIntelData.seo_health.working}</span>
                              </div>
                            )}
                            {message.businessIntelData.seo_health.missing && (
                              <div className="bi-seo-row">
                                <span className="bi-seo-tag missing">✗ Missing</span>
                                <span>{message.businessIntelData.seo_health.missing}</span>
                              </div>
                            )}
                            {message.businessIntelData.seo_health.quick_win && (
                              <div className="bi-seo-row">
                                <span className="bi-seo-tag quickwin">⚡ Quick Win</span>
                                <span>{message.businessIntelData.seo_health.quick_win}</span>
                              </div>
                            )}
                          </div>
                        </div>
                      )}

                      {[
                        { key: 'top_funnel', label: 'Top Funnel — Awareness', icon: '📢', color: '#8b5cf6' },
                        { key: 'mid_funnel', label: 'Mid Funnel — Trust', icon: '🤝', color: '#f59e0b' },
                        { key: 'bottom_funnel', label: 'Bottom Funnel — Revenue', icon: '💰', color: '#10b981' },
                      ].map(funnel => (
                        message.businessIntelData[funnel.key] && message.businessIntelData[funnel.key].length > 0 && (
                          <details key={funnel.key} className="bi-funnel-section">
                            <summary className="bi-funnel-header" style={{ '--funnel-color': funnel.color }}>
                              <span className="bi-funnel-icon">{funnel.icon}</span>
                              <span className="bi-funnel-label">{funnel.label}</span>
                              <span className="bi-funnel-count">{message.businessIntelData[funnel.key].length}</span>
                            </summary>
                            <div className="bi-funnel-strategies">
                              {message.businessIntelData[funnel.key].map((s, i) => (
                                <div key={i} className="bi-strategy-item">
                                  <div className="bi-strategy-name">
                                    <span className="bi-strategy-num" style={{ background: funnel.color }}>{i + 1}</span>
                                    {s.strategy}
                                  </div>
                                  <div className="bi-strategy-action">{s.action}</div>
                                </div>
                              ))}
                            </div>
                          </details>
                        )
                      ))}
                    </div>
                  )}

                  {/* ── AI Playbook — Gap Questions with Options ── */}
                  {message.isPlaybookGapQuestions && (
                    <div className="playbook-gap-container" style={{
                      background: 'linear-gradient(135deg, #faf5ff 0%, #f0f9ff 100%)',
                      border: '1px solid rgba(139, 92, 246, 0.25)',
                      borderRadius: '14px',
                      padding: '1.25rem',
                      marginTop: '0.75rem',
                    }}>
                      <div style={{ fontSize: '0.9rem', fontWeight: 600, color: '#7c3aed', marginBottom: '0.75rem' }}>
                        📋 A few more details needed
                      </div>

                      {message.gapQuestionsParsed && message.gapQuestionsParsed.length > 0 ? (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                          {message.gapQuestionsParsed.map((gq) => (
                            <div key={gq.id} style={{
                              background: 'rgba(255,255,255,0.7)',
                              borderRadius: '10px',
                              padding: '0.85rem',
                              border: '1px solid rgba(139, 92, 246, 0.12)',
                            }}>
                              <div style={{ fontSize: '0.82rem', fontWeight: 600, color: '#374151', marginBottom: '0.5rem' }}>
                                {gq.id} — {gq.label}
                              </div>
                              <div style={{ fontSize: '0.78rem', color: '#6b7280', marginBottom: '0.5rem', lineHeight: 1.5 }}>
                                {gq.question}
                              </div>
                              {playbookStage === 'gap-questions' && gq.options && gq.options.length > 0 && (
                                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.3rem' }}>
                                  {gq.options.map((opt, oi) => {
                                    const isSelected = playbookGapSelections[gq.id] === opt;
                                    return (
                                      <button
                                        key={oi}
                                        onClick={() => setPlaybookGapSelections(prev => ({ ...prev, [gq.id]: opt }))}
                                        style={{
                                          padding: '0.5rem 0.75rem',
                                          borderRadius: '8px',
                                          border: isSelected ? '2px solid #7c3aed' : '1px solid rgba(139, 92, 246, 0.2)',
                                          background: isSelected ? 'rgba(124, 58, 237, 0.08)' : '#fff',
                                          color: isSelected ? '#7c3aed' : '#374151',
                                          fontWeight: isSelected ? 600 : 400,
                                          fontSize: '0.8rem',
                                          cursor: 'pointer',
                                          textAlign: 'left',
                                          transition: 'all 0.15s ease',
                                        }}
                                      >
                                        {opt}
                                      </button>
                                    );
                                  })}
                                </div>
                              )}
                              {playbookStage !== 'gap-questions' && playbookGapSelections[gq.id] && (
                                <div style={{ fontSize: '0.8rem', color: '#7c3aed', fontWeight: 500, marginTop: '0.3rem' }}>
                                  ✓ {playbookGapSelections[gq.id]}
                                </div>
                              )}
                            </div>
                          ))}

                          {playbookStage === 'gap-questions' && (
                            <button
                              onClick={handlePlaybookGapSubmit}
                              disabled={
                                !message.gapQuestionsParsed.every(gq => playbookGapSelections[gq.id])
                              }
                              style={{
                                padding: '0.65rem 1.25rem',
                                borderRadius: '10px',
                                border: 'none',
                                background: message.gapQuestionsParsed.every(gq => playbookGapSelections[gq.id])
                                  ? '#7c3aed' : '#d1d5db',
                                color: '#fff',
                                fontWeight: 600,
                                fontSize: '0.85rem',
                                cursor: message.gapQuestionsParsed.every(gq => playbookGapSelections[gq.id])
                                  ? 'pointer' : 'not-allowed',
                                alignSelf: 'flex-end',
                                transition: 'background 0.2s',
                              }}
                            >
                              Submit Answers →
                            </button>
                          )}
                        </div>
                      ) : (
                        <>
                          <div style={{ fontSize: '0.82rem', color: '#374151', whiteSpace: 'pre-wrap', lineHeight: 1.6, marginBottom: '1rem' }}>
                            {message.gapQuestionsText}
                          </div>
                          {playbookStage === 'gap-questions' && (
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                              <textarea
                                value={playbookGapAnswer}
                                onChange={(e) => setPlaybookGapAnswer(e.target.value)}
                                placeholder="Type your answers here..."
                                rows={3}
                                style={{
                                  width: '100%',
                                  padding: '0.75rem',
                                  borderRadius: '10px',
                                  border: '1px solid rgba(139, 92, 246, 0.3)',
                                  fontSize: '0.85rem',
                                  resize: 'vertical',
                                  fontFamily: 'inherit',
                                  boxSizing: 'border-box',
                                }}
                              />
                              <button
                                onClick={() => {
                                  if (playbookGapAnswer.trim()) handlePlaybookGapSubmit();
                                }}
                                disabled={!playbookGapAnswer.trim()}
                                style={{
                                  padding: '0.65rem 1rem',
                                  borderRadius: '10px',
                                  border: 'none',
                                  background: playbookGapAnswer.trim() ? '#7c3aed' : '#d1d5db',
                                  color: '#fff',
                                  fontWeight: 600,
                                  cursor: playbookGapAnswer.trim() ? 'pointer' : 'not-allowed',
                                  alignSelf: 'flex-end',
                                }}
                              >
                                Submit →
                              </button>
                            </div>
                          )}
                        </>
                      )}
                    </div>
                  )}

                  {/* Website Snapshot — shown while playbook generates */}
                  {message.isWebsiteSnapshot && message.snapshotData && (() => {
                    const snap = message.snapshotData;
                    const seo = snap.seo_health || {};
                    const seoScore = [seo.has_meta, seo.has_viewport, seo.has_sitemap].filter(Boolean).length;
                    const socialIcons: Record<string, string> = {
                      'instagram.com': '📸', 'facebook.com': '👥', 'twitter.com': '🐦',
                      'x.com': '🐦', 'linkedin.com': '💼', 'youtube.com': '▶️',
                      'tiktok.com': '🎵', 'pinterest.com': '📌', 'threads.net': '🧵',
                    };

                    // Derive strengths
                    const strengths: string[] = [];
                    if (seoScore === 3) strengths.push('SEO foundations solid — meta, mobile, sitemap all set');
                    else if (seoScore === 2) strengths.push('Basic SEO set up — missing ' + (!seo.has_meta ? 'meta tags' : !seo.has_viewport ? 'mobile viewport' : 'sitemap'));
                    if (snap.social_links && snap.social_links.length >= 3) strengths.push(`Active on ${snap.social_links.length} social platforms`);
                    else if (snap.social_links && snap.social_links.length > 0) strengths.push(`Present on ${snap.social_links.length} social platform${snap.social_links.length > 1 ? 's' : ''}`);
                    if (snap.cta_patterns && snap.cta_patterns.length >= 2) strengths.push(`${snap.cta_patterns.length} conversion points — actively capturing leads`);
                    if (snap.tech_stack && snap.tech_stack.some((t: string) => /analytics|segment|mixpanel|hotjar/i.test(t))) strengths.push('Tracking & analytics detected');
                    if (snap.js_rendered) strengths.push('Modern JS-rendered app');
                    if (snap.page_types && snap.page_types.includes('blog')) strengths.push('Blog content — organic traffic opportunity');

                    // Derive gaps
                    const gaps: string[] = [];
                    const pageTypes = snap.page_types || [];
                    const criticalPages = [
                      { type: 'pricing', label: 'No pricing page — can\'t self-qualify' },
                      { type: 'case_studies', label: 'No case studies — no social proof' },
                      { type: 'faq', label: 'No FAQ — unanswered objections' },
                    ];
                    for (const cp of criticalPages) {
                      if (!pageTypes.includes(cp.type)) gaps.push(cp.label);
                    }
                    if (seoScore < 2) gaps.push('SEO basics weak — poor indexing');
                    if (!snap.social_links || snap.social_links.length === 0) gaps.push('No social links found');
                    if (!snap.cta_patterns || snap.cta_patterns.length === 0) gaps.push('No clear CTAs — no next step for visitors');
                    else if (snap.cta_patterns.length <= 1) gaps.push('Only 1 CTA — weak conversion path');

                    // Conversion funnel analysis
                    const ctaTypes: string[] = [];
                    const ctaList = (snap.cta_patterns || []).map((c: string) => c.toLowerCase());
                    if (ctaList.some((c: string) => /demo|call|schedule|book|consult/i.test(c))) ctaTypes.push('High-touch sales');
                    if (ctaList.some((c: string) => /free|trial|start|signup|sign up|get started/i.test(c))) ctaTypes.push('Self-serve');
                    if (ctaList.some((c: string) => /contact|submit|enquir|inquiry/i.test(c))) ctaTypes.push('Contact forms');

                    return (
                      <div style={{
                        marginTop: '0.75rem',
                        borderRadius: '14px',
                        border: '1px solid rgba(124, 58, 237, 0.18)',
                        background: 'linear-gradient(145deg, #faf5ff 0%, #f5f3ff 60%, #ede9fe 100%)',
                        boxShadow: '0 3px 16px rgba(124, 58, 237, 0.1)',
                        overflow: 'hidden',
                      }}>
                        {/* Header */}
                        <div style={{
                          padding: '0.7rem 0.9rem',
                          background: 'linear-gradient(135deg, #7c3aed 0%, #6d28d9 100%)',
                          display: 'flex', alignItems: 'center', gap: '0.5rem',
                        }}>
                          <span style={{ fontSize: '0.9rem' }}>🌐</span>
                          <span style={{ fontWeight: 700, fontSize: '0.82rem', color: '#fff' }}>Website Intelligence</span>
                          <div style={{ marginLeft: 'auto', display: 'flex', gap: '0.3rem' }}>
                            {snap.js_rendered && (
                              <span style={{ fontSize: '0.6rem', background: 'rgba(255,255,255,0.2)', color: '#fff', padding: '2px 6px', borderRadius: '8px' }}>⚡ JS</span>
                            )}
                            <span style={{ fontSize: '0.6rem', background: 'rgba(255,255,255,0.2)', color: '#fff', padding: '2px 6px', borderRadius: '8px' }}>{snap.pages_found} pages</span>
                          </div>
                        </div>

                        <div style={{ padding: '0.75rem 0.85rem', display: 'flex', flexDirection: 'column', gap: '0.6rem' }}>

                          {/* Business Identity */}
                          {snap.homepage_title && (
                            <div style={{ padding: '0.6rem 0.7rem', background: 'rgba(255,255,255,0.75)', borderRadius: '8px', border: '1px solid rgba(124,58,237,0.1)' }}>
                              <div style={{ fontSize: '0.78rem', fontWeight: 700, color: '#1e1b4b' }}>{snap.homepage_title}</div>
                              {snap.homepage_h1s && snap.homepage_h1s.length > 0 && (
                                <div style={{ fontSize: '0.7rem', color: '#5b21b6', fontStyle: 'italic', marginTop: '0.1rem' }}>"{snap.homepage_h1s[0]}"</div>
                              )}
                              {snap.homepage_description && (
                                <div style={{ fontSize: '0.66rem', color: '#6b7280', marginTop: '0.15rem', lineHeight: 1.4 }}>{snap.homepage_description.slice(0, 120)}{snap.homepage_description.length > 120 ? '…' : ''}</div>
                              )}
                            </div>
                          )}

                          {/* What's Working + Gaps */}
                          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.45rem' }}>
                            {strengths.length > 0 && (
                              <div style={{ padding: '0.55rem 0.65rem', background: 'rgba(16,185,129,0.06)', borderRadius: '8px', border: '1px solid rgba(16,185,129,0.2)' }}>
                                <div style={{ fontSize: '0.62rem', fontWeight: 700, color: '#059669', textTransform: 'uppercase', letterSpacing: '.04em', marginBottom: '0.3rem' }}>What's Working</div>
                                {strengths.slice(0, 3).map((s, i) => (
                                  <div key={i} style={{ fontSize: '0.66rem', color: '#374151', display: 'flex', gap: '0.3rem', lineHeight: 1.4, marginBottom: '0.2rem' }}>
                                    <span style={{ color: '#10b981', flexShrink: 0 }}>✓</span><span>{s}</span>
                                  </div>
                                ))}
                              </div>
                            )}
                            {gaps.length > 0 && (
                              <div style={{ padding: '0.55rem 0.65rem', background: 'rgba(239,68,68,0.04)', borderRadius: '8px', border: '1px solid rgba(239,68,68,0.18)' }}>
                                <div style={{ fontSize: '0.62rem', fontWeight: 700, color: '#dc2626', textTransform: 'uppercase', letterSpacing: '.04em', marginBottom: '0.3rem' }}>Gaps Found</div>
                                {gaps.slice(0, 3).map((g, i) => (
                                  <div key={i} style={{ fontSize: '0.66rem', color: '#374151', display: 'flex', gap: '0.3rem', lineHeight: 1.4, marginBottom: '0.2rem' }}>
                                    <span style={{ color: '#ef4444', flexShrink: 0 }}>✗</span><span>{g}</span>
                                  </div>
                                ))}
                              </div>
                            )}
                          </div>

                          {/* CTAs + Tech Stack */}
                          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.45rem' }}>
                            {snap.cta_patterns && snap.cta_patterns.length > 0 && (
                              <div style={{ padding: '0.55rem 0.65rem', background: 'rgba(255,255,255,0.65)', borderRadius: '8px', border: '1px solid rgba(124,58,237,0.1)' }}>
                                <div style={{ fontSize: '0.62rem', fontWeight: 700, color: '#6d28d9', textTransform: 'uppercase', letterSpacing: '.04em', marginBottom: '0.25rem' }}>🎯 Conversion Points</div>
                                {snap.cta_patterns.slice(0, 3).map((cta: string, i: number) => (
                                  <div key={i} style={{ fontSize: '0.64rem', color: '#374151', background: 'rgba(124,58,237,0.06)', padding: '1px 5px', borderRadius: '4px', marginBottom: '0.15rem', display: 'inline-block', marginRight: '0.2rem' }}>"{cta}"</div>
                                ))}
                                {ctaTypes.length > 0 && (
                                  <div style={{ fontSize: '0.6rem', color: '#7c3aed', fontWeight: 600, marginTop: '0.25rem' }}>{ctaTypes.join(' · ')}</div>
                                )}
                              </div>
                            )}
                            {snap.tech_stack && snap.tech_stack.length > 0 && (
                              <div style={{ padding: '0.55rem 0.65rem', background: 'rgba(255,255,255,0.65)', borderRadius: '8px', border: '1px solid rgba(124,58,237,0.1)' }}>
                                <div style={{ fontSize: '0.62rem', fontWeight: 700, color: '#6d28d9', textTransform: 'uppercase', letterSpacing: '.04em', marginBottom: '0.25rem' }}>⚙️ Tech Stack</div>
                                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.2rem' }}>
                                  {snap.tech_stack.map((tech: string, i: number) => (
                                    <span key={i} style={{ fontSize: '0.64rem', padding: '1px 6px', borderRadius: '4px', background: 'rgba(109,40,217,0.08)', color: '#5b21b6', fontWeight: 500 }}>{tech}</span>
                                  ))}
                                </div>
                              </div>
                            )}
                          </div>

                          {/* SEO + Social — compact row */}
                          <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap', alignItems: 'center', padding: '0.45rem 0.6rem', background: 'rgba(255,255,255,0.5)', borderRadius: '7px', border: '1px solid rgba(124,58,237,0.08)' }}>
                            <span style={{ fontSize: '0.66rem', fontWeight: 700, color: seoScore === 3 ? '#10b981' : seoScore >= 2 ? '#f59e0b' : '#ef4444' }}>
                              SEO {seoScore}/3
                            </span>
                            <span style={{ fontSize: '0.55rem', color: '#d1d5db' }}>|</span>
                            {seo.has_meta && <span style={{ fontSize: '0.62rem', color: '#6b7280' }}>✅ Meta</span>}
                            {seo.has_viewport && <span style={{ fontSize: '0.62rem', color: '#6b7280' }}>✅ Mobile</span>}
                            {seo.has_sitemap && <span style={{ fontSize: '0.62rem', color: '#6b7280' }}>✅ Sitemap</span>}
                            {!seo.has_meta && <span style={{ fontSize: '0.62rem', color: '#ef4444' }}>❌ Meta</span>}
                            {!seo.has_viewport && <span style={{ fontSize: '0.62rem', color: '#ef4444' }}>❌ Mobile</span>}
                            {!seo.has_sitemap && <span style={{ fontSize: '0.62rem', color: '#ef4444' }}>❌ Sitemap</span>}
                            {snap.social_links && snap.social_links.length > 0 && (
                              <>
                                <span style={{ fontSize: '0.55rem', color: '#d1d5db' }}>|</span>
                                {snap.social_links.slice(0, 4).map((link: string, i: number) => {
                                  const domain = Object.keys(socialIcons).find(d => link.includes(d));
                                  return <span key={i} style={{ fontSize: '0.72rem' }}>{domain ? socialIcons[domain] : '🔗'}</span>;
                                })}
                              </>
                            )}
                          </div>

                          {/* AI Observations */}
                          {snap.crawl_summary_points && snap.crawl_summary_points.length > 0 && (
                            <div style={{ padding: '0.55rem 0.65rem', background: 'rgba(109,40,217,0.05)', borderRadius: '8px', border: '1px solid rgba(109,40,217,0.12)' }}>
                              <div style={{ fontSize: '0.62rem', fontWeight: 700, color: '#6d28d9', textTransform: 'uppercase', letterSpacing: '.04em', marginBottom: '0.3rem' }}>🧠 AI Observations</div>
                              {snap.crawl_summary_points.map((pt: string, i: number) => (
                                <div key={i} style={{ fontSize: '0.68rem', color: '#374151', display: 'flex', gap: '0.35rem', lineHeight: 1.4, marginBottom: '0.15rem' }}>
                                  <span style={{ color: '#7c3aed', flexShrink: 0 }}>▸</span><span>{pt}</span>
                                </div>
                              ))}
                            </div>
                          )}

                          {/* Generating Footer */}
                          <div style={{
                            display: 'flex', alignItems: 'center', gap: '0.4rem',
                            padding: '0.5rem 0.65rem',
                            background: 'linear-gradient(135deg, rgba(124,58,237,0.08) 0%, rgba(109,40,217,0.12) 100%)',
                            borderRadius: '7px', border: '1px solid rgba(124,58,237,0.15)',
                          }}>
                            <span style={{ fontSize: '0.75rem' }}>⚙️</span>
                            <span style={{ fontSize: '0.68rem', color: '#5b21b6', fontWeight: 500 }}>Building your 10-step AI Growth Playbook using these insights…</span>
                          </div>

                        </div>
                      </div>
                    );
                  })()}

                  {/* ── AI Playbook Result ── */}
                  {message.isPlaybook && message.playbookData && (
                    <div className="playbook-container" style={{ marginTop: '0.75rem' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', marginBottom: '0.75rem' }}>
                        <span style={{ fontSize: '0.62rem', fontWeight: 700, color: '#7c3aed', letterSpacing: '0.08em', textTransform: 'uppercase' }}>✨ AI Growth Playbook</span>
                      </div>
                      <PlaybookPhaseContainer playbookData={message.playbookData} />
                    </div>
                  )}

                  {/* Crawl Summary — compressed 5-point business snapshot */}
                  {message.showCrawlDetails && !message.isPlaybook && message.crawlSummaryPoints && message.crawlSummaryPoints.length > 0 && (
                    <div className="crawl-summary-card" style={{
                      marginTop: '0.75rem',
                      padding: '0.85rem 1rem',
                      borderRadius: '12px',
                      border: '1px solid rgba(16, 185, 129, 0.25)',
                      background: 'linear-gradient(135deg, #f0fdf4 0%, #ecfdf5 100%)',
                      boxShadow: '0 2px 8px rgba(16, 185, 129, 0.08)',
                    }}>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
                        {message.crawlSummaryPoints.map((point, i) => (
                          <div key={i} style={{
                            display: 'flex',
                            alignItems: 'flex-start',
                            gap: '0.4rem',
                            fontSize: '0.82rem',
                            color: 'var(--ikshan-text-primary, #1a1a1a)',
                            lineHeight: '1.4',
                          }}>
                            <span style={{ color: '#10b981', fontWeight: 700, flexShrink: 0 }}>✓</span>
                            <span>{point}</span>
                          </div>
                        ))}
                      </div>
                      <details style={{ marginTop: '0.65rem' }}>
                        <summary style={{
                          fontSize: '0.75rem',
                          color: 'var(--ikshan-text-secondary, #6b7280)',
                          cursor: 'pointer',
                          userSelect: 'none',
                          fontWeight: 500,
                        }}>
                          View full analysis details
                        </summary>
                        <div style={{
                          marginTop: '0.4rem',
                          padding: '0.6rem',
                          fontSize: '0.75rem',
                          color: 'var(--ikshan-text-secondary, #6b7280)',
                          background: 'rgba(255,255,255,0.6)',
                          borderRadius: '8px',
                          lineHeight: '1.5',
                        }}>
                          This analysis was generated from a live crawl of your website. It captures your business positioning, target audience signals, technology stack, content strengths, and key opportunities. These insights are factored into your personalized tool recommendations.
                        </div>
                      </details>
                    </div>
                  )}

                  {/* Diagnostic Section Options — in-chat */}
                  {message.diagnosticOptions && message.diagnosticOptions.length > 0 && (
                    <div className="diagnostic-options" style={{ marginTop: '1rem' }}>
                      {/* Precision questions */}
                      {message.isPrecisionQuestion ? (
                        message.precisionIndex === currentPrecisionQIndex && flowStage === 'precision-questions' ? (
                          <>
                            {message.diagnosticOptions.map((opt, i) => (
                              <button
                                key={i}
                                className="diagnostic-option-btn"
                                onClick={() => !isTyping && handlePrecisionAnswer(opt)}
                                disabled={isTyping}
                                style={{
                                  animationDelay: `${i * 0.04}s`,
                                  opacity: isTyping ? 0.5 : undefined,
                                  pointerEvents: isTyping ? 'none' : undefined,
                                }}
                              >
                                {opt}
                              </button>
                            ))}
                            {message.allowsFreeText && (
                              <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.5rem' }}>
                                <input
                                  type="text"
                                  value={dynamicFreeText}
                                  onChange={(e) => setDynamicFreeText(e.target.value)}
                                  onKeyPress={(e) => {
                                    if (e.key === 'Enter' && dynamicFreeText.trim()) {
                                      handlePrecisionAnswer(dynamicFreeText.trim());
                                      setDynamicFreeText('');
                                    }
                                  }}
                                  placeholder="Or describe your own..."
                                  className="diagnostic-free-input"
                                />
                                <button
                                  onClick={() => { if (dynamicFreeText.trim()) { handlePrecisionAnswer(dynamicFreeText.trim()); setDynamicFreeText(''); } }}
                                  disabled={!dynamicFreeText.trim()}
                                  className="diagnostic-free-submit"
                                >
                                  &rarr;
                                </button>
                              </div>
                            )}
                          </>
                        ) : (
                          <p style={{ color: 'var(--ikshan-text-secondary, #6b7280)', fontSize: '0.85rem', fontStyle: 'italic', marginTop: '0.5rem' }}>
                            &#10003; Answered
                          </p>
                        )
                      ) : (
                      /* Regular diagnostic questions */
                      message.sectionIndex === currentDynamicQIndex ? (
                        <>
                          {message.diagnosticOptions.map((opt, i) => (
                            <button
                              key={i}
                              className="diagnostic-option-btn"
                              onClick={() => !isTyping && !answerProcessing && handleDynamicAnswer(opt)}
                              disabled={isTyping || answerProcessing}
                              style={{
                                animationDelay: `${i * 0.04}s`,
                                opacity: isTyping ? 0.5 : undefined,
                                pointerEvents: isTyping ? 'none' : undefined,
                              }}
                            >
                              {opt}
                            </button>
                          ))}
                          {message.allowsFreeText && (
                            <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.5rem' }}>
                              <input
                                type="text"
                                value={dynamicFreeText}
                                onChange={(e) => setDynamicFreeText(e.target.value)}
                                onKeyPress={(e) => {
                                  if (e.key === 'Enter' && dynamicFreeText.trim()) {
                                    handleDynamicFreeTextSubmit();
                                  }
                                }}
                                placeholder="Or describe your own..."
                                className="diagnostic-free-input"
                              />
                              <button
                                onClick={handleDynamicFreeTextSubmit}
                                disabled={!dynamicFreeText.trim()}
                                className="diagnostic-free-submit"
                              >
                                &rarr;
                              </button>
                            </div>
                          )}
                        </>
                      ) : (
                        <p style={{ color: 'var(--ikshan-text-secondary, #6b7280)', fontSize: '0.85rem', fontStyle: 'italic', marginTop: '0.5rem' }}>
                          &#10003; Answered
                        </p>
                      )
                      )}
                    </div>
                  )}

                  {/* Website URL Input — in-chat */}
                  {message.showWebsiteInput && flowStage === 'website-input' && (
                    <div className="website-input-card" style={{
                      marginTop: '1rem',
                      padding: '0.875rem',
                      borderRadius: '12px',
                      border: '1px solid var(--ikshan-border, #e5e7eb)',
                      background: 'var(--ikshan-card-bg, #f9fafb)',
                    }}>
                      <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '0.75rem' }}>
                        <input
                          type="url"
                          placeholder="https://yourbusiness.com"
                          style={{
                            flex: 1,
                            padding: '0.5rem 0.75rem',
                            borderRadius: '8px',
                            border: '1px solid var(--ikshan-border, #d1d5db)',
                            background: 'var(--ikshan-input-bg, #fff)',
                            color: 'var(--ikshan-text-primary, #1a1a1a)',
                            fontSize: '0.85rem',
                            outline: 'none',
                          }}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter' && e.target.value.trim()) {
                              handleWebsiteSubmit(e.target.value);
                            }
                          }}
                          id="website-url-input-mobile"
                        />
                        <button
                          onClick={() => {
                            const input = document.getElementById('website-url-input-mobile');
                            if (input && input.value.trim()) {
                              handleWebsiteSubmit(input.value);
                            }
                          }}
                          style={{
                            padding: '0.5rem 0.875rem',
                            borderRadius: '8px',
                            border: 'none',
                            background: 'var(--ikshan-accent, #6366f1)',
                            color: '#fff',
                            fontSize: '0.8rem',
                            fontWeight: 600,
                            cursor: 'pointer',
                          }}
                        >
                          Analyze
                        </button>
                      </div>
                      <button
                        onClick={handleSkipWebsite}
                        style={{
                          background: 'none',
                          border: 'none',
                          color: 'var(--ikshan-text-secondary, #6b7280)',
                          fontSize: '0.75rem',
                          cursor: 'pointer',
                          textDecoration: 'underline',
                          padding: '0.25rem 0',
                        }}
                      >
                        Skip — take me to my recommendations
                      </button>
                    </div>
                  )}

                  {/* Google Auth Gate — in-chat */}
                  {message.showAuthGate && (
                    <div className="auth-gate-card">
                      {userEmail ? (
                        <div className="auth-gate-signed-in">
                          <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><circle cx="8" cy="8" r="8" fill="#10b981"/><path d="M5 8.5l2 2 4-4" stroke="#fff" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>
                          <span>Signed in as <strong>{userName}</strong></span>
                        </div>
                      ) : (
                        <>
                          <button onClick={handleGoogleSignIn} className="auth-gate-google-btn">
                            <svg width="18" height="18" viewBox="0 0 48 48"><path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/><path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/><path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/><path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/></svg>
                            Sign in with Google
                          </button>
                          <button
                            onClick={handleSkipAuth}
                            style={{ background: 'none', border: 'none', color: 'var(--ikshan-text-secondary, #6b7280)', fontSize: '0.8rem', cursor: 'pointer', marginTop: '0.5rem', textDecoration: 'underline', width: '100%', textAlign: 'center', padding: '0.25rem' }}
                          >
                            Skip for now → generate without saving
                          </button>
                        </>
                      )}
                    </div>
                  )}

                  {/* Actions */}
                  {message.showFinalActions && (
                    <div style={{ marginTop: '1.5rem' }}>
                      {/* Action Buttons Row */}
                      <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap', marginBottom: '1.5rem' }}>
                        <button
                          onClick={handleStartNewIdea}
                          className="action-btn primary"
                        >
                          <Sparkles size={16} /> Check Another Idea
                        </button>
                        {message.companies && message.companies.length > 0 && (
                          <button
                            onClick={() => handleLearnImplementation(message.companies, message.userRequirement)}
                            className="action-btn secondary"
                          >
                            Learn Implementation
                          </button>
                        )}
                      </div>

                      {/* Payment Card — Unlock RCA */}
                      {selectedCategory && !paymentVerified && (
                        <div className="payment-card">
                          <div className="payment-card-badge">
                            <Lock size={12} /> Premium
                          </div>
                          <div className="payment-card-content">
                            <div className="payment-card-left">
                              <h3 className="payment-card-title">
                                <Brain size={20} /> Unlock Root Cause Analysis
                              </h3>
                              <p className="payment-card-desc">
                                Get a deep, structured diagnosis with AI-powered root cause analysis and corrective action plan.
                              </p>
                              <ul className="payment-card-features">
                                <li><Shield size={14} /> Problem Definition</li>
                                <li><BarChart3 size={14} /> Data Collection</li>
                                <li><Brain size={14} /> Root Cause Summary</li>
                                <li><TrendingUp size={14} /> Action Plan</li>
                              </ul>
                            </div>
                            <div className="payment-card-right">
                              <div className="payment-card-price">
                                <span className="payment-price-currency">₹</span>
                                <span className="payment-price-amount">499</span>
                                <span className="payment-price-period">one-time</span>
                              </div>
                              <button
                                onClick={handlePayForRCA}
                                disabled={paymentLoading}
                                className="payment-card-btn"
                              >
                                {paymentLoading ? (
                                  <>Processing...</>
                                ) : (
                                  <><CreditCard size={16} /> Pay ₹499 &amp; Unlock</>
                                )}
                              </button>
                              <p className="payment-card-secure">
                                <Shield size={12} /> Secured by JusPay
                              </p>
                            </div>
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>
            ))}

            {isTyping && (
              <div className="message bot">
                <div className="avatar"><img src="/android-chrome-192x192.png" alt="bot" style={{ width: 18, height: 18, objectFit: 'contain', borderRadius: '2px' }} /></div>
                <div className="message-content">
                  {taskClickProcessing ? (
                    <div className="thinking-clean" style={{ padding: '0.5rem 0.75rem' }}>
                      <div className="thinking-clean-spinner" style={{ width: 18, height: 18 }} />
                      <p key={thinkingPhraseIndex} className="thinking-clean-text" style={{ fontSize: '0.8rem' }}>
                        {THINKING_PHRASES[thinkingPhraseIndex]}
                      </p>
                    </div>
                  ) : (
                    <div className="typing-indicator" style={{ marginLeft: 0, padding: 0, boxShadow: 'none', background: 'transparent' }}>
                      <div className="typing-dot"></div>
                      <div className="typing-dot"></div>
                      <div className="typing-dot"></div>
                    </div>
                  )}
                </div>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>
        )}
      </div>

      {/* Input Area */}
      {!['outcome', 'domain', 'task', 'rca'].includes(flowStage) && (
        <div className="input-area">
          {speechError && <div style={{ position: 'absolute', top: '-40px', background: '#fee2e2', color: '#b91c1c', padding: '0.5rem 1rem', borderRadius: '8px', fontSize: '0.9rem' }}>{speechError}</div>}
          <div className="input-container">
            <textarea
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              onKeyPress={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  handleSend();
                }
              }}
              placeholder={isRecording ? "Listening..." : "Message Ikshan..."}
              rows={1}
            />
            <button
              onClick={() => {
                voiceSupported ? toggleVoiceRecording() : handleSend();
              }}
              title={isRecording ? "Stop" : "Send"}
            >
              {isRecording ? <MicOff size={20} /> : (inputValue.trim() ? <Send size={20} /> : <Mic size={20} />)}
            </button>
          </div>
        </div>
      )}

      {showChatHistory && (
        <div className="identity-overlay" onClick={() => setShowChatHistory(false)}>
          <div className="identity-form" onClick={(e) => e.stopPropagation()}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem' }}>
              <h2>Chat History</h2>
              <button onClick={() => setShowChatHistory(false)} style={{ background: 'transparent', color: '#6b7280', width: 'auto', padding: 0 }}><X size={24} /></button>
            </div>
            <div className="chat-history-list" style={{ maxHeight: '300px', overflowY: 'auto', textAlign: 'left' }}>
              {chatHistory.length === 0 ? <p style={{ color: '#6b7280' }}>No history yet</p> :
                chatHistory.map((chat) => (
                  <div
                    key={chat.id}
                    onClick={() => handleLoadChat(chat)}
                    style={{ padding: '1rem', borderBottom: '1px solid #f3f4f6', cursor: 'pointer' }}
                  >
                    <div style={{ fontWeight: 500, marginBottom: '0.25rem' }}>{chat.title}</div>
                    <div style={{ fontSize: '0.8rem', color: '#6b7280' }}>{formatHistoryTime(chat.timestamp)}</div>
                  </div>
                ))
              }
            </div>
          </div>
        </div>
      )}

      {/* Auth Modal — Google + OTP */}
      {showAuthModal && (
        <div className="identity-overlay" onClick={() => { setShowAuthModal(false); setOtpStep('phone'); setOtpError(''); }}>
          <div className="identity-form" onClick={(e) => e.stopPropagation()} style={{ maxWidth: '360px', padding: '1.5rem' }}>
            <h2 style={{ marginBottom: '0.5rem', fontSize: '1.1rem' }}>Verify to Continue</h2>
            <p style={{ marginBottom: '1.25rem', color: '#6b7280', fontSize: '0.85rem' }}>Sign in with Google or verify your phone</p>

            <button onClick={handleGoogleSignIn} style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '10px', background: 'white', border: '1px solid #d1d5db', color: '#374151', width: '100%', padding: '0.7rem', borderRadius: '8px', cursor: 'pointer', fontSize: '0.9rem', marginBottom: '1rem' }}>
              <span style={{ fontWeight: 600 }}>Continue with Google</span>
            </button>

            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '1rem' }}>
              <div style={{ flex: 1, height: '1px', background: '#e5e7eb' }} />
              <span style={{ color: '#9ca3af', fontSize: '0.75rem' }}>OR</span>
              <div style={{ flex: 1, height: '1px', background: '#e5e7eb' }} />
            </div>

            {otpStep === 'phone' ? (
              <div>
                <label style={{ display: 'block', marginBottom: '0.4rem', fontWeight: 500, fontSize: '0.85rem', color: '#374151' }}>Mobile Number</label>
                <div style={{ display: 'flex', gap: '0.4rem' }}>
                  <span style={{ display: 'flex', alignItems: 'center', padding: '0 0.4rem', background: '#f3f4f6', borderRadius: '8px', fontSize: '0.85rem', color: '#6b7280', border: '1px solid #d1d5db' }}>+91</span>
                  <input
                    type="tel"
                    value={otpPhone}
                    onChange={(e) => setOtpPhone(e.target.value.replace(/[^0-9]/g, '').slice(0, 10))}
                    placeholder="10-digit number"
                    maxLength={10}
                    style={{ flex: 1, padding: '0.7rem', borderRadius: '8px', border: '1px solid #d1d5db', fontSize: '0.9rem', outline: 'none' }}
                    onKeyDown={(e) => e.key === 'Enter' && handleSendOtp()}
                  />
                </div>
                {otpError && <p style={{ color: '#ef4444', fontSize: '0.75rem', marginTop: '0.3rem' }}>{otpError}</p>}
                <button
                  onClick={handleSendOtp}
                  disabled={otpLoading || otpPhone.length < 10}
                  style={{ width: '100%', marginTop: '0.6rem', padding: '0.7rem', borderRadius: '8px', background: otpLoading || otpPhone.length < 10 ? '#d1d5db' : '#2563eb', color: 'white', border: 'none', cursor: otpLoading || otpPhone.length < 10 ? 'not-allowed' : 'pointer', fontWeight: 600, fontSize: '0.9rem' }}
                >
                  {otpLoading ? 'Sending OTP...' : 'Send OTP'}
                </button>
              </div>
            ) : (
              <div>
                <label style={{ display: 'block', marginBottom: '0.4rem', fontWeight: 500, fontSize: '0.85rem', color: '#374151' }}>Enter OTP sent to +91 {otpPhone.slice(-10)}</label>
                <input
                  type="text"
                  inputMode="numeric"
                  value={otpCode}
                  onChange={(e) => setOtpCode(e.target.value.replace(/[^0-9]/g, '').slice(0, 6))}
                  placeholder="Enter OTP"
                  maxLength={6}
                  style={{ width: '100%', padding: '0.7rem', borderRadius: '8px', border: '1px solid #d1d5db', fontSize: '1rem', letterSpacing: '0.3rem', textAlign: 'center', outline: 'none' }}
                  onKeyDown={(e) => e.key === 'Enter' && handleVerifyOtp()}
                  autoFocus
                />
                {otpError && <p style={{ color: '#ef4444', fontSize: '0.75rem', marginTop: '0.3rem' }}>{otpError}</p>}
                <button
                  onClick={handleVerifyOtp}
                  disabled={otpLoading || otpCode.length < 4}
                  style={{ width: '100%', marginTop: '0.6rem', padding: '0.7rem', borderRadius: '8px', background: otpLoading || otpCode.length < 4 ? '#d1d5db' : '#16a34a', color: 'white', border: 'none', cursor: otpLoading || otpCode.length < 4 ? 'not-allowed' : 'pointer', fontWeight: 600, fontSize: '0.9rem' }}
                >
                  {otpLoading ? 'Verifying...' : 'Verify OTP'}
                </button>
                <button
                  onClick={handleResendOtp}
                  style={{ width: '100%', marginTop: '0.4rem', padding: '0.4rem', background: 'transparent', border: 'none', color: '#2563eb', cursor: 'pointer', fontSize: '0.8rem' }}
                >
                  ← Change number / Resend
                </button>
              </div>
            )}

            <button
              onClick={() => { setShowAuthModal(false); setOtpStep('phone'); setOtpError(''); }}
              style={{ width: '100%', marginTop: '0.75rem', padding: '0.4rem', background: 'transparent', border: 'none', color: '#9ca3af', cursor: 'pointer', fontSize: '0.75rem' }}
            >
              Skip for now
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

export default ChatBotNewMobile;
