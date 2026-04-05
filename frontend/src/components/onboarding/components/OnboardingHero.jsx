const TITLES = [
  {
    main: (
      <>
        Deploy 100+{' '}
        <span className="animate-[ob-gradient-flow_4s_ease_infinite] bg-clip-text text-transparent [background-image:linear-gradient(90deg,rgba(133,123,255,0.9),#BF69A2,rgba(133,123,255,0.9),#BF69A2)] bg-[length:300%_100%] drop-shadow-[0_0_12px_rgba(133,123,255,0.5)]">
          AI Agents
        </span>{' '}
        to Grow Your Business
      </>
    ),
    sub: 'Select what Matters most to you right now',
  },
  {
    main: 'What Area do you want to focus on?',
    sub: 'Pick the domain that matters most',
  },
  {
    main: 'What Task would you like help with?',
    sub: 'Choose the specific task to tackle',
  },
];

/**
 * step: 0 = no selection, 1 = outcome selected, 2 = domain selected
 */
export default function OnboardingHero({ step = 0 }) {
  const { main, sub } = TITLES[Math.min(step, TITLES.length - 1)];
  return (
    <div className="shrink-0 px-6 pb-2.5 pt-4 text-center">
      <h1 className="m-0 text-[clamp(22px,3vw,40px)] leading-tight font-extrabold text-white">
        {main}
      </h1>
      <p className="mt-1.5 text-sm text-white/45">{sub}</p>
    </div>
  );
}
