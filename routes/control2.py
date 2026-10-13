"""Restricted day-to-day operations portal for manager accounts.

Control 2 intentionally has no delete routes. The master admin controls whether
managers may approve payments or cash sales; that capability is disabled by default.
"""
from decimal import Decimal, InvalidOperation
from functools import wraps

from flask import Blueprint, flash, redirect, render_template, request, jsonify
from flask_login import current_user, login_required

from extensions import db
from models import (
    AuditLog, InventoryTransaction, PayOrder, Product, Role, Sale, SaleItem,
    Store, StoreProduct, SystemSetting, User, now,
)
from services.audit import audit
from services.payment_engine import manual_approve, set_fulfillment

bp = Blueprint("control2", __name__)


def manager_required(fn):
    @wraps(fn)
    @login_required
    def wrapped(*args, **kwargs):
        from flask import session
        if (session.get("portal") != "control2" or not current_user.is_authenticated
                or not current_user.is_active or not current_user.business_id
                or not current_user.role or current_user.role.name != "MANAGER"):
            return "Forbidden", 403
        return fn(*args, **kwargs)
    return wrapped


def approvals_enabled(business_id):
    row = SystemSetting.query.filter_by(business_id=business_id, key="control2_can_approve_payments").first()
    return bool(row and row.value == "1")


def _scope_order(order_id):
    return PayOrder.query.filter_by(id=order_id, business_id=current_user.business_id).first_or_404()


@bp.get("/control2/manifest.webmanifest")
def manager_manifest():
    from flask import request
    base = request.host_url.rstrip("/")
    setting = SystemSetting.query.filter_by(business_id=current_user.business_id, key="brand_name").first() if current_user.is_authenticated else None
    label = setting.value.strip() if setting and setting.value and setting.value.strip() else "Toror Mart"
    return jsonify({"name": f"{label} Control 2", "short_name": "Control 2", "start_url": f"{base}/control2/",
                    "scope": f"{base}/control2/", "display": "standalone", "background_color": "#f5faf7",
                    "theme_color": "#10a37f", "description": "Restricted day-to-day store operations.",
                    "icons": [{"src": f"{base}/static/pwa/icon.svg", "sizes": "any", "type": "image/svg+xml", "purpose": "any maskable"}]})


@bp.get("/control2/sw.js")
def manager_service_worker():
    from flask import Response
    js = """const CACHE='denmart-control2-static-v1';
const ASSETS=['/static/css/app.css','/static/js/app.js','/static/pwa/icon.svg','/control2/manifest.webmanifest'];
self.addEventListener('install',e=>e.waitUntil(caches.open(CACHE).then(c=>c.addAll(ASSETS)).catch(()=>{}).then(()=>self.skipWaiting())));
self.addEventListener('activate',e=>e.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k.startsWith('denmart-control2-static-')&&k!==CACHE).map(k=>caches.delete(k)))).then(()=>self.clients.claim())));
self.addEventListener('fetch',e=>{const u=new URL(e.request.url);if(u.origin!==location.origin||e.request.method!=='GET')return;const asset=u.pathname==='/static/css/app.css'||u.pathname==='/static/js/app.js'||u.pathname==='/static/pwa/icon.svg'||u.pathname==='/control2/manifest.webmanifest';const page=u.pathname.startsWith('/control2/');if(!asset&&!page)return;e.respondWith(fetch(e.request).then(r=>{if(asset&&r.ok)caches.open(CACHE).then(c=>c.put(e.request,r.clone()));return r;}).catch(async()=>{if(asset){const hit=await caches.match(e.request,{ignoreSearch:true});if(hit)return hit;}if(e.request.mode==='navigate')return new Response('<!doctype html><meta name=viewport content="width=device-width,initial-scale=1"><title>Control 2 offline</title><main style="font:16px system-ui;max-width:36rem;margin:3rem auto;padding:1rem"><h1>Manager portal is offline</h1><p>Private orders, employee records and approvals are not cached. Reconnect to continue safely.</p><a href="/control2/">Try again</a></main>',{status:503,headers:{'Content-Type':'text/html; charset=utf-8'}});return new Response('Offline. Reconnect to load current records.',{status:503});}));});
"""
    return Response(js, mimetype="application/javascript", headers={"Service-Worker-Allowed": "/control2/", "Cache-Control": "no-cache"})


@bp.get("/control2/")
@manager_required
def dashboard():
    business_id = current_user.business_id
    payments = PayOrder.query.filter_by(business_id=business_id).filter(PayOrder.payment_status.in_(["PENDING", "MANUAL_REVIEW"])).count()
    cash_sales = Sale.query.filter_by(business_id=business_id, status="PENDING_APPROVAL").count()
    low_stock = (StoreProduct.query.join(Store, Store.id == StoreProduct.store_id)
                 .filter(Store.business_id == business_id, StoreProduct.is_available.is_(True),
                         StoreProduct.stock_quantity <= StoreProduct.reorder_level).count())
    active_staff = User.query.filter_by(business_id=business_id, is_active=True).filter(User.id != current_user.id).count()
    return render_template("control2/dashboard.html", payments=payments, cash_sales=cash_sales,
                           low_stock=low_stock, active_staff=active_staff,
                           approvals_enabled=approvals_enabled(business_id))


@bp.get("/control2/payments")
@manager_required
def payments():
    rows = (PayOrder.query.filter_by(business_id=current_user.business_id)
            .order_by(PayOrder.created_at.desc()).limit(250).all())
    item_rows = {}
    from models import PayOrderItem
    for row in rows:
        item_rows[row.id] = PayOrderItem.query.filter_by(payment_order_id=row.id).all()
    return render_template("control2/payments.html", rows=rows, item_rows=item_rows,
                           approvals_enabled=approvals_enabled(current_user.business_id))


@bp.post("/control2/payments/<order_id>/approve")
@manager_required
def approve_payment(order_id):
    if not approvals_enabled(current_user.business_id):
        flash("The master administrator has disabled Control 2 payment approvals.", "error")
        return redirect("/control2/payments")
    order = _scope_order(order_id)
    try:
        ok, message = manual_approve(order, current_user.id, "Control 2 manager approval")
        if ok:
            flash(f"{order.reference} approved: payment verified and order moved to packaging.", "success")
        else:
            flash(message, "error")
    except Exception:
        db.session.rollback()
        flash("Approval failed safely; no payment state was changed.", "error")
    return redirect("/control2/payments")


@bp.post("/control2/payments/<order_id>/fulfillment")
@manager_required
def update_fulfillment(order_id):
    order = _scope_order(order_id)
    try:
        status = (request.form.get("status") or "").strip().upper()
        set_fulfillment(order, status, current_user.id)
        flash(f"{order.reference} fulfillment updated to {status}.", "success")
    except ValueError as exc:
        flash(str(exc), "error")
    except Exception:
        db.session.rollback()
        flash("Fulfillment update failed safely.", "error")
    return redirect("/control2/payments")


@bp.get("/control2/cash-sales")
@manager_required
def cash_sales():
    sales = Sale.query.filter_by(business_id=current_user.business_id, status="PENDING_APPROVAL").order_by(Sale.created_at.desc()).limit(250).all()
    items = {sale.id: SaleItem.query.filter_by(sale_id=sale.id).all() for sale in sales}
    staff_ids = {sale.cashier_id for sale in sales}
    staff = {u.id: u.name for u in User.query.filter(User.business_id == current_user.business_id, User.id.in_(staff_ids)).all()} if staff_ids else {}
    return render_template("control2/cash_sales.html", sales=sales, items=items, staff=staff,
                           approvals_enabled=approvals_enabled(current_user.business_id))


@bp.post("/control2/cash-sales/<sale_id>/approve")
@manager_required
def approve_cash_sale(sale_id):
    if not approvals_enabled(current_user.business_id):
        flash("The master administrator has disabled Control 2 sale approvals.", "error")
        return redirect("/control2/cash-sales")
    sale = Sale.query.filter_by(id=sale_id, business_id=current_user.business_id).with_for_update().first_or_404()
    if sale.status != "PENDING_APPROVAL":
        flash("This sale is no longer pending approval.", "error")
        return redirect("/control2/cash-sales")
    from models import SaleItem
    prepared = []
    for item in SaleItem.query.filter_by(sale_id=sale.id).all():
        sp = StoreProduct.query.filter_by(store_id=sale.store_id, product_id=item.product_id).with_for_update().first()
        qty = Decimal(str(item.quantity or 0))
        if not sp or Decimal(str(sp.stock_quantity or 0)) < qty or Decimal(str(sp.reserved_quantity or 0)) < qty:
            db.session.rollback()
            flash(f"Approval stopped: reservation is invalid for {item.product_name_snapshot}; no stock was deducted.", "error")
            return redirect("/control2/cash-sales")
        prepared.append((sp, qty))
    for sp, qty in prepared:
        sp.reserved_quantity = Decimal(str(sp.reserved_quantity or 0)) - qty
        sp.stock_quantity = Decimal(str(sp.stock_quantity or 0)) - qty
        db.session.add(InventoryTransaction(store_id=sp.store_id, product_id=sp.product_id, transaction_type="SALE",
            quantity=-qty, unit_cost=sp.cost_price, reference_type="SALE", reference_id=sale.id,
            notes="Cash sale completed after Control 2 manager approval", created_by=current_user.id))
    sale.status = "COMPLETED"
    sale.completed_at = now()
    db.session.commit()
    audit("POS_CASH_SALE_APPROVED_CONTROL2", "Sale", sale.id, new_values={"total": str(sale.total), "approved_by": current_user.name})
    flash(f"{sale.receipt_number} approved; stock deducted and receipt enabled.", "success")
    return redirect("/control2/cash-sales")


@bp.post("/control2/cash-sales/<sale_id>/reject")
@manager_required
def reject_cash_sale(sale_id):
    if not approvals_enabled(current_user.business_id):
        flash("The master administrator has disabled Control 2 sale approvals.", "error")
        return redirect("/control2/cash-sales")
    sale = Sale.query.filter_by(id=sale_id, business_id=current_user.business_id).with_for_update().first_or_404()
    if sale.status != "PENDING_APPROVAL":
        flash("This sale is no longer pending approval.", "error")
        return redirect("/control2/cash-sales")
    for item in SaleItem.query.filter_by(sale_id=sale.id).all():
        sp = StoreProduct.query.filter_by(store_id=sale.store_id, product_id=item.product_id).with_for_update().first()
        if sp:
            sp.reserved_quantity = max(Decimal("0"), Decimal(str(sp.reserved_quantity or 0)) - Decimal(str(item.quantity or 0)))
    sale.status = "REJECTED"
    sale.completed_at = None
    db.session.commit()
    audit("POS_CASH_SALE_REJECTED_CONTROL2", "Sale", sale.id, new_values={"total": str(sale.total), "rejected_by": current_user.name})
    flash(f"{sale.receipt_number} rejected; reserved stock released.", "success")
    return redirect("/control2/cash-sales")


@bp.route("/control2/stock", methods=["GET", "POST"])
@manager_required
def stock():
    business_id = current_user.business_id
    if request.method == "POST":
        store_product_id = (request.form.get("store_product_id") or "").strip()
        try:
            quantity = Decimal(str(request.form.get("quantity") or "0"))
            unit_cost = Decimal(str(request.form.get("unit_cost") or "0"))
        except InvalidOperation:
            flash("Enter a valid positive quantity and non-negative unit cost.", "error")
            return redirect("/control2/stock")
        item = (StoreProduct.query.join(Store, Store.id == StoreProduct.store_id)
                .filter(StoreProduct.id == store_product_id, Store.business_id == business_id).with_for_update().first())
        if not item or not quantity.is_finite() or quantity <= 0 or not unit_cost.is_finite() or unit_cost < 0:
            flash("Choose a product, use a positive quantity, and enter a valid cost.", "error")
            return redirect("/control2/stock")
        old_cost = Decimal(str(item.cost_price or 0))
        item.stock_quantity = Decimal(str(item.stock_quantity or 0)) + quantity
        if unit_cost > 0:
            item.cost_price = unit_cost
        db.session.add(InventoryTransaction(store_id=item.store_id, product_id=item.product_id, transaction_type="ADJUSTMENT_IN",
            quantity=quantity, unit_cost=item.cost_price, reference_type="CONTROL2_STOCK_IN", reference_id=item.id,
            notes=(request.form.get("notes") or "Stock added through Control 2")[:500], created_by=current_user.id))
        db.session.commit()
        audit("CONTROL2_STOCK_ADDED", "StoreProduct", item.id, old_values={"stock": str(Decimal(str(item.stock_quantity or 0)) - quantity), "cost": str(old_cost)},
              new_values={"stock": str(item.stock_quantity), "cost": str(item.cost_price), "quantity_added": str(quantity)})
        flash(f"Added {quantity} units to {item.product.name}.", "success")
        return redirect("/control2/stock")
    query_text = (request.args.get("q") or "").strip()[:100]
    q = StoreProduct.query.join(Store, Store.id == StoreProduct.store_id).join(Product, Product.id == StoreProduct.product_id).filter(
        Store.business_id == business_id, Product.status == "ACTIVE")
    if query_text:
        pattern = f"%{query_text}%"
        from sqlalchemy import or_
        q = q.filter(or_(Product.name.ilike(pattern), Product.barcode.ilike(pattern), Product.sku.ilike(pattern)))
    rows = q.order_by(Product.name.asc()).limit(300).all()
    stores = Store.query.filter_by(business_id=business_id, is_active=True).order_by(Store.name).all()
    return render_template("control2/stock.html", rows=rows, stores=stores, q=query_text)


@bp.route("/control2/staff", methods=["GET", "POST"])
@manager_required
def staff():
    business_id = current_user.business_id
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()[:160]
        username = (request.form.get("username") or "").strip()[:80]
        password = request.form.get("password") or ""
        role_name = (request.form.get("role_name") or "CASHIER").strip().upper()
        store_id = (request.form.get("store_id") or "").strip() or None
        phone = (request.form.get("phone") or "").strip()[:40] or None
        email = (request.form.get("email") or "").strip()[:160] or None
        role = Role.query.filter_by(name=role_name).first() if role_name in {"CASHIER", "STOCK_CONTROLLER"} else None
        store = Store.query.filter_by(id=store_id, business_id=business_id).first() if store_id else None
        if not name or not username or len(password) < 8 or not role or (store_id and not store):
            flash("Fill the name, unique username, password of at least 8 characters, role and a valid mart.", "error")
        elif User.query.filter_by(username=username).first() or (email and User.query.filter_by(email=email).first()):
            flash("That username or email is already in use.", "error")
        else:
            user = User(business_id=business_id, store_id=store_id, name=name, username=username, phone=phone, email=email,
                        role_id=role.id, is_active=True)
            user.set_password(password)
            db.session.add(user); db.session.commit()
            audit("CONTROL2_STAFF_CREATED", "User", user.id, new_values={"name": user.name, "username": user.username, "role": role.name})
            flash(f"Staff account created for {user.name}. They can use the POS login; only manager accounts can use Control 2.", "success")
            return redirect("/control2/staff")
    users = User.query.filter_by(business_id=business_id).order_by(User.name.asc()).all()
    stores = Store.query.filter_by(business_id=business_id, is_active=True).order_by(Store.name).all()
    return render_template("control2/staff.html", users=users, stores=stores)


@bp.post("/control2/staff/<user_id>/toggle")
@manager_required
def toggle_staff(user_id):
    target = User.query.filter_by(id=user_id, business_id=current_user.business_id).first_or_404()
    if target.id == current_user.id or not target.role or target.role.name in {"OWNER", "MANAGER"}:
        flash("You cannot disable your own account, the master administrator, or another manager. Ask the master admin for that change.", "error")
    else:
        target.is_active = not target.is_active
        db.session.commit()
        audit("CONTROL2_STAFF_DISABLED" if not target.is_active else "CONTROL2_STAFF_ENABLED", "User", target.id,
              new_values={"name": target.name, "username": target.username, "is_active": target.is_active})
        flash(f"{target.name} is now {'active' if target.is_active else 'disabled'}. No records were deleted.", "success")
    return redirect("/control2/staff")
