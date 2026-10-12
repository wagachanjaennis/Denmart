# Denmart search, scanner and performance patch

This patch contains only the files updated for these improvements. It does not include product photos, the database, payment secrets, environment files, or unrelated project code.

## Apply the patch

1. Make a backup of your current Denmart repository first.
2. Extract this ZIP into the **root of the Denmart repository** (the folder where `app.py` is located), keeping the folder paths. Allow it to replace the matching files.
3. Commit and push the replaced files and the new `tests_search.py` / this guide to the same GitHub repository, then let Render deploy.
4. When the deployment is live, test `/shop`, `/scan`, `/control/products`, and `/control/reports`.

## What changed

- **Catalogue search:** stronger word matching so every search word must match the product; product relevance is no longer pushed below products merely because those products have photos. Search suggestions appear while typing and `/shop` filters its product grid live. Search requests stay scoped to the selected mart/category where those are selected.
- **Barcode scanning:** the stock-scan field is focused on opening, accepts the output of USB/Bluetooth keyboard-mode scanners, and automatically looks up scans whether the scanner appends Enter or not. Camera scan attempts every barcode format exposed by that browser's `BarcodeDetector`, including available 1D and 2D formats. Barcode fields in Add/Edit Product also support keyboard-mode scanners.
- **Performance:** `/control/reports` is now labelled **Performance & graphs**, with daily sales line graph, daily units bar graph, top-product bars, key metrics and automatic refresh every 30 seconds. Sales totals are aggregated separately from sale lines to avoid multiplying a receipt total by the number of products on that receipt.
- **Cache updates:** updated JavaScript/CSS version strings ask browsers to load the new files.

## Scanner compatibility note

Most USB/Bluetooth barcode readers can be configured as a keyboard (often called HID keyboard or keyboard-wedge mode); that mode works with the barcode fields. This includes the scanner's decoded text regardless of whether it reads a 1D or 2D code. A scanner that requires a proprietary desktop driver, serial-port protocol, or vendor SDK instead of typing as a keyboard may need a device-specific bridge and cannot be guaranteed by a browser text field alone. Camera formats depend on what the active browser reports as supported.

## Validation performed

- Five focused product-search regression tests pass.
- Python source compilation and affected Jinja template parsing pass.
- JavaScript syntax checks pass for `static/js/app.js` and `static/js/scan.js`.

The physical scanner and live Render database were not available in this local build environment, so the actual hardware and deployment still need a quick on-device check after upload.
