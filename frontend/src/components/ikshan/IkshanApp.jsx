import { useState, useRef, useCallback, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import Navbar from './components/Navbar';
import FlowNode from './components/FlowNode';
import BranchArrows from './components/BranchArrows';
import StageLayout from './components/StageLayout';
import ScreensaverPreview from './stages/ScreensaverPreview';
import UrlStage from './stages/UrlStage';
import DeeperDiveStage from './stages/DeeperDiveStage';
import DiagnosticStage from './stages/DiagnosticStage';
import { outcomeOptions, OUTCOME_DOMAINS, DOMAIN_TASKS } from './constants';
import { getToolsForSelection } from './toolService';
import * as api from './api';
import { coreApi } from '../../api/services/core';
import './IkshanApp.css';

const IDLE_TIMEOUT = 10_000;
const RESEARCH_ORCHESTRATOR_AGENT_ID = 'business-research';
const phase2Path = (path) => `/phase2/${path}`;

export default function IkshanApp() {
  const navigate = useNavigate();
  const canvasRef = useRef(null);
  const [showScreensaver, setShowScreensaver] = useState(true);
  const idleTimerRef = useRef(null);

  // ─── Idle timer → show screensaver ────────────────────
  useEffect(() => {
    if (showScreensaver) return;
    const resetIdle = () => {
      clearTimeout(idleTimerRef.current);
      idleTimerRef.current = setTimeout(() => setShowScreensaver(true), IDLE_TIMEOUT);
    };
    resetIdle();
    const events = ['mousemove', 'mousedown', 'keydown', 'touchstart', 'wheel', 'scroll'];
    events.forEach((e) => window.addEventListener(e, resetIdle));
    return () => {
      clearTimeout(idleTimerRef.current);
      events.forEach((e) => window.removeEventListener(e, resetIdle));
    };
  }, [showScreensaver]);

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

  // URL stage
  const [showUrlForm, setShowUrlForm] = useState(false);
  const [toolPage, setToolPage] = useState(0);
  const [urlValue, setUrlValue] = useState('');
  const [gbpValue, setGbpValue] = useState('');
  const [urlTab, setUrlTab] = useState('website');
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
  const [loading, setLoading] = useState(false);

  // Precision
  const [showPrecision, setShowPrecision] = useState(false);
  const [precisionQuestions, setPrecisionQuestions] = useState([]);
  const [precisionIndex, setPrecisionIndex] = useState(0);

  // Complete
  const [showComplete, setShowComplete] = useState(false);
  const [error, setError] = useState(null);

  // Crawl
  const [crawlStatus, setCrawlStatus] = useState(''); // '', 'in_progress', 'complete', 'failed', 'skipped'
  const crawlPollRef = useRef(null);
  const crawlSummaryRef = useRef(null);

  // Playbook
  const [showPlaybook, setShowPlaybook] = useState(false);
  const [playbookStreaming, setPlaybookStreaming] = useState(false);
  const [playbookText, setPlaybookText] = useState('');
  const [playbookDone, setPlaybookDone] = useState(false);
  const [playbookResult, setPlaybookResult] = useState(null);
  const [gapQuestions, setGapQuestions] = useState([]);
  const [gapAnswers, setGapAnswers] = useState({});
  const [showGapQuestions, setShowGapQuestions] = useState(false);

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

  const scrollToEnd = useCallback(() => {
    const el = canvasRef.current;
    if (!el) return;
    requestAnimationFrame(() => {
      el.scrollTo({ left: el.scrollWidth - el.clientWidth, behavior: 'smooth' });
    });
  }, []);

  // ─── Crawl polling ────────────────────────────────────
  const startCrawlPolling = useCallback(() => {
    if (crawlPollRef.current) clearInterval(crawlPollRef.current);
    crawlPollRef.current = setInterval(async () => {
      try {
        const sid = sessionIdRef.current;
        if (!sid) return;
        const data = await api.getCrawlStatus(sid);
        if (data.crawl_status === 'complete' || data.crawl_status === 'failed') {
          setCrawlStatus(data.crawl_status);
          clearInterval(crawlPollRef.current);
          crawlPollRef.current = null;
          if (data.crawl_status === 'complete' && data.crawl_summary) {
            crawlSummaryRef.current = data.crawl_summary;
          }
        }
      } catch { /* silent */ }
    }, 3000);
  }, []);

  // Cleanup poll on unmount
  useEffect(() => () => { if (crawlPollRef.current) clearInterval(crawlPollRef.current); }, []);

  // Wait for crawl to finish (used before playbook)
  const waitForCrawl = useCallback(() => new Promise((resolve) => {
    if (!crawlPollRef.current) { resolve(); return; }
    const check = setInterval(() => {
      if (!crawlPollRef.current) { clearInterval(check); resolve(); }
    }, 500);
  }), []);

  // ─── Derived data ─────────────────────────────────────
  const domains = selectedOutcome ? (OUTCOME_DOMAINS[selectedOutcome.id] || []) : [];
  const tasks = selectedDomain ? (DOMAIN_TASKS[selectedDomain] || []) : [];

  // ─── Helpers to clear downstream state ────────────────
  const clearPostTask = () => {
    setShowUrlForm(false);
    setShowDeeperDive(false);
    setShowDiagnostic(false);
    setShowPrecision(false);
    setShowComplete(false);
    setEarlyTools([]);
  };

  // ─── Handlers ─────────────────────────────────────────

  const handleOutcomeClick = async (outcome) => {
    setSelectedOutcome(outcome);
    setSelectedDomain(null);
    setSelectedTask(null);
    clearPostTask();
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
    clearPostTask();
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
    setToolPage(0);
    setHoveredTask(null);
    setTimeout(scrollToEnd, 50);

    // Local tool lookup — no backend call
    const { tools } = getToolsForSelection(selectedOutcome.id, selectedDomain, task);
    if (tools.length > 0) {
      setEarlyTools(tools.map((t) => {
        const rawDesc = t.best_use_case || t.description || '';
        const desc = rawDesc.length > 120 ? rawDesc.slice(0, 117) + '...' : rawDesc;
        let bullets = [];
        if (t.key_pros) {
          const raw = Array.isArray(t.key_pros)
            ? t.key_pros
            : t.key_pros.split('\n').map(s => s.replace(/^[•\-\s]+/, '').trim()).filter(Boolean);
          bullets = raw.slice(0, 3).map(b => b.length > 70 ? b.slice(0, 67) + '...' : b);
        }
        return { name: t.name, rating: t.rating || null, description: desc, bullets, tag: t.category || 'RECOMMENDED', url: t.url };
      }));
    } else {
      setEarlyTools([]);
    }

    // Fire-and-forget backend task submission (for session tracking)
    try {
      const sid = await ensureSession();
      api.submitTask(sid, task).then((data) => setDiagnosticData(data)).catch(() => {});
    } catch (err) { console.warn('Task submit:', err.message); }
    setTimeout(scrollToEnd, 100);
  };

  const handleUrlSubmit = async (e) => {
    e.preventDefault();
    if (!urlValue.trim() && !gbpValue.trim()) return;
    setUrlSubmitting(true);
    try {
      const sid = await ensureSession();
      if (urlValue.trim()) {
        let finalUrl = urlValue.trim();
        if (!/^https?:\/\//i.test(finalUrl)) finalUrl = `https://${finalUrl}`;
        const res = await api.submitUrl(sid, finalUrl);
        if (res?.crawl_started) { setCrawlStatus('in_progress'); startCrawlPolling(); }
      }
      if (gbpValue.trim()) {
        let finalGbp = gbpValue.trim();
        if (!/^https?:\/\//i.test(finalGbp)) finalGbp = `https://${finalGbp}`;
        await api.submitUrl(sid, finalGbp);
      }
      await moveToScaleQuestions();
    } catch (err) { setError('Failed to submit URL.'); }
    finally { setUrlSubmitting(false); }
  };

  const handleUrlSkip = async () => {
    setUrlSubmitting(true);
    try {
      const sid = await ensureSession();
      await api.skipUrl(sid);
      setCrawlStatus('skipped');
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
          setShowPrecision(true);
          setTimeout(scrollToEnd, 50);
        } else {
          handleStartPlaybook();
        }
      } else if (data.next_question) {
        setCurrentQuestion(data.next_question);
        setQuestionIndex((i) => i + 1);
      }
    } catch (err) { setError(`Failed to submit answer: ${err.message}`); }
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
        handleStartPlaybook();
      }
    } catch (err) { setError('Failed to submit answer.'); }
    finally { setLoading(false); }
  };

  const getWebsiteUrl = () => {
    let u = (urlValue || '').trim();
    if (u && !/^https?:\/\//i.test(u)) u = `https://${u}`;
    return u;
  };

  /** Phase 2 uses JWT for identity; Phase 1 agent session is not required. URL comes from URL stage. */
  const handleDeepAnalysis = () => {
    const url = getWebsiteUrl();
    const userLine = url ? `${url}\n\nDo deep analysis.` : '';
    navigate(phase2Path('new'), {
      state: {
        agentId: RESEARCH_ORCHESTRATOR_AGENT_ID,
        ...(userLine ? { initialMessage: userLine } : {}),
      },
    });
  };

  const handleBackToStep1 = () => {
    setSelectedTask(null);
    clearPostTask();
    setUrlValue(''); setGbpValue('');
  };

  const clearError = () => setError(null);

  // ─── Playbook helpers ─────────────────────────────────
  const streamPlaybook = async (sid) => {
    await coreApi.playbookGenerateStream({ session_id: sid }, {
      onToken: (token) => setPlaybookText((t) => t + token),
      onDone: (result) => { setPlaybookResult(result); setPlaybookDone(true); setPlaybookStreaming(false); },
      onError: (msg) => { setError(msg); setPlaybookStreaming(false); },
    });
  };

  const handleStartPlaybook = async () => {
    setShowPlaybook(true);
    setPlaybookStreaming(true);
    setPlaybookText('');
    setPlaybookDone(false);
    setPlaybookResult(null);
    setTimeout(scrollToEnd, 50);
    try {
      const sid = await ensureSession();
      // Wait for background crawl to finish before generating playbook
      await waitForCrawl();
      const startData = await coreApi.playbookStart({ session_id: sid });
      if (startData.gap_questions?.length) {
        setGapQuestions(startData.gap_questions_parsed || startData.gap_questions);
        setShowGapQuestions(true);
        setPlaybookStreaming(false);
        return;
      }
      await streamPlaybook(sid);
    } catch (err) { setError('Failed to start playbook.'); setPlaybookStreaming(false); }
  };

  const handleGapSubmit = async () => {
    setShowGapQuestions(false);
    setPlaybookStreaming(true);
    try {
      const sid = await ensureSession();
      const answersStr = gapQuestions.map((q, i) => {
        const qNum = (typeof q === 'object' && q.id) ? q.id : `Q${i + 1}`;
        return `${qNum}-${gapAnswers[i] || ''}`;
      }).join(', ');
      await coreApi.playbookGapAnswers({ session_id: sid, answers: answersStr });
      await streamPlaybook(sid);
    } catch (err) { setError('Failed to submit answers.'); setPlaybookStreaming(false); }
  };

  // ─── RENDER: PLAYBOOK ─────────────────────────────────
  if (showPlaybook) {
    return (
      <StageLayout error={error} onClearError={clearError}>
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', padding: '24px 32px', overflow: 'hidden', minHeight: 0 }}>
          <h1 style={{ fontSize: 'clamp(20px,2.5vw,32px)', fontWeight: 800, margin: '0 0 20px', textAlign: 'center' }}>
            {showGapQuestions ? 'A Few More Questions' : playbookDone ? 'Your Playbook' : 'Generating Your Playbook…'}
          </h1>

          {/* Gap questions panel */}
          {showGapQuestions && (
            <div style={{ maxWidth: 640, margin: '0 auto', width: '100%', display: 'flex', flexDirection: 'column', gap: 20 }}>
              {gapQuestions.map((q, i) => {
                const qLabel = typeof q === 'string' ? q : q.question;
                const opts = typeof q === 'object' && Array.isArray(q.options) ? q.options : [];
                return (
                  <div key={i} style={{ padding: '16px 20px', borderRadius: 12, border: '1px solid rgba(255,255,255,0.12)', background: 'rgba(255,255,255,0.03)' }}>
                    <p style={{ fontSize: 14, fontWeight: 600, margin: '0 0 12px', color: 'rgba(255,255,255,0.9)' }}>{qLabel}</p>
                    {opts.length > 0 ? (
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                        {opts.map((opt, oi) => {
                          const optKey = opt.match(/^([A-E])\)/)?.[1] || String.fromCharCode(65 + oi);
                          const selected = gapAnswers[i] === optKey;
                          return (
                            <button
                              key={oi}
                              onClick={() => setGapAnswers((prev) => ({ ...prev, [i]: optKey }))}
                              style={{
                                textAlign: 'left', padding: '10px 14px', borderRadius: 8, cursor: 'pointer',
                                fontSize: 13, fontWeight: selected ? 700 : 400,
                                border: selected ? '1.5px solid #857BFF' : '1px solid rgba(255,255,255,0.12)',
                                background: selected ? 'rgba(133,123,255,0.18)' : 'rgba(255,255,255,0.04)',
                                color: selected ? '#fff' : 'rgba(255,255,255,0.75)',
                                transition: 'all 0.15s',
                              }}
                            >
                              {opt}
                            </button>
                          );
                        })}
                      </div>
                    ) : (
                      <textarea
                        rows={3}
                        placeholder="Your answer…"
                        value={gapAnswers[i] || ''}
                        onChange={(e) => setGapAnswers((prev) => ({ ...prev, [i]: e.target.value }))}
                        style={{ width: '100%', padding: '10px 14px', borderRadius: 8, border: '1px solid rgba(255,255,255,0.1)', background: 'rgba(255,255,255,0.05)', color: '#fff', fontSize: 13, resize: 'vertical', outline: 'none', boxSizing: 'border-box' }}
                      />
                    )}
                  </div>
                );
              })}
              <button
                onClick={handleGapSubmit}
                disabled={gapQuestions.length > 0 && !gapQuestions.every((_, i) => gapAnswers[i])}
                style={{ padding: '12px', borderRadius: 10, border: 'none', background: 'linear-gradient(90deg,#857BFF,#BF69A2)', color: '#fff', fontWeight: 800, fontSize: 14, cursor: gapQuestions.every((_, i) => gapAnswers[i]) ? 'pointer' : 'not-allowed', opacity: gapQuestions.every((_, i) => gapAnswers[i]) ? 1 : 0.5 }}
              >
                Generate Playbook
              </button>
            </div>
          )}

          {/* Streaming / final playbook text */}
          {!showGapQuestions && (
            <div style={{ flex: 1, overflow: 'auto', maxWidth: 800, margin: '0 auto', width: '100%' }}>
              {playbookStreaming && !playbookText && (
                <div style={{ color: 'rgba(255,255,255,0.4)', fontSize: 14, textAlign: 'center', paddingTop: 40 }}>Thinking…</div>
              )}
              {playbookText && (
                <pre style={{ whiteSpace: 'pre-wrap', fontFamily: 'inherit', fontSize: 14, lineHeight: 1.8, color: 'rgba(255,255,255,0.85)', margin: 0 }}>
                  {playbookText}
                  {playbookStreaming && <span style={{ opacity: 0.5 }}>▍</span>}
                </pre>
              )}
              {playbookDone && playbookResult?.website_audit && (
                <div style={{ marginTop: 32, padding: '20px', borderRadius: 12, border: '1px solid rgba(255,255,255,0.1)', background: 'rgba(255,255,255,0.03)' }}>
                  <h3 style={{ fontSize: 16, fontWeight: 700, margin: '0 0 10px', color: '#a882ff' }}>Website Audit</h3>
                  <pre style={{ whiteSpace: 'pre-wrap', fontFamily: 'inherit', fontSize: 13, lineHeight: 1.7, color: 'rgba(255,255,255,0.7)', margin: 0 }}>{playbookResult.website_audit}</pre>
                </div>
              )}
              {playbookDone && (
                <button onClick={handleDeepAnalysis} style={{ marginTop: 32, padding: '12px 32px', borderRadius: 10, border: 'none', background: 'linear-gradient(135deg,#6366f1,#8b5cf6)', color: '#fff', fontWeight: 700, fontSize: 15, cursor: 'pointer' }}>
                  Do Deep Analysis
                </button>
              )}
            </div>
          )}
        </div>
      </StageLayout>
    );
  }

  // ─── RENDER: COMPLETE ──────────────────────────────────
  if (showComplete) {
    return (
      <StageLayout error={error} onClearError={clearError}>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', minHeight: '60vh', gap: '24px', textAlign: 'center', color: '#fff' }}>
          <div style={{ fontSize: '48px' }}>&#10003;</div>
          <h1 style={{ fontSize: '28px', fontWeight: 800, letterSpacing: '-0.5px' }}>Analysis Complete</h1>
          <p style={{ fontSize: '15px', color: 'rgba(255,255,255,0.6)', maxWidth: '480px', lineHeight: 1.7 }}>
            Your diagnostic journey is complete. Based on your answers, we have enough context to generate your personalized playbook and tool recommendations.
          </p>
          <button
            onClick={handleDeepAnalysis}
            style={{ marginTop: '12px', padding: '12px 32px', borderRadius: '10px', background: 'linear-gradient(135deg, #6366f1, #8b5cf6)', color: '#fff', border: 'none', fontWeight: 700, fontSize: '15px', cursor: 'pointer' }}
          >
            Do Deep Analysis
          </button>
        </div>
      </StageLayout>
    );
  }

  // ─── RENDER: DIAGNOSTIC ───────────────────────────────
  if (showDiagnostic && currentQuestion) {
    const answerHandler = showPrecision ? handlePrecisionAnswer : handleDiagnosticAnswer;
    return (
      <StageLayout error={error} onClearError={clearError}>
        <DiagnosticStage
          currentQuestion={currentQuestion}
          questionIndex={showPrecision ? precisionIndex : questionIndex}
          scaleAnswers={scaleAnswers}
          onAnswer={(opt) => {
            setScaleAnswers((prev) => ({ ...prev, [questionIndex]: opt }));
            answerHandler(opt);
          }}
          loading={loading}
        />
      </StageLayout>
    );
  }

  // ─── RENDER: DEEPER DIVE ──────────────────────────────
  if (showDeeperDive) {
    return (
      <StageLayout error={error} onClearError={clearError}>
        <DeeperDiveStage
          scaleQuestions={scaleQuestions}
          scaleAnswers={scaleAnswers}
          onSelect={handleScaleSelect}
          scalePage={scalePage}
          onPageChange={setScalePage}
          onSubmit={handleScaleSubmit}
          loading={loading}
        />
      </StageLayout>
    );
  }

  // ─── RENDER: URL STAGE ────────────────────────────────
  if (showUrlForm) {
    return (
      <StageLayout error={error} onClearError={clearError}>
        <UrlStage
          selectedDomain={selectedDomain}
          urlValue={urlValue}
          gbpValue={gbpValue}
          onUrlChange={setUrlValue}
          onGbpChange={setGbpValue}
          urlTab={urlTab}
          onTabChange={setUrlTab}
          onSubmit={handleUrlSubmit}
          onSkip={handleUrlSkip}
          urlSubmitting={urlSubmitting}
          earlyTools={earlyTools}
          toolPage={toolPage}
          onToolPageChange={setToolPage}
          onBack={handleBackToStep1}
        />
      </StageLayout>
    );
  }

  // ─── RENDER: HORIZONTAL JOURNEY CANVAS ────────────────
  return (
    <div className="ik-app">
      <ScreensaverPreview active={showScreensaver} onDismiss={(outcome) => {
        setShowScreensaver(false);
        if (outcome) handleOutcomeClick(outcome);
      }} />

      <Navbar />

      <div className="ik-hero">
        <h1 className="ik-hero__title">
          Deploy 100+ <span className="ik-hero__accent">AI Agents</span> to Grow Your Business
        </h1>
        <p className="ik-hero__sub">Select what Matters most to you right now</p>
      </div>

      <div className="ik-canvas" ref={canvasRef}>
        <div className={`ik-canvas__track ${selectedOutcome ? 'ik-canvas__track--started' : ''}`}>

          {/* Column 0: Outcomes */}
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
                    {isHovered && !isLocked && OUTCOME_DOMAINS[opt.id] && (
                      <div className="ik-hover-branch">
                        <div className="ik-hover-branch__arrows">
                          <BranchArrows
                            count={OUTCOME_DOMAINS[opt.id].length}
                            sourceIndex={0}
                            srcLabels={[opt.text]}
                            srcHasSubtext
                            tgtLabels={OUTCOME_DOMAINS[opt.id]}
                          />
                        </div>
                        <div className="ik-hover-branch__nodes">
                          {OUTCOME_DOMAINS[opt.id].map((d) => (
                            <FlowNode key={d} label={d} variant="dark" />
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>

          {/* Arrows + Domains */}
          {selectedOutcome && (
            <>
              <div className="ik-col ik-col--arrows">
                <BranchArrows count={domains.length}
                  sourceIndex={outcomeOptions.findIndex(o => o.id === selectedOutcome.id)}
                  srcLabels={outcomeOptions.map(o => o.text)}
                  srcHasSubtext
                  tgtLabels={domains} />
              </div>

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
                          <div className="ik-hover-branch">
                            <div className="ik-hover-branch__arrows">
                              <BranchArrows
                                count={DOMAIN_TASKS[d].length}
                                sourceIndex={0}
                                srcLabels={[d]}
                                tgtLabels={DOMAIN_TASKS[d]}
                              />
                            </div>
                            <div className="ik-hover-branch__nodes">
                              {DOMAIN_TASKS[d].map((t) => (
                                <FlowNode key={t} label={t} variant="dark" />
                              ))}
                            </div>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            </>
          )}

          {/* Arrows + Tasks */}
          {selectedDomain && (
            <>
              {tasks.length <= 6 ? (
                /* ── Normal single-column layout ── */
                <>
                  <div className="ik-col ik-col--arrows">
                    <BranchArrows count={tasks.length}
                      sourceIndex={domains.indexOf(selectedDomain)}
                      srcLabels={domains}
                      tgtLabels={tasks} />
                  </div>

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
              ) : (
                /* ── Zigzag two-column layout for 7+ tasks ── */
                <>
                  {(() => {
                    const leftCol = tasks.filter((_, i) => i % 2 === 0);
                    const rightCol = tasks.filter((_, i) => i % 2 === 1);
                    return (
                      <>
                        <div className="ik-col ik-col--arrows">
                          <BranchArrows count={leftCol.length}
                            sourceIndex={domains.indexOf(selectedDomain)}
                            srcLabels={domains}
                            tgtLabels={leftCol} />
                        </div>

                        <div className={`ik-col ik-col--anim ${selectedTask ? 'ik-col--locked' : ''}`}>
                          <div className="ik-col__nodes">
                            {leftCol.map((t) => {
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

                        <div className={`ik-col ik-col--anim ik-col--zigzag-right ${selectedTask ? 'ik-col--locked' : ''}`}>
                          <div className="ik-col__nodes ik-col__nodes--staggered">
                            {rightCol.map((t) => {
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
                    );
                  })()}
                </>
              )}
            </>
          )}

          <div className="ik-col ik-col--spacer" />
        </div>
      </div>

      {error && (
        <div className="ik-app__error" onClick={clearError}>
          <span>{error}</span>
          <button className="ik-app__error-close">&times;</button>
        </div>
      )}
    </div>
  );
}
