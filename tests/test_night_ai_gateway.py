"""Gateway contracts use synthetic credentials and owned loopback sockets only."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest


def test_shared_budget_cannot_reset_on_oauth_or_wall_clock_correction():
    from infrastructure.night_ai_gateway import NetworkBudget
    now=datetime(2026,11,16,tzinfo=timezone.utc);permit,nonce=uuid4(),uuid4()
    budget=NetworkBudget.create(permit,nonce,now,now+timedelta(seconds=12),now_utc=now,monotonic_now=100.)
    assert budget.remaining(103.)==9
    assert budget.remaining(111.)==1
    assert budget.remaining(115.)==0
    with pytest.raises(ValueError):NetworkBudget.create(permit,nonce,now,now+timedelta(seconds=13),now_utc=now,monotonic_now=100.)


@pytest.mark.parametrize('address',['127.0.0.1','10.0.0.1','100.64.0.1','169.254.169.254','100.100.100.200',
    '168.63.129.16','192.0.2.1','198.18.0.1','224.0.0.1','::ffff:8.8.8.8','64:ff9b::808:808',
    '2002:0808:0808::1','2001::1','2001:db8::1','fe80::1','ff02::1','fd00:ec2::254'])
def test_cloud_explicit_ip_matrix_denies_special_ranges(address):
    from infrastructure.night_ai_gateway import cloud_ip_allowed
    assert not cloud_ip_allowed(address)


def test_cloud_ip_matrix_accepts_public_numeric_addresses():
    from infrastructure.night_ai_gateway import cloud_ip_allowed
    assert cloud_ip_allowed('8.8.8.8')
    assert cloud_ip_allowed('2606:4700:4700::1111')
