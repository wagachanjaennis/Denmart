# Denmart New Arrivals Product Editor

## What changed

- Added `/control/new-arrivals`, an owner-only catalogue screen that lists the bundled photos in `static/catalogue/new-arrivals/` and shows whether each photo is connected to a database product.
- Each unregistered photo can be turned into a normal searchable product with name, brand, barcode, category, selling price, cost and opening stock.
- Saving without a selling price creates a disabled draft. It can be named and assigned a barcode first, then completed through the existing product editor. A zero-price draft cannot be enabled for online or POS sales.
- Each product keeps a source-asset alias so the manager remembers which arrival photo belongs to it, even if an administrator later replaces the product image.
- The public homepage's Fresh Arrivals strip now reads those photos dynamically. Once a product is named and has a positive enabled online price, the homepage shows the product name and KES price and links to its product page; unfinished items remain marked as new arrivals / price being updated.
- Added the New arrivals link under Catalogue and stock in the admin navigation.

## Database impact

No existing table or column is added. The feature uses the current `products`, `store_products`, and `product_aliases` tables, so no database migration is required. The source photo itself remains in the project under `static/catalogue/new-arrivals/`.

## Admin workflow

1. Open **Control Centre → Catalogue and stock → New arrivals**.
2. Choose the mart where the item belongs.
3. Name each item, scan/type the barcode, and optionally add its brand, category, price, cost and opening quantity.
4. If the price is not known yet, leave both price fields blank. The product is saved as a disabled draft.
5. Use **Edit name, barcode, price & stock** on a registered item, or search it under **Products**, to finish or update it.

## Notes

The editor discovers photos directly from the bundled folder rather than depending on a hardcoded 52-item list. The uploaded source currently contains 53 WebP arrival photos.
