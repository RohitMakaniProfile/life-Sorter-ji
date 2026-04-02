import { useEffect, useState } from 'react';
import { BrowserRouter, Navigate, Route, Routes, useNavigate, useParams } from 'react-router-dom';
import OnboardingApp from './components/onboarding/OnboardingApp';
import ErrorBoundary from './components/ErrorBoundary';
import { UiAgentsProvider } from './context/UiAgentsContext';
import ChatPage from './pages/ai/ChatPage';
import ConversationsPage from './pages/ai/ConversationsPage';
import AgentsPage from './pages/ai/AgentsPage';
import AgentContextsPage from './pages/ai/AgentContextsPage';
import InternalGoogleLoginPage from './pages/ai/InternalGoogleLoginPage';
import Layout from './components/ai/Layout';
import { getConversations } from './api';

function ChatWithId() {
  const { conversationId } = useParams<{ conversationId: string }>();
  return <ChatPage conversationId={conversationId} />;
}

function DefaultChat() {
  const navigate = useNavigate();
  const [ready, setReady] = useState(false);

  useEffect(() => {
    getConversations()
      .then(({ conversations }) => {
        if (conversations.length > 0) {
          navigate(`/chat/${conversations[0].id}`, { replace: true });
        } else {
          navigate('/new', { replace: true });
        }
      })
      .catch(() => navigate('/new', { replace: true }))
      .finally(() => setReady(true));
  }, [navigate]);

  if (ready) return null;
  return (
    <div className="flex items-center justify-center h-full">
      <div className="w-5 h-5 border-2 border-violet-400 border-t-transparent rounded-full animate-spin" />
    </div>
  );
}

function App() {
  return (
    <ErrorBoundary>
      <UiAgentsProvider>
        <BrowserRouter>
          <Routes>
            <Route path="login-internal" element={<InternalGoogleLoginPage mode="internal" />} />
            <Route path="login-admin" element={<InternalGoogleLoginPage mode="admin" />} />
            <Route element={<Layout />}>
              <Route path="chat" element={<DefaultChat />} />
              <Route path="chat/:conversationId" element={<ChatWithId />} />
              <Route path="new" element={<ChatPage key="new" />} />
              <Route path="conversations" element={<ConversationsPage />} />
              <Route path="agents" element={<AgentsPage />} />
              <Route path="agents/:agentId/contexts" element={<AgentContextsPage />} />
            </Route>
            <Route path="/" element={<OnboardingApp />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </BrowserRouter>
      </UiAgentsProvider>
    </ErrorBoundary>
  );
}

export default App;
