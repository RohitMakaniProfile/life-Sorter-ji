import { useRef, useEffect } from 'react';

const MAX_ROWS = 5;
const LINE_HEIGHT = 20;

export default function ChatInput({
  onSend,
  loading,
}: {
  onSend: (msg: string) => Promise<void>;
  loading: boolean;
}) {
  const ref = useRef<HTMLTextAreaElement>(null);

  const resizeTextarea = () => {
    const el = ref.current;
    if (!el) return;

    el.style.height = 'auto';

    const maxHeight = MAX_ROWS * LINE_HEIGHT;
    el.style.height = Math.min(el.scrollHeight, maxHeight) + 'px';
    el.style.overflowY = el.scrollHeight > maxHeight ? 'auto' : 'hidden';
  };

  // ✅ FIX: force 1-line height on mount
  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    el.style.height = LINE_HEIGHT + 'px';
    el.style.overflowY = 'hidden';
  }, []);

  const handleSend = async () => {
    const val = ref.current?.value.trim();
    if (!val || loading) return;

    ref.current!.value = '';

    // reset to 1 line after send
    ref.current!.style.height = LINE_HEIGHT + 'px';

    await onSend(val);
  };

  const handleKeyDown = async (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      await handleSend();
    }
  };

  return (
    <div className="border-t bg-white px-4 py-3">
      <div className="flex items-end gap-3 bg-slate-100 rounded-2xl px-4 py-2 shadow-sm">
        <textarea
          ref={ref}
          rows={1}
          onInput={resizeTextarea}
          onKeyDown={handleKeyDown}
          placeholder="Ask anything..."
          className="flex-1 resize-none bg-transparent outline-none text-sm text-slate-800 placeholder:text-slate-400"
          style={{
            lineHeight: `${LINE_HEIGHT}px`,
            maxHeight: `${MAX_ROWS * LINE_HEIGHT}px`,
            overflowY: 'hidden',
          }}
        />

        <button
          onClick={handleSend}
          disabled={loading}
          className="flex items-center justify-center w-9 h-9 rounded-full bg-violet-600 hover:bg-violet-700 disabled:opacity-50 transition"
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            className="w-4 h-4 text-white"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2}
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M5 12l14-7-7 14-2-5-5-2z"
            />
          </svg>
        </button>
      </div>
    </div>
  );
}