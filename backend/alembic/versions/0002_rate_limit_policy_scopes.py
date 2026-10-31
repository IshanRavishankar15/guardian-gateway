"""Enforce valid and unambiguous rate-limit policy scopes.

Revision ID: 0002_rate_limit_policy_scopes
Revises: 0001_initial_schema
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_rate_limit_policy_scopes"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_rate_limit_policies_capacity_positive", "rate_limit_policies", "capacity > 0"
    )
    op.create_check_constraint(
        "ck_rate_limit_policies_refill_positive", "rate_limit_policies", "refill_rate > 0"
    )
    op.create_index(
        "uq_rate_limit_policy_global_scope",
        "rate_limit_policies",
        [sa.text("(1)")],
        unique=True,
        postgresql_where=sa.text("client_id IS NULL AND route_id IS NULL"),
    )
    op.create_index(
        "uq_rate_limit_policy_client_scope",
        "rate_limit_policies",
        ["client_id"],
        unique=True,
        postgresql_where=sa.text("client_id IS NOT NULL AND route_id IS NULL"),
    )
    op.create_index(
        "uq_rate_limit_policy_route_scope",
        "rate_limit_policies",
        ["route_id"],
        unique=True,
        postgresql_where=sa.text("client_id IS NULL AND route_id IS NOT NULL"),
    )
    op.create_index(
        "uq_rate_limit_policy_client_route_scope",
        "rate_limit_policies",
        ["client_id", "route_id"],
        unique=True,
        postgresql_where=sa.text("client_id IS NOT NULL AND route_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_rate_limit_policy_client_route_scope", table_name="rate_limit_policies")
    op.drop_index("uq_rate_limit_policy_route_scope", table_name="rate_limit_policies")
    op.drop_index("uq_rate_limit_policy_client_scope", table_name="rate_limit_policies")
    op.drop_index("uq_rate_limit_policy_global_scope", table_name="rate_limit_policies")
    op.drop_constraint("ck_rate_limit_policies_refill_positive", "rate_limit_policies", type_="check")
    op.drop_constraint("ck_rate_limit_policies_capacity_positive", "rate_limit_policies", type_="check")
