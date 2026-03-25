import { useState } from 'react';
import { Lock, Eye, EyeOff, ArrowLeft, Terminal } from 'lucide-react';
import './SandboxLogin.css';

const SandboxLogin = ({ onLogin, onBack }) => {
  const [id, setId] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const API_BASE = import.meta.env.VITE_API_URL || '';

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      const res = await fetch(`${API_BASE}/api/v1/sandbox/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id, password }),
      });

      if (res.ok) {
        const data = await res.json();
        onLogin(data.token);
      } else {
        setError('Invalid credentials');
      }
    } catch {
      setError('Connection failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="sandbox-login-container">
      <div className="sandbox-login-card">
        <button className="sandbox-back-btn" onClick={onBack}>
          <ArrowLeft size={16} /> Back
        </button>

        <div className="sandbox-login-header">
          <div className="sandbox-login-icon">
            <Terminal size={28} />
          </div>
          <h2>Developer Sandbox</h2>
          <p className="sandbox-login-subtitle">
            Authenticated access to test flows & system logs
          </p>
        </div>

        <form onSubmit={handleSubmit} className="sandbox-login-form">
          <div className="sandbox-field">
            <label htmlFor="sandbox-id">Developer ID</label>
            <div className="sandbox-input-wrapper">
              <Lock size={16} />
              <input
                id="sandbox-id"
                type="text"
                value={id}
                onChange={(e) => setId(e.target.value)}
                placeholder="Enter developer ID"
                autoFocus
                autoComplete="off"
              />
            </div>
          </div>

          <div className="sandbox-field">
            <label htmlFor="sandbox-pw">Password</label>
            <div className="sandbox-input-wrapper">
              <Lock size={16} />
              <input
                id="sandbox-pw"
                type={showPassword ? 'text' : 'password'}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Enter password"
                autoComplete="off"
              />
              <button
                type="button"
                className="sandbox-eye-btn"
                onClick={() => setShowPassword(!showPassword)}
              >
                {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            </div>
          </div>

          {error && <div className="sandbox-error">{error}</div>}

          <button
            type="submit"
            className="sandbox-submit-btn"
            disabled={loading || !id || !password}
          >
            {loading ? 'Authenticating…' : 'Access Sandbox'}
          </button>
        </form>

        <div className="sandbox-login-footer">
          <span>Restricted access — authorized developers only</span>
        </div>
      </div>
    </div>
  );
};

export default SandboxLogin;
