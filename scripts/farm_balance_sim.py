#!/usr/bin/env python
"""Deterministic progression simulator for the farm (qw_farm). Usage:

    python scripts/farm_balance_sim.py [--days 150] [--profile all|active|online|casual|grind|skilled] [--helpers] [--craft-masters 0..4] [--craft-capacity] [--visit-queues] [--debug] [--no-fields]
           [--field-mode auto|reference|manual|max] [--field-q 1100] [--field-hits 1] [--field-elapsed-k 200] [--field-manual-share 100] [--field-payback]
           [--sim-field-upkeep N] [--sim-field-steps a,b,c,d,e] [--sim-field-machines a,b,c,d] [--sim-field-widths w2,w3] [--sim-field-fuel N] [--sim-land size:cost,...]
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
  * Session order: settle and mow ready meadow patches -> collect (collect_group animals/workshops/plots, forest baskets) -> quests, daily contracts, caravan
    crates -> orders (deliver what the stock covers, skip what it cannot; up to 4 passes, 20 s apart, capped by the
    profile's orders/day) -> production (feed_all, workshop queues) -> forest trips -> sell the surplus -> invest
    -> plant.  Free player time is not otherwise limited (tap budgets are not modelled).
  * Planting: 1) a crop for an open "harvest" daily contract if it can ripen the same Moscow day, 2) crops that the
    planned production needs (deficit of stock + growing), at most 60% of the empty beds, 3) the rest with the best crop by
    (XP + 0.25 * profit) per *effective* hour, where effective time runs to the first session after the crop is ripe.
  * Production: for every workshop the greedy queue picks, per free slot, the recipe with the best value
    (sale value of outputs - inputs + XP, 1 XP = 1 coin) whose inputs are in stock, filling all available slots even
    when the queue lasts beyond the next visit (--visit-queues restores the old time-limited policy); goods that a
    planned recipe/animal needs but the stock lacks get a bonus (simple demand propagation, 3 levels).
  * Investment (greedy by payback = cost / estimated daily gain, 1 XP = 1 coin): land at once when the level allows,
    beds, workshops and animal houses (+ animal), building upgrades 1->3 (when the upgrade goods are in stock), barn
    upgrade, forest guides. Beds/trees fill from the far edge; buildings fill from the opposite edge. Tree valuation
    deducts the marginal daily land rent.  Coins reserved: seeds for the empty beds.
  * Stock policy: sell everything above max(4, planned need); the 4 kept units serve orders/crates.
  * Sinks (stage 14, upkeep from L10 is charged by the real ``economy.bill`` inside ``domain.apply``): ``pay_upkeep`` whenever there is
    a debt (start of a session and after selling); the surplus above 2 * INCOME_REF(level) goes 50% to the village fund (real
    ``fund_contribute``, coins) until the 5th personal tier of the season is full, then up to 30% of the surplus buys the most
    expensive paid decor (including R16 decor/trophies) that is open and not yet owned.  The shared village counter is not simulated (one farm).
  * Fields (stage 15, real ``qw_farm.fields`` through ``domain.apply``): a field step is bought at its price + one day of INCOME_REF
    in reserve, then the four tier-1 machines (cheapest first); width upgrades come from the surplus. EVERY visit each field gets
    up to four sequential operations (spray when it pays -> harvest -> cultivate -> sow, best crop by value per effective hour and by the growth of
    this field's cultivation): ``active``/``casual``/``online``/``grind`` use the autopilot by default (wait until ready after 90 s * ha / width before
    starting the next operation), ``skilled`` drives the operations by hand in one visit with the reference driver ``fields.reference_path``
    (the real server replay; the achieved average is printed); ``--field-mode`` replaces either choice for any profile.
    Field work finished by ``settle`` (autopilot, expiry) is booked to the ``fields`` source too.
    E27 (rules=3 economy, see docs/tasks/FARM_ECONOMY_SOFTENING.md): ``--field-mode`` chooses who drives the machines.  ``auto`` = autopilot
    (q 0.90, growth x1.05); ``reference`` = the real server replay of ``fields.reference_path``; ``manual`` = an average realistic player: raw
    quality ``--field-q`` (default 1.10) damaged by ``--field-hits`` bumps per operation (-3 condition = -12 permille and 15 coins each), the
    run lasts ``--field-elapsed-k`` % of the autopilot time A (default 200 = inside the 2.5 A where the bonus is whole; 400 shows the melt),
    the bonus over 0.90 melts exactly as in ``fields._finish``; ``max`` = a perfect 1.25 run without bumps at 1 A.  The manual run is closed
    through the real ``fields.complete`` (the path is not replayed: the quality is an input of the model, not an output).  With a sprayer a
    ripe field is sprayed first whenever the expected extra yield is worth more than the fuel (+2.5 % at the autopilot 0.90, up to +20 %).
    ``--field-payback`` skips the whole-farm run and measures every FIELD_STEP (plus the machines) in isolation per profile and mode.
    ``--sim-field-*`` / ``--sim-land`` change the numbers of this process only (restored afterwards; the game catalog is untouched).
  * Helpers (--helpers): hire the first available master, animal keeper and harvester, then pay the largest unlocked
    8-hour shift at visits only when the previous one ended. The real scheduler enforces 30-second intervals, quotas,
    remembered recipes, available feed, collection and refeeding; shifts never renew between visits. Reserve inputs for
    the covered part of the next visit gap, bounded by shared worker quota. No helper replants crops.
  * NOT modelled: tractor/combine/robot (bulk commands already available), neighbours/helps/gifts/market stall
    (quests q4/q9), secrets/reward decor, quests q12-q14.
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
from qw_farm import meadow as MD           # noqa: E402

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
FIELD_MODES = ('auto', 'reference', 'manual', 'max')
# Player models for the fields (rules=3): raw quality (permille before bumps and melt), bumps per operation, run time as % of the autopilot time A.
FIELD_MODEL = {'manual': dict(q=1100, hits=1, elapsed_k=200), 'max': dict(q=1250, hits=0, elapsed_k=100)}
ANIMAL_BY_HOUSE = {a['building']: a for a in C.ANIMALS.values()}
ORCHARD_FRUIT = {t['fruit'] for t in C.TREES.values()}
FRUIT_RECIPES = frozenset(r['id'] for r in C.RECIPES.values() if r['id'] in C.ORCHARD_RECIPE_IDS or set(r['inputs']) & ORCHARD_FRUIT)
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


def fill(recipes, slots, mult, gap, full=False):
    """Greedy queue: full queues may outlive a visit; value is discounted by complete visit gaps until collection."""
    total, chosen, remaining = 0.0, [], gap
    for _ in range(slots):
        best = None
        for r in recipes:
            sec = D.duration(r['seconds'] * mult, 1)
            if (full or sec <= remaining) and (best is None or recipe_score(r) > best[0]):
                best = (recipe_score(r), r, sec)
        if best is None:
            break
        total += best[0]
        remaining -= best[2]
        chosen.append(best[1])
    if full and chosen:
        total /= max(1, math.ceil((gap - remaining) / gap))
    if not chosen and recipes:
        r = min(recipes, key=lambda x: x['seconds'])
        sec = D.duration(r['seconds'] * mult, 1)
        total, chosen = recipe_score(r) / math.ceil(sec / gap), [r]
    return total, chosen


def manual_field_quality(q_raw, ha, width, hits, elapsed_k):
    """Quality (permille) of a manual rules=3 run: bumps first, then the bonus over the autopilot melts with the run time (``fields._finish``)."""
    q = FD.condition_quality(q_raw, 100 - hits * C.FIELD_HIT_DAMAGE)
    a = FD.auto_seconds(ha, width)
    full, zero = a * C.FIELD_FULL_K // 100, a * C.FIELD_ZERO_K // 100
    elapsed = a * elapsed_k // 100
    keep = 1000 if elapsed <= full else 0 if elapsed >= zero else (zero - elapsed) * 1000 // (zero - full)
    bonus = q - C.Q_AUTO_FULL
    return C.Q_AUTO_FULL + bonus * keep // 1000 if bonus > 0 else q


class Sim:
    def __init__(self, name, days, debug=False, fields=True, orchard=True, helpers=False, full_queues=True,
                 craft_masters=None, demand_actions_override=None, field_mode=None, field_q=None, field_hits=None,
                 field_elapsed_k=None, field_share=None):
        self.name, self.days, self.debug, self.fields, self.orchard = name, days, debug, fields, orchard
        self.helpers, self.full_queues = helpers, full_queues
        self.craft_masters = (1 if helpers else 0) if craft_masters is None else craft_masters
        self.demand_actions_override = demand_actions_override
        self.field_mode = field_mode or ('reference' if PROFILES[name].get('skilled') else 'auto')
        assert self.field_mode in FIELD_MODES, self.field_mode
        model = dict(FIELD_MODEL.get(self.field_mode, {}))
        for key, value in (('q', field_q), ('hits', field_hits), ('elapsed_k', field_elapsed_k)):
            if value is not None:
                model[key] = value
        self.field_model = model
        self.field_share = 100 if field_share is None else field_share      # percent of the operations done by hand in manual/max mode, the rest by autopilot
        self.helper_shifts = Counter()
        self.helper_actions = Counter()
        self.fruit_xp = Counter()             # band -> xp of the recipes that eat orchard fruit or orchard goods (approx.: counted when queued)
        self.trees_bought = Counter()         # species -> trees bought
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
        self.meadow = Counter()                # harvested grass, feeding substitution, and mill-equivalent
        self.meadow_proxy = defaultdict(float) # band -> saved mill time valued at workshop income_ref

    # ---------------------------------------------------------------- plumbing
    def lv(self):
        return C.level(self.f['xp'])

    def inv_value(self):
        return sum(price(k) * q for k, q in self.f['inventory'].items())

    def cmd(self, kind, data, now, tag):
        f = self.f
        if self.helpers:
            self.settle(now)
        c0, x0, w0, lv0 = f['coins'], f['xp'], self.inv_value(), C.level(f['xp'])
        grass0, feed0 = f['inventory'].get('grass', 0), f['inventory'].get('feed', 0)
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
        grass_delta = f['inventory'].get('grass', 0) - grass0
        if kind == 'mow_all' and grass_delta > 0:
            self.meadow['grass_mowed'] += grass_delta
            # One grass substitutes half a feed; each feed is one unit of the mill's 2-for-45s recipe.
            self.meadow['proxy'] += grass_delta * 0.5
            self.meadow_proxy[band] += grass_delta * 0.5
        elif kind == 'feed_all':
            grass_used = max(0, grass0 - f['inventory'].get('grass', 0))
            feed_used = max(0, feed0 - f['inventory'].get('feed', 0))
            if grass_used or feed_used:
                self.meadow['grass_fed'] += grass_used
                self.meadow['feed_from_mill'] += feed_used
                self.meadow['feed_equivalent'] += feed_used + grass_used / 2
                self.meadow['mill_seconds_saved'] += grass_used * 11.25
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
            if data.get('item') == 'grass':
                self.meadow['grass_sold'] += data.get('qty', 0)
                self.meadow['grass_sale_coins'] += dc
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
            self.cache[key] = sum(fill(rec, slots, mult, g, self.full_queues)[0] for g in self.gaps_per_day()) if rec else 0.0
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
            if c['level'] <= lv and not c.get('orchard'):   # fruit grows on trees now (FARM_ORCHARD.md)
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
        workshops = self.objects(lambda o: o['type'] in X.WORKSHOP_TYPES)
        animals = self.objects(lambda o: o.get('animal'))
        demand_actions = (self.demand_actions_override if self.demand_actions_override is not None
                          else self.helper_plan()['actions']) if self.helpers else None
        for o in workshops:
            recipes = self.pick_jobs(o, now, None, reach)
            for r in recipes:
                base.update(r['inputs'])
            if self.helpers and recipes and lv >= 6:
                r = recipes[-1]
                seconds = D.duration(r['seconds'] * C.RECIPE_SPEED[C.effective_level(o.get('level'))], 1)
                batches = min(math.ceil(min(self.gap(now), self.helper_plan()['seconds']) / seconds),
                              demand_actions // max(2, 2 * len(workshops)))
                for k, q in r['inputs'].items():
                    base[k] += q * max(0, batches - len(recipes))
        for o in animals:
            inputs, _, seconds = C.animal_batch(C.ANIMALS[o['animal']], o.get('level'))
            batches = 1
            if self.helpers and lv >= 3:
                batches = max(1, min(math.ceil(min(self.gap(now), self.helper_plan()['seconds']) / seconds),
                                     demand_actions // max(2, 2 * len(animals))))
            for k, q in inputs.items():
                base[k] += q * batches
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
        """Fill every real free slot from stock, or derive an ideal input plan when dem is None."""
        lv = self.lv()
        recs = [r for r in C.RECIPES.values() if r['building'] == obj['type'] and r['level'] <= lv]
        mult = C.RECIPE_SPEED[C.effective_level(obj.get('level'))]
        slots = C.queue_slots(obj.get('level'))
        gap = self.gap(now)
        if dem is None:
            recs = [r for r in recs if set(r['inputs']) <= reach]
            return fill(recs, slots, mult, gap, self.full_queues)[1]
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
                if (not self.full_queues and sec > remaining) or any(stock.get(k, 0) < q for k, q in r['inputs'].items()):
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
                if r['id'] in FRUIT_RECIPES:
                    self.fruit_xp[band_of(self.lv())] += r['xp']
        return dem

    # ---------------------------------------------------------------- forest trips
    def orchard_visit(self, now):
        """Fruit first (own tag, so the orchard is measured on its own), then care: the casual player only collects."""
        f = self.f
        for o in self.objects(lambda o: o['type'] == 'tree'):
            if o['fruit'] and o['fruit']['ready_at'] <= now:
                self.cmd('harvest', {'object': o['id'], 'revision': o['revision']}, now, 'orchard')
        if self.name == 'casual':
            return
        for o in self.objects(lambda o: o['type'] == 'tree'):
            if o['harvests'] >= o.get('prune_at', 7):
                self.cmd('tree_care', {'object': o['id'], 'action': 'prune', 'item': None}, now, 'orchard')
            elif o['fruit'] and o['fruit'].get('pest') and f['inventory'].get('garden_infusion', 0) > 0:
                self.cmd('tree_care', {'object': o['id'], 'action': 'spray', 'item': None}, now, 'orchard')

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
            if item in C.CROPS and C.CROPS[item]['level'] <= lv and used < cap and not C.CROPS[item].get('orchard'):
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
        # orchard (FARM_ORCHARD.md): a sapling pays back by an adult tree's fruit and XP per harvest, after the juvenile wait
        trees = [o for o in f['objects'] if o['type'] == 'tree']
        if self.orchard and len(f['objects']) < C.object_limit(f['size']) and self.spot(1, 1, True):
            for sp, t in C.TREES.items():
                if t['level'] > lv or budget < t['cost']:
                    continue
                value = t['yield_qty'] * price(t['fruit']) + t['xp']
                rate = (value / (self.eff(C.TREE_CYCLE, now) / DAY)
                        - E.tree_rent(f['size'], len(trees) + 1)) * FRICTION
                if rate <= 0:
                    continue
                delay = (t['juvenile'] + 1) * C.TREE_CYCLE / DAY
                cands.append((t['cost'] / rate + delay, t['cost'], ('tree', sp)))
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
            elif kind == 'tree':
                sp = self.spot(1, 1, True)
                if sp and self.cmd('plant_tree', {'species': arg, 'x': sp[0], 'y': sp[1], 'voucher': None}, now, 'capex:orchard'):
                    self.trees_bought[arg] += 1
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
                self.cmd('upgrade_machine', {'machine': k}, now, 'capex:widths')

    def field_crop(self, now, ha, coins, q_cult=None):
        """Best field crop by value per effective hour; growth is shortened/lengthened by the cultivation quality of this field."""
        lv = self.lv()
        grow = FD.growth_permille(C.Q_AUTO if q_cult is None else q_cult) / 1000
        best = None
        for c in C.CROPS.values():
            if c['field'] and c['level'] <= lv and (c['cost'] * C.FIELD_SEED_MULT + C.FIELD_FUEL) * ha <= coins:
                value = (c['yield_qty'] * C.FIELD_YIELD_MULT * c['price'] - c['cost'] * C.FIELD_SEED_MULT) * ha
                rate = value / self.eff(max(c['seconds'], C.FIELD_MIN_GROW) * grow, now)
                if best is None or rate > best[0]:
                    best = (rate, c['id'])
        return best[1] if best else None

    def spray_pays(self, fld, q_spray):
        """Spray only when the expected extra yield is worth more than the fuel (the crop is valued at the shop price)."""
        crop = fld.get('crop')
        if not isinstance(crop, dict) or crop.get('q_spray') or FD.machines_of(self.f).get('sprayer') is None:
            return False
        extra = FD.spray_bonus_permille(q_spray) - 1000
        base = crop['base'] * crop['q_sow'] / 1000 * price(crop['id']) * 0.95    # ~0.95: the harvest quality is below the sowing one on average
        return base * extra / 1000 > C.FIELD_FUEL * fld['ha']

    def finish_field(self, fld, run, t, mode):
        """Close the open run of ``fld`` at ``t`` according to the player model; returns the time the run ended (None: refused)."""
        op, width, ha = run['op'], run['width'], fld['ha']
        if mode in ('manual', 'max') and self.field_share < 100:
            self.fs['shared_ops'] += 1
            k = self.fs['shared_ops']
            if k * self.field_share // 100 == (k - 1) * self.field_share // 100:
                mode = 'auto'
        if mode == 'reference':
            path = FD.reference_path(fld, run)
            t += math.ceil(len(path) * C.FIELD_STEP_CS / 100) + 2
            self.settle(t)
            self.fs['ops_manual'] += 1
            self.fs_q[op].append(FD.quality(FD.simulate(fld, run, path)))
            self.cmd('field_finish', {'field': fld['id'], 'run': run['id'], 'path': path}, t, 'fields')
            return t
        if mode == 'auto':
            self.fs['ops_auto'] += 1
            if not self.cmd('field_finish', {'field': fld['id'], 'run': run['id'], 'path': None}, t + 1, 'fields'):
                return None
            t = fld['run']['done_at']
            self.settle(t)
            return t
        m = self.field_model        # manual / max: the quality is an input of the model, the run is closed by the real fields.complete
        q = manual_field_quality(m['q'], ha, width, m['hits'], m['elapsed_k'])
        t += FD.auto_seconds(ha, width) * m['elapsed_k'] // 100
        self.settle(t)
        hits = m['hits']
        self.settle_source(lambda farm, now: FD.complete(farm, fld, run, q, now, True, condition=100 - hits * C.FIELD_HIT_DAMAGE, hits=hits), t, 'fields')
        self.fs['ops_manual'] += 1
        self.fs['repair'] += hits * C.FIELD_HIT_REPAIR
        self.fs_q[op].append(q)
        return t

    def fields_visit(self, t):
        """Up to four sequential operations per field per visit (spray -> harvest -> cultivate -> sow), including the wait for the autopilot."""
        f, mode = self.f, self.field_mode
        by_hand = mode in ('manual', 'max') and self.field_share >= 50      # the quality the sprayer is expected to reach when deciding whether it pays
        q_spray = (manual_field_quality(self.field_model['q'], 1, 1, self.field_model['hits'], self.field_model['elapsed_k'])
                   if by_hand else C.Q_AUTO_FULL)
        for index in range(len(FD.fields_of(f))):
            for _ in range(4):
                fld = f['fields'][index]
                op = {'ripe': 'harvest', 'ready': 'sow', 'wild': 'cultivate'}.get(fld['state'])
                if op == 'harvest' and mode != 'reference' and self.spray_pays(fld, q_spray):    # the reference driver has no spraying route
                    op = 'spray'
                if fld['run'] is not None or op is None or FD.machines_of(f).get(C.FIELD_OPS[op]['machine']) is None:
                    break
                crop = self.field_crop(t, fld['ha'], f['coins'] - f['starter_credit'], fld['q_cult']) if op == 'sow' else ''
                if op == 'sow' and not crop:
                    break
                c0 = f['coins']
                if not self.cmd('field_start', {'field': fld['id'], 'op': op, 'crop': crop, 'revision': fld['revision']}, t, 'fields'):
                    break
                fuel = C.FIELD_FUEL * fld['ha']
                self.fs['fuel'] += fuel
                self.fs['seeds'] += c0 - f['coins'] - fuel
                self.fs['ops_' + op] += 1
                t = self.finish_field(fld, fld['run'], t, mode)
                if t is None:
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
    def helper_plan(self):
        """Largest unlocked finite shift. Only a visit can pay for a new shift."""
        return max((p for p in C.SHIFTS.values() if p.get('level', 1) <= self.lv()),
                   key=lambda p: (p['seconds'], p['actions']))

    def helpers_visit(self, now):
        if not self.helpers:
            return
        for role in ('craft', 'animals', 'harvest'):
            candidates = sorted((h for h in C.HELPERS.values() if h['role'] == role),
                                key=lambda h: (h['level'], h['cost'], h['id']))
            specs = candidates[:self.craft_masters] if role == 'craft' else candidates[:1]
            plan = self.helper_plan()
            for spec in specs:
                if self.lv() < spec['level']:
                    continue
                if spec['id'] not in self.f['helpers'] and self.f['coins'] >= spec['cost'] + plan['cost']:
                    self.cmd('hire_helper', {'helper': spec['id']}, now, 'capex:helpers')
                    self.cache.clear()
                worker = self.f['helpers'].get(spec['id'])
                if worker and (not worker.get('shift') or worker['shift']['status'] != 'working'):
                    if self.f['coins'] >= plan['cost'] and self.cmd('start_shift', {'worker': spec['id'], 'shift': plan['id']}, now, 'helpers'):
                        self.helper_shifts[role] += 1

    def settle(self, now):
        """Run real field settlement first, then the real worker scheduler; record their value separately."""
        self.settle_source(FD.settle, now, 'fields')
        self.settle_source(X.settle, now, 'helpers')

    def settle_source(self, transition, now, tag):
        f = self.f
        c0, x0, w0, lv0 = f['coins'], f['xp'], self.inv_value(), C.level(f['xp'])
        m0 = dict(P.progress(f)['total'])
        done0 = {k: (v.get('shift') or {}).get('done', 0) for k, v in f['helpers'].items()}
        transition(f, now)
        dc, dx = f['coins'] - c0, f['xp'] - x0
        dw = dc + self.inv_value() - w0
        band = band_of(lv0)
        if dw:
            self.income[band][tag] += dw
        if dc > 0:
            self.gross[band][tag] += dc
        if dx:
            self.xp_src[band][tag] += dx
        for k, v in f['helpers'].items():
            delta = (v.get('shift') or {}).get('done', 0) - done0.get(k, 0)
            if delta > 0:
                self.helper_actions[C.HELPERS[k]['role']] += delta
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
        # Model a player mowing every ready patch at each visit. Reading the view also
        # advances lazy spawn/cleanup to this visit's Moscow epoch.
        meadow_view = MD.view(f, t)
        if any(p['stage'] >= 1 for p in meadow_view['patches']):
            self.cmd('mow_all', {}, t, 'meadow')
        self.cmd('collect_group', {'group': 'animals', 'area': None}, t, 'animals')
        self.cmd('collect_group', {'group': 'workshops', 'area': None}, t, 'workshops')
        self.orchard_visit(t)
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
        self.helpers_visit(end)
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
    out.append(f'=== {sim.name}: {sim.p["label"]}; helpers={sim.helpers}; craft_masters={sim.craft_masters}; full_queues={sim.full_queues}')
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
    out.extend(orchard_report(sim, srcs_all, xp_all))
    out.extend(meadow_report(sim))
    if sim.helpers:
        out.append('HELPERS: paid shifts ' + str(dict(sim.helper_shifts)) + '; useful actions ' + str(dict(sim.helper_actions)))
        roster = ', '.join(f'{C.HELPERS[hid]["name"]} L{C.HELPERS[hid]["level"]}'
                           for hid in sorted(f['helpers']) if hid in C.HELPERS)
        out.append('  roster: ' + (roster or 'none hired'))
    if sim.debug:
        out.append('refused commands: ' + ', '.join(f'{k[0]}/{k[1]}={v}' for k, v in sim.err.most_common(12)))
    return '\r\n'.join(out)


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
           f' mode {sim.field_mode}, operations {sim.fs["ops_auto"]} autopilot + {sim.fs["ops_manual"]} manual'
           f' (cultivate {sim.fs["ops_cultivate"]}, sow {sim.fs["ops_sow"]}, spray {sim.fs["ops_spray"]}, harvest {sim.fs["ops_harvest"]})']
    out.append(f'  crops harvested (shop value) {net + fuel + seeds}, fuel {fuel}, seeds {seeds}, repair {sim.fs["repair"]} -> field income {net} '
               f'({net / span:.0f}/day); upkeep {C.FIELD_UPKEEP}/ha/day x {ha_days} ha-days = {upkeep} ({upkeep / span:.0f}/day assessed)')
    out.append(f'  NET after upkeep {net - upkeep} ({(net - upkeep) / span:.0f}/day since the first field); share of positive income {100 * net / pos:.1f}%, '
               f'of XP {100 * field_xp / xt:.1f}%; capex fields {cap["capex:fields"]}, machines {cap["capex:machines"]}, widths {cap["capex:widths"]}'
               + (f'; payback of fields + tier-1 machines {(cap["capex:fields"] + cap["capex:machines"]) / max(1, (net - upkeep) / span):.0f} days, '
                  f'with widths {(cap["capex:fields"] + cap["capex:machines"] + cap["capex:widths"]) / max(1, (net - upkeep) / span):.0f} days'
                  if net > upkeep else '; not paid back'))
    if sim.fs_q:
        out.append('  manual q (permille; reference = server replay, manual/max = model after bumps and melt): ' + ', '.join(f'{op} {sum(v) / len(v):.0f} (n={len(v)})' for op, v in sorted(sim.fs_q.items())))
    sinks = sink_tot['upkeep'] + sink_tot['fund'] + sink_tot['decor']
    out.append(f'  sinks share of net income (all sinks, incl. field upkeep): {100 * sinks / max(1, sink_tot["net"]):.0f}%'
               f' (field upkeep alone {100 * upkeep / max(1, sink_tot["net"]):.0f}%)')
    return out


def orchard_report(sim, srcs_all, xp_all):
    """FARM_ORCHARD.md section 9: the orchard's own XP/coins, the XP of the fruit recipes, and the share per level band."""
    trees = [o for o in sim.f['objects'] if o['type'] == 'tree']
    if not sim.orchard:
        return ['', 'ORCHARD: switched off (--no-orchard): fruit beds are closed by the catalog and no sapling is ever bought']
    xt = sum(xp_all.values()) or 1
    own, proc = xp_all.get('orchard', 0), sum(sim.fruit_xp.values())
    out = ['', f'ORCHARD: {len(trees)} trees at the end ({", ".join(f"{k} {v}" for k, v in sorted(sim.trees_bought.items())) or "none"}); '
           f'tree XP {own} = {100 * own / xt:.1f}% of all XP, fruit recipes (counted when queued) {proc} = {100 * proc / xt:.1f}%, '
           f'together {100 * (own + proc) / xt:.1f}%; coins value added {srcs_all.get("orchard", 0)}; sapling capex '
           f'{sum(sim.capex[b]["capex:orchard"] for b in BANDS)}']
    if sim.helpers:
        out.append('  orchard values above cover owner actions; automated harvests and recipe repeats are in the helpers source.')
    out.append('  per band (tree XP + fruit-recipe XP as % of the band XP): ' + '; '.join(
        f'L{b[0]}-{b[1]} {100 * (sim.xp_src[b]["orchard"] + sim.fruit_xp[b]) / max(1, sum(sim.xp_src[b].values())):.1f}%'
        for b in BANDS if sim.level_t.get(b[0]) is not None))
    return out


def meadow_report(sim):
    """FARM_WILD_GRASS.md §5: count the saved mill work at 0.5 coins per grass."""
    stats = sim.meadow
    if not stats['grass_mowed'] and not stats['grass_fed']:
        return ['', 'MEADOW: no grass harvested or fed in this run']
    end_t = sim.t0 + sim.days_run * DAY
    reference = 0.0
    rows = []
    for b in BANDS:
        start = sim.level_t.get(b[0])
        if start is None:
            continue
        nxt = sim.level_t.get(b[1] + 1)
        stop = nxt if nxt is not None else end_t
        days = max((stop - start) / DAY, 0.0)
        ref_value = C.income_ref(b[0]) * days
        reference += ref_value
        proxy = sim.meadow_proxy[b]
        if proxy:
            rows.append(f'L{b[0]}-{b[1]}: proxy {proxy:.0f}, income_ref {C.income_ref(b[0])}/day x {days:.1f}d = {100 * proxy / max(1, ref_value):.2f}%')
    share = 100 * stats['proxy'] / max(1, reference)
    feed_proxy = stats['grass_fed'] * 0.5
    feed_share = 100 * feed_proxy / max(1, reference)
    total_equiv = stats['feed_equivalent']
    retained = 100 * stats['feed_from_mill'] / max(1, total_equiv)
    return ['', f'MEADOW: mowed {stats["grass_mowed"]} grass (shop value {stats["grass_mowed"]} coins); sold {stats["grass_sold"]} for {stats["grass_sale_coins"]} coins; harvest value proxy {stats["proxy"]:.1f} coins ({share:.3f}% of time-weighted income_ref; 0.5/grass); realized mill-time proxy {feed_proxy:.1f} coins ({feed_share:.3f}%); mowing XP 0',
            f'  feeding: grass {stats["grass_fed"]} = {stats["grass_fed"] / 2:.1f} feed-equivalent; mill feed {stats["feed_from_mill"]}; feed demand retained {retained:.1f}% of no-grass demand; mill time saved {stats["mill_seconds_saved"] / 3600:.2f}h',
            '  value by band: ' + ('; '.join(rows) if rows else 'none')]


def coins_at(self, t):
    d = int((t - self.t0) // DAY)
    return self.end_coins.get(d, self.f['coins'])


Sim.coins_at = coins_at


def fields_net_total(sim):
    """(value added by the fields in coins, field XP) so far."""
    return (sum(sim.income[b]['fields'] for b in BANDS), sum(sim.xp_src[b]['fields'] for b in BANDS))


def field_payback_run(name, mode, step, days=70, warmup=14, drop=(), **model):
    """One field step in isolation: only its machines and its visits are simulated, everything else is ignored.

    The player owns just this field (all four tier-1 machines), has unlimited coins and the level at which the step opens.  Visits follow the
    profile; the first ``warmup`` days are dropped so that the numbers describe steady cycles.  Upkeep is not part of the simulated flow: it is
    charged analytically (``C.FIELD_UPKEEP`` per hectare per day).  Returns per-day numbers of the whole field.
    """
    spec = C.FIELD_STEPS[step]
    sim = Sim(name, days, orchard=False, field_mode=mode, field_q=model.get('q'), field_hits=model.get('hits'),
              field_elapsed_k=model.get('elapsed_k'), field_share=model.get('share'))
    f = sim.f
    f['xp'] = C.LEVELS[spec['level'] - 1]
    f['coins'], f['starter_credit'] = 10 ** 9, 0
    f['fields'] = [FD.new_field(spec)]
    f['field_machines'] = {k: dict(tier=1, acquired_at=sim.t0) for k in C.FIELD_MACHINES if k not in drop}    # drop=('sprayer',): the machine is not owned
    snap = None
    for d in range(days):
        for s in sim.sessions:
            t = T_BASE + d * DAY + s
            sim.settle(t)
            sim.pay_debt(t)
            sim.fields_visit(t)
        if d + 1 == warmup:
            snap = (fields_net_total(sim), Counter(sim.fs))
    (coins1, xp1), fs1 = fields_net_total(sim), sim.fs
    (coins0, xp0), fs0 = snap
    span = days - warmup
    ha = spec['ha']
    fuel, seeds, repair = (fs1[k] - fs0[k] for k in ('fuel', 'seeds', 'repair'))
    upkeep = C.FIELD_UPKEEP * ha
    net = (coins1 - coins0) / span
    ops = {k: (fs1['ops_' + k] - fs0['ops_' + k]) / span for k in ('cultivate', 'sow', 'spray', 'harvest')}
    return dict(step=step, ha=ha, level=spec['level'], cost=spec['cost'], coins=net, xp=(xp1 - xp0) / span, upkeep=upkeep,
                net=net - upkeep, fuel=fuel / span, seeds=seeds / span, repair=repair / span, ops=ops,
                cycle_days=1 / max(1e-9, ops['harvest']),
                q={op: sum(v) / len(v) for op, v in sim.fs_q.items() if v})


def payback_days(capex, per_day):
    return capex / per_day if per_day > 0 else math.inf


def field_payback_report(profiles=('active', 'casual', 'online'), modes=('manual', 'auto'), days=70, **model):
    """Table: payback of every FIELD_STEP (+ the four tier-1 machines for the first one) per profile and player model."""
    machines = sum(m['costs'][0] for m in C.FIELD_MACHINES.values())
    out = [f'FIELD PAYBACK (isolated field, rules={C.FIELD_RULES}, upkeep {C.FIELD_UPKEEP}/ha/day, fuel {C.FIELD_FUEL}/ha/op, tier-1 machines {machines} '
           f'in total, XP counted at 4 coins in the last column)']
    out.append(f'{"profile":8} {"mode":7} {"step":>4} {"ha":>2} {"L":>3} {"price":>8} {"cycle,d":>7} {"coins/d":>8} {"upkeep":>7} {"net/d":>8} {"XP/d":>6} '
               f'{"payback d":>10} {"incl.mach":>10} {"with XP":>8}')
    for name in profiles:
        for mode in modes:
            for step in range(len(C.FIELD_STEPS)):
                r = field_payback_run(name, mode, step, days, **model)
                extra = machines if step == 0 else 0
                net_xp = r['net'] + 4 * r['xp']
                out.append(f'{name:8} {mode:7} {step:>4} {r["ha"]:>2} {r["level"]:>3} {r["cost"]:>8} {r["cycle_days"]:>7.2f} {r["coins"]:>8.0f} '
                           f'{r["upkeep"]:>7} {r["net"]:>8.0f} {r["xp"]:>6.0f} {payback_days(r["cost"], r["net"]):>10.0f} '
                           f'{payback_days(r["cost"] + extra, r["net"]):>10.0f} {payback_days(r["cost"] + extra, net_xp):>8.0f}')
    return '\n'.join(out)


class overrides:
    """Context manager: change catalog numbers for this process only and restore them afterwards (simulation only, never a game change)."""

    def __init__(self, upkeep=None, steps=None, machines=None, widths=None, fuel=None, land=None):
        self.upkeep, self.steps, self.machines, self.widths, self.fuel, self.land = upkeep, steps, machines, widths, fuel, land

    def __enter__(self):
        from qw_farm import upkeep_config as UC
        self.saved = dict(upkeep=(C.FIELD_UPKEEP, UC.FIELD_UPKEEP), fuel=(C.FIELD_FUEL, FD.FIELD_FUEL),
                          steps=[dict(x) for x in C.FIELD_STEPS],
                          machines={k: tuple(m['costs']) for k, m in C.FIELD_MACHINES.items()},
                          land=[dict(x) for x in C.LAND_STEPS])
        if self.upkeep is not None:
            C.FIELD_UPKEEP = UC.FIELD_UPKEEP = FD.FIELD_UPKEEP = self.upkeep
        if self.fuel is not None:
            C.FIELD_FUEL = FD.FIELD_FUEL = self.fuel
        if self.steps is not None:
            assert len(self.steps) == len(C.FIELD_STEPS)
            for spec, cost in zip(C.FIELD_STEPS, self.steps):
                spec['cost'] = cost
        if self.machines is not None or self.widths is not None:
            for index, (k, m) in enumerate(C.FIELD_MACHINES.items()):
                first = m['costs'][0] if self.machines is None else self.machines[index]
                w2, w3 = (m['costs'][1], m['costs'][2]) if self.widths is None else self.widths
                m['costs'] = (first, w2, w3)
        for size, cost in (self.land or {}).items():
            step = next(x for x in C.LAND_STEPS if x['size'] == size)
            step['cost'] = cost
        return self

    def __exit__(self, *exc):
        from qw_farm import upkeep_config as UC
        C.FIELD_UPKEEP, UC.FIELD_UPKEEP = self.saved['upkeep']
        FD.FIELD_UPKEEP = self.saved['upkeep'][0]
        C.FIELD_FUEL, FD.FIELD_FUEL = self.saved['fuel']
        for spec, old in zip(C.FIELD_STEPS, self.saved['steps']):
            spec.update(old)
        for k, costs in self.saved['machines'].items():
            C.FIELD_MACHINES[k]['costs'] = costs
        for spec, old in zip(C.LAND_STEPS, self.saved['land']):
            spec.update(old)
        return False


def parse_ints(text, count=None):
    values = tuple(int(x) for x in text.split(','))
    if count is not None and len(values) != count:
        raise argparse.ArgumentTypeError(f'expected {count} comma-separated integers')
    return values


def parse_land(text):
    out = {}
    for part in text.split(','):
        size, cost = part.split(':')
        out[int(size)] = int(cost)
    return out


def craft_capacity_benchmark(master_count, workshop_count=23, action_quota=None, shift_cost=None):
    """Run the real settlement against all workshop types with every queue full and ample shared stock.

    This measures scheduler capacity, not a realistic production economy or a price recommendation.
    """
    if not 1 <= master_count <= 4:
        raise ValueError('master_count must be between 1 and 4')
    crafts = sorted((h for h in C.HELPERS.values() if h['role'] == 'craft'),
                    key=lambda h: (h['level'], h['cost'], h['id']))[:master_count]
    if len(crafts) != master_count:
        raise ValueError(f'only {len(crafts)} craft helpers are available')
    workshop_types = sorted(X.WORKSHOP_TYPES)[:workshop_count]
    if len(workshop_types) != workshop_count:
        raise ValueError(f'only {len(X.WORKSHOP_TYPES)} workshop types are available')

    start = T_BASE
    farm = D.new_farm('capacity-benchmark', 'Capacity', start)
    farm['xp'] = C.LEVELS[-1]
    farm['size'] = 60
    farm['coins'] = 10_000_000
    farm['helpers'] = {}
    farm['equipment'] = {}
    farm['inventory'] = {item: 10**12 for item in C.ITEMS}
    farm['objects'] = []
    seeded = 0
    for index, building in enumerate(workshop_types):
        recipes = sorted((r for r in C.RECIPES.values() if r['building'] == building),
                         key=lambda r: (r['seconds'], r['id']))
        if not recipes:
            continue
        recipe = recipes[0]
        obj = dict(id=f'bench_{index:02d}', type=building, x=(index % 20) * 3,
                   y=(index // 20) * 3, w=2, h=2, revision=0, level=3, jobs=[],
                   recipes_memory=[recipe['id']], last_recipe=recipe['id'], recipe_cursor=0)
        for slot in range(C.queue_slots(3)):
            job = X.make_job(obj, recipe, start, 1, f'seed-{index}-{slot}', farm)
            job['manual'] = True
            obj['jobs'].append(job)
            for item, amount in recipe['inputs'].items():
                farm['inventory'][item] -= amount
            seeded += 1
        farm['objects'].append(obj)

    shift_plan = dict(C.SHIFTS['manor'])
    if action_quota is not None:
        shift_plan['actions'] = action_quota
    if shift_cost is not None:
        shift_plan['cost'] = shift_cost
    for index, spec in enumerate(crafts):
        farm['helpers'][spec['id']] = dict(acquired_at=start, zone=None, total_runs=0,
            shift=dict(id=f'bench-shift-{index}', status='working', plan=shift_plan['id'],
                       starts_at=start, until=start + shift_plan['seconds'], next_at=start,
                       interval=C.SHIFT_INTERVAL, remaining=shift_plan['actions'], done=0,
                       speed=1, role='craft', quota=shift_plan['actions'], version=C.VERSION))

    X.settle(farm, start + shift_plan['seconds'])
    actions = sum(worker['shift']['done'] for worker in farm['helpers'].values())
    collected = farm['stats']['crafts']
    started_again = sum(amount for event in farm['events'] for row in event.get('details', [])
                        for amount in row.get('started', {}).values())
    return dict(masters=master_count, workshop_types=len(workshop_types), queue_slots=C.queue_slots(3),
                seeded_jobs=seeded, actions=actions, quota=master_count * shift_plan['actions'],
                batches_collected=collected, batches_restarted=started_again,
                jobs_left=sum(len(obj['jobs']) for obj in farm['objects']),
                shift_hours=shift_plan['seconds'] / 3600,
                quota_per_master=shift_plan['actions'], shift_cost=shift_plan['cost'],
                total_shift_cost=master_count * shift_plan['cost'],
                quota_hours_each=shift_plan['actions'] * C.SHIFT_INTERVAL / 3600,
                productive_hours_total=actions * C.SHIFT_INTERVAL / 3600)


def run_craft_capacity():
    print('Craft capacity benchmark: real scheduler; all workshop types, level-3 full queues, unlimited stock, no zones.')
    print('Manor shift time = 8h; quota capacity is actions × 30 s.')
    for masters in range(1, 5):
        result = craft_capacity_benchmark(masters)
        print('masters={masters} workshops={workshop_types} queue={seeded_jobs} actions={actions}/{quota} '
              'quota_ends_each_h={quota_hours_each:.1f}/{shift_hours:.0f} productive_h_total={productive_hours_total:.1f} '
              'collected={batches_collected} restarted={batches_restarted} jobs_left={jobs_left}'.format(**result))
    for actions, cost in ((720, 135), (960, 180)):
        result = craft_capacity_benchmark(2, action_quota=actions, shift_cost=cost)
        print('variant masters={masters} actions_each={quota_per_master} cost_each={shift_cost} '
              'total_cost={total_shift_cost} actions={actions}/{quota} '
              'quota_ends_each_h={quota_hours_each:.1f}/{shift_hours:.0f} productive_h_total={productive_hours_total:.1f} '
              'collected={batches_collected} restarted={batches_restarted} jobs_left={jobs_left}'.format(**result))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\r\n')[0])
    ap.add_argument('--days', type=int, default=25)
    ap.add_argument('--profile', default='all', choices=['all', *PROFILES])
    ap.add_argument('--debug', action='store_true')
    ap.add_argument('--helpers', action='store_true', help='hire one master, animal keeper and harvester; renew paid shifts only at visits')
    ap.add_argument('--craft-masters', type=int, choices=range(5), help='hire this many craft helpers (0–4; implies --helpers)')
    ap.add_argument('--craft-capacity', action='store_true', help='benchmark 1–4 masters on every workshop with full queues')
    ap.add_argument('--sim-manor-actions', type=int, help='simulation-only override for manor shift actions; duration and catalog cost stay unchanged')
    ap.add_argument('--sim-demand-actions', type=int, help='simulation-only fixed action budget used by demand planning; isolates demand from shift quota overrides')
    ap.add_argument('--visit-queues', action='store_true', help='historical policy: only queue recipes that finish by the next visit')
    ap.add_argument('--no-fields', action='store_true', help='baseline: the player never buys a field')
    ap.add_argument('--field-mode', choices=FIELD_MODES, help='who drives the field machines (default: auto; the skilled profile uses reference)')
    ap.add_argument('--field-q', type=int, help='manual/max model: raw quality in permille before bumps and melt (default 1100 / 1250)')
    ap.add_argument('--field-hits', type=int, help='manual/max model: bumps per operation (-3 condition, 15 coins each; default 1 / 0)')
    ap.add_argument('--field-elapsed-k', type=int, help='manual/max model: run time as percent of the autopilot time A (default 200 / 100; 250 keeps the bonus, 600 melts it)')
    ap.add_argument('--field-manual-share', type=int, help='manual/max model: percent of the operations done by hand, the rest by autopilot (default 100)')
    ap.add_argument('--field-payback', action='store_true', help='measure the payback of every field step in isolation (profiles active/casual/online, manual and auto)')
    ap.add_argument('--sim-field-upkeep', type=int, help='SIMULATION ONLY: coins per hectare per day')
    ap.add_argument('--sim-field-fuel', type=int, help='SIMULATION ONLY: coins per hectare per operation')
    ap.add_argument('--sim-field-steps', type=lambda x: parse_ints(x, len(C.FIELD_STEPS)), help='SIMULATION ONLY: prices of the five field steps')
    ap.add_argument('--sim-field-machines', type=lambda x: parse_ints(x, len(C.FIELD_MACHINES)), help='SIMULATION ONLY: tier-1 prices (cultivator,seeder,combine,sprayer)')
    ap.add_argument('--sim-field-widths', type=lambda x: parse_ints(x, 2), help='SIMULATION ONLY: width 2 and width 3 upgrade price of every machine')
    ap.add_argument('--sim-land', type=parse_land, help='SIMULATION ONLY: land step prices as size:cost,size:cost')
    ap.add_argument('--no-orchard', action='store_true', help='baseline: the player never buys a fruit tree (fruit beds are closed by the catalog)')
    args = ap.parse_args()
    if args.craft_capacity:
        run_craft_capacity()
        return
    patch = overrides(args.sim_field_upkeep, args.sim_field_steps, args.sim_field_machines, args.sim_field_widths, args.sim_field_fuel, args.sim_land)
    if args.field_payback:
        model = {k: v for k, v in (('q', args.field_q), ('hits', args.field_hits), ('elapsed_k', args.field_elapsed_k), ('share', args.field_manual_share)) if v is not None}
        with patch:
            print(field_payback_report(modes=(args.field_mode,) if args.field_mode else ('manual', 'auto'), days=max(args.days, 30), **model))
        return
    if args.sim_manor_actions is not None and not 1 <= args.sim_manor_actions <= 1920:
        ap.error('--sim-manor-actions must be between 1 and 1920')
    if args.sim_demand_actions is not None and not 1 <= args.sim_demand_actions <= 1920:
        ap.error('--sim-demand-actions must be between 1 and 1920')
    helpers = args.helpers or args.craft_masters is not None
    original_actions = C.SHIFTS['manor']['actions']
    original_catalog_limit = C.MAX_SHIFT_ACTIONS
    original_expansion_limit = X.MAX_SHIFT_ACTIONS
    if args.sim_manor_actions is not None:
        C.SHIFTS['manor']['actions'] = args.sim_manor_actions
        C.MAX_SHIFT_ACTIONS = max(p['actions'] for p in C.SHIFTS.values())
        X.MAX_SHIFT_ACTIONS = C.MAX_SHIFT_ACTIONS
    try:
        print(f'catalog {C.VERSION}; days={args.days}')
        if args.sim_manor_actions is not None:
            print(f'SIMULATION ONLY: manor actions={C.SHIFTS["manor"]["actions"]}; duration={C.SHIFTS["manor"]["seconds"]}s; cost={C.SHIFTS["manor"]["cost"]} coins; product catalog unchanged')
        if args.sim_demand_actions is not None:
            print(f'SIMULATION ONLY: demand planning action budget={args.sim_demand_actions}; product catalog unchanged')
        for name in (PROFILES if args.profile == 'all' else [args.profile]):
            t = time.time()
            with patch:
                sim = Sim(name, args.days, args.debug, not args.no_fields, not args.no_orchard, helpers,
                          not args.visit_queues, args.craft_masters, args.sim_demand_actions, args.field_mode, args.field_q,
                          args.field_hits, args.field_elapsed_k, args.field_manual_share).run()
                print(report(sim))
            print(f'(simulated in {time.time() - t:.1f}s)\r\n')
    finally:
        C.SHIFTS['manor']['actions'] = original_actions
        C.MAX_SHIFT_ACTIONS = original_catalog_limit
        X.MAX_SHIFT_ACTIONS = original_expansion_limit


if __name__ == '__main__':
    main()
