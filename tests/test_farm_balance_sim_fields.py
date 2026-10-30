"""E27: the balance simulator models the rules=3 fields (manual quality, melt, spray, repair) and measures their payback."""
import sys

import pytest

from scripts import farm_balance_sim as sim


def test_manual_quality_keeps_the_bonus_inside_the_full_window_and_melts_it_after():
    ha, width = 1, 1
    a = sim.FD.auto_seconds(ha, width)
    assert sim.manual_field_quality(1100, ha, width, 0, 200) == 1100          # 2 A <= 2.5 A: the whole bonus
    assert sim.manual_field_quality(1100, ha, width, 0, 250) == 1100
    assert sim.manual_field_quality(1100, ha, width, 0, 600) == sim.C.Q_AUTO_FULL   # 6 A: nothing is left over the autopilot
    mid = sim.manual_field_quality(1250, ha, width, 0, 425)                    # half way between 2.5 A and 6 A
    assert sim.C.Q_AUTO_FULL < mid < 1250 and abs(mid - (900 + 350 // 2)) <= 2
    assert a == 90


def test_manual_quality_pays_for_bumps_and_never_drops_below_the_floor():
    one_hit = sim.manual_field_quality(1100, 1, 1, 1, 200)
    assert one_hit == 1100 - sim.C.FIELD_HIT_DAMAGE * sim.C.FIELD_COND_PENALTY
    assert sim.manual_field_quality(850, 1, 1, 34, 200) == sim.C.Q_BASE_FULL    # a bad run keeps its own quality, clamped at 0.85
    assert sim.manual_field_quality(1250, 1, 1, 0, 100) == 1250


def test_overrides_change_and_restore_the_catalog_numbers():
    from qw_farm import upkeep_config as uc
    before = (sim.C.FIELD_UPKEEP, sim.C.FIELD_FUEL, [dict(x) for x in sim.C.FIELD_STEPS],
              {k: tuple(m['costs']) for k, m in sim.C.FIELD_MACHINES.items()}, dict(sim.C.LAND_STEPS[6]))
    with sim.overrides(upkeep=900, steps=(1, 2, 3, 4, 5), machines=(10, 20, 30, 40), widths=(7, 8), fuel=11, land={22: 12345}):
        assert sim.C.FIELD_UPKEEP == uc.defaults()['field_per_hectare'] == sim.FD.FIELD_UPKEEP == 900
        assert sim.C.FIELD_FUEL == sim.FD.FIELD_FUEL == 11
        assert [s['cost'] for s in sim.FD.FIELD_STEPS] == [1, 2, 3, 4, 5]
        assert sim.C.FIELD_MACHINES['seeder']['costs'] == (20, 7, 8)
        assert sim.C.land_step(20)['cost'] == 12345
    after = (sim.C.FIELD_UPKEEP, sim.C.FIELD_FUEL, [dict(x) for x in sim.C.FIELD_STEPS],
             {k: tuple(m['costs']) for k, m in sim.C.FIELD_MACHINES.items()}, dict(sim.C.LAND_STEPS[6]))
    assert after == before and uc.defaults()['field_per_hectare'] == before[0]


def test_isolated_field_payback_prefers_hands_and_counts_spray_and_repair():
    manual = sim.field_payback_run('active', 'manual', 0, days=20, warmup=6)
    auto = sim.field_payback_run('active', 'auto', 0, days=20, warmup=6)
    assert manual['net'] > auto['net'] > 0 and manual['xp'] > auto['xp']             # hands beat the autopilot, the field pays its upkeep
    assert manual['net'] == pytest.approx(manual['coins'] - manual['upkeep'])
    assert manual['ops']['spray'] > 0 and auto['ops']['spray'] == 0                   # +12 % is worth the fuel, +2.5 % is not
    assert manual['repair'] > 0 and auto['repair'] == 0
    assert manual['q']['sow'] == sim.manual_field_quality(1100, 1, 1, 1, 200)
    assert sim.payback_days(60000, manual['net']) < sim.payback_days(60000, auto['net'])
    assert sim.payback_days(1, 0) == float('inf')


def test_manual_share_mixes_hand_and_autopilot_operations():
    mixed = sim.Sim('active', 1, orchard=False, field_mode='manual', field_share=50)
    f = mixed.f
    f['xp'] = sim.C.LEVELS[21]
    f['coins'], f['starter_credit'] = 10 ** 8, 0
    f['fields'] = [sim.FD.new_field(sim.C.FIELD_STEPS[0])]
    f['field_machines'] = {k: dict(tier=1, acquired_at=mixed.t0) for k in sim.C.FIELD_MACHINES}
    t = sim.T_BASE + 8 * 3600
    for visit in range(6):
        mixed.settle(t)
        t = mixed.fields_visit(t) + 12 * 3600
    assert mixed.fs['ops_manual'] > 0 and mixed.fs['ops_auto'] > 0
    assert abs(mixed.fs['ops_manual'] - mixed.fs['ops_auto']) <= 1
    assert not mixed.err


def test_cli_routes_payback_flags_and_restores_after(monkeypatch, capsys):
    seen = {}

    def fake_report(profiles=('active',), modes=('manual', 'auto'), days=70, **model):
        seen.update(modes=modes, days=days, model=model, upkeep=sim.C.FIELD_UPKEEP, steps=[s['cost'] for s in sim.C.FIELD_STEPS])
        return 'PAYBACK TABLE'

    monkeypatch.setattr(sys, 'argv', ['farm_balance_sim.py', '--field-payback', '--days', '40', '--field-mode', 'manual', '--field-q', '1200',
                                      '--field-manual-share', '50', '--sim-field-upkeep', '777', '--sim-field-steps', '1,2,3,4,5'])
    monkeypatch.setattr(sim, 'field_payback_report', fake_report)
    before = sim.C.FIELD_UPKEEP
    sim.main()
    assert 'PAYBACK TABLE' in capsys.readouterr().out
    assert seen == dict(modes=('manual',), days=40, model=dict(q=1200, share=50), upkeep=777, steps=[1, 2, 3, 4, 5])
    assert sim.C.FIELD_UPKEEP == before
