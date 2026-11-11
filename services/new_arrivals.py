"""Helpers for turning bundled Denmart new-arrival photos into real products."""
from pathlib import Path

from models import Product, ProductAlias, Store, StoreProduct

ARRIVAL_ALIAS_TYPE = "NEW_ARRIVAL_ASSET"
ARRIVAL_ALIAS_PREFIX = "__DENMART_NEW_ARRIVAL__:"
ARRIVAL_STATIC_PREFIX = "/static/catalogue/new-arrivals/"

# Human-readable starter identities based on the supplied arrival photographs.
# Where packaging text or an exact variant is not legible, the name stays generic
# so the administrator can refine it without us inventing a brand or size.
ARRIVAL_DEFAULT_NAMES = {
    'IMG-20261013-WA0003.webp': 'Assorted Plastic Kitchen Storage Bowls',
    'IMG-20261107-WA0000.webp': 'Plastic Food Storage Container Set',
    'IMG-20261107-WA0001.webp': 'Clear Glass Serving Jugs',
    'IMG-20261107-WA0002.webp': 'Assorted Footballs',
    'IMG-20261107-WA0003.webp': 'Jasiri Packaged Grocery Item',
    'IMG-20261107-WA0004.webp': 'Mini Doll Toys',
    'IMG-20261107-WA0005.webp': 'Woven Plastic Storage Baskets',
    'IMG-20261107-WA0006.webp': 'Reusable Water Bottles and Flasks',
    'IMG-20261107-WA0007.webp': 'Glass Food Storage Jars with Lids',
    'IMG-20261107-WA0008.webp': 'Large Plastic Storage Tub',
    'IMG-20261107-WA0009.webp': 'Woven Household Storage Baskets',
    'IMG-20261107-WA0010.webp': 'Woven Household Storage Baskets - Assorted',
    'IMG-20261107-WA0011.webp': 'Assorted Colourful Hair Accessories',
    'IMG-20261107-WA0012.webp': 'Packaged Household Accessories',
    'IMG-20261107-WA0013.webp': 'Pink Bath Scrubbing Gloves',
    'IMG-20261107-WA0014.webp': 'Packaged Personal Care Accessories',
    'IMG-20261107-WA0015.webp': 'Packaged Kitchen and Household Utensils',
    'IMG-20261107-WA0016.webp': 'Green Plastic Storage Basket',
    'IMG-20261107-WA0017.webp': 'Plastic Buckets with Lids',
    'IMG-20261107-WA0018.webp': 'Woven Plastic Laundry Baskets',
    'IMG-20261107-WA0019.webp': 'Assorted Fashion Belts',
    'IMG-20261107-WA0020.webp': 'Household Cleaning Brushes',
    'IMG-20261107-WA0021.webp': 'Berry Bliss Packaged Snacks',
    'IMG-20261107-WA0022.webp': 'Clear Disposable Plastic Cups',
    'IMG-20261107-WA0023.webp': 'Reusable Plastic Water Bottles',
    'IMG-20261107-WA0024.webp': 'Food Storage Lunch Box Set',
    'IMG-20261107-WA0025.webp': 'Super Glue Adhesive',
    'IMG-20261107-WA0026.webp': 'White Plastic Storage Basket',
    'IMG-20261107-WA0027.webp': 'Plastic Food Containers with Coloured Lids',
    'IMG-20261107-WA0028.webp': 'Woven Plastic Storage Baskets - Assorted Colours',
    'IMG-20261107-WA0029.webp': 'Plastic Desk and Kitchen Organisers',
    'IMG-20261107-WA0030.webp': 'Assorted Small Toys',
    'IMG-20261107-WA0031.webp': 'Assorted Sweets and Lollipops',
    'IMG-20261107-WA0032.webp': 'Assorted Household Plastic Items',
    'IMG-20261107-WA0033.webp': 'White Plastic Step Stool',
    'IMG-20261107-WA0034.webp': 'White Plastic Step Stool',
    'IMG-20261107-WA0035.webp': 'Assorted Colourful Toy Sticks',
    'IMG-20261107-WA0036.webp': 'Plastic Table Mat',
    'IMG-20261107-WA0037.webp': 'Mint Chocolate Snack Bars',
    'IMG-20261107-WA0038.webp': 'Assorted Lollipops and Sweets',
    'IMG-20261107-WA0039.webp': 'Cadbury Dairy Milk Chocolate',
    'IMG-20261107-WA0040.webp': 'Packaged Hair Extensions',
    'IMG-20261107-WA0041.webp': 'Cadbury Dairy Milk White Chocolate',
    'IMG-20261107-WA0042.webp': 'Assorted Chocolate Snack Bars',
    'IMG-20261107-WA0043.webp': 'Star Brand Biryani Rice',
    'IMG-20261107-WA0044.webp': 'Assorted Balloons',
    'IMG-20261107-WA0045.webp': 'Red Packaged Snack Bars',
    'IMG-20261107-WA0046.webp': 'Packaged Hair Extensions',
    'IMG-20261107-WA0047.webp': 'Household Cleaning Brushes',
    'IMG-20261107-WA0048.webp': 'Always Sanitary Pads',
    'IMG-20261107-WA0049.webp': 'LED Light Bulbs',
    'IMG-20261107-WA0050.webp': 'Green Woven Plastic Laundry Basket',
    'IMG-20261107-WA0051.webp': 'Packaged Hair Extensions',
}

def default_arrival_name(filename: str, number: int | None = None) -> str:
    return ARRIVAL_DEFAULT_NAMES.get(filename, f'New Product {number or ""}'.strip())


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
    alias_rows = (ProductAlias.query.join(Product, Product.id == ProductAlias.product_id)
                  .join(StoreProduct, StoreProduct.product_id == Product.id)
                  .join(Store, Store.id == StoreProduct.store_id)
                  .filter(Store.business_id == business_id,
                          ProductAlias.alias_type == ARRIVAL_ALIAS_TYPE,
                          ProductAlias.alias.in_(markers))
                  .distinct().all())
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
    if store_id:
        query = query.filter(StoreProduct.store_id == store_id)
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
            "default_name": default_arrival_name(filename, index),
            "image_url": ARRIVAL_STATIC_PREFIX + filename,
            "product": product,
            "store_product": store_products.get(product.id) if product else None,
        })
    return cards
