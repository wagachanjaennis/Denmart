from functools import wraps
from urllib.parse import urlparse
from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from extensions import db
from models import SystemSetting, now
from services.catalogue_feeder import (
    get_config, get_status, get_cache, get_mode, save_config, sync_feeder,
    mark_local_override, mark_local_override_many, feeder_summary,
)

bp = Blueprint("catalogue_feeder", __name__)


def _admin_required(fn):
    @wraps(fn)
    @login_required
    def wrapped(*args, **kwargs):
        if (not current_user.is_authenticated or getattr(current_user, "role", None) is None
                or current_user.role.name != "OWNER"):
            return "Forbidden", 403
        from flask import session
        if session.get("portal") != "admin" or not current_user.has_permission("products.view"):
            return "Forbidden", 403
        return fn(*args, **kwargs)
    return wrapped


@bp.get("/control/catalogue-feeder")
@_admin_required
def page():
    business_id = current_user.business_id
    summary = feeder_summary(business_id)
    return render_template("admin/catalogue_feeder.html", summary=summary,
                           business=current_user.business, active_overrides=len(__import__("services.catalogue_feeder", fromlist=["get_overrides"]).get_overrides(business_id)))


@bp.post("/control/catalogue-feeder/save")
@_admin_required
def save():
    incoming = {
        "endpoint_url": request.form.get("endpoint_url", ""),
        "auth_type": request.form.get("auth_type", "none"),
        "header_name": request.form.get("header_name", "X-API-Key"),
        "token": request.form.get("token", ""),
        "items_path": request.form.get("items_path", "products"),
        "barcode_field": request.form.get("barcode_field", "barcode"),
        "image_field": request.form.get("image_field", "image_url"),
        "sku_field": request.form.get("sku_field", "sku"),
        "name_field": request.form.get("name_field", "name"),
        "auto_refresh": "1" if request.form.get("auto_refresh") == "1" else "0",
    }
    try:
        save_config(current_user.business_id, incoming)
        flash("Feeder settings saved. Your existing products, stock and sales were not changed.", "success")
    except Exception as exc:
        db.session.rollback()
        flash(str(exc)[:400], "error")
    return redirect(url_for("catalogue_feeder.page"))


@bp.post("/control/catalogue-feeder/sync")
@_admin_required
def sync():
    summary = feeder_summary(current_user.business_id)
    # If the button carries a changed URL/field mapping, save those settings first.
    if request.form.get("save_before_sync") == "1":
        incoming = {
            "endpoint_url": request.form.get("endpoint_url", ""),
            "auth_type": request.form.get("auth_type", "none"),
            "header_name": request.form.get("header_name", "X-API-Key"),
            "token": request.form.get("token", ""),
            "items_path": request.form.get("items_path", "products"),
            "barcode_field": request.form.get("barcode_field", "barcode"),
            "image_field": request.form.get("image_field", "image_url"),
            "sku_field": request.form.get("sku_field", "sku"),
            "name_field": request.form.get("name_field", "name"),
            "auto_refresh": "1" if request.form.get("auto_refresh") == "1" else "0",
        }
        try:
            save_config(current_user.business_id, incoming)
        except Exception as exc:
            db.session.rollback()
            flash(str(exc)[:400], "error")
            return redirect(url_for("catalogue_feeder.page"))
    result = sync_feeder(current_user.business_id)
    flash(result.get("message") or ("Feeder sync complete." if result.get("ok") else "Feeder sync failed."), "success" if result.get("ok") else "error")
    return redirect(url_for("catalogue_feeder.page"))


@bp.post("/control/catalogue-feeder/mode")
@_admin_required
def mode():
    selected = str(request.form.get("mode") or "current").lower()
    if selected not in {"current", "api"}:
        flash("Select either current catalogue or feeder API.", "error")
        return redirect(url_for("catalogue_feeder.page"))
    if selected == "api":
        cache = get_cache(current_user.business_id)
        if not cache.get("rows"):
            flash("Test and sync a valid feed before switching the online catalogue to API mode. Your current catalogue is still active.", "error")
            return redirect(url_for("catalogue_feeder.page"))
        setting = SystemSetting.query.filter_by(business_id=current_user.business_id, key="catalogue_feeder_activated_at").first()
        if setting is None:
            setting = SystemSetting(business_id=current_user.business_id, key="catalogue_feeder_activated_at", value=now().isoformat())
            db.session.add(setting)
    setting = SystemSetting.query.filter_by(business_id=current_user.business_id, key="catalogue_feeder_mode").first()
    if setting is None:
        setting = SystemSetting(business_id=current_user.business_id, key="catalogue_feeder_mode", value=selected)
        db.session.add(setting)
    else:
        setting.value = selected
        setting.updated_at = now()
    db.session.commit()
    flash("Online catalogue now uses " + ("the feeder API for barcodes and images. POS and offline data remain local." if selected == "api" else "your current Denmart product barcodes and images."), "success")
    return redirect(url_for("catalogue_feeder.page"))
