import { useState, useRef, useEffect, useCallback } from 'react';
import { Send, Bot, User, Mic, MicOff, Package, Box, Gift, ArrowLeft, Plus, MessageSquare, ShoppingCart, Scale, Users, Sparkles, Youtube, History, X, Menu, Edit3, Chrome, Zap, Brain, Copy, PanelLeftClose, PanelLeftOpen, ExternalLink, Star, Settings, FileText, BarChart3, ScanLine, Video, Calendar, Sun, Moon, Type, Globe, TrendingUp, Lock, Shield, CreditCard, Code, Activity } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import './ChatBotNew.css';
import { getApiBaseRequired } from '../config/apiBase';
import { formatCompaniesForDisplay, analyzeMarketGaps } from '../utils/csvParser';
import ContextPoolPanel from './ContextPoolPanel';


// ── Markdown normaliser — ensures consistent heading levels across LLM output ──
const formatSectionMarkdown = (text) => {
  let r = text;
  // Standalone **ALL CAPS LABEL** lines → ### heading
  r = r.replace(/^\*\*([A-Z][A-Z &\-\/():'0-9,.]+?)\*\*\s*$/gm, (_, l) => `### ${l.trim()}`);
  // Standalone ALL-CAPS lines (8+ chars, not already heading/table/list) → ### heading
  r = r.replace(/^(?![#>|*\-])([A-Z][A-Z &\-\/():'0-9,.]{7,})\s*$/gm, (_, l) => `### ${l.trim()}`);
  // STEP N → Tool  (tool matrix) → #### heading
  r = r.replace(/^(?:#{0,4}\s*)?(?:\*\*)?STEP\s+(\d{1,2})\s*[\u2192\->]+\s*(.+?)(?:\*\*)?\s*$/gm,
    (_, n, t) => `#### STEP ${n} → ${t.trim()}`);
  return r;
};

// ── Collapsible playbook section (stable component — must live outside render) ──
const formatPlaybookSteps = (text) => text; // raw text passed to PlaybookStepsRenderer

// ── Parse playbook text into structured steps ──
const parsePlaybookSteps = (text) => {
  const steps = [];
  let checklist = '';

  // Extract Week 1 checklist block
  const checklistMatch = text.match(/(?:#{0,4}\s*)?(?:\*\*)?\s*WEEK\s*1\s*EXECUTION\s*CHECKLIST(?:\*\*)?\s*\n([\s\S]*?)(?=\n(?:#{1,4}|\d+\.)|\Z)/i);
  if (checklistMatch) checklist = checklistMatch[1].trim();

  // Normalize step headings to a parseable marker
  const normalized = text
    .replace(/^(?:#{0,3}\s*)?(?:\*\*)?STEP\s+(\d{1,2})\s*[—\-–:]\s*(.*?)(?:\*\*)?\s*$/gm, '___STEP_$1___$2')
    .replace(/^(?:#{0,3}\s*)?(?:\*\*)?(\d{1,2})\.\s*(?:\*\*\s*)?(?:The\s+)?[""\u201C]?([^""\u201D\n]+?)[""\u201D]?(?:\*\*)?\s*$/gm, '___STEP_$1___$2');

  const blocks = normalized.split(/^___STEP_(\d+)___(.*)$/m);

  for (let i = 1; i < blocks.length; i += 3) {
    const num = parseInt(blocks[i]);
    const title = blocks[i + 1]?.replace(/\*\*/g, '').trim() || '';
    const body = (blocks[i + 2] || '').trim();

    // Parse subsections within the step body
    const SUB_PATTERNS = [
      { key: 'todo',    regex: /(?:#{0,4}\s*)?(?:\*\*)?(?:📌\s*)?WHAT TO DO(?:\*\*)?\s*\n/i,          icon: '📌', label: 'What To Do',       color: '#1d4ed8', bg: '#eff6ff', border: '#bfdbfe' },
      { key: 'tool',    regex: /(?:#{0,4}\s*)?(?:\*\*)?(?:🤖\s*)?TOOL\s*[+&]\s*AI SHORTCUT(?:\*\*)?\s*\n/i, icon: '🤖', label: 'Tool + AI Shortcut', color: '#7c3aed', bg: '#f5f3ff', border: '#ddd6fe' },
      { key: 'example', regex: /(?:#{0,4}\s*)?(?:\*\*)?(?:💡\s*)?REAL EXAMPLE(?:\*\*)?\s*\n/i,         icon: '💡', label: 'Real Example',      color: '#b45309', bg: '#fffbeb', border: '#fde68a' },
      { key: 'edge',    regex: /(?:#{0,4}\s*)?(?:\*\*)?(?:⚡\s*)?THE EDGE(?:\*\*)?\s*\n/i,             icon: '⚡', label: 'The Edge',         color: '#065f46', bg: '#f0fdf4', border: '#bbf7d0' },
    ];

    // Split body into subsections
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
      // Text before first subsection
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

// ── Renders structured playbook steps ──
const PlaybookStepsRenderer = ({ content }) => {
  const { steps, checklist } = parsePlaybookSteps(content);

  if (!steps.length) {
    return (
      <div className="playbook-markdown" style={{ fontSize: '0.875rem', color: '#1e293b', lineHeight: 1.8 }}>
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{formatSectionMarkdown(content)}</ReactMarkdown>
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
      {steps.map((step, si) => (
        <div key={si} style={{
          background: '#fff',
          border: '1px solid #e5e7eb',
          borderRadius: '16px',
          overflow: 'hidden',
          boxShadow: '0 2px 8px rgba(0,0,0,0.05)',
        }}>
          {/* Step header */}
          <div style={{
            padding: '1rem 1.25rem',
            background: 'linear-gradient(135deg, #faf5ff 0%, #f5f3ff 100%)',
            borderBottom: '1px solid #e9d5ff',
            display: 'flex', alignItems: 'center', gap: '0.9rem',
          }}>
            <div style={{
              width: '36px', height: '36px', borderRadius: '10px', flexShrink: 0,
              background: '#7c3aed', color: '#fff',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: '0.85rem', fontWeight: 800,
            }}>{step.num}</div>
            <div style={{ fontSize: '0.95rem', fontWeight: 800, color: '#1e1b4b', letterSpacing: '-0.02em', lineHeight: 1.3 }}>
              {step.title}
            </div>
          </div>

          {/* Subsections */}
          <div style={{ padding: '0.85rem', display: 'flex', flexDirection: 'column', gap: '0.65rem' }}>
            {step.subsections.map((sub, subi) => (
              <div key={subi} style={{
                borderRadius: '10px',
                background: sub.bg === 'transparent' ? '#fafafa' : sub.bg,
                border: `1px solid ${sub.border === 'transparent' ? '#f0f0f0' : sub.border}`,
                padding: '0.8rem 1rem',
              }}>
                {sub.label && (
                  <div style={{
                    display: 'inline-flex', alignItems: 'center', gap: '0.35rem',
                    fontSize: '0.7rem', fontWeight: 800, color: sub.color,
                    letterSpacing: '0.05em', textTransform: 'uppercase',
                    marginBottom: '0.5rem',
                  }}>
                    <span>{sub.icon}</span> {sub.label}
                  </div>
                )}
                <div className="playbook-markdown" style={{ fontSize: '0.845rem', color: '#374151', lineHeight: 1.75 }}>
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{formatSectionMarkdown(sub.content)}</ReactMarkdown>
                </div>
              </div>
            ))}
          </div>
        </div>
      ))}

      {/* Week 1 Checklist */}
      {checklist && (
        <div style={{
          background: '#fffbeb', border: '1px solid #fde68a',
          borderRadius: '16px', padding: '1.1rem 1.25rem',
          boxShadow: '0 2px 8px rgba(245,158,11,0.08)',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.75rem' }}>
            <span style={{ fontSize: '1.1rem' }}>📅</span>
            <span style={{ fontSize: '0.85rem', fontWeight: 800, color: '#92400e', letterSpacing: '-0.01em' }}>Week 1 Execution Checklist</span>
          </div>
          <div className="playbook-markdown" style={{ fontSize: '0.845rem', color: '#374151', lineHeight: 1.75 }}>
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{checklist}</ReactMarkdown>
          </div>
        </div>
      )}
    </div>
  );
};

const PlaybookCollapsible = ({ title, icon, color, bg, borderColor, content, isPlaybookSteps }) => {
  const [expanded, setExpanded] = useState(false);
  const [height, setHeight] = useState(0);
  const [visible, setVisible] = useState(false);
  const contentRef = useRef(null);

  useEffect(() => {
    const t = setTimeout(() => setVisible(true), 60);
    return () => clearTimeout(t);
  }, []);

  useEffect(() => {
    if (!contentRef.current) return;
    setHeight(expanded ? contentRef.current.scrollHeight : 0);
  }, [expanded]);

  return (
    <div style={{
      opacity: visible ? 1 : 0,
      transform: visible ? 'translateY(0)' : 'translateY(14px)',
      transition: 'opacity 0.45s ease, transform 0.45s ease',
      background: '#ffffff',
      borderRadius: '20px',
      marginBottom: '1rem',
      overflow: 'hidden',
      boxShadow: '0 4px 24px rgba(0,0,0,0.07), 0 1px 6px rgba(0,0,0,0.04)',
      border: `1px solid ${borderColor}`,
    }}>
      {/* Top gradient accent bar */}
      <div style={{ height: '4px', background: `linear-gradient(90deg, ${color}, ${color}66)` }} />

      {/* Clickable header */}
      <div
        onClick={() => setExpanded(e => !e)}
        style={{
          padding: '1.25rem 1.5rem',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          cursor: 'pointer', background: bg, userSelect: 'none',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.9rem' }}>
          <div style={{
            width: '44px', height: '44px', borderRadius: '12px',
            background: color + '1a',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: '1.35rem', flexShrink: 0,
            boxShadow: `0 2px 8px ${color}22`,
          }}>{icon}</div>
          <div>
            <div style={{ fontSize: '1.05rem', fontWeight: 800, color: '#111827', letterSpacing: '-0.02em', lineHeight: 1.2 }}>{title}</div>
            <div style={{ fontSize: '0.72rem', color: '#9ca3af', marginTop: '0.2rem', fontWeight: 500 }}>
              {expanded ? 'Click to collapse' : 'Click to expand'}
            </div>
          </div>
        </div>
        <div style={{
          width: '32px', height: '32px', borderRadius: '50%',
          background: color + '15', border: `1.5px solid ${borderColor}`,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          color, fontSize: '0.7rem', flexShrink: 0,
          transform: expanded ? 'rotate(180deg)' : 'rotate(0deg)',
          transition: 'transform 0.35s ease',
        }}>▼</div>
      </div>

      {/* Animated content */}
      <div style={{
        maxHeight: `${height}px`,
        overflow: 'hidden',
        transition: 'max-height 0.42s cubic-bezier(0.4, 0, 0.2, 1)',
      }}>
        <div ref={contentRef} style={{ borderTop: `1px solid ${borderColor}`, padding: '1.25rem 1.5rem' }}>
          {isPlaybookSteps ? (
            <PlaybookStepsRenderer content={content} />
          ) : (
            <div className="playbook-markdown" style={{ fontSize: '0.875rem', color: '#1e293b', lineHeight: 1.8 }}>
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{formatSectionMarkdown(content)}</ReactMarkdown>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

// ── Heuristic: pick the "better" model output by word count ──
const pickBestModel = (glm, opus) => {
  if (!glm && !opus) return 'glm';
  if (!opus) return 'glm';
  if (!glm) return 'opus';
  const wordCount = (s) => s.trim().split(/\s+/).length;
  const glmWords = wordCount(glm);
  const opusWords = wordCount(opus);
  // Opus wins ties and slight leads; GLM wins only if clearly longer (>20%)
  return glmWords > opusWords * 1.2 ? 'glm' : 'opus';
};

// ── Generic dual-model section (GLM vs Claude Sonnet 4.6 + Best) ──
const DualModelSection = ({
  glmContent, opusContent,
  title, icon,
  glmColor, glmBg, glmBorder,
  opusColor, opusBg, opusBorder,
  isPlaybookSteps = false,
}) => {
  const bestWinner = pickBestModel(glmContent, opusContent);
  const [tab, setTab] = useState(opusContent ? 'best' : 'glm');

  // No opus content → plain section (no tabs)
  if (!opusContent) {
    return (
      <PlaybookCollapsible
        title={title} icon={icon}
        color={glmColor} bg={glmBg} borderColor={glmBorder}
        content={glmContent} isPlaybookSteps={isPlaybookSteps}
      />
    );
  }

  const activeContent = tab === 'best'
    ? (bestWinner === 'opus' ? opusContent : glmContent)
    : tab === 'opus' ? opusContent : glmContent;
  const activeColor  = (tab === 'best' ? bestWinner : tab) === 'opus' ? opusColor : glmColor;
  const activeBg     = (tab === 'best' ? bestWinner : tab) === 'opus' ? opusBg     : glmBg;
  const activeBorder = (tab === 'best' ? bestWinner : tab) === 'opus' ? opusBorder : glmBorder;

  const TABS = [
    {
      id: 'best',
      label: `🏆 Best (${bestWinner === 'opus' ? 'Claude Opus' : 'GLM-5'})`,
      activeColor: '#065f46',
      idleColor: '#059669',
      idleBg: '#d1fae5',
    },
    { id: 'glm',  label: '⚡ GLM-5',           activeColor: '#1d4ed8', idleColor: '#0284c7', idleBg: '#dbeafe' },
    { id: 'opus', label: '✨ Claude Sonnet 4.6', activeColor: '#6d28d9', idleColor: '#7c3aed', idleBg: '#ede9fe' },
  ];

  return (
    <div>
      <div style={{ display: 'flex', gap: '0.4rem', marginBottom: '0.55rem', flexWrap: 'wrap' }}>
        {TABS.map(t => (
          <button key={t.id} onClick={() => setTab(t.id)} style={{
            padding: '0.28rem 0.8rem',
            fontSize: '0.77rem',
            fontWeight: 700,
            color: tab === t.id ? '#fff' : t.idleColor,
            background: tab === t.id ? t.activeColor : t.idleBg,
            border: `1.5px solid ${t.idleColor}`,
            borderRadius: '7px',
            cursor: 'pointer',
            transition: 'all 0.15s',
          }}>
            {t.label}
          </button>
        ))}
      </div>
      <PlaybookCollapsible
        key={tab}
        title={title} icon={icon}
        color={activeColor}
        bg={activeBg}
        borderColor={activeBorder}
        content={activeContent}
        isPlaybookSteps={isPlaybookSteps}
      />
    </div>
  );
};

// ── Gap Questions — Opus comparison tab (read-only) ──
const GapQuestionsOpusView = ({ parsed, raw }) => {
  if (parsed && parsed.length > 0) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
        {parsed.map((gq, i) => (
          <div key={i} style={{
            background: 'rgba(237,233,254,0.5)',
            borderRadius: '10px', padding: '0.9rem',
            border: '1px solid rgba(139,92,246,0.18)',
          }}>
            <div style={{ fontSize: '0.86rem', fontWeight: 600, color: '#6d28d9', marginBottom: '0.4rem' }}>
              {gq.id} — {gq.label}
            </div>
            <div style={{ fontSize: '0.83rem', color: '#4b5563', lineHeight: 1.5, marginBottom: '0.5rem' }}>
              {gq.question}
            </div>
            {gq.options && gq.options.map((opt, oi) => (
              <div key={oi} style={{
                padding: '0.4rem 0.75rem', marginBottom: '0.25rem',
                borderRadius: '7px', border: '1px solid rgba(139,92,246,0.2)',
                background: '#f5f3ff', fontSize: '0.82rem', color: '#5b21b6',
              }}>{opt}</div>
            ))}
          </div>
        ))}
        <div style={{ fontSize: '0.78rem', color: '#9ca3af', fontStyle: 'italic' }}>
          ✨ Claude Sonnet 4.6 questions — shown for comparison only. Answer GLM-5's questions above.
        </div>
      </div>
    );
  }
  if (raw) {
    return (
      <div style={{ fontSize: '0.86rem', color: '#374151', whiteSpace: 'pre-wrap', lineHeight: 1.6 }}>
        {raw}
        <div style={{ fontSize: '0.78rem', color: '#9ca3af', fontStyle: 'italic', marginTop: '0.5rem' }}>
          ✨ Claude Sonnet 4.6 questions — shown for comparison only.
        </div>
      </div>
    );
  }
  return <div style={{ fontSize: '0.84rem', color: '#9ca3af' }}>Opus gap questions not available.</div>;
};

// ── Gap Questions container with GLM/Opus model tabs ──
const GapQuestionsPanel = ({
  message, playbookStage, playbookGapSelections, setPlaybookGapSelections,
  playbookGapAnswer, setPlaybookGapAnswer, handlePlaybookGapSubmit,
}) => (
  <div className="playbook-gap-container" style={{
    background: 'linear-gradient(135deg, #faf5ff 0%, #f0f9ff 100%)',
    border: '1px solid rgba(139, 92, 246, 0.25)',
    borderRadius: '16px', padding: '1.5rem', marginTop: '0.75rem',
  }}>
    <div style={{ fontSize: '0.95rem', fontWeight: 600, color: '#7c3aed', marginBottom: '1rem' }}>
      📋 A few more details needed
    </div>

    {message.gapQuestionsParsed && message.gapQuestionsParsed.length > 0 ? (
      <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
        {message.gapQuestionsParsed.map((gq) => (
          <div key={gq.id} style={{
            background: 'rgba(255,255,255,0.7)', borderRadius: '12px',
            padding: '1rem', border: '1px solid rgba(139, 92, 246, 0.12)',
          }}>
            <div style={{ fontSize: '0.88rem', fontWeight: 600, color: '#374151', marginBottom: '0.6rem' }}>
              {gq.id} — {gq.label}
            </div>
            <div style={{ fontSize: '0.84rem', color: '#6b7280', marginBottom: '0.6rem', lineHeight: 1.5 }}>
              {gq.question}
            </div>
            {playbookStage === 'gap-questions' && gq.options && gq.options.length > 0 && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
                {gq.options.map((opt, oi) => {
                  const isSelected = playbookGapSelections[gq.id] === opt;
                  return (
                    <button key={oi}
                      onClick={() => setPlaybookGapSelections(prev => ({ ...prev, [gq.id]: opt }))}
                      style={{
                        padding: '0.55rem 0.85rem', borderRadius: '8px', textAlign: 'left',
                        border: isSelected ? '2px solid #7c3aed' : '1px solid rgba(139, 92, 246, 0.2)',
                        background: isSelected ? 'rgba(124,58,237,0.08)' : '#fff',
                        color: isSelected ? '#7c3aed' : '#374151',
                        fontWeight: isSelected ? 600 : 400, fontSize: '0.84rem',
                        cursor: 'pointer', transition: 'all 0.15s ease',
                      }}
                    >{opt}</button>
                  );
                })}
              </div>
            )}
            {playbookStage !== 'gap-questions' && playbookGapSelections[gq.id] && (
              <div style={{ fontSize: '0.84rem', color: '#7c3aed', fontWeight: 500, marginTop: '0.3rem' }}>
                ✓ {playbookGapSelections[gq.id]}
              </div>
            )}
          </div>
        ))}
        {playbookStage === 'gap-questions' && (
          <button
            onClick={handlePlaybookGapSubmit}
            disabled={!message.gapQuestionsParsed.every(gq => playbookGapSelections[gq.id])}
            style={{
              padding: '0.75rem 1.5rem', borderRadius: '10px', border: 'none',
              background: message.gapQuestionsParsed.every(gq => playbookGapSelections[gq.id]) ? '#7c3aed' : '#d1d5db',
              color: '#fff', fontWeight: 600, fontSize: '0.9rem', alignSelf: 'flex-end',
              cursor: message.gapQuestionsParsed.every(gq => playbookGapSelections[gq.id]) ? 'pointer' : 'not-allowed',
              transition: 'background 0.2s',
            }}
          >Submit Answers →</button>
        )}
      </div>
    ) : (
      <>
        <div style={{ fontSize: '0.88rem', color: '#374151', whiteSpace: 'pre-wrap', lineHeight: 1.6, marginBottom: '1rem' }}>
          {message.gapQuestionsText}
        </div>
        {playbookStage === 'gap-questions' && (
          <div style={{ display: 'flex', gap: '0.5rem' }}>
            <textarea value={playbookGapAnswer} onChange={(e) => setPlaybookGapAnswer(e.target.value)}
              placeholder="Type your answers here..." rows={3} style={{
                flex: 1, padding: '0.75rem', borderRadius: '10px',
                border: '1px solid rgba(139, 92, 246, 0.3)', fontSize: '0.88rem',
                resize: 'vertical', fontFamily: 'inherit',
              }} />
            <button onClick={() => { if (playbookGapAnswer.trim()) handlePlaybookGapSubmit(); }}
              disabled={!playbookGapAnswer.trim()}
              style={{
                padding: '0.75rem 1.25rem', borderRadius: '10px', border: 'none',
                background: playbookGapAnswer.trim() ? '#7c3aed' : '#d1d5db',
                color: '#fff', fontWeight: 600, alignSelf: 'flex-end',
                cursor: playbookGapAnswer.trim() ? 'pointer' : 'not-allowed',
              }}>Submit →</button>
          </div>
        )}
      </>
    )}
  </div>
);

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
// ROOT CAUSE ANALYSIS (RCA) DATA STRUCTURE
// Based on rca.csv - For Founder/Owner persona, Grow Revenue outcome
// ============================================
const RCA_DATA = {
  'lead-generation': {
    'founder-owner': {
      // Sub-outcome area 1: Social Media Content
      'Social media content (posts, ads, videos, product visuals)': {
        problemDefinition: [
          {
            question: 'Q1. What is the main purpose of your social media content right now?',
            options: [
              'Brand awareness',
              'Generating leads / DMs',
              'Driving sales',
              'Retargeting existing users',
              'Not clearly defined'
            ]
          },
          {
            question: 'Q2. How do you know content isn\'t working?',
            options: [
              'Low reach / views',
              'Engagement but no inquiries',
              'Inquiries but no sales',
              'Inconsistent performance',
              'Not tracked'
            ]
          },
          {
            question: 'Q3. Which best describes your current content style?',
            options: [
              'Product-focused',
              'Educational / problem-solving',
              'Trend / entertainment-based',
              'Mixed, no clear direction',
              'Not sure'
            ]
          },
          {
            question: 'Q4. Where does the breakdown seem to happen?',
            options: [
              'People don\'t see the content',
              'People see but don\'t engage',
              'Engage but don\'t inquire',
              'Inquire but don\'t buy',
              'Unsure'
            ]
          },
          {
            question: 'Q5. How consistent is your content output?',
            options: [
              'Daily / planned',
              'Weekly',
              'Irregular',
              'Very random',
              'Almost inactive'
            ]
          },
          {
            question: 'Q6. How confident are you that content contributes to revenue?',
            options: [
              'Very confident',
              'Somewhat confident',
              'Weak connection',
              'Mostly guesswork',
              'No idea'
            ]
          }
        ],
        dataCollection: [
          'Instagram / Facebook / YouTube profile links',
          'Last 30–60 days of content',
          'Posts, reels, ads (whatever exists)',
          'Which platform brings inquiries? (if known)'
        ]
      },
      // Sub-outcome area 2: SEO
      'Get more leads from Google & website (SEO)': {
        problemDefinition: [
          {
            question: 'Q1. What are you trying to improve via SEO?',
            options: [
              'Traffic volume',
              'Lead quality',
              'Sales / purchases',
              'Brand visibility',
              'Not sure'
            ]
          },
          {
            question: 'Q2. What best describes your current traffic?',
            options: [
              'Very low',
              'Decent but not converting',
              'High but poor quality',
              'Seasonal / inconsistent',
              'Not measured'
            ]
          },
          {
            question: 'Q3. What happens to most visitors?',
            options: [
              'Leave immediately',
              'Browse but don\'t act',
              'Click but don\'t submit',
              'Start checkout but abandon',
              'Not sure'
            ]
          },
          {
            question: 'Q4. Your SEO is mostly built around:',
            options: [
              'High search volume keywords',
              'Buyer-intent keywords',
              'Brand terms',
              'Random content ideas',
              'No clear strategy'
            ]
          },
          {
            question: 'Q5. How clear is your website\'s main action?',
            options: [
              'Very clear CTA',
              'Somewhat clear',
              'Multiple confusing CTAs',
              'No strong CTA',
              'Not sure'
            ]
          },
          {
            question: 'Q6. How confident are you in SEO tracking?',
            options: [
              'Fully tracked',
              'Partially tracked',
              'Conflicting data',
              'Mostly guessing',
              'Not tracked'
            ]
          }
        ],
        dataCollection: [
          'Website URL',
          'Top 3 pages they want users to convert from',
          'Google Search Console access OR screenshots',
          'Queries',
          'Pages',
          'Primary CTA on website'
        ]
      },
      // Sub-outcome area 3: Google & Meta Ads
      'Run Google and Meta ads + improve ROI': {
        problemDefinition: [
          {
            question: 'Q1. What is the main goal of running ads?',
            options: [
              'Immediate sales',
              'Lead generation',
              'Retargeting',
              'Testing demand',
              'Not clearly defined'
            ]
          },
          {
            question: 'Q2. What is the biggest concern with ads today?',
            options: [
              'High cost',
              'Low lead quality',
              'Low conversion',
              'Fake / inflated performance',
              'Don\'t know'
            ]
          },
          {
            question: 'Q3. Do reported conversions match real sales?',
            options: [
              'Yes, closely',
              'Some mismatch',
              'Large mismatch',
              'Very confusing',
              'Not tracked'
            ]
          },
          {
            question: 'Q4. Where do users drop after clicking ads?',
            options: [
              'Landing page',
              'Lead form',
              'WhatsApp / call',
              'Checkout',
              'Not sure'
            ]
          },
          {
            question: 'Q5. Ads are optimized mainly for:',
            options: [
              'Clicks',
              'Leads',
              'Purchases',
              'Value / ROAS',
              'Unsure'
            ]
          },
          {
            question: 'Q6. How confident are you in ad ROI?',
            options: [
              'Very confident',
              'Somewhat',
              'Low confidence',
              'Guessing',
              'No clarity'
            ]
          }
        ],
        dataCollection: [
          'Landing page URL used in ads',
          'Ad account screenshots (last 30 days)',
          'Spend',
          'Conversions',
          'ROAS / CPL',
          'What happens after the click',
          'Checkout / WhatsApp / call'
        ]
      },
      // Sub-outcome area 4: Google Business Profile
      'Google Business Profile visibility': {
        problemDefinition: [
          {
            question: 'Q1. What action do you want from GBP visitors?',
            options: [
              'Calls',
              'Directions / visits',
              'WhatsApp messages',
              'Website visits',
              'Not sure'
            ]
          },
          {
            question: 'Q2. How is your GBP performance currently?',
            options: [
              'Strong visibility',
              'Visible but low actions',
              'Low visibility',
              'Inconsistent',
              'Never checked'
            ]
          },
          {
            question: 'Q3. Compared to competitors, your reviews are:',
            options: [
              'Much better',
              'Similar',
              'Worse',
              'Very few',
              'Not sure'
            ]
          },
          {
            question: 'Q4. What happens after inquiries?',
            options: [
              'Convert well',
              'Some convert',
              'Mostly drop',
              'Poor follow-up',
              'Not tracked'
            ]
          },
          {
            question: 'Q5. Your business is mostly:',
            options: [
              'Location-dependent',
              'Service-area based',
              'Hybrid',
              'Online + offline',
              'Not sure'
            ]
          }
        ],
        dataCollection: [
          'GBP listing link',
          'Business category',
          'Reviews count + rating',
          'Main CTA enabled (call / website / WhatsApp)'
        ]
      },
      // Sub-outcome area 5: Why Customers Don't Convert
      'Understanding why customers don\'t convert': {
        problemDefinition: [
          {
            question: 'Q1. Where do customers drop most often?',
            options: [
              'Before contacting',
              'After first interaction',
              'After price',
              'After follow-up',
              'Not sure'
            ]
          },
          {
            question: 'Q2. Common customer response before leaving:',
            options: [
              '"Too expensive"',
              '"Will think"',
              '"Comparing options"',
              'Silent / ghosting',
              'Varies'
            ]
          },
          {
            question: 'Q3. Conversion depends mainly on:',
            options: [
              'Website checkout',
              'Human conversation',
              'Both',
              'Offline effort',
              'Not sure'
            ]
          },
          {
            question: 'Q4. What do you think is the main issue?',
            options: [
              'Price sensitivity',
              'Trust / credibility',
              'Unclear value',
              'Weak follow-up',
              'Wrong audience'
            ]
          },
          {
            question: 'Q5. How structured is conversion tracking?',
            options: [
              'Very clear',
              'Partial',
              'Messy',
              'Guesswork',
              'None'
            ]
          }
        ],
        dataCollection: [
          'Exact conversion path',
          'Website → checkout',
          'Website → WhatsApp',
          'Ads → call',
          'Price point',
          'Any customer messages / chats / objections (anonymized)',
          'Who handles conversion',
          'Founder / team / automation'
        ]
      },
      // Sub-outcome area 6: WhatsApp/Instagram Selling
      'Selling on WhatsApp/Instagram': {
        problemDefinition: [
          {
            question: 'Q1. Where do most chats come from?',
            options: [
              'Ads',
              'Organic social',
              'Website',
              'Referrals',
              'Not sure'
            ]
          },
          {
            question: 'Q2. What happens to most chats?',
            options: [
              'Convert quickly',
              'Long conversations, no sale',
              'Drop after price',
              'No response from user',
              'Not tracked'
            ]
          },
          {
            question: 'Q3. Who handles conversations?',
            options: [
              'Dedicated salesperson',
              'Founder',
              'Multiple people',
              'Automation only',
              'Mixed / unclear'
            ]
          },
          {
            question: 'Q4. Response time is usually:',
            options: [
              'Immediate',
              'Within hours',
              'Same day',
              'Delayed',
              'Varies'
            ]
          },
          {
            question: 'Q5. Is there a defined chat-to-sale flow?',
            options: [
              'Yes',
              'Partially',
              'Very loose',
              'None',
              'Not sure'
            ]
          }
        ],
        dataCollection: [
          'WhatsApp business setup',
          'Catalog / quick replies / automation (yes/no)',
          'Sample chat conversations (anonymized)',
          'Response time expectation',
          'Payment flow',
          'Link / UPI / COD / manual'
        ]
      },
      // Sub-outcome area 7: Lead Qualification & Conversion
      'Lead Qualification, Follow Up & Conversion': {
        problemDefinition: [
          {
            question: 'Q1. How do you define a "qualified lead"?',
            options: [
              'Budget + intent',
              'Interest shown',
              'Anyone who inquires',
              'Not clearly defined'
            ]
          },
          {
            question: 'Q2. What happens after first contact?',
            options: [
              'Structured follow-up',
              'One-time contact',
              'Manual reminders',
              'Often forgotten'
            ]
          },
          {
            question: 'Q3. Biggest leakage point?',
            options: [
              'First call',
              'Second follow-up',
              'Price discussion',
              'No response',
              'Not sure'
            ]
          },
          {
            question: 'Q4. How many follow-ups usually happen?',
            options: [
              '3+',
              '2',
              '1',
              'None'
            ]
          },
          {
            question: 'Q5. Lead tracking is:',
            options: [
              'Proper CRM',
              'Spreadsheet',
              'WhatsApp only',
              'No system'
            ]
          }
        ],
        dataCollection: [
          'Product listing URLs',
          'Top 5 products by revenue',
          'Bundle or combo pages (if any)',
          'Cart & checkout flow',
          'Average order value (approx)'
        ]
      },
      // Sub-outcome area 8: Ecommerce Listing SEO
      'Ecommerce Listing SEO + upsell bundles': {
        problemDefinition: [
          {
            question: 'Q1. What\'s the main revenue issue?',
            options: [
              'Low traffic',
              'Low conversion',
              'Low order value',
              'High cart drop',
              'Not sure'
            ]
          },
          {
            question: 'Q2. Product listings are optimized for:',
            options: [
              'Buyer keywords',
              'Generic keywords',
              'Platform suggestions',
              'Not optimized'
            ]
          },
          {
            question: 'Q3. Most customers buy:',
            options: [
              'One product',
              'Multiple products',
              'Bundles',
              'Depends'
            ]
          },
          {
            question: 'Q4. Bundles exist mainly to:',
            options: [
              'Increase AOV',
              'Clear inventory',
              'Solve a use-case',
              'Discounts only',
              'No bundles'
            ]
          },
          {
            question: 'Q5. Drop-off usually happens at:',
            options: [
              'Product page',
              'Cart',
              'Payment',
              'Delivery step',
              'Not sure'
            ]
          }
        ],
        dataCollection: [
          'Product listing URLs',
          'Top 5 products by revenue',
          'Bundle or combo pages (if any)',
          'Cart & checkout flow',
          'Average order value (approx)'
        ]
      }
    }
  }
};

// RCA Stages for future expansion
const RCA_STAGES = [
  { id: 'problem-definition', name: 'Problem Definition', description: 'Understanding how to define your problem better' },
  { id: 'data-collection', name: 'Data Collection', description: 'Collecting relevant data for analysis' },
  { id: 'symptom-identification', name: 'Symptom Identification', description: 'Identifying symptoms that may be going unnoticed' },
  { id: 'cause-identification', name: 'Cause Identification', description: 'Identifying potential causes' },
  { id: 'root-cause-validation', name: 'Root Cause Validation', description: 'Validating the root cause' },
  { id: 'corrective-action', name: 'Corrective Action Plan', description: 'Creating an action plan to address the root cause' }
];

// Helper function to find RCA data for a category
const findRCAData = (goal, role, category) => {
  // Try exact match first
  const goalData = RCA_DATA[goal];
  if (!goalData) return null;

  const roleData = goalData[role];
  if (!roleData) return null;

  // Try exact category match
  if (roleData[category]) return roleData[category];

  // Try partial match
  for (const key of Object.keys(roleData)) {
    if (category.toLowerCase().includes(key.toLowerCase().substring(0, 15)) ||
      key.toLowerCase().includes(category.toLowerCase().substring(0, 15))) {
      return roleData[key];
    }
  }

  return null;
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
    'Track orders + customer notifications',
    'Support ticket routing automation',
    'Auto-tag route and prioritize tickets',
    'Draft replies in brand voice',
    'WhatsApp/Instagram instant replies',
    'Build a support knowledge base'
  ],
  'Recruiting & HR Ops': [
    'Find candidates faster (multi-source)',
    'Resume screening + shortlisting',
    'Automate interview scheduling',
    'Automate candidate follow-ups',
    'High-volume hiring coordination',
    'Onboarding checklists + HR support',
    'Draft job descriptions and outreach'
  ],
  'Personal & Team Productivity': [
    'Summarize meetings + action items',
    'Summarize meetings + send action items',
    'Extract data from PDFs/images to Sheets',
    'Extract data from PDFs/images',
    'Automate repetitive admin workflows',
    'Excel and App script Automation',
    'Auto-tag and organize documents',
    'Organize notes automatically',
    'Draft emails reports and proposals',
    'Summarize PDFs and long documents'
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

const ChatBotNew = ({ onNavigate }) => {
  const [messages, setMessages] = useState([
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
  const [loadingPhase, setLoadingPhase] = useState(''); // '', 'tools', 'diagnostic'
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

  // ── AI Agent Session State ─────────────────────────────────
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
  const crawlPollRef = useRef(null); // interval ref for polling crawl status
  const crawlSummaryRef = useRef(null); // stash crawl summary to show at right time
  const pendingDiagnosticDataRef = useRef(null); // stash diagnostic data while URL input is shown
  const pendingReportDataRef = useRef(null); // stash {rcaSummary, crawlPoints} for post-auth

  // ── Scale Questions State ──────────────────────────────────
  const [scaleQuestions, setScaleQuestions] = useState([]);
  const [currentScaleQIndex, setCurrentScaleQIndex] = useState(0);
  const scaleAnswersRef = useRef({}); // ref to avoid stale closures
  const [scaleFormSelections, setScaleFormSelections] = useState({}); // {questionId: selectedOption}
  const [scaleFormSubmitted, setScaleFormSubmitted] = useState(false);

  // ── Precision Questions State ──────────────────────────────
  const [precisionQuestions, setPrecisionQuestions] = useState([]);
  const [currentPrecisionQIndex, setCurrentPrecisionQIndex] = useState(0);
  const pendingPrecisionDataRef = useRef(null); // stash {rcaSummaryText, crawlPoints} while precision Qs run

  // ── AI Playbook State ──────────────────────────────────────
  const [playbookStage, setPlaybookStage] = useState(''); // '', 'starting', 'gap-questions', 'generating', 'complete'
  const [playbookGapQuestions, setPlaybookGapQuestions] = useState('');
  const [playbookGapAnswer, setPlaybookGapAnswer] = useState('');
  const [playbookGapSelections, setPlaybookGapSelections] = useState({}); // {Q1: 'A) option', Q2: 'B) option'}

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

  const [isRecording, setIsRecording] = useState(false);
  const [voiceSupported, setVoiceSupported] = useState(false);
  const [showAuthModal, setShowAuthModal] = useState(false);
  const [isGoogleLoaded, setIsGoogleLoaded] = useState(false);
  const [showChatHistory, setShowChatHistory] = useState(false);
  const [speechError, setSpeechError] = useState(null);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [leftSidebarOpen, setLeftSidebarOpen] = useState(false);
  const [contextPoolOpen, setContextPoolOpen] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [thinkingPhraseIndex, setThinkingPhraseIndex] = useState(0);

  // Insights + ICP state
  const [businessInsights, setBusinessInsights] = useState(null);
  const [insightsLoading, setInsightsLoading] = useState(false);

  // Business Intelligence Verdict (pre-RCA, crawl-powered)
  const [businessIntelVerdict, setBusinessIntelVerdict] = useState(null);


  // User preferences state
  const [userPreferences, setUserPreferences] = useState(() => {
    const saved = localStorage.getItem('ikshan-user-preferences');
    return saved ? JSON.parse(saved) : {
      theme: 'light',
      fontSize: 'medium',
      language: 'en'
    };
  });

  // Save preferences to localStorage whenever they change
  useEffect(() => {
    localStorage.setItem('ikshan-user-preferences', JSON.stringify(userPreferences));
    // Apply theme to document
    document.documentElement.setAttribute('data-theme', userPreferences.theme);
    // Apply font size
    document.documentElement.setAttribute('data-font-size', userPreferences.fontSize);
  }, [userPreferences]);

  // Language options
  const languageOptions = [
    { code: 'en', name: 'English' },
    { code: 'hi', name: 'हिंदी (Hindi)' },
    { code: 'es', name: 'Español (Spanish)' },
    { code: 'fr', name: 'Français (French)' },
    { code: 'de', name: 'Deutsch (German)' },
    { code: 'zh', name: '中文 (Chinese)' }
  ];

  // Font size options
  const fontSizeOptions = [
    { value: 'small', label: 'Small' },
    { value: 'medium', label: 'Medium' },
    { value: 'large', label: 'Large' }
  ];

  // Products data for sidebar
  const productsData = [
    { id: 1, name: 'Ecom Listing SEO', subtitle: 'Improve 30-40% Revenue', icon: BarChart3, status: 'active' },
    { id: 2, name: 'Learn from Competitors', subtitle: 'Best Growth Hacks', icon: TrendingUp, status: 'active' },
    { id: 3, name: 'B2B Lead Gen', subtitle: 'Reddit and LinkedIn Hot Leads', icon: MessageSquare, status: 'active' },
    { id: 4, name: 'Youtube Helper', subtitle: 'Script + Thumbnail + Keyword Analysis', icon: Video, status: 'active' },
    { id: 5, name: 'AI Team Professionals', subtitle: 'Marketing / Ops / HR etc', icon: Users, status: 'active' },
    { id: 6, name: 'Content Creator', subtitle: 'SEO / Insta / Blogs / LinkedIn', icon: FileText, status: 'active' }
  ];

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

  // Payment state
  const [paymentVerified, setPaymentVerified] = useState(() => {
    return localStorage.getItem('ikshan-rca-paid') === 'true';
  });
  const [paymentLoading, setPaymentLoading] = useState(false);
  const [paymentOrderId, setPaymentOrderId] = useState(null);

  // Root Cause Analysis (RCA) state
  const [rcaActive, setRcaActive] = useState(false);
  const [rcaStage, setRcaStage] = useState('problem-definition'); // 'problem-definition', 'data-collection', etc.
  const [rcaCurrentQuestionIndex, setRcaCurrentQuestionIndex] = useState(0);
  const [rcaResponses, setRcaResponses] = useState({});
  const [rcaData, setRcaData] = useState(null);
  const [rcaDataInputs, setRcaDataInputs] = useState({}); // Store user's data collection inputs

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

  // Rotate thinking phrases when loading
  const THINKING_PHRASES = [
    '🧠 Thinking...',
    '🔍 Searching the best tools...',
    '📊 Analyzing your space...',
    '🎯 Matching to your needs...',
    '⚡ Almost there...',
  ];

  useEffect(() => {
    if (!taskClickProcessing) {
      setThinkingPhraseIndex(0);
      return;
    }
    const interval = setInterval(() => {
      setThinkingPhraseIndex(prev => (prev + 1) % THINKING_PHRASES.length);
    }, 2200);
    return () => clearInterval(interval);
  }, [taskClickProcessing]);

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

        // Proceed to playbook if auth-gated
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
    setSessionId(null);
    sessionIdRef.current = null;
    setDynamicQuestions([]);
    setCurrentDynamicQIndex(0);
    setDynamicAnswers({});
    setPersonaLoaded(null);
    setDynamicFreeText('');

    // Reset processing guards
    setTaskClickProcessing(false);
    setOutcomeClickProcessing(false);
    setDomainClickProcessing(false);
    setAnswerProcessing(false);

    // Reset Claude RCA mode
    setRcaMode(false);

    // Reset RCA state
    setRcaActive(false);
    setRcaStage('problem-definition');
    setRcaCurrentQuestionIndex(0);
    setRcaResponses({});
    setRcaData(null);
    setRcaDataInputs({});

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
  const handleDomainClick = async (domain) => {
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

  // Handle task selection (Question 3) - Loads diagnostic via Claude RCA or fallback
  const handleTaskClick = async (task) => {
    // Prevent duplicate clicks during loading
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

    // Load diagnostic questions (Claude RCA or fallback)
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
          // Stash the diagnostic data — we'll resume diagnostic after URL is submitted or skipped
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
            showBusinessUrlInput: true, // new flag for the URL input component
          };
          setMessages(prev => [...prev, urlPromptMsg]);
          setFlowStage('url-input');
          setIsTyping(false);
          setLoadingPhase('');
          return;
        }
      }
    } catch (e) {
      console.log('Diagnostic section load failed, falling back', e);
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

    // Show user message
    const userMsg = {
      id: getNextMessageId(),
      text: answer,
      sender: 'user',
      timestamp: new Date(),
    };
    setMessages(prev => [...prev, userMsg]);

    // Record answer on backend (reuse existing /session/answer endpoint)
    try {
      const sid = getSessionId();
      if (sid) {
        await fetch(`${API_BASE}/api/v1/agent/session/answer`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            session_id: sid,
            question_index: 900 + currentPrecisionQIndex, // high index to distinguish
            answer: `[${currentPQ?.type || 'precision'}] ${answer}`,
          }),
        });
      }
    } catch (e) {
      console.log('Precision answer save failed (non-blocking)', e);
    }

    const nextIdx = currentPrecisionQIndex + 1;

    if (nextIdx < precisionQuestions.length) {
      // Show next precision question
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
      // All precision questions answered — proceed to report
      const pendingData = pendingPrecisionDataRef.current;
      pendingPrecisionDataRef.current = null;
      const rcaSummary = pendingData?.rcaSummary || '';
      const crawlPoints = pendingData?.crawlPoints || [];
      await proceedToReport(rcaSummary, crawlPoints);
    }
  };

  // Handle diagnostic option click — in-chat flow (supports both RCA & fallback)
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

    saveToSheet(`Diagnostic (${currentQ?.section || 'q' + currentDynamicQIndex}): ${answer}`, '', '', '');

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
            // Claude says we have enough — try precision questions first, then report
            setIsTyping(false);

            const rcaSummaryText = data.acknowledgment
              ? `${data.acknowledgment}${data.rca_summary ? '\n\n' + data.rca_summary : ''}`
              : data.rca_summary || '';

            // Resolve crawl points now
            let crawlPoints = [];
            if (crawlStatus === 'in_progress') {
              // Wait for crawl to finish
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

            // Skip precision questions if user not signed in — show auth gate immediately
            if (!userEmail) {
              setIsTyping(false);
              setAnswerProcessing(false);
              await proceedToReport(rcaSummaryText, crawlPoints);
              return;
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
                // Show precision questions phase
                setIsTyping(false);
                setPrecisionQuestions(precData.questions);
                setCurrentPrecisionQIndex(0);
                pendingPrecisionDataRef.current = { rcaSummary: rcaSummaryText, crawlPoints };
                setFlowStage('precision-questions');

                // Transition message
                const transMsg = {
                  id: getNextMessageId(),
                  text: `I've cross-referenced your answers with what I found on your website. I have **3 precision questions** that dig into the gaps I spotted.`,
                  sender: 'bot',
                  timestamp: new Date(),
                };

                // First precision question
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

            // No precision questions — go directly to report/auth
            setIsTyping(false);
            setAnswerProcessing(false);
            await proceedToReport(rcaSummaryText, crawlPoints);
            return;
          }

          // Claude gave us the next question
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

      // If Claude fails, just end the diagnostic
      setIsTyping(false);
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
      setAnswerProcessing(false);
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
      console.log('Session tracking: diagnostic answer', e);
    }

    const nextIndex = currentDynamicQIndex + 1;

    if (nextIndex < dynamicQuestions.length) {
      // Add next section as bot message
      const nextQ = dynamicQuestions[nextIndex];
      const sectionLabel = nextQ.section_label || 'Diagnostic';
      const botMsg = {
        id: getNextMessageId(),
        text: `**${sectionLabel}**\n\n${nextQ.question}`,
        sender: 'bot',
        timestamp: new Date(),
        diagnosticOptions: nextQ.options,
        sectionIndex: nextIndex,
        sectionKey: nextQ.section,
        allowsFreeText: nextQ.allows_free_text !== false,
      };
      setMessages(prev => [...prev, userMsg, botMsg]);
      setCurrentDynamicQIndex(nextIndex);
    } else {
      // All sections answered — gate behind auth
      setMessages(prev => [...prev, userMsg]);
      setCurrentDynamicQIndex(nextIndex);
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
    }
  };

  // Handle free-text submission for diagnostic question
  const handleDynamicFreeTextSubmit = () => {
    if (dynamicFreeText.trim()) {
      handleDynamicAnswer(dynamicFreeText.trim());
    }
  };

  // Handle website URL submission for audience analysis
  const handleWebsiteSubmit = async (websiteUrl) => {
    if (!websiteUrl || !websiteUrl.trim()) return;

    let url = websiteUrl.trim();
    // Auto-prepend https:// if missing
    if (!url.startsWith('http://') && !url.startsWith('https://')) {
      url = 'https://' + url;
    }

    // Show user's input
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
      setFlowStage('diagnostic');
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

      // Show single message with all scale questions as a form
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
    // Validate all questions answered
    const allAnswered = scaleQuestions.every(q => {
      const sel = scaleFormSelections[q.id];
      return q.multiSelect
        ? Array.isArray(sel) && sel.length > 0
        : !!sel;
    });
    if (!allAnswered) return;

    scaleAnswersRef.current = { ...scaleFormSelections };
    setScaleFormSubmitted(true);

    // Show summary as user message
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

    // Submit & transition to diagnostic
    {
      setFlowStage('diagnostic');
      setIsTyping(true);

      // Submit scale answers (fire-and-forget) while fetching diagnostic question
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

      // Transition message
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
            // Got context-aware first question — use it instead of stashed
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
            pendingDiagnosticDataRef.current = null; // Clear stashed — no longer needed
            return;
          }
        }
      } catch (e) {
        console.log('Context-aware diagnostic failed, using stashed question', e);
      }

      // Fallback: use the stashed first question from Q3
      setIsTyping(false);
      resumeDiagnosticQuestions();
    }
  };

  // ── Business URL submission (right after tool recommendations) ──
  const handleBusinessUrlSubmit = async (urlInput, gbpInput) => {
    const websiteUrl = urlInput ? urlInput.trim() : '';
    const gbpUrl = gbpInput ? gbpInput.trim() : '';

    if (!websiteUrl && !gbpUrl) return;

    // Normalize URLs
    let normalizedWebsite = websiteUrl;
    let normalizedGbp = gbpUrl;

    if (normalizedWebsite && !normalizedWebsite.startsWith('http://') && !normalizedWebsite.startsWith('https://')) {
      normalizedWebsite = 'https://' + normalizedWebsite;
    }
    if (normalizedGbp && !normalizedGbp.startsWith('http://') && !normalizedGbp.startsWith('https://')) {
      normalizedGbp = 'https://' + normalizedGbp;
    }

    // Validate website URL if provided
    if (normalizedWebsite) {
      const domainRegex = /^https?:\/\/[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?(\.[a-zA-Z]{2,})+/;
      if (!domainRegex.test(normalizedWebsite)) {
        const errorMsg = {
          id: getNextMessageId(),
          text: `That doesn't look like a valid website URL. Please enter a website address like **yourcompany.com**.`,
          sender: 'bot',
          timestamp: new Date(),
          isError: true,
        };
        setMessages(prev => [...prev, errorMsg]);
        return;
      }
    }

    // Validate GBP URL if provided — accept any Google domain link
    if (normalizedGbp) {
      const gbpRegex = /^https?:\/\/(www\.)?(google\.(com|co\.[a-z]{2}|[a-z]{2,})(\/maps|\/)|maps\.google\.|maps\.app\.goo\.gl|g\.co\/|goo\.gl\/maps|share\.google\.)/i;
      if (!gbpRegex.test(normalizedGbp)) {
        const errorMsg = {
          id: getNextMessageId(),
          text: `That doesn't look like a valid Google Business Profile URL. Please paste a link from Google Maps or a Google share link.`,
          sender: 'bot',
          timestamp: new Date(),
          isError: true,
        };
        setMessages(prev => [...prev, errorMsg]);
        return;
      }
    }

    // Show user's input
    const displayParts = [];
    if (normalizedWebsite) displayParts.push(normalizedWebsite);
    if (normalizedGbp) displayParts.push('📍 ' + normalizedGbp);
    const userMsg = {
      id: getNextMessageId(),
      text: displayParts.join('\n'),
      sender: 'user',
      timestamp: new Date(),
    };
    setMessages(prev => [...prev, userMsg]);

    // Fire async crawl job (non-blocking)
    try {
      const sid = getSessionId();
      if (sid) {
        const res = await fetch(`${API_BASE}/api/v1/agent/session/url`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            session_id: sid,
            business_url: normalizedWebsite || '',
            gbp_url: normalizedGbp || '',
          })
        });
        const data = await res.json();

        if (data.crawl_started) {
          setCrawlStatus('in_progress');
          // Start polling for crawl completion
          startCrawlPolling();
        }

        // Show confirmation
        const confirmMsg = {
          id: getNextMessageId(),
          text: data.message || `Got it! I'm analyzing your business in the background while we continue.`,
          sender: 'bot',
          timestamp: new Date(),
        };
        setMessages(prev => [...prev, confirmMsg]);
      }
    } catch (e) {
      console.log('URL submission failed, continuing without crawl', e);
      const fallbackMsg = {
        id: getNextMessageId(),
        text: `I'll analyze your website shortly. Let's continue with a few more questions.`,
        sender: 'bot',
        timestamp: new Date(),
      };
      setMessages(prev => [...prev, fallbackMsg]);
    }

    // Advance to scale questions (which then lead to diagnostic)
    startScaleQuestions();
  };

  // ── Skip business URL (allow generic recommendations) ──
  const handleSkipBusinessUrl = () => {
    const userMsg = {
      id: getNextMessageId(),
      text: "Skip for now",
      sender: 'user',
      timestamp: new Date(),
    };
    setMessages(prev => [...prev, userMsg]);

    // Notify backend
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

    // Advance to scale questions (which then lead to diagnostic)
    startScaleQuestions();
  };

  // ── Poll crawl status in background ──
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
    }, 3000); // Poll every 3 seconds
  };

  // Cleanup crawl polling on unmount
  // (Note: using an effect for cleanup)
  const crawlPollCleanupRef = useRef(() => {
    if (crawlPollRef.current) {
      clearInterval(crawlPollRef.current);
      crawlPollRef.current = null;
    }
  });

  // Skip website analysis and go directly to scale questions → diagnostic
  const handleSkipWebsite = async () => {
    const userMsg = {
      id: getNextMessageId(),
      text: "Skip for now",
      sender: 'user',
      timestamp: new Date(),
    };
    setMessages(prev => [...prev, userMsg]);

    // Go to scale questions (diagnostic happens after)
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

    // Show "building playbook" message
    const startMsg = {
      id: getNextMessageId(),
      text: '🚀 Building your **AI Growth Playbook**...\n\nAnalysing business context and ICP...',
      sender: 'bot',
      timestamp: new Date(),
    };
    setMessages(prev => [...prev, startMsg]);

    try {
      const sid = getSessionId();

      // Step 1: Call /playbook/start → runs Agent 1 + 2
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
        // Agent A has parseable gap questions — show interactive panel
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

      // No gap questions — proceed directly to full pipeline
      setPlaybookStage('generating');
      setMessages(prev => {
        const updated = [...prev];
        const lastBot = updated.findLastIndex(m => m.sender === 'bot');
        if (lastBot >= 0) {
          updated[lastBot] = { ...updated[lastBot], text: '🚀 Building your **AI Growth Playbook**...\n\nContext parsed ✓ ICP built ✓\n\nGenerating 10-step playbook & website audit...' };
        }
        return updated;
      });

      // Step 2: Call /playbook/generate
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
          websiteAudit: genData.website_audit || '',
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
    // Build answer string from selections
    const answerParts = Object.entries(playbookGapSelections)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([qId, option]) => `${qId}: ${option}`);
    const answerText = answerParts.join('\n');

    if (!answerText.trim()) return;

    const userMsg = {
      id: getNextMessageId(),
      text: answerText,
      sender: 'user',
      timestamp: new Date(),
    };
    setMessages(prev => [...prev, userMsg]);

    setPlaybookStage('generating');
    setIsTyping(true);
    setPlaybookGapSelections({});
    setPlaybookGapAnswer('');

    const genMsg = {
      id: getNextMessageId(),
      text: '🚀 Got it! Now generating your **10-step playbook** & website audit...',
      sender: 'bot',
      timestamp: new Date(),
    };
    setMessages(prev => [...prev, genMsg]);

    try {
      const sid = getSessionId();

      // Submit gap answers
      const gapRes = await fetch(`${API_BASE}/api/v1/playbook/gap-answers`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sid, answers: answerText }),
      });

      if (!gapRes.ok) {
        const errBody = await gapRes.json().catch(() => ({}));
        throw new Error(errBody.detail || `Server error ${gapRes.status}`);
      }

      // Generate full playbook
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
          websiteAudit: genData.website_audit || '',
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
        if (typeof data.summary === 'object' && data.summary.one_liner) {
          solutionResponse += `> ${data.summary.one_liner}\n\n`;
        } else if (typeof data.summary === 'string') {
          solutionResponse += `> ${data.summary}\n\n`;
        }
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
      const immediatePrompt = generateImmediatePrompt(selectedGoal, domainLabel, category, category);

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

      solutionResponse += `---\n\n`;

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

  // Legacy subdomain handler - kept for backward compatibility
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
      await fetch('/api/save-idea', {
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

  // ============================================
  // PAYMENT HANDLERS
  // ============================================

  // Initiate payment for RCA unlock
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
        // Redirect to JusPay payment page
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
        text: `⚠️ **Payment Error**\n\nSomething went wrong while initiating the payment. Please try again.\n\n_Error: ${error.message}_`,
        sender: 'bot',
        timestamp: new Date(),
        showFinalActions: true
      }]);
    } finally {
      setPaymentLoading(false);
    }
  };

  // Check payment status on return from JusPay
  useEffect(() => {
    const urlParams = new URLSearchParams(window.location.search);
    const paymentStatus = urlParams.get('payment_status');
    const orderId = urlParams.get('order_id');

    if (paymentStatus === 'success' && orderId) {
      // Verify payment server-side
      const verifyPayment = async () => {
        try {
          const res = await fetch(`/api/v1/payments/status/${orderId}`);
          const data = await res.json();
          if (data.success && (data.status === 'CHARGED' || data.status === 'AUTO_REFUND')) {
            setPaymentVerified(true);
            localStorage.setItem('ikshan-rca-paid', 'true');
            setMessages(prev => [...prev, {
              id: getNextMessageId(),
              text: `✅ **Payment Successful!**\n\nYou now have full access to Root Cause Analysis. Click **Launch Root Cause Analysis** below any solution to start your deep dive.`,
              sender: 'bot',
              timestamp: new Date(),
              showFinalActions: true
            }]);
          }
        } catch (err) {
          console.error('Payment verification failed:', err);
        }
        // Clean URL params
        window.history.replaceState({}, '', window.location.pathname);
      };
      verifyPayment();
    }
  }, []);

  // ============================================
  // ROOT CAUSE ANALYSIS (RCA) HANDLERS
  // ============================================

  // Launch Root Cause Analysis
  const handleLaunchRCA = (category) => {
    // Find RCA data for the current selection
    const data = findRCAData(selectedGoal, 'founder-owner', category || selectedCategory);

    if (!data) {
      // No RCA data available for this combination
      const noDataMessage = {
        id: getNextMessageId(),
        text: `🔍 **Root Cause Analysis**\n\nRoot cause analysis is currently available for:\n- **Persona:** Founder / Owner\n- **Outcome:** Grow Revenue\n\nFor your selected combination, RCA data is coming soon. In the meantime, you can explore the implementation guide or check another idea!`,
        sender: 'bot',
        timestamp: new Date(),
        showFinalActions: true
      };
      setMessages(prev => [...prev, noDataMessage]);
      return;
    }

    // Initialize RCA - Go directly to typeform UI
    setRcaActive(true);
    setRcaStage('problem-definition');
    setRcaCurrentQuestionIndex(0);
    setRcaResponses({});
    setRcaData(data);
    setFlowStage('rca'); // This will show the typeform UI
  };

  // Handle RCA option selection in Typeform UI
  const handleRCAOptionSelectTypeform = (option, questionIndex) => {
    // Prevent selecting again if already answered
    if (rcaResponses[`q${questionIndex + 1}`]) return;
    // Save response
    const newResponses = { ...rcaResponses, [`q${questionIndex + 1}`]: option };
    setRcaResponses(newResponses);

    // Move to next question or data collection
    const nextIndex = questionIndex + 1;
    if (rcaData && rcaData.problemDefinition && nextIndex < rcaData.problemDefinition.length) {
      setRcaCurrentQuestionIndex(nextIndex);
    } else {
      // Move to data collection stage
      setRcaStage('data-collection');
    }
  };

  // Show RCA question
  const showRCAQuestion = (data, questionIndex) => {
    if (!data || !data.problemDefinition || questionIndex >= data.problemDefinition.length) {
      // Move to data collection stage
      showDataCollectionStage(data);
      return;
    }

    const questionData = data.problemDefinition[questionIndex];

    const questionMessage = {
      id: getNextMessageId(),
      text: `**${questionData.question}**`,
      sender: 'bot',
      timestamp: new Date(),
      isRCAQuestion: true,
      rcaOptions: questionData.options,
      rcaQuestionIndex: questionIndex
    };

    setMessages(prev => [...prev, questionMessage]);
    setRcaCurrentQuestionIndex(questionIndex);
  };

  // Handle RCA option selection
  const handleRCAOptionSelect = (option, questionIndex) => {
    // Prevent selecting again if already answered
    if (rcaResponses[`q${questionIndex + 1}`]) return;
    // Record user response
    const userMessage = {
      id: getNextMessageId(),
      text: option,
      sender: 'user',
      timestamp: new Date()
    };

    setMessages(prev => [...prev, userMessage]);

    // Save response
    const newResponses = { ...rcaResponses, [`q${questionIndex + 1}`]: option };
    setRcaResponses(newResponses);

    // Show next question or move to next stage
    const nextIndex = questionIndex + 1;
    if (rcaData && rcaData.problemDefinition && nextIndex < rcaData.problemDefinition.length) {
      setTimeout(() => {
        showRCAQuestion(rcaData, nextIndex);
      }, 300);
    } else {
      // Move to data collection stage
      setTimeout(() => {
        showDataCollectionStage(rcaData);
      }, 500);
    }
  };

  // Show Data Collection stage
  const showDataCollectionStage = (data) => {
    setRcaStage('data-collection');

    if (!data || !data.dataCollection || data.dataCollection.length === 0) {
      // Skip to summary if no data collection items
      showRCASummary();
      return;
    }

    let dataCollectionText = `## 🎯 You're doing great!\n\n`;
    dataCollectionText += `Based on your answers, here's what would help us give you the most accurate insights:\n\n`;
    dataCollectionText += `### Helpful Information\n\n`;

    data.dataCollection.forEach((item, index) => {
      dataCollectionText += `${index + 1}. **${item}**\n`;
    });

    dataCollectionText += `\n---\n\n`;
    dataCollectionText += `💡 **No pressure!** Don't worry if you don't have everything — share what you can, and we'll work with that.\n\n`;
    dataCollectionText += `✨ Even partial information helps us understand your situation better and provide valuable recommendations.`;

    const dataCollectionMessage = {
      id: getNextMessageId(),
      text: dataCollectionText,
      sender: 'bot',
      timestamp: new Date(),
      showRCADataCollectionActions: true
    };

    setMessages(prev => [...prev, dataCollectionMessage]);
  };

  // Show RCA Summary based on responses
  const showRCASummary = () => {
    const outcomeLabel = outcomeOptions.find(g => g.id === selectedGoal)?.text || selectedGoal;
    const domainLabel = selectedDomainName || 'General';

    let summaryText = `## 📋 Root Cause Analysis Summary\n\n`;
    summaryText += `**Domain:** ${domainLabel}\n`;
    summaryText += `**Outcome:** ${outcomeLabel}\n`;
    summaryText += `**Problem Area:** ${selectedCategory}\n\n`;
    summaryText += `---\n\n`;
    summaryText += `### Your Responses\n\n`;

    // List all responses
    if (rcaData && rcaData.problemDefinition) {
      rcaData.problemDefinition.forEach((q, index) => {
        const response = rcaResponses[`q${index + 1}`] || 'Not answered';
        summaryText += `**${q.question}**\n`;
        summaryText += `→ ${response}\n\n`;
      });
    }

    // List data collection inputs if any were provided
    if (rcaData && rcaData.dataCollection) {
      const hasAnyInput = rcaData.dataCollection.some((_, index) => rcaDataInputs[`data_${index}`]);
      if (hasAnyInput) {
        summaryText += `---\n\n`;
        summaryText += `### Information Provided\n\n`;
        rcaData.dataCollection.forEach((item, index) => {
          const value = rcaDataInputs[`data_${index}`];
          if (value && value.trim()) {
            summaryText += `**${item}**\n`;
            summaryText += `→ ${value}\n\n`;
          }
        });
      }
    }

    summaryText += `---\n\n`;
    summaryText += `### Next Steps\n\n`;
    summaryText += `Based on your responses, the following stages are recommended:\n`;
    summaryText += `- **Symptom Identification** - Coming soon\n`;
    summaryText += `- **Cause Identification** - Coming soon\n`;
    summaryText += `- **Root Cause Validation** - Coming soon\n`;
    summaryText += `- **Corrective Action Plan** - Coming soon\n\n`;
    summaryText += `📌 *Stay tuned! We're building out the complete RCA framework to provide you with actionable corrective action plans.*`;

    const summaryMessage = {
      id: getNextMessageId(),
      text: summaryText,
      sender: 'bot',
      timestamp: new Date(),
      showFinalActions: true
    };

    setMessages(prev => [...prev, summaryMessage]);

    // Reset RCA state
    setRcaActive(false);
    setFlowStage('complete');
  };

  // Handle data collection continue
  const handleRCADataCollectionContinue = () => {
    showRCASummary();
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
        const immediatePrompt = generateImmediatePrompt(selectedGoal, domainLabel, selectedCategory, requirement);

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

  // Compute header progress for the typeform stages
  const headerProgressInfo = (() => {
    const stageOrder = ['outcome', 'domain', 'task', 'url-input', 'scale-questions', 'rca', 'playbook', 'complete'];
    const idx = stageOrder.indexOf(flowStage);
    if (idx <= 0) return null;
    const pct = Math.round((idx / (stageOrder.length - 1)) * 100);
    const labels = { domain: 'Step 2', task: 'Step 3', 'url-input': 'Step 4', 'scale-questions': 'Step 5', rca: 'Step 6', playbook: 'Step 7', complete: 'Done' };
    return { pct, label: labels[flowStage] || `Step ${idx}` };
  })();

  return (
    <div className="chatbot-container">
      {/* 3px brand gradient accent bar at very top */}
      <div className="top-accent-bar" />

      {/* Header */}
      <header className="chatbot-header">
        <div className="header-left">
          <button
            onClick={() => setLeftSidebarOpen(!leftSidebarOpen)}
            title={leftSidebarOpen ? "Close Products" : "Our Products"}
            className={`sidebar-toggle ${leftSidebarOpen ? 'active' : ''}`}
          >
            {leftSidebarOpen ? <PanelLeftClose size={20} /> : <PanelLeftOpen size={20} />}
          </button>
          <button onClick={handleStartNewIdea} title="New Chat"><Plus size={20} /></button>
          <button onClick={() => setShowChatHistory(true)} title="History"><History size={20} /></button>
          <button onClick={() => onNavigate && onNavigate('about')} title="About Us"><FileText size={20} /></button>
          <button onClick={() => onNavigate && onNavigate('developer')} title="Developer" className="dev-header-btn"><Code size={20} /></button>
        </div>

        <div className="header-right">
          {/* Step progress indicator */}
          {headerProgressInfo && (
            <div className="header-progress visible">
              <span className="header-progress-label">{headerProgressInfo.label}</span>
              <div className="header-progress-track">
                <div className="header-progress-fill" style={{ width: `${headerProgressInfo.pct}%` }} />
              </div>
            </div>
          )}
          <button
            onClick={() => setContextPoolOpen(!contextPoolOpen)}
            title={contextPoolOpen ? "Close Context Pool" : "Context Pool"}
            className={`sidebar-toggle context-pool-toggle ${contextPoolOpen ? 'active' : ''}`}
          >
            <Activity size={18} />
          </button>
          <div className="logo-container">
            <img src="/android-chrome-192x192.png" alt="Ikshan" className="logo-img" />
            <h2>Ikshan</h2>
          </div>
        </div>
      </header>

      {/* Left Sidebar - Products & Market Intelligence Panel */}
      <div className={`left-sidebar ${leftSidebarOpen ? 'open' : ''}`}>
        <div className="sidebar-header">
          <div className="sidebar-tabs">
            <button
              className="sidebar-tab active"
              onClick={() => { setLeftSidebarOpen(false); }}
            >
              <MessageSquare size={14} /> Chat
            </button>
          </div>
          <button className="sidebar-close" onClick={() => setLeftSidebarOpen(false)}>
            <X size={18} />
          </button>
        </div>
        <div className="sidebar-content">
          <div className="products-list">
            {productsData.map((product) => {
              const IconComponent = product.icon;
              return (
                <div key={product.id} className={`product-card ${product.status}`}>
                  <IconComponent size={18} className="product-icon-simple" />
                  <div className="product-text">
                    <span className="product-name">{product.name}</span>
                    <span className="product-subtitle">{product.subtitle}</span>
                  </div>
                  {product.status === 'coming-soon' && (
                    <span className="coming-soon-badge">Soon</span>
                  )}
                </div>
              );
            })}
          </div>
          <div className="sidebar-footer">
            <button className="settings-btn" onClick={() => setShowSettings(true)}>
              <Settings size={18} /> Settings
            </button>
          </div>
        </div>
      </div>

      {/* Sidebar Overlay */}
      {leftSidebarOpen && (
        <div className="sidebar-overlay" onClick={() => setLeftSidebarOpen(false)} />
      )}

      {/* Main Content - Chat View */}
        <div className="chat-window">
          {/* Typeform / Flow Stages */}
          {['outcome', 'domain', 'task', 'rca'].includes(flowStage) ? (
            <div className="empty-state">
              {flowStage === 'outcome' && (
                <>
                  {/* Brand icon */}
                  <div className="empty-state-icon">
                    <BarChart3 size={30} strokeWidth={2} />
                  </div>
                  <h1>Professional expertise, on-demand—without the salary or recruiting.</h1>
                  <p className="empty-state-subtitle">Select what matters most to you right now</p>
                  <div className="suggestions-grid">
                    {outcomeOptions.map((outcome, index) => (
                      <div
                        key={outcome.id}
                        className="suggestion-card"
                        onClick={() => !outcomeClickProcessing && handleOutcomeClick(outcome)}
                        style={{ animationDelay: `${index * 0.08}s`, animation: 'fadeIn 0.4s ease-out both', opacity: outcomeClickProcessing ? 0.5 : 1, pointerEvents: outcomeClickProcessing ? 'none' : 'auto' }}
                      >
                        <h3>{outcome.text}</h3>
                        {outcome.subtext && <p className="goal-subtext">{outcome.subtext}</p>}
                      </div>
                    ))}
                  </div>
                  {/* Trust badges */}
                  <div className="trust-badges">
                    {['Free forever', 'No signup needed', 'Personalized results'].map(badge => (
                      <span key={badge} className="trust-badge">
                        <span className="trust-badge-check">✓</span>
                        {badge}
                      </span>
                    ))}
                  </div>
                </>
              )}

              {flowStage === 'domain' && (
                <>
                  <span className="empty-state-step-label">Step 2 of 6</span>
                  <h1>Which domain best matches your need?</h1>
                  <p className="empty-state-subtitle">Select a domain to see relevant tasks</p>
                  <div className="suggestions-grid">
                    {getDomainsForSelection().map((domain, index) => (
                      <div
                        key={index}
                        className="suggestion-card"
                        onClick={() => !domainClickProcessing && handleDomainClick(domain)}
                        style={{ animationDelay: `${index * 0.07}s`, animation: 'fadeIn 0.4s ease-out both', opacity: domainClickProcessing ? 0.5 : 1, pointerEvents: domainClickProcessing ? 'none' : 'auto' }}
                      >
                        <h3>{domain}</h3>
                      </div>
                    ))}
                  </div>
                  <button
                    className="back-nav-btn"
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
                      <span className="empty-state-step-label">Step 3 of 6</span>
                      <h1>What task would you like help with?</h1>
                      <div className="suggestions-grid">
                        {getTasksForSelection().map((task, index) => (
                          <div
                            key={index}
                            className="suggestion-card"
                            onClick={() => handleTaskClick(task)}
                            style={{
                              animationDelay: `${index * 0.05}s`,
                              animation: 'fadeIn 0.3s ease-out both',
                            }}
                          >
                            <h3>{task}</h3>
                          </div>
                        ))}
                        <div
                          className="suggestion-card"
                          style={{ borderStyle: 'dashed', borderColor: '#c7d2fe' }}
                          onClick={handleTypeCustomProblem}
                        >
                          <h3 style={{ color: '#6366f1' }}>Type my own problem...</h3>
                        </div>
                      </div>
                      <button
                        className="back-nav-btn"
                        onClick={() => { setSelectedDomainName(null); setFlowStage('domain'); }}
                      >
                        ← Back
                      </button>
                    </>
                  )}
                </>
              )}

              {/* RCA Typeform UI */}
              {flowStage === 'rca' && rcaData && (
                <>
                  {rcaStage === 'problem-definition' && rcaData.problemDefinition && rcaCurrentQuestionIndex < rcaData.problemDefinition.length && (
                    <>
                      <div className="rca-progress-bar">
                        <div className="rca-progress-fill" style={{ width: `${((rcaCurrentQuestionIndex + 1) / rcaData.problemDefinition.length) * 100}%` }}></div>
                      </div>
                      <p className="rca-stage-label">Stage 1: Problem Definition • Question {rcaCurrentQuestionIndex + 1} of {rcaData.problemDefinition.length}</p>
                      <h1>{rcaData.problemDefinition[rcaCurrentQuestionIndex].question}</h1>
                      <div className="suggestions-grid rca-options-grid">
                        {rcaData.problemDefinition[rcaCurrentQuestionIndex].options.map((option, index) => {
                          const alreadyAnswered = !!rcaResponses[`q${rcaCurrentQuestionIndex + 1}`];
                          const isSelected = rcaResponses[`q${rcaCurrentQuestionIndex + 1}`] === option;
                          return (
                          <div
                            key={index}
                            className={`suggestion-card rca-option-card${isSelected ? ' selected' : ''}${alreadyAnswered ? ' disabled' : ''}`}
                            onClick={() => !alreadyAnswered && handleRCAOptionSelectTypeform(option, rcaCurrentQuestionIndex)}
                            style={{ animationDelay: `${index * 0.05}s`, animation: 'fadeIn 0.3s ease-out forwards', opacity: alreadyAnswered && !isSelected ? 0.5 : 1, pointerEvents: alreadyAnswered ? 'none' : 'auto' }}
                          >
                            <h3>{option}</h3>
                          </div>
                          );
                        })}
                      </div>
                      <button
                        className="back-nav-btn"
                        onClick={() => {
                          if (rcaCurrentQuestionIndex > 0) {
                            setRcaCurrentQuestionIndex(rcaCurrentQuestionIndex - 1);
                          } else {
                            setRcaActive(false);
                            setFlowStage('complete');
                          }
                        }}
                      >
                        ← Back
                      </button>
                    </>
                  )}

                  {rcaStage === 'data-collection' && rcaData.dataCollection && (
                    <>
                      <div className="rca-progress-bar">
                        <div className="rca-progress-fill" style={{ width: '100%' }}></div>
                      </div>
                      <p className="rca-stage-label">Stage 2: Data Collection</p>
                      <h1>You're doing great! 🎯</h1>
                      <p style={{ color: '#6b7280', marginBottom: '0.5rem' }}>Based on your answers, here's what would help us give you the most accurate insights.</p>
                      <p style={{ color: '#9ca3af', marginBottom: '1.5rem', fontSize: '0.9rem' }}>💡 Don't worry if you don't have everything — share what you can, and we'll work with that!</p>
                      <div className="rca-data-collection-grid">
                        {rcaData.dataCollection.map((item, index) => (
                          <div
                            key={index}
                            className="rca-data-input-item"
                            style={{ animationDelay: `${index * 0.05}s`, animation: 'fadeIn 0.3s ease-out forwards' }}
                          >
                            <div className="rca-data-input-header">
                              <span className="rca-data-number">{index + 1}</span>
                              <label className="rca-data-label">{item}</label>
                            </div>
                            <input
                              type="text"
                              className="rca-data-input"
                              placeholder={`Enter ${item.toLowerCase()}...`}
                              value={rcaDataInputs[`data_${index}`] || ''}
                              onChange={(e) => setRcaDataInputs(prev => ({
                                ...prev,
                                [`data_${index}`]: e.target.value
                              }))}
                            />
                          </div>
                        ))}
                      </div>
                      <p style={{ color: '#9ca3af', marginTop: '1.5rem', fontSize: '0.85rem', textAlign: 'center' }}>✨ Even partial information helps us understand your situation better</p>
                      <div style={{ marginTop: '1.5rem', display: 'flex', gap: '1rem', justifyContent: 'center', flexWrap: 'wrap' }}>
                        <button
                          onClick={handleRCADataCollectionContinue}
                          className="action-btn primary"
                        >
                          Continue to Summary
                        </button>
                        <button
                          onClick={handleStartNewIdea}
                          className="action-btn secondary"
                        >
                          <Sparkles size={16} /> Check Another Idea
                        </button>
                      </div>
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
                          display: 'grid',
                          gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))',
                          gap: '0.75rem',
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
                                padding: '1rem 1.1rem',
                                cursor: tool.url ? 'pointer' : 'default',
                                transition: 'all 0.25s ease',
                                opacity: 0,
                                animation: `fadeIn 0.4s ease-out ${i * 0.1}s forwards`,
                                position: 'relative',
                                overflow: 'hidden',
                              }}
                              onClick={() => tool.url && window.open(tool.url, '_blank')}
                              onMouseEnter={(e) => {
                                e.currentTarget.style.transform = 'translateY(-2px)';
                                e.currentTarget.style.boxShadow = '0 8px 25px rgba(124, 58, 237, 0.15)';
                                e.currentTarget.style.borderColor = 'rgba(124, 58, 237, 0.35)';
                              }}
                              onMouseLeave={(e) => {
                                e.currentTarget.style.transform = 'translateY(0)';
                                e.currentTarget.style.boxShadow = 'none';
                                e.currentTarget.style.borderColor = 'rgba(124, 58, 237, 0.15)';
                              }}
                            >
                              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.5rem' }}>
                                <span style={{ fontSize: '0.95rem', fontWeight: 700, color: 'var(--ikshan-text-primary, #111827)' }}>
                                  {tool.name}
                                </span>
                                {tool.rating && (
                                  <span style={{
                                    fontSize: '0.75rem',
                                    fontWeight: 600,
                                    color: '#f59e0b',
                                    background: '#fef3c7',
                                    padding: '0.15rem 0.45rem',
                                    borderRadius: '6px',
                                  }}>
                                    ⭐ {tool.rating}
                                  </span>
                                )}
                              </div>
                              <p style={{
                                fontSize: '0.82rem',
                                color: 'var(--ikshan-text-secondary, #6b7280)',
                                lineHeight: 1.45,
                                margin: '0 0 0.5rem 0',
                              }}>
                                {tool.description}
                              </p>
                              {tool.why_relevant && (
                                <p style={{
                                  fontSize: '0.78rem',
                                  color: 'var(--ikshan-purple, #7c3aed)',
                                  fontWeight: 500,
                                  margin: 0,
                                  lineHeight: 1.4,
                                }}>
                                  {tool.why_relevant}
                                </p>
                              )}
                              {/* Enriched tool context: issue solved, stage, ease */}
                              {(tool.issue_solved || tool.implementation_stage || tool.ease_of_use) && (
                                <div style={{
                                  marginTop: '0.5rem',
                                  padding: '0.5rem 0.6rem',
                                  background: 'rgba(124, 58, 237, 0.04)',
                                  borderRadius: '8px',
                                  fontSize: '0.75rem',
                                  lineHeight: 1.5,
                                  color: 'var(--ikshan-text-secondary, #4b5563)',
                                }}>
                                  {tool.issue_solved && (
                                    <div style={{ marginBottom: '0.25rem' }}>
                                      <span style={{ fontWeight: 600, color: '#059669' }}>🎯 Solves: </span>
                                      {tool.issue_solved}
                                    </div>
                                  )}
                                  {tool.implementation_stage && (
                                    <div style={{ marginBottom: '0.25rem' }}>
                                      <span style={{ fontWeight: 600, color: '#3b82f6' }}>📅 When: </span>
                                      {tool.implementation_stage}
                                    </div>
                                  )}
                                  {tool.ease_of_use && (
                                    <div>
                                      <span style={{ fontWeight: 600, color: '#f59e0b' }}>⚡ Ease: </span>
                                      {tool.ease_of_use}
                                    </div>
                                  )}
                                </div>
                              )}
                              {tool.category && (
                                <span style={{
                                  display: 'inline-block',
                                  marginTop: '0.5rem',
                                  fontSize: '0.7rem',
                                  fontWeight: 600,
                                  textTransform: 'uppercase',
                                  letterSpacing: '0.04em',
                                  color: '#7c3aed',
                                  background: 'rgba(124, 58, 237, 0.08)',
                                  padding: '0.2rem 0.5rem',
                                  borderRadius: '4px',
                                }}>
                                  {tool.category}
                                </span>
                              )}
                            </div>
                          ))}
                        </div>
                        <div style={{
                          padding: '0.75rem 1rem',
                          background: 'linear-gradient(90deg, rgba(124, 58, 237, 0.06) 0%, rgba(99, 102, 241, 0.06) 100%)',
                          borderRadius: '10px',
                          borderLeft: '3px solid var(--ikshan-purple, #7c3aed)',
                        }}>
                          <p style={{
                            fontSize: '0.85rem',
                            color: 'var(--ikshan-text-primary, #374151)',
                            margin: 0,
                            lineHeight: 1.5,
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
                        padding: '1.25rem',
                        borderRadius: '14px',
                        border: '1px solid rgba(124, 58, 237, 0.2)',
                        background: 'linear-gradient(135deg, #fafaff 0%, #f0eeff 100%)',
                        boxShadow: '0 2px 12px rgba(124, 58, 237, 0.08)',
                      }}>
                        {/* Website URL */}
                        <div style={{ marginBottom: '0.6rem' }}>
                          <label style={{
                            display: 'block',
                            fontSize: '0.78rem',
                            fontWeight: 600,
                            color: 'var(--ikshan-text-secondary, #6b7280)',
                            marginBottom: '0.3rem',
                          }}>🌐 Website URL</label>
                          <input
                            type="url"
                            placeholder="yourcompany.com"
                            style={{
                              width: '100%',
                              padding: '0.7rem 1rem',
                              borderRadius: '10px',
                              border: '1.5px solid var(--ikshan-border, #d1d5db)',
                              background: 'var(--ikshan-input-bg, #fff)',
                              color: 'var(--ikshan-text-primary, #1a1a1a)',
                              fontSize: '0.9rem',
                              outline: 'none',
                              transition: 'border-color 0.2s ease',
                              boxSizing: 'border-box',
                            }}
                            onFocus={(e) => { e.target.style.borderColor = '#7c3aed'; }}
                            onBlur={(e) => { e.target.style.borderColor = '#d1d5db'; }}
                            id="business-url-input"
                            autoFocus
                          />
                        </div>

                        {/* GBP URL */}
                        <div style={{ marginBottom: '0.75rem' }}>
                          <label style={{
                            display: 'block',
                            fontSize: '0.78rem',
                            fontWeight: 600,
                            color: 'var(--ikshan-text-secondary, #6b7280)',
                            marginBottom: '0.3rem',
                          }}>📍 Google Business Profile URL <span style={{ fontWeight: 400, opacity: 0.7 }}>(optional)</span></label>
                          <input
                            type="url"
                            placeholder="Paste your Google Maps / GBP link"
                            style={{
                              width: '100%',
                              padding: '0.7rem 1rem',
                              borderRadius: '10px',
                              border: '1.5px solid var(--ikshan-border, #d1d5db)',
                              background: 'var(--ikshan-input-bg, #fff)',
                              color: 'var(--ikshan-text-primary, #1a1a1a)',
                              fontSize: '0.9rem',
                              outline: 'none',
                              transition: 'border-color 0.2s ease',
                              boxSizing: 'border-box',
                            }}
                            onFocus={(e) => { e.target.style.borderColor = '#7c3aed'; }}
                            onBlur={(e) => { e.target.style.borderColor = '#d1d5db'; }}
                            id="gbp-url-input"
                          />
                        </div>

                        <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                          <button
                            onClick={() => {
                              const websiteInput = document.getElementById('business-url-input');
                              const gbpInput = document.getElementById('gbp-url-input');
                              const website = websiteInput ? websiteInput.value.trim() : '';
                              const gbp = gbpInput ? gbpInput.value.trim() : '';
                              if (website || gbp) {
                                handleBusinessUrlSubmit(website, gbp);
                              }
                            }}
                            style={{
                              padding: '0.7rem 1.25rem',
                              borderRadius: '10px',
                              border: 'none',
                              background: 'linear-gradient(135deg, #7c3aed 0%, #6366f1 100%)',
                              color: '#fff',
                              fontSize: '0.85rem',
                              fontWeight: 700,
                              cursor: 'pointer',
                              whiteSpace: 'nowrap',
                              transition: 'transform 0.15s ease, box-shadow 0.15s ease',
                            }}
                            onMouseEnter={(e) => {
                              e.target.style.transform = 'translateY(-1px)';
                              e.target.style.boxShadow = '0 4px 14px rgba(124, 58, 237, 0.3)';
                            }}
                            onMouseLeave={(e) => {
                              e.target.style.transform = 'translateY(0)';
                              e.target.style.boxShadow = 'none';
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
                            fontSize: '0.8rem',
                            cursor: 'pointer',
                            padding: '0.25rem 0',
                            marginTop: '0.5rem',
                            opacity: 0.8,
                            transition: 'opacity 0.2s',
                          }}
                          onMouseEnter={(e) => { e.target.style.opacity = 1; e.target.style.textDecoration = 'underline'; }}
                          onMouseLeave={(e) => { e.target.style.opacity = 0.8; e.target.style.textDecoration = 'none'; }}
                        >
                          Skip — without URLs, we'll give general recommendations
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
                        {/* Verdict headline */}
                        {message.businessIntelData.verdict_line && (
                          <div className="bi-verdict-headline">
                            <span className="bi-verdict-headline-icon">⚡</span>
                            <span className="bi-verdict-headline-text">{message.businessIntelData.verdict_line}</span>
                          </div>
                        )}

                        {/* ICP Snapshot */}
                        {message.businessIntelData.icp_snapshot && (
                          <div className="bi-section bi-icp">
                            <div className="bi-section-label">
                              <span className="bi-section-icon">👤</span> Who Your Ideal Customer Is
                            </div>
                            <p className="bi-section-text">{message.businessIntelData.icp_snapshot}</p>
                          </div>
                        )}

                        {/* SEO Health */}
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

                        {/* Funnel Strategies — Collapsible */}
                        {[
                          { key: 'top_funnel', label: 'Top Funnel — Awareness & Discovery', icon: '📢', color: '#8b5cf6' },
                          { key: 'mid_funnel', label: 'Mid Funnel — Consideration & Trust', icon: '🤝', color: '#f59e0b' },
                          { key: 'bottom_funnel', label: 'Bottom Funnel — Conversion & Revenue', icon: '💰', color: '#10b981' },
                        ].map(funnel => (
                          message.businessIntelData[funnel.key] && message.businessIntelData[funnel.key].length > 0 && (
                            <details key={funnel.key} className="bi-funnel-section" open>
                              <summary className="bi-funnel-header" style={{ '--funnel-color': funnel.color }}>
                                <span className="bi-funnel-icon">{funnel.icon}</span>
                                <span className="bi-funnel-label">{funnel.label}</span>
                                <span className="bi-funnel-count">{message.businessIntelData[funnel.key].length} strategies</span>
                              </summary>
                              <div className="bi-funnel-strategies">
                                {message.businessIntelData[funnel.key].map((s, i) => (
                                  <div key={i} className="bi-strategy-item" style={{ animationDelay: `${i * 0.06}s` }}>
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

                    {/* ── AI Playbook — Gap Questions (GLM interactive + Opus comparison) ── */}
                    {message.isPlaybookGapQuestions && (
                      <GapQuestionsPanel
                        message={message}
                        playbookStage={playbookStage}
                        playbookGapSelections={playbookGapSelections}
                        setPlaybookGapSelections={setPlaybookGapSelections}
                        playbookGapAnswer={playbookGapAnswer}
                        setPlaybookGapAnswer={setPlaybookGapAnswer}
                        handlePlaybookGapSubmit={handlePlaybookGapSubmit}
                      />
                    )}

                    {/* ── AI Playbook Result ── */}
                    {message.isPlaybook && message.playbookData && (
                      <div className="playbook-container" style={{ marginTop: '1rem' }}>
                        {/* Playbook Header Banner — clean light design */}
                        <div style={{
                          background: '#fff',
                          borderRadius: '20px', padding: '1.4rem 1.75rem', marginBottom: '1rem',
                          border: '1px solid #e5e7eb',
                          boxShadow: '0 2px 12px rgba(0,0,0,0.06)',
                          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                        }}>
                          <div>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.4rem' }}>
                              <Sparkles size={14} color="#7c3aed" />
                              <span style={{ fontSize: '0.7rem', fontWeight: 700, color: '#7c3aed', letterSpacing: '0.08em', textTransform: 'uppercase' }}>AI Growth Playbook</span>
                            </div>
                            <div style={{ fontSize: '1.2rem', fontWeight: 900, color: '#111827', letterSpacing: '-0.025em', lineHeight: 1.2 }}>
                              Your Personalised Strategy
                            </div>
                            <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.6rem', flexWrap: 'wrap' }}>
                              {[['📋','Playbook','#7c3aed','#f3e8ff'],['🌐','Audit','#d97706','#fef3c7']].map(([ico,lbl,col,bg]) => (
                                <span key={lbl} style={{ display:'inline-flex', alignItems:'center', gap:'0.3rem', background: bg, color: col, fontSize:'0.72rem', fontWeight:700, padding:'0.25rem 0.6rem', borderRadius:'20px' }}>
                                  {ico} {lbl}
                                </span>
                              ))}
                            </div>
                          </div>
                          <div style={{ fontSize: '2.8rem', lineHeight: 1, flexShrink: 0 }}>🚀</div>
                        </div>

                        {message.playbookData.playbook && (
                          <PlaybookCollapsible
                            title="10-Step Growth Playbook" icon="📋"
                            color="#7c3aed" bg="linear-gradient(135deg, #faf5ff 0%, #f3eeff 100%)" borderColor="rgba(139, 92, 246, 0.2)"
                            content={message.playbookData.playbook}
                            isPlaybookSteps
                          />
                        )}
                        {message.playbookData.websiteAudit && (
                          <PlaybookCollapsible
                            title="Website Audit & Recommendations" icon="🌐"
                            color="#d97706" bg="linear-gradient(135deg, #fff7ed 0%, #fef3e2 100%)" borderColor="rgba(245, 158, 11, 0.2)"
                            content={message.playbookData.websiteAudit}
                          />
                        )}
                      </div>
                    )}

                    {/* Crawl Summary — compressed 5-point business snapshot */}
                    {message.showCrawlDetails && !message.isPlaybook && message.crawlSummaryPoints && message.crawlSummaryPoints.length > 0 && (
                      <div className="crawl-summary-card" style={{
                        marginTop: '0.75rem',
                        padding: '1rem 1.25rem',
                        borderRadius: '12px',
                        border: '1px solid rgba(16, 185, 129, 0.25)',
                        background: 'linear-gradient(135deg, #f0fdf4 0%, #ecfdf5 100%)',
                        boxShadow: '0 2px 8px rgba(16, 185, 129, 0.08)',
                      }}>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
                          {message.crawlSummaryPoints.map((point, i) => (
                            <div key={i} style={{
                              display: 'flex',
                              alignItems: 'flex-start',
                              gap: '0.5rem',
                              fontSize: '0.85rem',
                              color: 'var(--ikshan-text-primary, #1a1a1a)',
                              lineHeight: '1.4',
                            }}>
                              <span style={{ color: '#10b981', fontWeight: 700, flexShrink: 0 }}>✓</span>
                              <span>{point}</span>
                            </div>
                          ))}
                        </div>
                        <details style={{ marginTop: '0.75rem' }}>
                          <summary style={{
                            fontSize: '0.78rem',
                            color: 'var(--ikshan-text-secondary, #6b7280)',
                            cursor: 'pointer',
                            userSelect: 'none',
                            fontWeight: 500,
                          }}>
                            View full analysis details
                          </summary>
                          <div style={{
                            marginTop: '0.5rem',
                            padding: '0.75rem',
                            fontSize: '0.78rem',
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
                        padding: '1rem',
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
                              padding: '0.625rem 0.875rem',
                              borderRadius: '8px',
                              border: '1px solid var(--ikshan-border, #d1d5db)',
                              background: 'var(--ikshan-input-bg, #fff)',
                              color: 'var(--ikshan-text-primary, #1a1a1a)',
                              fontSize: '0.9rem',
                              outline: 'none',
                            }}
                            onKeyDown={(e) => {
                              if (e.key === 'Enter' && e.target.value.trim()) {
                                handleWebsiteSubmit(e.target.value);
                              }
                            }}
                            id="website-url-input"
                          />
                          <button
                            onClick={() => {
                              const input = document.getElementById('website-url-input');
                              if (input && input.value.trim()) {
                                handleWebsiteSubmit(input.value);
                              }
                            }}
                            style={{
                              padding: '0.625rem 1rem',
                              borderRadius: '8px',
                              border: 'none',
                              background: 'var(--ikshan-accent, #6366f1)',
                              color: '#fff',
                              fontSize: '0.85rem',
                              fontWeight: 600,
                              cursor: 'pointer',
                            }}
                          >
                            Analyze &rarr;
                          </button>
                        </div>
                        <button
                          onClick={handleSkipWebsite}
                          style={{
                            background: 'none',
                            border: 'none',
                            color: 'var(--ikshan-text-secondary, #6b7280)',
                            fontSize: '0.8rem',
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
                          {/* Launch RCA Button - Only show if paid */}
                          {selectedCategory && selectedGoal === 'lead-generation' && paymentVerified && (
                            <button
                              onClick={() => handleLaunchRCA(message.userRequirement || selectedCategory)}
                              className="action-btn rca"
                            >
                              <Brain size={16} /> Launch Root Cause Analysis
                            </button>
                          )}
                        </div>

                        {/* Payment Card — Unlock RCA (only show if NOT paid and RCA is relevant) */}
                        {selectedCategory && selectedGoal === 'lead-generation' && !paymentVerified && (
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
                                  Go beyond surface-level solutions. Get a deep, structured diagnosis of your problem with
                                  AI-powered root cause analysis, data collection framework, and corrective action plan.
                                </p>
                                <ul className="payment-card-features">
                                  <li><Shield size={14} /> Stage 1: Problem Definition (5 diagnostic questions)</li>
                                  <li><BarChart3 size={14} /> Stage 2: Data Collection framework</li>
                                  <li><Brain size={14} /> AI-generated Root Cause Summary</li>
                                  <li><TrendingUp size={14} /> Corrective Action Plan</li>
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
                                  <Shield size={12} /> Secured by JusPay &amp; HDFC Bank
                                </p>
                              </div>
                            </div>
                          </div>
                        )}
                      </div>
                    )}

                    {/* RCA Question Options */}
                    {message.isRCAQuestion && message.rcaOptions && (() => {
                      const questionKey = `q${message.rcaQuestionIndex + 1}`;
                      const answered = !!rcaResponses[questionKey];
                      const selectedOption = rcaResponses[questionKey];
                      return (
                      <div className="rca-options-container" style={{ marginTop: '1rem', display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                        {message.rcaOptions.map((option, index) => {
                          const isSelected = selectedOption === option;
                          return (
                          <button
                            key={index}
                            onClick={() => !answered && handleRCAOptionSelect(option, message.rcaQuestionIndex)}
                            className={`rca-option-btn${isSelected ? ' selected' : ''}`}
                            disabled={answered}
                            style={{
                              padding: '0.75rem 1rem',
                              background: isSelected ? 'var(--ikshan-chat-bubble-user)' : 'var(--ikshan-surface)',
                              border: isSelected ? '2px solid var(--ikshan-purple)' : '1px solid var(--ikshan-border)',
                              borderRadius: '0.75rem',
                              textAlign: 'left',
                              cursor: answered ? 'default' : 'pointer',
                              transition: 'all 0.2s ease',
                              fontSize: '0.95rem',
                              color: 'var(--ikshan-text-primary)',
                              opacity: answered && !isSelected ? 0.4 : 1,
                              pointerEvents: answered ? 'none' : 'auto'
                            }}
                            onMouseEnter={(e) => {
                              if (!answered) {
                                e.target.style.borderColor = 'var(--ikshan-purple)';
                                e.target.style.background = 'var(--ikshan-chat-bubble-user)';
                              }
                            }}
                            onMouseLeave={(e) => {
                              if (!answered) {
                                e.target.style.borderColor = 'var(--ikshan-border)';
                                e.target.style.background = 'var(--ikshan-surface)';
                              }
                            }}
                          >
                            {isSelected ? '☑' : '☐'} {option}
                          </button>
                          );
                        })}
                      </div>
                      );
                    })()
                    }

                    {/* RCA Data Collection Actions */}
                    {message.showRCADataCollectionActions && (
                      <div style={{ marginTop: '1.5rem', display: 'flex', gap: '0.75rem', flexWrap: 'wrap' }}>
                        <button
                          onClick={handleRCADataCollectionContinue}
                          className="action-btn primary"
                        >
                          Continue to Summary
                        </button>
                        <button
                          onClick={handleStartNewIdea}
                          className="action-btn secondary"
                        >
                          <Sparkles size={16} /> Check Another Idea
                        </button>
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
                      /* ── Sleek thinking animation during Q3 processing ── */
                      <div className="thinking-clean" style={{ padding: '0.5rem 0.75rem' }}>
                        <div className="thinking-clean-spinner" style={{ width: 18, height: 18 }} />
                        <p key={thinkingPhraseIndex} className="thinking-clean-text" style={{ fontSize: '0.8rem' }}>
                          {THINKING_PHRASES[thinkingPhraseIndex]}
                        </p>
                      </div>
                    ) : (
                      /* ── Default typing dots ── */
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

      {/* Input Area - Only show in chat view */}
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
          <div className="identity-form" onClick={(e) => e.stopPropagation()} style={{ maxWidth: '400px', padding: '2rem' }}>
            <h2 style={{ marginBottom: '0.5rem' }}>Verify to Continue</h2>
            <p style={{ marginBottom: '1.5rem', color: '#6b7280', fontSize: '0.9rem' }}>Sign in with Google or verify your phone number</p>

            {/* Google Sign-In */}
            <button onClick={handleGoogleSignIn} style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '10px', background: 'white', border: '1px solid #d1d5db', color: '#374151', width: '100%', padding: '0.75rem', borderRadius: '8px', cursor: 'pointer', fontSize: '0.95rem', marginBottom: '1.25rem' }}>
              <span style={{ fontWeight: 600 }}>Continue with Google</span>
            </button>

            {/* Divider */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '1.25rem' }}>
              <div style={{ flex: 1, height: '1px', background: '#e5e7eb' }} />
              <span style={{ color: '#9ca3af', fontSize: '0.8rem' }}>OR</span>
              <div style={{ flex: 1, height: '1px', background: '#e5e7eb' }} />
            </div>

            {/* OTP Flow */}
            {otpStep === 'phone' ? (
              <div>
                <label style={{ display: 'block', marginBottom: '0.5rem', fontWeight: 500, fontSize: '0.9rem', color: '#374151' }}>Mobile Number</label>
                <div style={{ display: 'flex', gap: '0.5rem' }}>
                  <span style={{ display: 'flex', alignItems: 'center', padding: '0 0.5rem', background: '#f3f4f6', borderRadius: '8px', fontSize: '0.9rem', color: '#6b7280', border: '1px solid #d1d5db' }}>+91</span>
                  <input
                    type="tel"
                    value={otpPhone}
                    onChange={(e) => setOtpPhone(e.target.value.replace(/[^0-9]/g, '').slice(0, 10))}
                    placeholder="10-digit mobile number"
                    maxLength={10}
                    style={{ flex: 1, padding: '0.75rem', borderRadius: '8px', border: '1px solid #d1d5db', fontSize: '0.95rem', outline: 'none' }}
                    onKeyDown={(e) => e.key === 'Enter' && handleSendOtp()}
                  />
                </div>
                {otpError && <p style={{ color: '#ef4444', fontSize: '0.8rem', marginTop: '0.4rem' }}>{otpError}</p>}
                <button
                  onClick={handleSendOtp}
                  disabled={otpLoading || otpPhone.length < 10}
                  style={{ width: '100%', marginTop: '0.75rem', padding: '0.75rem', borderRadius: '8px', background: otpLoading || otpPhone.length < 10 ? '#d1d5db' : '#2563eb', color: 'white', border: 'none', cursor: otpLoading || otpPhone.length < 10 ? 'not-allowed' : 'pointer', fontWeight: 600, fontSize: '0.95rem' }}
                >
                  {otpLoading ? 'Sending OTP...' : 'Send OTP'}
                </button>
              </div>
            ) : (
              <div>
                <label style={{ display: 'block', marginBottom: '0.5rem', fontWeight: 500, fontSize: '0.9rem', color: '#374151' }}>Enter OTP sent to +91 {otpPhone.slice(-10)}</label>
                <input
                  type="text"
                  inputMode="numeric"
                  value={otpCode}
                  onChange={(e) => setOtpCode(e.target.value.replace(/[^0-9]/g, '').slice(0, 6))}
                  placeholder="Enter 4-6 digit OTP"
                  maxLength={6}
                  style={{ width: '100%', padding: '0.75rem', borderRadius: '8px', border: '1px solid #d1d5db', fontSize: '1.1rem', letterSpacing: '0.3rem', textAlign: 'center', outline: 'none' }}
                  onKeyDown={(e) => e.key === 'Enter' && handleVerifyOtp()}
                  autoFocus
                />
                {otpError && <p style={{ color: '#ef4444', fontSize: '0.8rem', marginTop: '0.4rem' }}>{otpError}</p>}
                <button
                  onClick={handleVerifyOtp}
                  disabled={otpLoading || otpCode.length < 4}
                  style={{ width: '100%', marginTop: '0.75rem', padding: '0.75rem', borderRadius: '8px', background: otpLoading || otpCode.length < 4 ? '#d1d5db' : '#16a34a', color: 'white', border: 'none', cursor: otpLoading || otpCode.length < 4 ? 'not-allowed' : 'pointer', fontWeight: 600, fontSize: '0.95rem' }}
                >
                  {otpLoading ? 'Verifying...' : 'Verify OTP'}
                </button>
                <button
                  onClick={handleResendOtp}
                  style={{ width: '100%', marginTop: '0.5rem', padding: '0.5rem', background: 'transparent', border: 'none', color: '#2563eb', cursor: 'pointer', fontSize: '0.85rem' }}
                >
                  ← Change number / Resend OTP
                </button>
              </div>
            )}

            {/* Skip option */}
            <button
              onClick={() => { setShowAuthModal(false); setOtpStep('phone'); setOtpError(''); }}
              style={{ width: '100%', marginTop: '1rem', padding: '0.5rem', background: 'transparent', border: 'none', color: '#9ca3af', cursor: 'pointer', fontSize: '0.8rem' }}
            >
              Skip for now
            </button>
          </div>
        </div>
      )}

      {/* Settings Modal */}
      {showSettings && (
        <div className="settings-overlay" onClick={() => setShowSettings(false)}>
          <div className="settings-modal" onClick={(e) => e.stopPropagation()}>
            <div className="settings-header">
              <h2>Settings</h2>
              <button className="settings-close" onClick={() => setShowSettings(false)}>
                <X size={20} />
              </button>
            </div>

            <div className="settings-content">
              {/* Theme Toggle */}
              <div className="settings-section">
                <div className="settings-label">
                  <span className="settings-icon">{userPreferences.theme === 'dark' ? <Moon size={18} /> : <Sun size={18} />}</span>
                  <span>Theme</span>
                </div>
                <div className="theme-toggle">
                  <button
                    className={`theme-btn ${userPreferences.theme === 'light' ? 'active' : ''}`}
                    onClick={() => setUserPreferences(prev => ({ ...prev, theme: 'light' }))}
                  >
                    <Sun size={16} /> Light
                  </button>
                  <button
                    className={`theme-btn ${userPreferences.theme === 'dark' ? 'active' : ''}`}
                    onClick={() => setUserPreferences(prev => ({ ...prev, theme: 'dark' }))}
                  >
                    <Moon size={16} /> Dark
                  </button>
                </div>
              </div>

              {/* Font Size */}
              <div className="settings-section">
                <div className="settings-label">
                  <span className="settings-icon"><Type size={18} /></span>
                  <span>Font Size</span>
                </div>
                <div className="font-size-options">
                  {fontSizeOptions.map((option) => (
                    <button
                      key={option.value}
                      className={`font-size-btn ${userPreferences.fontSize === option.value ? 'active' : ''}`}
                      onClick={() => setUserPreferences(prev => ({ ...prev, fontSize: option.value }))}
                    >
                      {option.label}
                    </button>
                  ))}
                </div>
              </div>

              {/* Language */}
              <div className="settings-section">
                <div className="settings-label">
                  <span className="settings-icon"><Globe size={18} /></span>
                  <span>Language</span>
                </div>
                <select
                  className="language-select"
                  value={userPreferences.language}
                  onChange={(e) => setUserPreferences(prev => ({ ...prev, language: e.target.value }))}
                >
                  {languageOptions.map((lang) => (
                    <option key={lang.code} value={lang.code}>
                      {lang.name}
                    </option>
                  ))}
                </select>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Context Pool Panel — Right side LLM transparency */}
      <ContextPoolPanel
        sessionId={sessionId}
        isOpen={contextPoolOpen}
        onClose={() => setContextPoolOpen(false)}
      />
    </div>
  );
};

export default ChatBotNew;
