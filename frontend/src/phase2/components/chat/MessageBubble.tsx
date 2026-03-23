import { RichMessage } from '../../types';
import AssistantMessage from './AssistantMessage';
import UserMessage from './UserMessage';

export default function MessageBubble({
  message,
  isLast,
  loading,
  onOpenContext,
}: {
  message: RichMessage;
  isLast: boolean;
  loading: boolean;
  onOpenContext?: (messageId: string) => void;
}) {
  if (message.role === 'assistant' && !message.content?.trim() && !loading) {
    return null;
  }
  
  return (
    <div className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}>
      {message.role === 'assistant' && (
        <div className="mr-3">🤖</div>
      )}

      {message.role === 'user' ? (
        <UserMessage message={message} />
      ) : (
        <AssistantMessage message={message} isLast={isLast} loading={loading} onOpenContext={onOpenContext} />
      )}
    </div>
  );
}