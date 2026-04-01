export default function OnboardingHero() {
  return (
    <div className="shrink-0 px-6 pb-2.5 pt-4 text-center">
      <h1 className="m-0 text-[clamp(22px,3vw,40px)] leading-tight font-extrabold text-white">
        Deploy 100+{' '}
        <span
          className="animate-[ob-gradient-flow_4s_ease_infinite] bg-clip-text text-transparent [background-image:linear-gradient(90deg,rgba(133,123,255,0.9),#BF69A2,rgba(133,123,255,0.9),#BF69A2)] bg-[length:300%_100%] drop-shadow-[0_0_12px_rgba(133,123,255,0.5)]"
        >
          AI Agents
        </span>{' '}
        to Grow Your Business
      </h1>
      <p className="mt-1.5 text-sm text-white/45">Select what Matters most to you right now</p>
    </div>
  );
}
