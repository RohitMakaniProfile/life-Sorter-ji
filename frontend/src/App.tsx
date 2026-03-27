import { useState, useEffect } from 'react';
import ChatBotNew from './components/ChatBotNew';
import ChatBotNewMobile from './components/ChatBotNewMobile';
import AboutPage from './components/AboutPage';
import ErrorBoundary from './components/ErrorBoundary';
import { ThemeProvider } from './context/ThemeContext';
import './AppLegacy.css';

function App() {
  const [isMobile, setIsMobile] = useState(window.innerWidth <= 768);
  const [currentPage, setCurrentPage] = useState('chat');

  useEffect(() => {
    const handleResize = () => {
      setIsMobile(window.innerWidth <= 768);
    };
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  const handleNavigate = (page) => {
    setCurrentPage(page);
  };

  const renderPage = () => {
    switch (currentPage) {
      case 'about':
        return <AboutPage onBack={() => setCurrentPage('chat')} />;
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
