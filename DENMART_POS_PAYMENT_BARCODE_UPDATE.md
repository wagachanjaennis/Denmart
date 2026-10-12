# Denmart — POS payment and barcode autofill update

This is a **targeted incremental patch** for the existing Denmart repository. It is not a replacement project and does not include product images or a database.

## Apply the patch

1. Back up the current repository and database first.
2. Extract this ZIP into the **root of the existing Denmart repository** (the same directory containing `app.py`). Keep the folder paths and overwrite files with matching paths.
3. Commit and push the changed files to the existing GitHub repository so Render deploys them.
4. After deployment, sign in as administrator and review **Admin → PAY** before testing bank transfers.

Do not upload this patch as a new repository or delete existing product images, uploads, database files, persistent disk contents, or environment variables.

## Included changes

- POS barcode scans are treated as exact identifiers; an unknown barcode no longer falls back to a loose text search that can display unrelated products.
- POS has a direct cash completion action and an automatic M-PESA/bank-transfer matching flow. POS no longer asks for the customer's name or phone for the electronic payment request; the Android gateway receipt supplies payer details when its SMS contains them.
- A unique, exact-amount receipt for the selected payment route can complete the POS sale automatically. Overpayments, underpayments, ambiguous matches, stock conflicts, and other uncertain cases remain for administrator review.
- Admin → PAY includes the receiving bank account name, number, and transfer instructions. Configure the real details before using the bank method.
- Incoming bank-credit SMS is only eligible for automatic matching when it identifies the configured Denmart receiving account (full account number, or last four digits with account context). Bank messages that do not identify that account are saved for administrator review and are never auto-completed. If there is a likely pending POS amount, it is shown as a review candidate. Configure your real account and verify your bank's SMS format with a small test transfer before relying on auto-matching.
- Scanning in the Add/Edit Product form attempts to populate name, brand, category, SKU, unit, pack size, description, and a trusted product image where available. Price, cost, and stock quantity are deliberately not guessed. The scanner capture supports keyboard-wedge USB/Bluetooth scanners, including common 1D barcodes and GS1/2D payloads when the scanner sends them as keyboard input.
- Existing inventory transactions and old-stock/FIFO tracking are retained; the patch does not replace inventory records or rewrite stock layers.
- This is incremental to the earlier Search/Scanner/Performance ZIP. Keep the previously installed files that are not listed in this ZIP (including the live-search service and performance-report template/assets); this ZIP does not remove them.

## Important scanner limitation

No application can guarantee that every barcode worldwide has public product details. Denmart first checks its own product catalogue and then tries external product-facts catalogues. If no catalogue recognises a code, the code is captured and the form tells you to enter the identity details manually. A proprietary scanner that does not type into the focused field may require its manufacturer's software or a device-specific integration.

## Suggested verification after deployment

1. In POS, scan a known product barcode and confirm it adds only that exact product. Scan an unknown code such as `6161106004522`; it should report not found rather than return unrelated milk/bread/products.
2. Open Products → Add Product, focus the barcode field, and scan a known catalogue barcode. Confirm the available identity fields fill, while selling price, cost, and stock stay for manual entry.
3. Test a small M-PESA sale. Keep the amount exact and wait for the Android gateway SMS. Confirm the payer name and amount appear and the POS sale completes without an extra click when the match is unique.
4. For bank testing, save the real receiving account details in Admin → PAY. Test only with an SMS that identifies the configured account. Unverified credits should not auto-complete the ticket.
5. Test an intentionally mismatched amount or ambiguous receipt; it should remain in administrator review instead of completing the sale.
6. Recheck stock balances and the old/new stock layer display after one completed sale.

The source files and templates were syntax-checked, and the archive was checked for integrity. A live Flask/database deployment test and physical scanner test were not possible in this environment, so carry out the checks above on the deployed system before relying on electronic auto-matching in production.
