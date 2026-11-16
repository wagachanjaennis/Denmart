# Denmart Universal Bulk Product Editor — 16 November 2026

## What changed

The Products admin page now includes a Universal Bulk Product Editor above the existing single-item barcode/quick-entry form.

- Drop multiple product photos into the upload area or choose them from a phone/computer.
- Each photo becomes one new product card with an editable product name.
- Selling price and opening quantity are optional for each item.
- Blank price is saved as an unpriced draft and remains disabled for online/POS sale until priced later.
- Blank quantity is saved as zero opening stock.
- A positive selling price enables the product for online and POS sale.
- A common mart and optional category can be selected for the whole batch.
- Save all products with one action. The server validates the batch before writing and uses one database transaction; a failed save rolls back the entire batch.
- Product images are normalized to WebP and stored through Denmart's existing Product and ProductImage image persistence path.

## Limits and data safety

- Maximum 30 photos per batch.
- Maximum 8 MB per photo and 64 MB per request.
- No database schema migration is required.
- Existing quick barcode entry, product editing, CSV import, inventory, and photo-first storefront sorting remain available.
- Stock values are opening stock additions, not replacements for any existing stock. This workflow creates new product records only.
- The update does not include or replace any SQLite/JSON database, backup, secret, or environment file.

## GitHub upload

Extract the ZIP at the repository root and replace/add the files at the exact paths in `GITHUB_UPLOAD_LIST.txt`. The archive is an overlay patch, not a full application export. Do not upload database backups or environment secrets.
