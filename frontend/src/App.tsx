import { useState, useEffect } from 'react';
import ChatBotNew from './components/ChatBotNew';
import ChatBotNewMobile from './components/ChatBotNewMobile';
import AboutPage from './components/AboutPage';
import SandboxLogin from './components/SandboxLogin';
import SandboxPanel from './components/SandboxPanel';
import ErrorBoundary from './components/ErrorBoundary';
import { ThemeProvider } from './context/ThemeContext';
import './AppLegacy.css';

function App() {
  const [isMobile, setIsMobile] = useState(window.innerWidth <= 768);
  const [currentPage, setCurrentPage] = useState('chat');
  const [sandboxToken, setSandboxToken] = useState(null);

  useEffect(() => {
    const handleResize = () => {
      setIsMobile(window.innerWidth <= 768);
    };
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  const handleNavigate = (page) => {
    if (page === 'developer') {
      setCurrentPage(sandboxToken ? 'sandbox' : 'developer-login');
    } else {
      setCurrentPage(page);
    }
  };

  const handleSandboxLogin = (token) => {
    setSandboxToken(token);
    setCurrentPage('sandbox');
  };

  const handleSandboxLogout = () => {
    setSandboxToken(null);
    setCurrentPage('chat');
  };

  const renderPage = () => {
    switch (currentPage) {
      case 'about':
        return <AboutPage onBack={() => setCurrentPage('chat')} />;
      case 'developer-login':
        return (
          <SandboxLogin
            onLogin={handleSandboxLogin}
            onBack={() => setCurrentPage('chat')}
          />
        );
      case 'sandbox':
        return (
          <SandboxPanel
            token={sandboxToken}
            onBack={() => setCurrentPage('chat')}
            onLogout={handleSandboxLogout}
          />
        );
      default:
        return isMobile ? (
          <ChatBotNewMobile onNavigate={handleNavigate} />
        ) : (
          <ChatBotNew onNavigate={handleNavigate} />
        );
    }
  };

  return (
    <ErrorBoundary>
      <ThemeProvider>
        <div className="app">
          {renderPage()}
        </div>
      </ThemeProvider>
    </ErrorBoundary>
  );
}

export default App;
