import './Navbar.css';

export default function Navbar() {
  return (
    <nav className="ik-navbar">
      <div className="ik-navbar__left">
        <button className="ik-navbar__btn">
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><rect x="1" y="1" width="6" height="6" rx="1" stroke="currentColor" strokeWidth="1.5"/><rect x="9" y="1" width="6" height="6" rx="1" stroke="currentColor" strokeWidth="1.5"/><rect x="1" y="9" width="6" height="6" rx="1" stroke="currentColor" strokeWidth="1.5"/><rect x="9" y="9" width="6" height="6" rx="1" stroke="currentColor" strokeWidth="1.5"/></svg>
          Our Products
        </button>
        <button className="ik-navbar__btn">
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><line x1="8" y1="3" x2="8" y2="13" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/><line x1="3" y1="8" x2="13" y2="8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/></svg>
          New Chat
        </button>
        <button className="ik-navbar__btn">
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M2 4h12M2 8h8M2 12h10" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/></svg>
          History
        </button>
        <button className="ik-navbar__btn">
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><circle cx="8" cy="8" r="6" stroke="currentColor" strokeWidth="1.5"/><circle cx="8" cy="6.5" r="0.75" fill="currentColor"/><line x1="8" y1="8.5" x2="8" y2="11" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/></svg>
          How It Works
        </button>
      </div>
      <div className="ik-navbar__right">
        <span className="ik-navbar__logo">IKSHAN</span>
      </div>
    </nav>
  );
}
