"""add recall_states

Adds structured location data for recalls, parsed out of the free-text
`recalls.geographic_scope` field (see `normalization/geo_parse.py`):

- `recall_states`: one row per (recall, state) pair -- a recall can span
  multiple states, so this is the many-to-many join, not a column on
  `recalls`. No INSERT/UPDATE/DELETE policy for anon/authenticated,
  matching `recall_upcs` -- only the backend's service-role-equivalent
  connection (table ownership bypasses RLS) writes to it. SELECT is open
  to both `anon` and `authenticated` directly (not staged through an
  authenticated-only policy first, unlike the recall_upcs/recalls
  precedent in 2f082500b25a + 1a0a76ba3dbc) since recall browsing is
  already public by the time this migration was written.
- `recalls.is_nationwide`: true when `geographic_scope` reads as
  nationwide distribution (e.g. "Nationwide.", "distributed throughout
  the United States") rather than a specific state list. Kept as a flag
  instead of enumerating all 50 states into `recall_states`.
- `recalls.parse_status`: `'parsed'` or `'unparsed'`. `'unparsed'` means
  `geographic_scope`'s format couldn't be confidently read as either a
  state list or nationwide language -- deliberately not guessed, and
  queryable as its own bucket rather than silently indistinguishable
  from "no recall_states rows because none apply".

Revision ID: 66f2630fb756
Revises: 1a0a76ba3dbc
Create Date: 2026-09-23 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '66f2630fb756'
down_revision: Union[str, Sequence[str], None] = '1a0a76ba3dbc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""

    op.add_column(
        'recalls',
        sa.Column('is_nationwide', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    )
    op.add_column(
        'recalls',
        sa.Column('parse_status', sa.Text(), server_default='unparsed', nullable=False),
    )
    op.create_check_constraint(
        'ck_recalls_parse_status',
        'recalls',
        "parse_status IN ('parsed', 'unparsed')",
    )

    op.create_table(
        'recall_states',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('recall_id', sa.UUID(), nullable=False),
        sa.Column('state_code', sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(['recall_id'], ['recalls.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('recall_id', 'state_code', name='uq_recall_states_recall_id_state_code'),
    )
    op.create_index('idx_recall_states_state_code', 'recall_states', ['state_code'], unique=False)

    op.execute("ALTER TABLE public.recall_states ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY recall_states_select_public ON public.recall_states
        FOR SELECT
        TO authenticated, anon
        USING (true)
        """
    )


def downgrade() -> None:
    """Downgrade schema."""

    op.execute("DROP POLICY IF EXISTS recall_states_select_public ON public.recall_states")

    op.drop_index('idx_recall_states_state_code', table_name='recall_states')
    op.drop_table('recall_states')

    op.drop_constraint('ck_recalls_parse_status', 'recalls', type_='check')
    op.drop_column('recalls', 'parse_status')
    op.drop_column('recalls', 'is_nationwide')
