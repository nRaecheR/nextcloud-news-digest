"""Download images from article body HTML and replace references with local paths."""

from __future__ import annotations

import hashlib
import logging
import re
import urllib.parse
from pathlib import Path

import requests

LOGGER = logging.getLogger("nextcloud-news-digest")

# Extension -> MIME type mapping
_EXTENSION_MIME: dict[str, str] = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".avif": "image/avif",
    ".bmp": "image/bmp",
}

# Regex: media file extension (case-insensitive)
_MEDIA_RE = re.compile(
    r"\.(?:jpe?g|png|gif|webp|svg|avif|bmp)", re.IGNORECASE
)

# Regex: empty <img> tag (no src attribute) — captures alt text
_EMPTY_IMG_RE = re.compile(
    r'<img\s+alt="([^"]*)"[^>]*/?>'
)

# Regex: <a> tag with href containing a media URL — captures the URL
_MEDIA_HREF_RE = re.compile(
    r'<a[^>]+href="([^"]*\.(?:jpe?g|png|gif|webp|svg|avif|bmp)[^"]*)"',
    re.IGNORECASE,
)

# Regex: <img> tag with src — captures the src URL
_IMG_SRC_RE = re.compile(
    r'<img[^>]+src="([^"]*)"'
)


def download_images(
    body_html: str,
    output_dir: Path,
    cache: dict[str, str] | None = None,
) -> list[dict[str, str]]:
    """Download images referenced in HTML body to the output directory.

    Handles two patterns:
    1. ``<img src="...">`` tags with direct media URLs.
    2. Empty ``<img alt="...">`` placeholders where the URL lives in a
       preceding ``<a href="...">`` tag.

    Parameters
    ----------
    body_html : str
        Raw HTML body content (before stripping).
    output_dir : Path
        Directory to write images into (``images/`` subdirectory).
    cache : dict, optional
        Shared dict mapping URL -> local filename for deduplication.

    Returns
    -------
    list[dict[str, str]]
        List of dicts with ``url``, ``local_path``, ``alt`` text.
    """
    if cache is None:
        cache = {}

    images_dir = output_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, str]] = []
    seen_urls: set[str] = set()

    # --- Pattern 1: <img src="..."> ---
    for match in _IMG_SRC_RE.finditer(body_html):
        url = match.group(1)
        if url in seen_urls:
            continue
        seen_urls.add(url)
        filename = _download_one_image(url, images_dir, cache)
        if filename:
            results.append({
                "url": url,
                "local_path": f"images/{filename}",
                "alt": "",
            })

    # --- Pattern 2: empty <img> with associated <a href="...media..."> ---
    # The URL can be in a preceding <a> tag or a following <a> tag.
    for img_match in _EMPTY_IMG_RE.finditer(body_html):
        alt_text = img_match.group(1)
        img_start = img_match.start()

        # Look at preceding text for a media URL in an <a> tag.
        preceding = body_html[:img_start]

        # Find media hrefs in preceding content, work backwards to find
        # the closest one before this img tag.
        candidates = list(_MEDIA_HREF_RE.finditer(preceding))
        url = None
        for href_match in reversed(candidates):
            if href_match.end() < img_start:
                # Check nothing between the href and the img tag
                between = preceding[href_match.end():img_start]
                if not _MEDIA_HREF_RE.search(between):
                    url = href_match.group(1)
                    break

        # If no preceding link, try following <a> tags (up to 3000 chars).
        if url is None:
            following = body_html[img_start:img_start + 3000]
            follow_candidates = list(_MEDIA_HREF_RE.finditer(following))
            for href_match in follow_candidates:
                # Check nothing between the img and the href
                between = following[:href_match.start()]
                if not _MEDIA_HREF_RE.search(between):
                    url = href_match.group(1)
                    break

        if url is None:
            continue

        if url in seen_urls:
            continue
        seen_urls.add(url)
        filename = _download_one_image(url, images_dir, cache)
        if filename:
            results.append({
                "url": url,
                "local_path": f"images/{filename}",
                "alt": alt_text,
            })

    return results


def _download_one_image(
    url: str, output_dir: Path, cache: dict[str, str]
) -> str | None:
    """Download a single image and return its filename.

    Returns None on failure. Uses a hash of the URL as the filename to
    avoid collisions and keep names short and safe.
    """
    if url in cache:
        return cache[url]

    # Resolve protocol-relative URLs (//example.com -> https://example.com)
    if url.startswith("//"):
        url = f"https:{url}"

    try:
        resp = requests.head(url, timeout=10, allow_redirects=True)
        if resp.status_code != 200:
            LOGGER.warning(
                "Image HEAD failed %s (status %d)", url, resp.status_code
            )
            return None

        content_type = resp.headers.get("Content-Type", "")
        if not content_type.startswith("image/"):
            return None

        # Try to get filename from Content-Disposition header
        filename = _filename_from_header(resp)
        if not filename:
            # Derive from URL path
            parsed = urllib.parse.urlparse(url)
            path = parsed.path
            if "/" in path:
                path = path.rsplit("/", 1)[-1]
            if path:
                filename = path

        if not filename or not _MEDIA_RE.search(filename):
            # Fallback: hash the URL
            digest = hashlib.md5(url.encode()).hexdigest()
            ext = _extension_from_mime(content_type) or ".jpg"
            filename = f"{digest}{ext}"

        local_path = output_dir / filename
        if not local_path.exists():
            resp_download = requests.get(url, timeout=15, stream=True)
            resp_download.raise_for_status()
            with open(local_path, "wb") as f:
                for chunk in resp_download.iter_content(chunk_size=8192):
                    f.write(chunk)

        cache[url] = filename
        return filename
    except Exception:
        LOGGER.warning("Failed to download image: %s", url)
        return None


def _filename_from_header(resp: requests.Response) -> str:
    """Extract filename from Content-Disposition header, or empty string."""
    cd = resp.headers.get("Content-Disposition", "")
    m = re.search(r'filename\*?="?([^";\n]+)"?', cd)
    if m:
        return m.group(1).strip().strip('"')
    return ""


def _extension_from_mime(mime_type: str) -> str:
    """Map MIME type to file extension."""
    for ext, mime in _EXTENSION_MIME.items():
        if mime in mime_type:
            return ext
    return ""


def replace_images_in_html(
    body_html: str,
    image_refs: list[dict[str, str]],
) -> str:
    """Replace image references in raw HTML with markdown image links.

    This runs BEFORE HTML stripping so the content becomes markdown
    image references that get handled by the strip_html function.

    Parameters
    ----------
    body_html : str
        Raw HTML body content.
    image_refs : list[dict]
        Results from ``download_images()``.

    Returns
    -------
    str
        HTML with image tags replaced by markdown image syntax.
    """
    if not image_refs:
        return body_html

    result = body_html

    for ref in image_refs:
        local_path = ref["local_path"]
        alt = ref["alt"]
        url = ref["url"]

        if alt:
            # Pattern 2: empty <img> + preceding <a> link
            # Replace the <img> tag with a markdown image link
            def _replace_empty_img(
                html: str, a: str, local: str
            ) -> str:
                pattern = r'<img\s+alt="' + re.escape(a) + r'"[^>]*/?>'
                m = re.search(pattern, html)
                if m:
                    return (html[:m.start()]
                            + f"![{a}]({local})"
                            + html[m.end():])
                return html

            result = _replace_empty_img(result, alt, local_path)

            # Remove the preceding <a> tag with the media URL
            url_escaped = re.escape(url)
            a_pattern = (
                r'<a[^>]+href="' + url_escaped + r'[^"]*"[^>]*>'
                r'[^<]*</a>'
                r'\s*<br\s*/?>\s*\n?'
            )
            result = re.sub(a_pattern, "", result)

        else:
            # Pattern 1: <img src="...">
            url_escaped = re.escape(url)
            src_pattern = r'<img[^>]+src="' + url_escaped + r'"[^>]*>'
            result = re.sub(
                src_pattern,
                f"![{alt}]({local_path})",
                result,
            )

    return result