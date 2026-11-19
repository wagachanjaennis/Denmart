DENMART GITHUB CODE OVERLAY — 19 NOVEMBER 2026

This is a source-code overlay for the existing Denmart repository, not a full project. Extract it at the repository root and preserve the folder paths. It replaces the 13 listed source files.

Included:
- config.py, seed.py
- routes/admin.py, routes/advertising.py
- templates/admin/storefront_order.html
- templates/shop/_card.html
- templates/advertising/studio.html, screen.html
- static/css/admin-storefront-order.css
- static/js/admin-storefront-order.js, advert-player.js, advert-design-editor.js, advert-studio.js

Not included: app.py, requirements files, the rest of the routes/templates/static assets, any database, credentials, or new product photos. These remain in your existing repository. The 53 photo files in the earlier ZIP were already present byte-for-byte in your uploaded source archive, so they are intentionally omitted here.

Validation performed: Python syntax compilation of the four changed Python files, Node syntax checks of the four changed JavaScript files, Jinja parsing of the four changed templates, and archive CRC validation. A full Flask runtime/integration test was NOT run in this environment because Flask is not installed. Deploy to a staging service or take a backup before applying to production.

Database reminder: do not put Denmart_Cleaned_Database_2026-11-19.sqlite or its JSON export in a public GitHub repository. Store them privately and restore only after confirming Render's configured database type and taking a fresh live backup.
