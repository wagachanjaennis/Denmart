"""Online-only barcode/image feeder with a database-backed cache.

The feeder never creates, updates, deletes, or reprices Product/StoreProduct rows.
All POS and offline catalogue endpoints continue to use the merchant's own database.
"""
from __future__ import annotations

import ipaddress
import json
import re
import socket
import time
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import requests
from flask import current_app
from extensions import db
from models import Business, Product, SystemSetting, now

CONFIG_KEY = "catalogue_feeder_config"
CACHE_KEY = "catalogue_feeder_cache"
STATUS_KEY = "catalogue_feeder_status"
MODE_KEY = "catalogue_feeder_mode"
OVERRIDES_KEY = "catalogue_feeder_local_overrides"
ACTIVATED_KEY = "catalogue_feeder_activated_at"
AUTO_REFRESH_SECONDS = 15 * 60
_AUTO_ATTEMPTS: dict[str, float] = {}

DEFAULT_CONFIG = {
    "endpoint_url": "",
    "auth_type": "none",
    "header_name": "X-API-Key",
    "token": "",
    "items_path": "products",
    "barcode_field": "barcode",
    "image_field": "image_url",
    "sku_field": "sku",
    "name_field": "name",
    "auto_refresh": True,
}


def _setting(business_id: str, key: str, default=""):
    if not business_id:
        return default
    row = SystemSetting.query.filter_by(business_id=business_id, key=key).first()
    return row.value if row and row.value is not None else default


def _put_setting(business_id: str, key: str, value: str):
    row = SystemSetting.query.filter_by(business_id=business_id, key=key).first()
    if row is None:
        row = SystemSetting(business_id=business_id, key=key, value=value)
        db.session.add(row)
    else:
        row.value = value
        row.updated_at = now()
    return row


def primary_business():
    return Business.query.order_by(Business.created_at).first()


def _json_setting(business_id: str, key: str, fallback):
    raw = _setting(business_id, key, "")
    if not raw:
        return fallback
    try:
        value = json.loads(raw)
        return value if isinstance(value, type(fallback)) else fallback
    except (TypeError, ValueError):
        return fallback


def get_mode(business_id: str) -> str:
    value = str(_setting(business_id, MODE_KEY, "current") or "current").lower()
    return value if value in {"current", "api"} else "current"


def get_config(business_id: str) -> dict:
    stored = _json_setting(business_id, CONFIG_KEY, {})
    result = dict(DEFAULT_CONFIG)
    result.update({k: v for k, v in stored.items() if k in result})
    # Don't let malformed JSON turn a form value into a complex object.
    for key in ("endpoint_url", "auth_type", "header_name", "token", "items_path", "barcode_field", "image_field", "sku_field", "name_field"):
        result[key] = str(result.get(key) or "").strip()
    result["auth_type"] = result["auth_type"] if result["auth_type"] in {"none", "bearer", "header"} else "none"
    result["header_name"] = result["header_name"] or "X-API-Key"
    result["auto_refresh"] = bool(result.get("auto_refresh", True))
    return result


def get_cache(business_id: str) -> dict:
    return _json_setting(business_id, CACHE_KEY, {"rows": [], "fetched_at": None})


def get_status(business_id: str) -> dict:
    return _json_setting(business_id, STATUS_KEY, {})


def get_overrides(business_id: str) -> set[str]:
    values = _json_setting(business_id, OVERRIDES_KEY, [])
    return {str(x) for x in values if x}


def mark_local_override(business_id: str, product_id: str):
    """Keep an explicitly admin-created/edited product on its local image + barcode."""
    if not business_id or not product_id:
        return
    values = get_overrides(business_id)
    values.add(str(product_id))
    _put_setting(business_id, OVERRIDES_KEY, json.dumps(sorted(values), separators=(",", ":")))


def mark_local_override_many(business_id: str, product_ids):
    values = get_overrides(business_id)
    values.update(str(x) for x in product_ids if x)
    if business_id and values:
        _put_setting(business_id, OVERRIDES_KEY, json.dumps(sorted(values), separators=(",", ":")))


def normalize_identity(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


def _read_path(obj, path):
    """Read dotted JSON paths such as data.items and list paths such as images[0].url."""
    path = str(path or "").strip()
    if not path:
        return obj
    value = obj
    path = re.sub(r"\[(\d+)\]", r".\1", path)
    for part in path.split("."):
        if not part:
            return None
        if isinstance(value, dict):
            value = value.get(part)
        elif isinstance(value, list) and part.isdigit():
            index = int(part)
            value = value[index] if 0 <= index < len(value) else None
        else:
            return None
    return value


def _validate_endpoint(url: str, *, resolve_host: bool = True):
    parsed = urlparse(str(url or "").strip())
    if parsed.scheme not in {"https", "http"} or not parsed.hostname:
        raise ValueError("Enter a valid http:// or https:// API endpoint URL.")
    if parsed.username or parsed.password:
        raise ValueError("Put API credentials in the authentication fields, not inside the URL.")
    host = parsed.hostname.strip("[]").lower()
    if host in {"localhost", "localhost.localdomain"} or host.endswith((".local", ".internal", ".localhost")):
        raise ValueError("Private/local network API addresses are blocked for safety.")
    try:
        address = ipaddress.ip_address(host)
        if not address.is_global:
            raise ValueError("The API URL must use a public server address.")
    except ValueError as exc:
        # A non-IP hostname also raises ValueError; only propagate our policy error.
        if "public server address" in str(exc):
            raise
    except Exception:
        pass
    # Resolve hostnames before a live fetch to reject DNS names pointing at private
    # infrastructure. Saving a configuration only checks syntax so a temporarily
    # offline provider can be configured and diagnosed from the admin panel.
    if resolve_host:
        try:
            addresses = {entry[4][0] for entry in socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)}
            for raw in addresses:
                if not ipaddress.ip_address(raw).is_global:
                    raise ValueError("The API host resolves to a private address and is blocked.")
        except socket.gaierror:
            raise ValueError("The API host could not be resolved. Check the URL and try again.")
        except ValueError as exc:
            if "private address" in str(exc):
                raise
    return parsed


def save_config(business_id: str, incoming: dict):
    old = get_config(business_id)
    config = dict(DEFAULT_CONFIG)
    for key in config:
        if key in incoming:
            config[key] = incoming[key]
    config["endpoint_url"] = str(config.get("endpoint_url") or "").strip()
    for key in ("items_path", "barcode_field", "image_field", "sku_field", "name_field"):
        config[key] = str(config.get(key) or "").strip()
    config["auth_type"] = str(config.get("auth_type") or "none").lower()
    if config["auth_type"] not in {"none", "bearer", "header"}:
        raise ValueError("Choose a supported authentication method.")
    config["header_name"] = str(config.get("header_name") or "X-API-Key").strip()[:100]
    if not config.get("token"):
        config["token"] = old.get("token", "")
    else:
        config["token"] = str(config["token"]).strip()
    config["auto_refresh"] = str(config.get("auto_refresh", "1")).lower() not in {"0", "false", "off", ""}
    if config["endpoint_url"]:
        parsed = _validate_endpoint(config["endpoint_url"], resolve_host=False)
        if config.get("token") and config["auth_type"] != "none" and parsed.scheme != "https":
            raise ValueError("Use an HTTPS API endpoint when sending an API token or key.")
    elif config["auth_type"] != "none" or config["token"]:
        raise ValueError("Enter the API endpoint URL first.")
    if len(config["token"]) > 2000:
        raise ValueError("The API key/token is too long.")
    _put_setting(business_id, CONFIG_KEY, json.dumps(config, separators=(",", ":")))
    db.session.commit()
    return config


def _request_headers(config):
    headers = {"Accept": "application/json", "User-Agent": "DenmartCatalogueFeeder/1.0"}
    token = config.get("token", "")
    if token and config.get("auth_type") == "bearer":
        headers["Authorization"] = "Bearer " + token
    elif token and config.get("auth_type") == "header":
        header_name = str(config.get("header_name") or "X-API-Key").strip()
        if not re.fullmatch(r"[A-Za-z0-9-]{1,100}", header_name):
            raise ValueError("The custom API header name contains unsupported characters.")
        if header_name.lower() not in {"host", "content-length", "connection", "cookie", "set-cookie", "proxy-authorization"}:
            headers[header_name] = token
        else:
            raise ValueError("That header name is not allowed. Use X-API-Key or Authorization.")
    return headers


def _normalized_rows(payload, config):
    raw_rows = _read_path(payload, config.get("items_path", "products"))
    if isinstance(payload, list) and config.get("items_path") in {"", "products"}:
        raw_rows = payload
    if not isinstance(raw_rows, list):
        raise ValueError("The API responded, but its product list was not found. Check the JSON list path (for example: data.products).")
    if not raw_rows:
        raise ValueError("The API returned an empty product list. Existing Denmart data was kept unchanged.")
    rows = []
    for raw in raw_rows[:5000]:
        if not isinstance(raw, dict):
            continue
        barcode = _read_path(raw, config.get("barcode_field", "barcode"))
        image = _read_path(raw, config.get("image_field", "image_url"))
        sku = _read_path(raw, config.get("sku_field", "sku"))
        name = _read_path(raw, config.get("name_field", "name"))
        if isinstance(image, dict):
            image = image.get("url") or image.get("src") or image.get("front") or ""
        if isinstance(image, list):
            image = image[0] if image else ""
            if isinstance(image, dict):
                image = image.get("url") or image.get("src") or ""
        image = str(image or "").strip()
        if image.startswith("/") and config.get("endpoint_url"):
            image = urljoin(config["endpoint_url"], image)
        parsed_image = urlparse(image) if image else None
        if image and not (parsed_image and parsed_image.scheme in {"http", "https"} and parsed_image.netloc):
            image = ""
        row = {
            "barcode": re.sub(r"\s+", "", str(barcode or "")).strip()[:80],
            "image_url": image[:3000],
            "sku": str(sku or "").strip()[:80],
            "name": re.sub(r"\s+", " ", str(name or "")).strip()[:240],
        }
        if row["barcode"] or row["sku"] or row["name"]:
            rows.append(row)
    if not rows:
        raise ValueError("The API product list has no records with a barcode, SKU or product name. Check your field mappings.")
    return rows


def sync_feeder(business_id: str, *, timeout=(3.0, 12.0)) -> dict:
    config = get_config(business_id)
    started = datetime.now(timezone.utc).isoformat()
    try:
        if not config.get("endpoint_url"):
            raise ValueError("Save the API endpoint URL before testing the connection.")
        parsed_endpoint = _validate_endpoint(config["endpoint_url"])
        if config.get("token") and config["auth_type"] != "none" and parsed_endpoint.scheme != "https":
            raise ValueError("Use an HTTPS API endpoint when sending an API token or key.")
        response = requests.get(config["endpoint_url"], headers=_request_headers(config), timeout=timeout, allow_redirects=False, stream=True)
        try:
            if 300 <= response.status_code < 400:
                raise ValueError("The API returned a redirect. Enter its final HTTPS endpoint URL directly.")
            response.raise_for_status()
            max_bytes = 15 * 1024 * 1024
            chunks, total = [], 0
            for chunk in response.iter_content(chunk_size=128 * 1024):
                if not chunk:
                    continue
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError("The API response is larger than 15 MB. Use a paginated or catalogue-only feed endpoint.")
                chunks.append(chunk)
            body = b"".join(chunks)
            try:
                payload = json.loads(body.decode(response.encoding or "utf-8"))
            except Exception as exc:
                raise ValueError("The API response was not valid JSON. Use the API's JSON endpoint.") from exc
        finally:
            response.close()
        rows = _normalized_rows(payload, config)
        fetched = datetime.now(timezone.utc).isoformat()
        cache = {"rows": rows, "fetched_at": fetched, "source_url": config["endpoint_url"][:500]}
        _put_setting(business_id, CACHE_KEY, json.dumps(cache, separators=(",", ":")))
        status = {"ok": True, "message": f"Connected and cached {len(rows):,} catalogue records.", "count": len(rows), "last_success": fetched, "last_attempt": started, "last_error": ""}
        _put_setting(business_id, STATUS_KEY, json.dumps(status, separators=(",", ":")))
        db.session.commit()
        return status
    except Exception as exc:
        db.session.rollback()
        previous = get_status(business_id)
        status = {"ok": False, "message": str(exc)[:500], "count": len(get_cache(business_id).get("rows") or []),
                  "last_success": previous.get("last_success"), "last_attempt": started, "last_error": str(exc)[:500]}
        _put_setting(business_id, STATUS_KEY, json.dumps(status, separators=(",", ":")))
        db.session.commit()
        current_app.logger.warning("Catalogue feeder sync failed: %s", str(exc)[:500])
        return status


def _maybe_refresh(business_id: str):
    config = get_config(business_id)
    if not config.get("auto_refresh") or not config.get("endpoint_url"):
        return
    cache = get_cache(business_id)
    fetched_at = cache.get("fetched_at")
    expired = True
    if fetched_at:
        try:
            stamp = datetime.fromisoformat(str(fetched_at).replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            expired = (datetime.now(timezone.utc) - stamp).total_seconds() > AUTO_REFRESH_SECONDS
        except Exception:
            expired = True
    if not expired:
        return
    last_attempt = _AUTO_ATTEMPTS.get(business_id, 0)
    if time.time() - last_attempt < 120:
        return
    _AUTO_ATTEMPTS[business_id] = time.time()
    # Public requests use a short bounded timeout and continue rendering with the
    # previous cache if the supplier API is slow or offline.
    sync_feeder(business_id, timeout=(1.5, 3.5))


def apply_online_feeder_overlay(rows, business_id: str | None):
    """Attach request-only display values to StoreProduct relationships for online pages."""
    if not business_id or not rows or get_mode(business_id) != "api":
        return rows
    try:
        _maybe_refresh(business_id)
        cache = get_cache(business_id)
        feed_rows = cache.get("rows") if isinstance(cache.get("rows"), list) else []
        overrides = get_overrides(business_id)
        by_sku, by_name, by_barcode = {}, {}, {}
        for feed in feed_rows:
            sku = normalize_identity(feed.get("sku"))
            name = normalize_identity(feed.get("name"))
            barcode = re.sub(r"\s+", "", str(feed.get("barcode") or "")).strip()
            if sku:
                by_sku.setdefault(sku, feed)
            if name:
                by_name.setdefault(name, feed)
            if barcode:
                by_barcode.setdefault(barcode, feed)
        seen = set()
        for item in rows:
            product = getattr(item, "product", None)
            if not product or product.id in seen:
                continue
            seen.add(product.id)
            if str(product.id) in overrides:
                continue
            product._denmart_online_feeder_active = True
            product._denmart_online_barcode = ""
            product._denmart_online_image_url = ""
            match = None
            sku = normalize_identity(getattr(product, "sku", ""))
            name = normalize_identity(getattr(product, "name", ""))
            barcode = re.sub(r"\s+", "", str(getattr(product, "barcode", "") or "")).strip()
            if sku:
                match = by_sku.get(sku)
            if not match and name:
                match = by_name.get(name)
            if not match and barcode:
                match = by_barcode.get(barcode)
            if match:
                product._denmart_online_barcode = str(match.get("barcode") or "")
                product._denmart_online_image_url = str(match.get("image_url") or "")
        return rows
    except Exception:
        current_app.logger.exception("Could not apply online barcode/image feeder overlay")
        return rows


def online_barcode(product) -> str:
    if bool(getattr(product, "_denmart_online_feeder_active", False)):
        return str(getattr(product, "_denmart_online_barcode", "") or "")
    return str(getattr(product, "barcode", "") or "")


def feeder_summary(business_id: str) -> dict:
    config = get_config(business_id)
    cache = get_cache(business_id)
    status = get_status(business_id)
    rows = cache.get("rows") if isinstance(cache.get("rows"), list) else []
    try:
        local_products = Product.query.filter_by(status="ACTIVE").all()
        local_count = len(local_products)
        local_barcodes = sum(1 for product in local_products if str(product.barcode or "").strip())
    except Exception:
        local_count = local_barcodes = 0
    return {
        "mode": get_mode(business_id),
        "config": config,
        "status": status,
        "count": len(rows),
        "feed_barcodes": sum(1 for row in rows if str(row.get("barcode") or "").strip()),
        "feed_images": sum(1 for row in rows if str(row.get("image_url") or "").strip()),
        "local_products": local_count,
        "local_barcodes": local_barcodes,
        "fetched_at": cache.get("fetched_at"),
        "endpoint_host": urlparse(config.get("endpoint_url") or "").hostname or "Not configured",
        "has_token": bool(config.get("token")),
    }
