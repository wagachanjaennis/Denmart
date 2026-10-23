from io import BytesIO
import base64
import mimetypes
import re
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse
import ipaddress
import socket
import requests

from PIL import Image, ImageDraw, ImageFont
from flask import Blueprint, render_template, request, session, send_file, Response, redirect, current_app, jsonify
from extensions import db
from models import Product, Store, StoreProduct, Category, ProductAlias, ProductImage, Business, SystemSetting
from services.search import forgiving_rank
from services.branding import brand_display_name
from services.product_images import public_product_image, has_public_product_image, data_url_to_bytes, is_data_image_url, product_image_source, product_image_sources

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
    gallery_by_product = {}
    durable_by_product = {}
    for image_row in image_rows:
        key = str(image_row.product_id)
        url = str(image_row.image_url or "").strip()
        if not url:
            continue
        if getattr(image_row, "source_type", "") == "denmart-offline-cache":
            durable_by_product.setdefault(key, []).append(url)
            continue
        primary_by_product.setdefault(key, url)
        gallery_by_product.setdefault(key, []).append(url)
    for row in rows:
        key = str(row.product_id)
        saved = primary_by_product.get(key, "")
        if saved:
            row.product._denmart_saved_image_url = saved
        row.product._denmart_gallery_image_urls = gallery_by_product.get(key, [])
        row.product._denmart_durable_image_urls = durable_by_product.get(key, [])
    return rows


def catalogue_query(store=None, q="", category="", max_rows=2000):
    query = (StoreProduct.query.join(Product)
             .filter(StoreProduct.is_available.is_(True), StoreProduct.available_online.is_(True),
                     Product.status == "ACTIVE"))
    if store:
        query = query.filter(StoreProduct.store_id == store.id)
    if category:
        query = query.filter(Product.category_id == category)
    # Keep storefront requests bounded: rendering thousands of product cards makes
    # the first page slow, especially on mobile connections and free hosting.
    rows = query.order_by(Product.name).limit(max(1, min(int(max_rows), 2000))).all()
    rows = _attach_saved_product_images(rows)
    # Only the public online catalogue consumes this overlay. POS and offline sync
    # endpoints remain tied to local database barcodes, stock and prices.
    from services.catalogue_feeder import apply_online_feeder_overlay
    rows = apply_online_feeder_overlay(rows, store.business_id if store else None)
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
    products = catalogue_query(store, max_rows=2000)[:60] if store else []
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
    # Browsing pages show a manageable first batch; searches scan the broader
    # catalogue so an item is less likely to be missed.
    products = catalogue_query(store, q=q, category=category, max_rows=2000)[:120 if not q else 300]
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
    body = f"User-agent: *\nAllow: /\nDisallow: /control\nDisallow: /merchant\nDisallow: /api\nDisallow: /qaz\nDisallow: /advertcontrol\nDisallow: /advertisement\nSitemap: {base}/sitemap.xml\n"
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
    from services.catalogue_feeder import apply_online_feeder_overlay
    apply_online_feeder_overlay([item], store.business_id if store else None)
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
    # The checkout button must not depend on a separately toggled launch flag.
    # Payment destination defaults are established by get_pay_settings above.
    return render_template("shop/cart.html", store=store, payment_methods=methods, pay_settings=settings, orders_enabled=True)


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



def _public_image_url(raw: str) -> bool:
    """Reject local, credential-bearing and private-address image URLs before proxying."""
    try:
        parsed = urlparse(str(raw or "").strip())
        if parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username or parsed.password:
            return False
        host = parsed.hostname.rstrip(".").lower()
        if host in {"localhost", "localhost.localdomain"} or host.endswith((".local", ".internal", ".test")):
            return False
        try:
            ip = ipaddress.ip_address(host)
            if not ip.is_global:
                return False
        except ValueError:
            # Resolve hostnames to reject private/local DNS targets too. If DNS is
            # temporarily unavailable, the subsequent bounded fetch will fail closed.
            try:
                for item in socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM):
                    resolved = ipaddress.ip_address(item[4][0])
                    if not resolved.is_global:
                        return False
            except OSError:
                return False
        return True
    except Exception:
        return False


def _product_for_image(product_id):
    product = db.session.get(Product, product_id)
    if not product or product.status != "ACTIVE":
        return None
    try:
        image_rows = (ProductImage.query.filter_by(product_id=product.id)
                      .order_by(ProductImage.is_primary.desc(), ProductImage.sort_order, ProductImage.created_at).all())
        durable = [str(row.image_url or "").strip() for row in image_rows if str(row.image_url or "").strip() and getattr(row, "source_type", "") == "denmart-offline-cache"]
        gallery = [str(row.image_url or "").strip() for row in image_rows if str(row.image_url or "").strip() and getattr(row, "source_type", "") != "denmart-offline-cache"]
        product._denmart_durable_image_urls = durable
        if gallery:
            product._denmart_saved_image_url = gallery[0]
            product._denmart_gallery_image_urls = gallery
    except Exception:
        current_app.logger.exception("Could not load product image gallery")
    # API images may enrich the photo choices, but an empty/unavailable API image
    # never suppresses the saved local image or the curated exact-product source.
    try:
        rows = StoreProduct.query.filter_by(product_id=product.id).all()
        if rows:
            business_id = getattr(getattr(rows[0], "store", None), "business_id", None)
            from services.catalogue_feeder import apply_online_feeder_overlay
            apply_online_feeder_overlay(rows, business_id)
    except Exception:
        current_app.logger.exception("Could not apply product image feeder overlay")
    return product


def _serve_product_image_source(source: str, cache_seconds=604800, product=None, gallery_index=0):
    """Serve a local/data image or proxy a bounded public image URL as compressed WEBP."""
    source = str(source or "").strip()
    if not source:
        return ("", 404)
    if source.startswith("/static/"):
        from services.product_images import _local_static_image
        if not _local_static_image(source):
            return ("", 404)
        file_path = (Path(current_app.root_path) / source.lstrip("/")).resolve()
        response = send_file(file_path, conditional=True, max_age=cache_seconds)
        response.headers["Cache-Control"] = f"public, max-age={cache_seconds}, stale-while-revalidate=604800"
        response.headers["X-Denmart-Image"] = "bundled-product-photo"
        return response
    parsed_data = data_url_to_bytes(source)
    if parsed_data:
        binary, mime = parsed_data
        if len(binary) > 5_000_000:
            return ("", 413)
        response = send_file(BytesIO(binary), mimetype=mime, max_age=cache_seconds)
        response.headers["Cache-Control"] = f"public, max-age={cache_seconds}, stale-while-revalidate=604800"
        response.headers["X-Denmart-Image"] = "saved-product-upload"
        return response
    if not _public_image_url(source):
        return ("", 404)
    try:
        upstream = requests.get(source, headers={"User-Agent": "DenmartProductImage/1.0 (+https://denmart.co.ke)"},
                                timeout=(1.5, 3.5), allow_redirects=True, stream=True)
        if not upstream.ok or not str(upstream.headers.get("Content-Type", "")).lower().startswith("image/"):
            upstream.close()
            return ("", 404)
        if not _public_image_url(upstream.url):
            upstream.close()
            return ("", 404)
        chunks, length = [], 0
        for chunk in upstream.iter_content(64 * 1024):
            if not chunk:
                continue
            length += len(chunk)
            if length > 5_000_000:
                upstream.close()
                return ("", 413)
            chunks.append(chunk)
        upstream.close()
        raw = b"".join(chunks)
        if not raw:
            return ("", 404)
        # Normalize big supplier files to a light, same-origin WEBP. Same-origin
        # images can be cached offline and safely rendered into the MP4 canvas.
        try:
            from PIL import Image, ImageOps
            im = Image.open(BytesIO(raw))
            im = ImageOps.exif_transpose(im)
            if getattr(im, "is_animated", False):
                im.seek(0)
            if im.mode not in {"RGB", "RGBA"}:
                im = im.convert("RGBA" if "transparency" in im.info else "RGB")
            im.thumbnail((800, 800), Image.Resampling.LANCZOS)
            out = BytesIO()
            im.save(out, format="WEBP", quality=76, method=4, optimize=True)
            webp_bytes = out.getvalue()
            if product is not None and webp_bytes and len(webp_bytes) <= 450_000:
                try:
                    existing = ProductImage.query.filter_by(product_id=product.id, source_type="denmart-offline-cache", license_info=source).first()
                    if existing is None:
                        cached_url = "data:image/webp;base64," + base64.b64encode(webp_bytes).decode("ascii")
                        db.session.add(ProductImage(product_id=product.id, image_url=cached_url, alt_text=(str(product.name or "Product")[:180] + " · offline photo cache"), source_type="denmart-offline-cache", license_info=source[:2000], sort_order=1000 + max(0, min(7, int(gallery_index or 0))), is_primary=False))
                        db.session.commit()
                except Exception:
                    db.session.rollback()
                    current_app.logger.info("Could not persist a product photo for offline use", exc_info=True)
            out.seek(0)
            response = send_file(out, mimetype="image/webp", max_age=cache_seconds)
        except Exception:
            # Fall back to the validated original bytes if this image decoder does
            # not support the provider's format; still expose only image MIME types.
            mime = str(upstream.headers.get("Content-Type", "image/jpeg")).split(";", 1)[0]
            response = send_file(BytesIO(raw), mimetype=mime, max_age=cache_seconds)
        response.headers["Cache-Control"] = f"public, max-age={cache_seconds}, stale-while-revalidate=604800, immutable"
        response.headers["X-Denmart-Image"] = "proxied-real-product-photo"
        return response
    except requests.RequestException:
        current_app.logger.info("A product image source is currently unavailable", exc_info=True)
        return ("", 504)
    except Exception:
        current_app.logger.exception("Could not serve a product image")
        return ("", 404)


@lru_cache(maxsize=512)
def _lookup_open_food_facts_image(barcode):
    barcode = re.sub(r"\D", "", str(barcode or ""))
    if not 8 <= len(barcode) <= 14:
        return ""
    try:
        endpoint = "https://world.openfoodfacts.org/api/v2/product/" + barcode + ".json"
        response = requests.get(endpoint, params={"fields": "code,product_name,image_front_url,image_url"}, headers={"User-Agent": "DenmartOnline/1.0 (product-photo fallback)"}, timeout=(1.5, 3.0))
        if not response.ok:
            return ""
        payload = response.json()
        item = payload.get("product") if payload.get("status") == 1 else None
        actual_code = re.sub(r"\D", "", str((item or {}).get("code") or ""))
        if not item or actual_code != barcode:
            return ""
        photo = str(item.get("image_front_url") or item.get("image_url") or "").strip()
        return photo if _public_image_url(photo) else ""
    except Exception:
        current_app.logger.debug("Exact-barcode public image lookup unavailable", exc_info=True)
        return ""


def _try_product_image_sources(product, sources, cache_seconds=604800):
    for index, source in enumerate(sources):
        response = _serve_product_image_source(source, cache_seconds=cache_seconds, product=product, gallery_index=index)
        if isinstance(response, tuple):
            continue
        if getattr(response, "status_code", 200) >= 400:
            continue
        return response
    # Exact barcode verification is a last-resort source; it never borrows a photo
    # from a similarly named but differently coded product.
    barcode = getattr(product, "barcode", "") or getattr(product, "_denmart_online_barcode", "")
    if str(barcode or "").strip():
        photo = _lookup_open_food_facts_image(barcode)
        if photo:
            response = _serve_product_image_source(photo, cache_seconds=cache_seconds, product=product, gallery_index=len(sources))
            if not isinstance(response, tuple) and getattr(response, "status_code", 200) < 400:
                return response
    return ("", 404)


@bp.get("/product-photo/<product_id>.jpg")
def product_photo(product_id):
    product = _product_for_image(product_id)
    if not product:
        return ("", 404)
    sources = product_image_sources(product)[:8]
    result = _try_product_image_sources(product, sources, cache_seconds=604800)
    if not isinstance(result, tuple) and getattr(result, "status_code", 200) < 400:
        return result
    return _try_product_image_sources(product, list(getattr(product, "_denmart_durable_image_urls", []) or [])[:8], cache_seconds=604800)


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
    js = r'''const CACHE_VERSION = "denmart-public-v26-image-keep";
const STATIC_CACHE = `${CACHE_VERSION}-static`;
const IMAGE_CACHE = `${CACHE_VERSION}-images`;
const PAGE_CACHE = `${CACHE_VERSION}-pages`;
const STATIC_ASSETS = ["/static/css/app.css","/static/js/app.js","/static/js/offline-core.js","/shop/manifest.webmanifest","/shop/app-icon/192.png","/shop/app-icon/512.png"];
self.addEventListener("install", event => event.waitUntil((async()=>{const cache=await caches.open(STATIC_CACHE);await Promise.all(STATIC_ASSETS.map(async url=>{try{const r=await fetch(url,{cache:"no-store"});if(r.ok)await cache.put(url,r);}catch(_){}}));await self.skipWaiting();})()));
self.addEventListener("activate", event => {event.waitUntil((async()=>{const keys=await caches.keys();const fresh=await caches.open(IMAGE_CACHE);for(const key of keys){if(!key.startsWith("denmart-public-")||key.startsWith(CACHE_VERSION)||!key.endsWith("-images"))continue;try{const old=await caches.open(key);for(const req of await old.keys()){if(!await fresh.match(req)){const res=await old.match(req);if(res)await fresh.put(req,res);}}}catch(_){}}for(const key of keys){if(key.startsWith("denmart-public-")&&!key.startsWith(CACHE_VERSION)&&!key.endsWith("-images"))await caches.delete(key);}await self.clients.claim();})());});
async function cacheImage(cache, request, response){if(!(response&&(response.ok||response.type==="opaque")))return;try{await cache.put(request,response.clone());const keys=await cache.keys();if(keys.length>420){for(const key of keys.slice(0,keys.length-420))await cache.delete(key);}}catch(_){}}
function isPrivatePortal(path){return path==="/control"||path.startsWith("/control/")||path==="/control/offline-login"||path==="/control2"||path.startsWith("/control2/")||path==="/control2/offline-login"||path==="/merchant"||path.startsWith("/merchant/")||path==="/merchant/offline-login";}
function shouldCachePage(path){if(path==="/"||path==="/shop"||path.startsWith("/shop?")||path.startsWith("/product/")||path==="/cart"||path==="/locations"||path.startsWith("/locations/"))return true;if(["/control/offline-login","/control2/offline-login","/merchant/offline-login"].includes(path))return true;return false;}
function forbiddenPublicCache(path){return path.startsWith("/api/")||path.startsWith("/pay/order/")||path.startsWith("/pay/approval/")||path.startsWith("/pay/api/")||path.startsWith("/control/pay/")||path.startsWith("/logout");}
self.addEventListener("fetch", event => {
  const request=event.request,url=new URL(request.url);
  if(request.method!=="GET")return;
  // Product photos may be served from a trusted external image host. Cache only image
  // subresources here; never broaden this to cross-origin pages or API requests.
  if(request.destination==="image"&&url.origin!==location.origin){
    event.respondWith((async()=>{const cache=await caches.open(IMAGE_CACHE);const existing=await cache.match(request);const refresh=fetch(request).then(async response=>{await cacheImage(cache,request,response);return response;}).catch(()=>null);if(existing){event.waitUntil(refresh);return existing;}return await refresh||new Response("",{status:504});})());return;
  }
  if(url.origin!==location.origin)return;
  const path=url.pathname;
  if(path.startsWith("/api/"))return;
  if(request.destination==="style"||request.destination==="script"||path.endsWith("manifest.webmanifest")||path.includes("/shop/app-icon/")){
    event.respondWith((async()=>{const cache=await caches.open(STATIC_CACHE);try{const response=await fetch(request);if(response.ok){try{await cache.put(request,response.clone());}catch(_){}}return response;}catch(_){return await cache.match(request,{ignoreSearch:true})||new Response("Offline asset unavailable",{status:503});}})());return;
  }
  if(request.destination==="image" && !forbiddenPublicCache(path)){
    event.respondWith((async()=>{const cache=await caches.open(IMAGE_CACHE);const existing=await cache.match(request);const refresh=fetch(request).then(async response=>{await cacheImage(cache,request,response);return response;}).catch(()=>null);if(existing){event.waitUntil(refresh);return existing;}return await refresh||new Response("",{status:504});})());return;
  }
  if(request.mode==="navigate"){
    if(isPrivatePortal(path) && !["/control/offline-login","/control2/offline-login","/merchant/offline-login"].includes(path))return;
    if(!shouldCachePage(path)||forbiddenPublicCache(path))return;
    event.respondWith((async()=>{try{const response=await fetch(request);if(response.ok&&!response.redirected){try{await caches.open(PAGE_CACHE).then(c=>c.put(request,response.clone()));}catch(_){}}return response;}catch(_){const pages=await caches.open(PAGE_CACHE);const exact=await pages.match(request)||await pages.match(url.origin+path);if(exact)return exact;if(path.startsWith("/product/"))return new Response('<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1"><title>Product not saved offline</title><main style="font:16px system-ui;max-width:32rem;margin:3rem auto;padding:1rem"><h1>This product page is not saved on this device yet.</h1><p>Your basket is saved locally. Reconnect once to open this product and make it available offline.</p><a href="/shop">Return to the catalogue</a></main>',{status:503,headers:{"Content-Type":"text/html; charset=utf-8"}});if(path==="/shop"||path==="/cart")return await pages.match(url.origin+path)||await pages.match("/")||new Response("This page has not been saved on this device yet. Connect once to cache it for offline browsing.",{status:503,headers:{"Content-Type":"text/plain; charset=utf-8"}});return await pages.match("/")||new Response("This page has not been saved on this device yet. Connect once to cache it for offline browsing.",{status:503,headers:{"Content-Type":"text/plain; charset=utf-8"}});}})());
  }
});
'''
    return Response(js, mimetype="application/javascript", headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"})