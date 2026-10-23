# Denmart — Online Catalogue Feeder & Advertisement Studio

This update adds an online-only barcode/image feeder and a separate advertising studio. It stores feature settings in the existing `system_settings` table; it does not add a database table or rewrite products, stock, sales, checkout records, or payments.

## 1. Online barcode and image feeder

Open **`/control/catalogue-feeder`** while signed in to the Denmart owner/admin portal. The panel reports:

- Local Denmart product and barcode counts.
- Cached feeder record, barcode, and image counts.
- Latest successful sync and the most recent connection error.
- Whether the public online catalogue is using **Current data** or **Feeder API**.

### Configure a public API

1. Paste the full product-list endpoint, for example `https://api.example.com/v1/products` (not just the provider's home page).
2. Choose the authentication method. Supported options are no auth, a Bearer token, or an API key in a custom HTTP header. Use HTTPS whenever sending credentials.
3. Map the JSON list and fields to the API's response. For example, for `{"data":{"products":[{"name":"Milk 1L","sku":"MILK-1L","barcode":"6001234567890","image_url":"https://cdn.example.com/milk.webp"}]}}`, use:
   - Product-list path: `data.products`
   - Barcode field: `barcode`
   - Image URL field: `image_url`
   - SKU field: `sku`
   - Product name field: `name`
4. Press **Test connection & sync now**. Check the status message and counts. A successful response must contain a non-empty product list.
5. Select **Use API for online shop** only after the feed has synced successfully. Use **Use my current data** to switch the online display back to Denmart's existing saved values.

Dotted JSON paths are supported, including list paths such as `images[0].url`. The feeder accepts public HTTP(S) endpoints and URL-based images; private/local API addresses are blocked. Authenticated API endpoints must use HTTPS.

### What the feeder changes

In API mode, Denmart matches feed records against existing catalogue products using SKU first, then product name, then the existing barcode. For matched products, the online product payload, barcode search, and storefront use the API's barcode and image URL. A missing API image or barcode is not silently replaced with a stale local value. This is intentionally a **display overlay**, not a remote price/stock import: local Denmart product names, prices, availability, stock, order validation, checkout, M-Pesa reconciliation, POS scanning, and offline catalogue data remain local and unchanged.

Products created in the Denmart admin, new CSV product rows, or products whose barcode/image is explicitly changed by an administrator are marked as local overrides and keep their local barcode/image. A CSV import that only updates prices/stock for an existing product does not disable the feeder for that product.

The successful feed is cached in `system_settings`. When it is older than 15 minutes, public online requests can attempt a refresh. If the provider is unavailable, Denmart keeps the last good feed and records the error on the feeder page; it does not delete or rewrite the local catalogue. In API mode, online pages need connectivity to load uncached remote image URLs; the local POS/offline catalogue is not switched to the feeder.

## 2. Advertisement studio

Open **`/advertcontrol`**. It uses the same developer operator name and password configured through the existing `DEV_NAME` and `DEV_PASS` environment variables. The regular public advert does not expose these controls.

The first-run welcome campaign is ready to edit and includes:

- **WELCOME TO DENMART ONLINE**
- Everyday groceries, home, laundry, and personal-care copy.
- **Online ordering opens 5 November 2026**.
- A generated QR code that points to `/shop`, the website URL, and a moving ticker.

The editor includes editable scene templates for Welcome/Open Soon, Back to School, Laundry & Bathing, Christmas, Everyday Essentials, and Featured Offer. Each advert may contain up to eight animated scenes of 3–15 seconds, with a theme, headline, supporting copy, call to action, optional uploaded product image, QR visibility, and campaign date range.

### A simple creative workflow

1. Choose a template and edit its headline, supporting sentence, and one call to action.
2. Upload genuine product photos you have permission to use (for example, approved Blue Band, laundry detergent, or bathing-product photos). Images are compressed in the browser before saving.
3. Enter the campaign goal in **AI idea-to-ad helper** and click **Build my AI prompt**. Copy the brief into Canva, CapCut, or Adobe Express when you want an additional AI-created visual, voice-over, or finished edit. Their features and free limits are controlled by those services.
4. Use **Preview voice-over** to hear the on-device browser voice preview. This is a listening aid; it is not embedded into the downloaded video.
5. Review the animated preview, scan-check the QR code, and verify all dates, product claims, and prices.
6. Click **Save draft** to keep edits private, or **Publish to ad screen** to change the live screen. To schedule an advert, enable scheduling, choose a start date (and optional end date), then publish. The current ad stays live until the schedule window starts; the old published advert resumes when the schedule ends unless another scheduled advert is active.
7. Open **`/advertisement`** on a TV, tablet, kiosk, or browser. It is a clean 16:9 full-screen animated player without editing controls. Clicking/tapping the screen requests fullscreen where the browser supports it.

The built-in player animates typography, background, product-style motion graphics, scene transitions, the QR card, and the scrolling ticker. **Export animated video** records the animation as WebM in a modern Chrome/Edge browser. The WebM export is silent; add a music/voice-over track in a video editor and export MP4 there if the campaign needs audio or MP4 delivery. Direct AI video generation is not hosted inside Denmart: the prompt helper prepares a good brief for the external creative tools.

## 3. Routes and storage

- Feeder: `/control/catalogue-feeder`
- Developer ad editor: `/advertcontrol`
- Clean public display: `/advertisement` (alias `/advertisement/screen`)
- Current campaign JSON: `/advertisement/current.json`
- QR PNG: `/advertisement/qr.png`

Feeder configuration, the last good cache, override IDs, draft campaigns, published campaigns, and scheduled campaigns use new keys in the existing `system_settings` table. No new database table or schema migration is needed. The public advertising screen is marked `noindex`; robots rules also discourage indexing of the developer/control routes (authentication remains the actual protection).

## 4. Deployment notes

Deploy this source alongside the existing `requirements.txt` and environment variables. Keep the existing `DEV_NAME`, `DEV_PASS`, `SECRET_KEY`, database URL, and payment/gateway variables configured as before. On first use, check `/control/catalogue-feeder` in **Current data** mode; connect and sync a feed before switching to API mode. Test the shop, checkout, and POS after deployment. The original SQLite and JSON backup files supplied with this source bundle are kept separately and have not been edited.
