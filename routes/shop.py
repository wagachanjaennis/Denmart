from io import BytesIO
import base64
import mimetypes
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from flask import Blueprint, render_template, request, session, send_file, Response, redirect, current_app, jsonify
from extensions import db
from models import Product, Store, StoreProduct, Category, ProductAlias, ProductImage, Business, SystemSetting
from services.search import forgiving_rank
from services.branding import brand_display_name
from services.product_images import public_product_image, has_public_product_image, data_url_to_bytes, is_data_image_url

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


def _attach_saved_product_images(rows):
    """Make older ProductImage-table records visible without one query per product."""
    product_ids = {str(row.product_id) for row in rows}
    if not product_ids:
        return rows
    try:
        image_rows = (ProductImage.query.filter(ProductImage.product_id.in_(product_ids))
                      .order_by(ProductImage.is_primary.desc(), ProductImage.sort_order, ProductImage.created_at).all())
    except Exception:
        current_app.logger.exception("Could not load saved catalogue images")
        return rows
    primary_by_product = {}
    for image_row in image_rows:
        primary_by_product.setdefault(str(image_row.product_id), str(image_row.image_url or "").strip())
    for row in rows:
        saved = primary_by_product.get(str(row.product_id), "")
        if saved:
            row.product._denmart_saved_image_url = saved
    return rows


def catalogue_query(store=None, q="", category=""):
    query = (StoreProduct.query.join(Product)
             .filter(StoreProduct.is_available.is_(True), StoreProduct.available_online.is_(True),
                     StoreProduct.stock_quantity > StoreProduct.reserved_quantity, Product.status == "ACTIVE"))
    if store:
        query = query.filter(StoreProduct.store_id == store.id)
    if category:
        query = query.filter(Product.category_id == category)
    rows = query.order_by(Product.name).limit(2000).all()
    rows = _attach_saved_product_images(rows)
    if not q:
        return sorted(rows, key=lambda row: (0 if has_public_product_image(row.product) else 1, row.product.name.lower()))
    product_ids = [row.product_id for row in rows]
    aliases_by_product = {}
    if product_ids:
        for alias in ProductAlias.query.filter(ProductAlias.product_id.in_(product_ids)).all():
            aliases_by_product.setdefault(alias.product_id, []).append(alias.alias)
    ranked = forgiving_rank(rows, q, aliases_by_product=aliases_by_product, limit=300)
    # Preserve relevance for searches. Image availability must never outrank the query.
    return ranked


@bp.get("/")
def home():
    store = selected_store()
    categories = (Category.query.filter_by(business_id=store.business_id, is_active=True)
                  .order_by(Category.sort_order, Category.name).all()) if store else []
    # Render the entire available online range on the landing page. Images are lazy-loaded
    # by the product card so customers can scroll the catalogue without a second click.
    products = catalogue_query(store) if store else []
    return render_template(
        "shop/home.html",
        stores=active_stores(),
        store=store,
        products=products,
        categories=categories,
        total_products=len(products),
    )

@bp.get("/shop")
def shop():
    q = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    store = selected_store()
    products = catalogue_query(store, q=q, category=category)[:1000]
    categories = (Category.query.filter_by(business_id=store.business_id, is_active=True)
                  .order_by(Category.sort_order, Category.name).all()) if store else []
    return render_template("shop/shop.html", products=products, q=q, store=store, stores=active_stores(), categories=categories, product_count=StoreProduct.query.join(Product).filter(StoreProduct.is_available.is_(True), StoreProduct.available_online.is_(True), Product.status == "ACTIVE", StoreProduct.store_id == store.id).count() if store else 0)


@bp.get("/locations")
def locations():
    stores = active_stores()
    return render_template("shop/locations.html", stores=stores, store=selected_store())


@bp.get("/locations/<store_code>")
def location_detail(store_code):
    stores = active_stores()
    store = next((item for item in stores if item.code.lower() == store_code.lower() or item.id == store_code), None)
    if not store:
        return ("", 404)
    return render_template("shop/location_detail.html", store=store, stores=stores)


@bp.get("/robots.txt")
def robots_txt():
    base = request.url_root.rstrip("/")
    body = f"User-agent: *\nAllow: /\nDisallow: /control\nDisallow: /merchant\nDisallow: /api\nSitemap: {base}/sitemap.xml\n"
    return Response(body, mimetype="text/plain", headers={"Cache-Control":"public, max-age=3600"})


@bp.get("/sitemap.xml")
def sitemap_xml():
    base = request.url_root.rstrip("/")
    stores = active_stores()
    urls = [base + "/", base + "/shop", base + "/locations"]
    urls.extend(f"{base}/locations/{store.code}" for store in stores)
    products = (StoreProduct.query.join(Product)
                .filter(StoreProduct.is_available.is_(True), StoreProduct.available_online.is_(True), Product.status == "ACTIVE")
                .order_by(Product.updated_at.desc()).limit(1000).all())
    urls.extend(f"{base}/product/{item.product.slug}" for item in products)
    xml=['<?xml version="1.0" encoding="UTF-8"?>','<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for value in urls:
        safe=value.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
        xml.append(f"<url><loc>{safe}</loc></url>")
    xml.append("</urlset>")
    return Response("".join(xml), mimetype="application/xml", headers={"Cache-Control":"public, max-age=1800"})


@bp.get("/product/<slug>")
def product(slug):
    store = selected_store()
    item = (StoreProduct.query.join(Product)
            .filter(Product.slug == slug, StoreProduct.is_available.is_(True), StoreProduct.available_online.is_(True), Product.status == "ACTIVE")
            .filter(StoreProduct.store_id == store.id if store else True).first_or_404())
    _attach_saved_product_images([item])
    return render_template("shop/product.html", item=item, store=store)


@bp.get("/cart")
def cart():
    store = selected_store()
    methods = []
    settings = None
    if store:
        from services.payment_engine import get_pay_settings, enabled_methods
        settings = get_pay_settings(store.business_id)
        methods = enabled_methods(settings)
    launch_setting = SystemSetting.query.filter_by(business_id=(store.business_id if store else None), key="storefront_orders_enabled").first() if store else None
    orders_enabled = bool(launch_setting and launch_setting.value == "1")
    return render_template("shop/cart.html", store=store, payment_methods=methods, pay_settings=settings, orders_enabled=orders_enabled)


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



def _serve_data_product_photo(product):
    raw = str(product.image_url or "").strip()
    parsed = data_url_to_bytes(raw)
    if not parsed:
        return None
    binary, mime = parsed
    response = send_file(BytesIO(binary), mimetype=mime, max_age=31536000)
    response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    response.headers["X-Denmart-Image"] = "database-upload"
    return response


@bp.get("/product-photo/<product_id>.jpg")
def product_photo(product_id):
    product = db.session.get(Product, product_id)
    if not product or product.status != "ACTIVE":
        return ("", 404)

    # Older uploads may be stored in ProductImage instead of Product.image_url.
    # Resolve one product here too so direct photo links work outside catalogue pages.
    raw_image = str(product.image_url or "").strip()
    if not raw_image.startswith(("https://", "http://", "data:image/")):
        try:
            saved_image = (ProductImage.query.filter_by(product_id=product.id)
                           .order_by(ProductImage.is_primary.desc(), ProductImage.sort_order, ProductImage.created_at).first())
            if saved_image and str(saved_image.image_url or "").strip():
                product._denmart_saved_image_url = str(saved_image.image_url).strip()
        except Exception:
            current_app.logger.exception("Could not load saved product photo")

    # Exact curated photo: return a redirect so legacy callers can still resolve it.
    exact = public_product_image(product)
    if exact and not is_data_image_url(exact):
        response = redirect(exact, code=302)
        response.headers["Cache-Control"] = "public, max-age=86400"
        response.headers["X-Denmart-Image"] = "curated-remote"
        return response

    uploaded = _serve_data_product_photo(product)
    if uploaded is not None:
        return uploaded

    # Deliberately no generated illustration and no generic product substitute.
    return ("", 404)


@bp.get("/shop/manifest.webmanifest")
def shop_manifest():
    base = request.host_url.rstrip("/")
    business = Business.query.order_by(Business.created_at).first()
    brand = SystemSetting.query.filter_by(business_id=business.id, key="brand_name").first() if business else None
    name = brand_display_name(brand.value if brand else "")
    return jsonify({
        "id": "/",
        "name": name,
        "short_name": name[:12] or "Denmart",
        "start_url": f"{base}/",
        "scope": f"{base}/",
        "display": "standalone",
        "display_override": ["standalone", "browser"],
        "background_color": "#f7fafb",
        "theme_color": "#28c76f",
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
    brand_setting = SystemSetting.query.filter_by(business_id=business.id, key="brand_name").first() if business else None
    brand_name = brand_display_name(brand_setting.value if brand_setting else "")
    canvas = Image.new("RGBA", (size, size), (39, 200, 120, 255))
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
        words = [part for part in brand_name.split() if part]
        text = "".join(part[0] for part in words[:2]).upper() if len(words) > 1 else brand_name[:2].upper()
        bbox = draw.textbbox((0,0), text, font=font)
        draw.text(((size-(bbox[2]-bbox[0]))/2, (size-(bbox[3]-bbox[1]))/2-int(size*.03)), text, fill=(39,200,120,255), font=font)
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
    js = r'''const CACHE_VERSION = "denmart-public-v25-offline-persist";
const STATIC_CACHE = `${CACHE_VERSION}-static`;
const IMAGE_CACHE = `${CACHE_VERSION}-images`;
const PAGE_CACHE = `${CACHE_VERSION}-pages`;
const STATIC_ASSETS = ["/static/css/app.css","/static/js/app.js","/static/js/offline-core.js","/shop/manifest.webmanifest","/shop/app-icon/192.png","/shop/app-icon/512.png"];
self.addEventListener("install", event => event.waitUntil((async()=>{const cache=await caches.open(STATIC_CACHE);await Promise.all(STATIC_ASSETS.map(async url=>{try{const r=await fetch(url,{cache:"no-store"});if(r.ok)await cache.put(url,r);}catch(_){}}));await self.skipWaiting();})()));
self.addEventListener("activate", event => {event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k.startsWith("denmart-public-") && !k.startsWith(CACHE_VERSION)).map(k => caches.delete(k)))).then(() => self.clients.claim()));});
function isPrivatePortal(path){return path==="/control"||path.startsWith("/control/")||path==="/control/offline-login"||path==="/control2"||path.startsWith("/control2/")||path==="/control2/offline-login"||path==="/merchant"||path.startsWith("/merchant/")||path==="/merchant/offline-login";}
function shouldCachePage(path){if(path==="/"||path==="/shop"||path.startsWith("/shop?")||path.startsWith("/product/")||path==="/cart"||path==="/locations"||path.startsWith("/locations/"))return true;if(["/control/offline-login","/control2/offline-login","/merchant/offline-login"].includes(path))return true;return false;}
function forbiddenPublicCache(path){return path.startsWith("/api/")||path.startsWith("/pay/order/")||path.startsWith("/pay/approval/")||path.startsWith("/pay/api/")||path.startsWith("/control/pay/")||path.startsWith("/logout");}
self.addEventListener("fetch", event => {
  const request=event.request,url=new URL(request.url);
  if(request.method!=="GET")return;
  // Product photos may be served from a trusted external image host. Cache only image
  // subresources here; never broaden this to cross-origin pages or API requests.
  if(request.destination==="image"&&url.origin!==location.origin){
    event.respondWith((async()=>{const cache=await caches.open(IMAGE_CACHE);const existing=await cache.match(request);const refresh=fetch(request).then(async response=>{if(response.ok||response.type==="opaque"){try{await cache.put(request,response.clone());}catch(_){}}return response;}).catch(()=>null);if(existing){event.waitUntil(refresh);return existing;}return await refresh||new Response("",{status:504});})());return;
  }
  if(url.origin!==location.origin)return;
  const path=url.pathname;
  if(path.startsWith("/api/"))return;
  if(request.destination==="style"||request.destination==="script"||path.endsWith("manifest.webmanifest")||path.includes("/shop/app-icon/")){
    event.respondWith((async()=>{const cache=await caches.open(STATIC_CACHE);try{const response=await fetch(request);if(response.ok){try{await cache.put(request,response.clone());}catch(_){}}return response;}catch(_){return await cache.match(request,{ignoreSearch:true})||new Response("Offline asset unavailable",{status:503});}})());return;
  }
  if(request.destination==="image" && !forbiddenPublicCache(path)){
    event.respondWith((async()=>{const cache=await caches.open(IMAGE_CACHE);const existing=await cache.match(request);const refresh=fetch(request).then(async response=>{if(response.ok||response.type==="opaque"){try{await cache.put(request,response.clone());}catch(_){}}return response;}).catch(()=>null);if(existing){event.waitUntil(refresh);return existing;}return await refresh||new Response("",{status:504});})());return;
  }
  if(request.mode==="navigate"){
    if(isPrivatePortal(path) && !["/control/offline-login","/control2/offline-login","/merchant/offline-login"].includes(path))return;
    if(!shouldCachePage(path)||forbiddenPublicCache(path))return;
    event.respondWith((async()=>{try{const response=await fetch(request);if(response.ok&&!response.redirected){try{await caches.open(PAGE_CACHE).then(c=>c.put(request,response.clone()));}catch(_){}}return response;}catch(_){const pages=await caches.open(PAGE_CACHE);const exact=await pages.match(request)||await pages.match(url.origin+path);if(exact)return exact;if(path.startsWith("/product/"))return new Response('<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1"><title>Product not saved offline</title><main style="font:16px system-ui;max-width:32rem;margin:3rem auto;padding:1rem"><h1>This product page is not saved on this device yet.</h1><p>Your basket is saved locally. Reconnect once to open this product and make it available offline.</p><a href="/shop">Return to the catalogue</a></main>',{status:503,headers:{"Content-Type":"text/html; charset=utf-8"}});if(path==="/shop"||path==="/cart")return await pages.match(url.origin+path)||await pages.match("/")||new Response("This page has not been saved on this device yet. Connect once to cache it for offline browsing.",{status:503,headers:{"Content-Type":"text/plain; charset=utf-8"}});return await pages.match("/")||new Response("This page has not been saved on this device yet. Connect once to cache it for offline browsing.",{status:503,headers:{"Content-Type":"text/plain; charset=utf-8"}});}})());
  }
});
'''
    return Response(js, mimetype="application/javascript", headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"})