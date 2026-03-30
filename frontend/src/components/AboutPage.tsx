import { useState } from 'react';
import { ArrowLeft, Shield, FileText, Mail, User, ChevronDown, ChevronRight } from 'lucide-react';
import './AboutPage.css';

const SECTIONS = [
  { id: 'about', label: 'About Ikshan', icon: User },
  { id: 'privacy', label: 'Privacy Policy', icon: Shield },
  { id: 'terms', label: 'Terms & Conditions', icon: FileText },
  { id: 'contact', label: 'Contact Us', icon: Mail },
];

export default function AboutPage({ onBack }) {
  const [activeSection, setActiveSection] = useState('about');

  return (
    <div className="about-page">
      {/* Header — matches landing page style */}
      <header className="about-header">
        <div className="about-header-left">
          <button className="about-back-btn" onClick={onBack}>
            <ArrowLeft size={18} />
            <span>Back</span>
          </button>
        </div>
        <div className="about-header-right">
          <div className="logo-container">
            <img src="/android-chrome-192x192.png" alt="Ikshan" className="logo-img" />
            <h1 className="about-title">Ikshan</h1>
          </div>
        </div>
      </header>

      {/* Navigation Tabs */}
      <nav className="about-nav">
        {SECTIONS.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            className={`about-nav-btn ${activeSection === id ? 'active' : ''}`}
            onClick={() => setActiveSection(id)}
          >
            <Icon size={15} />
            <span>{label}</span>
          </button>
        ))}
      </nav>

      {/* Content */}
      <main className="about-content">
        {activeSection === 'about' && <AboutSection />}
        {activeSection === 'privacy' && <PrivacySection />}
        {activeSection === 'terms' && <TermsSection />}
        {activeSection === 'contact' && <ContactSection />}
      </main>

      <footer className="about-footer">
        <p>© {new Date().getFullYear()} Ikshan. All rights reserved.</p>
      </footer>
    </div>
  );
}

/* ─── About Section ─── */
function AboutSection() {
  return (
    <div className="about-section">
      <h2>Elite Growth Strategy & Execution—Unlocked by AI.</h2>
      <p className="about-lead">
        Most small businesses and startups leave money on the table every single day. Not because they lack vision,
        but because hiring elite, full-time growth experts or agencies is financially out of reach.
      </p>
      <p>
        Ikshan was built to change that. We believe that world-class business growth shouldn't be a luxury reserved
        for massive enterprises. We are bridging the gap between high-level strategy and everyday execution by giving
        you on-demand AI growth expertise that diagnoses your business gaps, ships the perfect strategy, and provides
        the DIY tools to execute it.
      </p>

      <div className="about-divider" />

      <h3>The Problem We Are Solving</h3>
      <div className="about-grid">
        <div className="about-card">
          <span className="about-card-label">The Cost Barrier</span>
          <p>Elite growth teams and specialized agencies drain your runway.</p>
        </div>
        <div className="about-card">
          <span className="about-card-label">The AI Overwhelm</span>
          <p>The AI landscape is noisy. Founders waste hours trying to piece together fragmented tools instead of actually using them to drive revenue.</p>
        </div>
        <div className="about-card">
          <span className="about-card-label">Blind Spots in Growth</span>
          <p>Without deep market, competitor, and internal analysis, companies miss hidden gaps in their funnels, positioning, and value propositions.</p>
        </div>
        <div className="about-card">
          <span className="about-card-label">The Execution Bottleneck</span>
          <p>Even when strategy is clear, executing complex tasks delays momentum and burns out small teams.</p>
        </div>
      </div>

      <div className="about-divider" />

      <h3>How Ikshan Works</h3>
      <p>
        Through our AI Agents, Ikshan deeply analyzes your company, your competitors, and the market. We build the
        massive context needed to pinpoint the exact gaps holding you back. From there, we hand you a customized
        action plan covering over 150+ revenue-growth categories.
      </p>
      <p>
        But we don't stop at strategy. Ikshan connects you directly to the best DIY automation and AI tools,
        letting you execute complex tasks with a single click.
      </p>

      <div className="about-pillars">
        <div className="about-pillar"><span>Lead Generation</span><small>Marketing, SEO, and Social</small></div>
        <div className="about-pillar"><span>Sales & Retention</span><small>Calling, Support, Account Expansion</small></div>
        <div className="about-pillar"><span>Business Strategy</span><small>Market Intelligence & Org Design</small></div>
        <div className="about-pillar"><span>Save Time</span><small>Automation, Operations, Finance</small></div>
      </div>

      <div className="about-divider" />

      <h3>Our Arsenal</h3>
      <div className="about-grid">
        <div className="about-card">
          <span className="about-card-label">Ecom Listing SEO</span>
          <p>Optimize listings and drive 30-40% improvement in revenue.</p>
        </div>
        <div className="about-card">
          <span className="about-card-label">Learn from Competitors</span>
          <p>Reverse-engineer and deploy the best growth hacks in your industry.</p>
        </div>
        <div className="about-card">
          <span className="about-card-label">B2B Lead Gen</span>
          <p>Scrape and secure hot, high-intent leads from Reddit and LinkedIn.</p>
        </div>
        <div className="about-card">
          <span className="about-card-label">YouTube Helper</span>
          <p>End-to-end video strategy, scripting, thumbnails, and keyword analysis.</p>
        </div>
        <div className="about-card">
          <span className="about-card-label">AI Team Professionals</span>
          <p>Deploy specialized AI agents for Marketing, Ops, HR, and more.</p>
        </div>
        <div className="about-card">
          <span className="about-card-label">Content Creator</span>
          <p>Dominate SEO, Instagram, Blogs, and LinkedIn with automated content.</p>
        </div>
      </div>

      <div className="about-divider" />

      <h3>Meet the Founder</h3>
      <div className="about-founder">
        <div className="about-founder-info">
          <h4>Vivek Gaur</h4>
          <span className="about-founder-role">Founder, Ikshan</span>
          <p>
            Vivek is a serial entrepreneur and growth operator who understands the mechanics of scale from the ground up.
            Before founding Ikshan, Vivek served as the Chief Growth Officer (CGO) at Physics Wallah (PW), where he
            engineered and led the company's hyper-growth trajectory from its early startup days all the way to a historic IPO.
          </p>
          <p>
            With a track record that includes two previously acquired startups, Vivek brings a fiercely pragmatic approach
            to business building. He has spent his career mastering the transition from raw startup hustle to highly
            efficient, systemized scale.
          </p>
        </div>
      </div>
    </div>
  );
}

/* ─── Privacy Section ─── */
function PrivacySection() {
  return (
    <div className="about-section about-legal">
      <h2>Privacy Policy</h2>
      <p className="about-legal-date">Last updated: February 2026</p>
      <p>
        Ikshan ("Ikshan," "we," "us," "our") provides an AI-powered business analysis and advisory platform.
        This Privacy Policy explains how we collect, use, share, and protect your information when you use our Services.
      </p>

      <Collapsible title="1. Information We Collect">
        <h4>A. Information you provide</h4>
        <ul>
          <li><strong>Account details:</strong> name, email, password (hashed), company name, role/title.</li>
          <li><strong>Billing details:</strong> billing address, tax info. Payment card details are processed by our payment processor and not stored by us.</li>
          <li><strong>Business inputs:</strong> website URL, product/service details, target audience, positioning notes, funnel numbers.</li>
          <li><strong>Communications:</strong> messages sent to support, feedback, survey responses.</li>
        </ul>
        <h4>B. Information collected automatically</h4>
        <ul>
          <li><strong>Usage data:</strong> pages viewed, clicks, feature usage, timestamps, referral URLs.</li>
          <li><strong>Device and log data:</strong> IP address, browser type, device identifiers, OS, language.</li>
          <li>Cookies and similar technologies.</li>
        </ul>
        <h4>C. Information from integrations (optional)</h4>
        <p>If you connect third-party services, we may access data you authorize via those integrations.</p>
      </Collapsible>

      <Collapsible title="2. How We Use Your Information">
        <ul>
          <li>Provide and operate the Services.</li>
          <li>Personalize outputs based on your business context.</li>
          <li>Measure performance and improve the Services.</li>
          <li>Provide customer support and communicate updates.</li>
          <li>Process payments, manage subscriptions, prevent fraud.</li>
          <li>Comply with legal obligations and enforce agreements.</li>
        </ul>
      </Collapsible>

      <Collapsible title="3. AI Processing and Your Content">
        <ul>
          <li>Your Content remains yours.</li>
          <li>We may use aggregated, de-identified insights to improve our product.</li>
          <li>Do not upload sensitive personal data unless explicitly requested and supported.</li>
        </ul>
      </Collapsible>

      <Collapsible title="4. How We Share Information">
        <ul>
          <li><strong>Service providers:</strong> hosting, analytics, customer support, email/SMS providers.</li>
          <li><strong>Payment processors:</strong> to process payments and manage subscriptions.</li>
          <li><strong>Integration partners:</strong> only when you enable integrations.</li>
          <li><strong>Legal and safety:</strong> if required by law or to protect rights.</li>
          <li><strong>Business transfers:</strong> in a merger, acquisition, or sale of assets.</li>
        </ul>
        <p><strong>We do not sell your personal information.</strong></p>
      </Collapsible>

      <Collapsible title="5. Data Retention">
        <p>We retain personal information as long as needed to provide the Services, comply with legal obligations, resolve disputes, and enforce agreements.</p>
      </Collapsible>

      <Collapsible title="6. Payments and Billing">
        <p>We use third-party payment processors. They may collect and process your payment information under their own privacy policies. Ikshan typically receives limited billing metadata but not full card details.</p>
      </Collapsible>

      <Collapsible title="7. Cookies and Tracking">
        <ul>
          <li>Essential site functionality (login/session).</li>
          <li>Analytics (traffic, usage patterns).</li>
          <li>Performance and debugging.</li>
        </ul>
        <p>You can control cookies through your browser settings.</p>
      </Collapsible>

      <Collapsible title="8. Security">
        <p>We use reasonable administrative, technical, and organizational safeguards to protect information. However, no method of transmission or storage is 100% secure.</p>
      </Collapsible>

      <Collapsible title="9. Your Rights and Choices">
        <ul>
          <li>Access, correct, or delete your personal data.</li>
          <li>Object to or restrict certain processing.</li>
          <li>Withdraw consent where processing is based on consent.</li>
          <li>Request a copy/portability of your data.</li>
        </ul>
      </Collapsible>

      <Collapsible title="10. International Data Transfers">
        <p>If we process data outside your country, we take steps to protect your information consistent with this policy and applicable law.</p>
      </Collapsible>

      <Collapsible title="11. Children's Privacy">
        <p>Our Services are not intended for children under 13. We do not knowingly collect such data.</p>
      </Collapsible>

      <Collapsible title="12. Changes to This Policy">
        <p>We may update this policy from time to time. The "Last updated" date will reflect the latest revision.</p>
      </Collapsible>

      <Collapsible title="13. Contact">
        <p>For privacy questions, contact us at <strong>privacy@ikshan.com</strong></p>
      </Collapsible>
    </div>
  );
}

/* ─── Terms Section ─── */
function TermsSection() {
  return (
    <div className="about-section about-legal">
      <h2>Terms & Conditions</h2>
      <p className="about-legal-date">Last updated: February 2026</p>
      <p>
        These Terms govern your access to and use of the Ikshan website and services.
        By using the Services, you agree to these Terms.
      </p>

      <Collapsible title="1. Who We Are">
        <p>Ikshan is a productized AI professional expertise platform that provides business diagnosis and action plans, focused on inbound lead generation and conversion funnel improvement.</p>
      </Collapsible>

      <Collapsible title="2. Eligibility and Account">
        <p>You must be at least 18 years old. You are responsible for maintaining account confidentiality, all activities under your account, and providing accurate information.</p>
      </Collapsible>

      <Collapsible title="3. Services Provided (Advisor Model)">
        <p>Ikshan provides analysis and recommendations including competitor comparisons, funnel analysis, landing page recommendations, and suggested fixes. <strong>Outputs are informational and advisory.</strong> You are responsible for decisions and actions taken.</p>
      </Collapsible>

      <Collapsible title="4. Acceptable Use">
        <ul>
          <li>Do not use the Services unlawfully or to violate others' rights.</li>
          <li>Do not attempt to reverse engineer or disrupt the Services.</li>
          <li>Do not upload malware or harmful code.</li>
          <li>Do not misrepresent Ikshan outputs as guaranteed results.</li>
        </ul>
      </Collapsible>

      <Collapsible title="5. Your Content and Permissions">
        <p>You own the content you submit. You grant Ikshan a limited license to use it solely to provide and improve the Services.</p>
      </Collapsible>

      <Collapsible title="6. Subscriptions, Billing, and Payments">
        <ul>
          <li>Pricing and billing cycles are shown at purchase.</li>
          <li>Payments are processed by a third-party processor.</li>
          <li>You authorize recurring billing where applicable.</li>
          <li>You can cancel anytime; access continues until the end of the billing period.</li>
        </ul>
      </Collapsible>

      <Collapsible title="7. Intellectual Property">
        <p>Ikshan and its content (software, branding, templates) are owned by Ikshan or licensors and protected by applicable IP laws.</p>
      </Collapsible>

      <Collapsible title="8. Third-Party Links and Integrations">
        <p>The Services may integrate with third-party tools. Ikshan is not responsible for third-party services, their content, or their policies.</p>
      </Collapsible>

      <Collapsible title="9. Disclaimers">
        <ul>
          <li>The Services are provided "as is" and "as available."</li>
          <li>We do not guarantee specific outcomes.</li>
          <li>Ikshan is not a law, tax, or investment advisor.</li>
        </ul>
      </Collapsible>

      <Collapsible title="10. Limitation of Liability">
        <p>Ikshan will not be liable for indirect, incidental, special, consequential, or punitive damages. Total liability will not exceed the amounts you paid in the preceding 12 months.</p>
      </Collapsible>

      <Collapsible title="11. Indemnity">
        <p>You agree to indemnify and hold Ikshan harmless from claims arising out of your use of the Services, your Content, or your violation of these Terms.</p>
      </Collapsible>

      <Collapsible title="12. Termination">
        <p>You may stop using the Services at any time. We may suspend or terminate access if you violate these Terms.</p>
      </Collapsible>

      <Collapsible title="13. Changes to Terms">
        <p>We may update these Terms. If changes are material, we'll provide notice. Continued use means acceptance.</p>
      </Collapsible>

      <Collapsible title="14. Contact">
        <p>Questions about these Terms: <strong>legal@ikshan.com</strong></p>
      </Collapsible>
    </div>
  );
}

/* ─── Contact Section ─── */
function ContactSection() {
  return (
    <div className="about-section">
      <h2>Contact Us</h2>

      <div className="about-contact-grid">
        <div className="about-contact-card">
          <span className="about-contact-label">Company</span>
          <span>IKSHAN AI TECH PRIVATE LIMITED</span>
        </div>
        <div className="about-contact-card">
          <span className="about-contact-label">Address</span>
          <span>PGN-06-12A03, Palm Gardens, Sector 83,<br/>Gurgaon- 122004, Haryana</span>
        </div>
        <div className="about-contact-card">
          <span className="about-contact-label">Phone</span>
          <a href="tel:8810543889">8810543889</a>
        </div>
        <div className="about-contact-card">
          <span className="about-contact-label">Email</span>
          <a href="mailto:infoikshan@gmail.com">infoikshan@gmail.com</a>
        </div>
      </div>
    </div>
  );
}

/* ─── Collapsible Component ─── */
function Collapsible({ title, children }) {
  const [open, setOpen] = useState(false);

  return (
    <div className={`about-collapsible ${open ? 'open' : ''}`}>
      <button className="about-collapsible-trigger" onClick={() => setOpen(!open)}>
        <span>{title}</span>
        {open ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
      </button>
      {open && <div className="about-collapsible-content">{children}</div>}
    </div>
  );
}
