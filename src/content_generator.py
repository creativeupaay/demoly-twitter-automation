"""
content_generator.py
================================================================================
Generates original Demoly.dev X posts or threads based on the style-guide.md
using Gemini structured JSON outputs.
================================================================================
"""

import random
import re
from typing import Optional, Any, List
from pathlib import Path

import csv
import json
from src.config import (
    STYLE_GUIDE_PATH,
    GENERATION_PROMPT_PATH,
    DEMOLY_FAQ_PATH,
    PUBLISHED_CSV_PATH,
    TOPICS_BANK_PATH,
    AccountConfig,
)
from src.gemini_client import GeminiClient, GeneratedPostModel
from src.trend_fetcher import (
    get_realtime_trending_context,
    get_realtime_trending_hashtags,
)
from src.media_manager import format_media_catalog_for_prompt, resolve_media_url
from src.image_generator import generate_image_for_post

# Maximum character limit on X (standard)
X_CHAR_LIMIT = 280


def load_style_guide(path: Optional[Path] = None) -> str:
    """Reads the style-guide.md file."""
    target_path = path or STYLE_GUIDE_PATH
    if not target_path.exists():
        raise FileNotFoundError(
            f"\n[STYLE GUIDE MISSING] Could not find style guide at: {target_path}\n"
            f"Please run the research analyzer first or ensure style-guide.md is present."
        )
    content = target_path.read_text(encoding="utf-8").strip()
    if not content:
        raise ValueError("[STYLE GUIDE EMPTY] style-guide.md exists but is empty.")
    return content


def load_knowledge_base(path: Optional[Path] = None) -> str:
    """Reads the Demoly FAQ & Knowledge Base file (data/demoly_faq.md)."""
    target_path = path or DEMOLY_FAQ_PATH
    if not target_path.exists():
        return ""
    return target_path.read_text(encoding="utf-8").strip()


def load_recent_published_posts(limit: int = 30, current_account_name: Optional[str] = None) -> str:
    """
    Reads the last N posts from published_posts.csv to prevent repetition.
    Differentiates between posts made by THIS account and OTHER accounts.
    """
    if not PUBLISHED_CSV_PATH.exists():
        return "None yet (this is the first post)."
    try:
        with open(PUBLISHED_CSV_PATH, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = [r for r in reader if r.get("Content")]
        if not rows:
            return "None yet (this is the first post)."

        recent = rows[-limit:]
        this_account_posts = []
        other_account_posts = []

        for r in recent:
            acct = r.get("Account", "Default").strip()
            text_snippet = r.get("Content", "").replace(" || ", " ")[:180].strip()
            post_type = r.get("Post Type", "post")
            entry = f"[{acct} | {post_type}]: \"{text_snippet}...\""
            if current_account_name and acct.lower() == current_account_name.lower():
                this_account_posts.append(entry)
            else:
                other_account_posts.append(entry)

        sections = []
        if this_account_posts:
            sections.append(
                f"=== POSTS PREVIOUSLY PUBLISHED BY THIS ACCOUNT ({current_account_name}) ===\n"
                f"(STRICT RULE: Do not reuse these exact angles, hooks, or phrasing!)\n"
                + "\n".join(f"{i}. {p}" for i, p in enumerate(this_account_posts, 1))
            )
        if other_account_posts:
            heading = f"=== RECENT POSTS PUBLISHED BY OTHER ACCOUNTS ===" if current_account_name else "=== RECENTLY PUBLISHED POSTS (ALL ACCOUNTS) ==="
            sections.append(
                f"{heading}\n(STRICT RULE: Do not duplicate these topics across accounts!)\n"
                + "\n".join(f"{i}. {p}" for i, p in enumerate(other_account_posts, 1))
            )

        return "\n\n".join(sections) if sections else "None yet."
    except Exception:
        return "None yet."


def load_topic_inspiration(limit: int = 6, persona_name: Optional[str] = None) -> str:
    """Samples N topics from the 100-topic bank (data/topics_bank.json) tailored to the persona."""
    if not TOPICS_BANK_PATH.exists():
        return ""
    try:
        with open(TOPICS_BANK_PATH, mode="r", encoding="utf-8") as f:
            topics = json.load(f)
        if not topics:
            return ""

        filtered_topics = []
        p_name = (persona_name or "").lower()

        if any(k in p_name for k in ["official", "brand", "demoly"]):
            # Official Demoly account: origin, problem, differentiators, positioning, sharing, vision
            target_keywords = ["origin", "positioning", "differentiators", "sharing", "security", "vision"]
            filtered_topics = [
                t for t in topics
                if any(kw in t.get("category", "").lower() for kw in target_keywords)
            ]
        elif any(k in p_name for k in ["tech", "engineer", "architect", "lead"]):
            # Tech Lead account: DOM architecture, MCP, bug reporting, recording capabilities, masking
            target_keywords = ["architecture", "mcp", "bug reporting", "recording capabilities", "editing", "trending"]
            filtered_topics = [
                t for t in topics
                if any(kw in t.get("category", "").lower() for kw in target_keywords)
            ]
        elif any(k in p_name for k in ["agency", "saas", "strategist", "operations", "client"]):
            # Agency/SaaS account: agency problem, workflows, pricing, admin, roadmap, operations
            target_keywords = ["agency problem", "target personas", "pricing", "roadmap", "operations", "mechanics"]
            filtered_topics = [
                t for t in topics
                if any(kw in t.get("category", "").lower() for kw in target_keywords)
            ]

        pool = filtered_topics if len(filtered_topics) >= limit else topics
        sample_size = min(limit, len(pool))
        chosen = random.sample(pool, sample_size)
        formatted = []
        for t in chosen:
            formatted.append(
                f"- [Topic #{t.get('id', '?')} | {t.get('category', t.get('pillar', 'General'))}]: {t.get('topic', '')}\n"
                f"  Angle: {t.get('angle', '')}\n"
                f"  Hook Idea: \"{t.get('hook_seed', '')}\""
            )
        return "\n".join(formatted)
    except Exception:
        return ""


def split_long_post(text: str, max_len: int = 280) -> list[str]:
    """Splits a post into multiple items strictly <= max_len without cutting mid-sentence or mid-word."""
    if len(text) <= max_len:
        return [text]

    paragraphs = text.split("\n\n")
    chunks = []
    current = ""
    for p in paragraphs:
        p = p.strip()
        if not p:
            continue
        if len(p) > max_len:
            sentences = re.split(r"(?<=[.!?])\s+", p)
            for s in sentences:
                s = s.strip()
                if not s:
                    continue
                if len(s) > max_len:
                    words = s.split(" ")
                    for w in words:
                        if not current:
                            current = w
                        elif len(current) + 1 + len(w) <= max_len:
                            current += " " + w
                        else:
                            chunks.append(current)
                            current = w
                else:
                    if not current:
                        current = s
                    elif len(current) + 1 + len(s) <= max_len:
                        current += " " + s
                    else:
                        chunks.append(current)
                        current = s
        else:
            if not current:
                current = p
            elif len(current) + 2 + len(p) <= max_len:
                current += "\n\n" + p
            else:
                chunks.append(current)
                current = p

    if current:
        chunks.append(current)

    return chunks


def validate_generated_content(content: GeneratedPostModel) -> GeneratedPostModel:
    """
    Validates structural rules on the generated content.
    Ensures every post adheres strictly to X's 280-char limit by automatically
    splitting longer paragraphs into multi-tweet sequences.
    """
    if not content.posts:
        raise ValueError("[GENERATION ERROR] Gemini returned an empty list of posts.")

    clean_posts = []
    for idx, post in enumerate(content.posts, 1):
        text = post.strip()
        if not text:
            continue

        # Sanitize: strip out any forbidden "Breakdown 👇", "Breakdown:", or pointing-down emojis
        text = re.sub(r"\s*(?:Breakdown|breakdown)?\s*[👇⬇]\s*$", "", text).strip()
        text = re.sub(r"\s+(?:Breakdown|breakdown)\s*[:\.]?\s*$", ".", text).strip()
        text = text.replace("👇", "").replace("🧵", "").strip()

        # For single posts or posts with media attached, prioritize keeping it as a single tweet <= 280 chars:
        if (content.type == "single" or content.media_filename) and len(text) > 280:
            # Check if trailing hashtags caused the overflow
            tags_match = re.search(r"\n\n(#[A-Za-z0-9_ ]+)$", text)
            if tags_match:
                base_text = text[:tags_match.start()].strip()
                tag_list = tags_match.group(1).split()
                fitted = False
                for t in tag_list:
                    if len(base_text) + len(t) + 2 <= 280:
                        text = f"{base_text}\n\n{t}"
                        fitted = True
                        break
                if not fitted and len(base_text) <= 280:
                    text = base_text

        # If post exceeds 280, safely split across tweets so Buffer / Twitter never rejects it
        if len(text) > 280:
            split_items = split_long_post(text, max_len=280)
            if content.type == "single" and len(split_items) > 1:
                content.type = "thread"
            clean_posts.extend(split_items)
        else:
            clean_posts.append(text)

    # Ensure at least 1-2 trending hashtags exist on the final tweet/post if none were generated
    has_hashtags = any("#" in p for p in clean_posts)
    if not has_hashtags and clean_posts:
        fallback_tags = "#buildinpublic #AI"
        last_post = clean_posts[-1]
        if len(last_post) + len(fallback_tags) + 2 <= 280:
            clean_posts[-1] = f"{last_post}\n\n{fallback_tags}"
        elif len(last_post) + 5 <= 280:
            clean_posts[-1] = f"{last_post}\n\n#AI"

    content.posts = clean_posts
    return content


def generate_post(
    content_type_preference: Optional[str] = None,
    gemini_client: Optional[GeminiClient] = None,
    preferred_media_filename: Optional[str] = None,
    allow_media: Optional[bool] = None,
    planned_focus_topic: Optional[str] = None,
    planned_trend_connection: Optional[str] = None,
    planned_rationale: Optional[str] = None,
    cached_trends: Optional[str] = None,
    cached_hashtags: Optional[str] = None,
    account: Optional[AccountConfig] = None,
) -> GeneratedPostModel:
    """
    Reads the style guide and generates either a single post or a thread.

    Parameters:
        content_type_preference: 'single', 'thread', or None (random choice)
        gemini_client: Optional GeminiClient instance
        preferred_media_filename: Optional filename of video or image to force attach
        allow_media: True to force media, False for text-only, None for balanced 25% cadence
        planned_focus_topic: Explicit topic angle planned for this post
        planned_trend_connection: Trending topic/hashtag connection
        planned_rationale: Strategic context for why this post was chosen
        cached_trends: Pre-fetched tech trends context to avoid duplicate network calls
        cached_hashtags: Pre-fetched trending hashtags to avoid duplicate network calls
        account: Target AccountConfig containing persona, voice, and audience details
    """
def extract_hook_words(text: str) -> set:
    """Extracts significant lowercase words from the first line (hook) of a post."""
    first_line = text.split("\n")[0].lower()
    words = re.findall(r"\b[a-z]{3,}\b", first_line)
    stopwords = {"this", "that", "with", "from", "your", "what", "when", "here", "they", "have", "more", "most", "will", "about", "there", "their", "where"}
    return {w for w in words if w not in stopwords}


def is_duplicate_of_recent(first_tweet: str, past_posts: List[str], threshold: float = 0.60) -> bool:
    """Checks whether the first tweet's hook significantly overlaps with recent published posts."""
    new_words = extract_hook_words(first_tweet)
    if len(new_words) < 3:
        return False
    for past in past_posts:
        past_words = extract_hook_words(past)
        if len(past_words) < 3:
            continue
        intersection = new_words & past_words
        union = new_words | past_words
        if union and (len(intersection) / len(union)) >= threshold:
            return True
    return False


def generate_post(
    content_type_preference: Optional[str] = None,
    gemini_client: Optional[GeminiClient] = None,
    preferred_media_filename: Optional[str] = None,
    allow_media: Optional[bool] = None,
    planned_focus_topic: Optional[str] = None,
    planned_trend_connection: Optional[str] = None,
    planned_rationale: Optional[str] = None,
    cached_trends: Optional[str] = None,
    cached_hashtags: Optional[str] = None,
    account: Optional[AccountConfig] = None,
) -> GeneratedPostModel:
    """
    Reads the style guide and generates either a single post or a thread.
    Supports Demoly Official, Tech Lead, and Agency/SaaS account personas
    with strict deduplication against recent history.
    """
    style_guide = load_style_guide()
    knowledge_base = load_knowledge_base()
    recent_posts = load_recent_published_posts(limit=30, current_account_name=account.name if account else None)
    topic_inspiration = load_topic_inspiration(limit=6, persona_name=account.name if account else None)
    realtime_trends = cached_trends or get_realtime_trending_context()
    trending_hashtags = cached_hashtags or get_realtime_trending_hashtags()

    # Determine whether this run should consider media:
    # If user passed --media: always True
    # If user passed --no-media: always False
    # If not specified: Healthy cadence -> 25% media, 75% text-only
    if preferred_media_filename:
        use_media = True
    elif allow_media is not None:
        use_media = allow_media
    else:
        use_media = random.random() < 0.25  # 1 in 4 posts

    if use_media:
        available_media = format_media_catalog_for_prompt()
    else:
        available_media = "None for this run. This post/thread is strictly TEXT-ONLY. You MUST set 'media_filename': null."

    if not GENERATION_PROMPT_PATH.exists():
        raise FileNotFoundError(f"Generation prompt template not found at {GENERATION_PROMPT_PATH}")

    prompt_template = GENERATION_PROMPT_PATH.read_text(encoding="utf-8")

    # Follow Style Guide: 80% threads, 20% single tweets
    if not content_type_preference:
        content_type_preference = random.choices(["thread", "single"], weights=[0.8, 0.2], k=1)[0]

    formatted_prompt = prompt_template.format(
        style_guide=style_guide,
        knowledge_base=knowledge_base,
        recent_posts=recent_posts,
        topic_inspiration=topic_inspiration,
        realtime_trends=realtime_trends,
        trending_hashtags=trending_hashtags,
        available_media=available_media,
        content_type_preference=content_type_preference,
    )

    # Inject account persona and tone instructions if specified
    if account:
        p_name = account.name.lower()
        role_specialization = ""
        if any(k in p_name for k in ["official", "brand", "demoly"]):
            role_specialization = (
                "\nSPECIALIZED ROLE (OFFICIAL DEMOLY BRAND VOICE):\n"
                "- Speak as Demoly's official voice, product team, and company mission.\n"
                "- Tell Demoly's authentic backstory: how Creative Pie agency (delivering 85+ client platforms) ran into a massive 35-60 walkthrough video bottleneck for an enterprise law firm client.\n"
                "- Explain why we created Demoly: because clients refuse to watch 10-minute videos for a 10-second button and kept asking for repeat Google Meet calls (2-4 hrs/week lost per developer).\n"
                "- Highlight why Demoly is fundamentally better: Loom's audio-transcript-only search is blind to silent clicks and UI actions; Google Drive fails to stream videos >100MB in-browser; Demoly captures the live browser DOM tree and lets clients talk to the video via interactive public links.\n"
                "- Share company philosophy, mission, product announcements, and customer transformations."
            )
        elif any(k in p_name for k in ["tech", "engineer", "architect", "lead"]):
            role_specialization = (
                "\nSPECIALIZED ROLE (TECH LEAD / DEEP SYSTEMS & AI ENGINEER):\n"
                "- Speak as a Senior Full-Stack Engineer / AI Systems Architect talking to peers (developers, AI engineers, CTOs).\n"
                "- Dive into technical internals: browser DOM tree indexing vs lossy pixel video OCR / transcripts.\n"
                "- Focus on Model Context Protocol (MCP) server integration for Cursor, Claude Code, and Antigravity: feeding timestamped DOM snapshots, console errors, and network logs directly to AI agents.\n"
                "- Focus on element-level DOM privacy masking (hiding Stripe keys / PII in the DOM layer non-destructively) and deterministic AI visual search on silent videos.\n"
                "- Focus on developer velocity, reproducible visual QA bug reports, and modern frontend tooling."
            )
        elif any(k in p_name for k in ["agency", "saas", "strategist", "operations", "client"]):
            role_specialization = (
                "\nSPECIALIZED ROLE (AGENCY OPERATIONS & SAAS STRATEGIST):\n"
                "- Speak as an agency operations lead and client success strategist talking to agency founders, dev shops, and SaaS creators.\n"
                "- Focus on client handover bottlenecks, eliminating unpaid post-launch scope creep, and saving 2 to 4 billable hours every week per team member.\n"
                "- Focus on replacing 30-minute Google Meet walkthroughs with interactive videos that answer questions autonomously, accelerating invoice sign-offs, and protecting agency profit margins.\n"
                "- Focus on the death of 40-page software documentation manuals that no client ever reads."
            )

        formatted_prompt += (
            f"\n\nACCOUNT VOICE & PERSONA INSTRUCTIONS:\n"
            f"- Account: {account.name}\n"
            f"- Persona / Tone: {account.persona or 'Tech builder & founder'}\n"
            f"- Target Audience: {account.target_audience or 'Builders, developers, and founders'}"
            f"{role_specialization}\n"
            f"Make sure your phrasing, hook style, and vocabulary reflect this unique persona."
        )

    # Inject planned strategic topic if specified by the daily planner
    if planned_focus_topic:
        formatted_prompt += f"\n\nTARGETED STRATEGIC OBJECTIVE FOR THIS RUN:\n- Primary Topic / Angle: {planned_focus_topic}"
        if planned_rationale:
            formatted_prompt += f"\n- Strategic Context: {planned_rationale}"
        if planned_trend_connection:
            formatted_prompt += f"\n- Live Trend / Hashtag Context to incorporate: {planned_trend_connection}"
        formatted_prompt += "\nFocus your post tightly around this angle while adhering to all Demoly voice and style rules."

    if preferred_media_filename:
        formatted_prompt += f"\n\nUSER OVERRIDE: You MUST use and reference the authentic media asset '{preferred_media_filename}' for this post. Set media_filename to '{preferred_media_filename}'."

    client = gemini_client or GeminiClient()
    raw_content = client.generate_content(formatted_prompt)

    # Validate output
    validated = validate_generated_content(raw_content)

    # Load recent history for anti-repetition check
    recent_raw_contents = []
    if PUBLISHED_CSV_PATH.exists():
        try:
            with open(PUBLISHED_CSV_PATH, mode="r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                recent_raw_contents = [r.get("Content", "") for r in reader if r.get("Content")][-30:]
        except Exception:
            pass

    # If first tweet overlaps with recent history, request one quick regeneration with explicit dedup warning
    if validated.posts and is_duplicate_of_recent(validated.posts[0], recent_raw_contents, threshold=0.55):
        print(f"[Deduplication] Detected hook similarity with past post. Regenerating with fresh angle...")
        retry_prompt = (
            formatted_prompt
            + f"\n\nSTRICT DEDUPLICATION WARNING: The hook '{validated.posts[0][:70]}...' is too similar to a past post! "
            f"Generate a COMPLETELY NEW, DIFFERENT hook and angle."
        )
        try:
            retry_raw = client.generate_content(retry_prompt)
            validated = validate_generated_content(retry_raw)
        except Exception as retry_err:
            print(f"[Deduplication] Retry warning: {retry_err}, keeping original.")

    # Hard validation: every post MUST mention "Demoly" by name
    all_text = " ".join(validated.posts)
    if "demoly" not in all_text.lower():
        print(f"[Brand Check] Post missing 'Demoly' name. Regenerating with brand enforcement...")
        brand_retry_prompt = (
            formatted_prompt
            + "\n\n⚠️ CRITICAL BRAND RULE VIOLATION: Your previous response did NOT mention 'Demoly' by name anywhere! "
            "This is UNACCEPTABLE. You MUST explicitly name 'Demoly' at least once in the post. "
            "Do NOT write generic advice without attributing the solution to Demoly. "
            "Example fix: Instead of 'Record once. Let AI handle the questions.' write "
            "'Demoly lets you record once and have AI answer client questions from the video instantly.'"
        )
        try:
            brand_retry_raw = client.generate_content(brand_retry_prompt)
            brand_validated = validate_generated_content(brand_retry_raw)
            if "demoly" in " ".join(brand_validated.posts).lower():
                validated = brand_validated
                print(f"[Brand Check] ✅ Regenerated post now includes 'Demoly'.")
            else:
                print(f"[Brand Check] ⚠️ Retry still missing Demoly name. Keeping best version.")
        except Exception as brand_err:
            print(f"[Brand Check] Retry error: {brand_err}, keeping original.")

    # Resolve media URL if media was selected
    if preferred_media_filename:
        validated.media_filename = preferred_media_filename

    if validated.media_filename:
        validated.media_url = resolve_media_url(validated.media_filename)

    return validated


def generate_planned_post(
    plan_item: Any,
    gemini_client: Optional[GeminiClient] = None,
    cached_trends: Optional[str] = None,
    cached_hashtags: Optional[str] = None,
    account: Optional[AccountConfig] = None,
) -> GeneratedPostModel:
    """
    Generates a single post or thread following a PostPlanItem from DailyCadencePlan.
    Supports both catalog-asset media posts and Gemini AI-generated image posts,
    tailored to a specific AccountConfig persona.
    """
    allow_media = True if plan_item.format == "media" else False

    # If generate_image=True, we don't pass preferred_media to the prompt
    # (no catalog asset), but we DO still flag allow_media=True so the prompt
    # is formatted as a media post. After generation, we attach the AI image URL.
    preferred_media_for_prompt = None if getattr(plan_item, "generate_image", False) else plan_item.preferred_media

    result = generate_post(
        content_type_preference=plan_item.post_type,
        gemini_client=gemini_client,
        preferred_media_filename=preferred_media_for_prompt,
        allow_media=allow_media,
        planned_focus_topic=plan_item.focus_topic,
        planned_trend_connection=plan_item.trend_connection,
        planned_rationale=plan_item.source_rationale,
        cached_trends=cached_trends,
        cached_hashtags=cached_hashtags,
        account=account,
    )

    # If this is an AI-generated image post, generate and attach the image now
    if getattr(plan_item, "generate_image", False) and plan_item.format == "media":
        print("[Content Generator] Generating image accurately matching post text...")
        image_url = generate_image_for_post(
            focus_topic=plan_item.focus_topic,
            trend_connection=plan_item.trend_connection,
            post_text=result.posts[0] if result.posts else None,
        )
        if image_url:
            result.media_filename = None  # No catalog filename — it's generated
            result.media_url = image_url
            print(f"[Content Generator] AI image attached: {image_url}")
        else:
            # Fallback: try to pick any catalog asset rather than posting blank
            print("[Content Generator] AI image generation failed. Falling back to catalog asset.")
            from src.media_manager import load_media_catalog
            catalog = load_media_catalog()
            if catalog:
                fallback_file = catalog[0].get("filename")
                result.media_filename = fallback_file
                result.media_url = resolve_media_url(fallback_file)
                print(f"[Content Generator] Fallback catalog asset: {fallback_file}")

    return result


if __name__ == "__main__":
    try:
        res = generate_post()
        print(f"\n[Generated Type]: {res.type}")
        for i, p in enumerate(res.posts, 1):
            print(f"\n--- Post {i} ({len(p)} chars) ---\n{p}")
    except Exception as err:
        print(f"\n[ERROR] {err}")
