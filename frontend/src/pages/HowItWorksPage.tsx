import { useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';

/**
 * How It Works page — matches the onboarding app color scheme.
 * Converted from the static DoableClaw_HowItWorks.html design.
 */
export default function HowItWorksPage() {
  const navigate = useNavigate();
  const observerRef = useRef<IntersectionObserver | null>(null);

  useEffect(() => {
    observerRef.current = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry, i) => {
          if (entry.isIntersecting) {
            setTimeout(() => entry.target.classList.add('visible'), i * 80);
            observerRef.current?.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.15 }
    );

    document.querySelectorAll('.anim-item').forEach((el) => {
      observerRef.current?.observe(el);
    });

    return () => observerRef.current?.disconnect();
  }, []);

  return (
    <div className="min-h-screen bg-[#111] bg-[radial-gradient(circle,rgba(255,255,255,0.18)_1px,transparent_1px)] bg-[length:14px_14px] font-sans text-white overflow-x-hidden">
      {/* NAV */}
      <nav className="fixed top-0 left-0 right-0 z-50 backdrop-blur-xl bg-[rgba(17,17,17,0.85)] border-b border-white/[0.06]">
        <div className="max-w-[1200px] mx-auto px-8 h-16 flex items-center justify-between">
          <button
            type="button"
            onClick={() => navigate('/')}
            className="font-bold text-xl tracking-tight text-white flex items-center gap-1.5 cursor-pointer bg-transparent border-none"
          >
            Doable<span className="text-transparent bg-clip-text bg-gradient-to-r from-[#857BFF] to-[#BF69A2] font-mono font-bold">Claw</span>
          </button>
          <div className="flex gap-8 items-center">
            <a href="#how" className="text-white/60 text-sm font-medium hover:text-white transition-colors no-underline">How it works</a>
            <a href="#agents" className="text-white/60 text-sm font-medium hover:text-white transition-colors no-underline">Claw agents</a>
            <a href="#reports" className="text-white/60 text-sm font-medium hover:text-white transition-colors no-underline">Reports</a>
            <button
              type="button"
              onClick={() => navigate('/')}
              className="bg-gradient-to-r from-[#857BFF] to-[#BF69A2] text-white px-5 py-2 rounded-lg font-semibold text-sm cursor-pointer border-none hover:brightness-110 hover:-translate-y-0.5 transition-all"
            >
              Get started free
            </button>
          </div>
        </div>
      </nav>

      {/* HERO */}
      <section id="how" className="pt-40 pb-24 px-8 text-center relative">
        <div className="absolute top-0 left-1/2 -translate-x-1/2 w-[800px] h-[800px] bg-[radial-gradient(circle,rgba(133,123,255,0.08)_0%,transparent_70%)] pointer-events-none" />
        <div className="inline-flex items-center gap-2 bg-[rgba(133,123,255,0.12)] border border-[rgba(133,123,255,0.3)] rounded-full px-4 py-1.5 text-xs font-semibold text-[#857BFF] mb-6 tracking-wider uppercase">
          ⚙️ How it works
        </div>
        <h1 className="text-[clamp(2.5rem,5.5vw,4rem)] font-bold tracking-tight leading-[1.1] max-w-[800px] mx-auto mb-6">
          Pick your challenge.<br />
          Our{' '}
          <span className="animate-[ob-gradient-flow_4s_ease_infinite] bg-clip-text text-transparent bg-[linear-gradient(90deg,rgba(133,123,255,0.9),#BF69A2,rgba(133,123,255,0.9),#BF69A2)] bg-[length:300%_100%] drop-shadow-[0_0_12px_rgba(133,123,255,0.5)]">
            Claw Agents
          </span>{' '}
          do the rest.
        </h1>
        <p className="text-lg text-white/50 max-w-[560px] mx-auto leading-relaxed">
          No setup. No configuration. Select a business outcome, get an AI-powered diagnosis and action plan — built for your business, in minutes.
        </p>
      </section>

      {/* TWO PATHWAYS */}
      <section className="py-20 px-8">
        <div className="max-w-[1100px] mx-auto">
          <div className="text-xs font-mono uppercase tracking-[0.15em] text-[#857BFF] font-bold mb-3">Two ways in</div>
          <h2 className="text-[clamp(1.75rem,3.5vw,2.5rem)] font-bold tracking-tight leading-[1.15] mb-4">
            Start from your challenge, or browse by solution.
          </h2>
          <p className="text-base text-white/50 max-w-[600px] leading-relaxed mb-12">
            Every path leads to the same thing: specialized Claw Agents executing growth tasks for your business.
          </p>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {/* Path 1 */}
            <div className="anim-item opacity-0 translate-y-5 transition-all duration-500 bg-[#161616] border border-white/[0.06] rounded-2xl p-8 relative overflow-hidden cursor-pointer hover:border-[rgba(133,123,255,0.3)] hover:-translate-y-0.5 hover:bg-[#1a1a1a] group">
              <div className="absolute top-0 right-0 w-32 h-32 rounded-full bg-[rgba(29,158,117,0.12)] blur-[60px]" />
              <div className="w-12 h-12 rounded-xl bg-[rgba(29,158,117,0.12)] text-[#1D9E75] flex items-center justify-center text-xl mb-5">🎯</div>
              <h3 className="text-xl font-bold mb-2">Path 1 — Start with your challenge</h3>
              <p className="text-sm text-white/50 leading-relaxed">
                Select from 150+ business outcome categories across 4 growth domains. Our agents scrape your website, analyze your market, and build a playbook specific to your business.
              </p>
              <span className="inline-block mt-4 text-xs font-semibold px-3 py-1 rounded-full bg-[rgba(29,158,117,0.12)] text-[#1D9E75] tracking-wide">
                Free audit included
              </span>
            </div>

            {/* Path 2 */}
            <div className="anim-item opacity-0 translate-y-5 transition-all duration-500 bg-[#161616] border border-white/[0.06] rounded-2xl p-8 relative overflow-hidden cursor-pointer hover:border-[rgba(133,123,255,0.3)] hover:-translate-y-0.5 hover:bg-[#1a1a1a] group">
              <div className="absolute top-0 right-0 w-32 h-32 rounded-full bg-[rgba(133,123,255,0.12)] blur-[60px]" />
              <div className="w-12 h-12 rounded-xl bg-[rgba(133,123,255,0.12)] text-[#857BFF] flex items-center justify-center text-xl mb-5">⚡</div>
              <h3 className="text-xl font-bold mb-2">Path 2 — Browse our product library</h3>
              <p className="text-sm text-white/50 leading-relaxed">
                Go directly to our 100+ Claw Agent catalog. Pick the agent that matches your growth need — SEO, lead gen, churn prevention, pricing — and activate it instantly.
              </p>
              <span className="inline-block mt-4 text-xs font-semibold px-3 py-1 rounded-full bg-[rgba(133,123,255,0.12)] text-[#857BFF] tracking-wide">
                Direct activation
              </span>
            </div>
          </div>
        </div>
      </section>

      {/* PATH 1 FLOW */}
      <section id="flow" className="py-20 px-8 bg-[#0d0d0d] border-t border-b border-white/[0.06]">
        <div className="max-w-[1100px] mx-auto">
          <div className="text-xs font-mono uppercase tracking-[0.15em] text-[#857BFF] font-bold mb-3">Path 1 — Detailed</div>
          <h2 className="text-[clamp(1.75rem,3.5vw,2.5rem)] font-bold tracking-tight leading-[1.15] mb-4">
            From challenge to custom playbook in 4 steps
          </h2>
          <p className="text-base text-white/50 max-w-[600px] leading-relaxed mb-12">
            Start free. Our agents do the heavy lifting — scraping, analyzing, and building a growth blueprint tailored to your business.
          </p>

          <div className="relative">
            {/* Vertical line */}
            <div className="absolute left-1/2 top-0 bottom-0 w-px bg-gradient-to-b from-transparent via-[rgba(133,123,255,0.3)] to-transparent -translate-x-1/2 hidden md:block" />

            {/* Step 1 */}
            <div className="anim-item opacity-0 translate-y-5 transition-all duration-500 grid grid-cols-1 md:grid-cols-[1fr_48px_1fr] gap-0 items-start mb-16">
              <div className="md:text-right px-0 md:px-8 order-2 md:order-1">
                <h3 className="text-xl font-bold mb-2">1 — Select your challenge</h3>
                <p className="text-sm text-white/50 leading-relaxed">
                  Pick from 4 outcome domains — Lead Generation, Sales & Retention, Business Strategy, or Save Time. Each domain branches into granular task-level challenges.
                </p>
                <p className="mt-4 text-sm text-white/30 italic">
                  You're not configuring anything. You're telling us what growth problem keeps you up at night.
                </p>
              </div>
              <div className="hidden md:flex w-12 h-12 items-center justify-center order-1 md:order-2">
                <div className="w-9 h-9 rounded-full border-2 border-[#857BFF] bg-[#111] flex items-center justify-center font-mono text-xs font-bold text-[#857BFF]">01</div>
              </div>
              <div className="px-0 md:px-4 mt-4 md:mt-0 order-3">
                <div className="bg-[#161616] border border-white/[0.06] rounded-xl p-5">
                  <span className="text-[10px] font-mono uppercase tracking-[0.12em] text-white/40 mb-3 block">Outcome domains</span>
                  <div className="flex flex-wrap gap-1.5">
                    <span className="px-2.5 py-1 rounded-md bg-[rgba(133,123,255,0.15)] border border-[#857BFF] text-xs text-[#857BFF]">Lead generation</span>
                    <span className="px-2.5 py-1 rounded-md bg-[#1a1a1a] border border-white/[0.06] text-xs text-white/50">Sales & retention</span>
                    <span className="px-2.5 py-1 rounded-md bg-[#1a1a1a] border border-white/[0.06] text-xs text-white/50">Business strategy</span>
                    <span className="px-2.5 py-1 rounded-md bg-[#1a1a1a] border border-white/[0.06] text-xs text-white/50">Save time</span>
                  </div>
                  <div className="mt-3 pt-3 border-t border-white/[0.06]">
                    <span className="text-[10px] font-mono uppercase tracking-[0.12em] text-white/40 mb-3 block">Task-level drilldown</span>
                    <div className="flex flex-wrap gap-1.5">
                      <span className="px-2.5 py-1 rounded-md bg-[rgba(133,123,255,0.15)] border border-[#857BFF] text-xs text-[#857BFF]">SEO & organic</span>
                      <span className="px-2.5 py-1 rounded-md bg-[#1a1a1a] border border-white/[0.06] text-xs text-white/50">Content & social</span>
                      <span className="px-2.5 py-1 rounded-md bg-[#1a1a1a] border border-white/[0.06] text-xs text-white/50">Paid ads</span>
                      <span className="px-2.5 py-1 rounded-md bg-[#1a1a1a] border border-white/[0.06] text-xs text-white/50">B2B prospecting</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            {/* Step 2 */}
            <div className="anim-item opacity-0 translate-y-5 transition-all duration-500 grid grid-cols-1 md:grid-cols-[1fr_48px_1fr] gap-0 items-start mb-16">
              <div className="px-0 md:px-4 mt-4 md:mt-0 order-3 md:order-1">
                <div className="bg-[#161616] border border-white/[0.06] rounded-xl p-5">
                  <span className="text-[10px] font-mono uppercase tracking-[0.12em] text-white/40 mb-3 block">Agent activity</span>
                  <div className="flex flex-col gap-2">
                    <div className="flex items-center gap-2">
                      <span className="w-1.5 h-1.5 rounded-full bg-[#1D9E75] shrink-0" />
                      <span className="text-xs text-white/50">Scraping website structure & copy...</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="w-1.5 h-1.5 rounded-full bg-[#EF9F27] shrink-0" />
                      <span className="text-xs text-white/50">Analyzing competitor positioning...</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="w-1.5 h-1.5 rounded-full bg-[#857BFF] shrink-0" />
                      <span className="text-xs text-white/50">Building task-specific playbook...</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="w-1.5 h-1.5 rounded-full bg-[#378ADD] shrink-0" />
                      <span className="text-xs text-white/50">Mapping market intelligence...</span>
                    </div>
                  </div>
                  <div className="mt-3 h-1 bg-white/[0.06] rounded overflow-hidden">
                    <div className="w-[65%] h-full bg-gradient-to-r from-[#857BFF] to-[#BF69A2] rounded animate-pulse" />
                  </div>
                </div>
              </div>
              <div className="hidden md:flex w-12 h-12 items-center justify-center order-1 md:order-2">
                <div className="w-9 h-9 rounded-full border-2 border-[#857BFF] bg-[#111] flex items-center justify-center font-mono text-xs font-bold text-[#857BFF]">02</div>
              </div>
              <div className="px-0 md:px-8 order-2 md:order-3">
                <h3 className="text-xl font-bold mb-2">2 — Agents scrape & analyze</h3>
                <p className="text-sm text-white/50 leading-relaxed">
                  Our Claw Agents go to work — crawling your website, scraping publicly available market data, analyzing competitor moves, and mapping your business context.
                </p>
                <p className="mt-4 text-sm text-white/30 italic">
                  This isn't generic advice. Every insight is built from your actual web presence and real market conditions.
                </p>
              </div>
            </div>

            {/* Step 3 */}
            <div className="anim-item opacity-0 translate-y-5 transition-all duration-500 grid grid-cols-1 md:grid-cols-[1fr_48px_1fr] gap-0 items-start mb-16">
              <div className="md:text-right px-0 md:px-8 order-2 md:order-1">
                <h3 className="text-xl font-bold mb-2">3 — Get your free audit report</h3>
                <p className="text-sm text-white/50 leading-relaxed">
                  In under 60 seconds, receive a customized playbook covering your selected challenge area — complete with action steps, ready-to-use prompts, and one-click Claw Agent activation.
                </p>
                <p className="mt-4 text-sm text-white/30 italic">
                  Think of it as a growth consultant's first session — free, fast, and specific to your business.
                </p>
              </div>
              <div className="hidden md:flex w-12 h-12 items-center justify-center order-1 md:order-2">
                <div className="w-9 h-9 rounded-full border-2 border-[#857BFF] bg-[#111] flex items-center justify-center font-mono text-xs font-bold text-[#857BFF]">03</div>
              </div>
              <div className="px-0 md:px-4 mt-4 md:mt-0 order-3">
                <div className="bg-[#161616] border border-[rgba(29,158,117,0.3)] rounded-xl p-5">
                  <span className="text-[10px] font-mono uppercase tracking-[0.12em] text-[#1D9E75] mb-3 block">Free audit preview</span>
                  <div className="text-sm text-white/50 leading-relaxed space-y-2">
                    <div className="flex items-center gap-2"><span className="text-[#1D9E75]">✓</span> Business-specific playbook</div>
                    <div className="flex items-center gap-2"><span className="text-[#1D9E75]">✓</span> Task-level action steps</div>
                    <div className="flex items-center gap-2"><span className="text-[#1D9E75]">✓</span> AI tool recommendations</div>
                    <div className="flex items-center gap-2"><span className="text-[#1D9E75]">✓</span> Ready-to-use prompts</div>
                  </div>
                </div>
              </div>
            </div>

            {/* Step 4 */}
            <div className="anim-item opacity-0 translate-y-5 transition-all duration-500 grid grid-cols-1 md:grid-cols-[1fr_48px_1fr] gap-0 items-start">
              <div className="px-0 md:px-4 mt-4 md:mt-0 order-3 md:order-1">
                <div className="bg-[#161616] border border-[rgba(133,123,255,0.3)] rounded-xl p-5">
                  <span className="text-[10px] font-mono uppercase tracking-[0.12em] text-[#857BFF] mb-3 block">Paid deep report</span>
                  <div className="text-sm text-white/50 leading-relaxed space-y-1.5">
                    <div className="flex items-center gap-2"><span className="text-[#857BFF]">◆</span> Depth action plan</div>
                    <div className="flex items-center gap-2"><span className="text-[#857BFF]">◆</span> 10 competitive intel insights</div>
                    <div className="flex items-center gap-2"><span className="text-[#857BFF]">◆</span> 10 brand & product levers</div>
                    <div className="flex items-center gap-2"><span className="text-[#857BFF]">◆</span> 10 conversion optimizations</div>
                    <div className="flex items-center gap-2"><span className="text-[#857BFF]">◆</span> 5 urgent action playbooks</div>
                    <div className="flex items-center gap-2"><span className="text-[#857BFF]">◆</span> 30+ gap analysis points</div>
                  </div>
                </div>
              </div>
              <div className="hidden md:flex w-12 h-12 items-center justify-center order-1 md:order-2">
                <div className="w-9 h-9 rounded-full border-2 border-[#857BFF] bg-[#111] flex items-center justify-center font-mono text-xs font-bold text-[#857BFF]">04</div>
              </div>
              <div className="px-0 md:px-8 order-2 md:order-3">
                <h3 className="text-xl font-bold mb-2">4 — Unlock the full deep report</h3>
                <p className="text-sm text-white/50 leading-relaxed">
                  Upgrade to get 30+ revenue gaps identified, competitive battle cards, conversion audits, and step-by-step TODO playbooks — each powered by dedicated Claw Agents.
                </p>
                <p className="mt-4 text-sm text-white/30 italic">
                  This is where the real ROI lives. Every gap comes with an executable action plan, not just a PDF.
                </p>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* OUTCOME DOMAINS */}
      <section className="py-20 px-8">
        <div className="max-w-[1100px] mx-auto">
          <div className="text-xs font-mono uppercase tracking-[0.15em] text-[#857BFF] font-bold mb-3">4 Outcome domains</div>
          <h2 className="text-[clamp(1.75rem,3.5vw,2.5rem)] font-bold tracking-tight leading-[1.15] mb-4">
            Every business challenge maps to a domain.
          </h2>
          <p className="text-base text-white/50 max-w-[600px] leading-relaxed mb-8">
            150+ revenue-growth categories. Each one has a dedicated Claw Agent ready to execute.
          </p>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div className="anim-item opacity-0 translate-y-5 transition-all duration-500 bg-[#161616] border border-white/[0.06] rounded-xl p-5 text-center cursor-pointer hover:border-[rgba(133,123,255,0.3)] hover:-translate-y-0.5">
              <div className="text-2xl mb-3 text-[#857BFF]">☯</div>
              <div className="text-sm font-semibold mb-1">Lead generation</div>
              <div className="text-[11px] font-mono text-white/40">SEO, Social, Ads, B2B, Email</div>
            </div>
            <div className="anim-item opacity-0 translate-y-5 transition-all duration-500 bg-[#161616] border border-white/[0.06] rounded-xl p-5 text-center cursor-pointer hover:border-[rgba(133,123,255,0.3)] hover:-translate-y-0.5">
              <div className="text-2xl mb-3 text-[#1D9E75]">★</div>
              <div className="text-sm font-semibold mb-1">Sales & retention</div>
              <div className="text-[11px] font-mono text-white/40">Sales ops, CRM, Upsell, Churn</div>
            </div>
            <div className="anim-item opacity-0 translate-y-5 transition-all duration-500 bg-[#161616] border border-white/[0.06] rounded-xl p-5 text-center cursor-pointer hover:border-[rgba(133,123,255,0.3)] hover:-translate-y-0.5">
              <div className="text-2xl mb-3 text-[#BF69A2]">⚙</div>
              <div className="text-sm font-semibold mb-1">Business strategy</div>
              <div className="text-[11px] font-mono text-white/40">Intel, Pricing, Innovation, BI</div>
            </div>
            <div className="anim-item opacity-0 translate-y-5 transition-all duration-500 bg-[#161616] border border-white/[0.06] rounded-xl p-5 text-center cursor-pointer hover:border-[rgba(133,123,255,0.3)] hover:-translate-y-0.5">
              <div className="text-2xl mb-3 text-[#EF9F27]">⚡</div>
              <div className="text-sm font-semibold mb-1">Save time</div>
              <div className="text-[11px] font-mono text-white/40">Automation, HR, Finance, Ops</div>
            </div>
          </div>
        </div>
      </section>

      {/* REPORT COMPARISON */}
      <section id="reports" className="py-20 px-8 bg-[#0d0d0d] border-t border-b border-white/[0.06]">
        <div className="max-w-[1100px] mx-auto">
          <div className="text-xs font-mono uppercase tracking-[0.15em] text-[#857BFF] font-bold mb-3">Free vs. paid</div>
          <h2 className="text-[clamp(1.75rem,3.5vw,2.5rem)] font-bold tracking-tight leading-[1.15] mb-4">
            Start free. Go deep when you're ready.
          </h2>
          <p className="text-base text-white/50 max-w-[600px] leading-relaxed mb-10">
            The free audit gives you enough to act on today. The paid report gives you everything a growth consultant would deliver — in minutes, not weeks.
          </p>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {/* Free */}
            <div className="bg-[#161616] border border-white/[0.06] rounded-2xl p-8">
              <span className="inline-block text-[10px] font-mono uppercase tracking-[0.12em] font-bold px-3 py-1 rounded-md bg-[rgba(29,158,117,0.12)] text-[#1D9E75] mb-4">Free audit</span>
              <h3 className="text-lg font-bold mb-1">Quick taste</h3>
              <p className="text-sm text-white/50 mb-6">Generated in 60 seconds from your URL or challenge</p>
              <ul className="space-y-3">
                <li className="flex items-start gap-2.5 text-sm text-white/50 leading-relaxed">
                  <span className="shrink-0 w-[18px] h-[18px] rounded-full bg-[rgba(29,158,117,0.12)] text-[#1D9E75] flex items-center justify-center text-[10px] mt-0.5">✓</span>
                  Customized playbook for your selected challenge
                </li>
                <li className="flex items-start gap-2.5 text-sm text-white/50 leading-relaxed">
                  <span className="shrink-0 w-[18px] h-[18px] rounded-full bg-[rgba(29,158,117,0.12)] text-[#1D9E75] flex items-center justify-center text-[10px] mt-0.5">✓</span>
                  Task-level action steps with AI tool picks
                </li>
                <li className="flex items-start gap-2.5 text-sm text-white/50 leading-relaxed">
                  <span className="shrink-0 w-[18px] h-[18px] rounded-full bg-[rgba(29,158,117,0.12)] text-[#1D9E75] flex items-center justify-center text-[10px] mt-0.5">✓</span>
                  Ready-to-use prompts & templates
                </li>
                <li className="flex items-start gap-2.5 text-sm text-white/50 leading-relaxed">
                  <span className="shrink-0 w-[18px] h-[18px] rounded-full bg-[rgba(29,158,117,0.12)] text-[#1D9E75] flex items-center justify-center text-[10px] mt-0.5">✓</span>
                  One-click Claw Agent activation preview
                </li>
                <li className="flex items-start gap-2.5 text-sm text-white/50 leading-relaxed">
                  <span className="shrink-0 w-[18px] h-[18px] rounded-full bg-[rgba(29,158,117,0.12)] text-[#1D9E75] flex items-center justify-center text-[10px] mt-0.5">✓</span>
                  Preview of 150+ growth categories
                </li>
              </ul>
            </div>

            {/* Paid */}
            <div className="bg-[#161616] border border-[rgba(133,123,255,0.4)] rounded-2xl p-8 shadow-[0_0_40px_rgba(133,123,255,0.08)]">
              <span className="inline-block text-[10px] font-mono uppercase tracking-[0.12em] font-bold px-3 py-1 rounded-md bg-[rgba(133,123,255,0.12)] text-[#857BFF] mb-4">Paid deep report</span>
              <h3 className="text-lg font-bold mb-1">Full growth diagnosis</h3>
              <p className="text-sm text-white/50 mb-6">30+ gaps identified with executable action plans</p>
              <ul className="space-y-3">
                <li className="flex items-start gap-2.5 text-sm text-white/50 leading-relaxed">
                  <span className="shrink-0 w-[18px] h-[18px] rounded-full bg-[rgba(133,123,255,0.12)] text-[#857BFF] flex items-center justify-center text-[10px] mt-0.5">◆</span>
                  Depth action plan with AI-powered business analysis
                </li>
                <li className="flex items-start gap-2.5 text-sm text-white/50 leading-relaxed">
                  <span className="shrink-0 w-[18px] h-[18px] rounded-full bg-[rgba(133,123,255,0.12)] text-[#857BFF] flex items-center justify-center text-[10px] mt-0.5">◆</span>
                  10 competitive intelligence insights (top 3 competitors)
                </li>
                <li className="flex items-start gap-2.5 text-sm text-white/50 leading-relaxed">
                  <span className="shrink-0 w-[18px] h-[18px] rounded-full bg-[rgba(133,123,255,0.12)] text-[#857BFF] flex items-center justify-center text-[10px] mt-0.5">◆</span>
                  10 high-leverage brand & product levers
                </li>
                <li className="flex items-start gap-2.5 text-sm text-white/50 leading-relaxed">
                  <span className="shrink-0 w-[18px] h-[18px] rounded-full bg-[rgba(133,123,255,0.12)] text-[#857BFF] flex items-center justify-center text-[10px] mt-0.5">◆</span>
                  10 conversion optimizations for 2X sales potential
                </li>
                <li className="flex items-start gap-2.5 text-sm text-white/50 leading-relaxed">
                  <span className="shrink-0 w-[18px] h-[18px] rounded-full bg-[rgba(133,123,255,0.12)] text-[#857BFF] flex items-center justify-center text-[10px] mt-0.5">◆</span>
                  5 urgent action playbooks with content & prompts
                </li>
                <li className="flex items-start gap-2.5 text-sm text-white/50 leading-relaxed">
                  <span className="shrink-0 w-[18px] h-[18px] rounded-full bg-[rgba(133,123,255,0.12)] text-[#857BFF] flex items-center justify-center text-[10px] mt-0.5">◆</span>
                  100+ Claw Agent library with instant activation
                </li>
              </ul>
            </div>
          </div>
        </div>
      </section>

      {/* CLAW AGENTS */}
      <section id="agents" className="py-20 px-8">
        <div className="max-w-[1100px] mx-auto">
          <div className="text-xs font-mono uppercase tracking-[0.15em] text-[#857BFF] font-bold mb-3">100+ Claw agents</div>
          <h2 className="text-[clamp(1.75rem,3.5vw,2.5rem)] font-bold tracking-tight leading-[1.15] mb-4">
            One agent per task. Activate and go.
          </h2>
          <p className="text-base text-white/50 max-w-[600px] leading-relaxed mb-8">
            Every growth task has a dedicated Claw Agent — pre-built with skills, connectors, and sub-agents. No setup. No pipelines. Just results.
          </p>

          <div className="flex gap-3 overflow-x-auto pb-4 scrollbar-thin scrollbar-thumb-white/10">
            {[
              { name: 'SEO Claw', task: 'Rank higher on Google', color: '#857BFF' },
              { name: 'Conversion Claw', task: 'Fix your funnel leaks', color: '#1D9E75' },
              { name: 'Competitor Intel Claw', task: "Spy on what's working", color: '#BF69A2' },
              { name: 'Copy Claw', task: 'Write in customer language', color: '#EF9F27' },
              { name: 'Pricing Claw', task: 'Optimize your price points', color: '#378ADD' },
              { name: 'Churn Claw', task: 'Predict & prevent churn', color: '#857BFF' },
              { name: 'Lead Magnet Claw', task: 'Build irresistible offers', color: '#1D9E75' },
              { name: 'Brand Health Claw', task: 'Track brand sentiment', color: '#BF69A2' },
              { name: 'CTA Claw', task: 'Restructure page flow', color: '#EF9F27' },
              { name: 'Google Business Claw', task: 'Dominate local search', color: '#378ADD' },
              { name: 'Trust Audit Claw', task: 'Build buyer confidence', color: '#857BFF' },
              { name: 'AI Readiness Claw', task: 'Plan your AI adoption', color: '#1D9E75' },
            ].map((agent, i) => (
              <div
                key={i}
                className="anim-item opacity-0 translate-y-5 transition-all duration-500 shrink-0 bg-[#161616] border border-white/[0.06] rounded-xl px-4 py-3 flex items-center gap-2.5 min-w-[200px] cursor-pointer hover:border-[rgba(133,123,255,0.3)] hover:-translate-y-0.5 hover:bg-[#1a1a1a]"
              >
                <span className="w-2 h-2 rounded-full shrink-0" style={{ background: agent.color }} />
                <div>
                  <div className="text-xs font-semibold whitespace-nowrap">{agent.name}</div>
                  <div className="text-[11px] text-white/40 whitespace-nowrap">{agent.task}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="py-24 px-8 text-center relative">
        <div className="absolute bottom-0 left-1/2 -translate-x-1/2 w-[700px] h-[400px] bg-[radial-gradient(ellipse,rgba(133,123,255,0.08)_0%,transparent_70%)] pointer-events-none" />
        <h2 className="text-[clamp(1.75rem,3.5vw,2.5rem)] font-bold tracking-tight leading-[1.15] mb-3">
          Ready to find your growth gaps?
        </h2>
        <p className="text-base text-white/50 mb-10">
          Enter your website or pick a challenge. Free audit in 60 seconds.
        </p>
        <button
          type="button"
          onClick={() => navigate('/')}
          className="inline-flex items-center gap-2 bg-gradient-to-r from-[#857BFF] to-[#BF69A2] text-white px-8 py-3.5 rounded-xl font-bold text-base cursor-pointer border-none hover:brightness-110 hover:-translate-y-0.5 hover:shadow-[0_8px_30px_rgba(133,123,255,0.25)] transition-all"
        >
          Start free audit →
        </button>
        <button
          type="button"
          onClick={() => navigate('/new')}
          className="inline-flex items-center gap-2 bg-transparent text-white px-8 py-3.5 rounded-xl font-semibold text-base cursor-pointer border border-white/[0.1] hover:border-white/30 transition-all ml-4"
        >
          Browse all agents
        </button>
      </section>

      {/* FOOTER */}
      <footer className="border-t border-white/[0.06] py-10 px-8 text-center">
        <p className="text-xs text-white/30">
          © 2026 DoableClaw · 100+ AI Claw Agents for Business Growth ·{' '}
          <a href="/privacy" className="text-white/30 underline">Privacy</a>
        </p>
      </footer>

      <style>{`
        .anim-item.visible {
          opacity: 1 !important;
          transform: translateY(0) !important;
        }
        .scrollbar-thin::-webkit-scrollbar {
          height: 4px;
        }
        .scrollbar-thin::-webkit-scrollbar-thumb {
          background: rgba(255,255,255,0.1);
          border-radius: 2px;
        }
        .scrollbar-thin::-webkit-scrollbar-track {
          background: transparent;
        }
      `}</style>
    </div>
  );
}

