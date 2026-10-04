from decimal import Decimal, InvalidOperation
from datetime import timedelta
import secrets
import json
import base64
import csv
import io
import re
from io import BytesIO
from PIL import Image, ImageOps
from pathlib import Path
from functools import wraps
import requests
from flask import Blueprint, flash, redirect, render_template, request, url_for, Response, current_app, session, send_file, jsonify, after_this_request
from flask_login import current_user, login_required
from sqlalchemy import or_
from extensions import db
from models import (Product, StoreProduct, PricingRule, PriceHistory, InventoryTransaction, User,
                    AuditLog, Sale, SaleItem, Store, Business, Category, SystemError,
                    Expense, Role, SystemSetting, Permission, Customer, ProductAlias, ProductImage,
                    Supplier, PurchaseOrder, PurchaseOrderItem, GatewaySmsMessage, LoyaltyAccount, LoyaltyTransaction, Shift, now)
from services.audit import audit
from services.backup_restore import export_database_json, create_sqlite_snapshot, restore_database_json, restore_sqlite_snapshot
from services.search import forgiving_rank

bp = Blueprint("admin", __name__)
ADMIN_BASE = "/control"


def admin_required(permission=None):
    def decorator(fn):
        @wraps(fn)
        @login_required
        def wrapped(*args, **kwargs):
            if session.get("portal") != "admin" or not current_user.is_authenticated or not current_user.role or current_user.role.name != "OWNER":
                return "Forbidden", 403
            if permission and not current_user.has_permission(permission):
                return "Forbidden", 403
            return fn(*args, **kwargs)
        return wrapped
    return decorator



def _uploaded_product_image(file_storage, product_name="Product"):
    """Return a compact square WebP data URL so uploaded photos travel with backups."""
    if not file_storage or not getattr(file_storage, "filename", ""):
        return None
    if not (getattr(file_storage, "mimetype", "") or "").lower().startswith("image/"):
        raise ValueError("Choose a valid image file.")
    raw = file_storage.read()
    if not raw:
        raise ValueError("The image file is empty.")
    if len(raw) > 8 * 1024 * 1024:
        raise ValueError("Product images must be 8 MB or smaller.")
    try:
        source = Image.open(BytesIO(raw))
        source = ImageOps.exif_transpose(source).convert("RGBA")
        source.thumbnail((760, 760), Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", (800, 800), "white")
        x = (800 - source.width) // 2
        y = (800 - source.height) // 2
        canvas.paste(source, (x, y), source)
        out = BytesIO()
        canvas.save(out, format="WEBP", quality=82, method=6, optimize=True)
        encoded = base64.b64encode(out.getvalue()).decode("ascii")
        return f"data:image/webp;base64,{encoded}"
    except Exception as exc:
        raise ValueError("The uploaded file is not a readable image.") from exc


def _remote_product_image_data_url(image_url):
    """Cache an administrator-supplied remote photo into the database once."""
    raw = str(image_url or "").strip()
    if not raw.startswith(("http://", "https://")):
        return raw
    try:
        response = requests.get(
            raw, timeout=12, allow_redirects=True,
            headers={"User-Agent": "DenmartAdminImageCache/2026.09", "Accept": "image/*,*/*;q=0.8"},
            stream=True,
        )
        response.raise_for_status()
        content_type = (response.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
        if not content_type.startswith("image/"):
            raise ValueError("The image URL did not return an image.")
        chunks = []; total = 0
        for chunk in response.iter_content(chunk_size=128 * 1024):
            if not chunk: continue
            total += len(chunk)
            if total > 8 * 1024 * 1024: raise ValueError("The image is larger than 8 MB.")
            chunks.append(chunk)
        source = Image.open(BytesIO(b"".join(chunks)))
        source = ImageOps.exif_transpose(source).convert("RGBA")
        source.thumbnail((760, 760), Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", (800, 800), "white")
        canvas.paste(source, ((800-source.width)//2, (800-source.height)//2), source)
        out = BytesIO(); canvas.save(out, format="WEBP", quality=82, method=6, optimize=True)
        return "data:image/webp;base64," + base64.b64encode(out.getvalue()).decode("ascii")
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("Denmart could not cache that image URL. Upload the exact product photo instead.") from exc


def _set_product_image(product, data_url, source_type="ADMIN_UPLOAD"):
    if not data_url:
        return
    # Uploaded photos are already normalized into a data URL; remote URLs are
    # fetched once so administrator-supplied images remain available with the
    # product record.
    cached = data_url if is_data_image_url(data_url) else _remote_product_image_data_url(data_url)
    product.image_url = cached
    ProductImage.query.filter_by(product_id=product.id).delete(synchronize_session=False)
    db.session.add(ProductImage(
        product_id=product.id, image_url=cached, thumbnail_url=cached,
        alt_text=product.name, source_type=source_type,
        license_info="Cached into the Denmart database by an administrator.", sort_order=0, is_primary=True,
    ))




@bp.get(f"{ADMIN_BASE}/daily-report")
@admin_required("reports.view")
def daily_report():
    business_id=current_user.business_id
    today_sale=db.func.date(Sale.created_at)==db.func.current_date()
    today_expense=db.func.date(Expense.incurred_at)==db.func.current_date()
    today_inventory=db.func.date(InventoryTransaction.created_at)==db.func.current_date()
    sales=db.session.query(db.func.coalesce(db.func.sum(Sale.total),0)).filter(Sale.business_id==business_id,Sale.status=="COMPLETED",today_sale).scalar() or 0
    expenses=db.session.query(db.func.coalesce(db.func.sum(Expense.amount),0)).filter(Expense.business_id==business_id,today_expense).scalar() or 0
    cogs=db.session.query(db.func.coalesce(db.func.sum((-InventoryTransaction.quantity)*InventoryTransaction.unit_cost),0)).join(Store,Store.id==InventoryTransaction.store_id).filter(Store.business_id==business_id,InventoryTransaction.transaction_type=="SALE",InventoryTransaction.quantity<0,today_inventory).scalar() or 0
    items=db.session.query(db.func.coalesce(db.func.sum(SaleItem.quantity),0)).join(Sale,Sale.id==SaleItem.sale_id).filter(Sale.business_id==business_id,Sale.status=="COMPLETED",today_sale).scalar() or 0
    sales=Decimal(str(sales)); expenses=Decimal(str(expenses)); cogs=Decimal(str(cogs)); items=Decimal(str(items))
    gross=sales-cogs; net=gross-expenses
    return render_template("admin/daily_report.html",business_name=current_user.business.name if current_user.business else "Denmart",
                           total_sales=sales,expenses=expenses,cogs=cogs,gross_profit=gross,net_result=net,items=items,report_date=now())


@bp.get(ADMIN_BASE)
@admin_required()
def dashboard():
    business_id=current_user.business_id
    today=db.func.date(Sale.created_at)==db.func.current_date()
    sales_today=db.session.query(db.func.coalesce(db.func.sum(Sale.total),0)).filter(Sale.business_id==business_id,Sale.status=="COMPLETED",today).scalar() or 0
    sales_total=db.session.query(db.func.coalesce(db.func.sum(Sale.total),0)).filter(Sale.business_id==business_id,Sale.status=="COMPLETED").scalar() or 0
    expenses_today=db.session.query(db.func.coalesce(db.func.sum(Expense.amount),0)).filter(Expense.business_id==business_id,db.func.date(Expense.incurred_at)==db.func.current_date()).scalar() or 0
    cogs_today=db.session.query(db.func.coalesce(db.func.sum((-InventoryTransaction.quantity)*InventoryTransaction.unit_cost),0)).join(Store,Store.id==InventoryTransaction.store_id).filter(Store.business_id==business_id,InventoryTransaction.transaction_type=="SALE",InventoryTransaction.quantity<0,today).scalar() or 0
    low_stock=(StoreProduct.query.filter(StoreProduct.stock_quantity<=StoreProduct.reorder_level).join(Product).join(Store).filter(Store.business_id==business_id).count())
    products_online=(StoreProduct.query.join(Store).filter(Store.business_id==business_id,StoreProduct.is_available.is_(True),StoreProduct.available_online.is_(True)).count())
    unresolved_errors=SystemError.query.filter_by(business_id=business_id,resolved=False).count()
    customers_count=Customer.query.filter_by(business_id=business_id,is_active=True).count()
    staff_count=User.query.filter_by(business_id=business_id,is_active=True).count()
    supplier_count=Supplier.query.filter_by(business_id=business_id,is_active=True).count()
    purchase_open=PurchaseOrder.query.filter(PurchaseOrder.business_id==business_id,PurchaseOrder.status.in_(["DRAFT","ORDERED","PARTIALLY_RECEIVED"])).count()
    reserved_units=db.session.query(db.func.coalesce(db.func.sum(StoreProduct.reserved_quantity),0)).join(Store,Store.id==StoreProduct.store_id).filter(Store.business_id==business_id).scalar() or 0
    inventory_cost_value=db.session.query(db.func.coalesce(db.func.sum(StoreProduct.stock_quantity*StoreProduct.cost_price),0)).join(Store,Store.id==StoreProduct.store_id).filter(Store.business_id==business_id).scalar() or 0
    recent=Sale.query.filter_by(business_id=business_id).order_by(Sale.created_at.desc()).limit(10).all()
    gross_profit_today=Decimal(str(sales_today))-Decimal(str(cogs_today))
    return render_template("admin/dashboard.html",sales_total=Decimal(str(sales_total)),today_sales=Decimal(str(sales_today)),expenses_today=Decimal(str(expenses_today)),gross_profit_today=gross_profit_today,net_result_today=gross_profit_today-Decimal(str(expenses_today)),low_stock=low_stock,products_online=products_online,unresolved_errors=unresolved_errors,customers_count=customers_count,staff_count=staff_count,supplier_count=supplier_count,purchase_open=purchase_open,reserved_units=reserved_units,inventory_cost_value=inventory_cost_value,recent=recent)

@bp.get(f"{ADMIN_BASE}/android-gateway")
@bp.get(f"{ADMIN_BASE}/payment-monitoring")
@admin_required()
def android_gateway_settings():
    """Admin-only connection page for the existing Android SMS gateway.

    This page configures no payment decisions; it only exposes the server URL
    and shared secret-bearing endpoint that the existing Android app needs to
    send its live SMS telemetry to Denmart.
    """
    business_id = current_user.business_id
    setting = SystemSetting.query.filter_by(
        business_id=business_id, key="android_gateway_secret"
    ).first()
    configured = str(
        current_app.config.get("ANDROID_GATEWAY_SHARED_SECRET")
        or current_app.config.get("PAYMENT_GATEWAY_SHARED_SECRET")
        or ""
    ).strip()
    secret = str((setting.value if setting and setting.value else configured) or "").strip()
    if not secret:
        secret = secrets.token_urlsafe(32)
        setting = setting or SystemSetting(business_id=business_id, key="android_gateway_secret")
        setting.value = secret
        db.session.add(setting)
        db.session.commit()

    public_base = str(current_app.config.get("PUBLIC_BASE_URL") or "").rstrip("/")
    if public_base:
        sms_endpoint = f"{public_base}{url_for('api.android_gateway_sms')}"
        ping_endpoint = f"{public_base}{url_for('api.android_gateway_ping')}"
    else:
        sms_endpoint = url_for("api.android_gateway_sms", _external=True)
        ping_endpoint = url_for("api.android_gateway_ping", _external=True)
    separator = "&" if "?" in sms_endpoint else "?"
    setup_link = f"{sms_endpoint}{separator}key={secret}"
    ping_separator = "&" if "?" in ping_endpoint else "?"
    ping_link = f"{ping_endpoint}{ping_separator}key={secret}"
    return render_template(
        "admin/android_gateway.html",
        setup_link=setup_link,
        ping_link=ping_link,
        secret=secret,
    )


@bp.get(f"{ADMIN_BASE}/live-messages")
@admin_required()
def live_messages():
    since=now()-timedelta(minutes=5)
    messages=GatewaySmsMessage.query.filter_by(business_id=current_user.business_id).order_by(GatewaySmsMessage.received_at.desc()).limit(100).all()
    recent_count=GatewaySmsMessage.query.filter(GatewaySmsMessage.business_id==current_user.business_id,GatewaySmsMessage.received_at>=since).count()
    last_received=messages[0].received_at if messages else None
    return render_template("admin/live_messages.html",messages=messages,recent_count=recent_count,last_received=last_received)

@bp.get(f"{ADMIN_BASE}/api/live-messages")
@admin_required()
def live_messages_api():
    since=now()-timedelta(minutes=5)
    messages=GatewaySmsMessage.query.filter_by(business_id=current_user.business_id).order_by(GatewaySmsMessage.received_at.desc()).limit(100).all()
    rows=[]
    for m in messages:
        parsed=(m.raw_payload or {}).get("parsed") if isinstance(m.raw_payload,dict) else {}
        rows.append({"time":m.received_at.isoformat() if m.received_at else None,"event_id":m.event_id,"device":m.gateway_device_id,"sim":(m.sim_slot or 0)+1,"sender":m.sender or "Unknown sender","message":m.message,"mpesa":bool(m.is_mpesa_candidate),"transaction_code":(parsed or {}).get("transaction_code") or "","amount":(parsed or {}).get("amount") or "","payer_name":(parsed or {}).get("payer_name") or "","phone":(parsed or {}).get("normalized_phone") or ""})
    return jsonify(ok=True,recent_count=GatewaySmsMessage.query.filter(GatewaySmsMessage.business_id==current_user.business_id,GatewaySmsMessage.received_at>=since).count(),last_received=(messages[0].received_at.isoformat() if messages and messages[0].received_at else None),messages=rows)

@bp.get(f"{ADMIN_BASE}/products")
@admin_required("products.view")
def products():
    q = request.args.get("q", "").strip()
    store_id = request.args.get("store_id", "").strip()
    category_id = request.args.get("category_id", "").strip()
    query = StoreProduct.query.join(Product).join(Store).filter(Store.business_id == current_user.business_id)
    if store_id:
        query = query.filter(StoreProduct.store_id == store_id)
    if category_id:
        query = query.filter(Product.category_id == category_id)
    items = query.order_by(Product.name).limit(10000).all()
    if q and items:
        aliases_by_product = {}
        ids = [item.product_id for item in items]
        for alias in ProductAlias.query.filter(ProductAlias.product_id.in_(ids)).all():
            aliases_by_product.setdefault(alias.product_id, []).append(alias.alias)
        items = forgiving_rank(items, q, aliases_by_product=aliases_by_product, limit=5000, minimum=0.50)
    return render_template(
        "admin/products.html", items=items,
        stores=Store.query.filter_by(business_id=current_user.business_id).order_by(Store.name).all(),
        categories=Category.query.filter_by(business_id=current_user.business_id).order_by(Category.sort_order, Category.name).all(),
        q=q, store_id=store_id, category_id=category_id,
    )


@bp.post(f"{ADMIN_BASE}/products/resolve-images")
@admin_required("products.edit")
def resolve_product_images():
    """Audit the local catalogue cache without making a network request."""
    from services.product_images import has_public_product_image

    products = Product.query.filter_by(status="ACTIVE").order_by(Product.name).all()
    ready = sum(1 for product in products if has_public_product_image(product))
    missing = len(products) - ready
    flash(f"Real-image audit: {ready}/{len(products)} active products have a curated real image or an administrator upload. {missing} remain without a real image and will stay as neutral placeholders.", "success" if missing == 0 else "error")
    return redirect(url_for("admin.products"))


@bp.post(f"{ADMIN_BASE}/products/create")
@admin_required("products.create")
def create_product():
    name = request.form.get("name", "").strip()
    brand = request.form.get("brand", "").strip() or None
    category_id = request.form.get("category_id", "").strip() or None
    unit = request.form.get("unit", "unit").strip() or "unit"
    pack_size = request.form.get("pack_size", "").strip() or unit
    sku = request.form.get("sku", "").strip() or None
    barcode = request.form.get("barcode", "").strip() or None
    description = request.form.get("description", "").strip() or None
    image_url = request.form.get("image_url", "").strip() or None
    try:
        uploaded_image = _uploaded_product_image(request.files.get("product_image"), name or "Product")
        if uploaded_image:
            image_url = uploaded_image
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("admin.products"))
    store_id = request.form.get("store_id", "").strip() or None
    try:
        price = Decimal(request.form.get("selling_price", "0"))
        cost = Decimal(request.form.get("cost_price", "0"))
        stock = Decimal(request.form.get("stock_quantity", "0"))
    except InvalidOperation:
        flash("Enter valid cost, price and stock values.", "error")
        return redirect(url_for("admin.products"))
    if not name:
        flash("Product name is required.", "error")
        return redirect(url_for("admin.products"))
    if price <= 0 or cost < 0 or stock < 0:
        flash("Use a positive selling price and non-negative cost/stock.", "error")
        return redirect(url_for("admin.products"))
    if category_id and not Category.query.filter_by(id=category_id, business_id=current_user.business_id).first():
        flash("Select a valid category.", "error"); return redirect(url_for("admin.products"))
    if store_id and not Store.query.filter_by(id=store_id, business_id=current_user.business_id).first():
        flash("Select a valid mart.", "error"); return redirect(url_for("admin.products"))
    if sku and Product.query.filter_by(sku=sku).first():
        flash("That SKU is already in use.", "error"); return redirect(url_for("admin.products"))
    if barcode and Product.query.filter_by(barcode=barcode).first():
        flash("That barcode is already in use.", "error"); return redirect(url_for("admin.products"))
    from seed import slugify
    base_slug = slugify(name) or "product"
    slug = base_slug; n = 2
    while Product.query.filter_by(slug=slug).first():
        slug = f"{base_slug}-{n}"; n += 1
    product = Product(name=name, slug=slug, brand=brand, category_id=category_id, unit=unit, pack_size=pack_size,
                      sku=sku, barcode=barcode, description=description, image_url=image_url, status="ACTIVE",
                      search_keywords=" ".join(x for x in [name.lower(), brand.lower() if brand else ""] if x))
    db.session.add(product); db.session.flush()
    if image_url:
        try:
            _set_product_image(product, image_url)
        except ValueError as exc:
            db.session.rollback(); flash(str(exc), "error"); return redirect(url_for("admin.products"))
    stores = [db.session.get(Store, store_id)] if store_id else Store.query.filter_by(business_id=current_user.business_id, is_active=True).all()
    if not stores:
        db.session.rollback(); flash("Create an active mart before adding stock.", "error"); return redirect(url_for("admin.products"))
    for store in stores:
        db.session.add(StoreProduct(store_id=store.id, product_id=product.id, cost_price=cost, selling_price=price,
                                     minimum_price=price, maximum_price=price * Decimal("1.30"), stock_quantity=stock,
                                     reorder_level=5, is_available=True, available_online=True, available_pos=True))
    db.session.add(ProductAlias(product_id=product.id, alias=name, alias_type="SEARCH"))
    db.session.commit()
    audit("PRODUCT_CREATED", "Product", product.id, new_values={"name": name, "sku": sku, "barcode": barcode, "stores": len(stores)})
    flash(f"{name} added to {len(stores)} mart(s).", "success")
    return redirect(url_for("admin.product_edit", product_id=product.id, store_id=stores[0].id))


@bp.post(f"{ADMIN_BASE}/products/import")
@admin_required("products.create")
def import_products():
    upload = request.files.get("catalogue_file")
    store_id = request.form.get("store_id", "").strip() or None
    if not upload or not upload.filename.lower().endswith(".csv"):
        flash("Choose a CSV catalogue file.", "error"); return redirect(url_for("admin.products"))
    if store_id and not Store.query.filter_by(id=store_id, business_id=current_user.business_id).first():
        flash("Select a valid mart.", "error"); return redirect(url_for("admin.products"))
    text = upload.read().decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    required = {"name", "selling_price"}
    if not required.issubset({(h or "").strip().lower() for h in (reader.fieldnames or [])}):
        flash("CSV needs at least name,selling_price columns.", "error"); return redirect(url_for("admin.products"))
    from seed import slugify
    stores = [db.session.get(Store, store_id)] if store_id else Store.query.filter_by(business_id=current_user.business_id, is_active=True).all()
    created = updated = 0
    errors = []
    for line_no, raw in enumerate(reader, start=2):
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
        name = row.get("name", "")
        if not name: continue
        try:
            price = Decimal(row.get("selling_price", "0")); cost = Decimal(row.get("cost_price", "0") or "0"); stock = Decimal(row.get("stock_quantity", "0") or "0")
            if price <= 0 or cost < 0 or stock < 0: raise InvalidOperation
        except InvalidOperation:
            errors.append(f"Line {line_no}: invalid numeric values"); continue
        category = None
        category_name = row.get("category", "")
        if category_name:
            slug = slugify(category_name)
            category = Category.query.filter_by(business_id=current_user.business_id, slug=slug).first()
            if not category:
                category = Category(business_id=current_user.business_id, name=category_name, slug=slug, is_active=True); db.session.add(category); db.session.flush()
        sku = row.get("sku") or None; barcode = row.get("barcode") or None
        product = None
        if sku: product = Product.query.filter_by(sku=sku).first()
        if not product and barcode: product = Product.query.filter_by(barcode=barcode).first()
        if not product: product = Product.query.filter_by(slug=slugify(name)).first()
        if product:
            product.name = name; product.brand = row.get("brand") or product.brand; product.category_id = category.id if category else product.category_id
            product.unit = row.get("unit") or product.unit; product.pack_size = row.get("pack_size") or product.pack_size
            product.description = row.get("description") or product.description; product.image_url = row.get("image_url") or product.image_url
            if sku: product.sku = sku
            if barcode: product.barcode = barcode
            updated += 1
        else:
            base = slugify(name) or "product"; slug = base; n = 2
            while Product.query.filter_by(slug=slug).first(): slug = f"{base}-{n}"; n += 1
            product = Product(name=name, slug=slug, brand=row.get("brand") or None, category_id=category.id if category else None,
                              unit=row.get("unit") or "unit", pack_size=row.get("pack_size") or row.get("unit") or "unit",
                              sku=sku, barcode=barcode, description=row.get("description") or None, image_url=row.get("image_url") or None,
                              search_keywords=f"{name.lower()} {(row.get('brand') or '').lower()} {(category_name or '').lower()}".strip())
            db.session.add(product); db.session.flush(); db.session.add(ProductAlias(product_id=product.id, alias=name, alias_type="SEARCH")); created += 1
        for store in stores:
            sp = StoreProduct.query.filter_by(store_id=store.id, product_id=product.id).first()
            if not sp:
                sp = StoreProduct(store_id=store.id, product_id=product.id); db.session.add(sp)
            sp.cost_price = cost; sp.selling_price = price; sp.minimum_price = price; sp.maximum_price = price * Decimal("1.30")
            sp.stock_quantity = stock; sp.is_available = row.get("enabled", "1").lower() not in {"0", "no", "false"}
            sp.available_online = row.get("online", "1").lower() not in {"0", "no", "false"}; sp.available_pos = row.get("pos", "1").lower() not in {"0", "no", "false"}
    db.session.commit()
    audit("PRODUCT_CSV_IMPORTED", "Business", current_user.business_id, new_values={"created": created, "updated": updated, "errors": len(errors)})
    msg = f"Catalogue import complete: {created} added, {updated} updated."
    if errors: msg += f" {len(errors)} row(s) skipped."
    flash(msg, "success" if not errors else "error")
    return redirect(url_for("admin.products"))


@bp.get(f"{ADMIN_BASE}/products/export.csv")
@admin_required("backup.create")
def export_products_csv():
    rows = (StoreProduct.query.join(Product).join(Store).filter(Store.business_id == current_user.business_id)
            .order_by(Product.name, Store.name).limit(10000).all())
    out = io.StringIO(); writer = csv.writer(out)
    writer.writerow(["name","brand","sku","barcode","category","unit","pack_size","description","image_url","mart","mart_code","cost_price","selling_price","stock_quantity","online","pos","enabled"])
    for sp in rows:
        p = sp.product; cat = db.session.get(Category, p.category_id) if p.category_id else None
        writer.writerow([p.name,p.brand or "",p.sku or "",p.barcode or "",cat.name if cat else "",p.unit or "",p.pack_size or "",p.description or "",p.image_url or "",sp.store.name,sp.store.code,sp.cost_price,sp.selling_price,sp.stock_quantity,int(sp.available_online),int(sp.available_pos),int(sp.is_available)])
    audit("CATALOGUE_CSV_EXPORTED", "Business", current_user.business_id, new_values={"rows": len(rows)})
    return Response(out.getvalue(), mimetype="text/csv", headers={"Content-Disposition":"attachment; filename=denmart-catalogue.csv"})


@bp.get(f"{ADMIN_BASE}/products/<product_id>/edit")
@admin_required("products.edit")
def product_edit(product_id):
    product = db.session.get(Product, product_id)
    if not product:
        return "Not found", 404
    owns_store = Store.query.filter_by(business_id=current_user.business_id).filter(Store.id.in_([sp.store_id for sp in StoreProduct.query.filter_by(product_id=product.id).all()])).first() if StoreProduct.query.filter_by(product_id=product.id).count() else None
    if not Category.query.filter_by(id=product.category_id, business_id=current_user.business_id).first() if product.category_id else False:
        pass
    stores = Store.query.filter_by(business_id=current_user.business_id).order_by(Store.name).all()
    store_id = request.args.get("store_id", "").strip()
    selected_store = next((s for s in stores if s.id == store_id), None) or (owns_store if owns_store and owns_store.business_id == current_user.business_id else (stores[0] if stores else None))
    if product.category_id and not Category.query.filter_by(id=product.category_id, business_id=current_user.business_id).first():
        return "Forbidden", 403
    for sp in StoreProduct.query.filter_by(product_id=product.id).all():
        if sp.store.business_id == current_user.business_id:
            continue
        return "Forbidden", 403
    return render_template("admin/product_edit.html", product=product, stores=stores, categories=Category.query.filter_by(business_id=current_user.business_id).order_by(Category.sort_order, Category.name).all(),
                           selected_store=selected_store, store_product=(StoreProduct.query.filter_by(product_id=product.id, store_id=selected_store.id).first() if selected_store else None))


@bp.post(f"{ADMIN_BASE}/products/<product_id>/edit")
@admin_required("products.edit")
def save_product(product_id):
    product = db.session.get(Product, product_id)
    if not product:
        return "Not found", 404
    if product.category_id and not Category.query.filter_by(id=product.category_id, business_id=current_user.business_id).first():
        return "Forbidden", 403
    old = {"name": product.name, "brand": product.brand, "sku": product.sku, "barcode": product.barcode, "status": product.status, "image_url": product.image_url}
    product.name = request.form.get("name", product.name).strip() or product.name
    product.brand = request.form.get("brand", "").strip() or None
    product.category_id = request.form.get("category_id", "").strip() or None
    product.unit = request.form.get("unit", "unit").strip() or "unit"
    product.pack_size = request.form.get("pack_size", "").strip() or product.unit
    product.sku = request.form.get("sku", "").strip() or None
    product.barcode = request.form.get("barcode", "").strip() or None
    product.description = request.form.get("description", "").strip() or None
    submitted_image_url = request.form.get("image_url", "").strip()
    try:
        uploaded_image = _uploaded_product_image(request.files.get("product_image"), product.name)
    except ValueError as exc:
        db.session.rollback(); flash(str(exc), "error")
        return redirect(url_for("admin.product_edit", product_id=product.id, store_id=request.form.get("store_id", "").strip()))
    try:
        if uploaded_image:
            _set_product_image(product, uploaded_image)
        elif submitted_image_url:
            _set_product_image(product, submitted_image_url, source_type="ADMIN_URL")
        elif request.form.get("remove_image") == "1":
            product.image_url = None
            ProductImage.query.filter_by(product_id=product.id).delete(synchronize_session=False)
    except ValueError as exc:
        db.session.rollback(); flash(str(exc), "error")
        return redirect(url_for("admin.product_edit", product_id=product.id, store_id=request.form.get("store_id", "").strip()))
    product.status = "ACTIVE" if request.form.get("status") == "ACTIVE" else "ARCHIVED"
    product.search_keywords = " ".join(x for x in [product.name.lower(), (product.brand or "").lower(), (product.description or "").lower()] if x)
    sp_store_id = request.form.get("store_id", "").strip()
    sp = StoreProduct.query.filter_by(product_id=product.id, store_id=sp_store_id).first()
    if sp and sp.store.business_id == current_user.business_id:
        try:
            sp.cost_price = Decimal(request.form.get("cost_price", str(sp.cost_price)))
            sp.selling_price = Decimal(request.form.get("selling_price", str(sp.selling_price)))
            sp.minimum_price = Decimal(request.form.get("minimum_price", str(sp.minimum_price or sp.selling_price)))
            maxv = request.form.get("maximum_price", "").strip(); sp.maximum_price = Decimal(maxv) if maxv else None
            sp.stock_quantity = Decimal(request.form.get("stock_quantity", str(sp.stock_quantity)))
            sp.reorder_level = Decimal(request.form.get("reorder_level", str(sp.reorder_level or 0)))
        except InvalidOperation:
            db.session.rollback(); flash("Check the numeric mart values.", "error"); return redirect(url_for("admin.product_edit", product_id=product.id, store_id=sp_store_id))
        sp.is_available = request.form.get("enabled") == "1" and product.status == "ACTIVE"
        sp.available_online = request.form.get("online") == "1" and sp.is_available
        sp.available_pos = request.form.get("pos") == "1" and sp.is_available
    alias = ProductAlias.query.filter_by(product_id=product.id, alias=product.name).first()
    if not alias: db.session.add(ProductAlias(product_id=product.id, alias=product.name, alias_type="SEARCH"))
    db.session.commit()
    audit("PRODUCT_UPDATED", "Product", product.id, old_values=old, new_values={"name": product.name, "brand": product.brand, "sku": product.sku, "barcode": product.barcode, "status": product.status, "image_url": product.image_url})
    flash("Product updated.", "success")
    return redirect(url_for("admin.product_edit", product_id=product.id, store_id=sp_store_id))


@bp.post(f"{ADMIN_BASE}/products/<product_id>/delete")
@admin_required("products.delete")
def delete_product(product_id):
    product = db.session.get(Product, product_id)
    if not product:
        flash("Product not found.", "error"); return redirect(url_for("admin.products"))
    references = (SaleItem.query.filter_by(product_id=product.id).count() + InventoryTransaction.query.filter_by(product_id=product.id).count())
    old_name = product.name
    if references:
        product.status = "ARCHIVED"
        StoreProduct.query.filter_by(product_id=product.id).update({"is_available": False, "available_online": False, "available_pos": False})
        db.session.commit()
        audit("PRODUCT_ARCHIVED", "Product", product.id, new_values={"reason":"historical references", "references": references})
        flash(f"{old_name} was archived because it has transaction history.", "success")
    else:
        StoreProduct.query.filter_by(product_id=product.id).delete(synchronize_session=False)
        ProductAlias.query.filter_by(product_id=product.id).delete(synchronize_session=False)
        ProductImage.query.filter_by(product_id=product.id).delete(synchronize_session=False)
        db.session.delete(product); db.session.commit()
        audit("PRODUCT_DELETED", "Product", product_id, new_values={"name": old_name})
        flash(f"{old_name} deleted.", "success")
    return redirect(url_for("admin.products"))


@bp.post(f"{ADMIN_BASE}/products/<store_product_id>/availability")
@admin_required("products.edit")
def toggle_product_availability(store_product_id):
    item = db.session.get(StoreProduct, store_product_id)
    if not item or item.store.business_id != current_user.business_id:
        return "Not found", 404
    item.available_online = request.form.get("online") == "1"
    item.available_pos = request.form.get("pos") == "1"
    item.is_available = request.form.get("enabled") == "1"
    db.session.commit()
    audit("PRODUCT_VISIBILITY_CHANGED", "StoreProduct", item.id,
          new_values={"online": item.available_online, "pos": item.available_pos, "enabled": item.is_available})
    flash("Product availability updated.", "success")
    return redirect(url_for("admin.products"))


@bp.get(f"{ADMIN_BASE}/products/<store_product_id>/price")
@admin_required("products.edit")
def update_price_get(store_product_id):
    return redirect(url_for("admin.products"))


@bp.post(f"{ADMIN_BASE}/products/<store_product_id>/price")
@admin_required("products.edit")
def update_price(store_product_id):
    item = db.session.get(StoreProduct, store_product_id)
    if not item or item.store.business_id != current_user.business_id:
        return "Not found", 404
    try:
        new_price = Decimal(request.form.get("selling_price", "0"))
    except InvalidOperation:
        flash("Invalid price.", "error"); return redirect(url_for("admin.products"))
    if new_price <= 0:
        flash("Price must be greater than zero.", "error"); return redirect(url_for("admin.products"))
    old = Decimal(str(item.selling_price))
    item.selling_price = new_price
    db.session.add(PriceHistory(store_product_id=item.id, old_price=old, new_price=new_price,
                                reason="Admin adjustment", changed_by=current_user.id))
    db.session.commit()
    audit("PRODUCT_PRICE_CHANGED", "StoreProduct", item.id, old_values={"price": str(old)}, new_values={"price": str(new_price)})
    flash("Price updated.", "success")
    return redirect(url_for("admin.products"))



@bp.get(f"{ADMIN_BASE}/inventory")
@bp.post(f"{ADMIN_BASE}/inventory/adjust")
@admin_required("inventory.view")
def inventory():
    business_id = current_user.business_id
    stores = Store.query.filter_by(business_id=business_id).order_by(Store.name).all()
    store_id = (request.args.get("store_id") or request.form.get("store_id") or "").strip()
    selected_store = db.session.get(Store, store_id) if store_id else None
    if selected_store and selected_store.business_id != business_id:
        selected_store = None
        store_id = ""
    if request.method == "POST":
        if not current_user.has_permission("inventory.adjust") and current_user.role.name != "OWNER":
            return "Forbidden", 403
        product_id = request.form.get("product_id", "").strip()
        try:
            delta = Decimal(request.form.get("quantity_delta", "0"))
            unit_cost = Decimal(request.form.get("unit_cost", "0") or "0")
        except InvalidOperation:
            flash("Quantity and cost must be valid numbers.", "error")
            return redirect(url_for("admin.inventory", store_id=store_id))
        if not selected_store or not product_id or delta == 0 or unit_cost < 0:
            flash("Choose a mart, product and a non-zero quantity change.", "error")
            return redirect(url_for("admin.inventory", store_id=store_id))
        product = db.session.get(Product, product_id)
        if not product:
            flash("Product not found.", "error")
            return redirect(url_for("admin.inventory", store_id=store_id))
        sp = StoreProduct.query.filter_by(store_id=selected_store.id, product_id=product.id).with_for_update().first()
        if not sp:
            sp = StoreProduct(store_id=selected_store.id, product_id=product.id, cost_price=unit_cost, selling_price=Decimal("0"), stock_quantity=0, reserved_quantity=0)
            db.session.add(sp); db.session.flush()
        current_stock = Decimal(sp.stock_quantity or 0)
        reserved = Decimal(sp.reserved_quantity or 0)
        new_stock = current_stock + delta
        if new_stock < 0 or new_stock < reserved:
            flash(f"Stock cannot fall below reserved quantity ({reserved}).", "error")
            return redirect(url_for("admin.inventory", store_id=store_id))
        old = {"stock": str(current_stock), "cost": str(sp.cost_price or 0)}
        sp.stock_quantity = new_stock
        if unit_cost > 0:
            sp.cost_price = unit_cost
        txn_type = "ADJUSTMENT_IN" if delta > 0 else "ADJUSTMENT_OUT"
        db.session.add(InventoryTransaction(
            store_id=selected_store.id, product_id=product.id, transaction_type=txn_type,
            quantity=delta, unit_cost=sp.cost_price, reference_type="ADMIN_ADJUSTMENT",
            reference_id=sp.id, notes=request.form.get("notes", "").strip()[:500] or None, created_by=current_user.id,
        ))
        db.session.commit()
        audit("INVENTORY_ADJUSTED", "StoreProduct", sp.id, old_values=old, new_values={"stock": str(sp.stock_quantity), "cost": str(sp.cost_price), "delta": str(delta)})
        flash(f"{product.name}: stock is now {sp.stock_quantity} at {selected_store.name}.", "success")
        return redirect(url_for("admin.inventory", store_id=selected_store.id))

    q = (request.args.get("q") or "").strip()
    low = request.args.get("low") == "1"
    query = StoreProduct.query.join(Store).join(Product).filter(Store.business_id == business_id)
    if selected_store:
        query = query.filter(StoreProduct.store_id == selected_store.id)
    if low:
        query = query.filter(StoreProduct.stock_quantity <= StoreProduct.reorder_level)
    rows = query.order_by((StoreProduct.stock_quantity - StoreProduct.reorder_level).asc(), Product.name.asc()).limit(10000).all()
    if q and rows:
        aliases_by_product = {}
        ids = [row.product_id for row in rows]
        for alias in ProductAlias.query.filter(ProductAlias.product_id.in_(ids)).all():
            aliases_by_product.setdefault(alias.product_id, []).append(alias.alias)
        rows = forgiving_rank(rows, q, aliases_by_product=aliases_by_product, limit=400, minimum=0.48)
    else:
        rows = rows[:400]
    total_cost = sum((Decimal(r.stock_quantity or 0) * Decimal(r.cost_price or 0) for r in rows), Decimal("0"))
    total_retail = sum((Decimal(r.stock_quantity or 0) * Decimal(r.selling_price or 0) for r in rows), Decimal("0"))
    low_count = sum(1 for r in rows if Decimal(r.stock_quantity or 0) <= Decimal(r.reorder_level or 0))

    def stock_layers(sp):
        # Inventory transactions form a lightweight FIFO ledger without a schema
        # migration. Existing unlogged stock is treated as the oldest/opening layer;
        # each later positive receipt/adjustment becomes a new layer. Sales consume
        # the oldest layer first, so the newest layer remains visually distinct.
        txns = (InventoryTransaction.query.filter_by(store_id=sp.store_id, product_id=sp.product_id)
                .order_by(InventoryTransaction.created_at.asc(), InventoryTransaction.id.asc()).all())
        net_tx = sum((Decimal(t.quantity or 0) for t in txns), Decimal("0"))
        opening = Decimal(sp.stock_quantity or 0) - net_tx
        layers = []
        if opening > 0:
            layers.append({"qty": opening, "remaining": opening, "when": sp.created_at, "label": "Opening stock", "source": "OLD"})
        for t in txns:
            qty = Decimal(t.quantity or 0)
            if qty > 0:
                layers.append({"qty": qty, "remaining": qty, "when": t.created_at,
                               "label": (t.notes or t.transaction_type or "Stock received").strip()[:80],
                               "source": "NEW" if t.transaction_type in {"PURCHASE", "ADJUSTMENT", "ADJUSTMENT_IN", "RECEIVE", "SCAN_STOCK"} else "OLD"})
            elif qty < 0:
                to_consume = -qty
                for layer in layers:
                    if to_consume <= 0:
                        break
                    take = min(layer["remaining"], to_consume)
                    layer["remaining"] -= take
                    to_consume -= take
        remaining = [x for x in layers if x["remaining"] > 0]
        remaining.sort(key=lambda x: (x["when"] or sp.created_at), reverse=True)
        # The newest surviving inbound layer is the visible NEW STOCK layer. Everything
        # underneath it is older stock; when those layers are exhausted the divider vanishes.
        for i, layer in enumerate(remaining):
            layer["is_newest"] = i == 0 and layer["source"] == "NEW"
        return remaining

    display_rows = [{"item": r, "layers": stock_layers(r)} for r in rows]
    return render_template("admin/inventory.html", rows=rows, display_rows=display_rows, stores=stores, store_id=store_id, selected_store=selected_store,
                           q=q, low=low, total_cost=total_cost, total_retail=total_retail, low_count=low_count)


@bp.route(f"{ADMIN_BASE}/categories", methods=["GET", "POST"])
@admin_required("products.edit")
def categories():
    business_id = current_user.business_id
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            flash("Category name is required.", "error")
        elif Category.query.filter_by(business_id=business_id, name=name).first():
            flash("That category already exists.", "error")
        else:
            slug = re_slug = "-".join(name.lower().split())[:140]
            if Category.query.filter_by(business_id=business_id, slug=slug).first():
                slug = f"{slug}-{secrets.token_hex(2)}"
            db.session.add(Category(business_id=business_id, name=name, slug=slug, description=request.form.get("description", "").strip() or None, sort_order=int(request.form.get("sort_order", 0) or 0), is_active=True))
            db.session.commit(); audit("CATEGORY_CREATED", "Category", None, new_values={"name": name}); flash("Category created.", "success")
    cats = Category.query.filter_by(business_id=business_id).order_by(Category.sort_order, Category.name).all()
    usage = {c.id: Product.query.filter_by(category_id=c.id).count() for c in cats}
    return render_template("admin/categories.html", categories=cats, usage=usage)


@bp.post(f"{ADMIN_BASE}/categories/<category_id>/toggle")
@admin_required("products.edit")
def toggle_category(category_id):
    category = db.session.get(Category, category_id)
    if not category or category.business_id != current_user.business_id:
        return "Not found", 404
    category.is_active = not category.is_active
    db.session.commit(); audit("CATEGORY_STATUS_CHANGED", "Category", category.id, new_values={"active": category.is_active})
    flash(f"{category.name} is now {'active' if category.is_active else 'hidden'}.", "success")
    return redirect(url_for("admin.categories"))


@bp.route(f"{ADMIN_BASE}/suppliers", methods=["GET", "POST"])
@admin_required("inventory.view")
def suppliers():
    business_id = current_user.business_id
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            flash("Supplier name is required.", "error")
        else:
            supplier = Supplier(business_id=business_id, name=name, phone=request.form.get("phone", "").strip() or None,
                                email=request.form.get("email", "").strip() or None, address=request.form.get("address", "").strip() or None,
                                tax_identifier=request.form.get("tax_identifier", "").strip() or None, is_active=True)
            db.session.add(supplier); db.session.commit(); audit("SUPPLIER_CREATED", "Supplier", supplier.id, new_values={"name": name}); flash("Supplier added.", "success")
            return redirect(url_for("admin.suppliers"))
    rows = Supplier.query.filter_by(business_id=business_id).order_by(Supplier.is_active.desc(), Supplier.name.asc()).all()
    return render_template("admin/suppliers.html", suppliers=rows)


@bp.post(f"{ADMIN_BASE}/suppliers/<supplier_id>/toggle")
@admin_required("inventory.view")
def toggle_supplier(supplier_id):
    supplier = db.session.get(Supplier, supplier_id)
    if not supplier or supplier.business_id != current_user.business_id:
        return "Not found", 404
    supplier.is_active = not supplier.is_active
    db.session.commit(); audit("SUPPLIER_STATUS_CHANGED", "Supplier", supplier.id, new_values={"active": supplier.is_active})
    return redirect(url_for("admin.suppliers"))


@bp.route(f"{ADMIN_BASE}/purchases", methods=["GET", "POST"])
@admin_required("inventory.view")
def purchases():
    business_id = current_user.business_id
    stores = Store.query.filter_by(business_id=business_id).order_by(Store.name).all()
    suppliers = Supplier.query.filter_by(business_id=business_id, is_active=True).order_by(Supplier.name).all()
    products = Product.query.filter_by(status="ACTIVE").order_by(Product.name).limit(1500).all()
    if request.method == "POST":
        store = db.session.get(Store, request.form.get("store_id", ""))
        supplier = db.session.get(Supplier, request.form.get("supplier_id", ""))
        product = db.session.get(Product, request.form.get("product_id", ""))
        try:
            qty = Decimal(request.form.get("quantity", "0")); unit_cost = Decimal(request.form.get("unit_cost", "0")); tax = Decimal(request.form.get("tax", "0") or "0")
        except InvalidOperation:
            qty = Decimal("0"); unit_cost = Decimal("0"); tax = Decimal("0")
        if not store or store.business_id != business_id or not supplier or supplier.business_id != business_id or not product or qty <= 0 or unit_cost < 0 or tax < 0:
            flash("Select valid mart, supplier, product, quantity and cost.", "error")
        else:
            subtotal = qty * unit_cost
            ref = f"PO-{now().strftime('%Y%m%d')}-{secrets.token_hex(3).upper()}"
            po = PurchaseOrder(business_id=business_id, store_id=store.id, supplier_id=supplier.id, reference_number=ref,
                               status="ORDERED", subtotal=subtotal, tax=tax, total=subtotal + tax, created_by=current_user.id)
            db.session.add(po); db.session.flush()
            db.session.add(PurchaseOrderItem(purchase_order_id=po.id, product_id=product.id, quantity=qty, unit_cost=unit_cost, tax=tax, total=subtotal + tax))
            db.session.commit(); audit("PURCHASE_ORDER_CREATED", "PurchaseOrder", po.id, new_values={"reference": ref, "total": str(po.total)})
            flash(f"Purchase order {ref} created.", "success")
            return redirect(url_for("admin.purchases"))
    rows = PurchaseOrder.query.filter_by(business_id=business_id).order_by(PurchaseOrder.created_at.desc()).limit(250).all()
    items = {}
    for po in rows:
        items[po.id] = PurchaseOrderItem.query.filter_by(purchase_order_id=po.id).all()
    stores_map = {s.id: s.name for s in stores}; suppliers_map = {s.id: s.name for s in suppliers}
    product_map = {p.id: p.name for p in products}
    return render_template("admin/purchases.html", purchases=rows, stores=stores, suppliers=suppliers, products=products, items=items,
                           stores_map=stores_map, suppliers_map=suppliers_map, product_map=product_map)


@bp.post(f"{ADMIN_BASE}/purchases/<purchase_id>/receive")
@admin_required("inventory.adjust")
def receive_purchase(purchase_id):
    po = db.session.get(PurchaseOrder, purchase_id)
    if not po or po.business_id != current_user.business_id:
        return "Not found", 404
    if po.status == "RECEIVED":
        flash("That purchase order is already received.", "error")
        return redirect(url_for("admin.purchases"))
    if po.status == "CANCELLED":
        flash("Cancelled purchase orders cannot be received.", "error")
        return redirect(url_for("admin.purchases"))
    lines = PurchaseOrderItem.query.filter_by(purchase_order_id=po.id).all()
    for line in lines:
        sp = StoreProduct.query.filter_by(store_id=po.store_id, product_id=line.product_id).first()
        if not sp:
            sp = StoreProduct(store_id=po.store_id, product_id=line.product_id, stock_quantity=0, reserved_quantity=0,
                              cost_price=line.unit_cost, selling_price=Decimal("0"), minimum_price=0,
                              is_available=False, available_online=False, available_pos=False)
            db.session.add(sp); db.session.flush()
        sp.stock_quantity = Decimal(sp.stock_quantity or 0) + Decimal(line.quantity)
        sp.cost_price = Decimal(line.unit_cost)
        db.session.add(InventoryTransaction(store_id=po.store_id, product_id=line.product_id, transaction_type="PURCHASE",
                                            quantity=Decimal(line.quantity), unit_cost=Decimal(line.unit_cost), reference_type="PURCHASE_ORDER",
                                            reference_id=po.id, created_by=current_user.id, notes=po.reference_number))
    po.status = "RECEIVED"
    db.session.commit(); audit("PURCHASE_RECEIVED", "PurchaseOrder", po.id, new_values={"status": po.status})
    flash(f"{po.reference_number} received and stock updated.", "success")
    return redirect(url_for("admin.purchases"))


@bp.get(f"{ADMIN_BASE}/customers")
@admin_required("reports.view")
def customers():
    business_id=current_user.business_id
    q=(request.args.get("q") or "").strip()
    query=Customer.query.filter_by(business_id=business_id)
    if q:
        needle=f"%{q}%"
        query=query.filter(or_(Customer.name.ilike(needle),Customer.phone.ilike(needle),Customer.email.ilike(needle)))
    rows=query.order_by(Customer.created_at.desc()).limit(500).all()
    ids=[c.id for c in rows]
    accounts=LoyaltyAccount.query.filter(LoyaltyAccount.business_id==business_id,LoyaltyAccount.customer_id.in_(ids)).all() if ids else []
    amap={a.customer_id:a for a in accounts}
    data=[]
    for customer in rows:
        account=amap.get(customer.id)
        data.append({"customer":customer,"points":account.points_balance if account else 0,"lifetime_points":account.lifetime_points if account else 0})
    return render_template("admin/customers.html",rows=data,q=q)

@bp.post(f"{ADMIN_BASE}/customers/<customer_id>/loyalty")
@admin_required("reports.view")
def adjust_loyalty(customer_id):
    customer = db.session.get(Customer, customer_id)
    if not customer or customer.business_id != current_user.business_id:
        return "Not found", 404
    try:
        points = int(request.form.get("points", "0"))
    except (TypeError, ValueError):
        points = 0
    if not points or abs(points) > 100000:
        flash("Enter a non-zero adjustment of up to 100,000 points.", "error")
        return redirect(url_for("admin.customers"))
    account = LoyaltyAccount.query.filter_by(business_id=current_user.business_id, customer_id=customer.id).first()
    if not account:
        account = LoyaltyAccount(business_id=current_user.business_id, customer_id=customer.id, points_balance=0, lifetime_points=0)
        db.session.add(account); db.session.flush()
    new_balance = account.points_balance + points
    if new_balance < 0:
        flash("Loyalty balance cannot go below zero.", "error")
        return redirect(url_for("admin.customers"))
    account.points_balance = new_balance
    if points > 0:
        account.lifetime_points += points
    db.session.add(LoyaltyTransaction(business_id=current_user.business_id, customer_id=customer.id, points=points,
                                      transaction_type="ADJUSTMENT", note="Administrator loyalty adjustment"))
    db.session.commit(); audit("LOYALTY_ADJUSTED", "Customer", customer.id, new_values={"points": points, "balance": new_balance})
    flash(f"{customer.name}: loyalty balance is now {new_balance} points.", "success")
    return redirect(url_for("admin.customers"))


@bp.get(f"{ADMIN_BASE}/shifts")
@admin_required("reports.view")
def shifts():
    business_id = current_user.business_id
    rows = (Shift.query.join(Store, Store.id == Shift.store_id).join(User, User.id == Shift.cashier_id)
            .filter(Store.business_id == business_id).order_by(Shift.opened_at.desc()).limit(300).all())
    stores = {s.id: s for s in Store.query.filter_by(business_id=business_id).all()}
    users = {u.id: u for u in User.query.filter_by(business_id=business_id).all()}
    return render_template("admin/shifts.html", shifts=rows, store_map=stores, user_map=users)


# ---------------------------------------------------------------------------
# Full control-centre management routes. These were intentionally kept out of
# the public shopping/merchant blueprints so the admin remains one protected
# workspace.
# ---------------------------------------------------------------------------

@bp.route(f"{ADMIN_BASE}/users", methods=["GET", "POST"])
@admin_required("users.manage")
def users():
    business_id = current_user.business_id
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        role_id = request.form.get("role_id") or ""
        store_id = request.form.get("store_id") or None
        email = (request.form.get("email") or "").strip() or None
        phone = (request.form.get("phone") or "").strip() or None
        role = db.session.get(Role, role_id)
        store = db.session.get(Store, store_id) if store_id else None
        if not name or not username or len(password) < 8 or not role:
            flash("Name, username, a role and a password of at least 8 characters are required.", "error")
        elif role.name == "OWNER":
            flash("Use the existing master administrator account for owner access. Create staff as Manager, Cashier, Stock Controller or another staff role.", "error")
        elif User.query.filter_by(username=username).first():
            flash("That username is already in use.", "error")
        elif email and User.query.filter(User.email == email).first():
            flash("That email is already in use.", "error")
        elif store and store.business_id != business_id:
            flash("The selected mart does not belong to this business.", "error")
        else:
            user = User(
                business_id=business_id, store_id=store.id if store else None,
                name=name, username=username, email=email, phone=phone,
                role_id=role.id, is_active=True,
            )
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            audit("STAFF_CREATED", "User", user.id, new_values={"name": name, "username": username, "role": role.name, "store_id": store.id if store else None})
            flash(f"{name} can now sign in as {role.name.replace('_', ' ').title()}.", "success")
            return redirect(url_for("admin.users"))
    roles = Role.query.filter(Role.name != "OWNER").order_by(Role.name).all()
    stores = Store.query.filter_by(business_id=business_id).order_by(Store.name).all()
    rows = User.query.filter_by(business_id=business_id).order_by(User.is_active.desc(), User.name.asc()).all()
    return render_template("admin/users.html", users=rows, roles=roles, stores=stores)


@bp.post(f"{ADMIN_BASE}/users/<user_id>/toggle")
@admin_required("users.manage")
def toggle_user(user_id):
    user = db.session.get(User, user_id)
    if not user or user.business_id != current_user.business_id:
        return "Not found", 404
    if user.id == current_user.id:
        flash("You cannot disable the account you are currently using.", "error")
        return redirect(url_for("admin.users"))
    user.is_active = not user.is_active
    db.session.commit()
    audit("STAFF_STATUS_CHANGED", "User", user.id, new_values={"active": user.is_active})
    flash(f"{user.name} is now {'active' if user.is_active else 'disabled'}.", "success")
    return redirect(url_for("admin.users"))


@bp.post(f"{ADMIN_BASE}/users/<user_id>/reset-password")
@admin_required("users.manage")
def reset_user_password(user_id):
    user = db.session.get(User, user_id)
    if not user or user.business_id != current_user.business_id or user.id == current_user.id:
        return "Not found", 404
    password = request.form.get("password") or ""
    if len(password) < 8:
        flash("New password must be at least 8 characters.", "error")
    else:
        user.set_password(password)
        db.session.commit()
        audit("STAFF_PASSWORD_RESET", "User", user.id)
        flash(f"Password reset for {user.name}.", "success")
    return redirect(url_for("admin.users"))


@bp.route(f"{ADMIN_BASE}/stores", methods=["GET", "POST"])
@admin_required("inventory.view")
def stores():
    business_id = current_user.business_id
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        code = (request.form.get("code") or "").strip().upper()
        phone = (request.form.get("phone") or "").strip() or None
        address = (request.form.get("address") or "").strip() or None
        def _store_num(v):
            try:
                return float(v) if str(v or "").strip() else None
            except ValueError:
                return None
        latitude = _store_num(request.form.get("latitude"))
        longitude = _store_num(request.form.get("longitude"))
        if latitude is not None and not -90 <= latitude <= 90:
            latitude = None
        if longitude is not None and not -180 <= longitude <= 180:
            longitude = None
        if not name or not code:
            flash("Mart name and code are required.", "error")
        elif Store.query.filter_by(business_id=business_id, code=code).first():
            flash("That mart code is already in use.", "error")
        else:
            store = Store(business_id=business_id, name=name, code=code, phone=phone, address=address, latitude=latitude, longitude=longitude, is_active=True)
            db.session.add(store)
            db.session.commit()
            audit("MART_CREATED", "Store", store.id, new_values={"name": name, "code": code})
            flash(f"{name} created.", "success")
            return redirect(url_for("admin.stores"))
    rows = Store.query.filter_by(business_id=business_id).order_by(Store.is_active.desc(), Store.name.asc()).all()
    return render_template("admin/stores.html", stores=rows)


@bp.post(f"{ADMIN_BASE}/stores/<store_id>/edit")
@admin_required("inventory.view")
def edit_store(store_id):
    store = db.session.get(Store, store_id)
    if not store or store.business_id != current_user.business_id:
        return "Not found", 404
    name = (request.form.get("name") or "").strip()
    code = (request.form.get("code") or "").strip().upper()
    if not name or not code:
        flash("Mart name and code are required.", "error")
        return redirect(url_for("admin.stores"))
    duplicate = Store.query.filter(Store.business_id == store.business_id, Store.code == code, Store.id != store.id).first()
    if duplicate:
        flash("That mart code belongs to another mart.", "error")
        return redirect(url_for("admin.stores"))
    def _num(v):
        try:
            return float(v) if str(v or "").strip() else None
        except ValueError:
            return None
    old = {"name": store.name, "code": store.code, "phone": store.phone, "address": store.address, "active": store.is_active}
    store.name = name; store.code = code; store.phone = (request.form.get("phone") or "").strip() or None
    store.address = (request.form.get("address") or "").strip() or None
    store.latitude = _num(request.form.get("latitude")); store.longitude = _num(request.form.get("longitude"))
    store.is_active = request.form.get("active") == "1"
    db.session.commit()
    audit("MART_UPDATED", "Store", store.id, old_values=old, new_values={"name": store.name, "code": store.code, "active": store.is_active})
    flash(f"{store.name} updated.", "success")
    return redirect(url_for("admin.stores"))


@bp.post(f"{ADMIN_BASE}/stores/<store_id>/delete")
@admin_required("inventory.view")
def delete_store(store_id):
    store = db.session.get(Store, store_id)
    if not store or store.business_id != current_user.business_id:
        return "Not found", 404
    active_count = Store.query.filter_by(business_id=store.business_id, is_active=True).count()
    if store.is_active and active_count <= 1:
        flash("Keep at least one active mart. Deactivate it only after another mart is active.", "error")
        return redirect(url_for("admin.stores"))
    store.is_active = False
    db.session.commit()
    audit("MART_DEACTIVATED", "Store", store.id, new_values={"active": False})
    flash(f"{store.name} has been deactivated. Historical sales remain intact.", "success")
    return redirect(url_for("admin.stores"))


@bp.route(f"{ADMIN_BASE}/expenses", methods=["GET", "POST"])
@admin_required("reports.view")
def expenses():
    business_id = current_user.business_id
    stores = Store.query.filter_by(business_id=business_id).order_by(Store.name).all()
    if request.method == "POST":
        category = (request.form.get("category") or "General").strip() or "General"
        description = (request.form.get("description") or "").strip()
        store_id = request.form.get("store_id") or None
        try:
            amount = Decimal(request.form.get("amount", "0"))
        except InvalidOperation:
            amount = Decimal("0")
        store = db.session.get(Store, store_id) if store_id else None
        if not description or amount <= 0 or (store and store.business_id != business_id):
            flash("Enter a description, positive amount and valid mart.", "error")
        else:
            row = Expense(business_id=business_id, store_id=store.id if store else None, category=category,
                          description=description, amount=amount, created_by=current_user.id)
            db.session.add(row); db.session.commit()
            audit("EXPENSE_RECORDED", "Expense", row.id, new_values={"category": category, "amount": str(amount), "store_id": store.id if store else None})
            flash("Expense recorded.", "success")
            return redirect(url_for("admin.expenses"))
    rows = Expense.query.filter_by(business_id=business_id).order_by(Expense.incurred_at.desc()).limit(500).all()
    total = db.session.query(db.func.coalesce(db.func.sum(Expense.amount), 0)).filter_by(business_id=business_id).scalar() or 0
    return render_template("admin/expenses.html", rows=rows, stores=stores, total=total)


@bp.route(f"{ADMIN_BASE}/pricing", methods=["GET", "POST"])
@admin_required("products.edit")
def pricing():
    business_id = current_user.business_id
    stores = Store.query.filter_by(business_id=business_id).order_by(Store.name).all()
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        rule_type = (request.form.get("rule_type") or "COST_PLUS_PERCENT").strip().upper()
        store_id = request.form.get("store_id") or None
        try:
            margin = Decimal(request.form.get("margin_percent", "0") or "0")
            markup = Decimal(request.form.get("fixed_markup", "0") or "0")
            rounding = Decimal(request.form.get("rounding_rule", "1") or "1")
            min_margin = Decimal(request.form.get("min_margin_percent", "0") or "0")
            max_discount = Decimal(request.form.get("max_discount_percent", "0") or "0")
            priority = int(request.form.get("priority", "100") or "100")
        except (InvalidOperation, ValueError):
            margin = markup = min_margin = max_discount = Decimal("0"); rounding = Decimal("1"); priority = 100
        store = db.session.get(Store, store_id) if store_id else None
        if not name or rule_type not in {"COST_PLUS_PERCENT", "FIXED_MARKUP"} or (store and store.business_id != business_id):
            flash("Enter a rule name and valid mart/type.", "error")
        elif margin < 0 or markup < 0 or rounding <= 0 or min_margin < 0 or max_discount < 0:
            flash("Pricing values cannot be negative and rounding must be greater than zero.", "error")
        else:
            rule = PricingRule(business_id=business_id, store_id=store.id if store else None, name=name,
                               rule_type=rule_type, margin_percent=margin, fixed_markup=markup,
                               rounding_rule=rounding, min_margin_percent=min_margin,
                               max_discount_percent=max_discount, priority=priority, is_active=True)
            db.session.add(rule); db.session.commit()
            audit("PRICING_RULE_CREATED", "PricingRule", rule.id, new_values={"name": name, "type": rule_type})
            flash("Pricing rule created.", "success")
            return redirect(url_for("admin.pricing"))
    rows = PricingRule.query.filter_by(business_id=business_id).order_by(PricingRule.priority.asc(), PricingRule.name.asc()).all()
    store_map = {s.id: s.name for s in stores}
    return render_template("admin/pricing.html", rules=rows, stores=stores, store_map=store_map)


@bp.post(f"{ADMIN_BASE}/pricing/<rule_id>/toggle")
@admin_required("products.edit")
def toggle_pricing_rule(rule_id):
    rule = db.session.get(PricingRule, rule_id)
    if not rule or rule.business_id != current_user.business_id:
        return "Not found", 404
    rule.is_active = not rule.is_active
    db.session.commit()
    audit("PRICING_RULE_STATUS_CHANGED", "PricingRule", rule.id, new_values={"active": rule.is_active})
    flash(f"{rule.name} is now {'active' if rule.is_active else 'off'}.", "success")
    return redirect(url_for("admin.pricing"))


@bp.post(f"{ADMIN_BASE}/pricing/apply")
@admin_required("products.edit")
def apply_pricing_rules():
    from services.pricing import suggested_price
    business_id = current_user.business_id
    changed = 0
    rows = StoreProduct.query.join(Store).filter(Store.business_id == business_id).all()
    active_rules = PricingRule.query.filter_by(business_id=business_id, is_active=True).order_by(PricingRule.priority.asc()).all()
    for sp in rows:
        rule = next((r for r in active_rules if r.store_id in {None, sp.store_id}), None)
        if not rule:
            continue
        new_price = suggested_price(sp, rule)
        old_price = Decimal(str(sp.selling_price or 0))
        if new_price != old_price:
            sp.selling_price = new_price
            sp.pricing_rule_id = rule.id
            db.session.add(PriceHistory(store_product_id=sp.id, old_price=old_price, new_price=new_price,
                                        reason=f"Applied pricing rule: {rule.name}", source="RULE", changed_by=current_user.id))
            changed += 1
    db.session.commit()
    audit("PRICING_RULES_APPLIED", "Business", business_id, new_values={"changed_prices": changed})
    flash(f"Pricing engine applied to {changed} store prices.", "success")
    return redirect(url_for("admin.pricing"))


@bp.route(f"{ADMIN_BASE}/settings", methods=["GET", "POST"])
@admin_required()
def settings():
    business_id=current_user.business_id
    business=Business.query.filter_by(id=business_id).first_or_404()
    footer_setting=SystemSetting.query.filter_by(business_id=business_id,key="footer_text").first()
    loyalty_setting=SystemSetting.query.filter_by(business_id=business_id,key="loyalty_points_per_100").first()
    if request.method=="POST":
        name=(request.form.get("business_name") or "").strip()[:200]
        footer=(request.form.get("footer_text") or "").strip()[:500]
        if name: business.name=name
        footer_setting=footer_setting or SystemSetting(business_id=business_id,key="footer_text")
        footer_setting.value=footer
        try: lp=max(0,int(request.form.get("loyalty_points_per_100","1") or "1"))
        except ValueError: lp=1
        loyalty_setting=loyalty_setting or SystemSetting(business_id=business_id,key="loyalty_points_per_100")
        loyalty_setting.value=str(lp)
        uploaded=request.files.get("business_logo")
        if uploaded and uploaded.filename:
            raw=uploaded.read()
            if raw:
                business.logo_url="data:"+(uploaded.mimetype or "image/png")+";base64,"+base64.b64encode(raw).decode("ascii")
        if request.form.get("remove_logo")=="1": business.logo_url=None
        db.session.commit(); audit("SETTINGS_UPDATED","Business",business_id,new_values={"business_name":business.name})
        flash("Settings saved.","success")
    return render_template("admin/settings.html",business=business,footer_text=footer_setting.value if footer_setting else "",
                           loyalty_points_per_100=loyalty_setting.value if loyalty_setting else "1")

@bp.get(f"{ADMIN_BASE}/reports")
@admin_required("reports.view")
def reports():
    try: days=max(1,min(int(request.args.get("days",30)),365))
    except ValueError: days=30
    since=now()-timedelta(days=days)
    sales_rows=db.session.query(db.func.date(Sale.created_at),db.func.coalesce(db.func.sum(Sale.total),0),db.func.coalesce(db.func.sum(SaleItem.quantity),0)).join(SaleItem,SaleItem.sale_id==Sale.id).filter(Sale.business_id==current_user.business_id,Sale.status=="COMPLETED",Sale.created_at>=since).group_by(db.func.date(Sale.created_at)).order_by(db.func.date(Sale.created_at)).all()
    daily_rows=[{"date":key,"sales":Decimal(str(total or 0)),"items":Decimal(str(items or 0))} for key,total,items in sales_rows]
    total_sales=sum((r["sales"] for r in daily_rows),Decimal("0")); total_items=sum((r["items"] for r in daily_rows),Decimal("0"))
    top=db.session.query(SaleItem.product_id,SaleItem.product_name_snapshot,db.func.coalesce(db.func.sum(SaleItem.quantity),0),db.func.coalesce(db.func.sum(SaleItem.line_total),0)).join(Sale,Sale.id==SaleItem.sale_id).filter(Sale.business_id==current_user.business_id,Sale.status=="COMPLETED",Sale.created_at>=since).group_by(SaleItem.product_id,SaleItem.product_name_snapshot).order_by(db.func.sum(SaleItem.line_total).desc()).limit(20).all()
    top_products=[{"name":name,"qty":Decimal(str(qty or 0)),"sales":Decimal(str(amount or 0))} for _,name,qty,amount in top]
    return render_template("admin/reports.html",days=days,total_sales=total_sales,total_items=total_items,daily_rows=daily_rows,top_products=top_products)

@bp.get(f"{ADMIN_BASE}/audit")
@admin_required()
def audit_page():
    q = (request.args.get("q") or "").strip()
    query = AuditLog.query.filter_by(business_id=current_user.business_id)
    if q:
        needle = f"%{q}%"
        query = query.filter(or_(AuditLog.action.ilike(needle), AuditLog.entity_type.ilike(needle), AuditLog.entity_id.ilike(needle)))
    logs = query.order_by(AuditLog.created_at.desc()).limit(500).all()
    return render_template("admin/audit.html", logs=logs, q=q)


@bp.route(f"{ADMIN_BASE}/system-errors", methods=["GET", "POST"])
@admin_required()
def system_errors():
    business_id = current_user.business_id
    if request.method == "POST":
        error_id = request.form.get("error_id") or ""
        row = db.session.get(SystemError, error_id)
        if row and row.business_id == business_id:
            row.resolved = True
            db.session.commit()
            audit("SYSTEM_ERROR_RESOLVED", "SystemError", row.id)
            flash("System error marked resolved.", "success")
        return redirect(url_for("admin.system_errors"))
    errors = SystemError.query.filter_by(business_id=business_id).order_by(SystemError.resolved.asc(), SystemError.created_at.desc()).limit(500).all()
    return render_template("admin/system_errors.html", errors=errors)


@bp.get(f"{ADMIN_BASE}/security")
@admin_required()
def security():
    business_id = current_user.business_id
    users = User.query.filter_by(business_id=business_id).all()
    logs = AuditLog.query.filter_by(business_id=business_id).order_by(AuditLog.created_at.desc()).limit(500).all()
    return render_template("admin/security.html", users=users, logs=logs)


@bp.get(f"{ADMIN_BASE}/backups")
@admin_required("backup.create")
def backups():
    latest = AuditLog.query.filter_by(business_id=current_user.business_id).filter(
        AuditLog.action.in_(["BACKUP_JSON_EXPORTED", "BACKUP_SQLITE_EXPORTED", "BACKUP_JSON_RESTORED", "BACKUP_SQLITE_RESTORED"])
    ).order_by(AuditLog.created_at.desc()).limit(40).all()
    return render_template("admin/backups.html", latest=latest)


@bp.get(f"{ADMIN_BASE}/export.json")
@admin_required("backup.create")
def export_json():
    payload = export_database_json()
    audit("BACKUP_JSON_EXPORTED", "Business", current_user.business_id, new_values={"format": "json"})
    raw = json.dumps(payload, ensure_ascii=False, indent=2, default=str).encode("utf-8")
    return send_file(BytesIO(raw), mimetype="application/json", as_attachment=True,
                     download_name=f"real-mart-backup-{now().strftime('%Y%m%d-%H%M%S')}.json")


@bp.get(f"{ADMIN_BASE}/export.sqlite")
@admin_required("backup.create")
def export_sqlite():
    import tempfile
    tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
    tmp.close()
    path = Path(tmp.name)
    try:
        # Build and verify the complete snapshot before opening it to the browser.
        create_sqlite_snapshot(path)
        audit("BACKUP_SQLITE_EXPORTED", "Business", current_user.business_id, new_values={"format": "sqlite"})

        @after_this_request
        def cleanup(response):
            try:
                path.unlink(missing_ok=True)
            except Exception:
                current_app.logger.warning("Could not remove temporary SQLite backup %s", path)
            return response

        return send_file(
            path,
            mimetype="application/vnd.sqlite3",
            as_attachment=True,
            conditional=True,
            etag=False,
            max_age=0,
            download_name=f"real-mart-backup-{now().strftime('%Y%m%d-%H%M%S')}.sqlite",
        )
    except Exception as exc:
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass
        current_app.logger.exception("SQLite backup generation failed")
        flash(f"SQLite backup could not be generated: {str(exc)[:220]}", "error")
        return redirect(url_for("admin.backups"))


@bp.post(f"{ADMIN_BASE}/restore/json")
@admin_required("backup.create")
def restore_json():
    upload = request.files.get("backup_file")
    if request.form.get("confirm") != "RESTORE" or not upload:
        flash("Choose a backup and confirm RESTORE before importing.", "error")
        return redirect(url_for("admin.backups"))
    try:
        raw = upload.stream.read()
        if not raw:
            raise ValueError("The selected backup file is empty.")
        # UTF-8 BOMs and filename extensions are both accepted; the content is
        # the authority, so files exported by Real Mart are accepted regardless
        # of browser-provided MIME type or filename casing.
        payload = json.loads(raw.decode("utf-8-sig"))
        restore_database_json(payload)
        session.clear()
        flash("JSON backup restored. Sign in again with the restored credentials.", "success")
        return redirect("/control")
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception("JSON restore failed")
        flash(f"Restore failed: {str(exc)[:220]}", "error")
        return redirect(url_for("admin.backups"))


@bp.post(f"{ADMIN_BASE}/restore/sqlite")
@admin_required("backup.create")
def restore_sqlite():
    import tempfile
    upload = request.files.get("backup_file")
    if request.form.get("confirm") != "RESTORE" or not upload:
        flash("Choose a backup and confirm RESTORE before importing.", "error")
        return redirect(url_for("admin.backups"))
    tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
    path = Path(tmp.name)
    try:
        upload.save(path)
        restore_sqlite_snapshot(path)
        session.clear()
        flash("SQLite backup restored. Sign in again with the restored credentials.", "success")
        return redirect("/control")
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception("SQLite restore failed")
        flash(f"Restore failed: {str(exc)[:220]}", "error")
        return redirect(url_for("admin.backups"))
    finally:
        try: path.unlink(missing_ok=True)
        except Exception: pass


