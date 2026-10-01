"""
daily_planner.py
================================================================================
Intelligent Daily Cadence Planner for Demoly.dev X (Twitter) Automation.

Orchestrates 3 distinct posts per day:
1. A Single Tweet (text-only)
2. A Thread (multi-tweet deep dive, text-only)
3. A Post with Photo/Video (authentic demo media attached)

Strategy:
- First evaluates real-time Twitter trending hashtags and tech discussions.
- Determines which format is best suited to trend-jack or address the top trend.
- Dynamically selects the most suitable topics/sources (Trend, FAQ, Topic Bank,
  or hybrid) for that day across the 3 formats without rigid formula constraints.
================================================================================
"""

import json
from typing import Optional, List
from pydantic import BaseModel, Field

from src.config import (
    TOPICS_BANK_PATH,
    DEMOLY_FAQ_PATH,
    PUBLISHED_CSV_PATH,
    AccountConfig,
)
from src.gemini_client import GeminiClient
from src.trend_fetcher import (
    get_realtime_trending_context,
    get_realtime_trending_hashtags,
)
from src.media_manager import (
    load_media_catalog,
    format_media_catalog_for_prompt,
    rotate_or_validate_media,
    get_available_media_for_account,
)
from src.content_generator import (
    load_style_guide,
    load_recent_published_posts,
    load_topic_inspiration,
)


class PostPlanItem(BaseModel):
    """Execution plan for a single post in the daily trio."""
    format: str = Field(description="Must be 'single' (text-only tweet), 'thread' (text-only thread), or 'media' (tweet/thread with photo/video)")
    post_type: str = Field(description="Content structure: 'single' or 'thread'")
    focus_topic: str = Field(description="The primary angle, problem statement, or concept for this post")
    source_rationale: str = Field(description="Strategic explanation of why this topic and source were chosen for today")
    trend_connection: Optional[str] = Field(default=None, description="Specific trending topic or hashtag to reference/trend-jack, if relevant")
    preferred_media: Optional[str] = Field(default=None, description="Filename from available media catalog if format=='media' and generate_image is False, else null")
    generate_image: bool = Field(default=False, description="If True, Gemini will generate a custom AI image for this post instead of using a catalog asset. Set True when the post is trend-based or when no catalog asset closely matches the topic.")


class DailyCadencePlan(BaseModel):
    """Overall strategic plan for today's 3-post cadence."""
    trend_analysis: str = Field(description="Evaluation of today's live trends and why formats/topics were allocated this way")
    items: List[PostPlanItem] = Field(description="Exactly 3 post items: 1 single tweet, 1 thread, 1 media post")


PLANNER_SYSTEM_PROMPT = """
You are the Head of Growth and Technical Social Strategist for Demoly (https://demoly.dev).
Demoly is an AI-powered browser screen recorder, client handover platform, and visual bug reporting tool built specifically for tech agencies, web development studios, and QA teams.
Demoly captures live browser interactions alongside video, enabling AI visual search on silent videos, element-level privacy masking, public interactive AI links, and MCP server integrations for Cursor/Antigravity/Claude Code.

Your task is to craft today's 3-POST CONTENT PLAN tailored specifically to the assigned target account:
1. One Single Tweet (strictly text-only, punchy insight, question, or counter-intuitive take)
2. One Thread (strictly text-only, multi-tweet deep dive, story, or framework)
3. One Post with Photo/Video (showcases authentic product media with matching copy)

ACCOUNT PERSONA SPECIALIZATION RULES:
1. IF TARGET ACCOUNT IS 'Demoly Official' (@Demolyy4ls):
   - Focus on Demoly's authentic origin story at agency Creative Upaay (delivering 85+ client platforms).
   - The 35-60 walkthrough video bottleneck for an enterprise law firm client where clients refused to watch 10-min videos for a 10-sec button and booked repeat calls (2-4 hrs/week lost per dev).
   - How Demoly beats Loom (indexing visual UI actions vs spoken audio only) and Google Drive (100MB streaming block).
   - Turning passive videos into active AI assistants that talk back, public interactive AI links, and company mission.
   - STRICT RULE: DO NOT use the word "DOM" at all! Use natural, conversational language.
   - DO NOT tag @Demolyy4ls (official brand account).

2. IF TARGET ACCOUNT IS 'Tech Lead / Systems Engineer' (Manish @ManishBulchand9):
   - Focus on browser internals: visual event indexing vs lossy pixel video OCR / transcripts.
   - Model Context Protocol (MCP) server integration for Cursor, Claude Code, and Antigravity (feeding visual telemetry, console logs, and network calls directly to AI agents).
   - Element-level privacy masking, deterministic AI visual search on silent videos, and developer tooling efficiency.
   - STRICT RULE: Limit the word "DOM" to at most ONCE per post/thread.
   - MANDATORY: Must naturally tag official account @Demolyy4ls.

3. IF TARGET ACCOUNT IS 'Agency Ops / SaaS Strategist' (Sourabh @scalebysourabh):
   - Focus on client handover bottlenecks, eliminating unpaid post-launch scope creep, and saving 2 to 4 billable hours every week per team member.
   - Replacing 30-minute Google Meet walkthroughs with interactive videos that answer questions autonomously.
   - Killing 40-page software documentation manuals that no client reads, accelerating invoice sign-offs, and protecting agency gross margins.
   - STRICT RULE: DO NOT use the word "DOM" at all!
   - MANDATORY: Must naturally tag official account @Demolyy4ls.

PLANNING RULES & STRATEGY:
1. 🔥 VIRAL HOOK TYPES — PICK ONE PER POST, NEVER REPEAT ACROSS THE 3 POSTS:
   Each post MUST use a different hook type:
   - Hook A: CAREER LEVERAGE — "Do this before your next client handover and your manager will ask how you leveled up so fast." / "If you do this one thing in your next delivery, your boss will give you a promotion."
   - Hook B: MONEY SAVED / ROI — "I saved our agency $8,000 last year by cutting one specific meeting from our workflow." / "We added $12K profit margin by fixing one habit."
   - Hook C: POWERFUL QUOTE OR CONFESSION — A short punchy insight or first-person confession that hits emotionally. Lowercase, raw, real. "we almost lost a $40K client because they couldn't find the logout button. here is what we changed."
   - Hook D: RELATABLE NIGHTMARE — Paint a vivid, painful scene the reader has lived. "It's 11 PM. A client Slacks: where is the billing settings again?"
   - Hook E: CONTRARIAN / HOT TAKE — "Unpopular opinion: If your client needs a call to understand your product, you failed at delivery."
   - Hook F: CLICKBAIT CLIFFHANGER — "The one tool that saved our agency 4 hours a week. It's embarrassingly simple."
   NEVER plan two posts with the same hook type in one day.
   NEVER use boring openers like "Most AI tools are...", "Recording a 10-minute video...", "Delivering an enterprise build..."

2. DYNAMIC SOURCE SELECTION & VARIETY:
   - Draw from Live Trends, Demoly FAQ capabilities, and Topic Bank angles.
   - Ensure all 3 posts explore COMPLETELY DIFFERENT angles, emotions, and content types.

3. GUARANTEED FORMAT TRIO:
   Across the 3 items in "items":
   - Exactly ONE item MUST have format="single", post_type="single", preferred_media=null, generate_image=TRUE.
     → This is the AI-IMAGE post. The single tweet gets a custom Pollinations-AI generated visual every day.
   - Exactly ONE item MUST have format="thread", post_type="thread", preferred_media=null, generate_image=false.
   - Exactly ONE item MUST have format="media", post_type="single", generate_image=false.

4. 📸 MEDIA ASSET ROTATION (FOR THE MEDIA POST):
   - NEVER pick any asset from "RECENTLY USED MEDIA ON THIS ACCOUNT"!
   - Pick a FRESH, UNUSED catalog asset. Set preferred_media=<exact filename>.

5. STRICT DEDUPLICATION:
   - Review RECENTLY PUBLISHED POSTS. NEVER repeat angles, hooks, or themes on this account or across accounts.
   - BANNED KEYWORDS in any plan focus_topic: "silent killer", "profit leak", "every single week", "cluttered Google Drive", "stop billing and start answering".

OUTPUT FORMAT:
Return strictly valid JSON matching the DailyCadencePlan schema.
"""


def plan_daily_cadence(
    gemini_client: Optional[GeminiClient] = None,
    account: Optional[AccountConfig] = None,
    batch_excluded_topics: Optional[List[str]] = None,
    batch_excluded_media: Optional[List[str]] = None,
) -> DailyCadencePlan:
    """
    Analyzes live trends, available assets, and recent posts to construct
    an optimized 3-post daily cadence plan.
    Supports multi-account personas and batch-level topic and media deduplication.
    """
    acct_label = f" for account '{account.name}'" if account else ""
    print(f"\n[Daily Planner] Analyzing live trends, assets, and topic bank{acct_label}...")
    realtime_trends = get_realtime_trending_context()
    trending_hashtags = get_realtime_trending_hashtags()
    recent_posts = load_recent_published_posts(limit=30, current_account_name=account.name if account else None)
    topic_inspiration = load_topic_inspiration(limit=8, persona_name=account.name if account else None)
    available_media = format_media_catalog_for_prompt(
        account_name=account.name if account else None,
        batch_excluded_media=batch_excluded_media,
    )

    account_prompt_section = ""
    if account:
        account_prompt_section = f"""
TARGET ACCOUNT PROFILE:
- Account Name/Handle: {account.name}
- Unique Persona & Voice: {account.persona or 'Tech founder and software builder'}
- Primary Audience: {account.target_audience or 'Tech builders and founders'}
RULE: Ensure today's 3 posts are tailored specifically for this account's unique persona, themes, and audience.
"""

    dedup_prompt_section = ""
    if batch_excluded_topics:
        excluded_list_str = "\n".join(f"- {t}" for t in batch_excluded_topics)
        dedup_prompt_section = f"""
STRICT CROSS-ACCOUNT DEDUPLICATION RULE:
The following topics have ALREADY been assigned to other accounts today:
{excluded_list_str}
You MUST pick completely DIFFERENT topics, trends, and angles so that this account has 100% unique, non-overlapping content!
"""

    user_prompt = f"""
LIVE REAL-TIME TECH TRENDS TODAY:
{realtime_trends}

LIVE TWITTER TRENDING HASHTAGS TODAY:
{trending_hashtags}

AVAILABLE AUTHENTIC PRODUCT MEDIA ASSETS:
{available_media}

RECENTLY PUBLISHED POSTS (DO NOT REPEAT):
{recent_posts}

TOPIC BANK CANDIDATES FOR INSPIRATION:
{topic_inspiration}
{account_prompt_section}
{dedup_prompt_section}
Create today's 3-post strategy plan now according to the planning rules.
"""

    client = gemini_client or GeminiClient()

    # Use Gemini structured outputs with DailyCadencePlan
    response = client._get_client().models.generate_content(
        model=client.model_name,
        contents=[
            {"role": "user", "parts": [{"text": PLANNER_SYSTEM_PROMPT + "\n\n" + user_prompt}]}
        ],
        config={
            "response_mime_type": "application/json",
            "response_schema": DailyCadencePlan,
            "temperature": 0.5,
        },
    )

    raw_text = response.text
    parsed_json = json.loads(raw_text)
    plan = DailyCadencePlan(**parsed_json)

    # Sanity verification on format trio:
    formats = [item.format for item in plan.items]
    if "single" not in formats or "thread" not in formats or "media" not in formats:
        # Normalize if needed
        print("[Daily Planner] Note: Re-normalizing formats to guarantee Single, Thread, and Media trio.")
        plan.items[0].format = "single"
        plan.items[0].post_type = "single"
        plan.items[0].preferred_media = None
        plan.items[0].generate_image = True  # Always AI-generate an image for the single post

        plan.items[1].format = "thread"
        plan.items[1].post_type = "thread"
        plan.items[1].preferred_media = None
        plan.items[1].generate_image = False

        plan.items[2].format = "media"
        if not plan.items[2].preferred_media and not plan.items[2].generate_image:
            avail = get_available_media_for_account(account_name=account.name if account else None, batch_excluded=batch_excluded_media)
            if avail:
                plan.items[2].preferred_media = avail[0].get("filename")

    # Ensure media item has either validated preferred_media or generate_image=True
    for item in plan.items:
        if item.format == "media":
            if item.preferred_media and not item.generate_image:
                item.preferred_media = rotate_or_validate_media(
                    item.preferred_media,
                    account_name=account.name if account else None,
                    batch_excluded=batch_excluded_media,
                )
            elif not item.preferred_media and not item.generate_image:
                avail = get_available_media_for_account(account_name=account.name if account else None, batch_excluded=batch_excluded_media)
                if avail:
                    item.preferred_media = avail[0].get("filename")
                else:
                    item.generate_image = True

    print(f"[Daily Planner] Successfully planned 3 posts.")
    print(f"[Daily Planner Strategy]: {plan.trend_analysis}")
    for idx, it in enumerate(plan.items, 1):
        if it.format == "media":
            media_mode = "AI-GENERATED" if it.generate_image else f"CATALOG: {it.preferred_media or 'None'}"
        else:
            media_mode = "text-only"
        print(f"  Post #{idx} [{it.format.upper()}]: {it.focus_topic[:70]}... | Image: {media_mode}")

    return plan


if __name__ == "__main__":
    print("\n--- Testing Daily Planner ---")
    daily_plan = plan_daily_cadence()
    print("\nGenerated Plan Details:")
    print(json.dumps(daily_plan.model_dump(), indent=2))
