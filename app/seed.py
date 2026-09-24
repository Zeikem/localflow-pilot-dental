import json
from pathlib import Path

from sqlalchemy import select

from app.db import SessionLocal, init_db
from app.models import Tenant


CONFIG_DIR = Path(__file__).resolve().parent.parent / "tenant_configs"


def main():
    init_db()

    with SessionLocal() as db:
        for path in sorted(CONFIG_DIR.glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            existing = db.scalar(select(Tenant).where(Tenant.slug == data["slug"]))

            if existing:
                existing.name = data["name"]
                existing.niche = data["niche"]
                existing.timezone = data["timezone"]
                existing.whatsapp_phone_number_id = data["whatsapp_phone_number_id"]
                existing.whatsapp_token_env = data["whatsapp_token_env"]
                existing.workflow_spec = data["workflow_spec"]
            else:
                db.add(Tenant(**data))

        db.commit()

    print("Tenants de ejemplo cargados.")


if __name__ == "__main__":
    main()
