import { PipelineState, RichMessage } from "../../types";
import ChatInput from "./ChatInput";
import MessageList from "./MessageList";
import SidePanel from "./SidePanel";

interface Props {
  messages: RichMessage[];
  loading: boolean;
  onSend: (msg: string) => Promise<void>;

  sidePanelOpen: boolean;
  onClosePanel: () => void;

  pipeline: PipelineState | null;
  panelMessageId?: string;
  panelTitle?: string;
  onOpenContext: (messageId: string) => void;
}

export default function ChatLayout({
  messages,
  loading,
  onSend,
  sidePanelOpen,
  onClosePanel,
  pipeline,
  panelMessageId,
  panelTitle,
  onOpenContext,
}: Props) {
  return (
    <div className="flex h-full w-full">
      {/* Chat */}
      <div className="flex-1 flex flex-col h-full">
        {/* Message List */}
        <div className="flex-1 overflow-hidden">
          <MessageList messages={messages} loading={loading} onOpenContext={onOpenContext} />
        </div>

        {/* Input stays at bottom */}
        <ChatInput onSend={onSend} loading={loading} />
      </div>

      {/* Side Panel */}
      <SidePanel
        open={sidePanelOpen}
        title={panelTitle}
        pipeline={pipeline}
        messageId={panelMessageId}
        onClose={onClosePanel}
      />
    </div>
  );
}