"""Simulator-only shift overrides must respect and restore the live validation contract."""
import sys

from scripts import farm_balance_sim as sim


def test_simulated_manor_quota_patches_and_restores_validation_limits(monkeypatch, capsys):
    catalog = sim.C
    expansion = sim.X
    before = (dict(catalog.SHIFTS['manor']), catalog.MAX_SHIFT_ACTIONS,
              expansion.MAX_SHIFT_ACTIONS, sim.T_BASE, sim.PROFILES['active']['sessions'])
    observed = {}

    def fake_run(self):
        observed['actions'] = catalog.SHIFTS['manor']['actions']
        observed['cost'] = catalog.SHIFTS['manor']['cost']
        observed['seconds'] = catalog.SHIFTS['manor']['seconds']
        observed['catalog_limit'] = catalog.MAX_SHIFT_ACTIONS
        observed['expansion_limit'] = expansion.MAX_SHIFT_ACTIONS
        observed['t_base'] = sim.T_BASE
        observed['sessions'] = sim.PROFILES['active']['sessions']
        observed['demand_actions'] = self.demand_actions_override
        return self

    monkeypatch.setattr(sys, 'argv', ['farm_balance_sim.py', '--days', '1', '--profile', 'active',
                                      '--craft-masters', '2', '--sim-manor-actions', '960',
                                      '--sim-demand-actions', '480'])
    monkeypatch.setattr(sim.Sim, 'run', fake_run)
    monkeypatch.setattr(sim, 'report', lambda _: 'captured sim')

    sim.main()
    output = capsys.readouterr().out

    assert observed == {
        'actions': 960, 'cost': before[0]['cost'], 'seconds': before[0]['seconds'],
        'catalog_limit': 960, 'expansion_limit': 960, 't_base': before[3], 'sessions': before[4],
        'demand_actions': 480,
    }
    assert output.count('SIMULATION ONLY') == 2 and 'product catalog unchanged' in output
    after = (dict(catalog.SHIFTS['manor']), catalog.MAX_SHIFT_ACTIONS,
             expansion.MAX_SHIFT_ACTIONS, sim.T_BASE, sim.PROFILES['active']['sessions'])
    assert after == before


def test_fixed_demand_budget_is_independent_of_the_shift_action_quota():
    scenario = sim.Sim('active', 1, helpers=True, craft_masters=2, demand_actions_override=480)
    scenario.f['xp'] = sim.C.LEVELS[19]
    scenario.f['objects'] = [dict(id='mill-demand-test', type='mill', x=0, y=0, w=2, h=2,
                                  level=3, jobs=[], last_recipe='flour', recipes_memory=['flour'])]
    scenario.f['inventory'] = {}
    scenario.pick_jobs = lambda obj, now, slots, reach: [sim.C.RECIPES['flour']]
    scenario.gap = lambda now: 28_800

    scenario.helper_plan = lambda: dict(seconds=28_800, actions=480)
    baseline_demand = scenario.demand(sim.T_BASE)
    scenario.helper_plan = lambda: dict(seconds=28_800, actions=960)
    larger_quota_demand = scenario.demand(sim.T_BASE)

    assert larger_quota_demand == baseline_demand
