import hmac
from functools import wraps
from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash
from flask_login import current_user
from extensions import db
from models import Business, SystemSetting, AuditLog, now

bp = Blueprint("developer_admin", __name__)
FEATURES = {
    "site": ("dev_site_mode", "Entire site"),
    "storefront": ("dev_storefront_enabled", "Online shopping"),
    "admin": ("dev_admin_enabled", "Admin dashboard"),
    "pos": ("dev_pos_enabled", "POS / till"),
}

def _dev_configured():
    return bool(str(current_app.config.get("DEV_NAME") or "").strip() and str(current_app.config.get("DEV_PASS") or ""))

def _dev_proof(login_at, csrf_token, password):
    payload = f"denmart-developer-console-v1|{int(login_at)}|{csrf_token}".encode("utf-8")
    return hmac.new(str(password).encode("utf-8"), payload, "sha256").hexdigest()

def _dev_ok():
    # Do not trust a boolean inside Flask's client-side session by itself. Tie the
    # session marker to DEV_PASS so a weak/default Flask SECRET_KEY cannot forge
    # developer-console access without also knowing the separate operator secret.
    if not _dev_configured() or not session.get("developer_admin_authenticated"):
        return False
    try:
        login_at = int(session.get("developer_admin_login_at") or 0)
    except (TypeError, ValueError):
        return False
    csrf_token = str(session.get("developer_admin_csrf") or "")
    provided = str(session.get("developer_admin_auth_proof") or "")
    if login_at <= 0 or not csrf_token or not provided:
        return False
    expected = _dev_proof(login_at, csrf_token, current_app.config.get("DEV_PASS") or "")
    return hmac.compare_digest(provided, expected)

def _business():
    return Business.query.order_by(Business.created_at).first()

def _get_setting(business_id, key, default):
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

def _audit(action, entity, values):
    business = _business()
    if not business:
        return
    db.session.add(AuditLog(business_id=business.id, user_id=current_user.id if current_user.is_authenticated else None,
        action=action, entity_type="DeveloperControl", entity_id=entity, new_values=values,
        ip_address=(request.headers.get("X-Forwarded-For", request.remote_addr) or "")[:80],
        user_agent=(request.user_agent.string or "")[:1000]))

def _require_dev(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not _dev_ok():
            return redirect(url_for("developer_admin.login"))
        return fn(*args, **kwargs)
    return wrapped

@bp.route("/qaz", methods=["GET", "POST"])
def login():
    if not _dev_configured():
        return "Developer controls are not configured.", 404
    if _dev_ok():
        return redirect(url_for("developer_admin.panel"))
    if request.method == "POST":
        name = str(request.form.get("developer_name") or "")
        password = str(request.form.get("developer_password") or "")
        expected_name = str(current_app.config.get("DEV_NAME") or "")
        expected_pass = str(current_app.config.get("DEV_PASS") or "")
        valid = hmac.compare_digest(name.encode("utf-8"), expected_name.encode("utf-8")) and hmac.compare_digest(password.encode("utf-8"), expected_pass.encode("utf-8"))
        attempt_count = int(session.get("developer_attempts") or 0)
        if attempt_count >= 8:
            return "Too many attempts. Close this browser session and try later.", 429
        if valid:
            session.pop("developer_attempts", None)
            session["developer_admin_authenticated"] = True
            session["developer_admin_login_at"] = int(now().timestamp())
            session["developer_admin_csrf"] = __import__("secrets").token_urlsafe(32)
            session["developer_admin_auth_proof"] = _dev_proof(
                session["developer_admin_login_at"], session["developer_admin_csrf"], expected_pass
            )
            business = _business()
            if business:
                _audit("DEV_CONTROL_LOGIN", "session", {"method": "environment_credentials"})
                db.session.commit()
            return redirect(url_for("developer_admin.panel"))
        session["developer_attempts"] = attempt_count + 1
        flash("Credentials not accepted.", "error")
    return render_template("dev_admin/login.html")

@bp.get("/qaz/panel")
@_require_dev
def panel():
    business = _business()
    if not business:
        return "No business database is configured.", 503
    flags = {key: _get_setting(business.id, setting_key, "1" if key != "site" else "0") for key, (setting_key, label) in FEATURES.items()}
    return render_template("dev_admin/panel.html", flags=flags, features=FEATURES, csrf_token_value=session.get("developer_admin_csrf", ""))

@bp.post("/qaz/panel/features")
@_require_dev
def save_features():
    business = _business()
    if not business:
        return "No business database is configured.", 503
    token = str(request.form.get("dev_csrf") or "")
    saved = str(session.get("developer_admin_csrf") or "")
    if not saved or not hmac.compare_digest(token, saved):
        return "Request verification failed. Reload the developer panel.", 400
    old = {}
    new = {}
    for key, (setting_key, label) in FEATURES.items():
        value = "1" if request.form.get(key) == "1" else "0"
        old[key] = _get_setting(business.id, setting_key, "1" if key != "site" else "0")
        new[key] = value
        _put_setting(business.id, setting_key, value)
    _audit("DEV_FEATURE_FLAGS_UPDATED", business.id, {"before": old, "after": new})
    db.session.commit()
    flash("Service controls updated. Changes apply to new requests immediately.", "success")
    return redirect(url_for("developer_admin.panel"))

@bp.post("/qaz/logout")
@_require_dev
def logout():
    business = _business()
    if business:
        _audit("DEV_CONTROL_LOGOUT", "session", {})
        db.session.commit()
    session.pop("developer_admin_authenticated", None)
    session.pop("developer_admin_login_at", None)
    session.pop("developer_admin_csrf", None)
    session.pop("developer_admin_auth_proof", None)
    return redirect(url_for("developer_admin.login"))
