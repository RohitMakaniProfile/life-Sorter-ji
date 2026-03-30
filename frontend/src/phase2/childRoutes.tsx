import { useEffect, useState } from 'react';
import { Navigate, Route, useNavigate, useParams } from 'react-router-dom';
import ChatPage from './pages/ChatPage';
import ConversationsPage from './pages/ConversationsPage';
import AgentsPage from './pages/AgentsPage';
import AgentContextsPage from './pages/AgentContextsPage';
import InternalGoogleLoginPage from './pages/InternalGoogleLoginPage';
import { getConversations } from '../api';
import { phase2Path } from './constants';
import Layout from './components/Layout';

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
          navigate(phase2Path(`chat/${conversations[0].id}`), { replace: true });
        } else {
          navigate(phase2Path('new'), { replace: true });
        }
      })
      .catch(() => navigate(phase2Path('new'), { replace: true }))
      .finally(() => setReady(true));
  }, [navigate]);

  if (ready) return null;
  return (
    <div className="flex items-center justify-center h-full">
      <div className="w-5 h-5 border-2 border-violet-400 border-t-transparent rounded-full animate-spin" />
    </div>
  );
}

/**
 * Children of `/phase2` route element (`Phase2Layout` = provider + outlet).
 * Same structure as git `development` `phase2/App.tsx`: login routes outside `Layout`.
 */
export const phase2OutletChildren = [
  <Route key="p2-login-int" path="login-internal" element={<InternalGoogleLoginPage mode="internal" />} />,
  <Route key="p2-login-adm" path="login-admin" element={<InternalGoogleLoginPage mode="admin" />} />,
  <Route key="p2-layout" element={<Layout />}>
    <Route index element={<Navigate to="chat" replace />} />
    <Route path="chat" element={<DefaultChat />} />
    <Route path="chat/:conversationId" element={<ChatWithId />} />
    <Route path="new" element={<ChatPage key="new" />} />
    <Route path="conversations" element={<ConversationsPage />} />
    <Route path="agents" element={<AgentsPage />} />
    <Route path="agents/:agentId/contexts" element={<AgentContextsPage />} />
  </Route>,
];
