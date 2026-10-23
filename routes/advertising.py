"""Developer-only advert studio and clean public campaign player.

Campaigns are stored as JSON in existing SystemSetting rows, so this feature does not
alter the Denmart schema or product/payment/stock tables. Compressed image data URLs
stay inside the database-backed campaign for reliable redeploys and backups.
"""
from __future__ import annotations

import base64
import json
import os
import re
import secrets
import subprocess
import tempfile
from pathlib import Path
from datetime import datetime, timezone
from functools import wraps
from io import BytesIO
from urllib.parse import quote

import qrcode
from flask import Blueprint, current_app, jsonify, redirect, render_template, request, send_file, url_for

from extensions import db
from flask_login import current_user
from models import SystemSetting, Product, ProductImage, StoreProduct, now
from services.product_images import product_image_sources, product_image_source, data_url_to_bytes, is_data_image_url, _local_static_image, real_product_image_url
from routes.dev_admin import _dev_ok, _business, _audit

bp = Blueprint("advertising", __name__)
CAMPAIGNS_KEY = "advert_campaigns"
PUBLISHED_KEY = "advert_published_campaign"
SCHEDULED_KEY = "advert_scheduled_campaigns"
THEMES = {"emerald", "midnight", "sunrise", "christmas", "school", "ocean", "plum"}


def default_campaign():
    return {
        "id": "denmart-welcome-2026",
        "name": "Welcome to Denmart Online",
        "theme": "emerald",
        "ticker": "WELCOME TO DENMART  •  EVERYDAY ESSENTIALS  •  ONLINE ORDERING OPENS 5 NOVEMBER 2026  •  DENMART.CO.KE",
        "website": "denmart.co.ke",
        "show_qr": True,
        "duration": 6,
        "schedule_enabled": False,
        "start_date": "",
        "end_date": "",
        "daily_start_time": "",
        "daily_end_time": "",
        "schedule_days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
        "priority": 0,
        "darken_screen": False,
        "overlay_opacity": 0.52,
        "flow_text_enabled": False,
        "flow_text": "",
        "media_asset_id": "",
        "media_name": "",
        "media_mime": "",
        "slides": [
            {"headline": "WELCOME TO DENMART ONLINE", "body": "Everyday essentials. A simpler way to shop.", "cta": "VISIT DENMART.CO.KE", "image_url": "", "image_urls": [], "show_qr": True, "duration": 6},
            {"headline": "THE THINGS YOUR HOME NEEDS", "body": "Discover groceries, laundry care, bathing essentials and everyday favourites in one convenient place.", "cta": "YOUR EVERYDAY STORE, ONLINE", "image_url": "", "image_urls": [], "show_qr": False, "duration": 6},
            {"headline": "WE'RE GETTING READY FOR YOU", "body": "Online ordering opens 5 November 2026.", "cta": "SAVE THE DATE  •  DENMART.CO.KE", "image_url": "", "image_urls": [], "show_qr": True, "duration": 7},
        ],
        "updated_at": "built-in-welcome-v1",
    }


def _setting(business_id, key, default=""):
    row = SystemSetting.query.filter_by(business_id=business_id, key=key).first()
    return row.value if row and row.value is not None else default


def _put_setting(business_id, key, value):
    row = SystemSetting.query.filter_by(business_id=business_id, key=key).first()
    if row is None:
        row = SystemSetting(business_id=business_id, key=key, value=value)
        db.session.add(row)
    else:
        row.value = value
        row.updated_at = now()
    return row


def _campaign_list(business_id):
    try:
        data = json.loads(_setting(business_id, CAMPAIGNS_KEY, "[]"))
        return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []
    except Exception:
        return []


def _published_campaign(business_id):
    try:
        raw = _setting(business_id, PUBLISHED_KEY, "")
        campaign = json.loads(raw) if raw else None
        if isinstance(campaign, dict) and isinstance(campaign.get("slides"), list) and campaign["slides"]:
            return campaign
    except Exception:
        current_app.logger.exception("Could not read published advertisement campaign")
    return default_campaign()


def _require_developer(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not _dev_ok():
            if request.path.startswith("/advertcontrol/api/"):
                return jsonify(ok=False, error="Your developer session has expired. Sign in again.", login_url=url_for("developer_admin.login", next="/advertcontrol")), 401
            return redirect(url_for("developer_admin.login", next="/advertcontrol"))
        return fn(*args, **kwargs)
    return wrapped


def _valid_campaign(raw):
    if not isinstance(raw, dict):
        raise ValueError("Campaign data is missing.")
    title = re.sub(r"\s+", " ", str(raw.get("name") or "Denmart advert")).strip()[:120]
    theme = str(raw.get("theme") or "emerald").lower()
    if theme not in THEMES:
        theme = "emerald"
    website = str(raw.get("website") or "denmart.co.ke").strip()[:160]
    ticker = re.sub(r"\s+", " ", str(raw.get("ticker") or "")).strip()[:260]
    slides_in = raw.get("slides")
    if not isinstance(slides_in, list) or not slides_in:
        raise ValueError("Add at least one scene to the advert.")
    if len(slides_in) > 8:
        raise ValueError("A campaign can contain up to 8 scenes.")
    slides = []
    def allowed_image(value):
        value = str(value or "").strip()
        return (not value or value.startswith(("data:image/", "https://", "http://", "/static/", "/product-photo/", "/advertisement/product-photo/")))
    for item in slides_in:
        if not isinstance(item, dict):
            continue
        image_url = str(item.get("image_url") or "").strip()
        image_urls_in = item.get("image_urls") if isinstance(item.get("image_urls"), list) else []
        image_urls = []
        for candidate in image_urls_in[:8]:
            candidate = str(candidate or "").strip()
            if not allowed_image(candidate):
                raise ValueError("Scene images must be real product photos, uploaded images, or HTTP(S) image URLs.")
            if candidate and candidate not in image_urls:
                image_urls.append(candidate[:620_000])
        if image_url and not allowed_image(image_url):
            raise ValueError("Scene images must be uploaded images or HTTP(S) URLs.")
        if image_url.startswith("data:image/") and len(image_url) > 600_000:
            raise ValueError("Each uploaded image must be compressed to 450 KB or smaller.")
        if image_url and image_url not in image_urls:
            image_urls.insert(0, image_url[:620_000])
        image_urls = image_urls[:8]
        slides.append({
            "headline": re.sub(r"\s+", " ", str(item.get("headline") or "Your everyday essentials")).strip()[:120],
            "body": re.sub(r"\s+", " ", str(item.get("body") or "")).strip()[:280],
            "cta": re.sub(r"\s+", " ", str(item.get("cta") or "SHOP ONLINE")).strip()[:100],
            "image_url": image_urls[0] if image_urls else image_url[:620_000],
            "image_urls": image_urls,
            "product_id": re.sub(r"[^A-Za-z0-9_-]", "", str(item.get("product_id") or ""))[:100],
            "product_name": re.sub(r"\s+", " ", str(item.get("product_name") or "")).strip()[:180],
            "show_qr": bool(item.get("show_qr", False)),
            "duration": max(3, min(15, int(item.get("duration") or 6))),
        })
    if not slides:
        raise ValueError("The campaign must contain at least one valid scene.")
    campaign_id = re.sub(r"[^a-zA-Z0-9_-]", "", str(raw.get("id") or ""))[:80] or secrets.token_urlsafe(10).replace("-", "").replace("_", "")
    daily_start_time = str(raw.get("daily_start_time") or "").strip()[:5]
    daily_end_time = str(raw.get("daily_end_time") or "").strip()[:5]
    for value in (daily_start_time, daily_end_time):
        if value:
            try:
                datetime.strptime(value, "%H:%M")
            except ValueError as exc:
                raise ValueError("Daily schedule times must use 24-hour HH:MM time.") from exc
    if bool(daily_start_time) != bool(daily_end_time):
        raise ValueError("Choose both a daily start time and end time, or leave both blank for all day.")
    valid_days = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}
    schedule_days = [str(day).lower()[:3] for day in raw.get("schedule_days", list(valid_days)) if str(day).lower()[:3] in valid_days] if isinstance(raw.get("schedule_days", list(valid_days)), list) else list(valid_days)
    if not schedule_days:
        raise ValueError("Select at least one day for the campaign schedule.")
    try:
        priority = max(-1000, min(1000, int(raw.get("priority") or 0)))
    except (TypeError, ValueError):
        priority = 0
    try:
        overlay_opacity = max(0.15, min(0.85, float(raw.get("overlay_opacity", 0.52))))
    except (TypeError, ValueError):
        overlay_opacity = 0.52
    media_asset_id = re.sub(r"[^a-zA-Z0-9_-]", "", str(raw.get("media_asset_id") or ""))[:80]
    campaign = {
        "id": campaign_id, "name": title or "Denmart advert", "theme": theme, "ticker": ticker,
        "website": website or "denmart.co.ke", "show_qr": bool(raw.get("show_qr", True)),
        "duration": max(3, min(15, int(raw.get("duration") or 6))),
        "schedule_enabled": bool(raw.get("schedule_enabled", False)),
        "start_date": str(raw.get("start_date") or "")[:10],
        "end_date": str(raw.get("end_date") or "")[:10],
        "daily_start_time": daily_start_time, "daily_end_time": daily_end_time,
        "schedule_days": list(dict.fromkeys(schedule_days)), "priority": priority,
        "darken_screen": bool(raw.get("darken_screen", False)),
        "overlay_opacity": overlay_opacity,
        "flow_text_enabled": bool(raw.get("flow_text_enabled", False)),
        "flow_text": re.sub(r"\s+", " ", str(raw.get("flow_text") or "")).strip()[:220],
        "media_asset_id": media_asset_id,
        "media_name": re.sub(r"[\\/\x00-\x1f]", "", str(raw.get("media_name") or ""))[:160],
        "media_mime": "video/mp4" if media_asset_id else "",
        "slides": slides, "updated_at": datetime.now(timezone.utc).isoformat()
    }
    for date_key in ("start_date", "end_date"):
        if campaign[date_key]:
            try:
                datetime.strptime(campaign[date_key], "%Y-%m-%d")
            except ValueError as exc:
                raise ValueError("Scheduled dates must use the date picker format.") from exc
    if campaign["schedule_enabled"] and not campaign["start_date"]:
        raise ValueError("Choose a start date before publishing a scheduled advert.")
    if campaign["start_date"] and campaign["end_date"] and campaign["end_date"] < campaign["start_date"]:
        raise ValueError("The end date cannot be earlier than the start date.")
    if len(json.dumps(campaign, separators=(",", ":"))) > 5_500_000:
        raise ValueError("This campaign is too large to store safely. Reduce the number or size of uploaded images.")
    return campaign


@bp.get("/advertcontrol")
@_require_developer
def studio():
    business = _business()
    if not business:
        return "No Denmart business database is configured.", 503
    campaigns = _campaign_list(business.id)
    published = _published_campaign(business.id)
    if not campaigns:
        campaigns = [default_campaign()]
    current = next((x for x in campaigns if x.get("id") == published.get("id")), campaigns[0])
    scheduled_ids = [str(item.get("id")) for item in _scheduled_campaigns(business.id)
                     if isinstance(item, dict) and item.get("id")]
    return render_template("advertising/studio.html", campaigns=campaigns, current_campaign=current,
                           published=published, scheduled_ids=scheduled_ids)


@bp.get("/advertcontrol/api/campaign/<campaign_id>")
@_require_developer
def load_campaign(campaign_id):
    business = _business()
    campaign = next((x for x in _campaign_list(business.id) if str(x.get("id")) == campaign_id), None) if business else None
    if not campaign and campaign_id == "denmart-welcome-2026":
        campaign = default_campaign()
    if not campaign:
        return jsonify(ok=False, error="Campaign not found."), 404
    return jsonify(ok=True, campaign=campaign)


@bp.get("/advertcontrol/api/products")
@_require_developer
def search_ad_products():
    """Search the real Denmart product database for the advertising studio."""
    query_text = " ".join(str(request.args.get("q") or "").split())[:120]
    query = Product.query.filter(Product.status == "ACTIVE")
    if query_text:
        pattern = "%" + query_text.replace("%", "\\%").replace("_", "\\_") + "%"
        query = query.filter(db.or_(Product.name.ilike(pattern), Product.brand.ilike(pattern), Product.barcode.ilike(pattern), Product.sku.ilike(pattern)))
    products = query.order_by(Product.name.asc()).limit(60).all()
    if not products and query_text:
        # Partial-token fallback still searches saved products only; it never invents
        # product names or package artwork.
        words = [word for word in query_text.split() if len(word) > 1][:3]
        if words:
            query = Product.query.filter(Product.status == "ACTIVE")
            for word in words:
                like = "%" + word + "%"
                query = query.filter(db.or_(Product.name.ilike(like), Product.brand.ilike(like)))
            products = query.order_by(Product.name.asc()).limit(40).all()
    product_ids = [p.id for p in products]
    gallery_rows = (ProductImage.query.filter(ProductImage.product_id.in_(product_ids))
                    .order_by(ProductImage.is_primary.desc(), ProductImage.sort_order, ProductImage.created_at).all()) if product_ids else []
    gallery = {}
    durable = {}
    for row in gallery_rows:
        if not row.image_url:
            continue
        target = durable if getattr(row, "source_type", "") == "denmart-offline-cache" else gallery
        target.setdefault(str(row.product_id), []).append(str(row.image_url).strip())
    # Let the saved feeder enrich selected product images when active. The saved local
    # product remains the source of names, SKUs, stock and price.
    store_rows = StoreProduct.query.filter(StoreProduct.product_id.in_(product_ids)).all() if product_ids else []
    if store_rows:
        business_id = getattr(getattr(store_rows[0], "store", None), "business_id", None)
        try:
            from services.catalogue_feeder import apply_online_feeder_overlay
            apply_online_feeder_overlay(store_rows, business_id)
        except Exception:
            current_app.logger.exception("Could not resolve product photos from the feeder for advert search")
    result = []
    for product in products:
        product._denmart_gallery_image_urls = gallery.get(str(product.id), [])
        product._denmart_durable_image_urls = durable.get(str(product.id), [])
        candidates = product_image_sources(product)
        image_urls = [f"/advertisement/product-photo/{quote(str(product.id), safe='')}/{i}.webp" for i in range(min(8, len(candidates)))]
        if not image_urls and str(product.barcode or "").strip():
            # The endpoint performs an exact-barcode image lookup on demand; do not
            # call an external API for every item on the search-results page.
            image_urls = [f"/advertisement/product-photo/{quote(str(product.id), safe='')}/0.webp"]
        result.append({"id": str(product.id), "name": product.name, "brand": product.brand or "",
                       "barcode": product.barcode or "", "sku": product.sku or "",
                       "image_urls": image_urls, "image_count": len(candidates),
                       "image_url": image_urls[0] if image_urls else ""})
    return jsonify(ok=True, items=result, count=len(result))


@bp.get("/advertisement/product-photo/<product_id>/<int:image_index>.webp")
def advertisement_product_photo(product_id, image_index):
    if image_index < 0 or image_index > 7:
        return ("", 404)
    product = _ad_product_with_gallery(product_id)
    if not product:
        return ("", 404)
    sources = product_image_sources(product)
    chosen = [sources[image_index]] if image_index < len(sources) else []
    from routes.shop import _try_product_image_sources
    response = _try_product_image_sources(product, chosen, cache_seconds=2592000)
    if not isinstance(response, tuple) and getattr(response, "status_code", 200) < 400:
        return response
    return _try_product_image_sources(product, list(getattr(product, "_denmart_durable_image_urls", []) or [])[:8], cache_seconds=2592000)


def _ad_product_with_gallery(product_id):
    product = db.session.get(Product, product_id)
    if not product or product.status != "ACTIVE":
        return None
    try:
        rows = ProductImage.query.filter_by(product_id=product.id).order_by(
            ProductImage.is_primary.desc(), ProductImage.sort_order, ProductImage.created_at).all()
        product._denmart_durable_image_urls = [str(row.image_url or "").strip() for row in rows if str(row.image_url or "").strip() and getattr(row, "source_type", "") == "denmart-offline-cache"]
        gallery = [str(row.image_url or "").strip() for row in rows if str(row.image_url or "").strip() and getattr(row, "source_type", "") != "denmart-offline-cache"]
        if gallery:
            product._denmart_saved_image_url = gallery[0]
            product._denmart_gallery_image_urls = gallery
    except Exception:
        current_app.logger.exception("Could not read product gallery for advertising")
    try:
        store_rows = StoreProduct.query.filter_by(product_id=product.id).all()
        if store_rows:
            from services.catalogue_feeder import apply_online_feeder_overlay
            business_id = getattr(getattr(store_rows[0], "store", None), "business_id", None)
            apply_online_feeder_overlay(store_rows, business_id)
    except Exception:
        current_app.logger.exception("Could not add supplier image to advertising gallery")
    return product


@bp.post("/advertcontrol/api/upload-video")
@_require_developer
def upload_ad_video():
    business = _business()
    if not business:
        return jsonify(ok=False, error="No Denmart database is configured."), 503
    upload = request.files.get("file")
    if not upload or not upload.filename:
        return jsonify(ok=False, error="Choose an MP4 video file first."), 400
    filename = re.sub(r"[^A-Za-z0-9._ -]", "", Path(upload.filename).name).strip()[:150] or "denmart-ad.mp4"
    if not filename.lower().endswith(".mp4"):
        return jsonify(ok=False, error="Upload a real MP4 video. The original file is preserved without re-encoding."), 400
    binary = upload.stream.read(20 * 1024 * 1024 + 1)
    if len(binary) > 20 * 1024 * 1024:
        return jsonify(ok=False, error="Keep the uploaded MP4 at 20 MB or smaller so publishing stays lightweight."), 413
    if len(binary) < 12 or binary[4:8] != b"ftyp":
        return jsonify(ok=False, error="This file does not look like a valid MP4. Choose an exported .mp4 video."), 400
    asset_id = secrets.token_urlsafe(18).replace("-", "").replace("_", "")[:32]
    value = json.dumps({"mime": "video/mp4", "filename": filename, "data": base64.b64encode(binary).decode("ascii")}, separators=(",", ":"))
    _put_setting(business.id, "advert_asset_" + asset_id, value)
    db.session.commit()
    return jsonify(ok=True, asset_id=asset_id, media_name=filename,
                   media_mime="video/mp4", media_url=f"/advertisement/media/{asset_id}",
                   message="MP4 uploaded. Denmart will play and download the original bytes without changing the video.")


@bp.get("/advertisement/media/<asset_id>")
def advertisement_media(asset_id):
    business = _business()
    asset_id = re.sub(r"[^a-zA-Z0-9_-]", "", str(asset_id or ""))[:80]
    raw = _setting(business.id, "advert_asset_" + asset_id, "") if business and asset_id else ""
    try:
        asset = json.loads(raw) if raw else {}
        binary = base64.b64decode(asset.get("data") or "", validate=True)
    except Exception:
        return ("", 404)
    if not binary or asset.get("mime") != "video/mp4":
        return ("", 404)
    download = request.args.get("download") == "1"
    filename = re.sub(r"[^A-Za-z0-9._ -]", "", Path(str(asset.get("filename") or "denmart-ad.mp4")).name)[:150] or "denmart-ad.mp4"
    response = send_file(BytesIO(binary), mimetype="video/mp4", as_attachment=download,
                         download_name=filename if download else None, conditional=True, max_age=31536000)
    response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    return response


@bp.post("/advertcontrol/api/export-mp4")
@_require_developer
def export_ad_mp4():
    upload = request.files.get("file")
    if not upload:
        return jsonify(ok=False, error="The recorded animation did not reach the MP4 exporter."), 400
    data = upload.stream.read(35 * 1024 * 1024 + 1)
    if len(data) > 35 * 1024 * 1024:
        return jsonify(ok=False, error="This recording is too large. Shorten the advert or use fewer/lighter images."), 413
    if not data:
        return jsonify(ok=False, error="The browser returned an empty video recording."), 400
    temp = tempfile.TemporaryDirectory(prefix="denmart-ad-mp4-")
    try:
        source = Path(temp.name) / "recording.webm"
        output = Path(temp.name) / "denmart-advert.mp4"
        source.write_bytes(data)
        try:
            import imageio_ffmpeg
            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            temp.cleanup()
            return jsonify(ok=False, error="The MP4 conversion component is not installed on this deployment. Redeploy the update so the MP4 exporter dependency is installed."), 503
        cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(source), "-an",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
               "-movflags", "+faststart", "-threads", "2", str(output)]
        done = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=100, check=False)
        if done.returncode != 0 or not output.exists() or output.stat().st_size < 1024:
            temp.cleanup()
            current_app.logger.warning("MP4 video export failed: %s", done.stderr.decode("utf-8", "replace")[-1000:])
            return jsonify(ok=False, error="MP4 conversion failed. The ad preview is unchanged; shorten the campaign or upload an already-exported MP4."), 422
        response = send_file(str(output), mimetype="video/mp4", as_attachment=True,
                             download_name="denmart-advert.mp4", conditional=True, max_age=0)
        response.call_on_close(temp.cleanup)
        response.headers["Cache-Control"] = "no-store"
        return response
    except subprocess.TimeoutExpired:
        temp.cleanup()
        return jsonify(ok=False, error="MP4 export exceeded the server's safe conversion limit. Shorten the ad and retry."), 408
    except Exception:
        temp.cleanup()
        current_app.logger.exception("Could not export Denmart advert as MP4")
        return jsonify(ok=False, error="The MP4 exporter could not finish. The campaign itself is still saved."), 500


@bp.post("/advertcontrol/api/save")
@_require_developer
def save_campaign():
    business = _business()
    if not business:
        return jsonify(ok=False, error="No Denmart database is configured."), 503
    payload = request.get_json(silent=True) or {}
    try:
        campaign = _valid_campaign(payload.get("campaign"))
        if campaign.get("media_asset_id") and not _setting(business.id, "advert_asset_" + campaign["media_asset_id"], ""):
            raise ValueError("The uploaded MP4 is no longer available. Upload it again before saving this campaign.")
        publish = bool(payload.get("publish"))
        live_campaign = _published_campaign(business.id) if publish and campaign.get("schedule_enabled") else None
        same_as_live = bool(live_campaign and str(campaign.get("id")) == str(live_campaign.get("id")))
        if same_as_live:
            # The live ad and its future update need separate IDs so the old
            # screen can remain live before the scheduled start date.
            campaign["id"] = (str(campaign["id"])[:55] + "-scheduled-" + secrets.token_hex(3))[:80]
        raw_campaigns = _campaign_list(business.id)
        if publish and campaign.get("schedule_enabled") and live_campaign:
            if same_as_live:
                # Restore the still-live snapshot in the library if a draft had
                # previously been saved with the same ID.
                found_live = False
                for index, existing in enumerate(raw_campaigns):
                    if str(existing.get("id")) == str(live_campaign.get("id")):
                        raw_campaigns[index] = live_campaign
                        found_live = True
                        break
                if not found_live:
                    raw_campaigns.append(live_campaign)
            elif not any(str(existing.get("id")) == str(live_campaign.get("id")) for existing in raw_campaigns):
                raw_campaigns.append(live_campaign)
        replaced = False
        for index, existing in enumerate(raw_campaigns):
            if str(existing.get("id")) == campaign["id"]:
                raw_campaigns[index] = campaign
                replaced = True
                break
        if not replaced:
            raw_campaigns.append(campaign)
        raw_campaigns = raw_campaigns[-25:]
        _put_setting(business.id, CAMPAIGNS_KEY, json.dumps(raw_campaigns, separators=(",", ":")))
        saved_ids = {str(item.get("id")) for item in raw_campaigns if isinstance(item, dict)}
        scheduled_campaigns = [item for item in _scheduled_campaigns(business.id)
                               if isinstance(item, dict) and str(item.get("id")) in saved_ids]
        if publish and campaign.get("schedule_enabled"):
            # A scheduled publication must not replace the live campaign before its
            # start date. Keep a separate published schedule list in SystemSetting.
            scheduled_campaigns = [x for x in scheduled_campaigns if str(x.get("id")) != campaign["id"]]
            scheduled_campaigns.append(campaign)
            _put_setting(business.id, SCHEDULED_KEY, json.dumps(scheduled_campaigns[-25:], separators=(",", ":")))
            message = "Campaign saved to the publishing schedule. The current advert stays live until this date window begins."
            audit_action = "ADVERT_CAMPAIGN_SCHEDULED"
        elif publish:
            _put_setting(business.id, PUBLISHED_KEY, json.dumps(campaign, separators=(",", ":")))
            # Immediate publication takes control of the screen now: cancel old
            # schedules already active today, while preserving future campaigns.
            today = _local_today()
            scheduled_campaigns = [x for x in scheduled_campaigns
                                   if str(x.get("id")) != campaign["id"] and not _within_schedule(x, today)]
            _put_setting(business.id, SCHEDULED_KEY, json.dumps(scheduled_campaigns, separators=(",", ":")))
            message = "Saved and published to the public ad screen."
            audit_action = "ADVERT_CAMPAIGN_PUBLISHED"
        else:
            message = "Draft saved. The public screen changes only when you publish."
            audit_action = "ADVERT_CAMPAIGN_SAVED"
        _audit(audit_action, campaign["id"],
               {"name": campaign["name"], "scenes": len(campaign["slides"]), "theme": campaign["theme"]})
        db.session.commit()
        return jsonify(ok=True, campaign=campaign, publish=publish, scheduled=bool(publish and campaign.get("schedule_enabled")), message=message)
    except Exception as exc:
        db.session.rollback()
        return jsonify(ok=False, error=str(exc)[:500]), 400


@bp.post("/advertcontrol/api/delete")
@_require_developer
def delete_campaign():
    business = _business()
    if not business:
        return jsonify(ok=False, error="No Denmart database is configured."), 503
    payload = request.get_json(silent=True) or {}
    campaign_id = str(payload.get("id") or "")[:80]
    campaigns = _campaign_list(business.id)
    campaign = next((x for x in campaigns if str(x.get("id")) == campaign_id), None)
    if not campaign:
        return jsonify(ok=False, error="Campaign not found."), 404
    if len(campaigns) <= 1:
        return jsonify(ok=False, error="Keep at least one saved campaign."), 400
    campaigns = [x for x in campaigns if str(x.get("id")) != campaign_id]
    _put_setting(business.id, CAMPAIGNS_KEY, json.dumps(campaigns, separators=(",", ":")))
    scheduled = [x for x in _scheduled_campaigns(business.id) if str(x.get("id")) != campaign_id]
    _put_setting(business.id, SCHEDULED_KEY, json.dumps(scheduled, separators=(",", ":")))
    published = _published_campaign(business.id)
    if published.get("id") == campaign_id:
        scheduled_ids = {str(item.get("id")) for item in scheduled}
        fallbacks = [item for item in campaigns if str(item.get("id")) not in scheduled_ids and not item.get("schedule_enabled")]
        replacement = fallbacks[0] if fallbacks else default_campaign()
        _put_setting(business.id, PUBLISHED_KEY, json.dumps(replacement, separators=(",", ":")))
    db.session.commit()
    return jsonify(ok=True, campaigns=campaigns)


def _local_now():
    try:
        from zoneinfo import ZoneInfo
        timezone_name = current_app.config.get("TIMEZONE", "Africa/Nairobi")
        return datetime.now(ZoneInfo(timezone_name))
    except Exception:
        return datetime.now(timezone.utc)


def _local_today():
    return _local_now().date().isoformat()


def _within_schedule(item, today, current_time=None, weekday=None):
    if not isinstance(item, dict) or not item.get("schedule_enabled"):
        return False
    start_date = str(item.get("start_date") or "")
    end_date = str(item.get("end_date") or "")
    if (start_date and today < start_date) or (end_date and today > end_date):
        return False
    # Legacy date-only checks used by the publish/cancel flow remain date-only.
    if current_time is None:
        return True
    day_names = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    allowed_days = item.get("schedule_days")
    if isinstance(allowed_days, list) and allowed_days and weekday is not None:
        if day_names[weekday % 7] not in {str(day).lower()[:3] for day in allowed_days}:
            return False
    start_time = str(item.get("daily_start_time") or "").strip()
    end_time = str(item.get("daily_end_time") or "").strip()
    if not start_time or not end_time:
        return True
    try:
        from datetime import time as clock_time
        start = clock_time.fromisoformat(start_time)
        end = clock_time.fromisoformat(end_time)
        now_time = current_time
        if start <= end:
            return start <= now_time < end
        # Support campaigns crossing midnight, e.g. 22:00–02:00.
        return now_time >= start or now_time < end
    except ValueError:
        return False


def _scheduled_campaigns(business_id):
    try:
        data = json.loads(_setting(business_id, SCHEDULED_KEY, "[]"))
        return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []
    except Exception:
        current_app.logger.exception("Could not read scheduled advertisement campaigns")
        return []


@bp.post("/advertcontrol/api/schedule/cancel")
@_require_developer
def cancel_schedule():
    business = _business()
    if not business:
        return jsonify(ok=False, error="No Denmart database is configured."), 503
    payload = request.get_json(silent=True) or {}
    campaign_id = str(payload.get("id") or "")[:80]
    scheduled = _scheduled_campaigns(business.id)
    filtered = [item for item in scheduled if str(item.get("id")) != campaign_id]
    if len(filtered) == len(scheduled):
        return jsonify(ok=False, error="That campaign is not in the publishing schedule."), 404
    _put_setting(business.id, SCHEDULED_KEY, json.dumps(filtered, separators=(",", ":")))
    # A cancelled schedule remains available as a normal draft, rather than
    # reopening with a checked schedule box that no longer exists.
    campaigns = _campaign_list(business.id)
    for item in campaigns:
        if str(item.get("id")) == campaign_id:
            item["schedule_enabled"] = False
            break
    _put_setting(business.id, CAMPAIGNS_KEY, json.dumps(campaigns, separators=(",", ":")))
    _audit("ADVERT_CAMPAIGN_SCHEDULE_CANCELLED", campaign_id, {})
    db.session.commit()
    return jsonify(ok=True, scheduled_ids=[str(item.get("id")) for item in filtered])


def _campaign_for_public():
    business = _business()
    if not business:
        return default_campaign()
    # The immediately published campaign is the fallback, including before/after
    # a scheduled campaign's window. A scheduled ad can never blank the screen.
    fallback = _published_campaign(business.id)
    local_now = _local_now()
    today = local_now.date().isoformat()

    active = []
    for item in _scheduled_campaigns(business.id):
        if _within_schedule(item, today, local_now.time(), local_now.weekday()):
            active.append(item)
    if active:
        # Higher priority wins for overlapping time windows; recency breaks ties.
        active.sort(key=lambda item: (int(item.get("priority") or 0), str(item.get("updated_at") or "")), reverse=True)
        return active[0]
    return fallback


@bp.get("/advertisement/current.json")
def current_public_campaign():
    response = current_app.response_class(json.dumps({"campaign": _campaign_for_public()}), mimetype="application/json")
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return response


@bp.get("/advertisement")
@bp.get("/advertisement/screen")
def public_screen():
    campaign = _campaign_for_public()
    response = current_app.make_response(render_template("advertising/screen.html", campaign=campaign))
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    return response


@bp.get("/advertisement/qr.png")
def advertisement_qr():
    # Use the canonical public origin when configured; otherwise encode this request's
    # host so local/test deployments still get a useful, scannable code.
    base = (current_app.config.get("PUBLIC_BASE_URL") or request.url_root).rstrip("/")
    target = base + "/shop"
    image = qrcode.make(target)
    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    output.seek(0)
    return send_file(output, mimetype="image/png", max_age=3600)
