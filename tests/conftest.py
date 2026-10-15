"""Farm tests run with a FRACTIONAL wall clock by default (production uses time.time(), a float).

Every ``FarmService`` built inside a ``test_farm_*`` module gets ``clock() + FARM_TEST_CLOCK_FRACTION`` (default 0.8106), so
the single time-normalisation point (``qw_farm.catalog.tick``) is exercised by all scenarios: helpers/shifts, workshops,
animals, caravan, contracts, stage 14 economy, progression. ``FARM_TEST_CLOCK_FRACTION=0`` restores whole-second clocks.
"""
import os
import pytest


@pytest.fixture(autouse=True)
def _farm_fractional_clock(request, monkeypatch):
    if not request.node.fspath.basename.startswith('test_farm'):
        return
    fraction = float(os.getenv('FARM_TEST_CLOCK_FRACTION', '0.8106'))
    if not fraction:
        return
    from qw_farm import service
    original = service.FarmService.__init__

    def init(self, unit, principal, *, clock=None, speed=1, **kwargs):
        if clock is None:
            import time
            clock = time.time
        original(self, unit, principal, clock=lambda: clock() + fraction, speed=speed, **kwargs)

    monkeypatch.setattr(service.FarmService, '__init__', init)
