"""
ViralXXXPorn.com Media Scraper
===============================
Scrapes video metadata and direct URLs from viralxxxporn.com (KVS CMS).
"""

import re
import json
import time
import os
import logging
from dataclasses import dataclass, field, asdict
from typing import Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger("viralxscraper")

BASE_URL = "https://viralxxxporn.com"
IMG_CDN = "https://imgcdn.viralxxxporn.com"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

session = requests.Session()
session.headers.update(HEADERS)


# ──────────────────────────────────────────────────────────────────────
# Data Models
# ──────────────────────────────────────────────────────────────────────


@dataclass
class VideoPreview:
    """Video metadata from listing pages (model/search results)."""

    video_id: int
    title: str
    url: str
    duration: str = ""
    quality: str = ""
    thumbnail: str = ""
    views: str = ""
    rating: str = ""
    added: str = ""
    categories: list[str] = field(default_factory=list)
    models: list[str] = field(default_factory=list)

    def dict(self) -> dict:
        d = asdict(self)
        d["url"] = self.url  # keep full URL
        return d


@dataclass
class VideoDetail(VideoPreview):
    """Full video details extracted from the video page."""

    embed_url: str = ""
    direct_url: str = ""
    description: str = ""
    tags: list[str] = field(default_factory=list)
    screenshots: list[str] = field(default_factory=list)
    files: dict[str, str] = field(default_factory=dict)  # quality -> URL


@dataclass
class ModelInfo:
    """Model profile metadata."""

    name: str
    slug: str
    url: str
    rank: int = 0
    views: str = ""
    followers: str = ""
    country: str = ""
    age: str = ""
    height: str = ""
    weight: str = ""
    thumbnail: str = ""
    description: str = ""
    video_count: int = 0
    album_count: int = 0
    short_count: int = 0


# ──────────────────────────────────────────────────────────────────────
# HTTP Helpers
# ──────────────────────────────────────────────────────────────────────


def _get(url: str, retries: int = 3, delay: float = 2.0) -> requests.Response:
    """GET request with retry logic. Does NOT retry on 404 (not-found is permanent)."""
    for attempt in range(retries):
        try:
            resp = session.get(url, timeout=30)
            if resp.status_code == 200:
                return resp
            # 404 is permanent — don't retry
            if resp.status_code == 404:
                raise RuntimeError(f"Not found (404): {url}")
            logger.warning(
                "HTTP %d for %s (attempt %d/%d)",
                resp.status_code, url, attempt + 1, retries,
            )
        except requests.RequestException as e:
            logger.warning(
                "Request error for %s (attempt %d/%d): %s",
                url, attempt + 1, retries, e,
            )
        if attempt < retries - 1:
            time.sleep(delay * (attempt + 1))
    raise RuntimeError(f"Failed to fetch {url} after {retries} attempts")


def _safe_text(el, default: str = "") -> str:
    """Safely extract text from a BeautifulSoup element."""
    return el.get_text(strip=True) if el else default


# ──────────────────────────────────────────────────────────────────────
# Input Validation
# ──────────────────────────────────────────────────────────────────────


_SLUG_RE = re.compile(r'^[a-z0-9]+(?:-[a-z0-9]+)*$')


def validate_slug(slug: str) -> Optional[str]:
    """
    Validate a model slug. Returns None if valid, or an error message if invalid.
    Accepts: lowercase letters, digits, hyphens (e.g. 'mandy-rose', 'model123').
    Rejects: empty, uppercase, spaces, special chars, leading/trailing hyphens.
    """
    if not slug or not slug.strip():
        return "Slug cannot be empty"
    slug = slug.strip().lower()
    if not _SLUG_RE.match(slug):
        return "Invalid slug — use only lowercase letters, digits, and hyphens (e.g. 'mandy-rose')"
    if len(slug) < 2:
        return "Slug too short — at least 2 characters"
    return None


def _validate_slug(slug: str) -> None:
    """Raise ValueError if slug is invalid."""
    err = validate_slug(slug)
    if err:
        raise ValueError(err)


def _safe_attr(el, attr: str, default: str = "") -> str:
    """Safely extract an attribute from a BeautifulSoup element."""
    return el.get(attr, default) if el else default


# ──────────────────────────────────────────────────────────────────────
# Model Page Scraping
# ──────────────────────────────────────────────────────────────────────


def scrape_model(slug: str, max_pages: int = 0) -> list[VideoPreview]:
    """
    Scrape all videos from a model page.
    
    Args:
        slug: Model slug (e.g., 'mandy-rose')
        max_pages: Max pages to scrape (0 = all available)
    
    Returns:
        List of VideoPreview objects
    
    Raises:
        ValueError: If slug is empty or contains invalid characters
    """
    _validate_slug(slug)
    videos: list[VideoPreview] = []
    page = 1
    
    while True:
        if page == 1:
            url = f"{BASE_URL}/models/{slug}/"
        else:
            url = f"{BASE_URL}/models/{slug}/{page}/"
        
        logger.info("Scraping model page %d: %s", page, url)
        
        try:
            resp = _get(url)
            soup = BeautifulSoup(resp.text, "lxml")
            page_videos = _parse_video_list(soup)
            
            if not page_videos:
                logger.info("No more videos found on page %d", page)
                break
            
            videos.extend(page_videos)
            logger.info("Found %d videos on page %d (total: %d)", 
                        len(page_videos), page, len(videos))
            
            if max_pages and page >= max_pages:
                break
            
            # Check if there's a next page
            next_link = soup.select_one('.pagination a.vx-next')
            if not next_link and not _has_next_page(soup, slug, page):
                break
                
            page += 1
            time.sleep(1)  # polite delay
            
        except RuntimeError as e:
            logger.error("Error scraping page %d: %s", page, e)
            break
    
    return videos


def _has_next_page(soup: BeautifulSoup, slug: str, current_page: int) -> bool:
    """Check if a next page exists in pagination."""
    next_page = current_page + 1
    for a in soup.select(".pagination a"):
        href = a.get("href", "")
        if f"/{slug}/{next_page}/" in href:
            return True
    return False


def _parse_video_list(soup: BeautifulSoup) -> list[VideoPreview]:
    """Parse video items from a listing/result page."""
    videos = []
    seen_ids = set()
    
    # KVS typical structure: look for links to /video/
    for a in soup.select("a[href*='/video/']"):
        href = a["href"]
        # Only match video page URLs, not embed or other
        match = re.search(r'/video/(\d+)/', href)
        if not match:
            continue
        vid = int(match.group(1))
        if vid in seen_ids:
            continue
        seen_ids.add(vid)
        
        # Get title from the link
        title = a.get("title", "") or _safe_text(a)
        if not title or title == "VXP":
            # Try img alt text
            img = a.select_one("img")
            if img and img.get("alt"):
                title = img["alt"]
        
        # Try to get the parent container for more metadata
        container = a.find_parent("div", class_=re.compile(r"item|video|card|list-item"))
        if not container:
            container = a.parent
        
        duration = ""
        quality = ""
        thumbnail = ""
        views = ""
        
        if container:
            dur_el = container.select_one(".vx-duration, .duration, .video-duration, span.duration")
            duration = _safe_text(dur_el)
            qual_el = container.select_one(".vx-quality, .quality, .hd-label, .hd-mark")
            quality = _safe_text(qual_el)
            
            # Thumbnails use lazy loading: data-original or data-webp
            thumb_img = container.select_one("img")
            thumbnail = (_safe_attr(thumb_img, "data-original") or
                        _safe_attr(thumb_img, "data-webp") or 
                        _safe_attr(thumb_img, "data-src") or
                        _safe_attr(thumb_img, "src"))
            # Skip SVG placeholders
            if thumbnail.startswith("data:image/svg"):
                thumbnail = ""
            
            views_el = container.select_one(".vx-views, .views, .video-views, span.views")
            views = _safe_text(views_el)
        
        videos.append(VideoPreview(
            video_id=vid,
            title=title or f"Video {vid}",
            url=urljoin(BASE_URL, href),
            duration=duration,
            quality=quality,
            thumbnail=thumbnail,
            views=views,
        ))
    
    return videos


# ──────────────────────────────────────────────────────────────────────
# Video Detail Scraping
# ──────────────────────────────────────────────────────────────────────


def scrape_video(video_id_or_url: int | str) -> Optional[VideoDetail]:
    """
    Scrape full details for a single video.
    
    Accepts either a video_id (int) or a full video URL (str).
    If given an ID, requires the full URL path — KVS returns 404 for slug-less URLs.
    """
    if isinstance(video_id_or_url, int):
        # Can't build URL from ID alone — need at minimum the slug
        # Try common patterns
        slug = f"video-{video_id_or_url}"  # fallback slug
        url = f"{BASE_URL}/video/{video_id_or_url}/{slug}/"
    else:
        url = video_id_or_url
    
    match = re.search(r'/video/(\d+)/', url)
    if not match:
        raise ValueError(f"Not a valid video URL: {url}")
    
    video_id = int(match.group(1))
    logger.info("Scraping video: %s", url)
    
    try:
        resp = _get(url)
        if resp.status_code == 404 and isinstance(video_id_or_url, int):
            # Slug-less URL failed, we can't recover without more info
            logger.error("Video %d not found (slug needed)", video_id)
            return None
        if resp.status_code != 200:
            logger.error("Video page returned %d", resp.status_code)
            return None
        return _parse_video_detail(resp.text, video_id, url)
    except RuntimeError:
        return None


def _parse_video_detail(html: str, video_id: int, url: str) -> VideoDetail:
    """Parse video page HTML into VideoDetail."""
    soup = BeautifulSoup(html, "lxml")
    
    # ── Title ───────────────────────────────────────────────────────
    title_el = soup.select_one("h1")
    title = _safe_text(title_el) or f"Video {video_id}"
    
    # ── Metadata ────────────────────────────────────────────────────
    duration = ""
    quality = ""
    thumbnail = ""
    views = ""
    rating = ""
    description = ""
    added = ""
    categories: list[str] = []
    models: list[str] = []
    tags: list[str] = []
    screenshots: list[str] = []
    
    # Duration from meta tag
    dur_meta = soup.select_one('meta[property="video:duration"]')
    if dur_meta:
        try:
            seconds = int(dur_meta.get("content", "0"))
            minutes = seconds // 60
            secs = seconds % 60
            duration = f"{minutes}:{secs:02d}"
        except (ValueError, TypeError):
            pass
    
    # Views
    views_ul = soup.select_one("ul.vx-info-list")
    if views_ul:
        items = views_ul.select("li")
        if items:
            views = _safe_text(items[0])
    
    # Rating
    rating_match = re.search(r'rated\s+([\d.]+)/5', html, re.I)
    if rating_match:
        rating = rating_match.group(1)
    
    # Thumbnail
    thumb_img = soup.select_one("meta[property='og:image']") or \
                soup.select_one("img.vx-poster, .video-poster img")
    if thumb_img:
        thumbnail = thumb_img.get("content", "") or thumb_img.get("src", "")
    
    # Rating
    rating_el = soup.select_one(".vx-rating, .rating, [itemprop='ratingValue']")
    rating = _safe_text(rating_el)
    
    # Description
    desc_el = soup.select_one(".vx-description, .video-description, [itemprop='description']")
    description = _safe_text(desc_el)
    
    # Categories - only from the video-specific links, not nav menu
    cat_section = soup.select_one(".vx-categories, .video-categories, .kt-categories")
    if cat_section:
        for a in cat_section.select("a[href*='/categories/']"):
            cat = _safe_text(a)
            if cat and cat not in categories:
                categories.append(cat)
    # Fallback: JSON-LD genre
    if not categories:
        for script in soup.select('script[type="application/ld+json"]'):
            try:
                data = json.loads(script.string)
                if isinstance(data, dict):
                    graph = data.get("@graph", [data])
                    for item in graph if isinstance(graph, list) else [graph]:
                        if isinstance(item, dict) and "genre" in item:
                            genres = item["genre"]
                            if isinstance(genres, list):
                                categories = [g for g in genres if isinstance(g, str)]
                            break
            except (json.JSONDecodeError, AttributeError):
                pass
    
    # Models - only from video-specific links
    model_section = soup.select_one(".vx-models, .video-models, .kt-models")
    if model_section:
        for a in model_section.select("a[href*='/models/']"):
            model = _safe_text(a)
            if model and model not in models:
                models.append(model)
    # Fallback: JSON-LD actor
    if not models:
        for script in soup.select('script[type="application/ld+json"]'):
            try:
                data = json.loads(script.string)
                if isinstance(data, dict):
                    graph = data.get("@graph", [data])
                    for item in graph if isinstance(graph, list) else [graph]:
                        if isinstance(item, dict) and "actor" in item:
                            actors = item["actor"]
                            if isinstance(actors, list):
                                for actor in actors:
                                    if isinstance(actor, dict):
                                        models.append(actor.get("name", ""))
            except (json.JSONDecodeError, AttributeError):
                pass
    
    # Tags - from JSON-LD keywords
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.string)
            if isinstance(data, dict):
                graph = data.get("@graph", [data])
                for item in graph if isinstance(graph, list) else [graph]:
                    if isinstance(item, dict) and "keywords" in item:
                        kw = item["keywords"]
                        if isinstance(kw, list):
                            tags = [k for k in kw if isinstance(k, str)]
                        elif isinstance(kw, str):
                            tags = [kw]
                        break
        except (json.JSONDecodeError, AttributeError):
            pass
    if not tags:
        tag_section = soup.select_one(".vx-tags, .video-tags, .kt-tags")
        if tag_section:
            for a in tag_section.select("a[rel='tag'], a[href*='/tags/']"):
                tag = _safe_text(a)
                if tag:
                    tags.append(tag)
    
    # Screenshots
    for img in soup.select(".vx-screenshots img, .screenshots img, img[data-fancybox*='screenshots']"):
        src = img.get("src", "") or img.get("data-original", "")
        if src and "screenshot" in src.lower():
            screenshots.append(src)
    
    # ── Quality from title or meta ──────────────────────────────────
    qual_match = re.search(r'\b(\d{3,4}p)\b', title)
    if qual_match:
        quality = qual_match.group(1)
    
    # ── Video URLs from KVS player init ─────────────────────────────
    direct_url = ""
    file_urls: dict[str, str] = {}
    embed_url = f"{BASE_URL}/embed/{video_id}"
    
    # Extract flashvars from initKtPlayer function
    flashvars_match = re.search(
        r"function\s+initKtPlayer\(\)\s*\{[^}]*flashvars\s*=\s*\{([^}]+(?:{[^}]*}[^}]*)*)\};",
        html, re.S | re.I
    )
    
    if not flashvars_match:
        # Try broader match
        flashvars_match = re.search(
            r"flashvars\s*=\s*\{.*?video_url\s*:\s*'([^']*)'",
            html, re.S
        )
        if flashvars_match:
            direct_url = flashvars_match.group(1)
    else:
        flashvars_text = flashvars_match.group(1)
        
        # Extract video_url from flashvars
        url_match = re.search(r"video_url\s*:\s*'([^']*)'", flashvars_text)
        if url_match:
            direct_url = url_match.group(1)
        
        # Extract postfix for quality variants  
        postfix_match = re.search(r"postfix\s*:\s*'([^']*)'", flashvars_text)
        
        if direct_url:
            # Always include the original quality
            q_match = re.search(r'_(\d+p)\.mp4', direct_url)
            if q_match:
                file_urls[q_match.group(1)] = direct_url
            else:
                file_urls["original"] = direct_url
            
            # Generate all quality variants
            qualities = ["240p", "360p", "480p", "720p", "1080p", "1440p", "2160p"]
            for q in qualities:
                if q in file_urls:
                    continue
                # Replace any quality in the URL with the new one
                variant = re.sub(r'_\d+p\.mp4', f'_{q}.mp4', direct_url)
                if variant != direct_url:
                    file_urls[q] = variant
    
    # Also try JSON-LD for direct URL
    if not direct_url:
        jsonld_scripts = soup.select('script[type="application/ld+json"]')
        for script in jsonld_scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict):
                    graph = data.get("@graph", [data])
                    for item in graph if isinstance(graph, list) else [graph]:
                        content_url = item.get("contentUrl", "")
                        if content_url and ".mp4" in content_url:
                            direct_url = content_url
                            break
            except (json.JSONDecodeError, AttributeError):
                pass
    
    # If we have direct_url, also add it to files
    if direct_url and not file_urls:
        # Extract quality from URL
        q_match = re.search(r'_(\d+p)\.mp4', direct_url)
        if q_match:
            file_urls[q_match.group(1)] = direct_url
        else:
            file_urls["original"] = direct_url
    
    return VideoDetail(
        video_id=video_id,
        title=title,
        url=url,
        duration=duration,
        quality=quality,
        thumbnail=thumbnail,
        views=views,
        rating=rating,
        added=added,
        categories=categories,
        models=models,
        description=description,
        tags=tags,
        screenshots=screenshots,
        embed_url=embed_url,
        direct_url=direct_url,
        files=file_urls,
    )


# ──────────────────────────────────────────────────────────────────────
# Search
# ──────────────────────────────────────────────────────────────────────


def scrape_search(query: str, max_pages: int = 1) -> list[VideoPreview]:
    """
    Search for videos on viralxxxporn.com.
    
    Args:
        query: Search term
        max_pages: Maximum result pages to scrape
    
    Returns:
        List of VideoPreview objects
    """
    videos: list[VideoPreview] = []
    
    for page in range(1, max_pages + 1):
        if page == 1:
            url = f"{BASE_URL}/search/{requests.utils.quote(query)}/"
        else:
            url = f"{BASE_URL}/search/{requests.utils.quote(query)}/{page}/"
        
        logger.info("Search page %d: %s", page, url)
        
        try:
            resp = _get(url)
            soup = BeautifulSoup(resp.text, "lxml")
            page_videos = _parse_video_list(soup)
            
            if not page_videos:
                break
            
            videos.extend(page_videos)
            time.sleep(1)
            
        except RuntimeError as e:
            logger.error("Search error page %d: %s", page, e)
            break
    
    return videos


# ──────────────────────────────────────────────────────────────────────
# Model Info
# ──────────────────────────────────────────────────────────────────────


def scrape_model_info(slug: str) -> Optional[ModelInfo]:
    """Scrape model profile information."""
    _validate_slug(slug)
    url = f"{BASE_URL}/models/{slug}/"
    logger.info("Scraping model info: %s", url)
    
    try:
        resp = _get(url)
    except RuntimeError:
        return None
    
    soup = BeautifulSoup(resp.text, "lxml")
    
    # Name
    name_el = soup.select_one("h1")
    name = _safe_text(name_el)
    # Clean: "Model Ranked number 417 Mandy Rose (Mandy Sacs)" 
    # or just "#417Mandy Rose..." (span before text without space)
    name = re.sub(r'^(Model\s+Ranked\s+)?(number\s+)?#\d+\s*', '', name).strip()
    
    # Rank
    rank = 0
    rank_el = soup.select_one(".vx-model-rank, .model-rank")
    if rank_el:
        rank_match = re.search(r'(\d+)', _safe_text(rank_el))
        if rank_match:
            rank = int(rank_match.group(1))
    
    # Stats (views, followers)
    views = ""
    followers = ""
    stats_ul = soup.select_one("ul.vx-info-list")
    if stats_ul:
        items = stats_ul.select("li")
        if len(items) >= 1:
            views = _safe_text(items[0])
        if len(items) >= 2:
            followers = _safe_text(items[1])
    
    # Info fields (country, city, age, height, weight)
    country = ""
    city = ""
    age = ""
    height = ""
    weight = ""
    
    for li in soup.select("ul.vx-list li.vx-item"):
        spans = li.select("span")
        if len(spans) >= 2:
            key = _safe_text(spans[0]).rstrip(":").strip()
            val = _safe_text(spans[1])
            key_lower = key.lower()
            if key_lower == "country":
                country = val
            elif key_lower == "city":
                city = val
            elif key_lower == "age":
                age = val
            elif key_lower == "height":
                height = val
            elif key_lower == "weight":
                weight = val
    
    # Thumbnail
    thumb_img = soup.select_one("img.vx-model-avatar, .model-avatar img")
    thumbnail = _safe_attr(thumb_img, "src") or _safe_attr(thumb_img, "data-original", "")
    
    # Description
    desc_el = soup.select_one(".vx-model-description, .model-description")
    description = _safe_text(desc_el)
    
    # Count videos
    vid_count = 0
    for a in soup.select("a[href*='/models/']"):
        txt = _safe_text(a)
        if "video" in txt.lower():
            match = re.search(r'(\d+)', txt)
            if match:
                vid_count = max(vid_count, int(match.group(1)))
    
    return ModelInfo(
        name=name,
        slug=slug,
        url=url,
        rank=rank,
        views=views,
        followers=followers,
        country=country,
        age=age,
        height=height,
        weight=weight,
        thumbnail=thumbnail,
        description=description,
        video_count=vid_count,
    )


# ──────────────────────────────────────────────────────────────────────
# Latest / Trending
# ──────────────────────────────────────────────────────────────────────


def scrape_latest(max_pages: int = 1) -> list[VideoPreview]:
    """Scrape the latest videos."""
    return _scrape_listing(f"{BASE_URL}/latest-updates/", max_pages)


def scrape_top_rated(max_pages: int = 1) -> list[VideoPreview]:
    """Scrape top rated videos."""
    return _scrape_listing(f"{BASE_URL}/top-rated/", max_pages)


def scrape_most_viewed(max_pages: int = 1) -> list[VideoPreview]:
    """Scrape most viewed videos."""
    return _scrape_listing(f"{BASE_URL}/most-popular/", max_pages)


def _scrape_listing(base_url: str, max_pages: int) -> list[VideoPreview]:
    """Generic listing scraper."""
    videos: list[VideoPreview] = []
    
    for page in range(1, max_pages + 1):
        if page == 1:
            url = base_url
        else:
            url = f"{base_url}{page}/"
        
        logger.info("Scraping listing: %s", url)
        
        try:
            resp = _get(url)
            soup = BeautifulSoup(resp.text, "lxml")
            page_videos = _parse_video_list(soup)
            
            if not page_videos:
                break
            
            videos.extend(page_videos)
            time.sleep(1)
            
        except RuntimeError as e:
            logger.error("Listing error page %d: %s", page, e)
            break
    
    return videos


# ──────────────────────────────────────────────────────────────────────
# Download Helpers
# ──────────────────────────────────────────────────────────────────────


_DOWNLOAD_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://viralxxxporn.com/",
    "Accept": "*/*",
}


def download_file(
    url: str,
    dest: str,
    headers: Optional[dict] = None,
    progress_callback=None,
) -> str:
    """
    Download a file from url to dest with streaming + optional progress.
    
    Args:
        url: Source URL
        dest: Destination file path (directories created automatically)
        headers: Optional extra headers (merged with defaults)
        progress_callback: Optional fn(bytes_downloaded, total_bytes) called during download
    
    Returns:
        The destination path on success
    
    Raises:
        RuntimeError on HTTP failure
    """
    hdrs = dict(_DOWNLOAD_HEADERS)
    if headers:
        hdrs.update(headers)
    
    dest = os.path.abspath(dest)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    
    resp = requests.get(url, headers=hdrs, stream=True, timeout=60)
    if resp.status_code != 200:
        raise RuntimeError(f"Download failed: HTTP {resp.status_code} for {url}")
    
    total = int(resp.headers.get("Content-Length", 0))
    downloaded = 0
    
    with open(dest, "wb") as f:
        for chunk in resp.iter_content(chunk_size=1024 * 1024):  # 1MB chunks
            if chunk:
                f.write(chunk)
                downloaded += len(chunk)
                if progress_callback:
                    progress_callback(downloaded, total)
    
    return dest


def download_video(
    detail,
    output_dir: str,
    quality: Optional[str] = None,
    progress_callback=None,
) -> Optional[str]:
    """
    Download a video from a VideoDetail object.
    
    Args:
        detail: VideoDetail with direct_url and files
        output_dir: Directory to save to
        quality: Specific quality to download (e.g. '1080p'). Downloads best available if None.
        progress_callback: Optional progress fn(bytes_done, bytes_total)
    
    Returns:
        Path to downloaded file, or None if no URL available
    """
    if not detail.direct_url and not detail.files:
        return None
    
    # Pick the best quality available, or the requested one
    if quality and quality in detail.files:
        url = detail.files[quality]
    else:
        # Use the confirmed direct_url — generated variants may not exist on server
        url = detail.direct_url or (list(detail.files.values())[0] if detail.files else None)
        quality = quality or "source"
    
    if not url:
        return None
    
    # Sanitize filename
    safe_title = re.sub(r'[<>:"/\\|?*]', '_', detail.title)[:80]
    ext = ".mp4"
    fname = f"{detail.video_id}_{quality}_{safe_title}{ext}"
    dest = os.path.join(output_dir, fname)
    
    return download_file(url, dest, progress_callback=progress_callback)


def download_thumbnail(detail, output_dir: str, progress_callback=None) -> Optional[str]:
    """Download a video's thumbnail image."""
    if not detail.thumbnail or not detail.thumbnail.startswith("http"):
        return None
    safe_title = re.sub(r'[<>:"/\\|?*]', '_', detail.title)[:60]
    fname = f"{detail.video_id}_thumb_{safe_title}.jpg"
    dest = os.path.join(output_dir, fname)
    try:
        return download_file(detail.thumbnail, dest, progress_callback=progress_callback)
    except RuntimeError:
        return None


def download_all_videos(
    details: list,
    output_dir: str,
    quality: Optional[str] = None,
    progress_callback=None,
) -> list[str]:
    """Download videos from a list of VideoDetail objects. Returns list of downloaded paths."""
    downloaded = []
    for d in details:
        try:
            path = download_video(d, output_dir, quality=quality, 
                                 progress_callback=progress_callback)
            if path:
                downloaded.append(path)
        except RuntimeError as e:
            logger.error("Failed to download video %d: %s", d.video_id, e)
    return downloaded


def download_all_thumbnails(details: list, output_dir: str) -> list[str]:
    """Download thumbnails from a list of VideoDetail objects."""
    downloaded = []
    for d in details:
        path = download_thumbnail(d, output_dir)
        if path:
            downloaded.append(path)
    return downloaded
