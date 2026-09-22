from io import BytesIO
import base64
import mimetypes
from pathlib import Path

from decimal import Decimal
from PIL import Image, ImageDraw, ImageFont
from flask import Blueprint, render_template, request, session, send_file, jsonify, Response, redirect, url_for, flash, current_app
from extensions import db
from models import Product, Store, StoreProduct, Category, SystemSetting, ProductAlias, ProductImage, Business, Order, Delivery, Payment, SystemError
from services.search import forgiving_rank
from services.product_images import is_local_image_url, local_path_from_url, image_content_type

bp = Blueprint("shop", __name__)


def active_stores():
    return Store.query.filter_by(is_active=True).order_by(Store.name).all()


def selected_store():
    stores = active_stores()
    requested = request.args.get("store", "").strip()
    store = next((s for s in stores if s.code.lower() == requested.lower() or s.id == requested), None)
    if store:
        session["store_code"] = store.code
        return store
    saved = session.get("store_code")
    if saved:
        store = next((s for s in stores if s.code.lower() == str(saved).lower()), None)
        if store:
            return store
    return stores[0] if stores else None


def catalogue_query(store=None, q="", category=""):
    query = (StoreProduct.query.join(Product)
             .filter(StoreProduct.is_available.is_(True), StoreProduct.available_online.is_(True),
                     StoreProduct.stock_quantity > StoreProduct.reserved_quantity, Product.status == "ACTIVE"))
    if store:
        query = query.filter(StoreProduct.store_id == store.id)
    if category:
        query = query.filter(Product.category_id == category)
    rows = query.order_by(Product.name).limit(2000).all()
    if not q:
        return rows
    product_ids = [row.product_id for row in rows]
    aliases_by_product = {}
    if product_ids:
        for alias in ProductAlias.query.filter(ProductAlias.product_id.in_(product_ids)).all():
            aliases_by_product.setdefault(alias.product_id, []).append(alias.alias)
    return forgiving_rank(rows, q, aliases_by_product=aliases_by_product, limit=300)


@bp.get("/")
def home():
    store = selected_store()
    categories = (Category.query.filter_by(business_id=store.business_id, is_active=True)
                  .order_by(Category.sort_order, Category.name).all()) if store else []
    rows = catalogue_query(store)[:600] if store else []
    priority = [
        "sugar", "fresh milk", "yoghurt", "bread", "maize meal", "rice", "cooking oil",
        "eggs", "tea", "coffee", "water", "tissue", "toilet", "washing", "soap", "biscuits",
    ]
    def rank(item):
        text = f"{item.product.name} {item.product.brand or ''}".lower()
        for i, term in enumerate(priority):
            if term in text:
                return i
        return 99
    ranked = sorted(rows, key=lambda x: (rank(x), x.product.name.lower()))
    essentials = ranked[:36]
    more_products = [x for x in ranked[36:] if x not in essentials][:120]
    return render_template("shop/home.html", stores=active_stores(), store=store, essentials=essentials, more_products=more_products, categories=categories, total_products=len(rows))


@bp.get("/shop")
def shop():
    q = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    store = selected_store()
    products = catalogue_query(store, q=q, category=category)[:1000]
    categories = (Category.query.filter_by(business_id=store.business_id, is_active=True)
                  .order_by(Category.sort_order, Category.name).all()) if store else []
    return render_template("shop/shop.html", products=products, q=q, store=store, stores=active_stores(), categories=categories, product_count=StoreProduct.query.join(Product).filter(StoreProduct.is_available.is_(True), StoreProduct.available_online.is_(True), Product.status == "ACTIVE", StoreProduct.store_id == store.id).count() if store else 0)


@bp.get("/product/<slug>")
def product(slug):
    store = selected_store()
    item = (StoreProduct.query.join(Product)
            .filter(Product.slug == slug, StoreProduct.is_available.is_(True), StoreProduct.available_online.is_(True), Product.status == "ACTIVE")
            .filter(StoreProduct.store_id == store.id if store else True).first_or_404())
    return render_template("shop/product.html", item=item, store=store)


@bp.get("/cart")
def cart():
    return render_template("shop/cart.html", store=selected_store())


@bp.get("/checkout")
def checkout():
    store = selected_store()
    till_setting = SystemSetting.query.filter_by(business_id=store.business_id, key="mpesa_till_number").first() if store else None
    till_number = str(till_setting.value or "").strip() if till_setting else ""
    return render_template("shop/checkout.html", store=store, till_number=till_number)


@bp.get("/order/<order_number>")
def order_confirmation(order_number):
    from models import Order, OrderItem
    order = Order.query.filter_by(order_number=order_number).first_or_404()
    items = OrderItem.query.filter_by(order_id=order.id).all()
    store = Store.query.get(order.store_id)
    till_setting = SystemSetting.query.filter_by(business_id=order.business_id, key="mpesa_till_number").first()
    till_number = str(till_setting.value or "").strip() if till_setting else ""
    active_payment = (Payment.query.filter(
        Payment.order_id == order.id,
        Payment.method.in_(["MPESA_TILL_INTENT", "MPESA_TILL_MANUAL", "MPESA_GATEWAY_INTENT", "MPESA_TILL", "MPESA_GATEWAY"]),
        Payment.status.in_(["PENDING", "PENDING_APPROVAL", "PARTIALLY_PAID"]),
    ).order_by(Payment.created_at.desc()).first())
    from services.payments.settlement import order_received_total, order_outstanding
    received_total = order_received_total(order)
    outstanding_total = order_outstanding(order)
    return render_template("shop/order_confirmation.html", order=order, items=items, store=store, till_number=till_number,
                           active_payment=active_payment, received_total=received_total, outstanding_total=outstanding_total)


@bp.get("/delivery/<order_number>")
def delivery_request(order_number):
    order = Order.query.filter_by(order_number=order_number).first_or_404()
    store = db.session.get(Store, order.store_id)
    if order.payment_status != "PAID":
        flash("Please wait until payment is fully approved before continuing to delivery.", "error")
        return redirect(url_for("shop.order_confirmation", order_number=order.order_number))
    existing = Delivery.query.filter_by(order_id=order.id).first()
    base_setting = SystemSetting.query.filter_by(business_id=order.business_id, key="delivery_bike_base_fee").first()
    km_setting = SystemSetting.query.filter_by(business_id=order.business_id, key="delivery_bike_per_km").first()
    enabled_setting = SystemSetting.query.filter_by(business_id=order.business_id, key="delivery_enabled").first()
    try:
        base_fee = Decimal(str(base_setting.value if base_setting else "100"))
        per_km = Decimal(str(km_setting.value if km_setting else "20"))
    except Exception:
        base_fee, per_km = Decimal("100"), Decimal("20")
    enabled = (enabled_setting.value if enabled_setting else "1") == "1"
    return render_template("shop/delivery.html", order=order, store=store, existing=existing, base_fee=base_fee, per_km=per_km, enabled=enabled)


@bp.post("/delivery/<order_number>/request")
def submit_delivery_request(order_number):
    order = Order.query.filter_by(order_number=order_number).first_or_404()
    if order.payment_status != "PAID":
        flash("Please wait until payment is fully approved before requesting delivery.", "error")
        return redirect(url_for("shop.order_confirmation", order_number=order.order_number))
    if Delivery.query.filter_by(order_id=order.id).first():
        flash("Delivery is already requested for this order.", "success")
        return redirect(url_for("shop.delivery_request", order_number=order.order_number))
    address = request.form.get("address", "").strip()
    phone = request.form.get("phone", "").strip()
    name = request.form.get("name", "").strip()
    try:
        km = Decimal(request.form.get("distance_km", "0") or "0")
        base_fee = Decimal(str(SystemSetting.query.filter_by(business_id=order.business_id, key="delivery_bike_base_fee").first().value if SystemSetting.query.filter_by(business_id=order.business_id, key="delivery_bike_base_fee").first() else "100"))
        per_km = Decimal(str(SystemSetting.query.filter_by(business_id=order.business_id, key="delivery_bike_per_km").first().value if SystemSetting.query.filter_by(business_id=order.business_id, key="delivery_bike_per_km").first() else "20"))
    except Exception:
        km = Decimal("0"); base_fee, per_km = Decimal("100"), Decimal("20")
    if not address or not phone or not name or km < 0 or km > 200:
        flash("Enter the recipient details, delivery address and a valid distance estimate.", "error")
        return redirect(url_for("shop.delivery_request", order_number=order.order_number))
    fee = (base_fee + (per_km * km)).quantize(Decimal("1"))
    order.delivery_address = address
    order.delivery_fee = fee
    order.delivery_notes = f"Bike delivery requested · estimated {km} km · delivery fee KES {fee} · recipient {name} {phone}"
    db.session.add(Delivery(order_id=order.id, status="PENDING", recipient_name=name[:160], recipient_phone=phone[:40], notes=order.delivery_notes))
    db.session.commit()
    flash(f"Bike delivery requested. Estimated delivery charge: KES {fee:.0f}.", "success")
    return redirect(url_for("shop.delivery_request", order_number=order.order_number))


@bp.get("/mpesa-till-qr")
def mpesa_till_qr():
    import qrcode
    store = selected_store()
    if not store:
        return ("", 404)
    setting = SystemSetting.query.filter_by(business_id=store.business_id, key="mpesa_till_number").first()
    till = str(setting.value or "").strip() if setting else ""
    if not till:
        return ("", 404)
    img = qrcode.make(till)
    buf = BytesIO(); img.save(buf, format="PNG", optimize=True); buf.seek(0)
    return send_file(buf, mimetype="image/png", max_age=3600)




@bp.get("/favicon.ico")
def favicon():
    # Reuse the installed app icon so browsers stop generating a noisy 404.
    from pathlib import Path
    icon = Path(current_app.root_path) / "static" / "pwa" / "icon.svg"
    if icon.exists():
        return send_file(icon, mimetype="image/svg+xml", max_age=86400)
    return ("", 404)

@bp.get("/app-qr.png")
def app_qr():
    import qrcode
    # The QR represents the customer-facing shop path, never a hard-coded domain.
    target = request.url_root.rstrip("/") + "/shop"
    img = qrcode.make(target)
    buf = BytesIO(); img.save(buf, format="PNG", optimize=True); buf.seek(0)
    return send_file(buf, mimetype="image/png", max_age=86400)


def _catalogue_manifest():
    """Load the build-time real-photo registry."""
    import json
    path = Path(current_app.static_folder) / "catalogue" / "catalogue-image-manifest.json"
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("products", {})
    except Exception:
        return {}


def _pending_product_photo(product):
    """Neutral product-specific pending card, never a fake product image."""
    import html
    brand = html.escape(str(product.brand or "Denmart"))
    name = html.escape(str(product.name or "Product photo pending"))
    svg = """<svg xmlns="http://www.w3.org/2000/svg" width="800" height="800" viewBox="0 0 800 800">
      <rect width="800" height="800" rx="56" fill="#f5f7f8"/>
      <rect x="58" y="58" width="684" height="684" rx="44" fill="#ffffff" stroke="#dfe6e9" stroke-width="4"/>
      <circle cx="400" cy="320" r="92" fill="#f0f3f5"/>
      <path d="M350 320h100M400 270v100" stroke="#9aa6ad" stroke-width="10" stroke-linecap="round"/>
      <text x="400" y="478" text-anchor="middle" font-family="Arial,sans-serif" font-size="24" font-weight="700" fill="#6d777d">PHOTO NOT CACHED YET</text>
      <text x="400" y="530" text-anchor="middle" font-family="Arial,sans-serif" font-size="22" font-weight="700" fill="#273137">{brand}</text>
      <text x="400" y="568" text-anchor="middle" font-family="Arial,sans-serif" font-size="20" fill="#4e5a60">{name}</text>
    </svg>"""
    return Response(svg, mimetype="image/svg+xml", headers={"Cache-Control": "no-store", "X-Denmart-Image": "catalogue-pending"})


def _local_product_photo(product):
    """Serve only the exact cached file recorded for this exact product."""
    manifest = _catalogue_manifest()
    entry = manifest.get(str(product.id)) or {}
    raw = str(entry.get("url") or "").strip()
    # First serve a verified build-cache photo. Then allow a real administrator-uploaded
    # local image stored directly on the product row. Generated legacy catalogue assets do
    # not exist in the repository anymore, so this cannot revive the old fake photos.
    if entry.get("type") == "photo" and is_local_image_url(raw):
        path = local_path_from_url(raw)
    else:
        row_raw = str(product.image_url or "").strip()
        path = local_path_from_url(row_raw) if is_local_image_url(row_raw) else None
    if not path or not path.is_file() or path.stat().st_size <= 0:
        return None
    response = send_file(path, mimetype=image_content_type(path), max_age=31536000, conditional=True, etag=True, last_modified=path.stat().st_mtime)
    response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    response.headers["X-Denmart-Image"] = "catalogue-real-local"
    return response


@bp.get("/product-photo/<product_id>.jpg")
def product_photo(product_id):
    product = db.session.get(Product, product_id)
    if not product or product.status != "ACTIVE":
        return ("", 404)
    local = _local_product_photo(product)
    if local is not None:
        return local
    raw = str(product.image_url or "").strip()
    if raw.startswith("data:image/") and "," in raw:
        try:
            header, encoded = raw.split(",", 1)
            binary = base64.b64decode(encoded)
            mime = header.split(";", 1)[0].replace("data:", "") or "image/webp"
            response = send_file(BytesIO(binary), mimetype=mime, max_age=31536000)
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            response.headers["X-Denmart-Image"] = "database-local"
            return response
        except Exception:
            pass
    return _pending_product_photo(product)


@bp.get("/shop/manifest.webmanifest")
def shop_manifest():
    base = request.host_url.rstrip("/")
    business = Business.query.order_by(Business.created_at).first()
    name = business.name if business else "Denmart"
    return jsonify({
        "id": "/",
        "name": name,
        "short_name": name[:12] or "Denmart",
        "start_url": f"{base}/",
        "scope": f"{base}/",
        "display": "standalone",
        "display_override": ["standalone", "browser"],
        "background_color": "#f7fafb",
        "theme_color": "#f57c00",
        "description": f"{name} online supermarket",
        "orientation": "any",
        "categories": ["shopping", "food", "business"],
        "lang": "en-KE",
        "dir": "ltr",
        "prefer_related_applications": False,
        "icons": [
            {"src": f"{base}/shop/app-icon/192.png", "sizes": "192x192", "type": "image/png", "purpose": "any maskable"},
            {"src": f"{base}/shop/app-icon/512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"},
        ],
        "shortcuts": [
            {"name": "Shop", "short_name": "Shop", "url": f"{base}/shop", "icons": [{"src": f"{base}/shop/app-icon/192.png", "sizes": "192x192", "type": "image/png"}]},
            {"name": "Basket", "short_name": "Basket", "url": f"{base}/cart", "icons": [{"src": f"{base}/shop/app-icon/192.png", "sizes": "192x192", "type": "image/png"}]},
        ],
    })


def _icon_bytes(size):
    business = Business.query.order_by(Business.created_at).first()
    logo_url = (business.logo_url or "").strip() if business else ""
    canvas = Image.new("RGBA", (size, size), (245, 124, 0, 255))
    if logo_url.startswith("data:image/") and "," in logo_url:
        try:
            raw = base64.b64decode(logo_url.split(",", 1)[1])
            src = Image.open(BytesIO(raw)).convert("RGBA")
            src.thumbnail((int(size * 0.72), int(size * 0.72)), Image.Resampling.LANCZOS)
            canvas.alpha_composite(src, ((size - src.width) // 2, (size - src.height) // 2))
        except Exception:
            pass
    else:
        pad = int(size * 0.14)
        draw = ImageDraw.Draw(canvas)
        draw.rounded_rectangle((pad, pad, size - pad, size - pad), radius=int(size * .18), fill=(255,255,255,255))
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", int(size * .30))
        except Exception:
            font = ImageFont.load_default()
        text = "DM"
        bbox = draw.textbbox((0,0), text, font=font)
        draw.text(((size-(bbox[2]-bbox[0]))/2, (size-(bbox[3]-bbox[1]))/2-int(size*.03)), text, fill=(25,118,74,255), font=font)
    out = BytesIO()
    canvas.convert("RGB").save(out, format="PNG", optimize=True)
    out.seek(0)
    return out


@bp.get("/shop/app-icon/<int:size>.png")
def shop_app_icon(size):
    if size not in {192, 512}:
        return ("", 404)
    return send_file(_icon_bytes(size), mimetype="image/png", max_age=300)


@bp.get("/shop/sw.js")
def shop_service_worker():
    js = '''const CACHE_VERSION = "denmart-public-v18-local-images";
const STATIC_CACHE = `${CACHE_VERSION}-static`;
const IMAGE_CACHE = `${CACHE_VERSION}-images`;
const PAGE_CACHE = `${CACHE_VERSION}-pages`;
const STATIC_ASSETS = ["/static/css/app.css","/static/js/app.js","/shop/manifest.webmanifest","/shop/app-icon/192.png","/shop/app-icon/512.png"];
self.addEventListener("install", event => {
  event.waitUntil(caches.open(STATIC_CACHE).then(cache => cache.addAll(STATIC_ASSETS)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => !k.startsWith(CACHE_VERSION)).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});
function bypass(request, url) {
  return request.method !== "GET" || url.origin !== location.origin || url.pathname.startsWith("/api/") || url.pathname.startsWith("/control") || url.pathname.startsWith("/merchant") || url.pathname.startsWith("/order/") || url.pathname.startsWith("/login") || url.pathname.startsWith("/logout");
}
self.addEventListener("fetch", event => {
  const request = event.request;
  const url = new URL(request.url);
  if (bypass(request, url)) return;

  // Catalogue images are bundled with the deployment and are never resolved remotely.
  // Cache-first makes products already viewed available when the app is offline.
  if (url.pathname.startsWith("/static/catalogue/products/")) {
    event.respondWith(caches.match(request).then(cached => cached || fetch(request).then(response => {
      if (response.ok) caches.open(IMAGE_CACHE).then(c => c.put(request, response.clone()));
      return response;
    })));
    return;
  }

  if (url.pathname.endsWith("manifest.webmanifest") || url.pathname.includes("/shop/app-icon/")) {
    event.respondWith(fetch(request).then(response => {
      if (response.ok) caches.open(STATIC_CACHE).then(c => c.put(request, response.clone()));
      return response;
    }).catch(() => caches.match(request)));
    return;
  }
  if (request.destination === "style" || request.destination === "script") {
    event.respondWith(caches.match(request).then(cached => {
      const update = fetch(request).then(response => {
        if (response.ok) caches.open(STATIC_CACHE).then(c => c.put(request, response.clone()));
        return response;
      }).catch(() => cached);
      return cached || update;
    }));
    return;
  }
  if (request.mode === "navigate") {
    event.respondWith(fetch(request).then(response => {
      if (response.ok && (url.pathname === "/" || url.pathname.startsWith("/shop") || url.pathname.startsWith("/product/") || url.pathname === "/cart")) caches.open(PAGE_CACHE).then(c => c.put(request, response.clone()));
      return response;
    }).catch(() => caches.match(request).then(cached => cached || caches.match("/"))));
  }
});
'''
    return Response(js, mimetype="application/javascript", headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"})
