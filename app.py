import os
from datetime import datetime, timezone
from flask import Flask, Blueprint, jsonify, redirect, url_for, request, render_template, current_app, session
from flask_login import current_user
from config import Config
from extensions import db, migrate, login_manager, csrf
from models import User, Business, SystemError, SystemSetting, Sale, PayOrder
from services.branding import brand_display_name, brand_display_copy
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix
from flask_wtf.csrf import CSRFError


def create_app():
    app = Flask(__name__)
    # Render terminates TLS before forwarding requests to Gunicorn. Trust the
    # forwarded proto/host so externally generated URLs stay HTTPS and point at
    # the public service rather than the internal HTTP hop.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    app.config.from_object(Config)
    os.makedirs(os.path.join(app.root_path, "instance"), exist_ok=True)

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    login_manager.login_view = None
    csrf.init_app(app)

    from routes.auth import bp as auth_bp
    from routes.shop import bp as shop_bp
    from routes.pos import bp as pos_bp
    from routes.admin import bp as admin_bp
    from routes.api import bp as api_bp
    from routes.scan import bp as scan_bp
    from routes.pay import bp as pay_bp
    from routes.control2 import bp as control2_bp
    from routes.dev_admin import bp as developer_admin_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(shop_bp)
    app.register_blueprint(pos_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(scan_bp)
    app.register_blueprint(pay_bp)
    app.register_blueprint(control2_bp)
    app.register_blueprint(developer_admin_bp)

    @app.get("/robots.txt")
    def robots_txt():
        # Discourage indexing of private control routes; this is not a substitute for auth.
        return "User-agent: *\nDisallow: /qaz\n", 200, {"Content-Type": "text/plain; charset=utf-8", "Cache-Control": "public, max-age=3600"}

    # Service gates are owner-controlled and deliberately leave /qaz available.
    @app.before_request
    def enforce_service_controls():
        if request.path.startswith("/qaz") or request.path.startswith("/static/") or request.path in {"/healthz", "/favicon.ico", "/pulse_receiver", "/robots.txt"}:
            return None
        try:
            business = Business.query.order_by(Business.created_at).first()
            if not business:
                return None
            flags = {row.key: row.value for row in SystemSetting.query.filter_by(business_id=business.id).all()
                     if row.key in {"dev_site_mode", "dev_storefront_enabled", "dev_admin_enabled", "dev_pos_enabled"}}
            path = request.path
            site_off = flags.get("dev_site_mode", "0") == "1"
            admin_off = flags.get("dev_admin_enabled", "1") != "1"
            pos_off = flags.get("dev_pos_enabled", "1") != "1"
            storefront_off = flags.get("dev_storefront_enabled", "1") != "1"
            if site_off:
                # Allow sign-in itself. Authenticated owner will land on the reminder
                # page in place of the dashboard; all customer/operations requests pause.
                if path == "/control" and request.method in {"GET", "POST"} and not current_user.is_authenticated:
                    return None
                if path in {"/merchant", "/control2"} and request.method in {"GET", "POST"} and not current_user.is_authenticated:
                    return None
                if current_user.is_authenticated and session.get("portal") == "admin" and path in {"/control", "/control/"}:
                    return render_template("dev_admin/maintenance.html", reason="Subscription reminder: this Denmart service is paused. Please renew the monthly subscription to restore operations."), 503
                # A quiet maintenance page is safer than letting cached data-changing requests run.
                return render_template("dev_admin/maintenance.html", reason="Sorry for the inconvenience. This service is temporarily unavailable. Please contact support."), 503
            if admin_off and (path == "/control" or path.startswith("/control/")):
                # Leave the login form reachable while the dashboard is paused;
                # after a successful sign-in the owner sees the subscription reminder.
                if path == "/control" and request.method in {"GET", "POST"} and not current_user.is_authenticated:
                    return None
                return render_template("dev_admin/maintenance.html", reason="Admin dashboard is temporarily unavailable. Please contact the service provider."), 503
            if pos_off and (path == "/merchant" or path.startswith("/merchant/") or path.startswith("/api/pos/")):
                return render_template("dev_admin/maintenance.html", reason="The till is temporarily unavailable. Sorry for the inconvenience; please try again later."), 503
            if storefront_off and (path in {"/", "/shop", "/cart", "/pay"} or path.startswith("/product/") or path.startswith("/locations") or path.startswith("/pay/")):
                return render_template("dev_admin/maintenance.html", reason="Online shopping is temporarily unavailable. Sorry for the inconvenience; please try again later."), 503
        except Exception:
            current_app.logger.exception("Service availability gate could not read its settings")
        return None

    # Render services sometimes start with `gunicorn app:app` and skip
    # the explicit init_db.py command. Ensure a fresh database cannot
    # crash the public storefront with "no such table" errors.
    if os.getenv("AUTO_INIT_DB", "1") != "0":
        from bootstrap import bootstrap_database
        with app.app_context():
            bootstrap_database()

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, user_id)

    @login_manager.unauthorized_handler
    def unauthorized():
        # The application has two authenticated portals. Route anonymous
        # visitors to the correct login screen instead of relying on a
        # single Flask-Login endpoint that does not exist.
        target = request.args.get("next", "")
        if request.path.startswith("/control2"):
            return redirect(f"/control2?next={request.path}")
        if request.path.startswith("/control") or request.path.startswith("/scan"):
            return redirect(f"/control?next={request.path}")
        return redirect(f"/merchant?next={request.path}")

    @app.context_processor
    def inject_globals():
        business = (current_user.business if current_user.is_authenticated and getattr(current_user, "business", None)
                    else Business.query.first())
        footer_setting = (SystemSetting.query.filter_by(business_id=business.id, key="footer_text").first() if business else None)
        brand_setting = (SystemSetting.query.filter_by(business_id=business.id, key="brand_name").first() if business else None)
        announcement_setting = (SystemSetting.query.filter_by(business_id=business.id, key="storefront_announcement").first() if business else None)
        sidebar_ad_title_setting = (SystemSetting.query.filter_by(business_id=business.id, key="storefront_sidebar_ad_title").first() if business else None)
        sidebar_ad_body_setting = (SystemSetting.query.filter_by(business_id=business.id, key="storefront_sidebar_ad_body").first() if business else None)
        sidebar_ad_link_setting = (SystemSetting.query.filter_by(business_id=business.id, key="storefront_sidebar_ad_link").first() if business else None)
        display_name = brand_display_name(brand_setting.value if brand_setting else "")
        footer = brand_display_copy(footer_setting.value, display_name) if footer_setting else f"All rights reserved · {display_name} Merchants"
        pending_pos_approvals = pending_pay_approvals = 0
        if request.path.startswith("/control") and current_user.is_authenticated and getattr(current_user, "business_id", None):
            pending_pos_approvals = Sale.query.filter_by(business_id=current_user.business_id, status="PENDING_APPROVAL").count()
            pending_pay_approvals = PayOrder.query.filter(PayOrder.business_id==current_user.business_id,
                PayOrder.payment_status.in_(["PENDING", "MANUAL_REVIEW"])).count()
        from services.product_images import public_product_image, has_public_product_image
        return {
            "business_name": display_name,
            "business_logo": business.logo_url if business else "",
            "currency": app.config["CURRENCY"],
            "footer_text": footer,
            "storefront_announcement": (brand_display_copy(announcement_setting.value, display_name) if announcement_setting else f"{display_name} online delivery service will be available from 27 October 2026."),
            "sidebar_ad_title": brand_display_copy(sidebar_ad_title_setting.value, display_name) if sidebar_ad_title_setting and sidebar_ad_title_setting.value else "",
            "sidebar_ad_body": brand_display_copy(sidebar_ad_body_setting.value, display_name) if sidebar_ad_body_setting and sidebar_ad_body_setting.value else "",
            "sidebar_ad_link": sidebar_ad_link_setting.value if sidebar_ad_link_setting and sidebar_ad_link_setting.value else "/shop",
            "pending_pos_approvals": pending_pos_approvals,
            "pending_pay_approvals": pending_pay_approvals,
            "title": None,
            "product_image_url": public_product_image,
            "has_product_image": has_public_product_image,
        }

    @app.get("/healthz")
    def healthz():
        return {"status": "ok", "service": "denmart", "time": datetime.now(timezone.utc).isoformat()}

    # External pulse endpoint is deliberately isolated from CSRF.
    pulse_bp = Blueprint("pulse", __name__)
    @pulse_bp.post("/pulse_receiver")
    @csrf.exempt
    def pulse_receiver():
        return ("", 204)
    app.register_blueprint(pulse_bp)

    def _record_system_error(exc, *, level="ERROR", code=None):
        """Persist an actionable error without ever letting logging break the request."""
        try:
            business_id = current_user.business_id if current_user.is_authenticated else None
            if not business_id:
                row = db.session.query(Business.id).order_by(Business.created_at).first()
                business_id = row[0] if row else None
            message = str(getattr(exc, "description", exc) or "Unexpected application error")[:1000]
            err = SystemError(
                business_id=business_id,
                level=level,
                code=(code or exc.__class__.__name__)[:120],
                message=message,
                path=request.path[:500],
                method=request.method[:20],
                user_id=current_user.id if current_user.is_authenticated else None,
                ip_address=request.headers.get("X-Forwarded-For", request.remote_addr),
                user_agent=request.user_agent.string[:1000],
            )
            db.session.add(err)
            db.session.commit()
        except Exception:
            db.session.rollback()

    @app.errorhandler(404)
    def not_found(exc):
        # A browser probing for /favicon.ico should not turn the health screen into noise.
        if request.path != "/favicon.ico":
            _record_system_error(exc, level="WARN", code="NOT_FOUND")
        return render_template("errors/not_found.html"), 404

    @app.errorhandler(CSRFError)
    def handle_csrf_error(exc):
        _record_system_error(exc, level="SECURITY", code="CSRF_ERROR")
        return render_template("errors/server_error.html"), 400

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code and exc.code >= 400 and request.path not in {"/healthz", "/pulse_receiver", "/favicon.ico"}:
            _record_system_error(exc, level="WARN" if exc.code < 500 else "ERROR", code=f"HTTP_{exc.code}")
        return exc

    @app.errorhandler(Exception)
    def handle_unexpected_error(exc):
        current_app.logger.exception("Unhandled application exception")
        _record_system_error(exc, level="ERROR", code=exc.__class__.__name__)
        return render_template("errors/server_error.html"), 500

    @app.post("/api/client-errors")
    @csrf.exempt
    def client_errors():
        """Accept lightweight browser errors so the health screen also catches JS failures."""
        payload = request.get_json(silent=True) or {}
        message = str(payload.get("message") or "Browser error")[:1000]
        source = str(payload.get("source") or "")[:300]
        line = payload.get("line")
        column = payload.get("column")
        details = message
        if source:
            details += f" · {source}"
        if line is not None:
            details += f" · line {line}:{column or 0}"
        _record_system_error(RuntimeError(details), level="CLIENT", code=str(payload.get("code") or "CLIENT_ERROR"))
        return ("", 204)

    @app.get("/api")
    def api_root():
        return jsonify(error="not_found"), 404

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=app.config["FLASK_ENV"] != "production")
