"""Invitation reward rules. Pure; the invited-by links live in the ``farm_invites`` table (``Unit.invite_*``).

* The invited farm gets a one-time bonus when it is linked to an inviter (a fresh farm only: created < 24 h ago, level 1,
  not linked before). A farm can have exactly one inviter and an inviter can never be the farm itself.
* The inviter gets coins ONCE per invited farm, lazily on their own visit, when that farm reached ``INVITE['level']``.
* Limits per inviter: ``per_day`` rewards per Moscow day and ``total`` rewards ever; a reward that does not fit waits.
* Neighbours: when two farms become neighbours for the FIRST time ever, BOTH get ``NEIGHBOR['reward']`` coins (about half a day
  of early income: ``income_ref(1) // 2``). Once per unordered pair for good (``farm_neighbor_pairs``), so parting and meeting
  again pays nothing; at most ``per_day`` / ``total`` such rewards per farm. An unpaid pair at the daily limit can claim
  later; an exhausted lifetime limit cannot be recovered. Rewards are paid on acceptance or explicitly claimed by
  previously accepted neighbours, with both farm aggregates locked in the same transaction.
* Coins only. XP never comes from here (the only XP funnel is ``progression.grant_xp``).
"""
from .catalog import INVITE, LEVELS, level, income_ref
from .domain import need, event
from . import economy


NEIGHBOR = dict(reward=income_ref(1) // 2, per_day=5, total=40)


def neighbor_state(farm):
    return farm.get('neighbor_bonus') or dict(day=-1, today=0, total=0, earned=0)


def neighbor_room(farm, now):
    r = neighbor_state(farm)
    today = r['today'] if r['day'] == economy.moscow_day(now) else 0
    return r['total'] < NEIGHBOR['total'] and today < NEIGHBOR['per_day']


def neighbor_left(farm, now):
    r = neighbor_state(farm)
    today = r['today'] if r['day'] == economy.moscow_day(now) else 0
    return max(0, min(NEIGHBOR['per_day'] - today, NEIGHBOR['total'] - r['total']))


def pay_neighbor(farm, partner, now):
    """Credit one side of a new pair. The caller has checked ``neighbor_room`` and claimed the pair."""
    r = farm.setdefault('neighbor_bonus', dict(day=-1, today=0, total=0, earned=0))
    day = economy.moscow_day(now)
    if r['day'] != day:
        r['day'], r['today'] = day, 0
    r['today'] += 1
    r['total'] += 1
    r['earned'] += NEIGHBOR['reward']
    farm['coins'] += NEIGHBOR['reward']
    r.setdefault('rewards', []).append(dict(id=partner['id'], partner_id=partner['id'],
                                            partner_name=partner['name'], amount=NEIGHBOR['reward'], at=now))
    r['rewards'] = r['rewards'][-NEIGHBOR['total']:]
    event(farm, now, f'Награда за соседство с «{partner["name"]}»: +{NEIGHBOR["reward"]} монет каждому.', 'neighbor')


def state(farm):
    return farm.get('referral') or dict(day=-1, today=0, total=0, earned=0)


def fresh(farm, now):
    return (farm.get('invited_by') is None and farm['xp'] < LEVELS[1]
            and now - farm.get('created_at', now) <= INVITE['fresh_hours'] * 3600)


def room(farm, now):
    r = state(farm)
    today = r['today'] if r['day'] == economy.moscow_day(now) else 0
    return r['total'] < INVITE['total'] and today < INVITE['per_day']


def today_left(farm, now):
    r = state(farm)
    today = r['today'] if r['day'] == economy.moscow_day(now) else 0
    return max(0, min(INVITE['per_day'] - today, INVITE['total'] - r['total']))


def pay_inviter(farm, name, now):
    r = farm.setdefault('referral', dict(day=-1, today=0, total=0, earned=0))
    day = economy.moscow_day(now)
    if r['day'] != day:
        r['day'], r['today'] = day, 0
    need(room(farm, now), 'invite_limit', 'Лимит наград за приглашения исчерпан.')
    r['today'] += 1
    r['total'] += 1
    r['earned'] += INVITE['reward']
    farm['coins'] += INVITE['reward']
    event(farm, now, f'{name} дорос до {INVITE["level"]} уровня по твоему приглашению: +{INVITE["reward"]} монет.', 'invite')


def give_bonus(farm, inviter_id, inviter_name, now):
    farm['invited_by'] = inviter_id
    farm['coins'] += INVITE['bonus']
    event(farm, now, f'{inviter_name} позвал тебя в игру: +{INVITE["bonus"]} монет на старт.', 'invite')


def view(farm, rows, now):
    """Client block: amounts, limits and the progress of the farms this farm invited."""
    invited = []
    for r in rows:
        lv = level(r['xp'])
        invited.append(dict(name=r['name'], level=lv, goal=INVITE['level'],
                            status='rewarded' if r['rewarded_at'] is not None else ('ready' if lv >= INVITE['level'] else 'growing')))
    s = state(farm)
    return dict(reward=INVITE['reward'], bonus=INVITE['bonus'], level=INVITE['level'], per_day=INVITE['per_day'], total_limit=INVITE['total'],
                total=s['total'], earned=s['earned'], today_left=today_left(farm, now), invited=invited,
                can_enter_code=fresh(farm, now),
                neighbor=dict(reward=NEIGHBOR['reward'], per_day=NEIGHBOR['per_day'], total_limit=NEIGHBOR['total'],
                              today_left=neighbor_left(farm, now), total=neighbor_state(farm)['total'], earned=neighbor_state(farm)['earned']))
