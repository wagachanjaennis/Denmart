"""Developer-only advert studio and clean public campaign player.

Campaigns are stored as JSON in existing SystemSetting rows, so this feature does not
alter the Denmart schema or product/payment/stock tables. Compressed image data URLs
stay inside the database-backed campaign for reliable redeploys and backups.
"""
from __future__ import annotations

import json
import re
import secrets
from datetime import datetime, timezone
from functools import wraps
from io import BytesIO

import qrcode
from flask import Blueprint, current_app, jsonify, redirect, render_template, request, send_file, url_for

from extensions import db
from flask_login import current_user
from models import SystemSetting, now
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
        "slides": [
            {"headline": "WELCOME TO DENMART ONLINE", "body": "Everyday essentials. A simpler way to shop.", "cta": "VISIT DENMART.CO.KE", "image_url": "", "show_qr": True, "duration": 6},
            {"headline": "THE THINGS YOUR HOME NEEDS", "body": "Discover groceries, laundry care, bathing essentials and everyday favourites in one convenient place.", "cta": "YOUR EVERYDAY STORE, ONLINE", "image_url": "", "show_qr": False, "duration": 6},
            {"headline": "WE'RE GETTING READY FOR YOU", "body": "Online ordering opens 5 November 2026.", "cta": "SAVE THE DATE  •  DENMART.CO.KE", "image_url": "", "show_qr": True, "duration": 7},
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
    for item in slides_in:
        if not isinstance(item, dict):
            continue
        image_url = str(item.get("image_url") or "").strip()
        if image_url and not (image_url.startswith("data:image/") or image_url.startswith("https://") or image_url.startswith("http://")):
            raise ValueError("Scene images must be uploaded images or HTTP(S) URLs.")
        if image_url.startswith("data:image/") and len(image_url) > 600_000:
            raise ValueError("Each uploaded image must be compressed to 450 KB or smaller.")
        slides.append({
            "headline": re.sub(r"\s+", " ", str(item.get("headline") or "Your everyday essentials")).strip()[:120],
            "body": re.sub(r"\s+", " ", str(item.get("body") or "")).strip()[:280],
            "cta": re.sub(r"\s+", " ", str(item.get("cta") or "SHOP ONLINE")).strip()[:100],
            "image_url": image_url[:620_000],
            "show_qr": bool(item.get("show_qr", False)),
            "duration": max(3, min(15, int(item.get("duration") or 6))),
        })
    if not slides:
        raise ValueError("The campaign must contain at least one valid scene.")
    campaign_id = re.sub(r"[^a-zA-Z0-9_-]", "", str(raw.get("id") or ""))[:80] or secrets.token_urlsafe(10).replace("-", "").replace("_", "")
    campaign = {"id": campaign_id, "name": title or "Denmart advert", "theme": theme, "ticker": ticker,
                "website": website or "denmart.co.ke", "show_qr": bool(raw.get("show_qr", True)),
                "duration": max(3, min(15, int(raw.get("duration") or 6))),
                "schedule_enabled": bool(raw.get("schedule_enabled", False)),
                "start_date": str(raw.get("start_date") or "")[:10],
                "end_date": str(raw.get("end_date") or "")[:10], "slides": slides,
                "updated_at": datetime.now(timezone.utc).isoformat()}
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


@bp.post("/advertcontrol/api/save")
@_require_developer
def save_campaign():
    business = _business()
    if not business:
        return jsonify(ok=False, error="No Denmart database is configured."), 503
    payload = request.get_json(silent=True) or {}
    try:
        campaign = _valid_campaign(payload.get("campaign"))
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


def _local_today():
    try:
        from zoneinfo import ZoneInfo
        timezone_name = current_app.config.get("TIMEZONE", "Africa/Nairobi")
        return datetime.now(ZoneInfo(timezone_name)).date().isoformat()
    except Exception:
        return datetime.now(timezone.utc).date().isoformat()


def _within_schedule(item, today):
    if not isinstance(item, dict) or not item.get("schedule_enabled"):
        return False
    start_date = str(item.get("start_date") or "")
    end_date = str(item.get("end_date") or "")
    return not (start_date and today < start_date) and not (end_date and today > end_date)


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
    today = _local_today()

    active = []
    for item in _scheduled_campaigns(business.id):
        if _within_schedule(item, today):
            active.append(item)
    if active:
        # When schedules overlap, the most recently saved campaign wins so the
        # operator can intentionally supersede a previous schedule.
        active.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
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
