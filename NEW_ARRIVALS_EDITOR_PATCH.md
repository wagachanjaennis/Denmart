# Denmart arrivals-to-catalogue integration

This release makes the 53 bundled arrival photos real, searchable catalogue products.

## Deployment workflow

1. Back up the live SQLite database before deploying. The database is intentionally not bundled in this ZIP.
2. Deploy the complete project ZIP.
3. Sign in as an owner with `products.create` permission and open **Catalogue and stock → New arrivals**.
4. Select the target mart and use **Register all 53 arrivals as products** once. This idempotent action creates a `Product` and mart-specific `StoreProduct` draft for each photo, attaches the photo, and stores “New Product N” / “New Arrival N” as searchable aliases. Repeating it does not create duplicates.
5. Open **Products** and search `New arrival` to find the whole set, or search a product name / `New Product N`. Edit names, barcode, category, selling price, cost and stock in the existing product editor. Drafts can be saved with a zero price while disabled.
6. To publish an item, enter a real selling price and stock, then enable it and tick Online in its mart settings. Once available and in stock, its homepage arrival tile links to its product detail and has an Add to basket button using the normal Denmart cart ID.

## Notes

- Initial product names are photo-based starter descriptions. Where a package label or exact variant is not legible, the name is deliberately generic and should be confirmed during stock-taking. No barcode, price or stock quantity is fabricated.
- The storefront displays “Price being updated” for unpriced drafts. Unpriced or out-of-stock items cannot be added to the basket.
- Existing product, basket, barcode, inventory and checkout tables are reused. No schema migration is required.
- This release changes backend routes, the homepage/product templates, admin navigation and the arrivals CSS. Deploy the full project ZIP rather than only static/templates.
