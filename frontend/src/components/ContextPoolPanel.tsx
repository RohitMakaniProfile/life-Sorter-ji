import { useState, useEffect, useRef, useCallback } from 'react';
import { X, ChevronDown, ChevronRight, Activity, Brain, Send as SendIcon, Layers, Clock, Zap, Database, Eye, EyeOff } from 'lucide-react';
import './ContextPoolPanel.css';
import { getApiBaseRequired } from '../config/apiBase';

const STAGE_LABELS = {
  outcome: 'Q1: Outcome',
  domain: 'Q2: Domain',
  task: 'Q3: Task',
  url_input: 'URL Input',
  scale_questions: 'Scale Questions',
  dynamic_questions: 'RCA Diagnostic',
  playbook: 'AI Playbook',
  complete: 'Complete',
};

const STAGE_ORDER = ['outcome', 'domain', 'task', 'url_input', 'scale_questions', 'dynamic_questions', 'playbook', 'complete'];

function CollapsibleSection({ title, icon: Icon, children, defaultOpen = false, count }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="ctx-section">
      <button className="ctx-section-header" onClick={() => setOpen(!open)}>
        <div className="ctx-section-title">
          {Icon && <Icon size={14} />}
          <span>{title}</span>
          {count !== undefined && <span className="ctx-badge">{count}</span>}
        </div>
        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
      </button>
      {open && <div className="ctx-section-body">{children}</div>}
    </div>
  );
}

function JsonBlock({ data, maxHeight = 300 }) {
  const [expanded, setExpanded] = useState(false);
  const text = typeof data === 'string' ? data : JSON.stringify(data, null, 2);
  const isLong = text.length > 500;

  return (
    <div className="ctx-json-block">
      <pre style={{ maxHeight: expanded ? 'none' : `${maxHeight}px` }}>
        {expanded ? text : text.slice(0, 800)}
        {!expanded && isLong && '...'}
      </pre>
      {isLong && (
        <button className="ctx-expand-btn" onClick={() => setExpanded(!expanded)}>
          {expanded ? 'Collapse' : 'Show full'}
        </button>
      )}
    </div>
  );
}

/**
 * Parse the user message (context sent to LLM) into named sections.
 * Splits on ═══ SECTION NAME ═══ headers.
 */
function parseContextSections(text) {
  if (!text) return [];
  const lines = text.split('\n');
  const sections = [];
  let currentSection = { title: 'Preamble', lines: [] };

  for (const line of lines) {
    const headerMatch = line.match(/^═+\s*(.+?)\s*═+$/);
    if (headerMatch) {
      if (currentSection.lines.length > 0) {
        sections.push(currentSection);
      }
      currentSection = { title: headerMatch[1], lines: [] };
    } else {
      currentSection.lines.push(line);
    }
  }
  if (currentSection.lines.length > 0) {
    sections.push(currentSection);
  }
  // Filter out empty preamble
  return sections.filter(s => s.lines.some(l => l.trim()));
}

function ContextSection({ title, lines }) {
  const [open, setOpen] = useState(true);
  const content = lines.join('\n').trim();
  if (!content) return null;

  return (
    <div className="ctx-context-block">
      <button className="ctx-context-block-header" onClick={() => setOpen(!open)}>
        <span>{title}</span>
        {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
      </button>
      {open && (
        <pre className="ctx-context-block-body">{content}</pre>
      )}
    </div>
  );
}

function LLMCallCard({ entry, index }) {
  const [showSystemPrompt, setShowSystemPrompt] = useState(false);
  const [showRawResponse, setShowRawResponse] = useState(false);

  const serviceLabel = entry.service === 'openai' ? 'OpenAI' : 'Claude (OpenRouter)';
  const serviceColor = entry.service === 'openai' ? '#10b981' : '#8b5cf6';
  const purposeLabel = (entry.purpose || '').replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());

  // Parse user message into structured sections
  const contextSections = parseContextSections(entry.user_message);

  // Try to parse raw response as JSON for pretty display
  let parsedResponse = null;
  try {
    parsedResponse = JSON.parse(entry.raw_response);
  } catch { /* not JSON */ }

  return (
    <div className="ctx-llm-card">
      {/* ── Header: Service + Purpose + Timing ── */}
      <div className="ctx-llm-card-header">
        <div className="ctx-llm-card-title">
          <span className="ctx-llm-service" style={{ color: serviceColor }}>
            {serviceLabel}
          </span>
          <span className="ctx-llm-purpose">{purposeLabel}</span>
        </div>
        <div className="ctx-llm-card-meta">
          {entry.latency_ms > 0 && (
            <span className="ctx-llm-latency">
              <Clock size={10} /> {entry.latency_ms}ms
            </span>
          )}
          <span className="ctx-llm-time">
            {entry.timestamp ? new Date(entry.timestamp).toLocaleTimeString() : ''}
          </span>
        </div>
      </div>

      {/* ── Params bar ── */}
      <div className="ctx-llm-card-params">
        <span>Model: <strong>{entry.model}</strong></span>
        <span>Temp: {entry.temperature}</span>
        <span>Max: {entry.max_tokens}</span>
        {entry.token_usage?.total_tokens > 0 && (
          <span>Tokens: {entry.token_usage.total_tokens}</span>
        )}
      </div>

      {/* ── CONTEXT SENT TO LLM (always visible, parsed into sections) ── */}
      <div className="ctx-llm-context-sent">
        <div className="ctx-llm-context-label">
          <Database size={12} />
          <span>Context Sent to LLM</span>
        </div>
        {contextSections.length > 0 ? (
          <div className="ctx-context-sections">
            {contextSections.map((sec, i) => (
              <ContextSection key={i} title={sec.title} lines={sec.lines} />
            ))}
          </div>
        ) : (
          <pre className="ctx-context-raw">{entry.user_message || '(empty)'}</pre>
        )}
      </div>

      {/* ── LLM RESPONSE (always visible, parsed if JSON) ── */}
      <div className="ctx-llm-response-section">
        <div className="ctx-llm-context-label">
          <Brain size={12} />
          <span>LLM Response</span>
        </div>
        {parsedResponse ? (
          <div className="ctx-response-parsed">
            {parsedResponse.status && (
              <div className="ctx-response-status">
                Status: <strong>{parsedResponse.status}</strong>
              </div>
            )}
            {parsedResponse.acknowledgment && (
              <div className="ctx-response-field">
                <span className="ctx-response-field-label">Acknowledgment</span>
                <p>{parsedResponse.acknowledgment}</p>
              </div>
            )}
            {parsedResponse.insight && (
              <div className="ctx-response-field ctx-response-insight">
                <span className="ctx-response-field-label">Insight</span>
                <p>{parsedResponse.insight}</p>
              </div>
            )}
            {parsedResponse.question && (
              <div className="ctx-response-field">
                <span className="ctx-response-field-label">Question Generated</span>
                <p>{parsedResponse.question}</p>
              </div>
            )}
            {parsedResponse.options && (
              <div className="ctx-response-field">
                <span className="ctx-response-field-label">Options</span>
                <ul className="ctx-response-options">
                  {parsedResponse.options.map((opt, i) => <li key={i}>{opt}</li>)}
                </ul>
              </div>
            )}
            {parsedResponse.summary && (
              <div className="ctx-response-field ctx-response-insight">
                <span className="ctx-response-field-label">Summary</span>
                <p>{typeof parsedResponse.summary === 'string'
                  ? parsedResponse.summary
                  : parsedResponse.summary.one_liner || JSON.stringify(parsedResponse.summary)
                }</p>
              </div>
            )}
            {/* For early recommendations */}
            {parsedResponse.tools && (
              <div className="ctx-response-field">
                <span className="ctx-response-field-label">Tools Selected ({parsedResponse.tools.length})</span>
                <ul className="ctx-response-options">
                  {parsedResponse.tools.map((t, i) => (
                    <li key={i}><strong>{t.name}</strong> — {t.why_relevant || t.description}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        ) : (
          <pre className="ctx-context-raw">{entry.raw_response || '(empty)'}</pre>
        )}
      </div>

      {/* ── Toggleable: System Prompt (big, usually the same) ── */}
      <button
        className="ctx-toggle-prompts"
        onClick={() => setShowSystemPrompt(!showSystemPrompt)}
      >
        {showSystemPrompt ? <EyeOff size={12} /> : <Eye size={12} />}
        {showSystemPrompt ? 'Hide System Prompt' : 'View System Prompt'}
      </button>
      {showSystemPrompt && (
        <div className="ctx-prompt-section">
          <span className="ctx-prompt-label">System Prompt</span>
          <JsonBlock data={entry.system_prompt} maxHeight={300} />
        </div>
      )}

      {entry.error && (
        <div className="ctx-prompt-section ctx-error">
          <span className="ctx-prompt-label">Error</span>
          <pre>{entry.error}</pre>
        </div>
      )}
    </div>
  );
}

function CrawlPageCard({ page, index }) {
  const [expanded, setExpanded] = useState(false);
  const typeLabel = (page.type || 'general').replace(/_/g, ' ');

  return (
    <div className="ctx-crawl-page-card">
      <button className="ctx-crawl-page-header" onClick={() => setExpanded(!expanded)}>
        <div className="ctx-crawl-page-info">
          <span className="ctx-crawl-page-type">{typeLabel}</span>
          <span className="ctx-crawl-page-title">{page.title || page.url}</span>
        </div>
        {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
      </button>
      {expanded && (
        <div className="ctx-crawl-page-body">
          <div className="ctx-crawl-page-url">{page.url}</div>
          {page.meta_desc && (
            <div className="ctx-kv">
              <span className="ctx-key">Meta</span>
              <span className="ctx-val">{page.meta_desc}</span>
            </div>
          )}
          {page.headings?.length > 0 && (
            <div className="ctx-crawl-headings">
              <span className="ctx-key">Headings</span>
              <ul>{page.headings.map((h, i) => <li key={i}>{h}</li>)}</ul>
            </div>
          )}
          {page.key_content && (
            <div className="ctx-crawl-content-preview">
              <span className="ctx-key">Content Preview</span>
              <pre>{page.key_content.slice(0, 500)}{page.key_content.length > 500 ? '...' : ''}</pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function ContextPoolPanel({ sessionId, isOpen, onClose }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const pollRef = useRef(null);
  const API_BASE = getApiBaseRequired();

  const fetchContextPool = useCallback(async () => {
    if (!sessionId) return;
    try {
      const res = await fetch(`${API_BASE}/api/v1/agent/session/${sessionId}/context-pool`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      setData(json);
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [sessionId, API_BASE]);

  // Poll every 4s when panel is open
  useEffect(() => {
    if (!isOpen || !sessionId) return;
    setLoading(true);
    fetchContextPool();
    pollRef.current = setInterval(fetchContextPool, 4000);
    return () => clearInterval(pollRef.current);
  }, [isOpen, sessionId, fetchContextPool]);

  if (!isOpen) return null;

  const currentStageIndex = data ? STAGE_ORDER.indexOf(data.stage) : -1;

  return (
    <div className="context-pool-panel">
      <div className="ctx-panel-header">
        <div className="ctx-panel-title">
          <Activity size={16} />
          <span>Context Pool</span>
        </div>
        <button className="ctx-close-btn" onClick={onClose}>
          <X size={16} />
        </button>
      </div>

      <div className="ctx-panel-body">
        {loading && !data && (
          <div className="ctx-loading">Loading context...</div>
        )}

        {error && !data && (
          <div className="ctx-error-msg">Error: {error}</div>
        )}

        {data && (
          <>
            {/* Stage Tracker */}
            <CollapsibleSection title="Stage Tracker" icon={Layers} defaultOpen={true}>
              <div className="ctx-stage-tracker">
                {STAGE_ORDER.map((stage, i) => {
                  const isCurrent = stage === data.stage;
                  const isPast = i < currentStageIndex;
                  return (
                    <div
                      key={stage}
                      className={`ctx-stage-item ${isCurrent ? 'current' : ''} ${isPast ? 'past' : ''}`}
                    >
                      <div className={`ctx-stage-dot ${isCurrent ? 'current' : ''} ${isPast ? 'past' : ''}`} />
                      <span className="ctx-stage-label">{STAGE_LABELS[stage]}</span>
                    </div>
                  );
                })}
              </div>
            </CollapsibleSection>

            {/* Context Assembled */}
            <CollapsibleSection title="Context Assembled" icon={Database} defaultOpen={true}>
              <div className="ctx-context-grid">
                <div className="ctx-kv">
                  <span className="ctx-key">Outcome</span>
                  <span className="ctx-val">{data.profile?.outcome_label || '—'}</span>
                </div>
                <div className="ctx-kv">
                  <span className="ctx-key">Domain</span>
                  <span className="ctx-val">{data.profile?.domain || '—'}</span>
                </div>
                <div className="ctx-kv">
                  <span className="ctx-key">Task</span>
                  <span className="ctx-val">{data.profile?.task || '—'}</span>
                </div>
                <div className="ctx-kv">
                  <span className="ctx-key">Persona Doc</span>
                  <span className="ctx-val">{data.profile?.persona_doc || '—'}</span>
                </div>
              </div>

              {/* Business Profile */}
              {data.business_profile && Object.keys(data.business_profile).length > 0 && (
                <div className="ctx-sub-section">
                  <span className="ctx-sub-title">Business Profile</span>
                  <div className="ctx-context-grid">
                    {Object.entries(data.business_profile).map(([k, v]) => (
                      <div className="ctx-kv" key={k}>
                        <span className="ctx-key">{k.replace(/_/g, ' ')}</span>
                        <span className="ctx-val">{v}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Crawl Data */}
              {data.crawl_status && (
                <div className="ctx-sub-section">
                  <span className="ctx-sub-title">
                    Crawl Data
                    <span className={`ctx-crawl-status ${data.crawl_status}`}>
                      {data.crawl_status}
                    </span>
                  </span>

                  {/* Live Progress Indicator */}
                  {data.crawl_progress && data.crawl_progress.phase && data.crawl_progress.phase !== 'complete' && (
                    <div className="ctx-crawl-progress">
                      <div className="ctx-crawl-progress-header">
                        <span className="ctx-crawl-phase-label">
                          {data.crawl_progress.phase === 'fetching_homepage' && '🔍 Fetching homepage...'}
                          {data.crawl_progress.phase === 'crawling_pages' && `📄 Crawling pages (${data.crawl_progress.pages_crawled}/${data.crawl_progress.pages_found})`}
                          {data.crawl_progress.phase === 'generating_summary' && '🤖 Generating AI summary...'}
                        </span>
                      </div>
                      {data.crawl_progress.phase === 'crawling_pages' && data.crawl_progress.pages_found > 0 && (
                        <div className="ctx-crawl-progress-bar-wrap">
                          <div
                            className="ctx-crawl-progress-bar"
                            style={{ width: `${Math.round((data.crawl_progress.pages_crawled / data.crawl_progress.pages_found) * 100)}%` }}
                          />
                        </div>
                      )}
                      {data.crawl_progress.current_page && (
                        <div className="ctx-crawl-current-page">
                          Current: <span>{data.crawl_progress.current_page}</span>
                        </div>
                      )}
                    </div>
                  )}

                  {/* Summary Bullets */}
                  {data.crawl_summary?.points && (
                    <ul className="ctx-crawl-points">
                      {data.crawl_summary.points.map((pt, i) => (
                        <li key={i}>{pt}</li>
                      ))}
                    </ul>
                  )}

                  {/* Homepage Meta Card */}
                  {data.crawl_raw?.homepage && (data.crawl_raw.homepage.title || data.crawl_raw.homepage.meta_desc) && (
                    <div className="ctx-crawl-homepage">
                      <span className="ctx-crawl-card-title">🏠 Homepage</span>
                      <div className="ctx-context-grid">
                        {data.crawl_raw.homepage.title && (
                          <div className="ctx-kv"><span className="ctx-key">Title</span><span className="ctx-val">{data.crawl_raw.homepage.title}</span></div>
                        )}
                        {data.crawl_raw.homepage.meta_desc && (
                          <div className="ctx-kv"><span className="ctx-key">Description</span><span className="ctx-val">{data.crawl_raw.homepage.meta_desc}</span></div>
                        )}
                        {data.crawl_raw.homepage.h1s?.length > 0 && (
                          <div className="ctx-kv"><span className="ctx-key">H1s</span><span className="ctx-val">{data.crawl_raw.homepage.h1s.join(' | ')}</span></div>
                        )}
                      </div>
                      {data.crawl_raw.homepage.headings?.length > 0 && (
                        <div className="ctx-crawl-headings">
                          <span className="ctx-key">Key Headings</span>
                          <ul>{data.crawl_raw.homepage.headings.slice(0, 8).map((h, i) => <li key={i}>{h}</li>)}</ul>
                        </div>
                      )}
                    </div>
                  )}

                  {/* Pages Crawled List */}
                  {data.crawl_raw?.pages_crawled?.length > 0 && (
                    <div className="ctx-crawl-pages">
                      <span className="ctx-crawl-card-title">📄 Pages Crawled ({data.crawl_raw.pages_crawled.length})</span>
                      {data.crawl_raw.pages_crawled.map((page, i) => (
                        <CrawlPageCard key={i} page={page} index={i} />
                      ))}
                    </div>
                  )}

                  {/* Tech Signals Grid */}
                  {data.crawl_raw?.tech_signals?.length > 0 && (
                    <div className="ctx-crawl-tech">
                      <span className="ctx-crawl-card-title">⚙️ Tech Signals</span>
                      <div className="ctx-crawl-tags">
                        {data.crawl_raw.tech_signals.map((t, i) => (
                          <span className="ctx-crawl-tag tech" key={i}>{t}</span>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* CTA Patterns */}
                  {data.crawl_raw?.cta_patterns?.length > 0 && (
                    <div className="ctx-crawl-ctas">
                      <span className="ctx-crawl-card-title">🎯 CTA Patterns</span>
                      <div className="ctx-crawl-tags">
                        {data.crawl_raw.cta_patterns.map((c, i) => (
                          <span className="ctx-crawl-tag cta" key={i}>{c}</span>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* SEO Checklist */}
                  {data.crawl_raw?.seo_basics && (
                    <div className="ctx-crawl-seo">
                      <span className="ctx-crawl-card-title">🔎 SEO Basics</span>
                      <div className="ctx-crawl-seo-grid">
                        <span className={data.crawl_raw.seo_basics.has_meta ? 'pass' : 'fail'}>
                          {data.crawl_raw.seo_basics.has_meta ? '✓' : '✗'} Meta Tags
                        </span>
                        <span className={data.crawl_raw.seo_basics.has_viewport ? 'pass' : 'fail'}>
                          {data.crawl_raw.seo_basics.has_viewport ? '✓' : '✗'} Mobile Viewport
                        </span>
                        <span className={data.crawl_raw.seo_basics.has_sitemap ? 'pass' : 'fail'}>
                          {data.crawl_raw.seo_basics.has_sitemap ? '✓' : '✗'} Sitemap
                        </span>
                      </div>
                    </div>
                  )}

                  {/* Social Links */}
                  {data.crawl_raw?.social_links?.length > 0 && (
                    <div className="ctx-crawl-socials">
                      <span className="ctx-crawl-card-title">🔗 Social Links ({data.crawl_raw.social_links.length})</span>
                      <ul className="ctx-crawl-points">
                        {data.crawl_raw.social_links.map((link, i) => (
                          <li key={i}>{link}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              )}

              {/* RCA History */}
              {data.rca_history && data.rca_history.length > 0 && (
                <div className="ctx-sub-section">
                  <span className="ctx-sub-title">RCA History ({data.rca_history.length} Q&A)</span>
                  {data.rca_history.map((qa, i) => (
                    <div className="ctx-qa-pair" key={i}>
                      <div className="ctx-qa-q">Q{i + 1}: {qa.question}</div>
                      <div className="ctx-qa-a">A: {qa.answer}</div>
                    </div>
                  ))}
                  {data.rca_complete && data.rca_summary && (
                    <div className="ctx-rca-summary">
                      <strong>Summary:</strong> {data.rca_summary}
                    </div>
                  )}
                </div>
              )}
            </CollapsibleSection>

            {/* Dynamic Loader Context — Persona Doc Sections */}
            {data.rca_diagnostic_context && data.rca_diagnostic_context.sections && (
              <CollapsibleSection
                title="Dynamic Loader Context"
                icon={Layers}
                defaultOpen={true}
                count={data.rca_diagnostic_context.sections?.length || 0}
              >
                {data.rca_diagnostic_context.task_matched && (
                  <div className="ctx-kv" style={{ marginBottom: '0.5rem' }}>
                    <span className="ctx-key">Matched Task</span>
                    <span className="ctx-val">{data.rca_diagnostic_context.task_matched}</span>
                  </div>
                )}
                {data.rca_diagnostic_context.sections.map((sec, i) => {
                  const sectionIcon = sec.key === 'problems' ? '⚠️' : sec.key === 'rca_bridge' ? '🔍' : '🚀';
                  return (
                    <div className="ctx-dynamic-section" key={i}>
                      <div className="ctx-dynamic-section-header">
                        <span>{sectionIcon} {sec.label}</span>
                        <span className="ctx-badge">{sec.items?.length || 0}</span>
                      </div>
                      {sec.question && (
                        <div className="ctx-dynamic-question">{sec.question}</div>
                      )}
                      <ul className="ctx-dynamic-items">
                        {(sec.items || []).map((item, j) => (
                          <li key={j}>{item}</li>
                        ))}
                      </ul>
                      {sec.key === 'rca_bridge' && sec.rca_parsed && (
                        <div className="ctx-rca-bridge-detail">
                          <span className="ctx-sub-title">Symptom → Metric → Root Cause</span>
                          {sec.rca_parsed.map((rca, k) => (
                            <div className="ctx-rca-bridge-row" key={k}>
                              <span className="ctx-rca-symptom">{rca.symptom}</span>
                              {rca.metric && <span className="ctx-rca-arrow">→ {rca.metric}</span>}
                              {rca.root_area && <span className="ctx-rca-root">→ {rca.root_area}</span>}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  );
                })}
                {data.rca_diagnostic_context.strategies && (
                  <div className="ctx-dynamic-section">
                    <div className="ctx-dynamic-section-header">
                      <span>📋 Strategies & Frameworks</span>
                    </div>
                    <pre className="ctx-context-block-body">
                      {data.rca_diagnostic_context.strategies}
                    </pre>
                  </div>
                )}
              </CollapsibleSection>
            )}

            {/* LLM Calls */}
            <CollapsibleSection
              title="Prompts Fired"
              icon={Zap}
              defaultOpen={true}
              count={data.llm_call_log?.length || 0}
            >
              {(!data.llm_call_log || data.llm_call_log.length === 0) ? (
                <div className="ctx-empty">No LLM calls yet — start the conversation</div>
              ) : (
                <div className="ctx-llm-list">
                  {data.llm_call_log?.map((entry, i) => (
                    <LLMCallCard key={i} entry={entry} index={i} />
                  ))}
                </div>
              )}
            </CollapsibleSection>

            {/* Playbook Progress */}
            {data.playbook_stage && data.playbook_stage !== 'not_started' && (
              <CollapsibleSection title="AI Playbook" icon={Zap} defaultOpen={true}>
                <div className="ctx-context-grid">
                  <div className="ctx-kv">
                    <span className="ctx-key">Stage</span>
                    <span className="ctx-val">
                      <span className={`ctx-crawl-status ${data.playbook_complete ? 'complete' : 'in_progress'}`}>
                        {data.playbook_stage}
                      </span>
                    </span>
                  </div>
                  {data.playbook_complete !== undefined && (
                    <div className="ctx-kv">
                      <span className="ctx-key">Complete</span>
                      <span className="ctx-val">{data.playbook_complete ? '✓ Yes' : 'In progress...'}</span>
                    </div>
                  )}
                </div>

                {/* Agent outputs summary */}
                {[
                  { key: 'playbook_agent1_output', label: 'Agent 1: Context Brief', icon: '📝' },
                  { key: 'playbook_agent2_output', label: 'Agent 2: ICP Card', icon: '👤' },
                  { key: 'playbook_agent3_output', label: 'Agent 3: Playbook', icon: '📋' },
                  { key: 'playbook_agent4_output', label: 'Agent 4: Tool Matrix', icon: '🛠' },
                  { key: 'playbook_agent5_output', label: 'Agent 5: Website Audit', icon: '🌐' },
                ].map(agent => (
                  data[agent.key] ? (
                    <div className="ctx-sub-section" key={agent.key}>
                      <span className="ctx-sub-title">{agent.icon} {agent.label}</span>
                      <pre className="ctx-context-block-body" style={{ maxHeight: '200px', overflow: 'auto', fontSize: '0.75rem' }}>
                        {data[agent.key].slice(0, 1000)}{data[agent.key].length > 1000 ? '...' : ''}
                      </pre>
                    </div>
                  ) : null
                ))}

                {/* Latencies */}
                {data.playbook_latencies && Object.keys(data.playbook_latencies).length > 0 && (
                  <div className="ctx-sub-section">
                    <span className="ctx-sub-title">⏱ Agent Latencies</span>
                    <div className="ctx-context-grid">
                      {Object.entries(data.playbook_latencies).map(([agent, ms]) => (
                        <div className="ctx-kv" key={agent}>
                          <span className="ctx-key">{agent}</span>
                          <span className="ctx-val">{(ms / 1000).toFixed(1)}s</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </CollapsibleSection>
            )}

            {/* All Q&A */}
            <CollapsibleSection
              title="All Q&A History"
              icon={Brain}
              count={data.questions_answers?.length || 0}
            >
              {data.questions_answers?.map((qa, i) => (
                <div className="ctx-qa-pair" key={i}>
                  <div className="ctx-qa-q">
                    <span className={`ctx-qa-type ${qa.type}`}>{qa.type}</span>
                    {qa.question}
                  </div>
                  <div className="ctx-qa-a">{qa.answer}</div>
                </div>
              ))}
            </CollapsibleSection>
          </>
        )}
      </div>
    </div>
  );
}
