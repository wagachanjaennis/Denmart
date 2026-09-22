"""Deterministic, local-first catalogue image helpers.

The public storefront must never search the internet for a product image while a
customer is browsing.  Images are prepared once by scripts/prepare_catalogue_images.py
and the product row stores the exact local URL it should use.
"""

from pathlib import Path
import base64
import hashlib
import mimetypes
import re
from urllib.parse import urlparse

from flask import current_app


LOCAL_PREFIX = "/static/catalogue/products/"
LOCAL_DIRNAME = "catalogue/products"


def local_product_image_url(product_id: str, ext: str = "webp") -> str:
    """Return the stable same-origin URL for one product's cached image."""
    safe_id = re.sub(r"[^A-Za-z0-9_-]", "", str(product_id or ""))
    return f"{LOCAL_PREFIX}{safe_id}.{ext}" if safe_id else ""


def local_product_image_path(product_id: str, ext: str = "webp") -> Path:
    return Path(current_app.static_folder) / LOCAL_DIRNAME / f"{re.sub(r'[^A-Za-z0-9_-]', '', str(product_id or ''))}.{ext}"


def is_local_image_url(url: str) -> bool:
    return str(url or "").strip().startswith(LOCAL_PREFIX)


def local_path_from_url(url: str) -> Path | None:
    raw = str(url or "").strip()
    if not raw.startswith(LOCAL_PREFIX):
        return None
    relative = raw[len("/static/"):].lstrip("/")
    candidate = Path(current_app.static_folder) / relative
    root = (Path(current_app.static_folder) / LOCAL_DIRNAME).resolve()
    try:
        resolved = candidate.resolve()
        if resolved.parent != root:
            return None
        return resolved
    except Exception:
        return None


def data_url_to_bytes(url: str):
    raw = str(url or "").strip()
    if not raw.startswith("data:image/") or "," not in raw:
        return None
    header, encoded = raw.split(",", 1)
    try:
        binary = base64.b64decode(encoded)
    except Exception:
        return None
    mime = header.split(";", 1)[0].replace("data:", "").strip().lower() or "image/png"
    return binary, mime


def image_content_type(path: Path) -> str:
    return mimetypes.guess_type(path.name)[0] or "image/webp"


def content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def looks_like_remote_url(url: str) -> bool:
    parsed = urlparse(str(url or "").strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
