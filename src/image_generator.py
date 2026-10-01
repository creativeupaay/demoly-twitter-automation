"""
image_generator.py
================================================================================
100% FREE AI Image & Visual Graphic Generation for Demoly.dev X Automation.

Zero API Keys, Zero Subscriptions, Zero Charges.

Visual Modalities Provided:
  1. POLLINATIONS AI (Flux / SDXL Text-to-Image)
     - Gemini creates an ultra-sleek, aesthetic 3D/cyber visual prompt.
     - Fetches 1200x675 high-res visuals from Pollinations.ai (100% free, no auth).

  2. VIRAL QUOTE / HOOK VISUAL CARD (Pillow Dark Mode)
     - High-engagement tweet/insight card with gradient border, profile avatar,
       verified badge, bold typography, and Demoly watermark.

  3. WORKFLOW COMPARISON INFOGRAPHIC (Before vs After Matrix)
     - High-contrast Before ("Without Demoly") vs After ("With Demoly.dev").

  4. VIRAL DEVELOPER MEME GENERATOR
     - Drake Hotline Bling and developer culture memes with Demoly promotion.

All generated assets are saved to assets/generated/ and uploaded to Catbox CDN for Buffer ingest.
================================================================================
"""

import os
import re
import json
import time
import urllib.parse
import urllib.request
import textwrap
from pathlib import Path
from typing import Optional, List, Dict, Any

from src.config import GENERATED_IMAGES_DIR, AccountConfig

# Ensure generated images and templates directories exist
GENERATED_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
TEMPLATES_DIR = Path("assets/templates")
TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# CDN Upload (uploads generated file to catbox.moe for Buffer ingest)
# ---------------------------------------------------------------------------

def _upload_to_cdn(file_path: Path) -> Optional[str]:
    """Uploads a local image file to catbox.moe CDN and returns the public URL."""
    try:
        import requests
        print(f"[Image Generator] Uploading to CDN: {file_path.name}")
        with open(file_path, "rb") as f:
            res = requests.post(
                "https://catbox.moe/user/api.php",
                data={"reqtype": "fileupload"},
                files={"fileToUpload": f},
                timeout=40,
            )
        if res.status_code == 200 and res.text.strip().startswith("http"):
            url = res.text.strip()
            print(f"[Image Generator] CDN upload successful: {url}")
            return url
        else:
            print(f"[Image Generator Warning] CDN upload unexpected response: {res.text[:200]}")
    except Exception as e:
        print(f"[Image Generator Warning] CDN upload failed: {e}")
    return None


# ---------------------------------------------------------------------------
# Provider 1: Pollinations AI (100% Free Text-to-Image with Flux/SDXL)
# ---------------------------------------------------------------------------

def generate_pollinations_image(
    prompt: str,
    slug: str = "visual",
    width: int = 1200,
    height: int = 675,
    model: str = "flux-schnell",
) -> Optional[str]:
    """
    Generates a 100% free high-resolution image using Pollinations AI.
    Uses flux-schnell (free, no auth) with turbo fallback.
    No API key or payment required.
    """
    # Free models in order of preference (flux-schnell is the free tier)
    free_models = [model, "flux-schnell", "turbo", "flux"]
    seen = set()
    ordered_models = [m for m in free_models if not (m in seen or seen.add(m))]

    timestamp = int(time.time())
    clean_slug = re.sub(r"[^a-z0-9]+", "_", slug.lower())[:30].strip("_")
    filename = f"{timestamp}_flux_{clean_slug}.jpg"
    save_path = GENERATED_IMAGES_DIR / filename
    encoded_prompt = urllib.parse.quote(prompt.strip())

    for attempt_model in ordered_models:
        try:
            print(f"[Pollinations AI] Trying model: {attempt_model}...")
            url = (
                f"https://image.pollinations.ai/prompt/{encoded_prompt}"
                f"?width={width}&height={height}&nologo=true"
                f"&model={attempt_model}&seed={int(time.time())}"
            )
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                content = resp.read()
                if len(content) > 5000:
                    save_path.write_bytes(content)
                    print(f"[Pollinations AI] ✅ Saved: {save_path.name} ({len(content):,} bytes) via {attempt_model}")
                    return _upload_to_cdn(save_path) or str(save_path)
                else:
                    print(f"[Pollinations AI] Model {attempt_model}: response too small ({len(content)} bytes), trying next...")
        except Exception as e:
            print(f"[Pollinations AI] Model {attempt_model} failed: {e}. Trying next...")

    print("[Pollinations AI Warning] All models exhausted.")
    return None


def generate_conceptual_image_for_post(post_text: str, focus_topic: str) -> Optional[str]:
    """
    Uses Gemini to craft a tailored visual prompt then generates via Pollinations free tier.
    Falls back to viral quote card if generation fails.
    """
    try:
        from src.gemini_client import GeminiClient
        gemini = GeminiClient()
        prompt = f"""You are an elite 3D visual artist and art director for Demoly (a modern SaaS platform for AI screen recording, interactive client handovers, and developer visual bug reporting).

Create an ultra-detailed, aesthetic text-to-image prompt for the topic: "{focus_topic}".
Context from post: "{post_text[:140]}"

Style Rules:
- Modern dark mode aesthetic, deep violet #7C3AED and electric indigo accents, clean neon lighting.
- Futuristic 3D isometric browser interface, glowing telemetry nodes, elegant glassmorphism, hyper-clean minimal composition.
- Cinematic lighting, octane render, 8k resolution, photorealistic, Behance trending UI, highly polished tech product.
- DO NOT include garbled text or ugly watermarks. Focus on 3D UI cards, visual streams, AI chat bubbles, and interactive workflows.

Return ONLY the raw visual prompt text (under 60 words). No commentary."""

        visual_prompt = gemini.generate_raw_text(prompt).strip()
        visual_prompt = re.sub(r"^[\"']|[\"']$", "", visual_prompt).strip()
        print(f"[Image Generator] Crafting visual with prompt: {visual_prompt[:90]}...")
        # Use flux-schnell (free tier) first
        result = generate_pollinations_image(prompt=visual_prompt, slug=focus_topic, model="flux-schnell")
        if result:
            return result
        # Pillow quote card as backup
        print("[Image Generator] Pollinations failed, generating quote card instead...")
        first_line = (post_text or focus_topic).split("\n")[0][:100]
        return generate_viral_quote_card(first_line, author_name="Demoly", handle="@Demolyy4ls", slug=focus_topic)
    except Exception as e:
        print(f"[Image Generator Warning] Conceptual image prompt creation failed: {e}")
        return None


# ---------------------------------------------------------------------------
# Provider 2: Viral Quote / Hook Visual Card
# ---------------------------------------------------------------------------

def generate_viral_quote_card(
    hook_text: str,
    author_name: str = "Demoly",
    handle: str = "@Demolyy4ls",
    slug: str = "quote",
) -> Optional[str]:
    """
    Renders a high-engagement dark-mode visual card featuring a bold statement/hook.
    """
    try:
        from PIL import Image, ImageDraw, ImageFont

        W, H = 1200, 675
        img = Image.new("RGB", (W, H), color="#080C16")
        draw = ImageDraw.Draw(img)

        # Ambient gradient glow
        for r in range(140, 0, -8):
            alpha = int(18 * (r / 140))
            draw.ellipse([W - 380 - r, -100 - r, W + 120 + r, 280 + r], outline=(124, 58, 237, alpha))
            draw.ellipse([-100 - r, H - 280 - r, 300 + r, H + 100 + r], outline=(99, 102, 241, alpha))

        # Main Card with subtle border
        draw.rounded_rectangle([70, 60, W - 70, H - 60], radius=28, fill="#0F172A", outline="#1E293B", width=2)

        # Fonts
        font_path_b = "C:\\Windows\\Fonts\\segoeuib.ttf" if os.path.exists("C:\\Windows\\Fonts\\segoeuib.ttf") else "arialbd.ttf"
        font_path_r = "C:\\Windows\\Fonts\\segoeui.ttf" if os.path.exists("C:\\Windows\\Fonts\\segoeui.ttf") else "arial.ttf"

        try:
            font_name = ImageFont.truetype(font_path_b, 26)
            font_handle = ImageFont.truetype(font_path_r, 20)
            font_quote = ImageFont.truetype(font_path_b, 34)
            font_badge = ImageFont.truetype(font_path_b, 16)
            font_footer = ImageFont.truetype(font_path_b, 18)
        except Exception:
            font_name = font_handle = font_quote = font_badge = font_footer = ImageFont.load_default()

        # Author Badge Header
        draw.ellipse([120, 110, 176, 166], fill="#7C3AED")
        draw.text((138, 122), "D", font=font_name, fill="#FFFFFF")

        draw.text((195, 115), author_name, font=font_name, fill="#F8FAFC")
        draw.text((195, 146), handle, font=font_handle, fill="#64748B")

        # Verified tick
        draw.rounded_rectangle([195 + len(author_name) * 16 + 10, 118, 195 + len(author_name) * 16 + 32, 140], radius=11, fill="#38BDF8")
        draw.text((195 + len(author_name) * 16 + 16, 120), "v", font=font_badge, fill="#0F172A")

        # Top Pill Tag
        draw.rounded_rectangle([W - 320, 115, W - 120, 155], radius=10, fill="#1E1B4B", outline="#4338CA")
        draw.text((W - 300, 124), "FOUNDER INSIGHT", font=font_badge, fill="#A78BFA")

        # Divider line
        draw.line([(120, 190), (W - 120, 190)], fill="#1E293B", width=1)

        # Quote Body
        wrapped = textwrap.fill(hook_text, width=42)
        draw.text((120, 230), f'"{wrapped}"', font=font_quote, fill="#F1F5F9", spacing=14)

        # Footer
        draw.line([(120, H - 140), (W - 120, H - 140)], fill="#1E293B", width=1)
        draw.text((120, H - 115), "demoly.dev", font=font_footer, fill="#8B5CF6")
        draw.text((250, H - 115), "|  The AI-Powered Browser Screen Recorder for Web Agencies", font=font_handle, fill="#64748B")

        timestamp = int(time.time())
        clean_slug = re.sub(r"[^a-z0-9]+", "_", slug.lower())[:30].strip("_")
        filename = f"{timestamp}_quote_{clean_slug}.png"
        save_path = GENERATED_IMAGES_DIR / filename
        img.save(save_path)
        print(f"[Image Generator] Generated Quote Card: {save_path.name}")
        return _upload_to_cdn(save_path) or str(save_path)
    except Exception as e:
        print(f"[Image Generator Warning] Failed to render quote card: {e}")
        return None


# ---------------------------------------------------------------------------
# Provider 3: Workflow Comparison Matrix (Before vs After Infographic)
# ---------------------------------------------------------------------------

def _get_comparison_data_from_gemini(post_text: str, focus_topic: str) -> Dict[str, Any]:
    """Uses Gemini to generate Before vs After comparison points."""
    try:
        from src.gemini_client import GeminiClient
        gemini = GeminiClient()
        prompt = f"""You are an expert tech infographic designer for Demoly.
Topic: "{focus_topic}"
Post: "{post_text}"

Generate JSON for a Before vs After comparison card:
{{
  "headline": "Punchy title under 40 chars",
  "left_title": "Without Demoly",
  "left_points": [
    "Friction point 1 under 45 chars",
    "Friction point 2 under 45 chars",
    "Friction point 3 under 45 chars"
  ],
  "right_title": "With Demoly.dev",
  "right_points": [
    "Solution benefit 1 under 45 chars",
    "Solution benefit 2 under 45 chars",
    "Solution benefit 3 under 45 chars"
  ]
}}
Return ONLY valid JSON."""
        raw = gemini.generate_raw_text(prompt)
        cleaned = re.sub(r"^```json\s*", "", raw, flags=re.MULTILINE)
        cleaned = re.sub(r"^```\s*$", "", cleaned, flags=re.MULTILINE).strip()
        data = json.loads(cleaned)
        if "headline" in data and "left_points" in data and "right_points" in data:
            return data
    except Exception as e:
        print(f"[Image Generator Warning] Comparison fallback: {e}")

    return {
        "headline": "The Client Handover Bottleneck",
        "left_title": "Without Demoly",
        "left_points": [
            "30-min calls explaining basic buttons",
            "Clients forget UI steps after 48h",
            "5+ back-and-forth bug support tickets"
        ],
        "right_title": "With Demoly.dev",
        "right_points": [
            "1-click self-serve interactive replay",
            "Inspect visual clicks and UI actions",
            "Zero status calls, 80% fewer tickets"
        ]
    }


def generate_comparison_infographic_card(post_text: str, focus_topic: str) -> Optional[str]:
    """Generates high-contrast Before vs After comparison matrix (1200x675)."""
    try:
        from PIL import Image, ImageDraw, ImageFont

        data = _get_comparison_data_from_gemini(post_text, focus_topic)
        headline = data.get("headline", "Workflow Comparison")
        left_title = data.get("left_title", "Without Demoly")
        left_points = data.get("left_points", [])
        right_title = data.get("right_title", "With Demoly.dev")
        right_points = data.get("right_points", [])

        W, H = 1200, 675
        img = Image.new("RGB", (W, H), color="#0A0E1A")
        draw = ImageDraw.Draw(img)

        font_path_b = "C:\\Windows\\Fonts\\segoeuib.ttf" if os.path.exists("C:\\Windows\\Fonts\\segoeuib.ttf") else "arialbd.ttf"
        font_path_r = "C:\\Windows\\Fonts\\segoeui.ttf" if os.path.exists("C:\\Windows\\Fonts\\segoeui.ttf") else "arial.ttf"

        try:
            font_badge = ImageFont.truetype(font_path_b, 18)
            font_h1 = ImageFont.truetype(font_path_b, 34)
            font_col_h = ImageFont.truetype(font_path_b, 24)
            font_item = ImageFont.truetype(font_path_r, 20)
            font_symbol = ImageFont.truetype(font_path_b, 22)
            font_footer = ImageFont.truetype(font_path_b, 18)
        except Exception:
            font_badge = font_h1 = font_col_h = font_item = font_symbol = font_footer = ImageFont.load_default()

        # Violet ambient glow
        for r in range(120, 0, -6):
            alpha = int(14 * (r / 120))
            draw.ellipse([W - 350 - r, -80 - r, W + 150 + r, 300 + r], outline=(124, 58, 237, alpha))

        # Main Card
        draw.rounded_rectangle([50, 40, W - 50, H - 40], radius=24, fill="#111827", outline="#1F2937", width=2)

        # Top Badge & Headline
        draw.rounded_rectangle([90, 75, 290, 115], radius=8, fill="#7C3AED")
        draw.text((110, 83), "WORKFLOW COMPARISON", font=font_badge, fill="#FFFFFF")
        draw.text((90, 135), headline, font=font_h1, fill="#F9FAFB")

        col_w = 480
        y_top = 210
        box_h = 320

        # Left Column (Friction)
        draw.rounded_rectangle([90, y_top, 90 + col_w, y_top + box_h], radius=16, fill="#1F1622", outline="#5B2136", width=2)
        draw.text((120, y_top + 25), left_title, font=font_col_h, fill="#F87171")
        y = y_top + 80
        for item in left_points[:4]:
            draw.text((120, y), "x", font=font_symbol, fill="#EF4444")
            draw.text((150, y + 2), item, font=font_item, fill="#D1D5DB")
            y += 56

        # Right Column (Solution)
        x_right = W - 90 - col_w
        draw.rounded_rectangle([x_right, y_top, x_right + col_w, y_top + box_h], radius=16, fill="#181F38", outline="#4338CA", width=2)
        draw.text((x_right + 30, y_top + 25), right_title, font=font_col_h, fill="#A78BFA")
        y = y_top + 80
        for item in right_points[:4]:
            draw.text((x_right + 30, y), "+", font=font_symbol, fill="#10B981")
            draw.text((x_right + 60, y + 2), item, font=font_item, fill="#E0E7FF")
            y += 56

        # Footer
        draw.line([(90, H - 90), (W - 90, H - 90)], fill="#2A344A", width=1)
        draw.text((90, H - 75), "demoly.dev", font=font_footer, fill="#8B5CF6")
        draw.text((220, H - 75), "|  Interactive Browser Screen Recording for Modern Web Agencies", font=font_item, fill="#6B7280")

        timestamp = int(time.time())
        slug = re.sub(r"[^a-z0-9]+", "_", focus_topic.lower())[:35].strip("_")
        filename = f"{timestamp}_matrix_{slug}.png"
        save_path = GENERATED_IMAGES_DIR / filename
        img.save(save_path)
        print(f"[Image Generator] Generated comparison infographic: {save_path.name}")
        return _upload_to_cdn(save_path) or str(save_path)

    except Exception as e:
        print(f"[Image Generator Warning] Failed to generate comparison infographic: {e}")
        return None


# ---------------------------------------------------------------------------
# Provider 4: Drake & Developer Meme Generator
# ---------------------------------------------------------------------------

def generate_drake_meme(top_text: str, bottom_text: str, slug: str) -> Optional[str]:
    """Renders Drake Hotline Bling meme with custom captions and demoly.dev branding."""
    try:
        from PIL import Image, ImageDraw, ImageFont
        drake_path = TEMPLATES_DIR / "drake.jpg"
        if not drake_path.exists():
            import requests
            r = requests.get("https://i.imgflip.com/30b1gx.jpg", timeout=20)
            drake_path.write_bytes(r.content)

        img = Image.open(drake_path).convert("RGB")
        W, H = img.size
        draw = ImageDraw.Draw(img)

        font_path = "C:\\Windows\\Fonts\\segoeuib.ttf" if os.path.exists("C:\\Windows\\Fonts\\segoeuib.ttf") else "arialbd.ttf"
        try:
            font = ImageFont.truetype(font_path, 28)
            badge_font = ImageFont.truetype(font_path, 18)
        except Exception:
            font = badge_font = ImageFont.load_default()

        wrapped_top = textwrap.fill(top_text, width=22)
        draw.text((W // 2 + 25, 80), wrapped_top, font=font, fill="#111827")

        wrapped_bottom = textwrap.fill(bottom_text, width=22)
        draw.text((W // 2 + 25, H // 2 + 80), wrapped_bottom, font=font, fill="#111827")

        draw.rectangle([W - 160, H - 36, W - 8, H - 8], fill="#7C3AED")
        draw.text((W - 146, H - 32), "demoly.dev", font=badge_font, fill="#FFFFFF")

        timestamp = int(time.time())
        clean_slug = re.sub(r"[^a-z0-9]+", "_", slug.lower())[:35].strip("_")
        filename = f"{timestamp}_meme_{clean_slug}.jpg"
        save_path = GENERATED_IMAGES_DIR / filename
        img.save(save_path)
        print(f"[Image Generator] Generated Drake meme: {save_path.name}")
        return _upload_to_cdn(save_path) or str(save_path)
    except Exception as e:
        print(f"[Image Generator Warning] Failed to render Drake meme: {e}")
        return None


def generate_meme_for_trend(post_text: str, focus_topic: str) -> Optional[str]:
    """Uses Gemini to craft a relatable meme punchline linking trending topic to Demoly."""
    try:
        from src.gemini_client import GeminiClient
        gemini = GeminiClient()
        prompt = f"""You are a social media strategist creating a viral tech meme for Demoly.
Topic: "{focus_topic}"
Tweet: "{post_text}"

Generate JSON for a Drake meme:
- "top": Frustrating traditional way (under 50 chars).
- "bottom": Demoly solution (under 50 chars).

JSON schema:
{{
  "top": "rejection text",
  "bottom": "approval text"
}}
Return ONLY valid JSON."""
        raw = gemini.generate_raw_text(prompt)
        cleaned = re.sub(r"^```json\s*", "", raw, flags=re.MULTILINE)
        cleaned = re.sub(r"^```\s*$", "", cleaned, flags=re.MULTILINE).strip()
        data = json.loads(cleaned)
        top = data.get("top", "Hosting a 45-min Zoom call to explain UI updates")
        bottom = data.get("bottom", "Sending a 15-sec Demoly video walkthrough")
        return generate_drake_meme(top, bottom, focus_topic)
    except Exception as e:
        print(f"[Image Generator Warning] Failed to generate meme copy: {e}")
        return None


# ---------------------------------------------------------------------------
# Master Dispatcher (Incorporating All Free Visual Modalities)
# ---------------------------------------------------------------------------

def generate_image_for_post(
    focus_topic: str,
    trend_connection: Optional[str] = None,
    post_text: Optional[str] = None,
    account: Optional[AccountConfig] = None,
) -> Optional[str]:
    """
    Intelligently generates the highest-converting visual for the post:
      1. Trend / Pop Culture Topics    -> Viral Developer Meme (Drake)
      2. AI / Conceptual / Big Vision  -> Pollinations AI (Flux 3D Cyber Art)
      3. Agency / Handover / Workflow  -> Before vs After Infographic Matrix
      4. Founder Quotes / Hot Takes   -> Dark-Mode Viral Quote Card

    100% Free - Zero cost, zero API keys required.
    """
    print(f"\n[Image Generator] Generating free visual for: '{focus_topic[:70]}'")
    effective_text = post_text or focus_topic
    text_lower = f"{focus_topic} {effective_text}".lower()

    author_name = account.name.split("(")[0].strip() if account else "Demoly"
    handle = "@Demolyy4ls"
    if account and "@" in account.name:
        handle_match = re.search(r"(@[A-Za-z0-9_]+)", account.name)
        if handle_match:
            handle = handle_match.group(1)

    # Strategy 1: Viral Memes for Culture & Trending Drama
    meme_keywords = ["meme", "pov:", "drake", "friday deployment", "client drama", "funny"]
    if any(k in text_lower for k in meme_keywords) or (trend_connection and "meme" in trend_connection.lower()):
        print("[Image Generator] Selecting: Viral Meme...")
        res = generate_meme_for_trend(effective_text, focus_topic)
        if res:
            return res

    # Strategy 2: Conceptual & Futuristic AI Imagery via Pollinations Flux
    conceptual_keywords = ["future", "vision", "ai agent", "mcp server", "telemetry", "cursor", "anthropic", "claude", "browser interaction", "smart", "autonomous"]
    if any(k in text_lower for k in conceptual_keywords):
        print("[Image Generator] Selecting: Pollinations AI (Flux Text-to-Image)...")
        res = generate_conceptual_image_for_post(effective_text, focus_topic)
        if res:
            return res

    # Strategy 3: Direct Workflow Comparisons
    comparison_keywords = ["vs", "compare", "without", "before", "handover", "loom", "drive", "bottleneck", "replace", "meetings"]
    if any(k in text_lower for k in comparison_keywords):
        print("[Image Generator] Selecting: Before vs After Matrix...")
        res = generate_comparison_infographic_card(effective_text, focus_topic)
        if res:
            return res

    # Strategy 4: High-Stakes Founder Quote / Viral Insight Card
    first_sentence = effective_text.split("\n")[0].strip()
    if len(first_sentence) > 30 and ("?" in first_sentence or "!" in first_sentence or "$" in first_sentence or "we" in first_sentence.lower()):
        print("[Image Generator] Selecting: Viral Quote / Hook Card...")
        res = generate_viral_quote_card(first_sentence, author_name=author_name, handle=handle, slug=focus_topic)
        if res:
            return res

    # Universal Fallback: Workflow Comparison or Pollinations AI
    print("[Image Generator] Defaulting to Workflow Comparison Card...")
    res = generate_comparison_infographic_card(effective_text, focus_topic)
    if res:
        return res

    return generate_pollinations_image(prompt=f"Minimalist dark mode tech interface for {focus_topic}, violet accents", slug=focus_topic)
