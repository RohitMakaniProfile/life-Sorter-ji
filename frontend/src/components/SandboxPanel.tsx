import { useState, useEffect, useRef, useCallback } from 'react';
import {
  ArrowLeft, Play, ScrollText, Terminal, Download, Trash2,
  ChevronRight, CheckCircle2, Circle, AlertCircle, Cpu,
  FileText, Eye, RotateCcw, Filter, Copy, Clock, Zap,
  Database, Code2, Hash, Activity, X, LogOut
} from 'lucide-react';
import './SandboxPanel.css';

// ── Outcome/Domain/Task data (copied structure for sandbox, no imports from ChatBotNew) ──
const OUTCOMES = [
  { id: 'lead-generation', label: 'Lead Generation (Marketing, SEO & Social)', icon: '🎯' },
  { id: 'conversion', label: 'Conversion & Sales Enablement', icon: '💰' },
  { id: 'retention', label: 'Revenue Retention & Customer Success', icon: '🔄' },
  { id: 'efficiency', label: 'Operational Efficiency & Team Productivity', icon: '⚡' },
  { id: 'finance', label: 'Financial Health, Legal & Admin', icon: '📊' },
];

// Domain mapping
const DOMAIN_MAP = {
  'lead-generation': ['Content & Social Media', 'SEO & Organic Visibility', 'Paid Media & Ads', 'B2B Lead Generation', 'Market Strategy & Innovation'],
  'conversion': ['Sales Execution & Enablement', 'Lead Management & Conversion', 'Marketing  & Sales Automation'],
  'retention': ['Customer Support Ops', 'Customer Success & Reputation', 'Same User More Sale_'],
  'efficiency': ['Personal & Team Productivity', 'Org Efficiency & Hiring', 'Recruiting & HR Ops', 'Business Intelligence & Analytics'],
  'finance': ['Finance Legal & Admin', 'Financial Health & Risk', 'Owner_ Founder Improvements'],
};

const API_BASE = import.meta.env.VITE_API_URL || '';

// ══════════════════════════════════════════════════════════════
// LOG LEVEL BADGES
// ══════════════════════════════════════════════════════════════

const LEVEL_CONFIG = {
  debug:   { color: '#6b7280', bg: 'rgba(107,114,128,0.1)', label: 'DEBUG' },
  info:    { color: '#3b82f6', bg: 'rgba(59,130,246,0.08)', label: 'INFO' },
  warn:    { color: '#f59e0b', bg: 'rgba(245,158,11,0.08)', label: 'WARN' },
  error:   { color: '#ef4444', bg: 'rgba(239,68,68,0.08)',  label: 'ERROR' },
  llm:     { color: '#8b5cf6', bg: 'rgba(139,92,246,0.08)', label: 'LLM' },
  context: { color: '#10b981', bg: 'rgba(16,185,129,0.08)', label: 'CTX' },
  flow:    { color: '#06b6d4', bg: 'rgba(6,182,212,0.08)',  label: 'FLOW' },
  file:    { color: '#f97316', bg: 'rgba(249,115,22,0.08)', label: 'FILE' },
};

const LevelBadge = ({ level }) => {
  const cfg = LEVEL_CONFIG[level] || LEVEL_CONFIG.info;
  return (
    <span className="sb-log-badge" style={{ color: cfg.color, background: cfg.bg }}>
      {cfg.label}
    </span>
  );
};


// ══════════════════════════════════════════════════════════════
// MAIN SANDBOX PANEL
// ══════════════════════════════════════════════════════════════

const SandboxPanel = ({ token, onLogout, onBack }) => {
  const [activeTab, setActiveTab] = useState('flow'); // 'flow' | 'logger'

  return (
    <div className="sb-container">
      {/* Header */}
      <header className="sb-header">
        <div className="sb-header-left">
          <button className="sb-icon-btn" onClick={onBack} title="Back to app">
            <ArrowLeft size={18} />
          </button>
          <div className="sb-header-logo">
            <Terminal size={18} />
            <span>Sandbox</span>
          </div>
        </div>

        <div className="sb-tabs">
          <button
            className={`sb-tab ${activeTab === 'flow' ? 'active' : ''}`}
            onClick={() => setActiveTab('flow')}
          >
            <Play size={14} /> Test Flow
          </button>
          <button
            className={`sb-tab ${activeTab === 'logger' ? 'active' : ''}`}
            onClick={() => setActiveTab('logger')}
          >
            <ScrollText size={14} /> Logger
          </button>
        </div>

        <div className="sb-header-right">
          <button className="sb-icon-btn" onClick={onLogout} title="Logout">
            <LogOut size={18} />
          </button>
        </div>
      </header>

      {/* Content */}
      <div className="sb-content">
        {activeTab === 'flow' ? <TestFlowPanel /> : <LoggerPanel />}
      </div>
    </div>
  );
};


// ══════════════════════════════════════════════════════════════
// TEST FLOW PANEL
// ══════════════════════════════════════════════════════════════

const TestFlowPanel = () => {
  const [sessionId, setSessionId] = useState(null);
  const [stage, setStage] = useState('idle'); // idle, outcome, domain, task, diagnostic, recommend, complete
  const [selectedOutcome, setSelectedOutcome] = useState(null);
  const [selectedDomain, setSelectedDomain] = useState(null);
  const [selectedTask, setSelectedTask] = useState(null);
  const [questions, setQuestions] = useState([]);
  const [currentQIndex, setCurrentQIndex] = useState(0);
  const [answers, setAnswers] = useState({});
  const [recommendations, setRecommendations] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [tasksList, setTasksList] = useState([]);

  // Hardcoded tasks per domain (simplified — real app fetches from persona docs)
  const getTasksForDomain = (domain) => {
    // Return generic tasks — the backend handles the actual persona matching
    return [
      `Automate ${domain.toLowerCase()} workflows`,
      `Analyze ${domain.toLowerCase()} performance metrics`,
      `Optimize ${domain.toLowerCase()} processes`,
      `Generate reports for ${domain.toLowerCase()}`,
    ];
  };

  const startSession = async () => {
    setLoading(true);
    setError('');
    try {
      const res = await fetch(`${API_BASE}/api/v1/sandbox/test/session`, { method: 'POST' });
      const data = await res.json();
      setSessionId(data.session_id);
      setStage('outcome');
    } catch (e) {
      setError('Failed to create session');
    }
    setLoading(false);
  };

  const selectOutcome = async (outcome) => {
    setSelectedOutcome(outcome);
    setLoading(true);
    try {
      await fetch(`${API_BASE}/api/v1/sandbox/test/outcome`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sessionId,
          outcome: outcome.id,
          outcome_label: outcome.label,
        }),
      });
      setStage('domain');
    } catch (e) {
      setError('Failed to set outcome');
    }
    setLoading(false);
  };

  const selectDomain = async (domain) => {
    setSelectedDomain(domain);
    setLoading(true);
    try {
      await fetch(`${API_BASE}/api/v1/sandbox/test/domain`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId, domain }),
      });
      setTasksList(getTasksForDomain(domain));
      setStage('task');
    } catch (e) {
      setError('Failed to set domain');
    }
    setLoading(false);
  };

  const selectTask = async (task) => {
    setSelectedTask(task);
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/v1/sandbox/test/task`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId, task }),
      });
      const data = await res.json();
      if (data.questions && data.questions.length > 0) {
        setQuestions(data.questions);
        setCurrentQIndex(0);
        setStage('diagnostic');
      } else {
        setStage('recommend');
      }
    } catch (e) {
      setError('Failed to set task');
    }
    setLoading(false);
  };

  const submitAnswer = async (answer) => {
    setAnswers(prev => ({ ...prev, [currentQIndex]: answer }));
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/v1/sandbox/test/answer`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sessionId,
          question_index: currentQIndex,
          answer,
        }),
      });
      const data = await res.json();
      if (data.all_answered) {
        setStage('recommend');
      } else {
        setCurrentQIndex(prev => prev + 1);
      }
    } catch (e) {
      setError('Failed to submit answer');
    }
    setLoading(false);
  };

  const getRecommendations = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/v1/sandbox/test/recommend`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId }),
      });
      const data = await res.json();
      setRecommendations(data);
      setStage('complete');
    } catch (e) {
      setError('Failed to get recommendations');
    }
    setLoading(false);
  };

  const resetFlow = () => {
    setSessionId(null);
    setStage('idle');
    setSelectedOutcome(null);
    setSelectedDomain(null);
    setSelectedTask(null);
    setQuestions([]);
    setCurrentQIndex(0);
    setAnswers({});
    setRecommendations(null);
    setError('');
  };

  // Progress steps
  const steps = [
    { key: 'outcome', label: 'Outcome' },
    { key: 'domain', label: 'Domain' },
    { key: 'task', label: 'Task' },
    { key: 'diagnostic', label: 'Diagnostic' },
    { key: 'recommend', label: 'Recommend' },
    { key: 'complete', label: 'Complete' },
  ];

  const stageIndex = steps.findIndex(s => s.key === stage);

  return (
    <div className="sb-flow-panel">
      {/* Progress bar */}
      {stage !== 'idle' && (
        <div className="sb-progress">
          {steps.map((step, i) => (
            <div key={step.key} className={`sb-progress-step ${i < stageIndex ? 'done' : i === stageIndex ? 'current' : ''}`}>
              {i < stageIndex ? <CheckCircle2 size={14} /> : i === stageIndex ? <Activity size={14} /> : <Circle size={14} />}
              <span>{step.label}</span>
              {i < steps.length - 1 && <ChevronRight size={12} className="sb-progress-arrow" />}
            </div>
          ))}
          <button className="sb-reset-btn" onClick={resetFlow} title="Reset">
            <RotateCcw size={14} /> Reset
          </button>
        </div>
      )}

      {/* Session indicator */}
      {sessionId && (
        <div className="sb-session-badge">
          <Hash size={12} /> {sessionId.slice(0, 8)}
        </div>
      )}

      {error && (
        <div className="sb-flow-error">
          <AlertCircle size={14} /> {error}
          <button onClick={() => setError('')}><X size={12} /></button>
        </div>
      )}

      {/* IDLE */}
      {stage === 'idle' && (
        <div className="sb-flow-center">
          <div className="sb-flow-start-icon"><Play size={32} /></div>
          <h3>Test User Flow</h3>
          <p>Run the full outcome → domain → task → diagnostic → recommendation flow without authentication or payment gates.</p>
          <button className="sb-primary-btn" onClick={startSession} disabled={loading}>
            {loading ? 'Creating…' : 'Start Test Session'}
          </button>
        </div>
      )}

      {/* OUTCOME */}
      {stage === 'outcome' && (
        <div className="sb-flow-section">
          <h3>Q1: What matters most to you?</h3>
          <div className="sb-options-grid">
            {OUTCOMES.map(o => (
              <button key={o.id} className="sb-option-card" onClick={() => selectOutcome(o)} disabled={loading}>
                <span className="sb-option-icon">{o.icon}</span>
                <span className="sb-option-label">{o.label}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* DOMAIN */}
      {stage === 'domain' && selectedOutcome && (
        <div className="sb-flow-section">
          <h3>Q2: Which domain?</h3>
          <p className="sb-flow-sublabel">Selected: {selectedOutcome.label}</p>
          <div className="sb-options-grid">
            {(DOMAIN_MAP[selectedOutcome.id] || []).map(d => (
              <button key={d} className="sb-option-card" onClick={() => selectDomain(d)} disabled={loading}>
                <span className="sb-option-label">{d}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* TASK */}
      {stage === 'task' && (
        <div className="sb-flow-section">
          <h3>Q3: What task?</h3>
          <p className="sb-flow-sublabel">Domain: {selectedDomain}</p>
          <div className="sb-flow-task-input">
            <input
              type="text"
              placeholder="Type a custom task or pick one below…"
              onKeyDown={(e) => e.key === 'Enter' && e.target.value && selectTask(e.target.value)}
              className="sb-task-input"
            />
          </div>
          <div className="sb-options-list">
            {tasksList.map((t, i) => (
              <button key={i} className="sb-option-card compact" onClick={() => selectTask(t)} disabled={loading}>
                <span className="sb-option-label">{t}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* DIAGNOSTIC */}
      {stage === 'diagnostic' && questions.length > 0 && (
        <div className="sb-flow-section">
          <h3>Diagnostic Q{currentQIndex + 1}/{questions.length}</h3>
          <p className="sb-flow-question">{questions[currentQIndex]?.question}</p>
          <div className="sb-options-list">
            {(questions[currentQIndex]?.options || []).map((opt, i) => (
              <button key={i} className="sb-option-card compact" onClick={() => submitAnswer(opt)} disabled={loading}>
                <span className="sb-option-label">{opt}</span>
              </button>
            ))}
          </div>
          {questions[currentQIndex]?.allows_free_text && (
            <div className="sb-flow-task-input">
              <input
                type="text"
                placeholder="Or type your own answer…"
                onKeyDown={(e) => e.key === 'Enter' && e.target.value && submitAnswer(e.target.value)}
                className="sb-task-input"
              />
            </div>
          )}
        </div>
      )}

      {/* RECOMMEND */}
      {stage === 'recommend' && (
        <div className="sb-flow-center">
          <Cpu size={28} className="sb-recommend-icon" />
          <h3>Ready for Recommendations</h3>
          <p>All answers collected. Generate AI-powered tool recommendations.</p>
          <button className="sb-primary-btn" onClick={getRecommendations} disabled={loading}>
            {loading ? 'Generating…' : 'Get Recommendations'}
          </button>
        </div>
      )}

      {/* COMPLETE */}
      {stage === 'complete' && recommendations && (
        <div className="sb-flow-section">
          <div className="sb-complete-header">
            <CheckCircle2 size={20} style={{ color: '#10b981' }} />
            <h3>Flow Complete</h3>
          </div>
          {recommendations.summary && (
            <div className="sb-rec-summary">
              {typeof recommendations.summary === 'object' && recommendations.summary.one_liner
                ? recommendations.summary.one_liner
                : typeof recommendations.summary === 'string'
                  ? recommendations.summary
                  : null}
            </div>
          )}
          <div className="sb-rec-grid">
            {['extensions', 'gpts', 'companies'].map(cat => (
              recommendations[cat]?.length > 0 && (
                <div key={cat} className="sb-rec-category">
                  <h4>{cat === 'extensions' ? '🧩 Extensions' : cat === 'gpts' ? '🤖 GPTs' : '🏢 Companies'}</h4>
                  {recommendations[cat].map((item, i) => (
                    <div key={i} className="sb-rec-item">
                      <strong>{item.name}</strong>
                      <p>{item.description}</p>
                      {item.why_recommended && <span className="sb-rec-why">{item.why_recommended}</span>}
                      {item.url && <a href={item.url} target="_blank" rel="noreferrer" className="sb-rec-link">Open →</a>}
                    </div>
                  ))}
                </div>
              )
            ))}
          </div>
          <button className="sb-primary-btn" onClick={resetFlow} style={{ marginTop: '1.5rem' }}>
            <RotateCcw size={14} /> Run Again
          </button>
        </div>
      )}

      {loading && <div className="sb-loading-bar" />}
    </div>
  );
};


// ══════════════════════════════════════════════════════════════
// LOGGER PANEL
// ══════════════════════════════════════════════════════════════

const LoggerPanel = () => {
  const [sessions, setSessions] = useState([]);
  const [selectedSession, setSelectedSession] = useState(null);
  const [logs, setLogs] = useState([]);
  const [context, setContext] = useState({});
  const [filter, setFilter] = useState('all');
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [expandedEntries, setExpandedEntries] = useState({});
  const [showContextPanel, setShowContextPanel] = useState(false);
  const logsEndRef = useRef(null);
  const intervalRef = useRef(null);

  const fetchSessions = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/v1/sandbox/logs`);
      const data = await res.json();
      setSessions(data.sessions || []);
    } catch {}
  }, []);

  const fetchLogs = useCallback(async (sid) => {
    try {
      const res = await fetch(`${API_BASE}/api/v1/sandbox/logs/${sid}`);
      const data = await res.json();
      setLogs(data.entries || []);
      setContext(data.context_snapshot || {});
    } catch {}
  }, []);

  // Auto refresh
  useEffect(() => {
    fetchSessions();
    if (autoRefresh) {
      intervalRef.current = setInterval(() => {
        fetchSessions();
        if (selectedSession) fetchLogs(selectedSession);
      }, 2000);
    }
    return () => clearInterval(intervalRef.current);
  }, [autoRefresh, selectedSession, fetchSessions, fetchLogs]);

  useEffect(() => {
    if (selectedSession) fetchLogs(selectedSession);
  }, [selectedSession, fetchLogs]);

  // Auto scroll
  useEffect(() => {
    if (autoRefresh && logsEndRef.current) {
      logsEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [logs, autoRefresh]);

  const filteredLogs = filter === 'all'
    ? logs
    : logs.filter(l => l.level === filter);

  const toggleExpand = (id) => {
    setExpandedEntries(prev => ({ ...prev, [id]: !prev[id] }));
  };

  const exportTxt = async () => {
    if (!selectedSession) return;
    try {
      const res = await fetch(`${API_BASE}/api/v1/sandbox/logs/export/${selectedSession}`);
      const text = await res.text();
      const blob = new Blob([text], { type: 'text/plain' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `sandbox-log-${selectedSession.slice(0, 8)}.txt`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {}
  };

  const exportGlobal = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/v1/sandbox/logs/export-all/global`);
      const text = await res.text();
      const blob = new Blob([text], { type: 'text/plain' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'sandbox-global-log.txt';
      a.click();
      URL.revokeObjectURL(url);
    } catch {}
  };

  const clearAllLogs = async () => {
    try {
      await fetch(`${API_BASE}/api/v1/sandbox/logs`, { method: 'DELETE' });
      setSessions([]);
      setLogs([]);
      setContext({});
      setSelectedSession(null);
    } catch {}
  };

  const copyEntry = (entry) => {
    navigator.clipboard.writeText(JSON.stringify(entry, null, 2));
  };

  return (
    <div className="sb-logger">
      {/* Sessions sidebar */}
      <div className="sb-logger-sidebar">
        <div className="sb-logger-sidebar-header">
          <h4><Database size={14} /> Sessions</h4>
          <div className="sb-logger-sidebar-actions">
            <button onClick={exportGlobal} title="Export all"><Download size={13} /></button>
            <button onClick={clearAllLogs} title="Clear all"><Trash2 size={13} /></button>
          </div>
        </div>
        <div className="sb-sessions-list">
          {sessions.length === 0 && (
            <div className="sb-sessions-empty">No sessions yet — run a test flow first</div>
          )}
          {sessions.map(s => (
            <button
              key={s.session_id}
              className={`sb-session-item ${selectedSession === s.session_id ? 'active' : ''}`}
              onClick={() => setSelectedSession(s.session_id)}
            >
              <div className="sb-session-item-top">
                <Hash size={11} />
                <span className="sb-session-id">{s.session_id.slice(0, 8)}</span>
                <span className="sb-session-count">{s.entry_count}</span>
              </div>
              <div className="sb-session-item-time">
                {new Date(s.started_at).toLocaleTimeString()}
              </div>
            </button>
          ))}
        </div>
      </div>

      {/* Log viewer */}
      <div className="sb-logger-main">
        {!selectedSession ? (
          <div className="sb-logger-empty">
            <ScrollText size={32} />
            <p>Select a session to view logs</p>
          </div>
        ) : (
          <>
            {/* Toolbar */}
            <div className="sb-logger-toolbar">
              <div className="sb-filter-group">
                <Filter size={13} />
                {['all', 'flow', 'llm', 'context', 'file', 'error'].map(f => (
                  <button
                    key={f}
                    className={`sb-filter-btn ${filter === f ? 'active' : ''}`}
                    onClick={() => setFilter(f)}
                  >
                    {f.toUpperCase()}
                  </button>
                ))}
              </div>
              <div className="sb-toolbar-actions">
                <button
                  className={`sb-toolbar-btn ${showContextPanel ? 'active' : ''}`}
                  onClick={() => setShowContextPanel(!showContextPanel)}
                  title="Context snapshot"
                >
                  <Eye size={13} /> Context
                </button>
                <button
                  className={`sb-toolbar-btn ${autoRefresh ? 'active' : ''}`}
                  onClick={() => setAutoRefresh(!autoRefresh)}
                  title="Auto refresh"
                >
                  <Activity size={13} /> Live
                </button>
                <button className="sb-toolbar-btn" onClick={exportTxt} title="Export .txt">
                  <Download size={13} /> Export
                </button>
              </div>
            </div>

            <div className="sb-logger-body">
              {/* Context panel (collapsible) */}
              {showContextPanel && Object.keys(context).length > 0 && (
                <div className="sb-context-panel">
                  <div className="sb-context-header">
                    <Code2 size={13} /> Context Snapshot
                    <button onClick={() => setShowContextPanel(false)}><X size={12} /></button>
                  </div>
                  <pre className="sb-context-pre">{JSON.stringify(context, null, 2)}</pre>
                </div>
              )}

              {/* Log entries */}
              <div className="sb-log-entries">
                {filteredLogs.length === 0 && (
                  <div className="sb-log-empty">No matching log entries</div>
                )}
                {filteredLogs.map((entry) => (
                  <div key={entry.id} className={`sb-log-entry ${expandedEntries[entry.id] ? 'expanded' : ''}`}>
                    <div className="sb-log-row" onClick={() => toggleExpand(entry.id)}>
                      <span className="sb-log-time">
                        <Clock size={10} />
                        {new Date(entry.timestamp).toLocaleTimeString([], { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                        {entry.duration_ms != null && <span className="sb-log-dur">{Math.round(entry.duration_ms)}ms</span>}
                      </span>
                      <LevelBadge level={entry.level} />
                      <span className="sb-log-cat">{entry.category}</span>
                      <span className="sb-log-event">{entry.event}</span>
                      {entry.code_file && (
                        <span className="sb-log-file">
                          <FileText size={10} /> {entry.code_file}
                        </span>
                      )}
                      <button className="sb-log-copy" onClick={(e) => { e.stopPropagation(); copyEntry(entry); }} title="Copy">
                        <Copy size={11} />
                      </button>
                    </div>
                    {expandedEntries[entry.id] && entry.detail && Object.keys(entry.detail).length > 0 && (
                      <div className="sb-log-detail">
                        <pre>{JSON.stringify(entry.detail, null, 2)}</pre>
                      </div>
                    )}
                  </div>
                ))}
                <div ref={logsEndRef} />
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
};

export default SandboxPanel;
