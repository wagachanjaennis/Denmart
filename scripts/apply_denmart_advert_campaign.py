"""Apply the prepared Denmart local-shopping advert to an existing live database.

Run once after deploying the matching source and static photo assets:
    AUTO_INIT_DB=0 python scripts/apply_denmart_advert_campaign.py

This updates only advert campaign SystemSetting rows and preserves other campaigns,
sales, products, stock, customers, users and other database records.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from app import create_app
from extensions import db
from models import Business, SystemSetting, now
from routes.advertising import CAMPAIGNS_KEY, PUBLISHED_KEY, default_campaign


def main() -> None:
    app = create_app()
    with app.app_context():
        business = Business.query.order_by(Business.created_at).first()
        if business is None:
            raise SystemExit("No Denmart business record was found; the campaign was not changed.")

        campaign = default_campaign()
        campaign["updated_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

        campaigns_row = SystemSetting.query.filter_by(
            business_id=business.id, key=CAMPAIGNS_KEY
        ).first()
        if campaigns_row and campaigns_row.value:
            try:
                campaigns = json.loads(campaigns_row.value)
            except (TypeError, ValueError) as exc:
                raise SystemExit("Saved campaign list is not valid JSON; no data was changed.") from exc
            if not isinstance(campaigns, list):
                raise SystemExit("Saved campaign list is not a list; no data was changed.")
        else:
            campaigns = []

        # Replace this campaign ID while keeping every other saved draft intact.
        replaced = False
        updated_campaigns = []
        for item in campaigns:
            if isinstance(item, dict) and str(item.get("id")) == campaign["id"]:
                if not replaced:
                    updated_campaigns.append(campaign)
                    replaced = True
            else:
                updated_campaigns.append(item)
        if not replaced:
            updated_campaigns.append(campaign)

        if campaigns_row is None:
            campaigns_row = SystemSetting(
                business_id=business.id, key=CAMPAIGNS_KEY,
                value=json.dumps(updated_campaigns, ensure_ascii=False, separators=(",", ":")),
            )
            db.session.add(campaigns_row)
        else:
            campaigns_row.value = json.dumps(updated_campaigns, ensure_ascii=False, separators=(",", ":"))
            campaigns_row.updated_at = now()

        published_row = SystemSetting.query.filter_by(
            business_id=business.id, key=PUBLISHED_KEY
        ).first()
        published_value = json.dumps(campaign, ensure_ascii=False, separators=(",", ":"))
        if published_row is None:
            db.session.add(SystemSetting(business_id=business.id, key=PUBLISHED_KEY, value=published_value))
        else:
            published_row.value = published_value
            published_row.updated_at = now()

        db.session.commit()
        print(f"Published campaign: {campaign['name']}")
        print(f"Saved campaign drafts preserved: {len(updated_campaigns) - 1}")
        print("Only advert campaign settings were updated.")


if __name__ == "__main__":
    main()
