"""Controlled-pilot clinical schema baseline.

The existing schema builder remains the single baseline definition during the
pilot. Production invokes it only through this migration; application startup
performs verification and never applies DDL.
"""
from __future__ import annotations

from clinical import initialize_clinical_store

revision = "20260930_001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    initialize_clinical_store()


def downgrade() -> None:
    raise RuntimeError("The clinical baseline migration is intentionally irreversible")
