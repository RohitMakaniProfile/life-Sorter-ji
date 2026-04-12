import { useEffect, useState } from 'react';
import { BrowserRouter, Navigate, Route, Routes, useNavigate, useParams } from 'react-router-dom';
import OnboardingApp from './components/onboarding/OnboardingApp';
import ErrorBoundary from './components/ErrorBoundary';
import MobileBlocker from './components/MobileBlocker';
import { UiAgentsProvider } from './context/UiAgentsContext';
import ChatPage from './pages/ai/ChatPage';
import ConversationsPage from './pages/ai/ConversationsPage';
import PlaybookRunPage from './pages/ai/PlaybookRunPage';
import AgentsPage from './pages/ai/AgentsPage';
import AgentContextsPage from './pages/ai/AgentContextsPage';
import Layout from './components/ai/Layout';
import PaymentPage from './pages/PaymentPage';
import AccountPage from './pages/AccountPage';
import HowItWorksPage from './pages/HowItWorksPage';
import { getConversations } from './api';
import AdminLoginPage from './pages/AdminLoginPage';
import GoogleLoginPage from './pages/GoogleLoginPage';
import PhoneVerifyPage from './pages/PhoneVerifyPage';
import RequireSuperAdmin from './components/RequireSuperAdmin';
import AdminSystemConfigPage from './pages/AdminSystemConfigPage';
import AdminObservabilityPage from './pages/AdminObservabilityPage';
import AdminSubscriptionGrantsPage from './pages/AdminSubscriptionGrantsPage';
import AdminUsersPage from './pages/AdminUsersPage';
import AdminSkillCallDetailPage from './pages/AdminSkillCallDetailPage';
import AdminPromptsPage from './pages/AdminPromptsPage';
import AdminTokenUsagePage from './pages/AdminTokenUsagePage';
import AdminOnboardingTokenUsagePage from './pages/AdminOnboardingTokenUsagePage';

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
      <MobileBlocker />
      <UiAgentsProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/admin/login" element={<AdminLoginPage />} />
            <Route path="/google-login" element={<GoogleLoginPage />} />
            <Route path="/phone-verify" element={<PhoneVerifyPage />} />

            {/* Standalone pages (no sidebar layout) */}
            <Route path="/payment" element={<PaymentPage />} />
            <Route path="/how-it-works" element={<HowItWorksPage />} />
            <Route path="/deep-analysis" element={<Navigate to="/payment" replace />} />
            <Route path="/playbook/:runId" element={<PlaybookRunPage />} />

            <Route element={<Layout />}>
              <Route path="chat" element={<DefaultChat />} />
              <Route path="chat/:conversationId" element={<ChatWithId />} />
              <Route path="new" element={<ChatPage key="new" />} />
              <Route path="account" element={<AccountPage />} />
              <Route path="conversations" element={<ConversationsPage />} />
              <Route path="agents" element={<RequireSuperAdmin />}>
                <Route index element={<AgentsPage />} />
                <Route path=":agentId/contexts" element={<AgentContextsPage />} />
              </Route>

              <Route path="admin" element={<RequireSuperAdmin />}>
                <Route index element={<Navigate to="/admin/observability" replace />} />
                <Route path="users" element={<AdminUsersPage />} />
                <Route path="skill-calls/:skillCallId" element={<AdminSkillCallDetailPage />} />
                <Route path="onboarding/:onboardingId/token-usage" element={<AdminOnboardingTokenUsagePage />} />
                <Route path="observability" element={<AdminObservabilityPage />} />
                <Route path="config" element={<AdminSystemConfigPage />} />
                <Route path="prompts" element={<AdminPromptsPage />} />
                <Route path="token-usage" element={<AdminTokenUsagePage />} />
                <Route path="subscription-grants" element={<AdminSubscriptionGrantsPage />} />
                <Route path="agents" element={<AgentsPage />} />
                <Route path="agents/:agentId/contexts" element={<AgentContextsPage />} />
              </Route>
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
