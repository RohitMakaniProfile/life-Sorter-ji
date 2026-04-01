import Navbar from './Navbar';

export default function StageLayout({ children, error, onClearError }) {
  return (
    <div className="flex h-screen max-h-screen flex-col overflow-hidden bg-[#111] bg-[radial-gradient(circle,rgba(255,255,255,0.18)_1px,transparent_1px)] bg-[length:14px_14px] font-sans text-white">
      <Navbar />
      <div className="flex min-h-0 flex-1 flex-col">{children}</div>
      {error && (
        <div
          className="fixed bottom-6 left-1/2 z-[200] flex max-w-[90vw] -translate-x-1/2 cursor-pointer items-center gap-3 rounded-[10px] bg-[rgba(220,50,50,0.95)] px-5 py-3 text-sm text-white backdrop-blur-md animate-[ob-slide-up_0.25s_ease]"
          onClick={onClearError}
          role="alert"
        >
          <span>{error}</span>
          <button type="button" className="cursor-pointer border-none bg-transparent p-0 text-xl leading-none text-white/70 hover:opacity-100">
            &times;
          </button>
        </div>
      )}
    </div>
  );
}
