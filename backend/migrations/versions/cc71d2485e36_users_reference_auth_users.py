"""users table becomes a profile table referencing auth.users

Turns `users` from a standalone identity table into a profile table keyed
off Supabase Auth: `users.id` no longer gets a server-generated default
(the id is supplied by the app as the authenticated `auth.uid()` on
sign-up) and gains a foreign key to `auth.users.id`, cascading on delete
so a deleted Supabase Auth user takes their profile row with them.

Revision ID: cc71d2485e36
Revises: d2e72bef0500
Create Date: 2026-09-12 20:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'cc71d2485e36'
down_revision: Union[str, Sequence[str], None] = 'd2e72bef0500'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Any existing rows in `users` were seeded with server-generated ids that
    # do not correspond to real `auth.users` rows, so they can't satisfy the
    # new foreign key. This project has no real users yet (auth was never
    # wired up), so it's safe to clear the table; if that stops being true,
    # this truncate needs to be replaced with a real backfill first.
    op.execute("TRUNCATE TABLE users CASCADE")

    op.alter_column('users', 'id', server_default=None)
    op.create_foreign_key(
        'fk_users_id_auth_users',
        'users',
        'users',
        ['id'],
        ['id'],
        referent_schema='auth',
        ondelete='CASCADE',
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('fk_users_id_auth_users', 'users', type_='foreignkey')
    op.alter_column('users', 'id', server_default=sa.text('gen_random_uuid()'))
