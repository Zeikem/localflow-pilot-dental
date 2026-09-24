from __future__ import annotations

import hashlib
from pathlib import Path

from sqlalchemy import text

from app.db import Base, DATABASE_URL, engine


MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"
LOCK_NAME = "localflow-schema-migrations"
LOCK_ID = int.from_bytes(
    hashlib.sha256(LOCK_NAME.encode("utf-8")).digest()[:8],
    byteorder="big",
    signed=True,
)


def _ensure_tracking_table(conn) -> None:
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                filename VARCHAR(255) PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
    )


def _applied(conn) -> set[str]:
    return set(
        conn.execute(text("SELECT filename FROM schema_migrations")).scalars().all()
    )


def main() -> None:
    # Ensure model metadata is registered before create_all.
    from app import models  # noqa: F401

    # SQLite is used only for local/tests; create_all is enough there.
    if DATABASE_URL.startswith("sqlite"):
        Base.metadata.create_all(bind=engine)
        print("SQLite schema is ready.")
        return

    with engine.begin() as conn:
        # Serialize schema work across API and workers starting simultaneously.
        conn.execute(text("SELECT pg_advisory_xact_lock(:lock_id)"), {"lock_id": LOCK_ID})

        # Bootstrap a clean DB at current schema. On an older DB, create_all only creates
        # missing tables; versioned SQL below handles alterations.
        Base.metadata.create_all(bind=conn)

        _ensure_tracking_table(conn)
        applied = _applied(conn)

        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if path.name in applied:
                continue
            sql = path.read_text(encoding="utf-8").strip()
            if sql:
                conn.exec_driver_sql(sql)
            conn.execute(
                text("INSERT INTO schema_migrations(filename) VALUES (:filename)"),
                {"filename": path.name},
            )
            print(f"Applied migration: {path.name}")

    print("Database schema is ready.")


if __name__ == "__main__":
    main()
