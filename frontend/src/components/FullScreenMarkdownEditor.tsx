import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

type Props = {
  open: boolean;
  title: string;
  value: string;
  mode: 'edit' | 'preview';
  saving?: boolean;
  canEdit?: boolean;
  onChange: (v: string) => void;
  onModeChange: (m: 'edit' | 'preview') => void;
  onSave: () => void | Promise<void>;
  onClose: () => void;
};

export default function FullScreenMarkdownEditor({
  open,
  title,
  value,
  mode,
  saving = false,
  canEdit = true,
  onChange,
  onModeChange,
  onSave,
  onClose,
}: Props) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 bg-black/50 flex items-stretch justify-center">
      <div className="w-full max-w-6xl bg-slate-900 border border-slate-700 flex flex-col">
        <div className="px-4 py-3 border-b border-slate-700 flex items-center justify-between gap-3">
          <div className="text-sm font-semibold text-slate-100 truncate">{title}</div>
          <div className="flex items-center gap-2">
            <div className="inline-flex rounded-lg border border-slate-600 bg-slate-900 p-0.5">
              <button type="button" onClick={() => onModeChange('edit')} className={`px-3 py-1.5 text-xs font-semibold rounded-md ${mode === 'edit' ? 'bg-violet-600 text-white' : 'text-slate-300'}`}>Edit</button>
              <button type="button" onClick={() => onModeChange('preview')} className={`px-3 py-1.5 text-xs font-semibold rounded-md ${mode === 'preview' ? 'bg-violet-600 text-white' : 'text-slate-300'}`}>Preview</button>
            </div>
            <button type="button" onClick={() => void onSave()} disabled={saving || !canEdit} className="px-3 py-2 text-xs font-semibold rounded-lg bg-violet-600 text-white disabled:opacity-60">{saving ? 'Saving…' : 'Save'}</button>
            <button type="button" onClick={onClose} className="px-3 py-2 text-xs font-semibold rounded-lg border border-slate-600 text-slate-300">Close</button>
          </div>
        </div>
        <div className="flex-1 overflow-hidden">
          {mode === 'edit' ? (
            <textarea
              value={value}
              onChange={(e) => onChange(e.target.value)}
              readOnly={!canEdit}
              className="w-full h-full resize-none font-mono text-xs p-4 outline-none bg-slate-800 text-slate-100"
            />
          ) : (
            <div className="h-full overflow-y-auto p-6 bg-slate-900 prose prose-sm prose-invert max-w-none">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{value || ''}</ReactMarkdown>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
