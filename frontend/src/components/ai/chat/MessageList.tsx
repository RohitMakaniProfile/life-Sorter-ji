import { RichMessage } from '../../../api/types';
import MessageBubble from './MessageBubble';

export default function MessageList({
  messages,
  loading,
  onOpenContext,
}: {
  messages: RichMessage[];
  loading: boolean;
  onOpenContext?: (messageId: string) => void;
}) {
  return (
    <div className="flex flex-col justify-end min-h-full p-6 space-y-6 bg-slate-50">
      {messages.map((m, i) => (
        <MessageBubble
          key={i}
          message={m}
          isLast={i === messages.length - 1}
          loading={loading}
          onOpenContext={onOpenContext}
        />
      ))}
    </div>
  );
}