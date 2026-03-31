import Navbar from './Navbar';

export default function StageLayout({ children, error, onClearError }) {
  return (
    <div className="ik-app">
      <Navbar />
      {children}
      {error && (
        <div className="ik-app__error" onClick={onClearError}>
          <span>{error}</span>
          <button className="ik-app__error-close">&times;</button>
        </div>
      )}
    </div>
  );
}
