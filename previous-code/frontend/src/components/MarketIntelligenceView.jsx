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
  Download,
  RefreshCw,
  Eye,
  Shield,
  DollarSign,
  MessageSquare,
  Star,
  ArrowRight,
  Clock,
  BarChart3,
  Lightbulb,
  AlertTriangle
} from 'lucide-react';
import './MarketIntelligenceView.css';

/**
 * Market Intelligence Full View Component
 * =======================================
 * Full-screen view for business website analysis
 * Provides comprehensive competitive intelligence report
 */

const MarketIntelligenceView = () => {
  // Form state
  const [websiteUrl, setWebsiteUrl] = useState('');
  const [businessDescription, setBusinessDescription] = useState('');
  const [location, setLocation] = useState('US');
  
  // Execution state
  const [isLoading, setIsLoading] = useState(false);
  const [currentPhase, setCurrentPhase] = useState('');
  const [phaseProgress, setPhaseProgress] = useState(0);
  const [results, setResults] = useState(null);
  const [error, setError] = useState(null);
  
  // UI state
  const [expandedSections, setExpandedSections] = useState({
    overview: true,
    competitors: true,
    userIntent: false,
    positioning: false,
    opportunities: false,
    recommendations: false
  });

  // Location options
  const locationOptions = [
    { code: 'US', name: 'United States' },
    { code: 'UK', name: 'United Kingdom' },
    { code: 'IN', name: 'India' },
    { code: 'CA', name: 'Canada' },
    { code: 'AU', name: 'Australia' },
    { code: 'DE', name: 'Germany' },
    { code: 'FR', name: 'France' },
    { code: 'Global', name: 'Global' }
  ];

  // Analysis phases
  const phases = [
    { id: 'init', label: 'Initializing analysis...', icon: RefreshCw },
    { id: 'serp', label: 'Scanning SERP results...', icon: Search },
    { id: 'competitors', label: 'Identifying competitors...', icon: Users },
    { id: 'scraping', label: 'Analyzing competitor websites...', icon: Globe },
    { id: 'intent', label: 'Understanding user intent...', icon: Target },
    { id: 'comparison', label: 'Building competitive comparison...', icon: BarChart3 },
    { id: 'report', label: 'Generating insights report...', icon: FileText }
  ];

  // Toggle section expansion
  const toggleSection = (section) => {
    setExpandedSections(prev => ({
      ...prev,
      [section]: !prev[section]
    }));
  };

  // Extract domain from URL
  const extractDomain = (url) => {
    try {
      let domain = url.replace(/^(https?:\/\/)?(www\.)?/, '');
      domain = domain.split('/')[0];
      return domain;
    } catch {
      return url;
    }
  };

  // Execute market intelligence analysis
  const handleExecute = useCallback(async () => {
    if (!websiteUrl.trim() && !businessDescription.trim()) {
      setError('Please enter a website URL or describe your business');
      return;
    }

    setIsLoading(true);
    setError(null);
    setResults(null);
    setPhaseProgress(0);

    try {
      // Animate through phases while API call is in progress
      const phaseAnimation = async () => {
        for (let i = 0; i < phases.length; i++) {
          setCurrentPhase(phases[i].id);
          setPhaseProgress(((i + 1) / phases.length) * 100);
          await new Promise(resolve => setTimeout(resolve, 1500));
        }
      };

      // Start phase animation
      const animationPromise = phaseAnimation();
      
      // Build service description from inputs
      const serviceQuery = businessDescription.trim() 
        || `Business website: ${extractDomain(websiteUrl)}`;

      // Call the backend API instead of importing Node.js modules
      const apiUrl = import.meta.env.VITE_API_URL || '';
      const response = await fetch(`${apiUrl}/api/market-intelligence`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          service: serviceQuery,
          location,
          year: new Date().getFullYear(),
          targetWebsite: websiteUrl.trim() || null
        }),
      });

      // Wait for animation to complete
      await animationPromise;

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.message || 'Analysis failed');
      }

      const result = await response.json();
      const executionResults = result.data;

      // Debug logging
      console.log('=== RAW API RESPONSE ===');
      console.log('Full result:', result);
      console.log('Execution results:', executionResults);
      console.log('Phase outputs:', executionResults?.phase_outputs);
      console.log('Phase confidences:', executionResults?.phase_confidences);

      // Enhance results with mock data for demo if needed
      const enhancedResults = enhanceResultsForDisplay(executionResults, websiteUrl);
      
      console.log('=== ENHANCED RESULTS ===');
      console.log('Enhanced:', enhancedResults);
      
      setCurrentPhase('complete');
      setPhaseProgress(100);
      setResults(enhancedResults);
      
    } catch (err) {
      console.error('Market Intelligence Error:', err);
      setError(err.message || 'An error occurred during analysis');
    } finally {
      setIsLoading(false);
    }
  }, [websiteUrl, businessDescription, location]);

  // Enhance results with display-friendly data
  const enhanceResultsForDisplay = (raw, targetUrl) => {
    const domain = extractDomain(targetUrl || '');
    
    // Handle new 4-phase data structure from enhanced orchestrator
    const phase1 = raw?.phase_outputs?.phase1 || {};
    const phase2 = raw?.phase_outputs?.phase2 || {};
    const phase3 = raw?.phase_outputs?.phase3 || {};
    const phase4 = raw?.phase_outputs?.phase4 || {};
    
    // Extract competitor data from Phase 4
    const competitors = (phase4.competitors || []).map(c => ({
      name: c.name || c.domain,
      domain: c.domain,
      positioning: c.positioning,
      primary_offerings: c.primary_offerings || [],
      gbp_info: c.gbp_info,
      why_picked: c.why_picked || [],
      score: c.score || 0,
      rank: c.rank
    }));
    
    return {
      ...raw,
      targetBusiness: {
        domain: domain || phase1.business_identity?.name?.value || 'Your Business',
        analyzedAt: raw.generated_at || new Date().toISOString(),
        location: location
      },
      summary: {
        competitorsFound: competitors.length,
        serpResultsAnalyzed: raw.summary?.metrics?.total_ctas || phase3.total_ctas || 0,
        marketPosition: competitors.length > 0 ? 'Competitive' : 'Emerging',
        opportunityScore: Math.round((raw.overall_confidence || 0.7) * 100),
        overallConfidence: raw.overall_confidence || 0
      },
      // Phase outputs for detailed display
      phaseOutputs: raw.phase_outputs,
      phaseConfidences: raw.phase_confidences || {},
      
      // Business Identity from Phase 1
      businessIdentity: phase1.business_identity || {},
      primaryOfferings: phase1.primary_offerings || [],
      proofAssets: phase1.proof_assets || [],
      
      // External Presence from Phase 2
      externalProfiles: phase2.profiles || {},
      sentimentThemes: phase2.sentiment_themes || [],
      profilesDiscovered: phase2.profiles_discovered || 0,
      
      // Marketing from Phase 3
      marketingInfra: phase3.marketing_infrastructure || {},
      totalCTAs: phase3.total_ctas || 0,
      salesProcessType: phase3.sales_process_type || 'Unknown',
      landingPages: phase3.landing_pages || [],
      
      // Competitors from Phase 4
      competitors: competitors,
      
      // Report markdown
      reportMarkdown: raw.report_markdown || '',
      
      // Intent Analysis (fallback for legacy compatibility)
      intentAnalysis: {
        intentClusters: phase2.sentiment_themes?.map(t => ({ name: t.theme, sentiment: t.sentiment })) || 
          ['Solution seekers', 'Price comparers', 'Feature researchers'],
        clickabilityFactors: phase3.landing_pages?.flatMap(lp => lp.primary_ctas || []).slice(0, 4) ||
          ['Clear value proposition', 'Social proof', 'Pricing transparency'],
        attractiveLanguage: phase1.primary_offerings?.map(o => o.name).slice(0, 5) ||
          ['AI-powered', 'Save time', 'Easy to use', 'Free trial']
      },
      positioning: phase4.competitive_insights?.market_gaps || [
        'Emphasize unique differentiators',
        'Add more social proof',
        'Highlight pricing advantages'
      ],
      recommendations: [
        { priority: 'high', action: 'Optimize website based on Phase 1 findings', impact: 'Improve business identity clarity' },
        { priority: 'high', action: 'Strengthen external presence (Phase 2)', impact: 'Build trust and credibility' },
        { priority: 'medium', action: 'Optimize CTAs and conversion paths (Phase 3)', impact: 'Improve conversion rate' },
        { priority: 'medium', action: 'Address competitive gaps (Phase 4)', impact: 'Differentiate from competitors' },
        { priority: 'low', action: 'Review full report for detailed insights', impact: 'Strategic planning' }
      ]
    };
  };

  // Reset form
  const handleReset = () => {
    setWebsiteUrl('');
    setBusinessDescription('');
    setResults(null);
    setError(null);
    setCurrentPhase('');
    setPhaseProgress(0);
  };

  // Render loading state
  const renderLoadingState = () => (
    <div className="miv-loading-container">
      <div className="miv-loading-card">
        <div className="miv-loading-icon">
          <Loader2 size={48} className="miv-spinner" />
        </div>
        <h2>Analyzing Your Market</h2>
        <p>This typically takes 30-60 seconds</p>
        
        <div className="miv-progress-bar">
          <div 
            className="miv-progress-fill" 
            style={{ width: `${phaseProgress}%` }}
          />
        </div>
        
        <div className="miv-phases-list">
          {phases.map((phase, index) => {
            const PhaseIcon = phase.icon;
            const isActive = currentPhase === phase.id;
            const isComplete = phases.findIndex(p => p.id === currentPhase) > index;
            
            return (
              <div 
                key={phase.id} 
                className={`miv-phase-item ${isActive ? 'active' : ''} ${isComplete ? 'complete' : ''}`}
              >
                <div className="miv-phase-icon">
                  {isComplete ? <CheckCircle size={16} /> : <PhaseIcon size={16} />}
                </div>
                <span>{phase.label}</span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );

  // Render results
  const renderResults = () => (
    <div className="miv-results">
      {/* Report Header */}
      <div className="miv-report-header">
        <div className="miv-report-title">
          <div className="miv-report-icon">
            <BarChart3 size={24} />
          </div>
          <div>
            <h1>Market Intelligence Report</h1>
            <p>
              <Globe size={14} /> {results.targetBusiness?.domain || 'Your Business'} 
              <span className="miv-separator">•</span>
              <MapPin size={14} /> {locationOptions.find(l => l.code === location)?.name}
              <span className="miv-separator">•</span>
              <Clock size={14} /> {new Date().toLocaleDateString()}
            </p>
          </div>
        </div>
        <div className="miv-report-actions">
          <button className="miv-btn-secondary" onClick={handleReset}>
            <RefreshCw size={16} /> New Analysis
          </button>
        </div>
      </div>

      {/* Summary Cards */}
      <div className="miv-summary-grid">
        <div className="miv-summary-card">
          <div className="miv-summary-icon competitors">
            <Users size={20} />
          </div>
          <div className="miv-summary-content">
            <span className="miv-summary-value">{results.summary?.competitorsFound || 0}</span>
            <span className="miv-summary-label">Competitors Found</span>
          </div>
        </div>
        <div className="miv-summary-card">
          <div className="miv-summary-icon serp">
            <Search size={20} />
          </div>
          <div className="miv-summary-content">
            <span className="miv-summary-value">{results.totalCTAs || 0}</span>
            <span className="miv-summary-label">CTAs Detected</span>
          </div>
        </div>
        <div className="miv-summary-card">
          <div className="miv-summary-icon position">
            <TrendingUp size={20} />
          </div>
          <div className="miv-summary-content">
            <span className="miv-summary-value">{results.summary?.marketPosition || 'N/A'}</span>
            <span className="miv-summary-label">Market Position</span>
          </div>
        </div>
        <div className="miv-summary-card highlight">
          <div className="miv-summary-icon opportunity">
            <Lightbulb size={20} />
          </div>
          <div className="miv-summary-content">
            <span className="miv-summary-value">{results.summary?.opportunityScore || 0}%</span>
            <span className="miv-summary-label">Confidence Score</span>
          </div>
        </div>
      </div>

      {/* Phase Confidence Overview */}
      {results.phaseConfidences && (
        <div className="miv-phase-overview">
          <div className="miv-phase-badges">
            <span className="miv-phase-badge phase1">
              Phase 1: {Math.round((results.phaseConfidences.phase1_website_extraction || 0) * 100)}%
            </span>
            <span className="miv-phase-badge phase2">
              Phase 2: {Math.round((results.phaseConfidences.phase2_external_presence || 0) * 100)}%
            </span>
            <span className="miv-phase-badge phase3">
              Phase 3: {Math.round((results.phaseConfidences.phase3_marketing_conversion || 0) * 100)}%
            </span>
            <span className="miv-phase-badge phase4">
              Phase 4: {Math.round((results.phaseConfidences.phase4_competitor_analysis || 0) * 100)}%
            </span>
          </div>
        </div>
      )}

      {/* PHASE 1: Business Identity */}
      {results.businessIdentity && (
        <div className="miv-section">
          <button 
            className="miv-section-header phase1-header"
            onClick={() => toggleSection('overview')}
          >
            <div className="miv-section-title">
              <Building2 size={18} />
              <span>Phase 1: Website Extraction</span>
              <span className="miv-confidence-badge">
                {Math.round((results.phaseConfidences?.phase1_website_extraction || 0) * 100)}% confident
              </span>
            </div>
            {expandedSections.overview ? <ChevronUp size={18} /> : <ChevronDown size={18} />}
          </button>
          {expandedSections.overview && (
            <div className="miv-section-content">
              <div className="miv-data-grid">
                <div className="miv-data-item">
                  <label>Business Name</label>
                  <span>{results.businessIdentity.name?.value || 'Not identified'}</span>
                </div>
                <div className="miv-data-item">
                  <label>Category</label>
                  <span>{results.businessIdentity.category?.value || 'Not identified'}</span>
                </div>
                <div className="miv-data-item">
                  <label>Location</label>
                  <span>
                    {results.businessIdentity.location?.city || ''} 
                    {results.businessIdentity.location?.country ? `, ${results.businessIdentity.location.country}` : 'Not specified'}
                  </span>
                </div>
              </div>
              {results.primaryOfferings && results.primaryOfferings.length > 0 && (
                <div className="miv-offerings">
                  <h5>Primary Offerings</h5>
                  <div className="miv-tags">
                    {results.primaryOfferings.slice(0, 5).map((offer, i) => (
                      <span key={i} className="miv-tag offering">
                        {offer.name} ({Math.round((offer.confidence || 0) * 100)}%)
                      </span>
                    ))}
                  </div>
                </div>
              )}
              {results.proofAssets && results.proofAssets.length > 0 && (
                <div className="miv-proof">
                  <h5>Proof Assets ({results.proofAssets.length})</h5>
                  <div className="miv-tags">
                    {results.proofAssets.slice(0, 5).map((proof, i) => (
                      <span key={i} className="miv-tag proof">{proof.type}</span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* PHASE 2: External Presence */}
      <div className="miv-section">
        <button 
          className="miv-section-header phase2-header"
          onClick={() => toggleSection('userIntent')}
        >
          <div className="miv-section-title">
            <Globe size={18} />
            <span>Phase 2: External Presence</span>
            <span className="miv-confidence-badge">
              {Math.round((results.phaseConfidences?.phase2_external_presence || 0) * 100)}% confident
            </span>
          </div>
          {expandedSections.userIntent ? <ChevronUp size={18} /> : <ChevronDown size={18} />}
        </button>
        {expandedSections.userIntent && (
          <div className="miv-section-content">
            <div className="miv-data-grid">
              <div className="miv-data-item">
                <label>Profiles Discovered</label>
                <span>{results.profilesDiscovered || 0}</span>
              </div>
            </div>
            {results.externalProfiles?.google_business_profile && (
              <div className="miv-gbp-info">
                <Star size={16} className="star-icon" />
                <span>Google Business: {results.externalProfiles.google_business_profile.rating}★</span>
                <span>({results.externalProfiles.google_business_profile.review_count} reviews)</span>
              </div>
            )}
            {results.sentimentThemes && results.sentimentThemes.length > 0 && (
              <div className="miv-themes">
                <h5>Sentiment Themes</h5>
                <div className="miv-themes-list">
                  {results.sentimentThemes.slice(0, 5).map((theme, i) => (
                    <div key={i} className={`miv-theme-item sentiment-${theme.sentiment || 'neutral'}`}>
                      <span>"{theme.theme}"</span>
                      <span className="sentiment">{theme.sentiment}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* PHASE 3: Marketing & Conversion */}
      <div className="miv-section">
        <button 
          className="miv-section-header phase3-header"
          onClick={() => toggleSection('positioning')}
        >
          <div className="miv-section-title">
            <Target size={18} />
            <span>Phase 3: Marketing & Conversion</span>
            <span className="miv-confidence-badge">
              {Math.round((results.phaseConfidences?.phase3_marketing_conversion || 0) * 100)}% confident
            </span>
          </div>
          {expandedSections.positioning ? <ChevronUp size={18} /> : <ChevronDown size={18} />}
        </button>
        {expandedSections.positioning && (
          <div className="miv-section-content">
            <div className="miv-data-grid">
              <div className="miv-data-item">
                <label>Total CTAs</label>
                <span>{results.totalCTAs || 0}</span>
              </div>
              <div className="miv-data-item">
                <label>Sales Process</label>
                <span>{results.salesProcessType || 'Unknown'}</span>
              </div>
              <div className="miv-data-item">
                <label>Landing Pages</label>
                <span>{results.landingPages?.length || 0}</span>
              </div>
            </div>
            {results.marketingInfra?.tracking_tags && (
              <div className="miv-tracking">
                <h5>Tracking Tags</h5>
                <div className="miv-tags">
                  {results.marketingInfra.tracking_tags.map((tag, i) => (
                    <span key={i} className="miv-tag tracking">{tag}</span>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* PHASE 4: Competitors Section */}
      {results.competitors && results.competitors.length > 0 && (
        <div className="miv-section">
          <button 
            className="miv-section-header phase4-header"
            onClick={() => toggleSection('competitors')}
          >
            <div className="miv-section-title">
              <Users size={18} />
              <span>Phase 4: Competitor Analysis</span>
              <span className="miv-badge">{results.competitors.length}</span>
              <span className="miv-confidence-badge">
                {Math.round((results.phaseConfidences?.phase4_competitor_analysis || 0) * 100)}% confident
              </span>
            </div>
            {expandedSections.competitors ? <ChevronUp size={18} /> : <ChevronDown size={18} />}
          </button>
          {expandedSections.competitors && (
            <div className="miv-section-content">
              <div className="miv-competitors-grid">
                {results.competitors.map((competitor, i) => (
                  <div key={i} className="miv-competitor-card">
                    <div className="miv-competitor-rank">#{competitor.rank || i + 1}</div>
                    <div className="miv-competitor-main">
                      <h4>{competitor.name || competitor.domain || `Competitor ${i + 1}`}</h4>
                      {competitor.domain && (
                        <a 
                          href={`https://${competitor.domain}`} 
                          target="_blank" 
                          rel="noopener noreferrer"
                          className="miv-competitor-url"
                        >
                          {competitor.domain} <ExternalLink size={12} />
                        </a>
                      )}
                      {competitor.positioning && (
                        <p className="miv-competitor-desc">{competitor.positioning}</p>
                      )}
                      {competitor.primary_offerings && competitor.primary_offerings.length > 0 && (
                        <div className="miv-competitor-offerings">
                          <strong>Offerings:</strong> {competitor.primary_offerings.slice(0, 3).join(', ')}
                        </div>
                      )}
                    </div>
                    <div className="miv-competitor-stats">
                      {competitor.gbp_info && (
                        <div className="miv-mini-stat">
                          <Star size={12} />
                          <span>{competitor.gbp_info.rating}★ ({competitor.gbp_info.reviews} reviews)</span>
                        </div>
                      )}
                      {competitor.score && (
                        <div className="miv-mini-stat">
                          <BarChart3 size={12} />
                          <span>Score: {Math.round(competitor.score * 100)}%</span>
                        </div>
                      )}
                      {competitor.why_picked && competitor.why_picked.length > 0 && (
                        <div className="miv-mini-stat">
                          <CheckCircle size={12} />
                          <span>{competitor.why_picked[0]}</span>
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Executive Summary / Report */}
      {results.reportMarkdown && (
        <div className="miv-section highlight">
          <button 
            className="miv-section-header"
            onClick={() => toggleSection('recommendations')}
          >
            <div className="miv-section-title">
              <FileText size={18} />
              <span>Executive Summary & Recommendations</span>
            </div>
            {expandedSections.recommendations ? <ChevronUp size={18} /> : <ChevronDown size={18} />}
          </button>
          {expandedSections.recommendations && (
            <div className="miv-section-content">
              <div className="miv-report-markdown">
                <pre>{results.reportMarkdown}</pre>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Execution Info */}
      {results.report_id && (
        <div className="miv-footer">
          <small>Report ID: {results.report_id} | Generated: {new Date(results.generated_at).toLocaleString()}</small>
        </div>
      )}
    </div>
  );

  // Render input form
  const renderInputForm = () => (
    <div className="miv-input-container">
      <div className="miv-hero">
        <div className="miv-hero-icon">
          <TrendingUp size={48} />
        </div>
        <h1>Business Intelligence Analysis</h1>
        <p>Enter your business website or describe your service to get comprehensive market insights, competitor analysis, and actionable recommendations.</p>
      </div>

      <div className="miv-form-card">
        <div className="miv-input-group">
          <label>
            <Globe size={16} />
            Website URL
          </label>
          <input
            type="url"
            value={websiteUrl}
            onChange={(e) => setWebsiteUrl(e.target.value)}
            placeholder="https://yourbusiness.com"
            disabled={isLoading}
          />
          <span className="miv-input-hint">Enter your website to analyze your competitive position</span>
        </div>

        <div className="miv-divider">
          <span>or</span>
        </div>

        <div className="miv-input-group">
          <label>
            <FileText size={16} />
            Describe Your Business
          </label>
          <textarea
            value={businessDescription}
            onChange={(e) => setBusinessDescription(e.target.value)}
            placeholder="e.g., AI-powered chatbot for restaurant ordering and reservations"
            rows={3}
            disabled={isLoading}
          />
          <span className="miv-input-hint">Describe what your business does or the service you offer</span>
        </div>

        <div className="miv-input-group">
          <label>
            <MapPin size={16} />
            Target Market
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

        {error && (
          <div className="miv-error">
            <AlertCircle size={16} />
            <span>{error}</span>
          </div>
        )}

        <button 
          className="miv-execute-btn"
          onClick={handleExecute}
          disabled={isLoading || (!websiteUrl.trim() && !businessDescription.trim())}
        >
          <Sparkles size={18} />
          Run Full Analysis
        </button>

        <div className="miv-features">
          <div className="miv-feature">
            <Search size={14} />
            <span>SERP Analysis</span>
          </div>
          <div className="miv-feature">
            <Users size={14} />
            <span>Competitor Discovery</span>
          </div>
          <div className="miv-feature">
            <Target size={14} />
            <span>User Intent</span>
          </div>
          <div className="miv-feature">
            <Lightbulb size={14} />
            <span>Recommendations</span>
          </div>
        </div>
      </div>
    </div>
  );

  return (
    <div className="miv-container">
      {isLoading ? renderLoadingState() : results ? renderResults() : renderInputForm()}
    </div>
  );
};

export default MarketIntelligenceView;
