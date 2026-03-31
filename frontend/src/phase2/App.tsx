import { useEffect, useState } from 'react';
import { Navigate, Route, Routes, useNavigate, useParams } from 'react-router-dom';
import Layout from './components/Layout';
import ChatPage from './pages/ChatPage';
import ConversationsPage from './pages/ConversationsPage';
import AgentsPage from './pages/AgentsPage';
import AgentContextsPage from './pages/AgentContextsPage';
import InternalGoogleLoginPage from './pages/InternalGoogleLoginPage';
import { getConversations } from './api/client';
import { UiAgentsProvider } from './context/UiAgentsContext';
import { phase2Path } from './constants';

function ChatWithId() {
  const { conversationId } = useParams<{ conversationId: string }>();
  return <ChatPage conversationId={conversationId} />;
}

/** Redirects to the most recent conversation, or /new if none exist. */
function DefaultChat() {
  const navigate = useNavigate();
  const [ready, setReady] = useState(false);

  useEffect(() => {
    getConversations()
      .then(({ conversations }) => {
        if (conversations.length > 0) {
          // conversations are sorted newest-first by the backend
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

function App({ basename = '' }: { basename?: string }) {
  return (
    <UiAgentsProvider>
      <Routes>
        <Route path="login-internal" element={<InternalGoogleLoginPage mode="internal" />} />
        <Route path="login-admin" element={<InternalGoogleLoginPage mode="admin" />} />
        <Route path="/" element={<Layout />}>
          <Route index element={<Navigate to={phase2Path('chat')} replace />} />
          <Route path="chat" element={<DefaultChat />} />
          <Route path="chat/:conversationId" element={<ChatWithId />} />
          <Route path="new" element={<ChatPage key="new" />} />
          <Route path="conversations" element={<ConversationsPage />} />
          <Route path="agents" element={<AgentsPage />} />
          <Route path="agents/:agentId/contexts" element={<AgentContextsPage />} />
        </Route>
        <Route path="*" element={<Navigate to={phase2Path('chat')} replace />} />
      </Routes>
    </UiAgentsProvider>
  );
}

export default App;
