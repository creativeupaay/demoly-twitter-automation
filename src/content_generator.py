"""
content_generator.py
================================================================================
Generates original Demoly.dev X posts or threads based on the style-guide.md
using Gemini structured JSON outputs.
================================================================================
"""

import random
import re
from typing import Optional, Any, List, Set, Tuple
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
from src.media_manager import (
    format_media_catalog_for_prompt,
    resolve_media_url,
    rotate_or_validate_media,
    get_available_media_for_account,
)
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
    Reads recent posts from published_posts.csv to prevent repetition.
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

        curr_key = (current_account_name or "").lower().split()[0] if current_account_name else ""

        for r in recent:
            acct = r.get("Account", "Default").strip()
            # Clean content snippet
            text_snippet = r.get("Content", "").replace(" || ", " ")[:260].strip()
            post_type = r.get("Post Type", "post")
            entry = f"[{acct} | {post_type}]: \"{text_snippet}...\""

            is_this_account = False
            if current_account_name:
                if acct.lower() == current_account_name.lower():
                    is_this_account = True
                elif curr_key and curr_key in acct.lower():
                    is_this_account = True

            if is_this_account:
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
    except Exception as e:
        print(f"[Warning] Failed to load recent published posts: {e}")
        return "None yet."


def load_topic_inspiration(limit: int = 8, persona_name: Optional[str] = None) -> str:
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
            # Tech Lead account: architecture, mcp, bug reporting, recording capabilities, editing, trending
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


def is_standalone_hashtag_post(text: str) -> bool:
    """Returns True if the post text contains only hashtags, mentions, whitespace, or punctuation."""
    cleaned = re.sub(r"#[A-Za-z0-9_]+", "", text)
    cleaned = re.sub(r"@[A-Za-z0-9_]+", "", cleaned)
    cleaned = re.sub(r"[\s\.,!?:;'\"]+", "", cleaned)
    return len(cleaned) == 0


def split_long_post(text: str, max_len: int = 280) -> list[str]:
    """Splits a post into multiple items strictly <= max_len without cutting mid-sentence, mid-word, or separating hashtags."""
    text = text.strip()
    if len(text) <= max_len:
        return [text]

    # Extract any trailing hashtags so they don't get isolated into their own chunk
    tags_match = re.search(r"(\n*#[A-Za-z0-9_ ]+)$", text)
    trailing_tags = ""
    if tags_match:
        trailing_tags = tags_match.group(1).strip()
        text = text[:tags_match.start()].strip()

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

    # Attach trailing hashtags back to the final chunk if they fit
    if trailing_tags and chunks:
        last_chunk = chunks[-1]
        tag_list = trailing_tags.split()
        fitted = []
        for t in tag_list:
            if len(last_chunk) + len(" ".join(fitted + [t])) + 2 <= max_len:
                fitted.append(t)
        if fitted:
            chunks[-1] = f"{last_chunk}\n\n{' '.join(fitted)}"

    return chunks or [text]


def sanitize_text_and_remove_jargon(text: str, allow_limited_dom: bool = False) -> str:
    """
    Cleans up repetitive technical jargon ("DOM") and fixes company name ("Creative Pie" -> "Creative Upaay").
    - Replaces any mention of Creative Pie with Creative Upaay.
    - If allow_limited_dom is False (Official & Agency accounts), completely eliminates "DOM" jargon.
    - If allow_limited_dom is True (Tech Lead account), allows at most 1 mention of DOM across the text.
    """
    # 1. Company Name Fix
    text = re.sub(r"\bCreative\s+Pie\b", "Creative Upaay", text, flags=re.IGNORECASE)

    # 2. DOM Jargon Cleanup
    if not allow_limited_dom:
        # Strictly remove DOM for non-tech accounts
        text = re.sub(r"\bDocument\s+Object\s+Model\s*(\(DOM\))?\b", "visual browser interactions", text, flags=re.IGNORECASE)
        text = re.sub(r"\bDOM\s+trees?\b", "visual interface structure", text, flags=re.IGNORECASE)
        text = re.sub(r"\bDOM\s+states?\b", "on-screen actions", text, flags=re.IGNORECASE)
        text = re.sub(r"\bDOM\s+layer\b", "interface layer", text, flags=re.IGNORECASE)
        text = re.sub(r"\bthe\s+browser\s+DOM\b", "live browser interactions", text, flags=re.IGNORECASE)
        text = re.sub(r"\bbrowser\s+DOM\b", "on-screen actions", text, flags=re.IGNORECASE)
        text = re.sub(r"\bthe\s+DOM\b", "the visual UI", text, flags=re.IGNORECASE)
        text = re.sub(r"\bDOM\b", "UI", text)
    else:
        # Tech lead: allow max 1 mention of DOM
        dom_matches = list(re.finditer(r"\bDOM\b", text))
        if len(dom_matches) > 1:
            # Replace all occurrences after the first one with "UI elements"
            first_end = dom_matches[0].end()
            head = text[:first_end]
            tail = text[first_end:]
            tail = re.sub(r"\bDOM\s+trees?\b", "UI hierarchy", tail, flags=re.IGNORECASE)
            tail = re.sub(r"\bDOM\s+states?\b", "element states", tail, flags=re.IGNORECASE)
            tail = re.sub(r"\bDOM\b", "UI", tail)
            text = head + tail

    return text


def validate_generated_content(
    content: GeneratedPostModel,
    account: Optional[AccountConfig] = None,
) -> GeneratedPostModel:
    """
    Validates structural rules on the generated content.
    - Sanitizes company name (Creative Upaay).
    - Removes or limits DOM jargon based on account persona.
    - Ensures hashtags are NEVER in their own separate post/tweet.
    - Ensures every post adheres strictly to X's 280-char limit.
    """
    if not content.posts:
        raise ValueError("[GENERATION ERROR] Gemini returned an empty list of posts.")

    is_tech_lead = False
    if account:
        p_name = account.name.lower()
        if any(k in p_name for k in ["tech", "engineer", "architect", "lead"]):
            is_tech_lead = True

    clean_posts = []
    for idx, post in enumerate(content.posts, 1):
        text = post.strip()
        if not text:
            continue

        # Sanitize: company name and jargon
        text = sanitize_text_and_remove_jargon(text, allow_limited_dom=is_tech_lead)

        # Sanitize: replace overused banned cliché phrases with fresh alternatives
        BANNED_PHRASES = [
            (r"\bsilent killer\b", "biggest hidden drain", re.IGNORECASE),
            (r"\bprofit leak\b", "hidden margin drain", re.IGNORECASE),
            (r"\bevery single week\b", "each week", re.IGNORECASE),
            (r"\bstop billing and start answering\b", "switch from building to babysitting", re.IGNORECASE),
            (r"\bcluttered Google Drive folder\b", "messy Drive dump", re.IGNORECASE),
            (r"\bscattering.*?links across.*?channels\b", "dumping links across random channels", re.IGNORECASE | re.DOTALL),
            (r"\bmassive waste of dev time\b", "a complete time sink", re.IGNORECASE),
        ]
        for pattern, replacement, flags in BANNED_PHRASES:
            text = re.sub(pattern, replacement, text, flags=flags)

        # Sanitize: strip out any forbidden "Breakdown 👇", "Breakdown:", or pointing-down emojis
        text = re.sub(r"\s*(?:Breakdown|breakdown)?\s*[👇⬇]\s*$", "", text).strip()
        text = re.sub(r"\s+(?:Breakdown|breakdown)\s*[:\.]?\s*$", ".", text).strip()
        text = text.replace("👇", "").replace("🧵", "").strip()

        # For single posts or posts with media attached, prioritize keeping it as a single tweet <= 280 chars:
        if (content.type == "single" or content.media_filename) and len(text) > 280:
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

    # Pass 2: Merge any standalone hashtag posts back into the preceding tweet so hashtags are NEVER separate
    merged_posts = []
    for p in clean_posts:
        if is_standalone_hashtag_post(p):
            tags = re.findall(r"#[A-Za-z0-9_]+", p)
            if merged_posts and tags:
                prev = merged_posts[-1]
                fitted_tags = []
                for t in tags:
                    if len(prev) + len(" ".join(fitted_tags + [t])) + 2 <= 280:
                        fitted_tags.append(t)
                if fitted_tags:
                    merged_posts[-1] = f"{prev}\n\n{' '.join(fitted_tags)}"
            # Standalone hashtag post is DROPPED, never kept as a separate tweet!
        else:
            merged_posts.append(p)

    if not merged_posts and clean_posts:
        merged_posts = clean_posts

    clean_posts = merged_posts

    # If format was single post, ensure all content remains in a single post
    if content.type == "single" and len(clean_posts) > 1:
        # Check if 2nd post was small and can fit into the 1st
        combined = "\n\n".join(clean_posts)
        if len(combined) <= 280:
            clean_posts = [combined]

    # Ensure at least 1-2 trending hashtags exist on the final tweet/post if none were generated
    has_hashtags = any("#" in p for p in clean_posts)
    if not has_hashtags and clean_posts:
        fallback_tags = "#buildinpublic #AI"
        last_post = clean_posts[-1]
        if len(last_post) + len(fallback_tags) + 2 <= 280:
            clean_posts[-1] = f"{last_post}\n\n{fallback_tags}"
        elif len(last_post) + 5 <= 280:
            clean_posts[-1] = f"{last_post}\n\n#AI"

    # Account-specific Cross-Tagging Rules:
    # 1. Demoly Official (@Demolyy4ls) should never tag @Demolyy4ls
    # 2. Manish (@ManishBulchand9) & Sourabh (@scalebysourabh) MUST tag @Demolyy4ls
    if account:
        p_name = account.name.lower()
        is_official = any(k in p_name for k in ["official", "brand"]) or "demolyy4ls" in p_name
        is_team = any(k in p_name for k in ["tech", "engineer", "architect", "lead", "manish", "agency", "saas", "strategist", "operations", "sourabh"]) and not is_official

        if is_official:
            # Strip accidental @Demolyy4ls self-tags
            clean_posts = [re.sub(r"@Demolyy4ls\b", "Demoly", p, flags=re.IGNORECASE) for p in clean_posts]
        elif is_team:
            # Ensure @Demolyy4ls is tagged in team posts
            has_tag = any("@demolyy4ls" in p.lower() for p in clean_posts)
            if not has_tag and clean_posts:
                replaced = False
                for i, p in enumerate(clean_posts):
                    if re.search(r"\bDemoly\b", p, flags=re.IGNORECASE):
                        candidate = re.sub(r"\bDemoly\b", "@Demolyy4ls", p, count=1, flags=re.IGNORECASE)
                        if len(candidate) <= 280:
                            clean_posts[i] = candidate
                            replaced = True
                            break
                if not replaced:
                    last_p = clean_posts[-1]
                    if len(last_p) + len(" @Demolyy4ls") <= 280:
                        clean_posts[-1] = f"{last_p} @Demolyy4ls"

    if len(clean_posts) == 1:
        content.type = "single"
    content.posts = clean_posts
    return content


def normalize_stem(word: str) -> str:
    """Basic stemmer to match variants like click, clicked, clicking, clicks."""
    w = word.lower().strip()
    if w.endswith("ies") and len(w) > 4:
        return w[:-3] + "y"
    if w.endswith("ing") and len(w) > 5:
        return w[:-3]
    if w.endswith("ed") and len(w) > 4:
        return w[:-2]
    if w.endswith("es") and len(w) > 4:
        return w[:-2]
    if w.endswith("s") and len(w) > 3 and not w.endswith("ss"):
        return w[:-1]
    return w


def extract_normalized_words(text: str) -> Set[str]:
    """Extracts stemmed lowercase words from text, excluding common stopwords."""
    words = re.findall(r"\b[a-z]{3,}\b", text.lower())
    stopwords = {
        "this", "that", "with", "from", "your", "what", "when", "here", "they",
        "have", "more", "most", "will", "about", "there", "their", "where", "which",
        "been", "were", "would", "could", "should", "into", "than", "then", "just",
        "some", "also", "like", "make", "over", "such", "these", "those", "does",
        "every", "after", "before", "while", "being"
    }
    return {normalize_stem(w) for w in words if w not in stopwords}


def extract_ngrams(text: str, n: int = 3) -> Set[str]:
    """Extracts n-word sequences to detect copied phrases."""
    words = re.findall(r"\b[a-z]{3,}\b", text.lower())
    if len(words) < n:
        return set()
    return {" ".join(words[i:i+n]) for i in range(len(words) - n + 1)}


def is_duplicate_of_recent(post_text: str, past_posts: List[str], threshold: float = 0.38) -> Tuple[bool, str]:
    """
    Checks whether a candidate post significantly overlaps with any recent published post:
    1. Hook (first line) similarity with stemming.
    2. Whole post word-level Jaccard similarity.
    3. Multi-word phrase matching (trigrams).
    Returns (is_duplicate: bool, matched_reason: str).
    """
    if not past_posts:
        return False, ""

    first_line = post_text.split("\n")[0].strip()
    new_hook_words = extract_normalized_words(first_line)
    new_full_words = extract_normalized_words(post_text)
    new_trigrams = extract_ngrams(post_text, 3)

    for past in past_posts:
        if not past or len(past) < 20:
            continue

        past_first_line = past.split("\n")[0].strip()
        past_hook_words = extract_normalized_words(past_first_line)

        # 1. Hook overlap check (threshold 0.45)
        if len(new_hook_words) >= 4 and len(past_hook_words) >= 4:
            hook_inter = new_hook_words & past_hook_words
            hook_union = new_hook_words | past_hook_words
            if hook_union and (len(hook_inter) / len(hook_union)) >= 0.45:
                return True, f"Hook similarity {len(hook_inter)/len(hook_union):.2f} with: '{past_first_line[:70]}...'"

        # 2. Full post Jaccard overlap (threshold 0.38)
        past_full_words = extract_normalized_words(past)
        if len(new_full_words) >= 8 and len(past_full_words) >= 8:
            full_inter = new_full_words & past_full_words
            full_union = new_full_words | past_full_words
            sim = len(full_inter) / len(full_union)
            if sim >= threshold:
                return True, f"Content overlap {sim:.2f} with past post: '{past_first_line[:70]}...'"

        # 3. Trigram phrase match (2 or more identical 3-word key phrases)
        if len(new_trigrams) >= 5:
            past_trigrams = extract_ngrams(past, 3)
            shared_phrases = new_trigrams & past_trigrams
            significant_phrases = [
                p for p in shared_phrases
                if not any(tag in p for tag in ["buildinpublic", "webdev", "saas", "tech", "coding", "ai"])
            ]
            if len(significant_phrases) >= 2:
                return True, f"Reused key phrases {significant_phrases[:2]} from: '{past_first_line[:70]}...'"

    return False, ""


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
    topic_inspiration = load_topic_inspiration(limit=8, persona_name=account.name if account else None)
    realtime_trends = cached_trends or get_realtime_trending_context()
    trending_hashtags = cached_hashtags or get_realtime_trending_hashtags()

    # Determine whether this run should consider media:
    if preferred_media_filename:
        use_media = True
    elif allow_media is not None:
        use_media = allow_media
    else:
        use_media = random.random() < 0.25  # 1 in 4 posts

    if use_media:
        available_media = format_media_catalog_for_prompt(
            account_name=account.name if account else None
        )
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
                "- Tell Demoly's authentic backstory: how agency Creative Upaay (delivering 85+ client platforms) ran into a massive 35-60 walkthrough video bottleneck for an enterprise law firm client.\n"
                "- Explain why we created Demoly: because clients refuse to watch 10-minute videos for a 10-second button and kept asking for repeat Google Meet calls (2-4 hrs/week lost per developer).\n"
                "- Highlight why Demoly is fundamentally better: Loom's audio-transcript-only search is blind to silent clicks and UI actions; Google Drive fails to stream videos >100MB in-browser; Demoly indexes visual browser actions and lets clients talk to the video via interactive public links.\n"
                "- Share company philosophy, mission, product announcements, and customer transformations.\n"
                "- STRICT TONE RULE: DO NOT use the word 'DOM' anywhere in this post!\n"
                "- STRICT TAGGING RULE: DO NOT tag @Demolyy4ls (this account is the official Demoly brand itself)."
            )
        elif any(k in p_name for k in ["tech", "engineer", "architect", "lead"]):
            role_specialization = (
                "\nSPECIALIZED ROLE (TECH LEAD / DEEP SYSTEMS & AI ENGINEER - MANISH @ManishBulchand9):\n"
                "- Speak as a Senior Full-Stack Engineer / AI Systems Architect talking to peers (developers, AI engineers, CTOs).\n"
                "- Focus on technical internals: visual telemetry vs lossy pixel video OCR / transcripts.\n"
                "- Focus on Model Context Protocol (MCP) server integration for Cursor, Claude Code, and Antigravity: feeding visual bug steps, console errors, and network logs directly to AI agents.\n"
                "- Focus on element-level privacy masking (hiding Stripe keys / PII in the UI layer non-destructively) and deterministic AI visual search on silent videos.\n"
                "- Focus on developer velocity, reproducible visual QA bug reports, and modern frontend tooling.\n"
                "- STRICT TONE RULE: Use the word 'DOM' at most ONCE across the entire post/thread!\n"
                "- 🤝 MANDATORY TAGGING RULE: You MUST naturally tag Demoly's official account @Demolyy4ls in your post or thread CTA (e.g. 'what we built into @Demolyy4ls', 'shipped this in @Demolyy4ls', 'test it on @Demolyy4ls')."
            )
        elif any(k in p_name for k in ["agency", "saas", "strategist", "operations", "client"]):
            role_specialization = (
                "\nSPECIALIZED ROLE (AGENCY OPERATIONS & SAAS STRATEGIST - SOURABH @scalebysourabh):\n"
                "- Speak as an agency operations lead and client success strategist talking to agency founders, dev shops, and SaaS creators.\n"
                "- Focus on client handover bottlenecks, eliminating unpaid post-launch scope creep, and saving 2 to 4 billable hours every week per team member.\n"
                "- Focus on replacing 30-minute Google Meet walkthroughs with interactive videos that answer questions autonomously, accelerating invoice sign-offs, and protecting agency profit margins.\n"
                "- Focus on the death of 40-page software documentation manuals that no client ever reads.\n"
                "- STRICT TONE RULE: DO NOT use the word 'DOM' anywhere in this post!\n"
                "- 🤝 MANDATORY TAGGING RULE: You MUST naturally tag Demoly's official account @Demolyy4ls in your post or thread CTA (e.g. 'how we solved this at @Demolyy4ls', 'we use @Demolyy4ls for every client handover', 'try @Demolyy4ls')."
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

    # Validate output with account awareness (DOM and Creative Upaay rules)
    validated = validate_generated_content(raw_content, account=account)

    # Load recent history for anti-repetition check
    recent_raw_contents = []
    if PUBLISHED_CSV_PATH.exists():
        try:
            with open(PUBLISHED_CSV_PATH, mode="r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                recent_raw_contents = [r.get("Content", "") for r in reader if r.get("Content")][-40:]
        except Exception:
            pass

    # Deep deduplication check across hook, content, and key phrases
    full_generated_text = " || ".join(validated.posts)
    is_dup, dup_reason = is_duplicate_of_recent(full_generated_text, recent_raw_contents, threshold=0.38)
    if is_dup:
        print(f"[Deduplication] Detected repetition ({dup_reason}). Regenerating with fresh angle...")
        retry_prompt = (
            formatted_prompt
            + f"\n\n🚨 STRICT DEDUPLICATION REJECTION: Your post was rejected because of: {dup_reason}\n"
            f"You MUST generate a COMPLETELY DIFFERENT hook and angle! "
            f"Choose a fresh perspective, different story, or different question that has NOT been used before."
        )
        try:
            retry_raw = client.generate_content(retry_prompt)
            validated = validate_generated_content(retry_raw, account=account)
            print("[Deduplication] [OK] Successfully generated unique content on retry.")
        except Exception as retry_err:
            print(f"[Deduplication] Retry warning: {retry_err}, keeping original.")

    # Hard validation: every post MUST mention "Demoly" by name
    all_text = " ".join(validated.posts)
    if "demoly" not in all_text.lower():
        print("[Brand Check] Post missing 'Demoly' name. Regenerating with brand enforcement...")
        brand_retry_prompt = (
            formatted_prompt
            + "\n\n⚠️ CRITICAL BRAND RULE VIOLATION: Your previous response did NOT mention 'Demoly' by name anywhere! "
            "This is UNACCEPTABLE. You MUST explicitly name 'Demoly' at least once in the post. "
            "Do NOT write generic advice without attributing the solution to Demoly."
        )
        try:
            brand_retry_raw = client.generate_content(brand_retry_prompt)
            brand_validated = validate_generated_content(brand_retry_raw, account=account)
            if "demoly" in " ".join(brand_validated.posts).lower():
                validated = brand_validated
                print("[Brand Check] [OK] Regenerated post now includes 'Demoly'.")
        except Exception as brand_err:
            print(f"[Brand Check] Retry error: {brand_err}, keeping original.")

    # Media rotation & URL resolution
    if preferred_media_filename:
        validated.media_filename = preferred_media_filename

    if validated.media_filename:
        # Validate that media has not been recently used on this account; auto-rotate if so
        validated.media_filename = rotate_or_validate_media(
            chosen_filename=validated.media_filename,
            account_name=account.name if account else None,
        )
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

    # Validate and rotate media to ensure no repetition for this account
    if allow_media and not getattr(plan_item, "generate_image", False) and plan_item.preferred_media:
        plan_item.preferred_media = rotate_or_validate_media(
            chosen_filename=plan_item.preferred_media,
            account_name=account.name if account else None,
        )

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
    if getattr(plan_item, "generate_image", False):
        print("[Content Generator] Generating AI visual image matching post content...")
        image_url = generate_image_for_post(
            focus_topic=plan_item.focus_topic,
            trend_connection=plan_item.trend_connection,
            post_text=result.posts[0] if result.posts else None,
            account=account,
        )
        if image_url:
            result.media_filename = None  # No catalog filename — it's AI-generated
            result.media_url = image_url
            print(f"[Content Generator] AI image attached: {image_url}")
        else:
            # Fallback: pick fresh catalog asset rather than posting with no image
            print("[Content Generator] AI image generation failed. Falling back to fresh catalog asset.")
            available = get_available_media_for_account(account_name=account.name if account else None)
            if available:
                fallback_file = available[0].get("filename")
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
