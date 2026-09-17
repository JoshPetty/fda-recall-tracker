"""remove households, move to per-user data ownership

Removes the household concept entirely and replaces it with direct
per-user ownership of receipts:

- `receipts.user_id` (FK -> public.users.id, matching the existing
  `uploaded_by_user_id` pattern -- `users.id` is the one column that
  references `auth.users.id` directly, per `cc71d2485e36`) replaces
  `receipts.household_id`. Existing receipts are backfilled from the
  user in their current household. There's currently exactly one
  household with one user, so this is a straightforward 1:1 mapping,
  but the backfill is written generically (picks the earliest-created
  user in the household) in case that's changed by the time this runs.
- `users.household_id` and the `households` table are dropped.
- `public.current_household_id()` is dropped -- no longer needed.
- Every RLS policy that used `current_household_id()` (receipts,
  receipt_items, match_candidates, notifications) is rewritten to
  `auth.uid()`-based ownership, either directly or via the join chain
  up from `receipts`. `notifications.user_id` already pointed straight
  at `users.id`, so its policy no longer needs a join at all.
- `users` SELECT/UPDATE become scoped to your own row (`id =
  auth.uid()`) instead of your household's rows. The existing
  `users_insert_self` policy (`id = auth.uid()`) is untouched -- it was
  already per-user, not household-scoped.

Downgrade note: reversing this is lossy. The original household
groupings aren't reconstructable from user_id alone, so the downgrade
gives every user their own new household (not the original grouping)
and backfills receipts.household_id from there. Fine for schema
reversibility, not for restoring the exact prior data shape.

Revision ID: 0b8ac26f895a
Revises: 66f2630fb756
Create Date: 2026-09-16 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0b8ac26f895a'
down_revision: Union[str, Sequence[str], None] = '66f2630fb756'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""

    # --- receipts.user_id: add, backfill from the current household's ----
    # --- user, then enforce NOT NULL --------------------------------------
    op.add_column('receipts', sa.Column('user_id', sa.UUID(), nullable=True))

    op.execute(
        """
        UPDATE receipts
        SET user_id = (
            SELECT u.id FROM users u
            WHERE u.household_id = receipts.household_id
            ORDER BY u.created_at, u.id
            LIMIT 1
        )
        WHERE user_id IS NULL
        """
    )

    op.alter_column('receipts', 'user_id', nullable=False)
    op.create_foreign_key(
        'fk_receipts_user_id_users', 'receipts', 'users', ['user_id'], ['id'],
    )

    # --- drop RLS policies that depend on current_household_id() ---------
    op.execute("DROP POLICY IF EXISTS notifications_all_own_household ON public.notifications")
    op.execute("DROP POLICY IF EXISTS match_candidates_all_own_household ON public.match_candidates")
    op.execute("DROP POLICY IF EXISTS receipt_items_all_own_household ON public.receipt_items")
    op.execute("DROP POLICY IF EXISTS receipts_all_own_household ON public.receipts")
    op.execute("DROP POLICY IF EXISTS users_update_own_household ON public.users")
    op.execute("DROP POLICY IF EXISTS users_select_own_household ON public.users")
    op.execute("DROP POLICY IF EXISTS households_update_own ON public.households")
    op.execute("DROP POLICY IF EXISTS households_select_own ON public.households")

    # --- drop household columns/table, then the helper function ----------
    op.drop_column('receipts', 'household_id')
    op.drop_column('users', 'household_id')
    op.drop_table('households')
    op.execute("DROP FUNCTION IF EXISTS public.current_household_id()")

    # --- recreate policies scoped to auth.uid() directly ------------------
    op.execute(
        """
        CREATE POLICY users_select_own ON public.users
        FOR SELECT
        TO authenticated
        USING (id = auth.uid())
        """
    )
    op.execute(
        """
        CREATE POLICY users_update_own ON public.users
        FOR UPDATE
        TO authenticated
        USING (id = auth.uid())
        WITH CHECK (id = auth.uid())
        """
    )
    # users_insert_self is unchanged (already `id = auth.uid()`, not
    # household-scoped) -- not touched here.

    op.execute(
        """
        CREATE POLICY receipts_all_own ON public.receipts
        FOR ALL
        TO authenticated
        USING (user_id = auth.uid())
        WITH CHECK (user_id = auth.uid())
        """
    )

    op.execute(
        """
        CREATE POLICY receipt_items_all_own ON public.receipt_items
        FOR ALL
        TO authenticated
        USING (
            EXISTS (
                SELECT 1 FROM public.receipts r
                WHERE r.id = receipt_items.receipt_id
                AND r.user_id = auth.uid()
            )
        )
        WITH CHECK (
            EXISTS (
                SELECT 1 FROM public.receipts r
                WHERE r.id = receipt_items.receipt_id
                AND r.user_id = auth.uid()
            )
        )
        """
    )

    op.execute(
        """
        CREATE POLICY match_candidates_all_own ON public.match_candidates
        FOR ALL
        TO authenticated
        USING (
            EXISTS (
                SELECT 1 FROM public.receipt_items ri
                JOIN public.receipts r ON r.id = ri.receipt_id
                WHERE ri.id = match_candidates.receipt_item_id
                AND r.user_id = auth.uid()
            )
        )
        WITH CHECK (
            EXISTS (
                SELECT 1 FROM public.receipt_items ri
                JOIN public.receipts r ON r.id = ri.receipt_id
                WHERE ri.id = match_candidates.receipt_item_id
                AND r.user_id = auth.uid()
            )
        )
        """
    )

    # notifications.user_id already references users.id directly, so
    # ownership is now a direct comparison -- no join needed anymore.
    op.execute(
        """
        CREATE POLICY notifications_all_own ON public.notifications
        FOR ALL
        TO authenticated
        USING (user_id = auth.uid())
        WITH CHECK (user_id = auth.uid())
        """
    )


def downgrade() -> None:
    """Downgrade schema.

    Lossy: the original household groupings can't be reconstructed from
    user_id alone, so each user gets their own new household rather than
    being restored to whatever household they previously shared.
    """

    # --- drop the per-user policies ---------------------------------------
    op.execute("DROP POLICY IF EXISTS notifications_all_own ON public.notifications")
    op.execute("DROP POLICY IF EXISTS match_candidates_all_own ON public.match_candidates")
    op.execute("DROP POLICY IF EXISTS receipt_items_all_own ON public.receipt_items")
    op.execute("DROP POLICY IF EXISTS receipts_all_own ON public.receipts")
    op.execute("DROP POLICY IF EXISTS users_update_own ON public.users")
    op.execute("DROP POLICY IF EXISTS users_select_own ON public.users")

    # --- recreate households, household_id columns, current_household_id -
    op.create_table(
        'households',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.execute("ALTER TABLE public.households ENABLE ROW LEVEL SECURITY")

    op.add_column('users', sa.Column('household_id', sa.UUID(), nullable=True))

    # One new household per user -- not the original grouping, see docstring.
    op.execute(
        """
        INSERT INTO households (id, name)
        SELECT gen_random_uuid(), 'Recovered household for ' || email
        FROM users
        """
    )
    op.execute(
        """
        UPDATE users
        SET household_id = (
            SELECT h.id FROM households h
            WHERE h.name = 'Recovered household for ' || users.email
        )
        """
    )
    op.alter_column('users', 'household_id', nullable=False)
    op.create_foreign_key(
        'users_household_id_fkey', 'users', 'households', ['household_id'], ['id'],
    )

    op.add_column('receipts', sa.Column('household_id', sa.UUID(), nullable=True))
    op.execute(
        """
        UPDATE receipts
        SET household_id = (
            SELECT u.household_id FROM users u WHERE u.id = receipts.user_id
        )
        """
    )
    op.alter_column('receipts', 'household_id', nullable=False)
    op.create_foreign_key(
        'receipts_household_id_fkey', 'receipts', 'households', ['household_id'], ['id'],
    )

    op.drop_constraint('fk_receipts_user_id_users', 'receipts', type_='foreignkey')
    op.drop_column('receipts', 'user_id')

    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.current_household_id()
        RETURNS uuid
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
            SELECT household_id
            FROM public.users
            WHERE id = auth.uid()
        $$;
        """
    )

    op.execute(
        """
        CREATE POLICY households_select_own ON public.households
        FOR SELECT
        TO authenticated
        USING (id = public.current_household_id())
        """
    )
    op.execute(
        """
        CREATE POLICY households_update_own ON public.households
        FOR UPDATE
        TO authenticated
        USING (id = public.current_household_id())
        WITH CHECK (id = public.current_household_id())
        """
    )
    op.execute(
        """
        CREATE POLICY users_select_own_household ON public.users
        FOR SELECT
        TO authenticated
        USING (household_id = public.current_household_id())
        """
    )
    op.execute(
        """
        CREATE POLICY users_update_own_household ON public.users
        FOR UPDATE
        TO authenticated
        USING (household_id = public.current_household_id())
        WITH CHECK (household_id = public.current_household_id())
        """
    )
    op.execute(
        """
        CREATE POLICY receipts_all_own_household ON public.receipts
        FOR ALL
        TO authenticated
        USING (household_id = public.current_household_id())
        WITH CHECK (household_id = public.current_household_id())
        """
    )
    op.execute(
        """
        CREATE POLICY receipt_items_all_own_household ON public.receipt_items
        FOR ALL
        TO authenticated
        USING (
            EXISTS (
                SELECT 1 FROM public.receipts r
                WHERE r.id = receipt_items.receipt_id
                AND r.household_id = public.current_household_id()
            )
        )
        WITH CHECK (
            EXISTS (
                SELECT 1 FROM public.receipts r
                WHERE r.id = receipt_items.receipt_id
                AND r.household_id = public.current_household_id()
            )
        )
        """
    )
    op.execute(
        """
        CREATE POLICY match_candidates_all_own_household ON public.match_candidates
        FOR ALL
        TO authenticated
        USING (
            EXISTS (
                SELECT 1 FROM public.receipt_items ri
                JOIN public.receipts r ON r.id = ri.receipt_id
                WHERE ri.id = match_candidates.receipt_item_id
                AND r.household_id = public.current_household_id()
            )
        )
        WITH CHECK (
            EXISTS (
                SELECT 1 FROM public.receipt_items ri
                JOIN public.receipts r ON r.id = ri.receipt_id
                WHERE ri.id = match_candidates.receipt_item_id
                AND r.household_id = public.current_household_id()
            )
        )
        """
    )
    op.execute(
        """
        CREATE POLICY notifications_all_own_household ON public.notifications
        FOR ALL
        TO authenticated
        USING (
            EXISTS (
                SELECT 1 FROM public.users u
                WHERE u.id = notifications.user_id
                AND u.household_id = public.current_household_id()
            )
        )
        WITH CHECK (
            EXISTS (
                SELECT 1 FROM public.users u
                WHERE u.id = notifications.user_id
                AND u.household_id = public.current_household_id()
            )
        )
        """
    )
