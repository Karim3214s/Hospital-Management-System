"""Bill Base"""

from alembic import op
import sqlalchemy as sa

revision = '4064efd8d09b'
down_revision = '3c4dc1f25b21'
branch_labels = None
depends_on = None


def upgrade():

    with op.batch_alter_table('bills') as batch_op:

        batch_op.add_column(
            sa.Column('record_Id', sa.Integer(), nullable=True)
        )

        batch_op.add_column(
            sa.Column('appointment_Id', sa.Integer(), nullable=True)
        )

        batch_op.add_column(
            sa.Column('bill_status',
            sa.String(20), nullable=True)
        )

        batch_op.add_column(
            sa.Column('bill_date',
            sa.Date(), nullable=True)
        )

        batch_op.add_column(
            sa.Column('notes',
            sa.String(255), nullable=True)
        )

        batch_op.add_column(
            sa.Column('created_by',
            sa.Integer(), nullable=True)
        )


def downgrade():
    pass