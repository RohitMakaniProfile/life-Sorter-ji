import { useState, useEffect } from 'react';
import { BrowserRouter, Route, Routes } from 'react-router-dom';
import ChatBotNew from './components/ChatBotNew';
import ChatBotNewMobile from './components/ChatBotNewMobile';
import AboutPage from './components/AboutPage';
import ErrorBoundary from './components/ErrorBoundary';
import { ThemeProvider } from './context/ThemeContext';
import Phase2Layout from './phase2/Phase2Layout';
import { phase2OutletChildren } from './phase2/childRoutes';
import './AppLegacy.css';

function LegacyHome({ onNavigate }: { onNavigate: (page: string) => void }) {
  const [isMobile, setIsMobile] = useState(window.innerWidth <= 768);

  useEffect(() => {
    const handleResize = () => {
      setIsMobile(window.innerWidth <= 768);
    };
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  return (
    <div className="app">
      {isMobile ? (
        <ChatBotNewMobile onNavigate={onNavigate} />
      ) : (
        <ChatBotNew onNavigate={onNavigate} />
      )}
    </div>
  );
}

function LegacyApp() {
  const [currentPage, setCurrentPage] = useState('chat');

  const handleNavigate = (page: string) => {
    setCurrentPage(page);
  };

  if (currentPage === 'about') {
    return (
      <div className="app">
        <AboutPage onBack={() => setCurrentPage('chat')} />
      </div>
    );
  }

  return <LegacyHome onNavigate={handleNavigate} />;
}

export default function App() {
  return (
    <ErrorBoundary>
      <ThemeProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/" element={<LegacyApp />} />
            <Route path="/phase2" element={<Phase2Layout />}>
              {phase2OutletChildren}
            </Route>
          </Routes>
        </BrowserRouter>
      </ThemeProvider>
    </ErrorBoundary>
  );
}
