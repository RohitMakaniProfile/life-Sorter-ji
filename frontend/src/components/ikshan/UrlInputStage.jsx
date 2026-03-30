import { useState } from 'react';
import FlowNode from './FlowNode';
import ToolCard from './ToolCard';
import './UrlInputStage.css';

/**
 * Step 2.1 — URL input + "Best Tools For You" early recommendations
 *
 * Props:
 *   domain               – selected domain name (shown as origin node)
 *   earlyTools           – array of { name, rating, description, bullets, tag, url }
 *   onSubmitUrl(url)     – called with the validated URL
 *   onSkip()             – skip URL input
 *   onBack()             – go back
 */
export default function UrlInputStage({ domain, earlyTools = [], onSubmitUrl, onSkip, onBack }) {
  const [urlTab, setUrlTab] = useState('website'); // 'website' | 'gbp'
  const [urlValue, setUrlValue] = useState('');
  const [email, setEmail] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!urlValue.trim()) return;

    let finalUrl = urlValue.trim();
    if (!/^https?:\/\//i.test(finalUrl)) {
      finalUrl = `https://${finalUrl}`;
    }

    setSubmitting(true);
    try {
      await onSubmitUrl(finalUrl, email.trim());
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="ik-url">
      {/* Hero */}
      <div className="ik-url__hero">
        <h1 className="ik-url__title">
          Get Business <span className="ik-url__accent-purple">Audit</span> report and{' '}
          <span className="ik-url__accent-gold">Playbook</span>
        </h1>
      </div>

      {/* Chain: domain node → connector → form */}
      <div className="ik-url__chain">
        <FlowNode label={domain} variant="light" />

        <svg className="ik-url__connector" viewBox="0 0 80 2" preserveAspectRatio="none">
          <line x1="0" y1="1" x2="70" y2="1" stroke="rgba(255,255,255,0.35)" strokeWidth="2" />
          <polygon points="70,0 80,1 70,2" fill="rgba(255,255,255,0.35)" />
        </svg>

        {/* URL Form Card */}
        <form className="ik-url__form-card" onSubmit={handleSubmit}>
          {/* Tabs */}
          <div className="ik-url__tabs">
            <button
              type="button"
              className={`ik-url__tab ${urlTab === 'website' ? 'ik-url__tab--active' : ''}`}
              onClick={() => setUrlTab('website')}
            >
              Website URL
            </button>
            <button
              type="button"
              className={`ik-url__tab ${urlTab === 'gbp' ? 'ik-url__tab--active' : ''}`}
              onClick={() => setUrlTab('gbp')}
            >
              Google Business Profile URI
            </button>
          </div>

          <input
            className="ik-url__input"
            type="text"
            placeholder={urlTab === 'website' ? 'yourcompany.com' : 'Google Business Profile URL'}
            value={urlValue}
            onChange={(e) => setUrlValue(e.target.value)}
            autoFocus
          />

          <input
            className="ik-url__input"
            type="email"
            placeholder="Enter your work email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />

          <button className="ik-url__submit-btn" type="submit" disabled={submitting || !urlValue.trim()}>
            {submitting ? 'Analyzing...' : 'Analyze My Business'}
          </button>

          <button type="button" className="ik-url__skip" onClick={onSkip}>
            Skip - without URLs, we'll give general recommendations
          </button>
        </form>
      </div>

      {/* Early Tool Recommendations */}
      {earlyTools.length > 0 && (
        <div className="ik-url__tools-section">
          <h2 className="ik-url__tools-heading">Best Tools For You</h2>
          <div className="ik-url__tools-scroll">
            {earlyTools.map((tool, i) => (
              <ToolCard
                key={i}
                name={tool.name}
                rating={tool.rating}
                description={tool.description}
                bullets={tool.bullets || []}
                tag={tool.tag || tool.category}
                url={tool.url}
              />
            ))}
          </div>
        </div>
      )}

      {/* Back */}
      <button className="ik-url__back" onClick={onBack}>
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
          <path d="M10 13L5 8L10 3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
        </svg>
        Step 1
      </button>
    </div>
  );
}
