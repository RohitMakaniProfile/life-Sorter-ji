import { useState, useRef, useCallback, useEffect } from 'react';
import Navbar from './Navbar';
import FlowNode from './FlowNode';
import ToolCard from './ToolCard';
import ScreensaverPreview from './ScreensaverPreview';
import { outcomeOptions, OUTCOME_DOMAINS, DOMAIN_TASKS } from './constants';
import * as api from './api';
import './IkshanApp.css';

/**
 * HORIZONTAL JOURNEY CANVAS
 *
 * The entire screen is one horizontally-scrolling canvas.
 * Each selection adds a new column to the right, connected by arrows.
 * Mouse wheel scrolls left/right. All previous nodes stay visible —
 * the user sees their full journey trail.
 *
 * Columns:
 *   0: Outcomes (Q1)   — always shown
 *   1: Domains (Q2)    — after outcome selected
 *   2: Tasks (Q3)      — after domain selected
 *   3: URL form        — after task selected
 *   4: Deeper Dive     — after URL submit/skip
 *   5: Diagnostic      — after scale answers
 *   6+: Precision / Complete
 */

export default function IkshanApp() {
  const canvasRef = useRef(null);
  const [showScreensaver, setShowScreensaver] = useState(true);

  // ─── Session ──────────────────────────────────────────
  const sessionIdRef = useRef(null);
  const sessionPromiseRef = useRef(null);

  const ensureSession = useCallback(async () => {
    if (sessionIdRef.current) return sessionIdRef.current;
    if (!sessionPromiseRef.current) {
      sessionPromiseRef.current = api.createSession()
        .then((data) => { sessionIdRef.current = data.session_id; return data.session_id; })
        .catch((err) => { sessionPromiseRef.current = null; throw err; });
    }
    return sessionPromiseRef.current;
  }, []);

  // ─── Journey State ────────────────────────────────────
  const [selectedOutcome, setSelectedOutcome] = useState(null);
  const [selectedDomain, setSelectedDomain] = useState(null);
  const [selectedTask, setSelectedTask] = useState(null);
  const [hoveredOutcome, setHoveredOutcome] = useState(null);
  const [hoveredDomain, setHoveredDomain] = useState(null);
  const [hoveredTask, setHoveredTask] = useState(null);

  // Post-task stages
  const [showUrlForm, setShowUrlForm] = useState(false);
  const [toolPage, setToolPage] = useState(0);
  const TOOLS_PER_PAGE = 3;
  const [urlTab, setUrlTab] = useState('website');
  const [urlValue, setUrlValue] = useState('');
  const [email, setEmail] = useState('');
  const [urlSubmitting, setUrlSubmitting] = useState(false);
  const [earlyTools, setEarlyTools] = useState([]);

  // Deeper dive
  const [showDeeperDive, setShowDeeperDive] = useState(false);
  const [scaleQuestions, setScaleQuestions] = useState([]);
  const [scaleAnswers, setScaleAnswers] = useState({});
  const [scalePage, setScalePage] = useState(0);

  // Diagnostic
  const [showDiagnostic, setShowDiagnostic] = useState(false);
  const [diagnosticData, setDiagnosticData] = useState(null);
  const [currentQuestion, setCurrentQuestion] = useState(null);
  const [questionIndex, setQuestionIndex] = useState(0);
  const [acknowledgment, setAcknowledgment] = useState('');
  const [loading, setLoading] = useState(false);

  // Precision
  const [showPrecision, setShowPrecision] = useState(false);
  const [precisionQuestions, setPrecisionQuestions] = useState([]);
  const [precisionIndex, setPrecisionIndex] = useState(0);

  // Complete
  const [showComplete, setShowComplete] = useState(false);

  const [error, setError] = useState(null);

  // ─── Horizontal wheel scroll ──────────────────────────
  useEffect(() => {
    const el = canvasRef.current;
    if (!el) return;
    const onWheel = (e) => {
      if (Math.abs(e.deltaY) > Math.abs(e.deltaX)) {
        e.preventDefault();
        el.scrollLeft += e.deltaY;
      }
    };
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  }, []);

  // Auto-scroll so newest column is roughly centered
  const scrollToEnd = useCallback(() => {
    const el = canvasRef.current;
    if (!el) return;
    requestAnimationFrame(() => {
      // Scroll so the rightmost content is in view with some breathing room
      const target = el.scrollWidth - el.clientWidth;
      el.scrollTo({ left: Math.max(0, target), behavior: 'smooth' });
    });
  }, []);

  // ─── Derived data ─────────────────────────────────────
  const domains = selectedOutcome ? (OUTCOME_DOMAINS[selectedOutcome.id] || []) : [];
  const tasks = selectedDomain ? (DOMAIN_TASKS[selectedDomain] || []) : [];
  const hoverDomains = hoveredOutcome ? (OUTCOME_DOMAINS[hoveredOutcome] || []) : [];
  const hoverTasks = hoveredDomain ? (DOMAIN_TASKS[hoveredDomain] || []) : [];

  // ─── Handlers ─────────────────────────────────────────

  const handleOutcomeClick = async (outcome) => {
    setSelectedOutcome(outcome);
    setSelectedDomain(null);
    setSelectedTask(null);
    setShowUrlForm(false);
    setShowDeeperDive(false);
    setShowDiagnostic(false);
    setShowPrecision(false);
    setShowComplete(false);
    setEarlyTools([]);
    setHoveredOutcome(null);
    setTimeout(scrollToEnd, 50);

    try {
      const sid = await ensureSession();
      await api.submitOutcome(sid, outcome.id, `${outcome.text} (${outcome.subtext})`);
    } catch (err) { console.warn('Outcome submit:', err.message); }
  };

  const handleDomainClick = async (domain) => {
    setSelectedDomain(domain);
    setSelectedTask(null);
    setShowUrlForm(false);
    setShowDeeperDive(false);
    setShowDiagnostic(false);
    setShowPrecision(false);
    setShowComplete(false);
    setEarlyTools([]);
    setHoveredDomain(null);
    setTimeout(scrollToEnd, 50);

    try {
      const sid = await ensureSession();
      await api.submitDomain(sid, domain);
    } catch (err) { console.warn('Domain submit:', err.message); }
  };

  const handleTaskClick = async (task) => {
    setSelectedTask(task);
    setShowUrlForm(true);
    setShowDeeperDive(false);
    setShowDiagnostic(false);
    setShowPrecision(false);
    setShowComplete(false);
    setEarlyTools([]);
    setToolPage(0);
    setHoveredTask(null);
    setTimeout(scrollToEnd, 50);

    try {
      const sid = await ensureSession();
      // Submit task to session (fire and forget, don't block tools)
      api.submitTask(sid, task).then((data) => setDiagnosticData(data)).catch(() => {});

      // Fetch instant tool recommendations based on Q1/Q2/Q3
      const toolsData = await api.getInstantTools(
        selectedOutcome.id, selectedDomain, task
      );
      if (toolsData.tools && toolsData.tools.length > 0) {
        setEarlyTools(toolsData.tools.map((t) => {
          // Concise description: prefer best_use_case (short), fallback to description truncated
          const rawDesc = t.best_use_case || t.description || '';
          const desc = rawDesc.length > 100 ? rawDesc.slice(0, 97) + '...' : rawDesc;

          // Max 3 bullet points, each ≤60 chars
          let bullets = [];
          if (t.key_pros) {
            const raw = Array.isArray(t.key_pros)
              ? t.key_pros
              : t.key_pros.split('\n').map(s => s.replace(/^[•\-\s]+/, '').trim()).filter(Boolean);
            bullets = raw.slice(0, 3).map(b => b.length > 60 ? b.slice(0, 57) + '...' : b);
          }

          return {
            name: t.name,
            rating: t.rating || null,
            description: desc,
            bullets,
            tag: t.category || 'RECOMMENDED',
            url: t.url,
          };
        }));
      }
    } catch (err) { console.warn('Task submit / instant-tools:', err.message); }

    setTimeout(scrollToEnd, 100);
  };

  const handleUrlSubmit = async (e) => {
    e.preventDefault();
    if (!urlValue.trim()) return;
    let finalUrl = urlValue.trim();
    if (!/^https?:\/\//i.test(finalUrl)) finalUrl = `https://${finalUrl}`;
    setUrlSubmitting(true);
    try {
      const sid = await ensureSession();
      await api.submitUrl(sid, finalUrl);
      await moveToScaleQuestions();
    } catch (err) {
      setError('Failed to submit URL.');
    } finally { setUrlSubmitting(false); }
  };

  const handleUrlSkip = async () => {
    setUrlSubmitting(true);
    try {
      const sid = await ensureSession();
      await api.skipUrl(sid);
    } catch (err) { console.warn('Skip URL:', err.message); }
    await moveToScaleQuestions();
    setUrlSubmitting(false);
  };

  const moveToScaleQuestions = async () => {
    try {
      const sid = await ensureSession();
      const data = await api.getScaleQuestions(sid);
      setScaleQuestions(data.questions || []);
    } catch (err) { setScaleQuestions([]); }
    setShowDeeperDive(true);
    setTimeout(scrollToEnd, 50);
  };

  const handleScaleSelect = (qId, option, multiSelect) => {
    setScaleAnswers((prev) => {
      if (multiSelect) {
        const cur = prev[qId] || [];
        return { ...prev, [qId]: cur.includes(option) ? cur.filter((o) => o !== option) : [...cur, option] };
      }
      return { ...prev, [qId]: option };
    });
  };

  const handleScaleSubmit = async () => {
    setLoading(true);
    try {
      const sid = await ensureSession();
      await api.submitScaleAnswers(sid, scaleAnswers);
      const diagData = await api.startDiagnostic(sid);
      if (diagData.question) {
        setCurrentQuestion(diagData.question);
        setAcknowledgment(diagData.acknowledgment || '');
        setQuestionIndex(0);
      } else if (diagnosticData?.questions?.length) {
        setCurrentQuestion(diagnosticData.questions[0]);
        setQuestionIndex(0);
      }
      setShowDiagnostic(true);
      setTimeout(scrollToEnd, 50);
    } catch (err) { setError('Failed to start diagnostic.'); }
    finally { setLoading(false); }
  };

  const handleDiagnosticAnswer = async (answer) => {
    setLoading(true);
    try {
      const sid = await ensureSession();
      const data = await api.submitAnswer(sid, questionIndex, answer);
      if (data.all_answered) {
        const precData = await api.getPrecisionQuestions(sid);
        if (precData.available && precData.questions?.length) {
          setPrecisionQuestions(precData.questions);
          setPrecisionIndex(0);
          setCurrentQuestion(precData.questions[0]);
          setAcknowledgment(data.acknowledgment || '');
          setShowPrecision(true);
        } else {
          setShowComplete(true);
        }
        setTimeout(scrollToEnd, 50);
      } else if (data.next_question) {
        setCurrentQuestion(data.next_question);
        setAcknowledgment(data.acknowledgment || '');
        setQuestionIndex((i) => i + 1);
      }
    } catch (err) { console.error('Diagnostic answer error:', err); setError(`Failed to submit answer: ${err.message}`); }
    finally { setLoading(false); }
  };

  const handlePrecisionAnswer = async (answer) => {
    setLoading(true);
    try {
      const sid = await ensureSession();
      await api.submitAnswer(sid, precisionIndex, answer);
      const nextIdx = precisionIndex + 1;
      if (nextIdx < precisionQuestions.length) {
        setPrecisionIndex(nextIdx);
        setCurrentQuestion(precisionQuestions[nextIdx]);
      } else {
        setShowComplete(true);
        setTimeout(scrollToEnd, 50);
      }
    } catch (err) { setError('Failed to submit answer.'); }
    finally { setLoading(false); }
  };

  const handleRestart = () => {
    setSelectedOutcome(null); setSelectedDomain(null); setSelectedTask(null);
    setShowUrlForm(false); setShowDeeperDive(false); setShowDiagnostic(false);
    setShowPrecision(false); setShowComplete(false); setEarlyTools([]);
    setDiagnosticData(null); setError(null); setHoveredOutcome(null);
    setHoveredDomain(null); setHoveredTask(null);
    sessionIdRef.current = null; sessionPromiseRef.current = null;
    if (canvasRef.current) canvasRef.current.scrollLeft = 0;
  };

  // ─── Arrow SVG (reusable single connector) ─────────────
  const Arrow = () => (
    <svg className="ik-arrow" viewBox="0 0 80 20">
      <defs>
        <marker id="ik-arrowhead" markerWidth="6" markerHeight="5" refX="5.5" refY="2.5" orient="auto" markerUnits="strokeWidth">
          <path d="M0,0 L6,2.5 L0,5" fill="none" stroke="rgba(255,255,255,0.9)" strokeWidth="1" />
        </marker>
      </defs>
      <line x1="4" y1="10" x2="68" y2="10"
        stroke="rgba(255,255,255,0.15)" strokeWidth="6" />
      <line x1="4" y1="10" x2="68" y2="10"
        stroke="rgba(255,255,255,0.75)" strokeWidth="1.5" markerEnd="url(#ik-arrowhead)" />
    </svg>
  );

  // ─── Branching arrows (one source → multiple targets) ─
  // Measure actual node heights: outcomes have subtext (~56px), domains/tasks single-line (~36px)
  // We use per-column heights for better alignment.
  const NODE_GAP = 8;

  const measureNodeH = (labels, hasSubtext) => {
    // padding: 10px top + 10px bottom = 20px
    // single line: font 12px * 1.3 line-height = ~16px → total ~36px
    // with subtext: +10px subtext + 2px margin = ~48px
    // multi-line text (>22 chars at 220px wide): ~52px
    return labels.map((label) => {
      const baseH = 20; // padding
      const labelLines = Math.ceil((label.length || 10) / 22);
      const labelH = labelLines * 16;
      const subtextH = hasSubtext ? 14 : 0;
      return baseH + labelH + subtextH;
    });
  };

  const colHeight = (nodeHeights) =>
    nodeHeights.reduce((sum, h) => sum + h, 0) + Math.max(0, nodeHeights.length - 1) * NODE_GAP;

  const nodeYCenters = (nodeHeights, totalH) => {
    const col = colHeight(nodeHeights);
    const offset = (totalH - col) / 2;
    let y = offset;
    return nodeHeights.map((h) => {
      const center = y + h / 2;
      y += h + NODE_GAP;
      return center;
    });
  };

  const BranchArrows = ({ count, sourceIndex, sourceTotal, srcLabels, srcHasSubtext, tgtLabels, tgtHasSubtext }) => {
    if (count <= 0) return null;

    const srcNodeH = srcLabels ? measureNodeH(srcLabels, srcHasSubtext) : Array(sourceTotal || 1).fill(46);
    const tgtNodeH = tgtLabels ? measureNodeH(tgtLabels, tgtHasSubtext) : Array(count).fill(46);

    const srcColH = colHeight(srcNodeH);
    const tgtColH = colHeight(tgtNodeH);
    const h = Math.max(srcColH, tgtColH, 50);
    const w = 100;
    const spineX = 35;          // x where the vertical spine sits
    const R = 10;               // max corner radius
    const endX = w - 10;        // leave room for arrowhead

    const srcCenters = nodeYCenters(srcNodeH, h);
    const tgtCenters = nodeYCenters(tgtNodeH, h);
    const srcY = srcCenters[sourceIndex !== undefined ? sourceIndex : 0];

    return (
      <svg className="ik-branch-arrows" viewBox={`0 0 ${w} ${h}`} style={{ height: `${h}px` }}>
        <defs>
          <marker id="ik-bhead" markerWidth="6" markerHeight="5" refX="5.5" refY="2.5" orient="auto" markerUnits="strokeWidth">
            <path d="M0,0 L6,2.5 L0,5" fill="none" stroke="rgba(255,255,255,0.9)" strokeWidth="1" />
          </marker>
        </defs>
        {tgtCenters.map((tgtY, i) => {
          const dy = tgtY - srcY;
          const absDy = Math.abs(dy);
          let d;

          if (absDy < 2) {
            // Nearly straight — just a horizontal line
            d = `M 0,${srcY} L ${endX},${tgtY}`;
          } else {
            const r = Math.min(R, absDy / 2);
            if (dy > 0) {
              // Target is below source
              d = [
                `M 0,${srcY}`,
                `L ${spineX - r},${srcY}`,
                `A ${r},${r} 0 0,1 ${spineX},${srcY + r}`,
                `L ${spineX},${tgtY - r}`,
                `A ${r},${r} 0 0,0 ${spineX + r},${tgtY}`,
                `L ${endX},${tgtY}`,
              ].join(' ');
            } else {
              // Target is above source
              d = [
                `M 0,${srcY}`,
                `L ${spineX - r},${srcY}`,
                `A ${r},${r} 0 0,0 ${spineX},${srcY - r}`,
                `L ${spineX},${tgtY + r}`,
                `A ${r},${r} 0 0,1 ${spineX + r},${tgtY}`,
                `L ${endX},${tgtY}`,
              ].join(' ');
            }
          }

          return (
            <g key={i}>
              <path d={d}
                fill="none" stroke="rgba(255,255,255,0.12)" strokeWidth="5"
                className="ik-branch-arrows__path" style={{ animationDelay: `${i * 40}ms` }}
              />
              <path d={d}
                fill="none" stroke="rgba(255,255,255,0.75)" strokeWidth="1.5"
                markerEnd="url(#ik-bhead)"
                className="ik-branch-arrows__path" style={{ animationDelay: `${i * 40}ms` }}
              />
            </g>
          );
        })}
      </svg>
    );
  };

  // ─── Scale questions pagination ───────────────────────
  const SCALE_PER_PAGE = 2;
  const scalePages = Math.ceil(scaleQuestions.length / SCALE_PER_PAGE);
  const currentScaleQs = scaleQuestions.slice(scalePage * SCALE_PER_PAGE, (scalePage + 1) * SCALE_PER_PAGE);
  const isScaleLastPage = scalePage === scalePages - 1;

  // ─── "Go back to Step 1" handler ───────────────────────
  const handleBackToStep1 = () => {
    setSelectedTask(null);
    setShowUrlForm(false);
    setShowDeeperDive(false);
    setShowDiagnostic(false);
    setShowPrecision(false);
    setShowComplete(false);
    setEarlyTools([]);
    setUrlValue('');
    setEmail('');
  };

  // ─── RENDER ───────────────────────────────────────────

  // ── DIAGNOSTIC SIGNALS VIEW ───────────────────────────
  if (showDiagnostic && currentQuestion) {
    return (
      <div className="ik-app">
        <Navbar />

        {/* Header */}
        <div className="ik-diag__header">
          <h1 className="ik-diag__title">Diagnostic Signals</h1>
          <p className="ik-diag__subtitle">Which of these symptoms are you currently experiencing</p>
        </div>

        {/* Question area */}
        <div className="ik-diag">
          <div className="ik-diag__card">
            <p className="ik-diag__question">{currentQuestion.question}</p>
            <div className="ik-diag__options">
              {currentQuestion.options.map((opt, i) => (
                <button key={i}
                  className={`ik-diag__option ${scaleAnswers[questionIndex] === opt ? 'ik-diag__option--selected' : ''}`}
                  onClick={() => {
                    setScaleAnswers((prev) => ({ ...prev, [questionIndex]: opt }));
                    handleDiagnosticAnswer(opt);
                  }}>
                  <span className="ik-diag__option-num">{String.fromCharCode(65 + i)}</span>
                  {opt}
                </button>
              ))}
            </div>
          </div>

          {/* Loading overlay */}
          {loading && <div className="ik-diag__loading">Thinking…</div>}
        </div>

        {/* Chat bar at bottom */}
        <div className="ik-diag-chat">
          <input className="ik-diag-chat__input" type="text" placeholder="Type your own answer or message Clawbot..."
            onKeyDown={(e) => {
              if (e.key === 'Enter' && e.target.value.trim()) {
                handleDiagnosticAnswer(e.target.value.trim());
                e.target.value = '';
              }
            }} />
          <button className="ik-diag-chat__btn"
            onClick={(e) => {
              const input = e.currentTarget.previousElementSibling;
              if (input.value.trim()) {
                handleDiagnosticAnswer(input.value.trim());
                input.value = '';
              }
            }}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M5 12h14M12 5l7 7-7 7"/></svg>
          </button>
        </div>

        {error && (
          <div className="ik-app__error" onClick={() => setError(null)}>
            <span>{error}</span>
            <button className="ik-app__error-close">&times;</button>
          </div>
        )}
      </div>
    );
  }

  // ── DEEPER DIVE (Scale Questions) VIEW ────────────────
  if (showDeeperDive) {
    return (
      <div className="ik-app">
        <Navbar />
        <div className="ik-dive">
          <h1 className="ik-dive__title">Business Context</h1>
          <p className="ik-dive__subtitle">Help us understand your situation to give better recommendations</p>

          <div className="ik-dive__body">
            {/* Dashed arrow */}
            <svg className="ik-dive__arrow" viewBox="0 0 200 20">
              <defs>
                <marker id="ik-dd-head" markerWidth="6" markerHeight="5" refX="5.5" refY="2.5" orient="auto">
                  <path d="M0,0 L6,2.5 L0,5" fill="none" stroke="rgba(255,255,255,0.6)" strokeWidth="1" />
                </marker>
              </defs>
              <line x1="0" y1="10" x2="190" y2="10"
                stroke="rgba(255,255,255,0.3)" strokeWidth="1.5" strokeDasharray="6,4"
                markerEnd="url(#ik-dd-head)" />
            </svg>

            {/* 2 question cards side by side */}
            {scaleQuestions.length > 0 ? (
              <div className="ik-dive__cards">
                {currentScaleQs.map((q, qi) => {
                  const qIdx = scalePage * SCALE_PER_PAGE + qi;
                  return (
                    <div key={qIdx} className="ik-dive__card">
                      <p className="ik-dive__question">{q.question}</p>
                      <div className="ik-dive__options">
                        {q.options.map((opt, oi) => (
                          <button key={oi}
                            className={`ik-dive__option ${
                              (q.multi_select
                                ? (scaleAnswers[qIdx] || []).includes(opt)
                                : scaleAnswers[qIdx] === opt)
                                ? 'ik-dive__option--sel' : ''
                            }`}
                            onClick={() => handleScaleSelect(qIdx, opt, q.multi_select)}>
                            {opt}
                          </button>
                        ))}
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : (
              <div className="ik-dive__cards">
                <div className="ik-dive__card">
                  <p className="ik-dive__question">Loading questions…</p>
                </div>
              </div>
            )}
          </div>

          {/* Nav row pinned at bottom */}
          <div className="ik-dive__nav">
            {scalePage > 0 && (
              <button className="ik-dive__nav-btn" onClick={() => setScalePage((p) => p - 1)}>
                &lsaquo; Previous
              </button>
            )}
            <div style={{ flex: 1 }} />
            <span className="ik-dive__page">{scalePage + 1} / {scalePages || 1}</span>
            <div style={{ flex: 1 }} />
            {!isScaleLastPage ? (
              <button className="ik-dive__nav-btn ik-dive__nav-btn--primary"
                onClick={() => setScalePage((p) => p + 1)}>
                Next &rsaquo;
              </button>
            ) : (
              <button className="ik-dive__nav-btn ik-dive__nav-btn--primary"
                onClick={handleScaleSubmit} disabled={loading}>
                {loading ? 'Processing…' : 'Continue'}
              </button>
            )}
          </div>
        </div>

        {error && (
          <div className="ik-app__error" onClick={() => setError(null)}>
            <span>{error}</span>
            <button className="ik-app__error-close">&times;</button>
          </div>
        )}
      </div>
    );
  }

  // ── POST-Q3 FULL-PAGE VIEW ────────────────────────────
  if (showUrlForm) {
    return (
      <div className="ik-app">
        <Navbar />

        <div className="ik-s2">
          {/* Hero */}
          <h1 className="ik-s2__title">
            Get Business <span className="ik-s2__accent ik-s2__accent--orange">Audit</span> report and{' '}
            <span className="ik-s2__accent ik-s2__accent--purple">Playbook</span>
          </h1>

          {/* Domain node → arrow → URL form */}
          <div className="ik-s2__flow">
            <div className="ik-s2__node">
              <FlowNode label={selectedDomain} variant="light" active />
            </div>

            <svg className="ik-s2__arrow" viewBox="0 0 120 20">
              <defs>
                <marker id="ik-s2-head" markerWidth="6" markerHeight="5" refX="5.5" refY="2.5" orient="auto">
                  <path d="M0,0 L6,2.5 L0,5" fill="none" stroke="rgba(255,255,255,0.5)" strokeWidth="1" />
                </marker>
              </defs>
              <line x1="4" y1="10" x2="110" y2="10"
                stroke="rgba(255,255,255,0.3)" strokeWidth="1.5" markerEnd="url(#ik-s2-head)" />
            </svg>

            <div className="ik-s2__form-wrap">
              <div className="ik-inline-form">
                <p className="ik-inline-form__hint">Enter your business website or Google Business Profile URL</p>
                <form onSubmit={handleUrlSubmit}>
                  <input className="ik-inline-form__input" type="text"
                    placeholder="yourcompany.com or Google Business Profile URL"
                    value={urlValue} onChange={(e) => setUrlValue(e.target.value)} autoFocus />
                  <button className="ik-inline-form__submit" type="submit"
                    disabled={urlSubmitting || !urlValue.trim()}>
                    {urlSubmitting ? 'Analyzing...' : 'Analyze My Business'}
                  </button>
                </form>
                <button className="ik-inline-form__skip" onClick={handleUrlSkip} disabled={urlSubmitting}>
                  Skip — without URLs, we'll give general recommendations
                </button>
              </div>
            </div>
          </div>

          {/* Tools carousel */}
          {earlyTools.length > 0 && (() => {
            const totalPages = Math.ceil(earlyTools.length / TOOLS_PER_PAGE);
            const pageTools = earlyTools.slice(toolPage * TOOLS_PER_PAGE, (toolPage + 1) * TOOLS_PER_PAGE);
            return (
              <div className="ik-s2__tools">
                <h2 className="ik-s2__tools-heading">Best Tools For You</h2>
                <div className="ik-carousel">
                  <button className="ik-carousel__btn ik-carousel__btn--left"
                    onClick={() => setToolPage((p) => p - 1)}
                    disabled={toolPage === 0}>
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M15 18l-6-6 6-6"/></svg>
                  </button>
                  <div className="ik-carousel__track">
                    {pageTools.map((tool, i) => (
                      <ToolCard key={toolPage * TOOLS_PER_PAGE + i} name={tool.name} rating={tool.rating}
                        description={tool.description} bullets={tool.bullets}
                        tag={tool.tag} url={tool.url} />
                    ))}
                  </div>
                  <button className="ik-carousel__btn ik-carousel__btn--right"
                    onClick={() => setToolPage((p) => p + 1)}
                    disabled={toolPage >= totalPages - 1}>
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M9 18l6-6-6-6"/></svg>
                  </button>
                </div>
                <div className="ik-carousel__dots">
                  {Array.from({ length: totalPages }).map((_, i) => (
                    <button key={i}
                      className={`ik-carousel__dot ${i === toolPage ? 'ik-carousel__dot--active' : ''}`}
                      onClick={() => setToolPage(i)} />
                  ))}
                </div>
              </div>
            );
          })()}

          {/* Back to Step 1 */}
          <button className="ik-s2__back" onClick={handleBackToStep1}>
            &lsaquo; Step 1
          </button>
        </div>

        {/* Error toast */}
        {error && (
          <div className="ik-app__error" onClick={() => setError(null)}>
            <span>{error}</span>
            <button className="ik-app__error-close">&times;</button>
          </div>
        )}
      </div>
    );
  }

  // ── STEP 1: HORIZONTAL JOURNEY CANVAS ─────────────────

  return (
    <div className="ik-app">
      {/* Screensaver preview overlay */}
      {showScreensaver && (
        <ScreensaverPreview onDismiss={() => setShowScreensaver(false)} />
      )}

      <Navbar />

      {/* Hero title — fixed at top */}
      <div className="ik-hero">
        <h1 className="ik-hero__title">
          Deploy 100+ <span className="ik-hero__accent">AI Agents</span> to Grow Your Business
        </h1>
        <p className="ik-hero__sub">Select what Matters most to you right now</p>
      </div>

      {/* Horizontal scrolling canvas */}
      <div className="ik-canvas" ref={canvasRef}>
        <div className={`ik-canvas__track ${selectedOutcome ? 'ik-canvas__track--started' : ''}`}>

          {/* ── COLUMN 0: Outcomes ───────────────────── */}
          <div className={`ik-col ${selectedOutcome ? 'ik-col--locked' : ''}`}>
            <div className="ik-col__nodes">
              {outcomeOptions.map((opt) => {
                const isSelected = selectedOutcome?.id === opt.id;
                const isHovered = hoveredOutcome === opt.id;
                const isLocked = !!selectedOutcome;
                return (
                  <div key={opt.id}
                    className={`ik-col__node-wrap ${isLocked && !isSelected ? 'ik-col__node-wrap--dimmed' : ''}`}
                    onMouseEnter={() => !isLocked && setHoveredOutcome(opt.id)}
                    onMouseLeave={() => setHoveredOutcome(null)}>
                    <FlowNode
                      label={opt.text} subtext={opt.subtext}
                      variant={isSelected ? 'light' : 'dark'}
                      active={isSelected}
                      onClick={isLocked ? undefined : () => handleOutcomeClick(opt)}
                    />
                    {/* Hover preview: show domains */}
                    {isHovered && !isLocked && OUTCOME_DOMAINS[opt.id] && (
                      <div className="ik-hover-preview">
                        {OUTCOME_DOMAINS[opt.id].map((d) => (
                          <div key={d} className="ik-hover-preview__item">{d}</div>
                        ))}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>

          {/* ── ARROW: Outcome → Domains ─────────────── */}
          {selectedOutcome && (
            <>
              <div className="ik-col ik-col--arrows">
                <BranchArrows count={domains.length}
                  sourceIndex={outcomeOptions.findIndex(o => o.id === selectedOutcome.id)}
                  sourceTotal={outcomeOptions.length}
                  srcLabels={outcomeOptions.map(o => o.text)}
                  srcHasSubtext={true}
                  tgtLabels={domains}
                  tgtHasSubtext={false} />
              </div>

              {/* ── COLUMN 1: Domains ────────────────── */}
              <div className={`ik-col ik-col--anim ${selectedDomain ? 'ik-col--locked' : ''}`}>
                <div className="ik-col__nodes">
                  {domains.map((d) => {
                    const isSel = selectedDomain === d;
                    const isHov = hoveredDomain === d;
                    const isLocked = !!selectedDomain;
                    return (
                      <div key={d}
                        className={`ik-col__node-wrap ${isLocked && !isSel ? 'ik-col__node-wrap--dimmed' : ''}`}
                        onMouseEnter={() => !isLocked && setHoveredDomain(d)}
                        onMouseLeave={() => setHoveredDomain(null)}>
                        <FlowNode label={d} variant={isSel ? 'light' : 'dark'} active={isSel}
                          onClick={isLocked ? undefined : () => handleDomainClick(d)} />
                        {isHov && !isLocked && DOMAIN_TASKS[d] && (
                          <div className="ik-hover-preview">
                            {DOMAIN_TASKS[d].slice(0, 5).map((t) => (
                              <div key={t} className="ik-hover-preview__item">{t}</div>
                            ))}
                            {DOMAIN_TASKS[d].length > 5 && (
                              <div className="ik-hover-preview__more">+{DOMAIN_TASKS[d].length - 5} more</div>
                            )}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            </>
          )}

          {/* ── ARROW: Domain → Tasks ────────────────── */}
          {selectedDomain && (
            <>
              <div className="ik-col ik-col--arrows">
                <BranchArrows count={tasks.length}
                  sourceIndex={domains.indexOf(selectedDomain)}
                  sourceTotal={domains.length}
                  srcLabels={domains}
                  srcHasSubtext={false}
                  tgtLabels={tasks}
                  tgtHasSubtext={false} />
              </div>

              {/* ── COLUMN 2: Tasks ──────────────────── */}
              <div className={`ik-col ik-col--anim ${selectedTask ? 'ik-col--locked' : ''}`}>
                <div className="ik-col__nodes">
                  {tasks.map((t) => {
                    const isSel = selectedTask === t;
                    const isLocked = !!selectedTask;
                    return (
                      <div key={t}
                        className={`ik-col__node-wrap ${isLocked && !isSel ? 'ik-col__node-wrap--dimmed' : ''}`}
                        onMouseEnter={() => !isLocked && setHoveredTask(t)}
                        onMouseLeave={() => setHoveredTask(null)}>
                        <FlowNode label={t} variant={isSel ? 'light' : 'dark'} active={isSel}
                          onClick={isLocked ? undefined : () => handleTaskClick(t)} />
                      </div>
                    );
                  })}
                </div>
              </div>
            </>
          )}

          {/* ── Post-Q3 stages rendered in full-page view above ── */}

          {/* End spacer so last column can center */}
          <div className="ik-col ik-col--spacer" />
        </div>
      </div>

      {/* Error toast */}
      {error && (
        <div className="ik-app__error" onClick={() => setError(null)}>
          <span>{error}</span>
          <button className="ik-app__error-close">&times;</button>
        </div>
      )}
    </div>
  );
}
