"""Helpers for turning bundled Denmart new-arrival photos into real products."""
from pathlib import Path

from models import Product, ProductAlias, Store, StoreProduct

ARRIVAL_ALIAS_TYPE = "NEW_ARRIVAL_ASSET"
ARRIVAL_ALIAS_PREFIX = "__DENMART_NEW_ARRIVAL__:"
ARRIVAL_STATIC_PREFIX = "/static/catalogue/new-arrivals/"


def arrival_alias(filename: str) -> str:
    return ARRIVAL_ALIAS_PREFIX + str(filename or "").strip()


def list_arrival_photos(root_path) -> list[str]:
    folder = Path(root_path) / "static" / "catalogue" / "new-arrivals"
    if not folder.is_dir():
        return []
    return sorted(
        path.name for path in folder.iterdir()
        if path.is_file() and path.suffix.lower() == ".webp" and path.name.startswith("IMG-")
    )


def arrival_product_map(filenames: list[str], business_id: str | None):
    """Return {filename: Product} for assets already connected to this business."""
    if not filenames or not business_id:
        return {}

    markers = [arrival_alias(name) for name in filenames]
    alias_rows = ProductAlias.query.filter(
        ProductAlias.alias_type == ARRIVAL_ALIAS_TYPE,
        ProductAlias.alias.in_(markers),
    ).all()
    marker_to_product_id = {row.alias: row.product_id for row in alias_rows}
    product_ids = set(marker_to_product_id.values())

    # Also recognize photos connected by the image URL, including products created
    # by an earlier build before the persistent source-asset alias was added.
    image_urls = [ARRIVAL_STATIC_PREFIX + name for name in filenames]
    image_rows = (Product.query.join(StoreProduct, StoreProduct.product_id == Product.id)
                  .join(Store, Store.id == StoreProduct.store_id)
                  .filter(Store.business_id == business_id, Product.image_url.in_(image_urls))
                  .distinct().all())
    image_to_product_id = {
        str(product.image_url or "").strip().removeprefix(ARRIVAL_STATIC_PREFIX): product.id
        for product in image_rows
    }
    product_ids.update(image_to_product_id.values())
    if not product_ids:
        return {}

    products = (Product.query.join(StoreProduct, StoreProduct.product_id == Product.id)
                .join(Store, Store.id == StoreProduct.store_id)
                .filter(Store.business_id == business_id, Product.id.in_(product_ids))
                .distinct().all())
    by_id = {product.id: product for product in products}
    result = {}
    for filename in filenames:
        product_id = marker_to_product_id.get(arrival_alias(filename)) or image_to_product_id.get(filename)
        if product_id in by_id:
            result[filename] = by_id[product_id]
    return result


def arrival_store_product_map(product_ids: set[str], business_id: str, store_id: str | None = None):
    """Return a preferred store-product row for each mapped arrival product."""
    if not product_ids or not business_id:
        return {}
    query = (StoreProduct.query.join(Store, Store.id == StoreProduct.store_id)
             .filter(Store.business_id == business_id, StoreProduct.product_id.in_(product_ids)))
    rows = query.order_by(Store.name).all()
    result = {}
    for row in rows:
        if row.product_id not in result or (store_id and row.store_id == store_id):
            result[row.product_id] = row
    return result


def build_arrival_cards(root_path, business_id: str | None, store_id: str | None = None):
    filenames = list_arrival_photos(root_path)
    products = arrival_product_map(filenames, business_id)
    store_products = arrival_store_product_map({p.id for p in products.values()}, business_id, store_id)
    cards = []
    for index, filename in enumerate(filenames, start=1):
        product = products.get(filename)
        cards.append({
            "filename": filename,
            "number": index,
            "image_url": ARRIVAL_STATIC_PREFIX + filename,
            "product": product,
            "store_product": store_products.get(product.id) if product else None,
        })
    return cards
