"""Application T contracts; no runtime factory or HTTP entry is enabled here."""
from uuid import uuid4
import pytest


def test_dispatch_principals_flags_and_static_templates_are_closed():
    from application.night_case_ai_dispatch import AccountPrincipal, WorkerPrincipal, DispatchFlags, RENDER_TEMPLATE_HASH
    AccountPrincipal(uuid4());WorkerPrincipal('worker-test')
    assert not DispatchFlags().enabled and not DispatchFlags().external_allowed
    assert len(RENDER_TEMPLATE_HASH)==64
    for invalid in ('telegram:123',True,None):
        with pytest.raises(ValueError):AccountPrincipal(invalid)
    for invalid in ('', 'bad\nworker', 'x'*97):
        with pytest.raises(ValueError):WorkerPrincipal(invalid)
