"""Add institution-scoped proposed reviewer directory.

This migration is prepared for a future approved pilot deployment. It is not
applied by application startup.
"""
from __future__ import annotations

from alembic import op

revision = "20261004_002"
down_revision = "20260930_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    connection.exec_driver_sql("""
            CREATE TABLE IF NOT EXISTS reviewers (
                id TEXT PRIMARY KEY, institution TEXT NOT NULL, name TEXT NOT NULL,
                affiliation TEXT NOT NULL, expertise TEXT NOT NULL, source_url TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'proposed', added_by TEXT NOT NULL,
                created_at DOUBLE PRECISION NOT NULL
            )
        """)
    connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS reviewers_institution_idx ON reviewers(institution)")


def downgrade() -> None:
    raise RuntimeError("Reviewer directory migration is intentionally irreversible")
