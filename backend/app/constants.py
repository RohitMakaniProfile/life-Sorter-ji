DEFAULT_AGENT_ID = "research-orchestrator"
USD_TO_INR = 94.0
MODEL_PRICING_USD_PER_TOKEN: dict[str, tuple[float, float]] = {
    # OpenAI
    "gpt-4o-mini": (0.15 / 1_000_000, 0.60 / 1_000_000),
    "gpt-4o": (5.0 / 1_000_000, 15.0 / 1_000_000),
    "gpt-4.1": (2.0 / 1_000_000, 8.0 / 1_000_000),
    "gpt-4.1-mini": (0.40 / 1_000_000, 1.60 / 1_000_000),
    # Anthropic / Claude (direct + OpenRouter-prefixed)
    "claude-3-5-sonnet-20241022": (3.0 / 1_000_000, 15.0 / 1_000_000),
    "claude-3-7-sonnet-20250219": (3.0 / 1_000_000, 15.0 / 1_000_000),
    "claude-sonnet-4-6": (3.0 / 1_000_000, 15.0 / 1_000_000),   # matches "anthropic/claude-sonnet-4-6"
    "claude-opus-4-6": (15.0 / 1_000_000, 75.0 / 1_000_000),
    # Google Gemini
    "gemini-2.5-flash-lite": (0.075 / 1_000_000, 0.30 / 1_000_000),
    "gemini-2.5-flash": (0.15 / 1_000_000, 0.60 / 1_000_000),
    "gemini-2.5-pro": (1.25 / 1_000_000, 10.0 / 1_000_000),
    # Other
    "z-ai/glm-5": (0.30 / 1_000_000, 1.20 / 1_000_000),
}
DEFAULT_AGENTS = [
    {
        "id": "research-orchestrator",
        "name": "Business Research",
        "emoji": "🕵️",
        "description": "Agentic research using website scrapers, social and sentiment skills",
        "allowed_skill_ids": [
            "business-scan", "scrape-bs4", "scrape-playwright", "scrape-googlebusiness",
            "platform-scout", "web-search", "platform-taxonomy", "classify-links",
            "instagram-sentiment", "youtube-sentiment", "playstore-sentiment",
            "quora-search", "find-platform-handles",
        ],
        "skill_selector_context": "",
        "final_output_formatting_context": "",
    },
    {
        "id": "business_problem_identifier",
        "name": "Business Problem Identifier",
        "emoji": "🎯",
        "description": "Guided onboarding journey to identify your business problem and generate a personalised playbook",
        "allowed_skill_ids": [],
        "skill_selector_context": "",
        "final_output_formatting_context": "",
    },
]
