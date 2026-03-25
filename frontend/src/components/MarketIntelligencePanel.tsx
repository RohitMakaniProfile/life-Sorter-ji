import { useState, useCallback } from 'react';
import { 
  Search, 
  Globe, 
  TrendingUp, 
  Loader2, 
  CheckCircle, 
  AlertCircle, 
  MapPin,
  Calendar,
  Building2,
  Sparkles,
  ChevronDown,
  ChevronUp,
  ExternalLink,
  Target,
  Users,
  Zap,
  FileText,
  Share2,
  Megaphone,
  BarChart3,
  Star,
  MessageCircle,
  Link,
  ShoppingBag,
  Award
} from 'lucide-react';
import './MarketIntelligencePanel.css';

/**
 * Market Intelligence Panel Component
 * ===================================
 * Testing panel for the Market Intelligence Entity
 * Shows 4-phase analysis results
 */

const MarketIntelligencePanel = () => {
  // Form state
  const [service, setService] = useState('');
  const [location, setLocation] = useState('IN');
  const [year, setYear] = useState(new Date().getFullYear());
  
  // Execution state
  const [isLoading, setIsLoading] = useState(false);
  const [currentPhase, setCurrentPhase] = useState('');
  const [results, setResults] = useState(null);
  const [error, setError] = useState(null);
  
  // UI state - expanded sections for each phase
  const [expandedSections, setExpandedSections] = useState({
    executiveSummary: true,
    phase1: true,
    phase2: true,
    phase3: true,
    phase4: true,
    recommendations: true
  });

  // Location options
  const locationOptions = [
    { code: 'US', name: 'United States' },
    { code: 'UK', name: 'United Kingdom' },
    { code: 'IN', name: 'India' },
    { code: 'CA', name: 'Canada' },
    { code: 'AU', name: 'Australia' },
    { code: 'DE', name: 'Germany' },
    { code: 'FR', name: 'France' }
  ];

  // Toggle section expansion
  const toggleSection = (section) => {
    setExpandedSections(prev => ({
      ...prev,
      [section]: !prev[section]
    }));
  };

  // Execute market intelligence analysis
  const handleExecute = useCallback(async () => {
    if (!service.trim()) {
      setError('Please enter a service or product to analyze');
      return;
    }

    setIsLoading(true);
    setError(null);
    setResults(null);
    setCurrentPhase('Initializing...');

    try {
      // Phase progress simulation while API call is in progress
      const phases = [
        'SERP Discovery...',
        'Analyzing competitors...',
        'Extracting insights...',
        'Running AI analysis...',
        'Generating report...'
      ];
      
      let phaseIndex = 0;
      const phaseInterval = setInterval(() => {
        if (phaseIndex < phases.length) {
          setCurrentPhase(phases[phaseIndex]);
          phaseIndex++;
        }
      }, 3000);

      // Call the backend API instead of importing Node.js modules
      const apiUrl = import.meta.env.VITE_API_URL || '';
      const response = await fetch(`${apiUrl}/api/market-intelligence`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          service: service.trim(),
          location,
          year
        }),
      });

      clearInterval(phaseInterval);

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.message || 'Analysis failed');
      }

      const result = await response.json();
      
      setCurrentPhase('Complete!');
      setResults(result.data);
      
    } catch (err) {
      console.error('Market Intelligence Error:', err);
      setError(err.message || 'An error occurred during analysis');
    } finally {
      setIsLoading(false);
    }
  }, [service, location, year]);

  // Render confidence badge
  const renderConfidenceBadge = (confidence) => {
    const percentage = Math.round((confidence || 0) * 100);
    const colorClass = percentage >= 70 ? 'high' : percentage >= 40 ? 'medium' : 'low';
    return (
      <span className={`mi-confidence-badge ${colorClass}`}>
        {percentage}% confident
      </span>
    );
  };

  // Render competitor card for Phase 4
  const renderCompetitorCard = (competitor, index) => (
    <div key={index} className="mi-competitor-card">
      <div className="mi-competitor-header">
        <div className="mi-competitor-rank">#{competitor.rank || index + 1}</div>
        <div className="mi-competitor-info">
          <h4>{competitor.name || competitor.domain || `Competitor ${index + 1}`}</h4>
          {competitor.domain && (
            <a 
              href={`https://${competitor.domain}`} 
              target="_blank" 
              rel="noopener noreferrer"
              className="mi-competitor-link"
            >
              {competitor.domain} <ExternalLink size={12} />
            </a>
          )}
        </div>
      </div>
      
      {competitor.positioning && (
        <p className="mi-competitor-positioning">{competitor.positioning}</p>
      )}
      
      {competitor.primary_offerings && competitor.primary_offerings.length > 0 && (
        <div className="mi-competitor-offerings">
          <strong>Key Offerings:</strong> {competitor.primary_offerings.slice(0, 3).join(', ')}
        </div>
      )}
      
      {competitor.gbp_info && (
        <div className="mi-competitor-gbp">
          <Star size={14} className="star-icon" /> {competitor.gbp_info.rating}★ ({competitor.gbp_info.reviews} reviews)
        </div>
      )}
      
      <div className="mi-competitor-stats">
        {competitor.why_picked && competitor.why_picked.length > 0 && (
          <span className="mi-stat">
            <CheckCircle size={12} /> {competitor.why_picked.slice(0, 2).join(', ')}
          </span>
        )}
        {competitor.score && (
          <span className="mi-stat">
            <BarChart3 size={12} /> Score: {Math.round(competitor.score * 100)}%
          </span>
        )}
      </div>
    </div>
  );

  return (
    <div className="mi-panel">
      <div className="mi-panel-header">
        <div className="mi-panel-icon">
          <TrendingUp size={20} />
        </div>
        <div>
          <h3>Market Intelligence</h3>
          <p>SERP-driven competitor analysis</p>
        </div>
      </div>

      {/* Input Form */}
      <div className="mi-form">
        <div className="mi-input-group">
          <label>
            <Target size={14} />
            Service / Product
          </label>
          <input
            type="text"
            value={service}
            onChange={(e) => setService(e.target.value)}
            placeholder="e.g., AI chatbot for restaurants"
            disabled={isLoading}
          />
        </div>

        <div className="mi-input-row">
          <div className="mi-input-group">
            <label>
              <MapPin size={14} />
              Location
            </label>
            <select 
              value={location} 
              onChange={(e) => setLocation(e.target.value)}
              disabled={isLoading}
            >
              {locationOptions.map(loc => (
                <option key={loc.code} value={loc.code}>{loc.name}</option>
              ))}
            </select>
          </div>

          <div className="mi-input-group">
            <label>
              <Calendar size={14} />
              Year
            </label>
            <input
              type="number"
              value={year}
              onChange={(e) => setYear(parseInt(e.target.value))}
              min={2020}
              max={2030}
              disabled={isLoading}
            />
          </div>
        </div>

        <button 
          className="mi-execute-btn"
          onClick={handleExecute}
          disabled={isLoading || !service.trim()}
        >
          {isLoading ? (
            <>
              <Loader2 size={16} className="mi-spinner" />
              {currentPhase}
            </>
          ) : (
            <>
              <Sparkles size={16} />
              Run Analysis
            </>
          )}
        </button>
      </div>

      {/* Error Display */}
      {error && (
        <div className="mi-error">
          <AlertCircle size={16} />
          <span>{error}</span>
        </div>
      )}

      {/* Results Display */}
      {results && (
        <div className="mi-results">
          {/* Overall Summary */}
          <div className="mi-overall-summary">
            <div className="mi-summary-header">
              <h3><Award size={18} /> Market Intelligence Report</h3>
              {renderConfidenceBadge(results.overall_confidence)}
            </div>
            {results.summary && (
              <div className="mi-summary-quick">
                <span><Building2 size={14} /> {results.summary.business_name || 'Business'}</span>
                <span><Globe size={14} /> {results.summary.category || 'Unknown Category'}</span>
              </div>
            )}
          </div>

          {/* Phase Confidence Overview */}
          {results.phase_confidences && (
            <div className="mi-phase-overview">
              <div className="mi-phase-badges">
                <span className="mi-phase-badge phase1">
                  Phase 1: {Math.round((results.phase_confidences.phase1_website_extraction || 0) * 100)}%
                </span>
                <span className="mi-phase-badge phase2">
                  Phase 2: {Math.round((results.phase_confidences.phase2_external_presence || 0) * 100)}%
                </span>
                <span className="mi-phase-badge phase3">
                  Phase 3: {Math.round((results.phase_confidences.phase3_marketing_conversion || 0) * 100)}%
                </span>
                <span className="mi-phase-badge phase4">
                  Phase 4: {Math.round((results.phase_confidences.phase4_competitor_analysis || 0) * 100)}%
                </span>
              </div>
            </div>
          )}

          {/* PHASE 1: Website Extraction */}
          {results.phase_outputs?.phase1 && (
            <div className="mi-section mi-phase-section">
              <button 
                className="mi-section-header phase1-header"
                onClick={() => toggleSection('phase1')}
              >
                <div className="mi-section-title">
                  <Globe size={16} />
                  <span>Phase 1: Website Extraction</span>
                  {renderConfidenceBadge(results.phase_outputs.phase1.overall_confidence)}
                </div>
                {expandedSections.phase1 ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
              </button>
              {expandedSections.phase1 && (
                <div className="mi-section-content">
                  {/* Business Identity */}
                  {results.phase_outputs.phase1.business_identity && (
                    <div className="mi-subsection">
                      <h5><Building2 size={14} /> Business Identity</h5>
                      <div className="mi-data-grid">
                        <div className="mi-data-item">
                          <label>Name:</label>
                          <span>{results.phase_outputs.phase1.business_identity.name?.value || 'N/A'}</span>
                        </div>
                        <div className="mi-data-item">
                          <label>Category:</label>
                          <span>{results.phase_outputs.phase1.business_identity.category?.value || 'N/A'}</span>
                        </div>
                        <div className="mi-data-item">
                          <label>Location:</label>
                          <span>
                            {results.phase_outputs.phase1.business_identity.location?.city || ''} 
                            {results.phase_outputs.phase1.business_identity.location?.country ? `, ${results.phase_outputs.phase1.business_identity.location.country}` : ''}
                          </span>
                        </div>
                      </div>
                    </div>
                  )}

                  {/* Primary Offerings */}
                  {results.phase_outputs.phase1.primary_offerings && results.phase_outputs.phase1.primary_offerings.length > 0 && (
                    <div className="mi-subsection">
                      <h5><ShoppingBag size={14} /> Primary Offerings</h5>
                      <ul className="mi-offerings-list">
                        {results.phase_outputs.phase1.primary_offerings.slice(0, 5).map((offering, i) => (
                          <li key={i}>
                            <span className="offering-name">{offering.name}</span>
                            {offering.confidence && (
                              <span className="offering-confidence">
                                {Math.round(offering.confidence * 100)}%
                              </span>
                            )}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {/* Proof Assets */}
                  {results.phase_outputs.phase1.proof_assets && results.phase_outputs.phase1.proof_assets.length > 0 && (
                    <div className="mi-subsection">
                      <h5><Award size={14} /> Proof Assets ({results.phase_outputs.phase1.proof_assets.length})</h5>
                      <div className="mi-proof-list">
                        {results.phase_outputs.phase1.proof_assets.slice(0, 5).map((proof, i) => (
                          <span key={i} className="mi-proof-tag">{proof.type}: {proof.description || proof.value}</span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {/* PHASE 2: External Presence */}
          {results.phase_outputs?.phase2 && (
            <div className="mi-section mi-phase-section">
              <button 
                className="mi-section-header phase2-header"
                onClick={() => toggleSection('phase2')}
              >
                <div className="mi-section-title">
                  <Share2 size={16} />
                  <span>Phase 2: External Presence & Social Perception</span>
                  {renderConfidenceBadge(results.phase_outputs.phase2.overall_confidence)}
                </div>
                {expandedSections.phase2 ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
              </button>
              {expandedSections.phase2 && (
                <div className="mi-section-content">
                  {/* Profiles Discovered */}
                  <div className="mi-subsection">
                    <h5><Link size={14} /> Profiles Discovered: {results.phase_outputs.phase2.profiles_discovered || 0}</h5>
                    
                    {/* Social Profiles */}
                    {results.phase_outputs.phase2.profiles?.social && results.phase_outputs.phase2.profiles.social.length > 0 && (
                      <div className="mi-social-profiles">
                        {results.phase_outputs.phase2.profiles.social.map((profile, i) => (
                          <div key={i} className="mi-social-item">
                            <span className="platform">{profile.platform}</span>
                            {profile.followers && <span className="followers">{profile.followers} followers</span>}
                            {profile.url && (
                              <a href={profile.url} target="_blank" rel="noopener noreferrer">
                                <ExternalLink size={12} />
                              </a>
                            )}
                          </div>
                        ))}
                      </div>
                    )}
                    
                    {/* Google Business Profile */}
                    {results.phase_outputs.phase2.profiles?.google_business_profile && (
                      <div className="mi-gbp-info">
                        <Star size={14} className="star-icon" />
                        <span>Google Business: {results.phase_outputs.phase2.profiles.google_business_profile.rating}★</span>
                        <span>({results.phase_outputs.phase2.profiles.google_business_profile.review_count} reviews)</span>
                      </div>
                    )}
                  </div>

                  {/* Sentiment Themes */}
                  {results.phase_outputs.phase2.sentiment_themes && results.phase_outputs.phase2.sentiment_themes.length > 0 && (
                    <div className="mi-subsection">
                      <h5><MessageCircle size={14} /> Sentiment Themes</h5>
                      <div className="mi-themes-list">
                        {results.phase_outputs.phase2.sentiment_themes.slice(0, 5).map((theme, i) => (
                          <div key={i} className={`mi-theme-item sentiment-${theme.sentiment || 'neutral'}`}>
                            <span className="theme-name">"{theme.theme}"</span>
                            <span className="theme-sentiment">{theme.sentiment}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {/* PHASE 3: Marketing & Conversion */}
          {results.phase_outputs?.phase3 && (
            <div className="mi-section mi-phase-section">
              <button 
                className="mi-section-header phase3-header"
                onClick={() => toggleSection('phase3')}
              >
                <div className="mi-section-title">
                  <Megaphone size={16} />
                  <span>Phase 3: Marketing & Conversion</span>
                  {renderConfidenceBadge(results.phase_outputs.phase3.overall_confidence)}
                </div>
                {expandedSections.phase3 ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
              </button>
              {expandedSections.phase3 && (
                <div className="mi-section-content">
                  {/* CTAs */}
                  <div className="mi-subsection">
                    <h5><Target size={14} /> CTAs Detected: {results.phase_outputs.phase3.total_ctas || 0}</h5>
                    <p className="mi-sales-process">
                      Sales Process: <strong>{results.phase_outputs.phase3.sales_process_type || 'Unknown'}</strong>
                    </p>
                  </div>

                  {/* Tracking & Ad Platforms */}
                  {results.phase_outputs.phase3.marketing_infrastructure && (
                    <div className="mi-subsection">
                      <h5><BarChart3 size={14} /> Marketing Infrastructure</h5>
                      <div className="mi-infra-list">
                        {results.phase_outputs.phase3.marketing_infrastructure.tracking_tags && (
                          <span className="mi-tag">
                            Tracking: {results.phase_outputs.phase3.marketing_infrastructure.tracking_tags.join(', ') || 'None'}
                          </span>
                        )}
                        {results.phase_outputs.phase3.marketing_infrastructure.ad_platform_signals && (
                          <span className="mi-tag">
                            Ad Platforms: {results.phase_outputs.phase3.marketing_infrastructure.ad_platform_signals.length || 0}
                          </span>
                        )}
                      </div>
                    </div>
                  )}

                  {/* Landing Pages */}
                  {results.phase_outputs.phase3.landing_pages && results.phase_outputs.phase3.landing_pages.length > 0 && (
                    <div className="mi-subsection">
                      <h5><FileText size={14} /> Landing Pages ({results.phase_outputs.phase3.landing_pages.length})</h5>
                      <ul className="mi-landing-list">
                        {results.phase_outputs.phase3.landing_pages.slice(0, 3).map((page, i) => (
                          <li key={i}>
                            {page.headline || page.url || `Page ${i + 1}`}
                            {page.primary_ctas && <span className="cta-count">({page.primary_ctas.length} CTAs)</span>}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {/* PHASE 4: Competitor Analysis */}
          {results.phase_outputs?.phase4 && (
            <div className="mi-section mi-phase-section">
              <button 
                className="mi-section-header phase4-header"
                onClick={() => toggleSection('phase4')}
              >
                <div className="mi-section-title">
                  <Users size={16} />
                  <span>Phase 4: Competitor Analysis</span>
                  {renderConfidenceBadge(results.phase_outputs.phase4.overall_confidence)}
                </div>
                {expandedSections.phase4 ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
              </button>
              {expandedSections.phase4 && (
                <div className="mi-section-content">
                  {results.phase_outputs.phase4.competitors && results.phase_outputs.phase4.competitors.length > 0 ? (
                    <div className="mi-competitors-list">
                      {results.phase_outputs.phase4.competitors.map((competitor, i) => renderCompetitorCard(competitor, i))}
                    </div>
                  ) : (
                    <p className="mi-no-data">No competitors identified</p>
                  )}
                </div>
              )}
            </div>
          )}

          {/* Executive Summary / Report Markdown */}
          {results.report_markdown && (
            <div className="mi-section mi-phase-section">
              <button 
                className="mi-section-header summary-header"
                onClick={() => toggleSection('executiveSummary')}
              >
                <div className="mi-section-title">
                  <FileText size={16} />
                  <span>Executive Summary & Recommendations</span>
                </div>
                {expandedSections.executiveSummary ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
              </button>
              {expandedSections.executiveSummary && (
                <div className="mi-section-content mi-report-markdown">
                  <pre className="mi-markdown-content">{results.report_markdown}</pre>
                </div>
              )}
            </div>
          )}

          {/* Execution Info */}
          {results.report_id && (
            <div className="mi-execution-info">
              <small>Report ID: {results.report_id} | Generated: {new Date(results.generated_at).toLocaleString()}</small>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default MarketIntelligencePanel;
