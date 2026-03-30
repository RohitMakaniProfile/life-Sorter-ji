import { useState, useEffect } from 'react';
import IkshanApp from './components/ikshan/IkshanApp';
import ChatBotNew from './components/ChatBotNew';
import ChatBotNewMobile from './components/ChatBotNewMobile';
import AboutPage from './components/AboutPage';
import SandboxLogin from './components/SandboxLogin';
import SandboxPanel from './components/SandboxPanel';
import ErrorBoundary from './components/ErrorBoundary';
import { ThemeProvider } from './context/ThemeContext';
import './App.css';

function App() {
  const [isMobile, setIsMobile] = useState(window.innerWidth <= 768);
  const [currentPage, setCurrentPage] = useState('ikshan');
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
    setCurrentPage('ikshan');
  };

  const renderPage = () => {
    switch (currentPage) {
      case 'ikshan':
        return <IkshanApp />;
      case 'about':
        return <AboutPage onBack={() => setCurrentPage('ikshan')} />;
      case 'developer-login':
        return (
          <SandboxLogin
            onLogin={handleSandboxLogin}
            onBack={() => setCurrentPage('ikshan')}
          />
        );
      case 'sandbox':
        return (
          <SandboxPanel
            token={sandboxToken}
            onBack={() => setCurrentPage('ikshan')}
            onLogout={handleSandboxLogout}
          />
        );
      case 'chat-legacy':
        return isMobile ? (
          <ChatBotNewMobile onNavigate={handleNavigate} />
        ) : (
          <ChatBotNew onNavigate={handleNavigate} />
        );
      default:
        return <IkshanApp />;
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
