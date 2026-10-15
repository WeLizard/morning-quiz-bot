#!/usr/bin/env python
"""Deterministic progression simulator for the farm (qw_farm). Usage:

    python scripts/farm_balance_sim.py [--days 25] [--profile all|active|online|casual|grind|skilled] [--debug] [--no-fields]
    (r9: e.g. --days 90; the run stops at the maximum level L50)

WHAT IS REAL.  Every game action goes through the real ``qw_farm.domain.apply`` (plant, plant_many, harvest via
collect_group, queue, feed_all, sell, order, skip_order, quest, expand, build, buy_animal, upgrade, start_trip,
collect_trip, caravan_fill, contract_claim ...), ``qw_farm.expansion.settle`` and the real catalog.  Prices, XP, times,
land steps, orders (``make_order``), caravan and contracts (``qw_farm.market``) are exactly the game's.  The only
non-game elements are the player policies below.  Nothing is randomised: the game's own hash-based RNG is the only
source of variation, so the output is reproducible.

PLAYER MODEL (documented simplifications).
  * Time: the clock is the game clock (Moscow-day aligned).  A session is one visit; actions inside a session happen at
    ``t`` (+ a few seconds for order re-rolls, + one crop cycle per step in the grind loop).  ``active``: sessions 08:00
    and 22:00, ~12 orders/day.  ``online`` = a visit every 2 hours 08:00-22:00.  ``casual``: one session 20:00, ~5
    orders/day.  ``grind`` = active + inside every session a ~9 minute loop: the best FAST crop of the level (growth
    < 1800 s, best (XP + 0.25 * profit) per hour; wheat at L1) on every empty bed, one cycle later collect + replant, the
    mill is kept busy with the best recipe (feed) - the "spam short crops + mill feed loop" exploit.
  * Session order: collect (collect_group animals/workshops/plots, forest baskets) -> quests, daily contracts, caravan
    crates -> orders (deliver what the stock covers, skip what it cannot; up to 4 passes, 20 s apart, capped by the
    profile's orders/day) -> production (feed_all, workshop queues) -> forest trips -> sell the surplus -> invest
    -> plant.  Free player time is not otherwise limited (tap budgets are not modelled).
  * Planting: 1) a crop for an open "harvest" daily contract if it can ripen the same Moscow day, 2) crops that the
    planned production needs (deficit of stock + growing), at most 60% of the empty beds, 3) the rest with the best crop by
    (XP + 0.25 * profit) per *effective* hour, where effective time runs to the first session after the crop is ripe.
  * Production: for every workshop the greedy queue picks, per free slot, the recipe with the best value
    (sale value of outputs - inputs + XP, 1 XP = 1 coin) that fits the time to the next session and whose inputs are in
    stock; goods that a planned recipe/animal needs but the stock lacks get a bonus (simple demand propagation, 3 levels).
  * Investment (greedy by payback = cost / estimated daily gain, 1 XP = 1 coin): land at once when the level allows,
    beds, workshops and animal houses (+ animal), building upgrades 1->3 (when the upgrade goods are in stock), barn
    upgrade, forest guides.  Beds/buildings are placed first-fit.  Coins reserved: seeds for the empty beds.
  * Stock policy: sell everything above max(4, planned need); the 4 kept units serve orders/crates.
  * Sinks (stage 14, upkeep from L10 is charged by the real ``economy.bill`` inside ``domain.apply``): ``pay_upkeep`` whenever there is
    a debt (start of a session and after selling); the surplus above 2 * INCOME_REF(level) goes 50% to the village fund (real
    ``fund_contribute``, coins) until the 5th personal tier of the season is full, then up to 30% of the surplus buys the most
    expensive paid decor (including R16 decor/trophies) that is open and not yet owned.  The shared village counter is not simulated (one farm).
  * Fields (stage 15, real ``qw_farm.fields`` through ``domain.apply``): a field step is bought at its price + one day of INCOME_REF
    in reserve, then the three tier-1 machines (cheapest first); width upgrades come from the surplus.  EVERY visit each field gets
    its next operation (harvest -> cultivate -> sow, best crop by value per effective hour): ``active``/``casual``/``grind`` use the
    autopilot (one operation per visit, ready after 90 s * ha / width), ``skilled`` drives the three operations by hand in one visit
    with the reference driver ``fields.reference_path`` (the real server replay gives q 0.85..1.10; the achieved average is printed).
    Field work finished by ``settle`` (autopilot, expiry) is booked to the ``fields`` source too.
  * NOT modelled: helpers' shifts, tractor/combine/robot (the free bulk commands make them redundant, which is the
    point of a review item), neighbours/helps/gifts/market stall (quests q4/q9), secrets/reward decor, quests q12-q14.
    Reputation, caravan, contracts and orders are the real code.

OUTPUT per profile: days to levels 5/10/.../50 (step 5), per level band the net coin income and XP per day, the share of
each income source (value added: crops = harvest value - seeds, workshops/animals = outputs - inputs, orders/caravan/
contracts = premium over the goods' shop value ...) and of each XP source.
"""
import argparse
import math
import os
import sys
import time
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from qw_farm import catalog as C          # noqa: E402
from qw_farm import domain as D           # noqa: E402
from qw_farm import economy as E          # noqa: E402
from qw_farm import expansion as X        # noqa: E402
from qw_farm import fields as FD          # noqa: E402
from qw_farm import market as M           # noqa: E402
from qw_farm import progression as P      # noqa: E402

DAY = 86400
T_BASE = 20000 * DAY - M.TZ_OFFSET        # a Moscow midnight
LEVEL_MAX = P.LEVEL_MAX
BANDS = [(1, 4)] + [(lo, lo + 4) for lo in range(5, 45, 5)] + [(45, LEVEL_MAX)]
MILESTONES = tuple(range(5, LEVEL_MAX + 1, 5))
FRICTION = 0.6        # estimated gains of new buildings are discounted: supply chains are never perfect
MAX_COPIES = 3
KEEP = 4
PROFILES = {
    'active': dict(label='active: sessions 08:00 + 22:00 (~10 min), bulk commands, ~12 orders/day',
                   sessions=(8 * 3600, 22 * 3600), orders=12, grind=False),
    'casual': dict(label='casual: one session 20:00 (~10 min), ~5 orders/day',
                   sessions=(20 * 3600,), orders=5, grind=False),
    'online': dict(label='online: a visit every 2 hours from 08:00 to 22:00 (8 sessions, ~10 min), bulk commands, ~12 orders/day',
                   sessions=tuple(h * 3600 for h in range(8, 23, 2)), orders=12, grind=False),
    'grind': dict(label='active+grind: active + the best FAST crop of the level (< 1800 s) re-planted in a ~9 minute loop and mill feed loop in each session',
                  sessions=(8 * 3600, 22 * 3600), orders=12, grind=True),
    'skilled': dict(label='skilled: active, but fields are driven by hand (all three operations per visit, reference driver)',
                    sessions=(8 * 3600, 22 * 3600), orders=12, grind=False, skilled=True),
}
ANIMAL_BY_HOUSE = {a['building']: a for a in C.ANIMALS.values()}
WORKSHOPS = sorted({r['building'] for r in C.RECIPES.values()})
PAID_DECOR = [*C.DECOR_SHOP, *C.DECOR_EXTRA]
GUIDES = [h for h in C.HELPERS.values() if h['role'] == 'guide']


def price(i):
    return C.ITEMS[i]['price']


def vol(d):
    return sum(price(k) * q for k, q in d.items())


def band_of(lv):
    return next(b for b in BANDS if b[0] <= lv <= b[1])


def recipe_score(r):
    return vol(r['outputs']) - vol(r['inputs']) + r['xp']


def fill(recipes, slots, mult, gap):
    """Greedy ideal queue for one visit: (value, chosen). A recipe longer than the gap counts 1/ceil(sec/gap)."""
    total, chosen, remaining = 0.0, [], gap
    for _ in range(slots):
        best = None
        for r in recipes:
            sec = D.duration(r['seconds'] * mult, 1)
            if sec <= remaining and (best is None or recipe_score(r) > best[0]):
                best = (recipe_score(r), r, sec)
        if best is None:
            break
        total += best[0]
        remaining -= best[2]
        chosen.append(best[1])
    if not chosen and recipes:
        r = min(recipes, key=lambda x: x['seconds'])
        sec = D.duration(r['seconds'] * mult, 1)
        total, chosen = recipe_score(r) / math.ceil(sec / gap), [r]
    return total, chosen


class Sim:
    def __init__(self, name, days, debug=False, fields=True):
        self.name, self.days, self.debug, self.fields = name, days, debug, fields
        self.p = PROFILES[name]
        self.sessions = sorted(self.p['sessions'])
        self.t0 = T_BASE + self.sessions[0]
        self.f = D.new_farm('balance-sim-' + name, 'Sim', self.t0)
        X.upgrade_state(self.f)
        self.n = 0
        self.level_t = {1: self.t0}
        self.maxlv = 1
        self.income = defaultdict(Counter)    # band -> tag -> net wealth delta (coins + goods at shop price)
        self.gross = defaultdict(Counter)     # band -> tag -> coins received
        self.xp_src = defaultdict(Counter)    # band -> tag -> xp
        self.mech = defaultdict(Counter)      # band -> m1 / m2 (extra XP) / m3 (XP lost to Fatigue)
        self.capex = defaultdict(Counter)
        self.sinks = defaultdict(Counter)     # band -> upkeep / fund / decor coins
        self.decor_owned = set()
        self.err = Counter()
        self.orders_today = (-1, 0)
        self.sold_log = []                    # (day, coins from sell) for the barn upgrade estimate
        self.cache = {}
        self.end_coins = {}
        self.end_t = self.t0
        self.fs = Counter()                   # field statistics (ops, fuel, seeds, ha-days)
        self.fs_q = defaultdict(list)         # operation -> achieved manual q (permille)
        self.fs_ha = {}                       # day -> hectares owned

    # ---------------------------------------------------------------- plumbing
    def lv(self):
        return C.level(self.f['xp'])

    def inv_value(self):
        return sum(price(k) * q for k, q in self.f['inventory'].items())

    def cmd(self, kind, data, now, tag):
        f = self.f
        c0, x0, w0, lv0 = f['coins'], f['xp'], self.inv_value(), C.level(f['xp'])
        m0 = dict(P.progress(f)['total'])
        paid0 = E.state(f)['stats']['upkeep_paid']
        self.n += 1
        try:
            D.apply(f, f, kind, data, now, f'c{self.n}')
        except D.FarmError as e:
            self.err[(kind, e.code)] += 1
            return False
        dc, dx = f['coins'] - c0, f['xp'] - x0
        du = E.state(f)['stats']['upkeep_paid'] - paid0       # the daily bill is taken inside whichever command came first
        dw = dc + self.inv_value() - w0 + du
        band = band_of(lv0)
        if du:
            self.sinks[band]['upkeep'] += du
        if tag.startswith('sink:'):
            if tag != 'sink:upkeep':
                self.sinks[band][tag[5:]] += -dw
        elif tag.startswith('capex'):
            self.capex[band][tag] += -dw
        else:
            self.income[band][tag] += dw
        if dc > 0:
            self.gross[band][tag] += dc
        if dx:
            self.xp_src[band][tag] += dx
        for k, v in P.progress(f)['total'].items():
            if v != m0[k]:
                self.mech[band][k] += v - m0[k]
        lv = C.level(f['xp'])
        while self.maxlv < lv:
            self.maxlv += 1
            self.level_t[self.maxlv] = now
        if kind == 'sell':
            self.sold_log.append((int((now - T_BASE) // DAY), dc))
        return True

    def stock(self, item):
        return self.f['inventory'].get(item, 0)

    def objects(self, pred):
        return [o for o in self.f['objects'] if pred(o)]

    # ---------------------------------------------------------------- calendar
    def day_of(self, t):
        return int((t - T_BASE) // DAY)

    def next_session(self, t, inclusive=False):
        d = self.day_of(t) - 1
        while True:
            for s in self.sessions:
                tt = T_BASE + d * DAY + s
                if tt > t or (inclusive and tt == t):
                    return tt
            d += 1

    def gap(self, now):
        return self.next_session(now) - now

    def eff(self, seconds, now):
        """Real time until the first session at which a thing that takes ``seconds`` can be collected."""
        return self.next_session(now + seconds, inclusive=True) - now

    def gaps_per_day(self):
        s = self.sessions
        return [(s[(i + 1) % len(s)] - s[i]) % DAY or DAY for i in range(len(s))]

    # ---------------------------------------------------------------- estimates (ideal, no stock)
    def reach(self):
        return set(D.reachable(self.f))

    def recipes_at(self, typ, reach):
        lv = self.lv()
        return [r for r in C.RECIPES.values() if r['building'] == typ and r['level'] <= lv
                and set(r['inputs']) <= reach]

    def workshop_daily(self, typ, lvl, reach):
        key = ('w', typ, lvl, self.lv())
        if key not in self.cache:
            rec = self.recipes_at(typ, reach)
            mult, slots = C.RECIPE_SPEED[lvl], C.queue_slots(lvl)
            self.cache[key] = sum(fill(rec, slots, mult, g)[0] for g in self.gaps_per_day()) if rec else 0.0
        return self.cache[key]

    def animal_daily(self, animal, lvl, reach):
        key = ('a', animal['id'], lvl)
        if key not in self.cache:
            inputs, outputs, secs = C.animal_batch(animal, lvl)
            if not set(inputs) <= reach:
                self.cache[key] = 0.0
            else:
                value = vol(outputs) - vol(inputs) + 5
                secs = D.duration(secs, 1)
                self.cache[key] = sum(value if secs <= g else value / math.ceil(secs / g) for g in self.gaps_per_day())
        return self.cache[key]

    def crop_rank(self, now):
        lv = self.lv()
        rows = []
        for c in C.CROPS.values():
            if c['level'] <= lv:
                profit = c['yield_qty'] * c['price'] - c['cost']
                e = self.eff(c['seconds'], now)
                rows.append(((c['xp'] + 0.25 * profit) / e, c))
        rows.sort(key=lambda x: -x[0])
        return [c for _, c in rows]

    def bed_daily(self, now):
        best = self.crop_rank(now)[0]
        return (best['yield_qty'] * best['price'] - best['cost'] + best['xp']) / (self.eff(best['seconds'], now) / DAY)

    # ---------------------------------------------------------------- demand
    def demand(self, now):
        """Units of goods that the planned production of the next visit wants (plus contract/caravan/upgrade wishes)."""
        f, lv = self.f, self.lv()
        reach = self.reach()
        base = Counter()
        for o in self.objects(lambda o: o['type'] in X.WORKSHOP_TYPES):
            for r in self.pick_jobs(o, now, None, reach):
                base.update(r['inputs'])
        for o in self.objects(lambda o: o.get('animal')):
            base.update(C.animal_batch(C.ANIMALS[o['animal']], o.get('level'))[0])
        m = f['market']
        car = m['caravan']
        if car:
            for c in car['crates']:
                if not c['done']:
                    base[c['item']] += c['qty']
        for c in m['contracts']['items']:
            if not c['claimed'] and c['kind'] == 'craft':
                base[c['item']] += max(0, c['goal'] - M.contract_progress(f, c))
        for spec_lv, spec in C.UPGRADES.items():
            if lv >= spec['level'] and any(C.upgrade_kind(o['type']) and o.get('level', 1) < spec_lv
                                           for o in f['objects']):
                for k, q in spec['items'].items():
                    base[k] += q
        need = Counter(base)
        for _ in range(3):
            extra = Counter()
            for item, q in need.items():
                deficit = q - self.stock(item)
                if deficit <= 0 or item in C.CROPS:
                    continue
                prod = self.producer(item, reach)
                if prod:
                    inputs, out_q = prod
                    batches = math.ceil(deficit / out_q)
                    for k, v in inputs.items():
                        extra[k] += v * batches
            need = base + extra
        return need

    def producer(self, item, reach):
        best = None
        for r in C.RECIPES.values():
            if item in r['outputs'] and r['level'] <= self.lv() and set(r['inputs']) <= reach \
                    and any(o['type'] == r['building'] for o in self.f['objects']):
                sc = recipe_score(r) / r['outputs'][item]
                if best is None or sc > best[0]:
                    best = (sc, r['inputs'], r['outputs'][item])
        for o in self.f['objects']:
            if o.get('animal'):
                a = C.ANIMALS[o['animal']]
                inputs, outputs, _ = C.animal_batch(a, o.get('level'))
                if item in outputs and set(inputs) <= reach:
                    return inputs, outputs[item]
        return (best[1], best[2]) if best else None

    # ---------------------------------------------------------------- production
    def pick_jobs(self, obj, now, dem, reach):
        """Recipes to queue now (real: stock + free slots + time to next visit) or the ideal plan (dem is None)."""
        lv = self.lv()
        recs = [r for r in C.RECIPES.values() if r['building'] == obj['type'] and r['level'] <= lv]
        mult = C.RECIPE_SPEED[C.effective_level(obj.get('level'))]
        slots = C.queue_slots(obj.get('level'))
        gap = self.gap(now)
        if dem is None:
            recs = [r for r in recs if set(r['inputs']) <= reach]
            return fill(recs, slots, mult, gap)[1]
        free = slots - len(obj['jobs'])
        busy = max([now] + [j['ready_at'] for j in obj['jobs']])
        remaining = now + gap - busy
        stock = dict(self.f['inventory'])
        chosen = []
        boost = self.contract_boost(now)
        for _ in range(max(0, free)):
            best = None
            for r in recs:
                sec = D.duration(r['seconds'] * mult, 1)
                if sec > remaining or any(stock.get(k, 0) < q for k, q in r['inputs'].items()):
                    continue
                sc = recipe_score(r) + sum(min(q, max(0, dem[i] - stock.get(i, 0))) * price(i)
                                           for i, q in r['outputs'].items())
                sc += boost.get(next(iter(r['outputs'])), 0)
                if best is None or sc > best[0]:
                    best = (sc, r, sec)
            if best is None:
                break
            _, r, sec = best
            chosen.append(r)
            remaining -= sec
            for k, q in r['inputs'].items():
                stock[k] -= q
        return chosen

    def contract_boost(self, now):
        out = {}
        day_end = (self.day_of(now + M.TZ_OFFSET - 0) + 1) * DAY + T_BASE
        for c in self.f['market']['contracts']['items']:
            if not c['claimed'] and c['kind'] == 'craft' and self.next_session(now) < day_end:
                out[c['item']] = c['coins'] + c['xp']
        return out

    def produce(self, now):
        f = self.f
        dem = self.demand(now)
        reach = self.reach()
        if any(o.get('animal') and not o.get('animal_job') for o in f['objects']):
            self.cmd('feed_all', {'area': None}, now, 'animals')
        for o in self.objects(lambda o: o['type'] in X.WORKSHOP_TYPES):
            for r in self.pick_jobs(o, now, dem, reach):
                if not self.cmd('queue', {'object': o['id'], 'recipe': r['id']}, now, 'workshops'):
                    break
        return dem

    # ---------------------------------------------------------------- forest trips
    def trips(self, now):
        f = self.f
        for t in list(f['trips']):
            if t['ready_at'] <= now:
                self.cmd('collect_trip', {'trip': t['id']}, now, 'forage')
        lv = self.lv()
        slots = [''] + [h['id'] for h in GUIDES if h['id'] in f['helpers']]
        for guide in slots:
            if len(f['trips']) >= 2:
                break
            if guide == '' and any(not t['guide'] for t in f['trips']):
                continue
            if guide and any(t['guide'] == guide for t in f['trips']):
                continue
            best = None
            for r in C.ROUTES.values():
                if r['level'] > lv or any(self.stock(k) < q for k, q in r['inputs'].items()):
                    continue
                spec = C.HELPERS[guide]['specialty'] if guide else None
                outs = dict(r['outputs'])
                if guide and spec == r['specialty']:
                    outs[next(iter(outs))] += 1
                sec = D.duration(r['seconds'] * (0.8 if guide else 1), 1)
                net = vol(outs) + r['xp'] - r['cost'] - vol(r['inputs'])
                e = self.eff(sec, now)
                score = net / (e / self.gap(now))
                if net > 0 and (best is None or score > best[0]):
                    best = (score, r)
            if best:
                self.cmd('start_trip', {'route': best[1]['id'], 'guide': guide}, now, 'forage')

    # ---------------------------------------------------------------- rewards, orders
    def rewards(self, now):
        f = self.f
        for q in C.QUESTS:
            if q['id'] not in f['claimed_quests'] and f['stats'].get(q['stat'], 0) >= q['goal']:
                self.cmd('quest', {'quest': q['id']}, now, 'quests')
        if self.lv() >= M.CONTRACTS['level']:
            for c in f['market']['contracts']['items']:
                if not c['claimed'] and M.contract_progress(f, c) >= c['goal']:
                    self.cmd('contract_claim', {'contract': c['id']}, now, 'contracts')
        car = f['market']['caravan']
        if car:
            for i, c in enumerate(car['crates']):
                if not c['done'] and self.stock(c['item']) >= c['qty']:
                    self.cmd('caravan_fill', {'crate': i}, now, 'caravan')
                    if not f['market']['caravan']:
                        break

    def orders(self, t):
        f = self.f
        day = self.day_of(t)
        if self.orders_today[0] != day:
            self.orders_today = (day, 0)
        per_session = max(1, round(self.p['orders'] / len(self.sessions)))
        done_here = 0
        for p in range(4):
            now = t + 20 * p
            if p:
                self.settle(now)
            changed = False
            for o in sorted(f['orders'], key=lambda o: -o['coins']):
                fillable = all(self.stock(k) >= q for k, q in o['needs'].items())
                if fillable and done_here < per_session and self.orders_today[1] < self.p['orders']:
                    if self.cmd('order', {'order': o['id']}, now, 'orders'):
                        done_here += 1
                        self.orders_today = (day, self.orders_today[1] + 1)
                        changed = True
                elif not fillable and o['skip_at'] <= now and done_here < per_session:
                    if self.cmd('skip_order', {'order': o['id']}, now, 'orders'):
                        changed = True
            if not changed:
                break

    # ---------------------------------------------------------------- selling, planting
    def sell(self, now, dem):
        for item, q in sorted(self.f['inventory'].items()):
            extra = q - max(KEEP, dem.get(item, 0))
            while extra > 0:
                part = min(extra, 999)
                self.cmd('sell', {'item': item, 'qty': part}, now, 'barn_bonus')
                extra -= part

    def plant_plan(self, now, dem):
        f = self.f
        lv = self.lv()
        empty = sorted((o for o in f['objects'] if o['type'] == 'plot' and not o.get('crop')),
                       key=lambda o: (o['y'], o['x'], o['id']))
        left, coins = len(empty), f['coins']
        plan = []

        def take(crop, n):
            nonlocal left, coins
            n = min(n, left, coins // crop['cost'])
            if n > 0:
                plan.append((crop['id'], n))
                left -= n
                coins -= n * crop['cost']

        if not left:
            return empty, plan
        day_end = T_BASE + (self.day_of(now) + 1) * DAY
        for c in f['market']['contracts']['items']:
            if not c['claimed'] and c['kind'] == 'harvest' and C.CROPS[c['item']]['level'] <= lv:
                crop = C.CROPS[c['item']]
                if now + crop['seconds'] <= day_end and self.next_session(now + crop['seconds'], True) < day_end:
                    remaining = c['goal'] - M.contract_progress(f, c) - self.growing(crop['id'])
                    if remaining > 0:
                        take(crop, math.ceil(remaining / crop['yield_qty']))
        cap = int(0.6 * len(empty))
        used = 0
        for item, q in sorted(dem.items(), key=lambda kv: -kv[1] * price(kv[0])):
            if item in C.CROPS and C.CROPS[item]['level'] <= lv and used < cap:
                crop = C.CROPS[item]
                deficit = q - self.stock(item) - self.growing(item)
                if deficit > 0 and self.eff(crop['seconds'], now) <= 2 * self.gap(now):
                    before = left
                    take(crop, min(math.ceil(deficit / crop['yield_qty']), cap - used))
                    used += before - left
        for crop in self.crop_rank(now):
            if not left:
                break
            take(crop, left)
        return empty, plan

    def growing(self, crop_id):
        return sum(o['crop']['yield_qty'] for o in self.f['objects'] if o['type'] == 'plot' and o.get('crop')
                   and o['crop']['id'] == crop_id)

    def plant(self, now, dem):
        empty, plan = self.plant_plan(now, dem)
        if not plan:
            return
        if len(plan) == 1 and plan[0][1] == len(empty):
            self.cmd('plant_many', {'crop': plan[0][0], 'area': None}, now, 'crops')
            return
        i = 0
        for crop, n in plan:
            for o in empty[i:i + n]:
                self.cmd('plant', {'object': o['id'], 'crop': crop, 'revision': o['revision']}, now, 'crops')
            i += n

    # ---------------------------------------------------------------- investments
    def cells(self):
        used = set()
        for o in self.f['objects']:
            used |= D.object_cells(o)
        return used

    def spot(self, w, h, plot):
        size, used = self.f['size'], self.cells()
        ys = range(size - h, -1, -1) if plot else range(0, size - h + 1)
        xs = list(range(size - w, -1, -1) if plot else range(0, size - w + 1))
        for y in ys:
            for x in xs:
                if not any((a, b) in used for a in range(x, x + w) for b in range(y, y + h)):
                    return x, y
        return None

    def invest(self, now):
        f = self.f
        for _ in range(60):
            lv = self.lv()
            dem = {}
            _, plan = self.plant_plan(now, dem)
            reserve = sum(C.CROPS[c]['cost'] * n for c, n in plan)
            empties = sum(1 for o in f['objects'] if o['type'] == 'plot' and not o.get('crop'))
            if plan and sum(n for _, n in plan) < empties:
                reserve = f['coins']                      # cannot even afford seeds
            budget = f['coins'] - reserve
            step = C.land_step(f['size'])
            if step and lv >= step['level'] and budget >= step['cost']:
                if self.cmd('expand', {}, now, 'capex:land'):
                    self.cache.clear()
                    continue
            if lv >= C.FIELD_MIN_LEVEL and self.buy_fields(now, budget):
                continue
            if self.buy_one(now, budget, lv):
                continue
            break

    def buy_one(self, now, budget, lv):
        f = self.f
        reach = self.reach()
        cands = []     # (payback_days, cost, action)
        # beds
        plots = sum(1 for o in f['objects'] if o['type'] == 'plot')
        if plots < C.plot_limit(f['size']) and len(f['objects']) < C.object_limit(f['size']):
            best = self.crop_rank(now)[0]
            unit = 35 + best['cost']
            gain = self.bed_daily(now)
            if gain > 0 and budget >= unit:
                cands.append((unit / gain, unit, ('plot', None)))
        # buildings (+ animal)
        for typ, b in C.BUILDINGS.items():
            if b['decor'] or b.get('secret') or b['level'] > lv or typ in ('house', 'barn'):
                continue
            copies = sum(1 for o in f['objects'] if o['type'] == typ)
            if copies >= MAX_COPIES or len(f['objects']) >= C.object_limit(f['size']):
                continue
            factor = FRICTION * (1.0 if copies == 0 else 0.8)
            if typ in X.WORKSHOP_TYPES:
                gain, cost = self.workshop_daily(typ, 1, reach) * factor, b['cost']
            elif typ in ANIMAL_BY_HOUSE and ANIMAL_BY_HOUSE[typ]['level'] <= lv:
                a = ANIMAL_BY_HOUSE[typ]
                gain, cost = self.animal_daily(a, 1, reach) * factor, b['cost'] + a['cost']
            else:
                continue
            if gain > 0 and budget >= cost and self.spot(b['w'], b['h'], False):
                cands.append((cost / gain, cost, ('build', typ)))
        # animals for empty houses
        for o in f['objects']:
            a = ANIMAL_BY_HOUSE.get(o['type'])
            if a and not o.get('animal') and a['level'] <= lv and budget >= a['cost']:
                gain = self.animal_daily(a, o.get('level', 1), reach) * FRICTION
                if gain > 0:
                    cands.append((a['cost'] / gain, a['cost'], ('animal', o)))
        # upgrades
        for o in f['objects']:
            kind = C.upgrade_kind(o['type'])
            cur = o.get('level', 1)
            if not kind or cur >= C.MAX_BUILDING_LEVEL:
                continue
            cost = C.upgrade_cost(o['type'], cur + 1)
            if lv < cost['level'] or budget < cost['coins'] or any(self.stock(k) < q for k, q in cost['items'].items()):
                continue
            total = cost['coins'] + vol(cost['items'])
            if kind == 'workshop':
                gain = (self.workshop_daily(o['type'], cur + 1, reach) - self.workshop_daily(o['type'], cur, reach)) * FRICTION
            elif kind == 'animals':
                a = ANIMAL_BY_HOUSE.get(o['type'])
                gain = (self.animal_daily(a, cur + 1, reach) - self.animal_daily(a, cur, reach)) * FRICTION if a else 0
            else:
                recent = [c for d, c in self.sold_log if d >= self.day_of(now) - 5]
                gain = (C.BARN_SELL_BONUS[cur + 1] - C.BARN_SELL_BONUS[cur]) / 100 * sum(recent) / 5
            if gain > 0:
                cands.append((total / gain, cost['coins'], ('upgrade', o)))
        # forest guides: cheap, permanent
        for h in GUIDES:
            if h['id'] not in f['helpers'] and lv >= h['level'] and budget >= h['cost']:
                cands.append((6.0, h['cost'], ('guide', h['id'])))
        cands.sort(key=lambda x: x[0])
        for payback, cost, (kind, arg) in cands:
            if payback > 60:
                break
            if kind == 'plot':
                best = self.crop_rank(now)[0]
                n = max(1, min(C.plot_limit(f['size']) - plots, int(budget // (35 + best['cost'])), 12))
                bought = 0
                for _ in range(n):
                    sp = self.spot(1, 1, True)
                    if sp is None or not self.cmd('build', {'type': 'plot', 'x': sp[0], 'y': sp[1]}, now, 'capex:plot'):
                        break
                    bought += 1
                if bought:
                    return True
            elif kind == 'build':
                b = C.BUILDINGS[arg]
                sp = self.spot(b['w'], b['h'], False)
                if sp and self.cmd('build', {'type': arg, 'x': sp[0], 'y': sp[1]}, now, 'capex:building'):
                    new = f['objects'][-1]
                    if arg in ANIMAL_BY_HOUSE:
                        self.cmd('buy_animal', {'object': new['id'], 'animal': ANIMAL_BY_HOUSE[arg]['id']}, now, 'capex:animal')
                    self.cache.clear()
                    return True
            elif kind == 'animal':
                if self.cmd('buy_animal', {'object': arg['id'], 'animal': ANIMAL_BY_HOUSE[arg['type']]['id']}, now, 'capex:animal'):
                    self.cache.clear()
                    return True
            elif kind == 'upgrade':
                if self.cmd('upgrade', {'object': arg['id'], 'revision': arg['revision']}, now, 'capex:upgrade'):
                    self.cache.clear()
                    return True
            elif kind == 'guide':
                if self.cmd('hire_helper', {'helper': arg}, now, 'capex:guide'):
                    return True
        return False

    # ---------------------------------------------------------------- stage 14 sinks
    def pay_debt(self, now):
        if E.state(self.f)['debt'] > 0 and self.f['coins'] - self.f['starter_credit'] > 0:
            self.cmd('pay_upkeep', {}, now, 'sink:upkeep')

    def spend(self, now):
        """Surplus policy: > 2 * INCOME_REF stays nowhere. 50% to the fund until tier 5 of the season, then <= 30% to decor."""
        f, lv = self.f, self.lv()
        self.pay_debt(now)
        self.upgrade_machines(now)
        if lv < C.FUND_LEVEL:
            return
        surplus = f['coins'] - f['starter_credit'] - 2 * C.income_ref(lv)
        if surplus <= 0:
            return
        e = E.state(f)
        rec = e['seasons'].get(str(E.season_of(now)))
        ref = rec['ref'] if rec else C.income_ref(lv)
        top = E.thresholds(ref)[-1]
        personal = rec['personal'] if rec else 0
        if personal < top:
            amount = min(surplus // 2, top - personal)
            if amount >= 1 and self.cmd('fund_contribute', {'coins': amount, 'items': {}}, now, 'sink:fund'):
                return
        budget = surplus * 30 // 100
        while True:
            shop = [d for d in PAID_DECOR if d['id'] not in self.decor_owned and C.BUILDINGS[d['id']]['level'] <= lv and d['cost'] <= budget]
            for d in sorted(shop, key=lambda d: -d['cost']):
                sp = self.spot(d['w'], d['h'], False)
                if sp and len(f['objects']) < C.object_limit(f['size']) and self.cmd('build', {'type': d['id'], 'x': sp[0], 'y': sp[1]}, now, 'sink:decor'):
                    self.decor_owned.add(d['id'])
                    budget -= d['cost']
                    break
            else:
                return

    # ---------------------------------------------------------------- stage 15: fields
    def owned_machines(self):
        return FD.machines_of(self.f)

    def buy_fields(self, now, budget):
        """Cheapest affordable purchase first: a field step (price + 1 day of INCOME_REF in reserve), then tier-1 machines."""
        f, lv = self.f, self.lv()
        if not self.fields:
            return False
        reserve = C.income_ref(lv)
        owned = {x['step'] for x in FD.fields_of(f)}
        options = [('buy_field', {'step': st['step']}, st['cost'], 'capex:fields') for st in C.FIELD_STEPS
                   if st['step'] not in owned and lv >= st['level']]
        if owned or options:
            options += [('buy_machine', {'machine': k}, m['costs'][0], 'capex:machines') for k, m in C.FIELD_MACHINES.items()
                        if k not in self.owned_machines() and lv >= m['levels'][0]]
        for kind, data, cost, tag in sorted(options, key=lambda o: o[2]):
            if budget >= cost + reserve and self.cmd(kind, data, now, tag):
                self.cache.clear()
                return True
        return False

    def upgrade_machines(self, now):
        f, lv = self.f, self.lv()
        if not FD.fields_of(f):
            return
        for k, m in sorted(C.FIELD_MACHINES.items(), key=lambda kv: kv[1]['costs'][-1]):
            own = self.owned_machines().get(k)
            if own and own['tier'] < 3 and lv >= m['levels'][own['tier']] \
                    and f['coins'] - f['starter_credit'] >= m['costs'][own['tier']] + 2 * C.income_ref(lv):
                self.cmd('upgrade_machine', {'machine': k}, now, 'capex:machines')

    def field_crop(self, now, ha, coins):
        lv = self.lv()
        best = None
        for c in C.CROPS.values():
            if c['field'] and c['level'] <= lv and (c['cost'] * C.FIELD_SEED_MULT + C.FIELD_FUEL) * ha <= coins:
                value = (c['yield_qty'] * C.FIELD_YIELD_MULT * c['price'] - c['cost'] * C.FIELD_SEED_MULT) * ha
                rate = value / self.eff(max(c['seconds'], C.FIELD_MIN_GROW), now)
                if best is None or rate > best[0]:
                    best = (rate, c['id'])
        return best[1] if best else None

    def fields_visit(self, t):
        """Every field gets its next operation. Returns the time at which the visit ended (manual driving takes time)."""
        f, skilled = self.f, self.p.get('skilled', False)
        for index in range(len(FD.fields_of(f))):
            for _ in range(3 if skilled else 1):
                fld = f['fields'][index]
                op = {'ripe': 'harvest', 'ready': 'sow', 'wild': 'cultivate'}.get(fld['state'])
                if fld['run'] is not None or op is None or FD.machines_of(f).get(C.FIELD_OPS[op]['machine']) is None:
                    break
                crop = self.field_crop(t, fld['ha'], f['coins'] - f['starter_credit']) if op == 'sow' else ''
                if op == 'sow' and not crop:
                    break
                c0 = f['coins']
                if not self.cmd('field_start', {'field': fld['id'], 'op': op, 'crop': crop, 'revision': fld['revision']}, t, 'fields'):
                    break
                fuel = C.FIELD_FUEL * fld['ha']
                self.fs['fuel'] += fuel
                self.fs['seeds'] += c0 - f['coins'] - fuel
                run = fld['run']
                if skilled:
                    path = FD.reference_path(fld, run)
                    t += math.ceil(len(path) * C.FIELD_STEP_CS / 100) + 2
                    self.settle(t)
                    self.fs['ops_manual'] += 1
                    self.fs_q[op].append(FD.quality(FD.simulate(fld, run, path)))
                    self.cmd('field_finish', {'field': fld['id'], 'run': run['id'], 'path': path}, t, 'fields')
                else:
                    self.fs['ops_auto'] += 1
                    self.cmd('field_finish', {'field': fld['id'], 'run': run['id'], 'path': None}, t + 1, 'fields')
                    break
        return t

    # ---------------------------------------------------------------- grind loop
    def grind(self, t):
        f = self.f
        now, end = t + 90, t + 600
        fast = [c for c in C.CROPS.values() if c['level'] <= self.lv() and c['seconds'] < C.CROP_CLASS_SLOW]
        gcrop = max(fast, key=lambda c: ((c['xp'] + 0.25 * (c['yield_qty'] * price(c['id']) - c['cost'])) / c['seconds'], c['id']))
        step = max(31, D.duration(gcrop['seconds'], 1) + 1)
        mills = self.objects(lambda o: o['type'] == 'mill')
        while now < end:
            self.settle(now)
            self.cmd('collect_group', {'group': 'plots', 'area': None}, now, 'crops')
            self.cmd('collect_group', {'group': 'workshops', 'area': None}, now, 'workshops')
            if now + step < end:        # the last cycle leaves the beds empty for the normal plan
                self.cmd('plant_many', {'crop': gcrop['id'], 'area': None}, now, 'crops')
            for m in mills:
                lvl = C.RECIPE_SPEED[C.effective_level(m.get('level'))]
                recs = [r for r in C.RECIPES.values() if r['building'] == 'mill' and r['level'] <= self.lv()
                        and all(self.stock(k) >= q for k, q in r['inputs'].items())]
                if recs and len(m['jobs']) < C.queue_slots(m.get('level')):
                    r = max(recs, key=lambda r: (recipe_score(r), r['id']))
                    self.cmd('queue', {'object': m['id'], 'recipe': r['id']}, now, 'workshops')
            now += step

    # ---------------------------------------------------------------- session / run
    def settle(self, now):
        """The real settle; whatever it materialises (autopilot / expired field runs; helpers are not modelled) is field work."""
        f = self.f
        c0, x0, w0, lv0 = f['coins'], f['xp'], self.inv_value(), C.level(f['xp'])
        m0 = dict(P.progress(f)['total'])
        X.settle(f, now)
        dc, dx = f['coins'] - c0, f['xp'] - x0
        dw = dc + self.inv_value() - w0
        band = band_of(lv0)
        if dw:
            self.income[band]['fields'] += dw
        if dc > 0:
            self.gross[band]['fields'] += dc
        if dx:
            self.xp_src[band]['fields'] += dx
        for k, v in P.progress(f)['total'].items():
            if v != m0[k]:
                self.mech[band][k] += v - m0[k]
        lv = C.level(f['xp'])
        while self.maxlv < lv:
            self.maxlv += 1
            self.level_t[self.maxlv] = now

    def session(self, t):
        f = self.f
        self.cache.clear()
        self.settle(t)
        self.cmd('collect_group', {'group': 'animals', 'area': None}, t, 'animals')
        self.cmd('collect_group', {'group': 'workshops', 'area': None}, t, 'workshops')
        self.cmd('collect_group', {'group': 'plots', 'area': None}, t, 'crops')
        self.rewards(t)
        self.pay_debt(t)
        field_end = self.fields_visit(t)
        self.orders(field_end)
        if self.p['grind']:
            self.grind(t)
        end = max(t + 600 if self.p['grind'] else t + 90, field_end + 90)
        dem = self.produce(end)
        self.trips(end)
        self.rewards(end)
        self.sell(end, dem)
        self.pay_debt(end)
        self.invest(end)
        dem = self.demand(end)
        self.plant(end, dem)
        self.spend(end)
        self.end_t = end

    def run(self):
        d = 0
        while d < self.days and self.maxlv < LEVEL_MAX:
            for s in self.sessions:
                self.session(T_BASE + d * DAY + s)
                if self.maxlv >= LEVEL_MAX:
                    break
            self.end_coins[d] = self.f['coins']
            self.fs_ha[d] = sum(x['ha'] for x in FD.fields_of(self.f))
            d += 1
        self.days_run = d
        return self


# -------------------------------------------------------------------- reporting
def fmt_days(sim, lv):
    t = sim.level_t.get(lv)
    return f'{(t - sim.t0) / DAY:6.1f}' if t is not None else '   >' + str(sim.days_run)


def slowest(sim, band):
    """Longest time (days) spent on a single level of the band, over completed level-ups."""
    spans = [(sim.level_t[lv + 1] - sim.level_t[lv]) / DAY for lv in range(band[0], band[1] + 1)
             if lv in sim.level_t and lv + 1 in sim.level_t]
    return max(spans, default=0.0)


def report(sim):
    f = sim.f
    out = []
    out.append(f'=== {sim.name}: {sim.p["label"]}')
    out.append(f'simulated {sim.days_run} days, level {sim.maxlv}, xp {f["xp"]}, coins {f["coins"]}, '
               f'land {f["size"]}x{f["size"]}, beds {sum(o["type"] == "plot" for o in f["objects"])}, '
               f'objects {len(f["objects"])}, orders {f["stats"]["orders"]}, commands {sim.n}')
    out.append('days to level:  ' + '  '.join(f'L{lv}={fmt_days(sim, lv).strip()}' for lv in MILESTONES))
    end_t = sim.t0 + sim.days_run * DAY
    out.append('')
    out.append(f'{"band":>7} {"days":>6} {"net coins/day":>14} {"xp/day":>9} {"capex/day":>10} {"coins at end":>13}  top coin sources (share)')
    srcs_all, xp_all = Counter(), Counter()
    for b in BANDS:
        start = sim.level_t.get(b[0])
        if start is None:
            continue
        nxt = sim.level_t.get(b[1] + 1)
        stop = nxt if nxt is not None else end_t
        days = max((stop - start) / DAY, 1e-9)
        inc, xps, cap = sim.income[b], sim.xp_src[b], sim.capex[b]
        srcs_all.update(inc)
        xp_all.update(xps)
        net = sum(inc.values())
        tot_pos = sum(v for v in inc.values() if v > 0) or 1
        top = ', '.join(f'{k} {100 * v / tot_pos:.0f}%' for k, v in inc.most_common(4) if v > 0)
        coins_end = sim.coins_at(nxt) if nxt is not None else f['coins']
        out.append(f'{b[0]:>3}-{b[1]:<3} {days:6.1f} {net / days:14.0f} {sum(xps.values()) / days:9.0f} '
                   f'{sum(cap.values()) / days:10.0f} {coins_end:13}  {top}')
    out.append('')
    out.append('SINKS per band (coins/day; share of net coin income): upkeep + fund + decor [+ capex]; coins on hand at band end (days of income)')
    out.append(f'{"band":>7} {"net/day":>9} {"upkeep":>8} {"fund":>8} {"decor":>8} {"capex":>8} {"sinks%":>7} {"+capex%":>8} {"coins end":>11} {"= days":>7}')
    tot = Counter()
    for b in BANDS:
        start = sim.level_t.get(b[0])
        if start is None:
            continue
        nxt = sim.level_t.get(b[1] + 1)
        days = max(((nxt if nxt is not None else end_t) - start) / DAY, 1e-9)
        net = sum(sim.income[b].values()) / days
        sk, cap = sim.sinks[b], sum(sim.capex[b].values())
        tot.update({k: v for k, v in sk.items()})
        tot['capex'] += cap
        tot['net'] += net * days
        sinks = (sk['upkeep'] + sk['fund'] + sk['decor']) / days
        coins_end = sim.coins_at(nxt) if nxt is not None else f['coins']
        out.append(f'{b[0]:>3}-{b[1]:<3} {net:9.0f} {sk["upkeep"] / days:8.0f} {sk["fund"] / days:8.0f} {sk["decor"] / days:8.0f} {cap / days:8.0f} '
                   f'{100 * sinks / max(net, 1):6.0f}% {100 * (sinks + cap / days) / max(net, 1):7.0f}% {coins_end:11} {coins_end / max(net, 1):7.1f}')
    net_all = tot['net'] or 1
    out.append(f'overall: upkeep {tot["upkeep"]} ({100 * tot["upkeep"] / net_all:.0f}% of net income), fund {tot["fund"]} ({100 * tot["fund"] / net_all:.0f}%), '
               f'decor {tot["decor"]} ({100 * tot["decor"] / net_all:.0f}%), capex {tot["capex"]} ({100 * tot["capex"] / net_all:.0f}%); '
               f'decor owned {len(sim.decor_owned)}/{len(PAID_DECOR)}; upkeep debt {E.state(f)["debt"]}')
    pos = sum(v for v in srcs_all.values() if v > 0) or 1
    out.append('')
    out.append('income sources overall (value added): ' + ', '.join(f'{k} {100 * v / pos:.0f}%' for k, v in srcs_all.most_common(8) if v > 0))
    xt = sum(xp_all.values()) or 1
    out.append('xp sources overall: ' + ', '.join(f'{k} {100 * v / xt:.0f}%' for k, v in xp_all.most_common(8)))
    mech = Counter()
    for b in BANDS:
        mech.update(sim.mech[b])
    out.append(f'r9 mechanisms: M1 dew +{mech["m1"]} XP ({100 * mech["m1"] / xt:.1f}% of XP), M2 vigour +{mech["m2"]} XP '
               f'({100 * mech["m2"] / xt:.1f}%), M3 fatigue lost {mech["m3"]} XP ({100 * mech["m3"] / (xt + mech["m3"]):.1f}% of would-be XP)')
    out.append('  per band (M1 / M2 / M3-lost XP): ' + '; '.join(f'L{b[0]}-{b[1]} {sim.mech[b]["m1"]}/{sim.mech[b]["m2"]}/{sim.mech[b]["m3"]}'
                                                         for b in BANDS if sim.level_t.get(b[0]) is not None))
    out.append('max days on one level in band: ' + ', '.join(f'L{b[0]}-{b[1]} {slowest(sim, b):.1f}' for b in BANDS if sim.level_t.get(b[0]) is not None))
    out.extend(field_report(sim, srcs_all, xp_all, tot))
    if sim.debug:
        out.append('refused commands: ' + ', '.join(f'{k[0]}/{k[1]}={v}' for k, v in sim.err.most_common(12)))
    return '\n'.join(out)


def field_report(sim, srcs_all, xp_all, sink_tot):
    """Stage 15: what the fields earned (value of the crops harvested minus fuel and seeds), what they cost (upkeep) and what they bought."""
    days_ha = sorted(sim.fs_ha.items())
    first = next((d for d, ha in days_ha if ha > 0), None)
    if first is None:
        return ['fields: none bought (level < %d or no money)' % C.FIELD_MIN_LEVEL]
    ha_days = sum(ha for d, ha in days_ha)
    upkeep = C.FIELD_UPKEEP * ha_days
    net = srcs_all.get('fields', 0)                    # value added: crops harvested at shop price - fuel - seeds
    fuel, seeds = sim.fs['fuel'], sim.fs['seeds']
    span = max(1, sim.days_run - first)
    cap = Counter()
    for b in BANDS:
        cap.update(sim.capex[b])
    xt = sum(xp_all.values()) or 1
    pos = sum(v for v in srcs_all.values() if v > 0) or 1
    field_xp = xp_all.get('fields', 0)
    out = ['', f'FIELDS (stage 15): first field on day {first}, {days_ha[-1][1]} ha at the end, machines '
           + ', '.join(f'{k} t{v["tier"]}' for k, v in sorted(FD.machines_of(sim.f).items())) + ';'
           f' operations {sim.fs["ops_auto"]} autopilot + {sim.fs["ops_manual"]} manual']
    out.append(f'  crops harvested (shop value) {net + fuel + seeds}, fuel {fuel}, seeds {seeds} -> field income {net} '
               f'({net / span:.0f}/day); upkeep {C.FIELD_UPKEEP}/ha/day x {ha_days} ha-days = {upkeep} ({upkeep / span:.0f}/day assessed)')
    out.append(f'  NET after upkeep {net - upkeep} ({(net - upkeep) / span:.0f}/day since the first field); share of positive income {100 * net / pos:.1f}%, '
               f'of XP {100 * field_xp / xt:.1f}%; capex fields {cap["capex:fields"]}, machines {cap["capex:machines"]}'
               + (f'; payback {(cap["capex:fields"] + cap["capex:machines"]) / max(1, (net - upkeep) / span):.0f} days' if net > upkeep else '; not paid back'))
    if sim.fs_q:
        out.append('  manual q (permille, achieved by the server replay): ' + ', '.join(f'{op} {sum(v) / len(v):.0f} (n={len(v)})' for op, v in sorted(sim.fs_q.items())))
    sinks = sink_tot['upkeep'] + sink_tot['fund'] + sink_tot['decor']
    out.append(f'  sinks share of net income (all sinks, incl. field upkeep): {100 * sinks / max(1, sink_tot["net"]):.0f}%'
               f' (field upkeep alone {100 * upkeep / max(1, sink_tot["net"]):.0f}%)')
    return out


def coins_at(self, t):
    d = int((t - self.t0) // DAY)
    return self.end_coins.get(d, self.f['coins'])


Sim.coins_at = coins_at


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--days', type=int, default=25)
    ap.add_argument('--profile', default='all', choices=['all', *PROFILES])
    ap.add_argument('--debug', action='store_true')
    ap.add_argument('--no-fields', action='store_true', help='baseline: the player never buys a field')
    args = ap.parse_args()
    print(f'catalog {C.VERSION}; days={args.days}')
    for name in (PROFILES if args.profile == 'all' else [args.profile]):
        t = time.time()
        sim = Sim(name, args.days, args.debug, not args.no_fields).run()
        print(report(sim))
        print(f'(simulated in {time.time() - t:.1f}s)\n')


if __name__ == '__main__':
    main()
