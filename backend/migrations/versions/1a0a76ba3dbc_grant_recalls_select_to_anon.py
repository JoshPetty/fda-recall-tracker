"""grant recalls select to anon

Extends the existing read-only SELECT policy on the global reference
tables (recalls, recall_upcs, recall_history) to the `anon` role,
alongside `authenticated`. Same posture as before: no INSERT/UPDATE/
DELETE for either role, only the backend's service-role-equivalent
connection (table ownership bypasses RLS) can write to them.

This is what makes recall browsing/search work for signed-out users in
the Expo app (see app/recalls/ — moved out of the auth-gated (app)
route group in the same change that introduced this migration).

Revision ID: 1a0a76ba3dbc
Revises: 2f082500b25a
Create Date: 2026-09-16 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1a0a76ba3dbc'
down_revision: Union[str, Sequence[str], None] = '2f082500b25a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


REFERENCE_TABLES = ("recalls", "recall_upcs", "recall_history")


def upgrade() -> None:
    """Upgrade schema."""

    for table in REFERENCE_TABLES:
        op.execute(
            f"ALTER POLICY {table}_select_authenticated ON public.{table} "
            f"TO authenticated, anon"
        )


def downgrade() -> None:
    """Downgrade schema."""

    for table in REFERENCE_TABLES:
        op.execute(
            f"ALTER POLICY {table}_select_authenticated ON public.{table} "
            f"TO authenticated"
        )
