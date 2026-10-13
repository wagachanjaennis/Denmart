from decimal import Decimal, InvalidOperation
import secrets
from flask import Blueprint, jsonify, render_template, request, Response
from flask_login import current_user, login_required
from extensions import csrf, db
from models import Sale, SaleItem, StoreProduct, InventoryTransaction, Shift, now, Store, User, SystemSetting
from services.branding import brand_display_name
from services.audit import audit

bp=Blueprint("pos", __name__)

def cashier_required(fn):
    from functools import wraps
    @wraps(fn)
    @login_required
    def wrapped(*args,**kwargs):
        from flask import session
        if session.get("portal")!="pos" or not current_user.is_active or not current_user.business_id or not current_user.role:
            return jsonify(error="forbidden"),403
        if not current_user.store_id:
            store=Store.query.filter_by(business_id=current_user.business_id,is_active=True).order_by(Store.created_at).first()
            if not store:return jsonify(error="no_active_store"),503
            current_user.store_id=store.id; db.session.commit()
        return fn(*args,**kwargs)
    return wrapped

@bp.get("/merchant/on")
@cashier_required
def dashboard_entry():
    store=db.session.get(Store,current_user.store_id)
    shift=Shift.query.filter_by(store_id=current_user.store_id,cashier_id=current_user.id,status="OPEN").first()
    last_agent=User.query.filter(User.business_id==current_user.business_id,User.store_id==current_user.store_id,User.id!=current_user.id,User.last_login_at.isnot(None)).order_by(User.last_login_at.desc()).first()
    brand = SystemSetting.query.filter_by(business_id=current_user.business_id, key="brand_name").first()
    display_name = brand_display_name(brand.value if brand else "")
    return render_template("pos/index.html",store=store,shift=shift,last_agent=last_agent,business_name=display_name,footer_text="",title="Till")

@bp.get("/merchant/manifest.webmanifest")
def pos_manifest():
    base=request.host_url.rstrip("/")
    business = Store.query.filter_by(is_active=True).order_by(Store.created_at).first()
    brand = SystemSetting.query.filter_by(business_id=(business.business_id if business else None), key="brand_name").first() if business else None
    display_name = brand_display_name(brand.value if brand else "")
    return jsonify({"name":f"{display_name} Till","short_name":"Till","start_url":f"{base}/merchant/on","scope":f"{base}/merchant","display":"standalone","background_color":"#f5faf7","theme_color":"#10a37f","description":"Store sales application.","icons":[{"src":f"{base}/static/pwa/icon.svg","sizes":"any","type":"image/svg+xml","purpose":"any maskable"}]})

@bp.get("/merchant/sw.js")
def pos_service_worker():
    js = r"""const CACHE='denmart-agent-offline-v3';
const STATIC=CACHE+'-static', PAGES=CACHE+'-pages', IMAGES=CACHE+'-images', DB='denmart-device-v2', STORE='records';
const ASSETS=['/static/css/app.css','/static/js/pos.js','/static/js/offline-core.js','/static/pwa/icon.svg','/static/pwa/pos-offline.html','/merchant/manifest.webmanifest','/merchant/offline-login'];
async function openDB(){return new Promise((resolve,reject)=>{const r=indexedDB.open(DB,1);r.onupgradeneeded=()=>{if(!r.result.objectStoreNames.contains(STORE))r.result.createObjectStore(STORE,{keyPath:'key'});};r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);});}
async function readLocal(key){try{const db=await openDB();return await new Promise((resolve,reject)=>{const r=db.transaction(STORE,'readonly').objectStore(STORE).get(key);r.onsuccess=()=>resolve(r.result?.value);r.onerror=()=>reject(r.error);});}catch(_){return null;}}
async function writeLocal(key,value){try{const db=await openDB();await new Promise((resolve,reject)=>{const tx=db.transaction(STORE,'readwrite');tx.objectStore(STORE).put({key,value,updatedAt:new Date().toISOString()});tx.oncomplete=resolve;tx.onerror=tx.onabort=()=>reject(tx.error);});}catch(_){}}
async function allowedOffline(){const session=await readLocal('offline:session:pos');if(!session||!session.username||Date.now()-Number(session.lastActive||0)>30*60*1000)return false;const owner=await readLocal('offline:cache-owner:pos');const cred=await readLocal('offline:credential:pos:'+session.username);if(!owner||owner.username!==session.username||!cred||!cred.verified||Date.now()-Number(cred.activatedAt||0)>30*24*60*60*1000)return false;await writeLocal('offline:session:pos',{...session,lastActive:Date.now()});return true;}
async function cachePage(request,response){try{if(!response.ok||response.redirected||new URL(response.url).pathname!==new URL(request.url).pathname)return;const body=await response.clone().text();if(!body.includes('<html')&&!body.includes('<!doctype'))return;if(!body.includes('name="offline-access-portal" content="pos"'))return;const match=body.match(/<meta name="offline-access-user" content="([^"]+)"/);if(!match||!match[1])return;const username=match[1].trim().toLocaleLowerCase();const cred=await readLocal('offline:credential:pos:'+username);const pending=await readLocal('offline:pending-credential:pos:'+username);if(!(cred&&cred.verified)&&!(pending&&pending.createdAt&&Date.now()-Number(pending.createdAt)<10*60*1000))return;const owner=await readLocal('offline:cache-owner:pos');const pageCache=await caches.open(PAGES);if(owner&&owner.username&&owner.username!==username){for(const key of await pageCache.keys())await pageCache.delete(key);}await pageCache.put(request,response.clone());}catch(_){}}
async function offlinePage(request){const url=new URL(request.url),path=url.pathname;if(path==='/merchant/offline-login'||path==='/merchant')return (await caches.match('/merchant/offline-login'))||(await caches.match('/merchant'))||new Response('Offline. Sign in online once to enable offline till access.',{status:503});if(await allowedOffline()){const c=await caches.open(PAGES);const hit=await c.match(request)||await c.match(url.origin+path);if(hit)return hit;const home=await c.match('/merchant/on');if(home)return home;}return (await caches.match('/merchant/offline-login'))||(await caches.match('/static/pwa/pos-offline.html'))||new Response('Till offline. Sign in online once first.',{status:503,headers:{'Content-Type':'text/plain; charset=utf-8'}});}
self.addEventListener('install',e=>e.waitUntil((async()=>{const c=await caches.open(STATIC);await Promise.all(ASSETS.map(async u=>{try{const r=await fetch(u,{cache:'no-store'});if(r.ok)await c.put(u,r);}catch(_){}}));await self.skipWaiting();})()));
self.addEventListener('activate',e=>e.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k.startsWith('denmart-agent-')&&k!==STATIC&&k!==PAGES&&k!==IMAGES).map(k=>caches.delete(k)))).then(()=>self.clients.claim())));
self.addEventListener('fetch',e=>{const req=e.request,u=new URL(req.url);if(req.method!=='GET')return;if(req.destination==='image'){e.respondWith((async()=>{const c=await caches.open(IMAGES);const old=await c.match(req);const refresh=fetch(req).then(async r=>{if(r.ok||r.type==='opaque'){try{await c.put(req,r.clone());}catch(_){}}return r;}).catch(()=>null);if(old){e.waitUntil(refresh);return old;}return await refresh||new Response('',{status:504});})());return;}if(u.origin!==location.origin)return;const asset=req.destination==='style'||req.destination==='script'||req.destination==='font'||['/static/css/app.css','/static/js/pos.js','/static/js/offline-core.js','/static/pwa/icon.svg','/static/pwa/pos-offline.html','/merchant/manifest.webmanifest'].includes(u.pathname);if(asset){e.respondWith((async()=>{const c=await caches.open(STATIC);try{const r=await fetch(req);if(r.ok)c.put(req,r.clone());return r;}catch(_){return await c.match(req,{ignoreSearch:true})||new Response('',{status:503});}})());return;}if(u.pathname==='/merchant/offline-login'||u.pathname==='/merchant'||u.pathname==='/merchant/on'||u.pathname.startsWith('/merchant/')){if(u.pathname==='/merchant/sw.js')return;e.respondWith((async()=>{try{const r=await fetch(req);if(req.mode==='navigate')await cachePage(req,r);return r;}catch(_){if(req.mode==='navigate')return offlinePage(req);return new Response('Till action unavailable offline. Cash sales can be queued by the local POS workspace.',{status:503,headers:{'Content-Type':'text/plain; charset=utf-8'}});}})());}});
"""
    return Response(js, mimetype="application/javascript", headers={"Service-Worker-Allowed": "/merchant", "Cache-Control": "no-cache"})
@bp.get("/merchant/receipt/<receipt_number>")
@cashier_required
def receipt(receipt_number):
    sale=Sale.query.filter_by(receipt_number=receipt_number).first_or_404()
    if sale.store_id!=current_user.store_id:return "Forbidden",403
    if sale.status != "COMPLETED":
        return Response("This sale has not been approved and completed yet. No receipt is available until approval.", status=409, mimetype="text/plain")
    items=SaleItem.query.filter_by(sale_id=sale.id).all()
    return render_template("pos/receipt.html",sale=sale,items=items)

def _create_sale(data):
    items=data.get("items") or []
    client_ref=(data.get("client_ref") or "").strip()[:60]
    # Idempotency lookup must run before shift validation: the original request may
    # have committed while its response was lost and the shift may since be closed.
    if client_ref:
        existing=Sale.query.filter_by(receipt_number=client_ref).first()
        if existing:
            if existing.store_id != current_user.store_id or existing.cashier_id != current_user.id:
                return None,(jsonify(error="client_ref_conflict",message="This sale reference belongs to another till or cashier."),409)
            return existing,(jsonify(ok=True,sale_id=existing.id,receipt_number=existing.receipt_number,total=str(existing.total),status=existing.status,approval_required=existing.status!="COMPLETED",duplicate=True),200)
    shift=Shift.query.filter_by(store_id=current_user.store_id,cashier_id=current_user.id,status="OPEN").first()
    if not shift: return None,(jsonify(error="shift_not_open"),409)
    if not items: return None,(jsonify(error="cart_empty"),400)
    subtotal=Decimal("0"); prepared=[]
    for raw in items:
        sp=(StoreProduct.query.filter_by(id=raw.get("store_product_id"),store_id=current_user.store_id).with_for_update().first())
        try: qty=Decimal(str(raw.get("quantity",0)))
        except InvalidOperation:return None,(jsonify(error="invalid_quantity"),400)
        if not sp or not sp.available_pos or not sp.is_available or qty<=0:return None,(jsonify(error="invalid_item"),400)
        # Offline transactions carry the price the cashier actually saw. Never
        # silently recalculate at a changed price during reconnect/sync.
        if raw.get("unit_price") is not None:
            try: expected_price=Decimal(str(raw.get("unit_price"))).quantize(Decimal("0.01"))
            except InvalidOperation:return None,(jsonify(error="invalid_price"),400)
            current_price=Decimal(str(sp.selling_price)).quantize(Decimal("0.01"))
            if expected_price != current_price:
                return None,(jsonify(error="price_changed",product=sp.product.name,recorded_price=str(expected_price),current_price=str(current_price),message="The product price changed since this basket was saved. This sale was not submitted; review the basket and confirm the price with the customer."),409)
        available=Decimal(str(sp.stock_quantity or 0))-Decimal(str(sp.reserved_quantity or 0))
        if available<qty:return None,(jsonify(error="insufficient_stock",product=sp.product.name,available=str(available)),409)
        line=Decimal(str(sp.selling_price))*qty; subtotal+=line; prepared.append((sp,qty,line))
    receipt_number=client_ref or f"DM-{now().strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(3).upper()}"
    sale=Sale(business_id=current_user.business_id,store_id=current_user.store_id,cashier_id=current_user.id,receipt_number=receipt_number,subtotal=subtotal,total=subtotal,status="PENDING_APPROVAL",completed_at=None)
    db.session.add(sale); db.session.flush()
    for sp,qty,line in prepared:
        # Hold stock while cash approval is pending. Cashiers cannot complete a sale
        # merely by pressing the button; inventory changes only after owner approval.
        sp.reserved_quantity=Decimal(str(sp.reserved_quantity or 0))+qty
        db.session.add(SaleItem(sale_id=sale.id,product_id=sp.product_id,product_name_snapshot=sp.product.name,barcode_snapshot=sp.product.barcode,unit_price=sp.selling_price,quantity=qty,line_total=line))
    db.session.commit(); audit("SALE_PENDING_APPROVAL","Sale",sale.id,new_values={"total":str(sale.total),"status":"PENDING_APPROVAL"})
    return sale,(jsonify(ok=True,sale_id=sale.id,receipt_number=receipt_number,total=str(sale.total),status=sale.status,approval_required=True,message="Cash sale submitted for administrator approval. It is not completed and stock has not been deducted yet."),200)

@csrf.exempt
@bp.post("/api/pos/sales")
@cashier_required
def create_sale():
    sale,response=_create_sale(request.get_json(silent=True) or {})
    if response:return response

@csrf.exempt
@bp.post("/api/pos/shifts/open")
@cashier_required
def open_shift():
    existing=Shift.query.filter_by(store_id=current_user.store_id,cashier_id=current_user.id,status="OPEN").first()
    if existing:return jsonify(error="shift_already_open",id=existing.id),409
    shift=Shift(store_id=current_user.store_id,cashier_id=current_user.id)
    db.session.add(shift); db.session.commit(); audit("SHIFT_OPENED","Shift",shift.id,new_values={})
    return jsonify(ok=True,shift_id=shift.id)

@csrf.exempt
@bp.post("/api/pos/shifts/close")
@cashier_required
def close_shift():
    shift=Shift.query.filter_by(store_id=current_user.store_id,cashier_id=current_user.id,status="OPEN").first()
    if not shift:return jsonify(error="shift_not_open"),409
    shift.closed_at=now(); shift.status="CLOSED"
    db.session.commit(); audit("SHIFT_CLOSED","Shift",shift.id,new_values={})
    return jsonify(ok=True,shift_id=shift.id)

@bp.get("/api/pos/day-summary")
@cashier_required
def day_summary():
    today=db.func.date(Sale.created_at)==db.func.current_date()
    count,total=db.session.query(db.func.count(Sale.id),db.func.coalesce(db.func.sum(Sale.total),0)).filter(Sale.store_id==current_user.store_id,Sale.status=="COMPLETED",today).first()
    return jsonify(ok=True,sales_count=int(count or 0),sales_total=str(total or 0))

@csrf.exempt
@bp.post("/api/pos/sync/offline")
@cashier_required
def sync_offline():
    data=request.get_json(silent=True) or {}; queue=data.get("sales") or []
    if not isinstance(queue,list):return jsonify(error="invalid_queue"),400
    if len(queue)>50:return jsonify(error="queue_too_large"),413
    results=[]
    for sale_data in queue:
        if not isinstance(sale_data,dict): results.append({"ok":False,"error":"invalid_sale"}); continue
        try:
            sale,response=_create_sale(sale_data)
            if response is not None:
                body,status=response
                # Flask response objects are safe to inspect only after get_json().
                payload=body.get_json(silent=True) or {}
                results.append({"ok":status<400,**payload})
            else:
                results.append({"ok":True,"sale_id":sale.id,"receipt_number":sale.receipt_number,"total":str(sale.total)})
        except Exception:
            db.session.rollback(); results.append({"ok":False,"client_ref":sale_data.get("client_ref"),"error":"sync_failed"})
    return jsonify(ok=all(x.get("ok") for x in results) if results else True,results=results)
