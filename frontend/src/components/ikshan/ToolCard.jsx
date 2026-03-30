import './ToolCard.css';

/**
 * Tool recommendation card as seen in the Figma "Best Tools For You" section.
 * @param {string} name        - Tool name
 * @param {number} rating      - Star rating (e.g. 4.5)
 * @param {string} description - Short description
 * @param {string[]} bullets   - Feature bullet points
 * @param {string} tag         - Category tag (e.g. "LEAD-INTELLIGENCE")
 * @param {string} url         - Link to tool
 */
export default function ToolCard({ name, rating, description, bullets = [], tag, url }) {
  return (
    <a className="ik-tool-card" href={url} target="_blank" rel="noopener noreferrer">
      <div className="ik-tool-card__header">
        <span className="ik-tool-card__name">{name}</span>
        {rating && (
          <span className="ik-tool-card__rating">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="#e8b931"><path d="M12 2l3.09 6.26L22 9.27l-5 4.87L18.18 22 12 18.56 5.82 22 7 14.14 2 9.27l6.91-1.01L12 2z"/></svg>
            {rating}
          </span>
        )}
      </div>
      {tag && <span className="ik-tool-card__tag">{tag}</span>}
      <p className="ik-tool-card__desc">{description}</p>
      {bullets.length > 0 && (
        <ul className="ik-tool-card__bullets">
          {bullets.map((b, i) => <li key={i}>{b}</li>)}
        </ul>
      )}
      <span className="ik-tool-card__cta">Learn more &rarr;</span>
    </a>
  );
}
