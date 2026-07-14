import json

from sqlalchemy import select

from app.infrastructure.persistence.database import SessionLocal
from app.infrastructure.persistence.models import StrategyRecord
from app.strategies.catalog import CATALOG


def seed() -> int:
    created = 0
    with SessionLocal() as session:
        existing = set(session.scalars(select(StrategyRecord.version)).all())
        for spec in CATALOG:
            if spec.version in existing:
                continue
            session.add(StrategyRecord(
                name=spec.name,
                version=spec.version,
                status="RESEARCH",
                config_json=json.dumps(spec.model_dump(mode="json")),
                promotion_notes="Research candidate; not authorized for execution",
            ))
            created += 1
        session.commit()
    return created


if __name__ == "__main__":
    print(f"created={seed()} total={len(CATALOG)}")
