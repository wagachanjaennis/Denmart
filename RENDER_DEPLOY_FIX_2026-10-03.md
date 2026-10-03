# Denmart Render deployment fix — 03 Oct 2026

This release is a single consistent web source tree.

## Critical fix
`routes/shop.py`, `routes/api.py`, `routes/admin.py`, and `seed.py` use the
`PaymentDestination` model. `models.py` in this release defines that model as
`payment_destinations`.

Do not combine files from an older Denmart release with this release. In
particular, do not deploy the newer routes with the older `models.py`.

## Database
`bootstrap.py` calls `db.create_all()` during first boot, so a missing
`payment_destinations` table will be created on a new/existing database when
this release starts. Existing data in unrelated tables is not replaced.

## Render
The web application entrypoint is:

    gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --threads 4 --timeout 120

The service may still show Python 3.14.x if the Render service settings override
the repository blueprint. That is independent of the `PaymentDestination`
ImportError that this release fixes.
