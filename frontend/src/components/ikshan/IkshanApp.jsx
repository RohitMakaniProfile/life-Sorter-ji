import { useState, useRef, useCallback, useEffect } from 'react';
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
import './IkshanApp.css';

const IDLE_TIMEOUT = 10_000;

// ★ DEMO MODE — set to true to skip LLM calls and see the full UI with dummy data
const DEMO_MODE = true;

const DEMO_DIAGNOSTIC_QUESTIONS = [
  { question: 'What is the biggest bottleneck in your current workflow?', options: ['Manual data entry', 'Slow approvals', 'Lack of visibility', 'Too many tools'], allows_free_text: true, section: 'rca', section_label: 'Diagnostic' },
  { question: 'How do you currently measure success for this task?', options: ['Revenue metrics', 'Time saved', 'Customer feedback', 'We don\'t measure it'], allows_free_text: true, section: 'rca', section_label: 'Diagnostic' },
  { question: 'What is your team size working on this?', options: ['Just me', '2-5 people', '6-15 people', '15+'], allows_free_text: true, section: 'rca', section_label: 'Diagnostic' },
];

const DEMO_PRECISION_QUESTIONS = [
  { type: 'contradiction', question: 'You mentioned manual data entry is your bottleneck, but your website shows automated forms. Are these actually connected to your CRM?', options: ['Yes, fully connected', 'Partially', 'No, they are separate', 'I\'m not sure'], section_label: 'Precision', insight: 'We noticed a gap between your public-facing automation and internal workflow.' },
  { type: 'blind_spot', question: 'Based on your answers, it seems you may not be tracking lead response time. Would faster response help close more deals?', options: ['Definitely yes', 'Possibly', 'Not a priority right now', 'We already track this'], section_label: 'Precision', insight: 'Companies that respond within 5 minutes convert 21x more leads.' },
];

export default function IkshanApp() {
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
        await api.submitUrl(sid, finalUrl);
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
      if (DEMO_MODE) {
        setCurrentQuestion(DEMO_DIAGNOSTIC_QUESTIONS[0]);
        setQuestionIndex(0);
        setShowDiagnostic(true);
        setTimeout(scrollToEnd, 50);
        return;
      }
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
      if (DEMO_MODE) {
        const nextIdx = questionIndex + 1;
        if (nextIdx < DEMO_DIAGNOSTIC_QUESTIONS.length) {
          setCurrentQuestion(DEMO_DIAGNOSTIC_QUESTIONS[nextIdx]);
          setQuestionIndex(nextIdx);
        } else {
          // Move to precision questions
          setPrecisionQuestions(DEMO_PRECISION_QUESTIONS);
          setPrecisionIndex(0);
          setCurrentQuestion(DEMO_PRECISION_QUESTIONS[0]);
          setShowPrecision(true);
          setTimeout(scrollToEnd, 50);
        }
        return;
      }
      const sid = await ensureSession();
      const data = await api.submitAnswer(sid, questionIndex, answer);
      if (data.all_answered) {
        const precData = await api.getPrecisionQuestions(sid);
        if (precData.available && precData.questions?.length) {
          setPrecisionQuestions(precData.questions);
          setPrecisionIndex(0);
          setCurrentQuestion(precData.questions[0]);
          setShowPrecision(true);
        } else {
          setShowComplete(true);
        }
        setTimeout(scrollToEnd, 50);
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
      if (DEMO_MODE) {
        const nextIdx = precisionIndex + 1;
        if (nextIdx < precisionQuestions.length) {
          setPrecisionIndex(nextIdx);
          setCurrentQuestion(precisionQuestions[nextIdx]);
        } else {
          setShowComplete(true);
          setTimeout(scrollToEnd, 50);
        }
        return;
      }
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
    clearPostTask();
    setDiagnosticData(null); setError(null);
    setHoveredOutcome(null); setHoveredDomain(null); setHoveredTask(null);
    sessionIdRef.current = null; sessionPromiseRef.current = null;
    if (canvasRef.current) canvasRef.current.scrollLeft = 0;
  };

  const handleBackToStep1 = () => {
    setSelectedTask(null);
    clearPostTask();
    setUrlValue(''); setGbpValue('');
  };

  const clearError = () => setError(null);

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
            onClick={handleRestart}
            style={{ marginTop: '12px', padding: '12px 32px', borderRadius: '10px', background: 'linear-gradient(135deg, #6366f1, #8b5cf6)', color: '#fff', border: 'none', fontWeight: 700, fontSize: '15px', cursor: 'pointer' }}
          >
            Start New Journey
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
