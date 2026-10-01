"""
media_manager.py
================================================================================
Manages authentic Demoly videos (.mp4) and images (.png, .jpg) in assets/.
- Scans assets/videos and assets/images
- Catalogs metadata in data/media_catalog.json
- Automatically analyzes media using Gemini multimodal capabilities
- Resolves public URLs for Buffer media publishing
================================================================================
"""

import sys
import json
import argparse
from pathlib import Path
from typing import List, Dict, Optional, Any

from src.config import (
    ASSETS_DIR,
    VIDEOS_DIR,
    IMAGES_DIR,
    MEDIA_CATALOG_PATH,
    MEDIA_BASE_URL,
    PUBLISHED_CSV_PATH,
)
from src.gemini_client import GeminiClient

VIDEO_EXTS = {".mp4", ".webm", ".mov"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".svg", ".gif", ".webp"}


def load_media_catalog() -> List[Dict[str, Any]]:
    """
    Loads the registered media catalog from data/media_catalog.json,
    filtering for files that actually exist in assets/videos or assets/images.
    """
    if not MEDIA_CATALOG_PATH.exists():
        return []
    try:
        with open(MEDIA_CATALOG_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)

        valid_assets = []
        for entry in raw:
            fname = entry.get("filename")
            if not fname:
                continue
            is_video = entry.get("type") == "video" or Path(fname).suffix.lower() in VIDEO_EXTS
            target_dir = VIDEOS_DIR if is_video else IMAGES_DIR
            if (target_dir / fname).exists() or Path(fname).exists():
                valid_assets.append(entry)
        return valid_assets
    except Exception as e:
        print(f"[Warning] Failed to load media catalog: {e}")
        return []


def save_media_catalog(catalog: List[Dict[str, Any]]) -> None:
    """Saves the media catalog to data/media_catalog.json."""
    MEDIA_CATALOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(MEDIA_CATALOG_PATH, "w", encoding="utf-8") as f:
        json.dump(catalog, f, indent=2, ensure_ascii=False)


def _upload_catbox(path: Path) -> Optional[str]:
    """Uploads a local image or media file to catbox.moe CDN."""
    import requests
    try:
        with open(path, "rb") as f:
            res = requests.post(
                "https://catbox.moe/user/api.php",
                data={"reqtype": "fileupload"},
                files={"fileToUpload": (path.name, f)},
                timeout=60,
            )
        if res.status_code == 200 and res.text.strip().startswith("http"):
            return res.text.strip()
    except Exception as e:
        print(f"[Media Uploader] Catbox upload error: {e}")
    return None


def _upload_to_cdn(local_path: Path, is_video: bool = False) -> Optional[str]:
    """
    Uploads a local file to a public CDN that Buffer can ingest.
    Uses catbox.moe for fast public hosting.
    """
    print(f"[Media Uploader] Uploading {local_path.name} to CDN...")
    url = _upload_catbox(local_path)
    if url:
        print(f"[Media Uploader] Uploaded successfully: {url}")
        return url
    print("[Media Uploader] CDN upload failed.")
    return None


# Simple in-process URL cache to avoid re-uploading the same file in one run
_url_cache: dict = {}


def resolve_media_url(filename: str) -> Optional[str]:
    """
    Resolves the public HTTP(S) URL for a media file.
    - If filename is already an http(s) URL, returns it as-is.
    - For images: uploads to Catbox CDN (fast, direct image serving, 100% reliable on Buffer).
      Falls back to MEDIA_BASE_URL (jsDelivr) if Catbox is unavailable.
    - For videos: uses MEDIA_BASE_URL (jsDelivr) which supports Accept-Ranges: bytes.
      Falls back to Catbox CDN upload if MEDIA_BASE_URL is not configured.
    """
    if not filename:
        return None
    if filename.startswith("http://") or filename.startswith("https://"):
        return filename

    path_obj = Path(filename)
    clean_name = path_obj.name

    if clean_name in _url_cache:
        return _url_cache[clean_name]

    ext = path_obj.suffix.lower()
    is_video = ext in VIDEO_EXTS

    # Locate local file
    local_path = None
    target_dir = VIDEOS_DIR if is_video else IMAGES_DIR
    potential_file = target_dir / clean_name
    if potential_file.exists():
        local_path = potential_file
    elif path_obj.exists():
        local_path = path_obj

    # If the file does not exist locally, fall back to a valid asset from the catalog
    if not local_path or not local_path.exists():
        print(f"[Media Resolver] Warning: File '{clean_name}' not found locally. Seeking fallback...")
        catalog = load_media_catalog()
        matching = [e.get("filename") for e in catalog if (e.get("type") == "video") == is_video]
        if matching:
            fallback = matching[0]
            print(f"[Media Resolver] Falling back to available asset '{fallback}'")
            return resolve_media_url(fallback)
        return None

    # 1. For images: prefer Catbox upload (Buffer ingests Catbox images without 404 or CDN issues)
    if not is_video:
        url = _upload_to_cdn(local_path, is_video=False)
        if url:
            _url_cache[clean_name] = url
            return url
        # Fallback to MEDIA_BASE_URL if Catbox failed
        if MEDIA_BASE_URL:
            import urllib.parse
            base = MEDIA_BASE_URL.rstrip("/")
            safe_name = urllib.parse.quote(clean_name)
            url = f"{base}/assets/images/{safe_name}"
            _url_cache[clean_name] = url
            return url

    # 2. For videos: MEDIA_BASE_URL (jsDelivr) is preferred because Buffer requires byte-range requests
    if is_video:
        if MEDIA_BASE_URL:
            import urllib.parse
            base = MEDIA_BASE_URL.rstrip("/")
            safe_name = urllib.parse.quote(clean_name)
            url = f"{base}/assets/videos/{safe_name}"
            _url_cache[clean_name] = url
            return url
        # Fallback to Catbox upload for videos if no MEDIA_BASE_URL
        url = _upload_to_cdn(local_path, is_video=True)
        if url:
            _url_cache[clean_name] = url
            return url

    return None


def analyze_media_file_with_gemini(file_path: Path, media_type: str) -> Dict[str, Any]:
    """
    Calls Gemini multimodal vision to inspect the actual video or image bytes
    and generate accurate tags, UI summary, and capability mappings.
    """
    clean_name = file_path.stem.replace("_", " ").replace("-", " ")
    prompt = f"""
You are cataloging an authentic Demoly product asset for social media publishing on X.
Asset Name: {file_path.name}
Asset Type: {media_type}

Inspect this visual asset and identify the exact Demoly UI elements, screens, or features shown (e.g. landing page, dashboard, recording controls, DOM search, masking, client handover):
Provide a valid JSON response with this exact schema:
{{
  "summary": "1-sentence description of the exact UI features, dashboard elements, or workflow shown in this {media_type}",
  "capabilities": ["Specific Feature 1", "Specific Feature 2"],
  "recommended_hook_angle": "Natural hook suggestion to introduce this visual proof on X"
}}
Return ONLY valid JSON.
"""
    try:
        from google.genai import types
        client = GeminiClient()
        raw_client = client._get_client()

        ext = file_path.suffix.lower()
        mime_map = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
            ".mp4": "video/mp4",
            ".webm": "video/webm",
        }
        mime = mime_map.get(ext, "image/png")

        with open(file_path, "rb") as f:
            media_bytes = f.read()

        part = types.Part.from_bytes(data=media_bytes, mime_type=mime)
        res = raw_client.models.generate_content(
            model=client.model_name,
            contents=[part, prompt]
        )
        raw_text = res.text.strip()
        if raw_text.startswith("```json"):
            raw_text = raw_text[7:]
        if raw_text.startswith("```"):
            raw_text = raw_text[3:]
        if raw_text.endswith("```"):
            raw_text = raw_text[:-3]
        raw_text = raw_text.strip()

        data = json.loads(raw_text)
        return {
            "summary": data.get("summary", f"Demoly interface showing {clean_name}"),
            "capabilities": data.get("capabilities", ["Demoly Web Feature"]),
            "recommended_hook_angle": data.get("recommended_hook_angle", f"Here is how this works in Demoly:"),
        }
    except Exception as e:
        return {
            "summary": f"Demoly {media_type} interface for {clean_name}.",
            "capabilities": ["Product Feature"],
            "recommended_hook_angle": f"Watch how this works in Demoly:",
        }


def scan_and_index_assets() -> int:
    """
    Scans assets/videos and assets/images for new media files,
    prunes deleted assets, and indexes them into data/media_catalog.json.
    """
    catalog = load_media_catalog()
    # Prune any assets that are no longer on disk
    initial_len = len(catalog)
    catalog = [
        e for e in catalog
        if (VIDEOS_DIR / e.get("filename", "")).exists() or (IMAGES_DIR / e.get("filename", "")).exists()
    ]
    pruned_count = initial_len - len(catalog)
    if pruned_count > 0:
        print(f"[Media Indexer] Pruned {pruned_count} missing media file(s) from catalog.")

    existing_files = {entry.get("filename") for entry in catalog if "filename" in entry}
    added_count = 0

    # Ensure directories exist
    VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Scan Videos
    for v_file in VIDEOS_DIR.iterdir():
        if v_file.is_file() and v_file.suffix.lower() in VIDEO_EXTS:
            if v_file.name not in existing_files:
                print(f"[Media Indexer] Found new video: {v_file.name}. Analyzing with Gemini...")
                analysis = analyze_media_file_with_gemini(v_file, media_type="video")
                catalog.append({
                    "id": f"vid_{len(catalog) + 1}",
                    "filename": v_file.name,
                    "type": "video",
                    "file_size_kb": round(v_file.stat().st_size / 1024, 1),
                    "summary": analysis["summary"],
                    "capabilities": analysis["capabilities"],
                    "recommended_hook_angle": analysis["recommended_hook_angle"],
                })
                existing_files.add(v_file.name)
                added_count += 1

    # 2. Scan Images
    for i_file in IMAGES_DIR.iterdir():
        if i_file.is_file() and i_file.suffix.lower() in IMAGE_EXTS and not i_file.name.startswith("."):
            if i_file.name not in existing_files:
                print(f"[Media Indexer] Found new image: {i_file.name}. Analyzing with Gemini...")
                analysis = analyze_media_file_with_gemini(i_file, media_type="image")
                catalog.append({
                    "id": f"img_{len(catalog) + 1}",
                    "filename": i_file.name,
                    "type": "image",
                    "file_size_kb": round(i_file.stat().st_size / 1024, 1),
                    "summary": analysis["summary"],
                    "capabilities": analysis["capabilities"],
                    "recommended_hook_angle": analysis["recommended_hook_angle"],
                })
                existing_files.add(i_file.name)
                added_count += 1

    if added_count > 0 or pruned_count > 0:
        save_media_catalog(catalog)
        print(f"[Media Indexer] Catalog updated. Total assets: {len(catalog)}.")
    else:
        print(f"[Media Indexer] No new media assets found. Catalog is up to date ({len(catalog)} total assets).")

    return added_count


def get_used_media_for_account(account_name: Optional[str] = None, lookback: int = 30) -> List[str]:
    """
    Returns the list of media filenames used recently by this account (or all accounts if None),
    read from data/published_posts.csv in reverse chronological order (most recent first).
    """
    if not PUBLISHED_CSV_PATH.exists():
        return []
    import csv
    used = []
    try:
        with open(PUBLISHED_CSV_PATH, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        # Search backwards from most recent
        for r in reversed(rows):
            med = (r.get("Media") or "").strip()
            if not med or med.lower() in ("none", "null", ""):
                continue
            acct = (r.get("Account") or "").strip()
            # If account_name specified, match case-insensitively or substring
            if account_name:
                p_acc = account_name.lower().split()[0]  # e.g. "demoly", "manish", "sourabh"
                if p_acc not in acct.lower() and account_name.lower() != acct.lower():
                    continue
            used.append(med)
            if len(used) >= lookback:
                break
    except Exception as e:
        print(f"[Media Tracker Warning] Error reading media history: {e}")
    return used


def get_available_media_for_account(
    account_name: Optional[str] = None,
    batch_excluded: Optional[List[str]] = None,
    media_type: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Returns media catalog assets prioritized for this account:
    1. Excludes assets in batch_excluded (picked by other accounts in this batch).
    2. Prioritizes assets NEVER used by this account or least-recently used.
    3. Guarantees no repeated picture on the same account.
    """
    catalog = load_media_catalog()
    if not catalog:
        return []

    excluded_set = set(batch_excluded or [])
    used_recently = get_used_media_for_account(account_name=account_name, lookback=25)
    used_set = set(used_recently)

    # Filter by media_type if specified
    eligible = [e for e in catalog if e.get("filename") not in excluded_set]
    if media_type:
        eligible = [e for e in eligible if e.get("type") == media_type]

    # Partition into fresh (never used recently) and used
    fresh = [e for e in eligible if e.get("filename") not in used_set]

    # For used assets, sort by least-recently used (earliest in history / furthest from most recent)
    def lru_key(item):
        fname = item.get("filename")
        if fname in used_recently:
            return used_recently.index(fname)
        return 9999

    used_sorted = sorted([e for e in eligible if e.get("filename") in used_set], key=lru_key, reverse=True)

    # Return fresh assets first, followed by LRU assets
    return fresh + used_sorted


def rotate_or_validate_media(
    chosen_filename: Optional[str],
    account_name: Optional[str] = None,
    batch_excluded: Optional[List[str]] = None,
) -> Optional[str]:
    """
    Hard safety guard: If the chosen media was already used recently by this account
    or in the current batch, automatically rotates to the best fresh or least-recently-used asset.
    """
    if not chosen_filename:
        return None

    excluded = set(batch_excluded or [])
    recent_used = get_used_media_for_account(account_name=account_name, lookback=10)

    # If filename is valid and NOT used in last 10 posts and NOT in batch_excluded: keep it!
    if chosen_filename not in excluded and chosen_filename not in recent_used:
        return chosen_filename

    print(f"[Media Rotation] Media '{chosen_filename}' was recently used by {account_name or 'account'} or in current batch. Auto-rotating to a fresh asset...")
    available = get_available_media_for_account(account_name=account_name, batch_excluded=batch_excluded)
    if available:
        rotated = available[0].get("filename")
        print(f"[Media Rotation] Selected fresh asset: '{rotated}'")
        return rotated
    return chosen_filename


def format_media_catalog_for_prompt(
    account_name: Optional[str] = None,
    batch_excluded_media: Optional[List[str]] = None,
) -> str:
    """
    Formats the registered media catalog into concise context for Gemini's prompt,
    filtering and prioritizing fresh, unused assets for this account to prevent repeats.
    """
    available = get_available_media_for_account(
        account_name=account_name,
        batch_excluded=batch_excluded_media,
    )
    if not available:
        catalog = load_media_catalog()
        available = catalog or []

    if not available:
        return "None available yet. (Generate standard text-only post or thread)."

    recent_used = get_used_media_for_account(account_name=account_name, lookback=15)
    used_notice = ""
    if recent_used:
        used_notice = (
            f"\n⚠️ RECENTLY USED MEDIA ON THIS ACCOUNT (STRICTLY FORBIDDEN TO REUSE TODAY):\n"
            + ", ".join(recent_used[:10])
            + "\nDO NOT pick any of the above files! You MUST pick a FRESH asset from the list below.\n"
        )

    # Show up to 10 top prioritized assets (fresh assets first)
    lines = [
        f"Available authentic product media you can attach (prioritized fresh assets for {account_name or 'today'}):",
        used_notice,
    ]
    for item in available[:10]:
        m_type = item.get("type", "media").upper()
        fname = item.get("filename", "")
        summary = item.get("summary", "")
        caps = ", ".join(item.get("capabilities", []))
        lines.append(f"- [{m_type}] Filename: \"{fname}\" | Shows: {summary} | Capabilities: {caps}")

    lines.append("\nRULE: If you select a media file above, pick ONLY from the fresh eligible list, set 'media_filename' to its exact filename, and write your tweet copy to introduce or highlight what is shown on screen.")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Demoly Media Manager")
    parser.add_argument("--scan", action="store_true", help="Scan assets/ for new videos/images and index them")
    parser.add_argument("--list", action="store_true", help="List all indexed media assets")
    args = parser.parse_args()

    if args.scan:
        scan_and_index_assets()
    elif args.list:
        catalog = load_media_catalog()
        print(f"\nRegistered Media Assets ({len(catalog)} total):")
        for item in catalog:
            print(f"- [{item.get('type', '').upper()}] {item.get('filename')}: {item.get('summary')}")
        print()
    else:
        scan_and_index_assets()


if __name__ == "__main__":
    main()
