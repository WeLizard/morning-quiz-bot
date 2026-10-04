"""Move the mutable question bank contract into PostgreSQL."""

from alembic import op
import sqlalchemy as sa


revision = '20260904_0009'
down_revision = '20260904_0008'
branch_labels = None
depends_on = None

NOW = sa.text('CURRENT_TIMESTAMP')
EMPTY_OBJECT = sa.text("'{}'::json")
EMPTY_ARRAY = sa.text("'[]'::json")


def upgrade():
    op.create_table(
        'question_categories',
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('revision', sa.Integer(), server_default='0', nullable=False),
        sa.Column('content_hash', sa.String(64), nullable=False),
        sa.Column('questions', sa.JSON(), server_default=EMPTY_ARRAY, nullable=False),
        sa.Column('metadata_json', sa.JSON(), server_default=EMPTY_OBJECT, nullable=False),
        sa.Column('archived', sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint('name'),
    )
    op.create_table(
        'question_category_revisions',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('category_name', sa.String(100), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('content_hash', sa.String(64), nullable=False),
        sa.Column('questions', sa.JSON(), server_default=EMPTY_ARRAY, nullable=False),
        sa.Column('metadata_json', sa.JSON(), server_default=EMPTY_OBJECT, nullable=False),
        sa.Column('action', sa.String(32), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('category_name', 'revision', name='uq_question_category_revision'),
    )
    op.create_index(
        'ix_question_category_history', 'question_category_revisions',
        ['category_name', 'created_at'],
    )


def downgrade():
    op.drop_index('ix_question_category_history', table_name='question_category_revisions')
    op.drop_table('question_category_revisions')
    op.drop_table('question_categories')
