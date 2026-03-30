/**
 * Desktop `ChatBotNew` and mobile `ChatBotNewMobile` persist Phase 1 threads in localStorage.
 * That state is unrelated to Phase 2 JWT — so after Phase 2 logout, a refresh on `/` can still
 * restore the old playbook and any bot error lines with zero network calls.
 */
const CURRENT_CHAT_KEY = 'ikshan-current-chat';
const CHAT_HISTORY_KEY = 'ikshan-chat-history';

export function clearLegacyPhase1ChatPersistence(): void {
  try {
    localStorage.removeItem(CURRENT_CHAT_KEY);
    localStorage.removeItem(CHAT_HISTORY_KEY);
  } catch {
    // ignore quota / private mode
  }
}
