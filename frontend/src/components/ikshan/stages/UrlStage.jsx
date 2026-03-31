import FlowNode from '../components/FlowNode';
import ToolCard from '../components/ToolCard';
import './UrlStage.css';

const TOOLS_PER_PAGE = 3;

export default function UrlStage({
  selectedDomain, urlValue, gbpValue, onUrlChange, onGbpChange,
  urlTab, onTabChange,
  onSubmit, onSkip, urlSubmitting, earlyTools, toolPage, onToolPageChange, onBack,
}) {
  const totalPages = Math.ceil(earlyTools.length / TOOLS_PER_PAGE);
  const pageTools = earlyTools.slice(toolPage * TOOLS_PER_PAGE, (toolPage + 1) * TOOLS_PER_PAGE);

  const isWebsite = urlTab === 'website';
  const currentValue = isWebsite ? urlValue : gbpValue;
  const currentOnChange = isWebsite ? onUrlChange : onGbpChange;
  const placeholder = isWebsite ? 'yourcompany.com' : 'google.com/maps/place/your-business';

  return (
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
            <div className="ik-inline-form__tabs">
              <button type="button"
                className={`ik-inline-form__tab ${isWebsite ? 'ik-inline-form__tab--active' : ''}`}
                onClick={() => onTabChange('website')}>
                Website URL
              </button>
              <button type="button"
                className={`ik-inline-form__tab ${!isWebsite ? 'ik-inline-form__tab--active' : ''}`}
                onClick={() => onTabChange('gbp')}>
                Google Business Profile URI
              </button>
            </div>
            <form onSubmit={onSubmit}>
              <input className="ik-inline-form__input" type="text"
                placeholder={placeholder}
                value={currentValue}
                onChange={(e) => currentOnChange(e.target.value)}
                autoFocus
                key={urlTab} />
              <button className="ik-inline-form__submit" type="submit"
                disabled={urlSubmitting || (!urlValue.trim() && !gbpValue.trim())}>
                {urlSubmitting ? 'Analyzing...' : 'Analyze My Business'}
              </button>
            </form>
            <button className="ik-inline-form__skip" onClick={onSkip} disabled={urlSubmitting}>
              Skip — without URLs, we'll give general recommendations
            </button>
          </div>
        </div>
      </div>

      {/* Tools carousel */}
      {earlyTools.length > 0 && (
        <div className="ik-s2__tools">
          <h2 className="ik-s2__tools-heading">Best Tools For You</h2>
          <div className="ik-carousel">
            <button className="ik-carousel__btn ik-carousel__btn--left"
              onClick={() => onToolPageChange((p) => p - 1)}
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
              onClick={() => onToolPageChange((p) => p + 1)}
              disabled={toolPage >= totalPages - 1}>
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M9 18l6-6-6-6"/></svg>
            </button>
          </div>
          <div className="ik-carousel__dots">
            {Array.from({ length: totalPages }).map((_, i) => (
              <button key={i}
                className={`ik-carousel__dot ${i === toolPage ? 'ik-carousel__dot--active' : ''}`}
                onClick={() => onToolPageChange(i)} />
            ))}
          </div>
        </div>
      )}

      {/* Back to Step 1 */}
      <button className="ik-s2__back" onClick={onBack}>
        &lsaquo; BACK
      </button>
    </div>
  );
}
