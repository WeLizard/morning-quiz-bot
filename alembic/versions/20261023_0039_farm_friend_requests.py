"""Neighbour request escrow and history, additive only.

Revision ID: 20261023_0039
Revises: 20261020_0038
"""
from alembic import op
import sqlalchemy as sa

revision = '20261023_0039'
down_revision = '20261020_0038'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(sa.text("CREATE TABLE farm_requests (\n\tid UUID NOT NULL, \n\trequester_farm UUID NOT NULL, \n\trequester_account UUID NOT NULL, \n\taudience_farm UUID, \n\titem TEXT NOT NULL, \n\tqty INTEGER NOT NULL, \n\toffer_kind TEXT NOT NULL, \n\toffer_item TEXT, \n\toffer_qty INTEGER, \n\toffer_coins INTEGER, \n\tvalue INTEGER NOT NULL, \n\tstatus TEXT NOT NULL, \n\tgiver_farm UUID, \n\tgiver_account UUID, \n\tcreated_at FLOAT NOT NULL, \n\texpires_at FLOAT NOT NULL, \n\tdelivered_at FLOAT, \n\tsettle_by FLOAT, \n\tclosed_at FLOAT, \n\tPRIMARY KEY (id), \n\tCONSTRAINT ck_farm_request_offer CHECK (offer_kind IN ('free','coins','item')), \n\tCONSTRAINT ck_farm_request_status CHECK (status IN ('open','delivered','settled','returned','cancelled','expired')), \n\tCONSTRAINT ck_farm_request_amount CHECK (qty BETWEEN 1 AND 20 AND value > 0), \n\tCONSTRAINT ck_farm_request_terms CHECK ((offer_kind='free' AND offer_item IS NULL AND offer_qty IS NULL AND offer_coins IS NULL) OR (offer_kind='coins' AND offer_item IS NULL AND offer_qty IS NULL AND offer_coins > 0) OR (offer_kind='item' AND offer_item IS NOT NULL AND offer_qty > 0 AND offer_coins IS NULL)), \n\tCONSTRAINT ck_farm_request_not_self CHECK (giver_farm IS NULL OR giver_farm <> requester_farm), \n\tFOREIGN KEY(requester_farm) REFERENCES farm_states (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(requester_account) REFERENCES accounts (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(audience_farm) REFERENCES farm_states (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(giver_farm) REFERENCES farm_states (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(giver_account) REFERENCES accounts (id) ON DELETE RESTRICT\n)"))
    op.execute(sa.text('CREATE INDEX ix_farm_requests_giver_delivered ON farm_requests (giver_farm, delivered_at)'))
    op.execute(sa.text('CREATE INDEX ix_farm_requests_requester_status ON farm_requests (requester_farm, status)'))


def downgrade():
    if op.get_bind().scalar(sa.text('SELECT EXISTS (SELECT 1 FROM farm_requests)')):
        raise RuntimeError('Farm request history exists; refusing to delete it by downgrading')
    op.drop_table('farm_requests')
