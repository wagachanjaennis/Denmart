from decimal import Decimal, InvalidOperation
import secrets
from flask import Blueprint, jsonify, render_template, request, Response
from flask_login import current_user, login_required
from extensions import csrf, db
from models import Sale, SaleItem, StoreProduct, InventoryTransaction, Shift, now, Store, User
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
    return render_template("pos/index.html",store=store,shift=shift,last_agent=last_agent,business_name=current_user.business.name if current_user.business else "Denmart",footer_text="",title="Till")

@bp.get("/merchant/manifest.webmanifest")
def pos_manifest():
    base=request.host_url.rstrip("/")
    return jsonify({"name":"Denmart Till","short_name":"Till","start_url":f"{base}/merchant/on","scope":f"{base}/merchant","display":"standalone","background_color":"#24180f","theme_color":"#f29b38","description":"Store sales application.","icons":[{"src":f"{base}/static/pwa/icon.svg","sizes":"any","type":"image/svg+xml","purpose":"any maskable"}]})

@bp.get("/merchant/sw.js")
def pos_service_worker():
    js="""const CACHE='denmart-agent-v18';
self.addEventListener('install',e=>e.waitUntil(self.skipWaiting()));
self.addEventListener('activate',e=>e.waitUntil(self.clients.claim()));
self.addEventListener('fetch',e=>{const u=new URL(e.request.url);if(u.origin!==location.origin||e.request.method!=='GET'||!u.pathname.startsWith('/merchant'))return;e.respondWith(fetch(e.request).catch(()=>caches.match(e.request).then(r=>r||new Response('Till connection unavailable',{status:503}))))});
"""
    return Response(js,mimetype="application/javascript",headers={"Service-Worker-Allowed":"/merchant"})

@bp.get("/merchant/receipt/<receipt_number>")
@cashier_required
def receipt(receipt_number):
    sale=Sale.query.filter_by(receipt_number=receipt_number).first_or_404()
    if sale.store_id!=current_user.store_id:return "Forbidden",403
    items=SaleItem.query.filter_by(sale_id=sale.id).all()
    return render_template("pos/receipt.html",sale=sale,items=items)

def _create_sale(data):
    items=data.get("items") or []
    client_ref=(data.get("client_ref") or "").strip()[:80]
    shift=Shift.query.filter_by(store_id=current_user.store_id,cashier_id=current_user.id,status="OPEN").first()
    if not shift: return None,(jsonify(error="shift_not_open"),409)
    if not items: return None,(jsonify(error="cart_empty"),400)
    if client_ref:
        existing=Sale.query.filter_by(receipt_number=client_ref).first()
        if existing: return existing,(jsonify(ok=True,sale_id=existing.id,receipt_number=existing.receipt_number,total=str(existing.total),duplicate=True),200)
    subtotal=Decimal("0"); prepared=[]
    for raw in items:
        sp=(StoreProduct.query.filter_by(id=raw.get("store_product_id"),store_id=current_user.store_id).with_for_update().first())
        try: qty=Decimal(str(raw.get("quantity",0)))
        except InvalidOperation:return None,(jsonify(error="invalid_quantity"),400)
        if not sp or not sp.available_pos or not sp.is_available or qty<=0:return None,(jsonify(error="invalid_item"),400)
        available=Decimal(str(sp.stock_quantity or 0))-Decimal(str(sp.reserved_quantity or 0))
        if available<qty:return None,(jsonify(error="insufficient_stock",product=sp.product.name,available=str(available)),409)
        line=Decimal(str(sp.selling_price))*qty; subtotal+=line; prepared.append((sp,qty,line))
    receipt_number=client_ref or f"DM-{now().strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(3).upper()}"
    sale=Sale(business_id=current_user.business_id,store_id=current_user.store_id,cashier_id=current_user.id,receipt_number=receipt_number,subtotal=subtotal,total=subtotal,status="COMPLETED",completed_at=now())
    db.session.add(sale); db.session.flush()
    for sp,qty,line in prepared:
        sp.stock_quantity=Decimal(str(sp.stock_quantity or 0))-qty
        db.session.add(SaleItem(sale_id=sale.id,product_id=sp.product_id,product_name_snapshot=sp.product.name,barcode_snapshot=sp.product.barcode,unit_price=sp.selling_price,quantity=qty,line_total=line))
        db.session.add(InventoryTransaction(store_id=sp.store_id,product_id=sp.product_id,transaction_type="SALE",quantity=-qty,unit_cost=sp.cost_price,reference_type="SALE",reference_id=sale.id,created_by=current_user.id))
    db.session.commit(); audit("SALE_CREATED","Sale",sale.id,new_values={"total":str(sale.total)})
    return sale,(jsonify(ok=True,sale_id=sale.id,receipt_number=receipt_number,total=str(sale.total)),200)

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
