"""Optionally add the prepared Denmart campaign as an editable draft.

This script NEVER publishes, overwrites, or replaces the currently live campaign.
Existing saved campaigns are retained. It is safe to re-run.

Run after deploying if you want the prepared local-shopping creative in the draft list:
    AUTO_INIT_DB=0 python scripts/apply_denmart_advert_campaign.py
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from app import create_app
from extensions import db
from models import Business, SystemSetting, now
from routes.advertising import CAMPAIGNS_KEY, default_campaign


def main() -> None:
    app = create_app()
    with app.app_context():
        business = Business.query.order_by(Business.created_at).first()
        if business is None:
            raise SystemExit("No Denmart business record was found; no data was changed.")

        row = SystemSetting.query.filter_by(business_id=business.id, key=CAMPAIGNS_KEY).first()
        if row and row.value:
            try:
                campaigns = json.loads(row.value)
            except (TypeError, ValueError) as exc:
                raise SystemExit("Saved campaigns are not valid JSON; no data was changed.") from exc
            if not isinstance(campaigns, list):
                raise SystemExit("Saved campaigns are not a list; no data was changed.")
        else:
            campaigns = []

        # Add as a distinct draft. Never replace a campaign with the same ID and never
        # modify advert_published_campaign. Publishing remains an explicit user action.
        draft = default_campaign()
        draft["id"] = "denmart-local-shopping-draft-20261107"
        draft["name"] = "Denmart Local Shopping · Editable Draft"
        draft["updated_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        if any(isinstance(item, dict) and str(item.get("id")) == draft["id"] for item in campaigns):
            print("The prepared editable draft already exists; nothing was changed.")
            return

        campaigns.append(draft)
        value = json.dumps(campaigns, ensure_ascii=False, separators=(",", ":"))
        if row is None:
            db.session.add(SystemSetting(business_id=business.id, key=CAMPAIGNS_KEY, value=value))
        else:
            row.value = value
            row.updated_at = now()
        db.session.commit()
        print("Added the prepared Denmart creative as an editable draft.")
        print("The live advertisement was not changed or published.")


if __name__ == "__main__":
    main()
