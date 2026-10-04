from datetime import datetime, timezone
from extensions import db
from models import Business, Store, Role, Permission, User, Category, Product, ProductAlias, PricingRule, StoreProduct, Supplier, Customer, Sale, SaleItem, GatewaySmsMessage, LoyaltyAccount, LoyaltyTransaction, PaySettings, PayOrder, PayOrderItem, PayReceipt, PayEvent

TABLES=[Business,Store,Role,Permission,User,Category,Product,ProductAlias,PricingRule,StoreProduct,Supplier,Customer,Sale,SaleItem,GatewaySmsMessage,LoyaltyAccount,LoyaltyTransaction,PaySettings,PayOrder,PayOrderItem,PayReceipt,PayEvent]

def export_business(business_id):
    data={"format":"denmart-json-v2","exported_at":datetime.now(timezone.utc).isoformat(),"business_id":business_id,"tables":{}}
    for model in TABLES:
        rows=model.query.filter_by(business_id=business_id).all() if hasattr(model,"business_id") else model.query.all()
        data["tables"][model.__tablename__]=[{c.name:(getattr(row,c.name).isoformat() if hasattr(getattr(row,c.name),"isoformat") else getattr(row,c.name)) for c in model.__table__.columns} for row in rows]
    return data
