"""add pending video status

Revision ID: 20260812_0003
Revises: 20260811_0002
Create Date: 2026-08-12

Direct-to-storage uploads need a state for "row reserved, bytes not confirmed
yet": the browser PUTs straight to R2, so the API cannot know the file arrived
until it asks storage. `pending` rows become `processing` once the object is
verified, or are swept away if the upload never lands.

Only the CHECK constraint changes — the column already holds free text.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260812_0003"
down_revision: str | None = "20260811_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE videos DROP CONSTRAINT ck_videos_status")
    op.execute("""
        ALTER TABLE videos ADD CONSTRAINT ck_videos_status
            CHECK (status IN ('pending', 'processing', 'ready', 'failed'))
    """)


def downgrade() -> None:
    # Nothing may be left in a state the old constraint forbids. These rows
    # never had their bytes confirmed, so dropping them loses nothing.
    op.execute("DELETE FROM videos WHERE status = 'pending'")
    op.execute("ALTER TABLE videos DROP CONSTRAINT ck_videos_status")
    op.execute("""
        ALTER TABLE videos ADD CONSTRAINT ck_videos_status
            CHECK (status IN ('processing', 'ready', 'failed'))
    """)
