"""signals unique per candle

Revision ID: ce38830a9933
Revises: e139d6c9018a
Create Date: 2026-11-11 14:05:05.826280

SQLite cannot ALTER-add a table constraint: this migration uses Alembic
batch mode (recreate-and-copy) per the Alembic SQLite documentation.
"""
from alembic import op

revision: str | None = 'ce38830a9933'
down_revision: str | None = 'e139d6c9018a'
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    with op.batch_alter_table("signals") as batch_op:
        batch_op.create_unique_constraint(
            'uq_signal_per_candle',
            ['product_id', 'granularity', 'config_hash', 'candle_start_time'],
        )


def downgrade() -> None:
    with op.batch_alter_table("signals") as batch_op:
        batch_op.drop_constraint('uq_signal_per_candle', type_='unique')
