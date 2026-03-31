"""
═══════════════════════════════════════════════════════════════
RCA TREE — Root Cause Analysis Questionnaire Data
═══════════════════════════════════════════════════════════════
Extracted from ChatBotNew.jsx lines 214-754.
Structured as: outcome → persona → sub-area → {problemDefinition, dataCollection}
"""

from __future__ import annotations

from typing import Optional


# ── RCA Stages ─────────────────────────────────────────────────

RCA_STAGES = [
    {"id": "problem-definition", "name": "Problem Definition", "description": "Understanding how to define your problem better"},
    {"id": "data-collection", "name": "Data Collection", "description": "Collecting relevant data for analysis"},
    {"id": "symptom-identification", "name": "Symptom Identification", "description": "Identifying symptoms that may be going unnoticed"},
    {"id": "cause-identification", "name": "Cause Identification", "description": "Identifying potential causes"},
    {"id": "root-cause-validation", "name": "Root Cause Validation", "description": "Validating the root cause"},
    {"id": "corrective-action", "name": "Corrective Action Plan", "description": "Creating an action plan to address the root cause"},
]


# ── RCA Data Tree ──────────────────────────────────────────────

RCA_DATA: dict = {
    "grow-revenue": {
        "founder-owner": {
            "Social media content (posts, ads, videos, product visuals)": {
                "problemDefinition": [
                    {
                        "question": "Q1. What is the main purpose of your social media content right now?",
                        "options": [
                            "Brand awareness", "Generating leads / DMs", "Driving sales",
                            "Retargeting existing users", "Not clearly defined",
                        ],
                    },
                    {
                        "question": "Q2. How do you know content isn't working?",
                        "options": [
                            "Low reach / views", "Engagement but no inquiries",
                            "Inquiries but no sales", "Inconsistent performance", "Not tracked",
                        ],
                    },
                    {
                        "question": "Q3. Which best describes your current content style?",
                        "options": [
                            "Product-focused", "Educational / problem-solving",
                            "Trend / entertainment-based", "Mixed, no clear direction", "Not sure",
                        ],
                    },
                    {
                        "question": "Q4. Where does the breakdown seem to happen?",
                        "options": [
                            "People don't see the content", "People see but don't engage",
                            "Engage but don't inquire", "Inquire but don't buy", "Unsure",
                        ],
                    },
                    {
                        "question": "Q5. How consistent is your content output?",
                        "options": ["Daily / planned", "Weekly", "Irregular", "Very random", "Almost inactive"],
                    },
                    {
                        "question": "Q6. How confident are you that content contributes to revenue?",
                        "options": [
                            "Very confident", "Somewhat confident",
                            "Weak connection", "Mostly guesswork", "No idea",
                        ],
                    },
                ],
                "dataCollection": [
                    "Instagram / Facebook / YouTube profile links",
                    "Last 30–60 days of content",
                    "Posts, reels, ads (whatever exists)",
                    "Which platform brings inquiries? (if known)",
                ],
            },
            "Get more leads from Google & website (SEO)": {
                "problemDefinition": [
                    {"question": "Q1. What are you trying to improve via SEO?", "options": ["Traffic volume", "Lead quality", "Sales / purchases", "Brand visibility", "Not sure"]},
                    {"question": "Q2. What best describes your current traffic?", "options": ["Very low", "Decent but not converting", "High but poor quality", "Seasonal / inconsistent", "Not measured"]},
                    {"question": "Q3. What happens to most visitors?", "options": ["Leave immediately", "Browse but don't act", "Click but don't submit", "Start checkout but abandon", "Not sure"]},
                    {"question": "Q4. Your SEO is mostly built around:", "options": ["High search volume keywords", "Buyer-intent keywords", "Brand terms", "Random content ideas", "No clear strategy"]},
                    {"question": "Q5. How clear is your website's main action?", "options": ["Very clear CTA", "Somewhat clear", "Multiple confusing CTAs", "No strong CTA", "Not sure"]},
                    {"question": "Q6. How confident are you in SEO tracking?", "options": ["Fully tracked", "Partially tracked", "Conflicting data", "Mostly guessing", "Not tracked"]},
                ],
                "dataCollection": [
                    "Website URL", "Top 3 pages they want users to convert from",
                    "Google Search Console access OR screenshots", "Queries", "Pages", "Primary CTA on website",
                ],
            },
            "Run Google and Meta ads + improve ROI": {
                "problemDefinition": [
                    {"question": "Q1. What is the main goal of running ads?", "options": ["Immediate sales", "Lead generation", "Retargeting", "Testing demand", "Not clearly defined"]},
                    {"question": "Q2. What is the biggest concern with ads today?", "options": ["High cost", "Low lead quality", "Low conversion", "Fake / inflated performance", "Don't know"]},
                    {"question": "Q3. Do reported conversions match real sales?", "options": ["Yes, closely", "Some mismatch", "Large mismatch", "Very confusing", "Not tracked"]},
                    {"question": "Q4. Where do users drop after clicking ads?", "options": ["Landing page", "Lead form", "WhatsApp / call", "Checkout", "Not sure"]},
                    {"question": "Q5. Ads are optimized mainly for:", "options": ["Clicks", "Leads", "Purchases", "Value / ROAS", "Unsure"]},
                    {"question": "Q6. How confident are you in ad ROI?", "options": ["Very confident", "Somewhat", "Low confidence", "Guessing", "No clarity"]},
                ],
                "dataCollection": [
                    "Landing page URL used in ads", "Ad account screenshots (last 30 days)",
                    "Spend", "Conversions", "ROAS / CPL",
                    "What happens after the click", "Checkout / WhatsApp / call",
                ],
            },
            "Google Business Profile visibility": {
                "problemDefinition": [
                    {"question": "Q1. What action do you want from GBP visitors?", "options": ["Calls", "Directions / visits", "WhatsApp messages", "Website visits", "Not sure"]},
                    {"question": "Q2. How is your GBP performance currently?", "options": ["Strong visibility", "Visible but low actions", "Low visibility", "Inconsistent", "Never checked"]},
                    {"question": "Q3. Compared to competitors, your reviews are:", "options": ["Much better", "Similar", "Worse", "Very few", "Not sure"]},
                    {"question": "Q4. What happens after inquiries?", "options": ["Convert well", "Some convert", "Mostly drop", "Poor follow-up", "Not tracked"]},
                    {"question": "Q5. Your business is mostly:", "options": ["Location-dependent", "Service-area based", "Hybrid", "Online + offline", "Not sure"]},
                ],
                "dataCollection": [
                    "GBP listing link", "Business category",
                    "Reviews count + rating", "Main CTA enabled (call / website / WhatsApp)",
                ],
            },
            "Understanding why customers don't convert": {
                "problemDefinition": [
                    {"question": "Q1. Where do customers drop most often?", "options": ["Before contacting", "After first interaction", "After price", "After follow-up", "Not sure"]},
                    {"question": "Q2. Common customer response before leaving:", "options": ['"Too expensive"', '"Will think"', '"Comparing options"', "Silent / ghosting", "Varies"]},
                    {"question": "Q3. Conversion depends mainly on:", "options": ["Website checkout", "Human conversation", "Both", "Offline effort", "Not sure"]},
                    {"question": "Q4. What do you think is the main issue?", "options": ["Price sensitivity", "Trust / credibility", "Unclear value", "Weak follow-up", "Wrong audience"]},
                    {"question": "Q5. How structured is conversion tracking?", "options": ["Very clear", "Partial", "Messy", "Guesswork", "None"]},
                ],
                "dataCollection": [
                    "Exact conversion path", "Website → checkout", "Website → WhatsApp",
                    "Ads → call", "Price point",
                    "Any customer messages / chats / objections (anonymized)",
                    "Who handles conversion", "Founder / team / automation",
                ],
            },
            "Selling on WhatsApp/Instagram": {
                "problemDefinition": [
                    {"question": "Q1. Where do most chats come from?", "options": ["Ads", "Organic social", "Website", "Referrals", "Not sure"]},
                    {"question": "Q2. What happens to most chats?", "options": ["Convert quickly", "Long conversations, no sale", "Drop after price", "No response from user", "Not tracked"]},
                    {"question": "Q3. Who handles conversations?", "options": ["Dedicated salesperson", "Founder", "Multiple people", "Automation only", "Mixed / unclear"]},
                    {"question": "Q4. Response time is usually:", "options": ["Immediate", "Within hours", "Same day", "Delayed", "Varies"]},
                    {"question": "Q5. Is there a defined chat-to-sale flow?", "options": ["Yes", "Partially", "Very loose", "None", "Not sure"]},
                ],
                "dataCollection": [
                    "WhatsApp business setup", "Catalog / quick replies / automation (yes/no)",
                    "Sample chat conversations (anonymized)", "Response time expectation",
                    "Payment flow", "Link / UPI / COD / manual",
                ],
            },
            "Lead Qualification, Follow Up & Conversion": {
                "problemDefinition": [
                    {"question": 'Q1. How do you define a "qualified lead"?', "options": ["Budget + intent", "Interest shown", "Anyone who inquires", "Not clearly defined"]},
                    {"question": "Q2. What happens after first contact?", "options": ["Structured follow-up", "One-time contact", "Manual reminders", "Often forgotten"]},
                    {"question": "Q3. Biggest leakage point?", "options": ["First call", "Second follow-up", "Price discussion", "No response", "Not sure"]},
                    {"question": "Q4. How many follow-ups usually happen?", "options": ["3+", "2", "1", "None"]},
                    {"question": "Q5. Lead tracking is:", "options": ["Proper CRM", "Spreadsheet", "WhatsApp only", "No system"]},
                ],
                "dataCollection": [
                    "Product listing URLs", "Top 5 products by revenue",
                    "Bundle or combo pages (if any)", "Cart & checkout flow",
                    "Average order value (approx)",
                ],
            },
            "Ecommerce Listing SEO + upsell bundles": {
                "problemDefinition": [
                    {"question": "Q1. What's the main revenue issue?", "options": ["Low traffic", "Low conversion", "Low order value", "High cart drop", "Not sure"]},
                    {"question": "Q2. Product listings are optimized for:", "options": ["Buyer keywords", "Generic keywords", "Platform suggestions", "Not optimized"]},
                    {"question": "Q3. Most customers buy:", "options": ["One product", "Multiple products", "Bundles", "Depends"]},
                    {"question": "Q4. Bundles exist mainly to:", "options": ["Increase AOV", "Clear inventory", "Solve a use-case", "Discounts only", "No bundles"]},
                    {"question": "Q5. Drop-off usually happens at:", "options": ["Product page", "Cart", "Payment", "Delivery step", "Not sure"]},
                ],
                "dataCollection": [
                    "Product listing URLs", "Top 5 products by revenue",
                    "Bundle or combo pages (if any)", "Cart & checkout flow",
                    "Average order value (approx)",
                ],
            },
        },
    },
}


# ── Categories Data ────────────────────────────────────────────
# Maps Goal + Role to available sub-category labels

CATEGORIES_DATA: dict = {
    "grow-revenue": {
        "founder-owner": [
            "Social media content (posts, ads, videos, product visuals)",
            "Get more leads from Google & website (SEO)",
            "Run Google and Meta ads + improve ROI",
            "Google Business Profile visibility",
            "Understanding why customers don't convert",
            "Selling on WhatsApp/Instagram",
            "Lead Qualification, Follow Up & Conversion",
            "Ecommerce Listing SEO + upsell bundles",
        ],
        "sales-marketing": [
            "Run Google and Meta ads + improve ROI",
            "Social media content (posts, ads, videos, product visuals)",
            "Get more leads from Google & website (SEO)",
            "Qualify & route leads automatically (AI SDR)",
            "Selling on WhatsApp/Instagram",
            "Improve Google Business Profile leads",
            "Write SEO Keyword, blogs and landing pages",
            "Write product titles that rank SEO",
            "Create ad creatives that convert",
            "Create upsell/cross-sell messaging",
        ],
        "ops-admin": [
            "Reduce missed leads with faster replies",
            "Improve order experience to boost repeats",
            "Call, Chat & Ticket Intelligence",
            "Smart CCTV: revenue/footfall insights (advanced)",
        ],
        "finance-legal": [
            "Spot profit leaks and improve margins",
            "Prevent revenue leakage from contracts (renewals, pricing, penalties)",
            "Speed up deal closure with faster contract review",
            "Sales & revenue forecasting",
        ],
        "hr-recruiting": [
            "Hire faster to support growth",
            "Find candidates faster (multi-source)",
            "Resume screening + shortlisting",
        ],
        "support-success": [
            "Improve retention and reduce churn",
            "Upsell/cross-sell recommendations",
            "Improve reviews and response quality",
            "Find why customers don't convert",
            "Call, Chat & Ticket Intelligence",
        ],
        "individual-student": [
            "Personal brand to get opportunities",
            "Business Idea Generation",
            "Trending Products",
        ],
    },
    "save-time": {
        "founder-owner": [
            "Automate lead capture into Sheets/CRM",
            "Draft proposals, quotes, and emails faster",
            "Extract data from PDFs/images to Sheets",
            "Automate procurement requests/approvals",
            "24/7 support assistant + escalation",
            "Automate order updates and tracking",
            "Summarize meetings + action items",
            "Automate HR or Finance",
        ],
        "sales-marketing": [
            "Auto-capture leads from forms/ads",
            "Mail + DM + influencer outreach automation",
            "Repurpose long videos into shorts",
            "Schedule posts + reuse content ideas",
            "Bulk update product listings/catalog",
            "Generate A+ store content at scale",
            "Auto-create weekly content calendar",
            "Auto-reply + follow-up sequences",
        ],
        "ops-admin": [
            "Automate repetitive admin workflows",
            "Excel and App script Automation",
            "Extract invoice/order data from PDFs",
            "Classify docs (invoice/contract/report)",
            "Auto-tag and organize documents",
            "Summarize meetings + send action items",
            "Automate procurement approvals",
            "Track orders + customer notifications",
            "Support ticket routing automation",
            "Smart CCTV: critical event alerts (advanced)",
        ],
        "finance-legal": [
            "Bookkeeping assistance + auto categorization",
            "Expense tracking + spend control automation",
            "Extract invoices/receipts from PDFs into Sheets",
            "Auto-generate client/vendor payment reminders",
            "Draft finance emails, reports, and summaries faster",
            "Extract key terms from contracts (payment, renewal, notice period)",
            "Automate contract approvals, renewals, and deadline reminders",
        ],
        "hr-recruiting": [
            "Automate interview scheduling",
            "Automate candidate follow-ups",
            "High-volume hiring coordination",
            "Onboarding checklists + HR support",
            "Draft job descriptions and outreach",
        ],
        "support-success": [
            "24/7 support assistant + escalation",
            "Auto-tag, route, and prioritize tickets",
            "Draft replies in brand voice",
            "Summarize calls/chats into CRM notes",
            "Build a support knowledge base",
            "WhatsApp/Instagram instant replies",
        ],
        "individual-student": [
            "Draft emails, reports, and proposals",
            "Summarize PDFs and long documents",
            "Extract data from PDFs/images",
            "Organize notes automatically",
        ],
    },
    "better-decisions": {
        "founder-owner": [
            "Instant sales dashboard (daily/weekly)",
            "Marketing performance dashboard (ROI)",
            "Build a knowledge base from SOPs",
            "Track competitors, pricing, and offers",
            "Market & industry trend summaries",
            "Predict demand & business outcomes",
            "Review sentiment → improvement ideas",
            "Churn & retention insights",
            "Cashflow + spend control dashboard",
        ],
        "sales-marketing": [
            "Campaign performance tracking dashboard",
            "Track calls, clicks, and form fills",
            "Call/chat/ticket insights from conversations",
            "Review sentiment + competitor comparisons",
            "Competitor monitoring & price alerts",
            "Market & trend research summaries",
            "Chat with past campaigns and assets",
        ],
        "ops-admin": [
            "Ops dashboard (orders, backlog, SLA)",
            "AI research summaries for decisions",
            "Predict demand and stock needs",
            "Supplier risk monitoring",
            "Delivery/logistics performance reporting",
            "Internal Q&A bot from SOPs/policies",
            "Industry best practice",
            "Customer Churn & Retention Insights",
        ],
        "finance-legal": [
            "Instant finance dashboard (monthly/weekly)",
            "Budget vs actual insights with variance alerts",
            "Cashflow forecast (30/60/90 days)",
            "Predict demand & business outcomes from past data",
            "Spend control alerts and trend insights",
            "Contract risk snapshot (high-risk clauses, obligations, renewals)",
            "Supplier risk and exposure tracking",
        ],
        "hr-recruiting": [
            "Hiring funnel dashboard",
            "Improve hire quality insights",
            "Interview feedback summaries",
            "HR knowledge base from policies",
            "Internal Q&A bot for HR queries",
            "Organize resumes and candidate notes",
        ],
        "support-success": [
            "Support SLA dashboard",
            "Call/chat/ticket intelligence insights",
            "Review sentiment + issue detection",
            "Churn & retention insights",
            "Brand monitoring & crisis alerts",
            "Search/chat across help docs",
            "Internal Q&A bot from SOPs",
        ],
        "individual-student": [
            "Weekly goals + progress summary",
            "Chat with your personal documents",
            "Auto-tag and organize your files",
            "Market & industry trend summaries",
        ],
    },
    "personal-growth": {
        "founder-owner": [
            "Plan weekly priorities and tasks",
            "Prep for pitches and presentations",
            "Personal branding content plan",
            "Create a learning plan + summaries",
            "Contract drafting & review support",
            "Team Spirit Action plan",
        ],
        "sales-marketing": [
            "Plan weekly priorities and tasks",
            "Prep for pitches and presentations",
            "Personal branding content plan",
            "Create a learning plan + summaries",
            "Contract drafting & review support",
            "Team Spirit Action plan",
        ],
        "ops-admin": [
            "Plan weekly priorities and tasks",
            "Prep for pitches and presentations",
            "Personal branding content plan",
            "Create a learning plan + summaries",
            "Contract drafting & review support",
            "Team Spirit Action plan",
        ],
        "finance-legal": [
            "Plan weekly priorities and tasks",
            "Prep for pitches and presentations",
            "Personal branding content plan",
            "Create a learning plan + summaries",
            "Contract drafting & review support",
            "Team Spirit Action plan",
        ],
        "hr-recruiting": [
            "Plan weekly priorities and tasks",
            "Interview prep + question practice",
            "Personal branding content plan",
            "Create a learning plan + summaries",
            "Contract drafting & review support",
            "Team Spirit Action plan",
        ],
    },
}


# ── Lookup Helpers ─────────────────────────────────────────────


def find_rca_data(
    outcome: str,
    persona: str,
    category: str,
) -> Optional[dict]:
    """
    Find RCA questionnaire data for a given outcome+persona+category.
    Supports exact match and partial matching.
    """
    goal_data = RCA_DATA.get(outcome)
    if not goal_data:
        return None

    role_data = goal_data.get(persona)
    if not role_data:
        return None

    # Exact match
    if category in role_data:
        return role_data[category]

    # Partial match
    cat_lower = category.lower()
    for key in role_data:
        key_prefix = key.lower()[:15]
        if cat_lower.startswith(key_prefix) or key_prefix in cat_lower:
            return role_data[key]

    return None


def get_categories(outcome: str, persona: str) -> list[str]:
    """Get available sub-categories for a given outcome and persona."""
    return CATEGORIES_DATA.get(outcome, {}).get(persona, [])
