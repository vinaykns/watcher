"""Add apscheduler_jobs table to store background jobs

Revision ID: 0f6042416884
Revises: 001
Create Date: 2017-03-24 11:21:29.036532

"""
from alembic import op
import sqlalchemy as sa

from watcher.db.sqlalchemy import models

# revision identifiers, used by Alembic.
revision = '0f6042416884'
down_revision = '001'


def upgrade():
    op.create_table(
        'apscheduler_jobs',
        sa.Column('id', sa.Unicode(191, _warn_on_bytestring=False),
                  nullable=False),
        sa.Column('next_run_time', sa.Float(25), index=True),
        sa.Column('job_state', sa.LargeBinary, nullable=False),
        sa.Column('service_id', sa.Integer(), nullable=False),
        sa.Column('tag', models.JSONEncodedDict(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['service_id'], ['services.id'])
    )


def downgrade():
    op.drop_table('apscheduler_jobs')
