"""add row level security policies

Enables RLS on every table in the public schema and adds policies for the
Supabase-facing (anon/authenticated) roles. The Python backend connects
with a role that owns these tables, so table ownership bypasses RLS for it
regardless of policy content — these policies only constrain access through
Supabase's PostgREST/client-SDK path.

Household-scoped tables (households, users, receipts, receipt_items,
match_candidates, notifications) are restricted to the caller's own
household via the `public.current_household_id()` helper, which looks up
`household_id` from the `users` row matching `auth.uid()`.

`households` intentionally gets no INSERT/DELETE policy: at signup time a
new user has no `users` row yet, so there is no household to check an
insert against. Household creation for onboarding isn't wired up yet and
needs its own decision (e.g. a SECURITY DEFINER function or a backend-side
step) — tracked in STATUS.md, not solved here.

`users` also gets no DELETE policy — profile deletion should follow from
deleting the `auth.users` row (which cascades via the existing FK), not
from a direct client-side delete of the profile row alone.

Global reference tables (recalls, recall_upcs, recall_history) get
SELECT-only for authenticated users; only the backend ingestion pipeline
(service-role-equivalent connection, bypassing RLS) writes to them.

Backend-only tables (raw_ingestions, ingestion_runs, jobs) and
`alembic_version` get RLS enabled with no policies at all, so anon/
authenticated have zero access and only a service-role/table-owner
connection can touch them.

Revision ID: 2f082500b25a
Revises: cc71d2485e36
Create Date: 2026-09-13 15:08:00.420253

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2f082500b25a'
down_revision: Union[str, Sequence[str], None] = 'cc71d2485e36'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


NO_POLICY_TABLES = ("raw_ingestions", "ingestion_runs", "jobs", "alembic_version")

REFERENCE_TABLES = ("recalls", "recall_upcs", "recall_history")


def upgrade() -> None:
    """Upgrade schema."""

    # Helper: the caller's own household_id, derived from their `users` row.
    # SECURITY DEFINER + a pinned search_path so it works consistently
    # regardless of the calling role's own table privileges/search_path.
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

    # --- Enable RLS everywhere in the public schema ---------------------
    all_tables = (
        "households",
        "users",
        "receipts",
        "receipt_items",
        "match_candidates",
        "notifications",
        *REFERENCE_TABLES,
        *NO_POLICY_TABLES,
    )
    for table in all_tables:
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")

    # --- households: read/update own household only, no insert/delete ---
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

    # --- users: see/update household members, insert only your own row --
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
        CREATE POLICY users_insert_self ON public.users
        FOR INSERT
        TO authenticated
        WITH CHECK (id = auth.uid())
        """
    )

    # --- receipts: full read/write within own household ------------------
    op.execute(
        """
        CREATE POLICY receipts_all_own_household ON public.receipts
        FOR ALL
        TO authenticated
        USING (household_id = public.current_household_id())
        WITH CHECK (household_id = public.current_household_id())
        """
    )

    # --- receipt_items: household derived via parent receipt -------------
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

    # --- match_candidates: household derived via receipt_item -> receipt -
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

    # --- notifications: household derived via the owning user ------------
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

    # --- global reference tables: read-only for any authenticated user ---
    for table in REFERENCE_TABLES:
        op.execute(
            f"""
            CREATE POLICY {table}_select_authenticated ON public.{table}
            FOR SELECT
            TO authenticated
            USING (true)
            """
        )

    # --- backend-only tables + alembic_version: RLS enabled, no policies -
    # (nothing further to do here: NO_POLICY_TABLES already had RLS
    # enabled above, and no policy means anon/authenticated get no rows)


def downgrade() -> None:
    """Downgrade schema."""

    for table in REFERENCE_TABLES:
        op.execute(f"DROP POLICY IF EXISTS {table}_select_authenticated ON public.{table}")

    op.execute("DROP POLICY IF EXISTS notifications_all_own_household ON public.notifications")
    op.execute("DROP POLICY IF EXISTS match_candidates_all_own_household ON public.match_candidates")
    op.execute("DROP POLICY IF EXISTS receipt_items_all_own_household ON public.receipt_items")
    op.execute("DROP POLICY IF EXISTS receipts_all_own_household ON public.receipts")
    op.execute("DROP POLICY IF EXISTS users_insert_self ON public.users")
    op.execute("DROP POLICY IF EXISTS users_update_own_household ON public.users")
    op.execute("DROP POLICY IF EXISTS users_select_own_household ON public.users")
    op.execute("DROP POLICY IF EXISTS households_update_own ON public.households")
    op.execute("DROP POLICY IF EXISTS households_select_own ON public.households")

    all_tables = (
        "households",
        "users",
        "receipts",
        "receipt_items",
        "match_candidates",
        "notifications",
        *REFERENCE_TABLES,
        *NO_POLICY_TABLES,
    )
    for table in all_tables:
        op.execute(f"ALTER TABLE public.{table} DISABLE ROW LEVEL SECURITY")

    op.execute("DROP FUNCTION IF EXISTS public.current_household_id()")
