"""create users and refresh tokens

Revision ID: 20260811_0001
Revises:
Create Date: 2026-08-11

Initial auth schema:

* ``users`` — one row per account. Email is stored lower-cased (normalised in
  the service layer) and the unique index is what actually prevents duplicate
  signups under concurrency.
* ``refresh_tokens`` — one row per issued refresh token, holding only the
  SHA-256 digest. Rotation marks the old row ``revoked_at`` instead of
  deleting it, which is what makes token replay detectable.

Written as literal SQL rather than ``op.create_table()`` builder calls: the
migration is the thing that runs against production, so it should be readable
as exactly what Postgres will execute.

One statement per ``op.execute`` — asyncpg prepares each statement, so it
rejects several commands sent in a single string.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260811_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Provides gen_random_uuid() for the users.id default.
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    op.execute("""
        CREATE TABLE users (
            id            UUID         NOT NULL DEFAULT gen_random_uuid(),
            name          VARCHAR(120) NOT NULL,
            email         VARCHAR(320) NOT NULL,
            password_hash VARCHAR(255) NOT NULL,
            is_active     BOOLEAN      NOT NULL DEFAULT true,
            created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
            updated_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
            CONSTRAINT pk_users PRIMARY KEY (id)
        )
    """)

    # A unique index, not a separate UNIQUE constraint: the model declares
    # `unique=True, index=True`, and adding both would duplicate the index.
    op.execute("CREATE UNIQUE INDEX ix_users_email ON users (email)")

    op.execute("""
        CREATE TABLE refresh_tokens (
            id         UUID        NOT NULL,
            user_id    UUID        NOT NULL,
            token_hash VARCHAR(64) NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            revoked_at TIMESTAMPTZ,
            user_agent VARCHAR(255),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT pk_refresh_tokens PRIMARY KEY (id),
            CONSTRAINT fk_refresh_tokens_user_id_users
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
        )
    """)

    # Unique: the digest is how a presented token is looked up.
    op.execute("CREATE UNIQUE INDEX ix_refresh_tokens_token_hash ON refresh_tokens (token_hash)")
    # Non-unique: supports "revoke every session for this user".
    op.execute("CREATE INDEX ix_refresh_tokens_user_id ON refresh_tokens (user_id)")


def downgrade() -> None:
    # Dropping the table takes its indexes and the foreign key with it.
    op.execute("DROP TABLE refresh_tokens")
    op.execute("DROP TABLE users")
