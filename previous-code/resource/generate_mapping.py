
"""
Generate tools_by_q1_q2_q3.json — Pre-maps tools to Q1→Q2→Q3 diagnostic paths.
Reads: tools.xlsx (All Tools sheet) + categories CSV
Outputs: tools_by_q1_q2_q3.json in same directory
"""

import csv
import json
import os
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

import openpyxl

BASE = Path(__file__).parent.parent
TOOLS_XLSX = Path(__file__).parent / "tools.xlsx"
CATEGORIES_CSV = BASE / "categories - Categories (1).csv"
OUTPUT = Path(__file__).parent / "tools_by_q1_q2_q3.json"

# ── Semantic mapping: CSV task → equivalent xlsx tool-task strings ──
# These bridge the naming gap between user-facing tasks in the CSV
# and the task labels assigned to tools in the xlsx dataset.
CSV_TO_XLSX_ALIASES = {
    # SEO & Organic Visibility
    "Get more leads from Google & website (SEO)": [
        "Write SEO Keyword blogs and landing pages",
    ],
    "Google Business Profile visibility": [
        "Improve Google Business Profile leads",
        "Google Business Profile visibility",
        "Write SEO Keyword blogs and landing pages",
    ],
    "Improve Google Business Profile leads": [
        "Google Business Profile visibility",
        "Improve Google Business Profile leads",
        "Write SEO Keyword blogs and landing pages",
    ],
    "Write product titles that rank SEO": [
        "Write SEO Keyword blogs and landing pages",
        "Bulk update product listings/catalog",
    ],
    "Ecommerece Lisitng SEO + upsell bundles": [
        "Bulk update product listings/catalog",
        "Create bundles to increase Average Order Value (AOV)",
    ],
    # Sales Execution
    "Selling on WhatsApp/Instagram": [
        "Drive sales on WhatsApp & Instagram",
        "WhatsApp/Instagram instant replies",
    ],
    "Speed up deal closure with faster contract review": [
        "Review contracts & accelerate deal signing",
    ],
    "Chat with past campaigns and assets": [
        "Instant answers from sales docs & past deals",
    ],
    # Lead Management & Conversion
    "Qualify & route leads automatically (AI SDR)": [
        "Automate lead qualification & scoring (AI SDR)",
    ],
    "Lead Qualification Follow Up & Conversion": [
        "Automate lead qualification & scoring (AI SDR)",
        "Reactivate cold or dead leads",
        "Run automated nurture & recovery sequences",
    ],
    "Reduce missed leads with faster replies": [
        "Instant 24/7 lead response & booking",
        "Auto\u2011reply + follow\u2011up sequences",
    ],
    "Find why customers don't convert": [
        "Analyze lost deals to uncover objections",
        "Predict churn risk & alert success teams",
        "Detect angry customers for priority routing",
        "Automate review collection & smart responses",
    ],
    "Understanding why customers don't convert": [
        "Analyze lost deals to uncover objections",
        "Predict churn risk & alert success teams",
        "Detect angry customers for priority routing",
        "Automate review collection & smart responses",
    ],
    # Customer Success & Reputation
    "Improve reviews and response quality": [
        "Automate review collection & smart responses",
    ],
    "Call Chat & Ticket Intelligence": [
        "Extract actionable insights from calls",
        "Analyze support calls & tickets for root causes",
    ],
    "Improve retention and reduce churn": [
        "Predict churn risk & alert success teams",
    ],
    "Churn & retention insights": [
        "Predict churn risk & alert success teams",
    ],
    "Support SLA dashboard": [
        "Track support SLAs & agent performance",
        "Monitor operational SLAs & delivery bottlenecks",
    ],
    "Call/chat/ticket intelligence insights": [
        "Extract actionable insights from calls",
        "Analyze support calls & tickets for root causes",
    ],
    "Review sentiment + issue detection": [
        "Automate review collection & smart responses",
        "Detect angry customers for priority routing",
    ],
    # Repeat Sales
    "Upsell/cross\u2011sell recommendations": [
        "Automate personalized upsell & cross-sell messages",
        "Predict 'Next Best Product' to recommend",
        "Create bundles to increase Average Order Value (AOV)",
    ],
    "Create upsell/cross-sell messaging": [
        "Automate personalized upsell & cross-sell messages",
    ],
    "Improve order experience to boost repeats": [
        "Track orders + customer notifications",
        "Trigger re-order & renewal reminders",
    ],
    # Business Intelligence & Analytics
    "Instant sales dashboard (daily/weekly)": [
        "Build a real-time sales & revenue command center",
        "Optimize marketing impact through out of the box dashboards",
    ],
    "Marketing performance dashboard (ROI)": [
        "Track marketing ROI across ads & organic channels",
        "Optimize marketing impact through out of the box dashboards",
    ],
    "Campaign performance tracking dashboard": [
        "Track marketing ROI across ads & organic channels",
        "Compare performance vs. competitors & benchmarks",
    ],
    "Track calls Clicks and form fills": [
        "Extract actionable insights from calls",
        "Track marketing ROI across ads & organic channels",
    ],
    "Call/chat/ticket insights from conversations": [
        "Extract actionable insights from calls",
        "Analyze support calls & tickets for root causes",
    ],
    "Review sentiment \u2192 improvement ideas": [
        "Automate review collection & smart responses",
    ],
    "Review sentiment + competitor comparisons": [
        "Automate review collection & smart responses",
        "Compare performance vs. competitors & benchmarks",
    ],
    "Ops dashboard (orders blacklog SLA)": [
        "Monitor operational SLAs & delivery bottlenecks",
        "Track team goals & operational bottlenecks",
    ],
    # Market Strategy & Innovation
    "Business Idea Generation": [
        "Validate new business ideas before launch",
        "Conduct smarter, faster market research",
    ],
    "Trending Products": [
        "Identify trending products & market opportunities",
    ],
    "Track competitors prcing and offers": [
        "Track competitor pricing & promotional strategies",
        "Spy on competitor ads & offers",
    ],
    "Predict demand & business outcomes": [
        "Forecast revenue & inventory requirements",
    ],
    "Competitor monitoring & price alerts": [
        "Track competitor pricing & promotional strategies",
        "Compare performance vs. competitors & benchmarks",
    ],
    "Market & trend research summaries": [
        "Market & industry trend summaries",
        "Conduct smarter, faster market research",
        "Summarize market research & Learning Plan",
    ],
    "AI research summaries for decisions": [
        "Conduct smarter, faster market research",
        "Summarize market research & Learning Plan",
    ],
    "Sales & revenue forecasting": [
        "Forecast revenue & inventory requirements",
        "Build a real-time sales & revenue command center",
    ],
    "Predict demand and stock needs": [
        "Forecast revenue & inventory requirements",
    ],
    # Financial Health & Risk
    "Spot profit leaks and improve margins": [
        "Spot profit leaks & unnecessary spend",
    ],
    "Prevent revenue leakage from contracts (renewals pricing penalties)": [
        "Audit contracts for risk & revenue leakage",
        "Extract key terms from contracts",
    ],
    "Cashflow + spend control dashboard": [
        "Predict cash runway & financial health (30-90 days)",
        "Expense tracking + spend control automation",
    ],
    "Instant finance dashboard (monthly/weekly)": [
        "Predict cash runway & financial health (30-90 days)",
        "Automate budget variance alerts & reporting",
    ],
    "Budget vs actual insights with variance alerts": [
        "Automate budget variance alerts & reporting",
    ],
    "Cashflow forecast (30/60/90 days)": [
        "Predict cash runway & financial health (30-90 days)",
    ],
    "Spend control alerts and trend insights": [
        "Expense tracking + spend control automation",
        "Spot profit leaks & unnecessary spend",
    ],
    "Contract risk snapshot (high-risk clauses obligations renewals)": [
        "Audit contracts for risk & revenue leakage",
        "Extract key terms from contracts",
    ],
    "Supplier risk monitoring": [
        "Supplier risk and exposure tracking",
        "Monitor vendor compliance & cost benchmarks",
    ],
    # Org Efficiency & Hiring
    "Hire faster to support growth": [
        "Streamline employee onboarding & HR support",
        "Find candidates faster (multi\u2011source)",
        "Find candidates faster (multi-source)",
    ],
    "Build a knowledge base from SOPs": [
        "Turn SOPs & policies into an instant Q&A bot",
    ],
    "Internal Q&A bot from SOPs/policies": [
        "Turn SOPs & policies into an instant Q&A bot",
    ],
    "Industry best practice": [
        "Conduct smarter, faster market research",
    ],
    "Delivery/logistics performance reporting": [
        "Monitor operational SLAs & delivery bottlenecks",
        "Track team goals & operational bottlenecks",
    ],
    "Hiring funnel dashboard": [
        "Automate candidate screening & interview insights",
    ],
    "Improve hire quality insights": [
        "Automate candidate screening & interview insights",
        "Resume screening + shortlisting",
    ],
    "Interview feedback summaries": [
        "Automate candidate screening & interview insights",
    ],
    "HR knowledge base from policies": [
        "Turn SOPs & policies into an instant Q&A bot",
    ],
    "Internal Q&A bot for HR queries": [
        "Turn SOPs & policies into an instant Q&A bot",
    ],
    "Organize resumes and candidate notes": [
        "Resume screening + shortlisting",
    ],
    "Brand monitoring & crisis alerts": [
        "Track competitor pricing & promotional strategies",
        "Compare performance vs. competitors & benchmarks",
    ],
    "Search/chat across help docs": [
        "Turn SOPs & policies into an instant Q&A bot",
        "Auto-organize files & chat with business docs",
    ],
    "Internal Q&A bot from SOPs": [
        "Turn SOPs & policies into an instant Q&A bot",
    ],
    "Weekly goals + progress summary": [
        "Prioritize high-impact weekly goals & OKRs",
        "Track team goals & operational bottlenecks",
    ],
    "Chat with your personal documents": [
        "Auto-organize files & chat with business docs",
    ],
    "Auto\u2011tag and organize your files": [
        "Auto\u2011tag and organize documents",
        "Auto-organize files & chat with business docs",
    ],
    # Improve yourself
    "Plan weekly priorities and tasks": [
        "Prioritize high-impact weekly goals & OKRs",
    ],
    "Prep for pitches and presentations": [
        "Craft pitches & presentations",
    ],
    "Personal branding content plan": [
        "Build founder authority & personal brand",
        "Build a personal brand on LinkedIn/Twitter",
    ],
    "Create a learning plan + summaries": [
        "Summarize market research & Learning Plan",
        "Conduct smarter, faster market research",
    ],
    "Contract drafting & review support": [
        "Review contracts & accelerate deal signing",
        "Extract key terms from contracts",
        "Audit contracts for risk & revenue leakage",
    ],
    "Team Sprit Action plan": [
        "Design team culture & alignment roadmaps",
    ],
}


def norm_outcome(label: str) -> str:
    if not label:
        return ""
    k = label.lower().strip()
    if "lead gen" in k:
        return "lead-generation"
    if "sales" in k or "retention" in k:
        return "sales-retention"
    if "strategy" in k or "intelligence" in k:
        return "business-strategy"
    if "save time" in k or "automation" in k:
        return "save-time"
    return ""


def norm_text(text: str) -> str:
    if not text:
        return ""
    t = unicodedata.normalize("NFKD", str(text)).lower().strip()
    # Normalize smart quotes/apostrophes to ASCII equivalents
    t = t.replace("\u2018", "'").replace("\u2019", "'")
    t = t.replace("\u201c", '"').replace("\u201d", '"')
    t = re.sub(r"^[\u2022\u2013\u2014\-\*]+\s*", "", t).strip()
    # Normalize whitespace
    t = re.sub(r"\s+", " ", t)
    return t


def load_taxonomy() -> dict:
    taxonomy = {}
    with open(CATEGORIES_CSV, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            oid = norm_outcome(row["Growth Bucket"].strip())
            if not oid:
                continue
            domain = row["Sub-Category"].strip()
            task = row["Task / Solution"].strip()
            taxonomy.setdefault(oid, {}).setdefault(domain, [])
            if task not in taxonomy[oid][domain]:
                taxonomy[oid][domain].append(task)
    return taxonomy


def load_tools() -> list[dict]:
    wb = openpyxl.load_workbook(str(TOOLS_XLSX), read_only=True)
    ws = wb["All Tools"]
    headers = None
    tools = []
    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if i == 0:
            headers = [str(h).strip() if h else "" for h in row]
            continue
        tools.append(dict(zip(headers, row)))
    wb.close()
    return tools


def build_task_index(tools: list[dict]) -> dict:
    """Build inverted index: normalized_task -> set of tool indices."""
    index = defaultdict(set)
    for idx, tool in enumerate(tools):
        raw = str(tool.get("Tasks", "") or "")
        tool["_oid"] = norm_outcome(str(tool.get("Outcome", "")))
        tool["_persona"] = (
            str(tool.get("Persona", "")).strip() if tool.get("Persona") else ""
        )
        for line in raw.split("\n"):
            line = line.strip()
            if not line:
                continue
            n = norm_text(line)
            if n:
                index[n].add(idx)
    return index


def find_matching_tools(task: str, task_norm: str, index: dict) -> set:
    """Find tool indices matching a Q3 task via exact match + alias expansion."""
    idxs = set(index.get(task_norm, set()))

    # Check aliases: if the original CSV task has mapped xlsx equivalents
    aliases = CSV_TO_XLSX_ALIASES.get(task, [])
    # Also try with smart quotes normalized (CSV may use curly apostrophes)
    if not aliases:
        task_ascii = (
            task.replace("\u2018", "'")
            .replace("\u2019", "'")
            .replace("\u201c", '"')
            .replace("\u201d", '"')
        )
        aliases = CSV_TO_XLSX_ALIASES.get(task_ascii, [])
    for alias in aliases:
        an = norm_text(alias)
        idxs.update(index.get(an, set()))

    # Substring fallback for remaining misses
    if not idxs and len(task_norm) > 12:
        for indexed_norm, tool_idxs in index.items():
            if len(indexed_norm) > 12:
                if task_norm in indexed_norm or indexed_norm in task_norm:
                    idxs.update(tool_idxs)

    return idxs


def format_tool(tool: dict) -> dict:
    r = tool.get("Avg Rating", "")
    rv = tool.get("Total Reviews", "")
    c = tool.get("Composite Score", 0) or 0
    return {
        "name": str(tool.get("Product Name", "")).strip(),
        "description": (str(tool.get("Description", ""))[:300]).strip()
        if tool.get("Description")
        else "",
        "url": str(tool.get("Product URL", "")).strip()
        if tool.get("Product URL")
        else "",
        "source": str(tool.get("Source", "")).strip()
        if tool.get("Source")
        else "",
        "category": str(tool.get("Category", "")).strip()
        if tool.get("Category")
        else "",
        "rating": float(r) if r else None,
        "total_reviews": int(rv) if rv else None,
        "composite_score": round(float(c), 4) if c else 0,
        "review_summary": (str(tool.get("Review Summary", ""))[:300]).strip()
        if tool.get("Review Summary")
        else "",
        "key_pros": str(tool.get("Key Pros", "")).strip()
        if tool.get("Key Pros")
        else "",
        "key_cons": str(tool.get("Key Cons", "")).strip()
        if tool.get("Key Cons")
        else "",
        "best_use_case": (str(tool.get("Best Use Case", ""))[:300]).strip()
        if tool.get("Best Use Case")
        else "",
        "icon_url": str(tool.get("Icon URL", "")).strip()
        if tool.get("Icon URL")
        else "",
        "persona": tool.get("_persona", ""),
    }


def main():
    print("Loading taxonomy...")
    taxonomy = load_taxonomy()
    total_tasks = sum(
        len(tasks) for domains in taxonomy.values() for tasks in domains.values()
    )
    print(f"  {len(taxonomy)} outcomes, {total_tasks} total Q3 tasks")

    print("Loading tools...")
    tools = load_tools()
    print(f"  {len(tools)} tools loaded")

    print("Building task index...")
    index = build_task_index(tools)
    print(f"  {len(index)} unique task strings indexed")

    print("Mapping tools to Q1→Q2→Q3 paths...")
    result = {}
    total = matched = empty = 0

    for oid, domains in taxonomy.items():
        result[oid] = {}
        for domain, tasks in domains.items():
            result[oid][domain] = {}
            for task in tasks:
                total += 1
                tn = norm_text(task)

                # Find matching tools (exact + alias + substring fallback)
                idxs = find_matching_tools(task, tn, index)

                # Score and rank
                scored = []
                for idx in idxs:
                    t = tools[idx]
                    cs = float(t.get("Composite Score", 0) or 0)
                    # Outcome match bonus
                    ob = 2.0 if t["_oid"] == oid else 0.0
                    # Persona/domain match bonus
                    tp = t["_persona"].lower()
                    dl = domain.lower()
                    if tp == dl:
                        pb = 1.5
                    elif dl in tp or tp in dl:
                        pb = 0.75
                    else:
                        pb = 0.0
                    scored.append((cs + ob + pb, cs, idx))

                scored.sort(key=lambda x: (x[0], x[1]), reverse=True)

                # Deduplicate by name, top 10
                seen = set()
                top = []
                for _, _, idx in scored:
                    t = tools[idx]
                    nm = str(t.get("Product Name", "")).strip().lower()
                    if nm in seen:
                        continue
                    seen.add(nm)
                    top.append(format_tool(t))
                    if len(top) >= 10:
                        break

                result[oid][domain][task] = top
                if top:
                    matched += 1
                else:
                    empty += 1

    print(f"\nResults:")
    print(f"  Total Q1→Q2→Q3 paths: {total}")
    print(f"  Paths with tools:     {matched}")
    print(f"  Paths without tools:  {empty}")

    # Write JSON
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    sz = os.path.getsize(OUTPUT) / (1024 * 1024)
    print(f"\nOutput: {OUTPUT} ({sz:.2f} MB)")

    # Show empty paths
    if empty > 0:
        print(f"\nEmpty paths:")
        for oid2, domains2 in result.items():
            for dom2, tasks2 in domains2.items():
                for tn2, tl2 in tasks2.items():
                    if not tl2:
                        print(f"  {oid2} > {dom2} > {tn2}")

    # Sample output
    print("\n=== Sample ===")
    for oid2 in list(result.keys())[:4]:
        for dom2 in list(result[oid2].keys())[:1]:
            for tn2, tl2 in list(result[oid2][dom2].items())[:2]:
                print(f"{oid2} > {dom2} > {tn2}: {len(tl2)} tools")
                for t2 in tl2[:3]:
                    print(
                        f"  - {t2['name']} (cs={t2['composite_score']}, r={t2['rating']})"
                    )


if __name__ == "__main__":
    main()
