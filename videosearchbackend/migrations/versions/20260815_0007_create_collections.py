"""create collections

Revision ID: 20260815_0007
Revises: 20260814_0006
Create Date: 2026-08-15

Collections schema:

* ``collections`` — one row per named group of videos, owned by a user. The
  unique index is on ``(owner_id, lower(name))`` rather than ``(owner_id,
  name)``: "Lectures" and "lectures" would be indistinguishable in the
  sidebar, so the second is a mistake worth rejecting.
* ``collection_videos`` — the membership join, keyed on
  ``(collection_id, video_id)`` so re-adding a video is a no-op rather than a
  duplicate row. Both foreign keys cascade, which drops memberships when
  either side goes away — deleting a collection never deletes its videos.

Written as literal SQL (see 20260811_0001) — one statement per op.execute,
since asyncpg rejects multiple commands in a single prepared string.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260815_0007"
down_revision: str | None = "20260814_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE collections (
            id         UUID         NOT NULL DEFAULT gen_random_uuid(),
            owner_id   UUID         NOT NULL,
            name       VARCHAR(120) NOT NULL,
            created_at TIMESTAMPTZ  NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ  NOT NULL DEFAULT now(),
            CONSTRAINT pk_collections PRIMARY KEY (id),
            CONSTRAINT fk_collections_owner_id_users
                FOREIGN KEY (owner_id) REFERENCES users (id) ON DELETE CASCADE
        )
    """)

    op.execute("CREATE INDEX ix_collections_owner_id ON collections (owner_id)")
    # Case-insensitive uniqueness per owner — see the module docstring.
    op.execute("""
        CREATE UNIQUE INDEX uq_collections_owner_id_lower_name
            ON collections (owner_id, lower(name))
    """)

    op.execute("""
        CREATE TABLE collection_videos (
            collection_id UUID        NOT NULL,
            video_id      UUID        NOT NULL,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT pk_collection_videos PRIMARY KEY (collection_id, video_id),
            CONSTRAINT fk_collection_videos_collection_id_collections
                FOREIGN KEY (collection_id) REFERENCES collections (id) ON DELETE CASCADE,
            CONSTRAINT fk_collection_videos_video_id_videos
                FOREIGN KEY (video_id) REFERENCES videos (id) ON DELETE CASCADE
        )
    """)

    # The primary key already serves collection → videos; this covers the
    # reverse lookup the library grid makes once per page load.
    op.execute("CREATE INDEX ix_collection_videos_video_id ON collection_videos (video_id)")


def downgrade() -> None:
    op.execute("DROP TABLE collection_videos")
    op.execute("DROP TABLE collections")
