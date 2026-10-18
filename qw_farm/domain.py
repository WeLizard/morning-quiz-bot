"""Pure farm rules. All time and identity come from the trusted application layer.

State is one small aggregate per farm. Mutate a transaction-local copy only.
An error MUST roll back the whole command in the persistence layer.
"""
from __future__ import annotations
from copy import deepcopy
from hashlib import sha256
import math
import re
from .catalog import (tick, CROPS, ITEMS, BUILDINGS, RECIPES, ANIMALS, QUESTS, LEVELS, NPCS, VERSION, level, is_land_size, land_step,
                      MAX_BUILDING_LEVEL, RECIPE_SPEED, BARN_SELL_BONUS, upgrade_kind, upgrade_cost, effective_level,
                      queue_slots, animal_batch, animal_xp, ANIMAL_XP_LEGACY, land_bound, plot_limit, object_limit)
from . import progression, economy, projects


class FarmError(Exception):
    def __init__(self, code: str, message: str, status: int = 409):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def need(condition, code, message, status=409):
    if not condition:
        raise FarmError(code, message, status)


def number(value, low=1, high=100):
    need(type(value) is int and low <= value <= high, 'invalid_number', 'Недопустимое количество.', 422)
    return value


def named(values, key):
    need(isinstance(key, str) and key in values, 'unknown_item', 'Этот предмет не найден.', 422)
    return values[key]


def find(values, key):
    item = next((x for x in values if x['id'] == key), None)
    need(item is not None, 'not_found', 'Объект уже изменился. Обнови ферму.', 404)
    return item


def duration(seconds, speed, farm=None):
    """Timer length in seconds. ``farm`` is passed where the PLAYER starts a timer: open upkeep debt makes it 1.2x (stage 14)."""
    if farm is not None:
        seconds = economy.stretch(seconds, farm)
    return max(1, math.ceil(seconds / speed))


def inventory(farm, values, direction=1):
    for key, qty in values.items():
        named(ITEMS, key)
        number(qty, 1, 1000000)
        need(farm['inventory'].get(key, 0) + direction * qty >= 0,
             'missing_goods', f'Не хватает: {ITEMS[key]["name"]}.')
    for key, qty in values.items():
        farm['inventory'][key] = farm['inventory'].get(key, 0) + direction * qty


def pay(farm, amount):
    need(farm['coins'] >= amount, 'insufficient_coins', 'Недостаточно монет. Можно продать урожай или выполнить заказ.')
    farm['coins'] -= amount
    credit = farm['starter_credit']
    farm['starter_credit'] = max(0, credit - amount)
    return credit - farm['starter_credit']  # the part paid from the starter gift (a refund must restore it)


def event(farm, now, text, kind='info'):
    farm['events'].insert(0, dict(at=now,text=text,kind=kind))
    del farm['events'][80:]


def object_cells(obj):
    return {(x,y) for x in range(obj['x'],obj['x']+obj['w']) for y in range(obj['y'],obj['y']+obj['h'])}


def place(farm, x, y, w=1, h=1, ignore=None):
    number(x,0,land_bound()-1); number(y,0,land_bound()-1)
    cells={(a,b) for a in range(x,x+w) for b in range(y,y+h)}
    need(all(a < farm['size'] and b < farm['size'] for a,b in cells), 'outside_land', 'Сначала расширь этот участок земли.')
    used=set()
    for obj in farm['objects']:
        if obj['id'] != ignore:
            used |= object_cells(obj)
    need(not used & cells, 'occupied', 'На этом месте уже что-то стоит.')


def rotatable(typ):
    """Walled buildings drawn in tile space can face either way; decor, plots, roads and the duck pond are screen sprites."""
    return typ in {'house','barn'} or (typ in BUILDINGS and not BUILDINGS[typ].get('decor') and typ!='duckpond')


def barn_sell_bonus(farm):
    """Percent added to the sale price by the best barn; farms without a barn (or older saves) get 0."""
    return max([BARN_SELL_BONUS[effective_level(o.get('level'))] for o in farm['objects'] if o['type']=='barn'] or [0])


def can_visit(me, other):
    if me['id'] == other['id']:
        return True
    if other['id'] in me['blocked'] or me['id'] in other['blocked']:
        return False
    return other['settings']['visibility'] == 'public' or (
        other['settings']['visibility'] == 'friends' and
        me['neighbors'].get(other['id'],{}).get('status') == 'accepted' and
        other['neighbors'].get(me['id'],{}).get('status') == 'accepted')


def social_allowed(me, other, permission):
    need(me['id'] != other['id'], 'own_farm', 'Это действие предназначено для соседа.', 422)
    need(can_visit(me,other), 'private_farm', 'Ферма недоступна.', 404)
    need(me['neighbors'].get(other['id'],{}).get('status') == 'accepted' and
         other['neighbors'].get(me['id'],{}).get('status') == 'accepted', 'not_neighbor', 'Сначала нужно стать соседями.', 403)
    need(other['settings'][permission], 'permission_denied', 'Хозяин отключил это действие.', 403)


def daily(farm, key, now, limit):
    day=int(now//86400)
    if farm['daily']['day'] != day:
        farm['daily']={'day':day,'counts':{}}
    counts=farm['daily']['counts']
    need(counts.get(key,0) < limit, 'daily_limit', 'На сегодня хватит — продолжим завтра.', 429)
    counts[key]=counts.get(key,0)+1


def reachable(farm):
    lv=level(farm['xp'])
    result={k for k,v in CROPS.items() if v['level']<=lv}
    from .catalog import ROUTES, route_level
    types={b['type'] for b in farm['objects']}
    for _ in range(20):
        old=len(result)
        for route in ROUTES.values():
            if route_level(route)<=lv and set(route['inputs'])<=result:
                result.update(route['outputs'])
        for a in ANIMALS.values():
            if any(o.get('animal')==a['id'] for o in farm['objects']) and a['level']<=lv and set(a['inputs'])<=result:
                result.update(a['outputs'])
        for r in RECIPES.values():
            if r['building'] in types and r['level']<=lv and set(r['inputs'])<=result:
                result.update(r['outputs'])
        if len(result)==old: break
    return sorted(result)


def make_order(farm, slot, now):
    seq=farm['order_seq']; farm['order_seq']+=1
    rng=int(sha256(f'{farm["id"]}:{seq}:{slot}'.encode()).hexdigest()[:16],16)
    products=reachable(farm)
    a=products[rng % len(products)]
    needs={a:1+(rng//17)%3}
    if seq>2 and len(products)>1:
        b=products[(rng//31) % len(products)]
        if a!=b: needs[b]=1+(rng//73)%2
    if seq==0: needs={'wheat':6}
    if seq==1: needs={'carrot':3}
    if seq==2: needs={'flour':1,'egg':2}
    price=sum(ITEMS[k]['price']*q for k,q in needs.items())
    npc,subtitle=NPCS[rng % len(NPCS)]
    if seq>2:   # a resident with a signature theme (Медведь Пух: energy drinks) mostly asks for it, when it is reachable
        from .catalog import NPC_SIGNATURE, SIGNATURE_PCT
        sig=[i for i in NPC_SIGNATURE.get(npc,()) if i in products]
        if sig and (rng//41)%100<SIGNATURE_PCT:
            needs={sig[(rng//43)%len(sig)]:1+(rng//47)%3}
            price=sum(ITEMS[k]['price']*q for k,q in needs.items())
    special=None
    if seq>2:
        from . import market
        special=market.special_needs(farm,rng,npc,products)
    if special:
        needs=special;price=sum(ITEMS[k]['price']*q for k,q in needs.items());subtitle='Особая просьба: любимое лакомство'
    coins=math.ceil(price*1.45)+6
    if special:coins=math.ceil(coins*1.2)
    return dict(id=f'order_{seq}',slot=slot,npc=npc,title=subtitle,needs=needs,
                coins=coins,xp=max(5,price//5),skip_at=now+15,**({'special':True} if special else {}))


def new_farm(farm_id, name, now):
    now=tick(now)
    farm=dict(id=farm_id,name=f'Ферма {name}'[:28],catalog=VERSION,created_at=now,revision=0,
        coins=250,starter_credit=250,xp=0,size=8,inventory={'wheat':6,'feed':2},
        settings={'visibility':'friends','allow_help':True,'allow_gifts':True,'allow_pranks':False,'allow_trade':True},
        objects=[],neighbors={},blocked=[],events=[],pranks=[],listings=[],orders=[],order_seq=0,
        stats={'harvests':0,'crafts':0,'orders':0,'helps':0,'builds':0,'gifts':0},
        home_projects=projects.initial_state(),
        claimed_quests=[],daily={'day':int(now//86400),'counts':{}})
    for i,(typ,x,y) in enumerate([('house',0,0),('barn',0,3),('mill',3,0),('coop',6,0)]):
        farm['objects'].append(dict(id=f'building_{i}',type=typ,x=x,y=y,w=2,h=2,revision=0,level=1,jobs=[],animal='chicken' if typ=='coop' else None,animal_job=None))
    for i,(x,y) in enumerate([(3,4),(4,4),(5,4),(3,5),(4,5),(5,5)]):
        plot=dict(id=f'plot_{i}',type='plot',x=x,y=y,w=1,h=1,revision=0,crop=None)
        if i<2:
            plot['crop']=dict(id='wheat',planted_at=now-30,ready_at=now,yield_qty=3,xp=2,helped=False,version=VERSION,cost=0,gift=0)
        if i==2:
            plot['crop']=dict(id='carrot',planted_at=now-100,ready_at=now+20,yield_qty=3,xp=3,helped=False,version=VERSION,cost=0,gift=0)
        farm['objects'].append(plot)
    from . import market
    market.upgrade_market(farm);market.make_contracts(farm,market.moscow_day(now))  # r8: nothing left to settle on day one
    farm['orders']=[make_order(farm,i,now) for i in range(3)]
    event(farm,now,'Филиныч оставил семена, корм и 250 монет на обустройство. Добро пожаловать!','welcome')
    return farm


# Per-command schemas reject client-supplied rewards, prices or ready_at.
SCHEMAS={
 'plant':{'object','crop','revision'},'dig_up':{'object','revision'},'harvest':{'object','revision'},'collect_all':set(),
 'queue':{'object','recipe'},'collect':{'object','job'},'cancel_job':{'object','job'},
 'feed':{'object'},'collect_animal':{'object'},'buy_animal':{'object','animal'},
 'build':{'type','x','y'},'move':{'object','x','y','revision'},'rotate':{'object','revision'},'demolish':{'object','revision'},'upgrade':{'object','revision'},
 'rescue':set(),'expand':set(),'sell':{'item','qty'},'order':{'order'},'skip_order':{'order'},'quest':{'quest'},
 'village_quest':{'npc','action'},
 'settings':{'name','visibility','allow_help','allow_gifts','allow_pranks','allow_trade'},
 'request_neighbor':set(),'accept_neighbor':set(),'claim_neighbor_reward':set(),'remove_neighbor':set(),'block':set(),'unblock':set(),
 'help':{'object','revision'},'prank':set(),'clear_prank':set(),'gift':{'item','qty'},
 'list':{'item','qty','unit_price'},'buy':{'listing'},'cancel_listing':{'listing'},
 'pay_upkeep':set(),'fund_contribute':{'coins','items'},
}
SOCIAL={'request_neighbor','accept_neighbor','claim_neighbor_reward','remove_neighbor','block','unblock','help','prank','gift','buy'}


def apply(me, other, kind, data, now, command_id, speed=1, form='n'):
    """Apply one strictly validated command to locked copies of farm aggregates."""
    now=tick(now)
    from . import expansion
    expansion.upgrade_state(me)
    if other is not me: expansion.upgrade_state(other)
    if kind in expansion.SCHEMAS:
        need(isinstance(data,dict) and set(data)==expansion.SCHEMAS[kind], 'invalid_command', 'Некорректные параметры действия.',422)
        need(me['id']==other['id'], 'not_owner', 'Это не твоя ферма.',403)
        text=expansion.apply_extension(me,kind,data,now,command_id,speed,form)
        progression.touch(me,now)  # r9: a successful command of the actor is activity (M2 pool, Moscow-day roll)
        economy.bill(me,now)       # r9 stage 14: one upkeep bill per active Moscow day, after the command
        return text
    need(kind in SCHEMAS, 'unknown_command', 'Неизвестное действие.', 422)
    need(isinstance(data,dict) and set(data)==SCHEMAS[kind], 'invalid_command', 'Некорректные параметры действия.',422)
    need(kind in SOCIAL or me['id']==other['id'], 'not_owner', 'Это не твоя ферма.',403)
    if kind in {'help','prank','gift','buy'}:
        social_allowed(me, other, {'help':'allow_help','prank':'allow_pranks','gift':'allow_gifts','buy':'allow_trade'}[kind])
    obj=None
    if 'object' in data:
        obj=find((other if kind=='help' else me)['objects'],data['object'])
        if 'revision' in data:
            need(type(data['revision']) is int and obj['revision']==data['revision'], 'stale_object','Объект изменился. Попробуй ещё раз.')
    lv=level(me['xp']); text='Готово.'
    if kind=='plant':
        crop=named(CROPS,data['crop'])
        need(obj['type']=='plot' and obj['crop'] is None,'busy_plot','Эта грядка занята.')
        need(lv>=crop['level'],'locked','Эта культура откроется на следующем уровне.')
        gift=pay(me,crop['cost'])
        obj['crop']=dict(id=crop['id'],planted_at=now,ready_at=now+duration(crop['seconds'],speed,me),
            yield_qty=crop['yield_qty'],xp=crop['xp'],helped=False,version=VERSION,cost=crop['cost'],gift=gift)
        obj['revision']+=1; text=f'{crop["name"]}: посажено.'
    elif kind=='dig_up':
        from . import undo
        text=undo.dig_up(me,obj,now)
    elif kind in {'harvest','collect_all'}:
        plots=[obj] if kind=='harvest' else [p for p in me['objects'] if p['type']=='plot' and p['crop'] and p['crop']['ready_at']<=now]
        need(bool(plots),'nothing_ready','Пока ничего не созрело.')
        for p in plots:
            c=p.get('crop'); need(c is not None and c['ready_at']<=now,'not_ready','Урожай ещё растёт.')
            inventory(me,{c['id']:c['yield_qty']});progression.grant_xp(me,c['xp'],'harvest',now,True,CROPS[c['id']]['seconds'] if c['id'] in CROPS else None);me['stats']['harvests']+=1
            expansion.observe_harvest(me,c['id']);expansion.market.count(me,'h:'+c['id'],c['yield_qty']);p['last_crop']=c['id']
            p['crop']=None;p['revision']+=1
        text=f'Урожай собран: {len(plots)} гряд.'
    elif kind=='queue':
        r=named(RECIPES,data['recipe'])
        need(obj['type']==r['building'] and r['level']<=lv,'wrong_building','Этот рецепт здесь пока недоступен.')
        need(len(obj['jobs']) < queue_slots(obj.get('level')),'queue_full','Очередь заполнена. Забери готовые товары.')
        inventory(me,r['inputs'],-1)
        obj['jobs'].append(expansion.make_job(obj,r,now,speed,command_id,me))
        obj['last_recipe']=r['id']  # remembered for the artisans and «повторить партии»
        obj['revision']+=1;text='Производство поставлено в очередь.'
    elif kind in {'collect','cancel_job'}:
        job=find(obj.get('jobs',[]),data['job'])
        if kind=='collect':
            need(job['ready_at']<=now,'not_ready','Продукция ещё не готова.')
            inventory(me,job['outputs']);expansion.market.count_outputs(me,job['outputs']);progression.grant_xp(me,job['xp'],'craft',now,True,RECIPES[job['recipe']]['seconds'] if job.get('recipe') in RECIPES else None);me['stats']['crafts']+=1;text='Готовая продукция на складе.'
        else:
            need(job['starts_at']>now,'already_started','Можно отменить только ещё не начатую работу.')
            inventory(me,job['inputs']);text='Ингредиенты возвращены.'
        obj['jobs'].remove(job)
        if kind=='cancel_job':
            end=now
            for j in obj['jobs']:
                if j['starts_at']>now:
                    j['starts_at']=max(now,end);j['ready_at']=j['starts_at']+j['seconds']
                end=j['ready_at']
        obj['revision']+=1
    elif kind=='buy_animal':
        a=named(ANIMALS,data['animal'])
        need(obj['type']==a['building'] and not obj.get('animal'),'animal_exists','Этот домик уже занят или не подходит.')
        need(lv>=a['level'],'locked','Нужен более высокий уровень.')
        pay(me,a['cost']);obj['animal']=a['id'];obj['revision']+=1;text='Животные поселились на ферме.'
    elif kind=='feed':
        a=named(ANIMALS,obj.get('animal'))
        need(not obj.get('animal_job'),'animal_busy','Сначала забери готовую продукцию.')
        inputs,outputs,seconds=animal_batch(a,obj.get('level'))
        inventory(me,inputs,-1)
        obj['animal_job']=dict(ready_at=now+duration(seconds,speed,me),outputs=outputs,xp=animal_xp(a,obj.get('level')),version=VERSION)
        obj['revision']+=1;text='Животные накормлены. Можно заниматься другими делами.'
    elif kind=='collect_animal':
        j=obj.get('animal_job');need(j and j['ready_at']<=now,'not_ready','Животные ещё не приготовили продукцию.')
        inventory(me,j['outputs']);expansion.market.count_outputs(me,j['outputs']);progression.grant_xp(me,j.get('xp',ANIMAL_XP_LEGACY),'animal',now,True);me['stats']['crafts']+=1;obj['animal_job']=None;obj['revision']+=1;text='Продукция животных собрана.'
    elif kind=='build':
        typ=data['type']
        if typ=='plot':
            c=dict(cost=35,level=1,w=1,h=1)
            need(sum(o['type']=='plot' for o in me['objects'])<plot_limit(me['size']),'plot_limit',f'На таком участке доступно до {plot_limit(me["size"])} грядок. Расширь землю.')
        else: c=named(BUILDINGS,typ)
        need(lv>=c['level'],'locked',f'Нужен уровень {c["level"]}.')
        need(not c.get('secret') or c['secret'] in me['secrets'],'secret_locked','Этот декор нужно сначала найти в кабинете находок.')
        need(not c.get('reward') or economy.reward_allowed(me,typ),'reward_locked','Этот декор выдаётся наградой фонда деревни.')
        need(len(me['objects'])<object_limit(me['size']),'object_limit','Достигнут лимит объектов для этого участка.')
        place(me,data['x'],data['y'],c['w'],c['h'])
        free=c.get('decor') and not c.get('secret') and expansion.market.free_decor(me,typ)  # r8: caravan gift
        if free:expansion.market.take_decor(me,typ)
        else:pay(me,c['cost']);economy.note_decor_spend(me,typ,c['cost'])
        me['objects'].append(dict(id=command_id,type=typ,x=data['x'],y=data['y'],w=c['w'],h=c['h'],
           revision=0,level=1,jobs=[],animal=None,animal_job=None,**({'crop':None} if typ=='plot' else {})))
        me['stats']['builds']+=1;progression.grant_xp(me,5,'build',now,True);text='Постройка готова.'
    elif kind=='move':
        place(me,data['x'],data['y'],obj['w'],obj['h'],obj['id'])
        obj['x']=data['x'];obj['y']=data['y'];obj['revision']+=1;text='Новое место сохранено.'
    elif kind=='rotate':
        need(rotatable(obj['type']),'cannot_rotate','Эту постройку поворачивать не нужно.')
        try:place(me,obj['x'],obj['y'],obj['h'],obj['w'],obj['id'])
        except FarmError as error:
            if error.code not in {'occupied','outside_land'}:raise
            raise FarmError(error.code,'Для поворота не хватает места.',error.status) from None
        obj['w'],obj['h']=obj['h'],obj['w']
        obj['orientation']=1-obj.get('orientation',0);obj['revision']+=1;text='Постройка повёрнута.'
    elif kind=='demolish':
        need(obj['type'] not in {'house','barn'},'cannot_demolish','Дом и склад нельзя снести.')
        need(not (obj.get('crop') or obj.get('jobs') or obj.get('animal_job') or obj.get('animal')),
             'object_busy','Сначала освободи объект от урожая, производства или животных.')
        building=BUILDINGS.get(obj['type'])
        wood=4+effective_level(obj.get('level'))-1 if building and not building.get('decor') else 0
        if wood:inventory(me,{'wood':wood})
        me['objects'].remove(obj)
        text=f'Постройка разобрана: древесина ×{wood}.' if wood else 'Объект убран с фермы.'
    elif kind=='upgrade':
        need(upgrade_kind(obj['type']) is not None,'cannot_upgrade','Эту постройку улучшать не нужно.')
        cur=obj.get('level',1)
        need(type(cur) is int and cur<MAX_BUILDING_LEVEL,'max_level','Уже максимальный уровень постройки.')
        target=cur+1;cost=upgrade_cost(obj['type'],target)
        need(lv>=cost['level'],'locked',f'Улучшение до {target} уровня открывается с {cost["level"]} уровня фермы.')
        need(me['coins']>=cost['coins'],'insufficient_coins','Недостаточно монет для улучшения.')
        inventory(me,cost['items'],-1)  # validates every good before anything is spent
        pay(me,cost['coins']);obj['level']=target;obj['revision']+=1
        text={'workshop':f'Мастерская улучшена до {target} уровня: очередь длиннее, работа быстрее.',
              'animals':f'Домик улучшен до {target} уровня: животные помещаются в большем количестве.',
              'barn':f'Склад улучшен до {target} уровня: торговля идёт выгоднее.'}[upgrade_kind(obj['type'])]
    elif kind=='expand':
        step=land_step(me['size'])
        need(step,'max_land','Весь участок уже открыт.')
        need(level(me['xp'])>=step['level'],'level_required',f"Расширение до {step['size']} × {step['size']} открывается с {step['level']} уровня.")
        pay(me,step['cost']);me['size']=step['size'];progression.grant_xp(me,20,'expand',now,True);text='Новый участок открыт.'
    elif kind=='rescue':
        has_resources=any(me['inventory'].values()) or projects.has_reserved(me) or bool(me['listings']) or any(
            o.get('crop') or o.get('jobs') or o.get('animal_job') for o in me['objects'])
        need(me['coins']<2 and not has_resources,'no_rescue_needed','Сначала используй или продай оставшиеся ресурсы.')
        me['coins']+=2;me['starter_credit']+=2;text='Филиныч выдал монеты на один посев пшеницы. Начнём снова!'
    elif kind=='pay_upkeep':
        text=f'Долг по содержанию погашен: −{economy.pay_debt(me)} монет.'
    elif kind=='fund_contribute':
        coins,items=data['coins'],data['items']
        need(isinstance(items,dict) and all(type(q) is int for q in items.values()),'invalid_command','Некорректный вклад.',422)
        value,text,_=economy.contribute(me,coins,items,now)
    elif kind=='sell':
        item=named(ITEMS,data['item']);qty=number(data['qty'],1,999)
        inventory(me,{item['id']:qty},-1);bonus=barn_sell_bonus(me);gain=item['price']*qty*(100+bonus)//100;me['coins']+=gain
        text=f'Продано: +{gain} монет.'+(f' (склад: +{bonus}%)' if bonus else '')
    elif kind in {'order','skip_order'}:
        order=find(me['orders'],data['order'])
        if kind=='order':
            inventory(me,order['needs'],-1);coins,xp=expansion.market.order_reward(me,order)
            me['coins']+=coins;progression.grant_xp(me,xp,'order',now,True);me['stats']['orders']+=1;expansion.market.after_order(me,order,now)
            text=f'{order["npc"]} благодарит! +{coins} монет.'
        else:
            need(order['skip_at']<=now,'skip_wait','Подожди немного перед заменой заказа.');text='На доске новый заказ.'
        slot=order['slot'];me['orders'][slot]=make_order(me,slot,now)
    elif kind=='village_quest':
        from . import village_quests
        text=village_quests.act(me,data['npc'],data['action'],now)
    elif kind=='quest':
        q=find(QUESTS,data['quest'])
        need(q['id'] not in me['claimed_quests'],'already_claimed','Награда уже получена.')
        need(me['stats'][q['stat']]>=q['goal'],'quest_incomplete','Задание ещё не выполнено.')
        me['claimed_quests'].append(q['id']);me['coins']+=q['coins'];progression.grant_xp(me,q['xp'],'quest',now,True);text=f'«{q["name"]}»: награда получена!'
    elif kind=='settings':
        name=data['name'];need(isinstance(name,str) and 2<=len(name.strip())<=28 and not any(ord(c)<32 for c in name),'invalid_name','Название: от 2 до 28 символов.',422)
        need(isinstance(data['visibility'],str) and data['visibility'] in {'private','friends','public'},'invalid_privacy','Недопустимая приватность.',422)
        for k in ['allow_help','allow_gifts','allow_pranks','allow_trade']:
            need(type(data[k]) is bool,'invalid_flag','Настройка должна быть логической.',422)
        me['name']=name.strip();me['settings']={k:data[k] for k in me['settings']};text='Настройки сохранены.'
    elif kind=='claim_neighbor_reward':
        need(me['id']!=other['id'],'own_farm','Это твоя ферма.',422)
        need(other['id'] not in me['blocked'] and me['id'] not in other['blocked'] and
             me['neighbors'].get(other['id'],{}).get('status')=='accepted' and
             other['neighbors'].get(me['id'],{}).get('status')=='accepted',
             'not_neighbor','Награда доступна только действующим соседям.',403)
        text='Забрать награду за соседство.'
    elif kind in {'request_neighbor','accept_neighbor','remove_neighbor','block','unblock'}:
        need(me['id']!=other['id'],'own_farm','Это твоя ферма.',422)
        a,b=me['id'],other['id']
        if kind=='block':
            if b not in me['blocked']:me['blocked'].append(b)
            me['neighbors'].pop(b,None);other['neighbors'].pop(a,None);text='Сосед заблокирован. Доступ закрыт.'
        elif kind=='unblock':
            if b in me['blocked']:me['blocked'].remove(b)
            text='Блокировка снята. Для соседства нужно новое приглашение.'
        else:
            need(b not in me['blocked'] and a not in other['blocked'],'blocked','Взаимодействие недоступно.',403)
            if kind=='request_neighbor':
                need(b not in me['neighbors'],'already_requested','Приглашение уже отправлено или соседство принято.')
                need(len(me['neighbors'])<100 and len(other['neighbors'])<100,'neighbors_full','Список соседей заполнен.')
                daily(me,'invites',now,20)
                me['neighbors'][b]={'name':other['name'],'status':'outgoing'}
                other['neighbors'][a]={'name':me['name'],'status':'incoming'}
                event(other,now,f'{me["name"]}: приглашение в соседи.','social');text='Приглашение отправлено.'
            elif kind=='accept_neighbor':
                need(me['neighbors'].get(b,{}).get('status')=='incoming' and other['neighbors'].get(a,{}).get('status')=='outgoing','no_invite','Приглашение не найдено.')
                me['neighbors'][b]={'name':other['name'],'status':'accepted'}
                other['neighbors'][a]={'name':me['name'],'status':'accepted'}
                event(other,now,f'{me["name"]} принимает приглашение. Теперь вы соседи!','social');text='Теперь вы соседи!'
            else:
                me['neighbors'].pop(b,None);other['neighbors'].pop(a,None);text='Соседство отменено.'
    elif kind=='help':
        social_allowed(me,other,'allow_help')
        c=obj.get('crop');need(c and c['ready_at']>now and not c['helped'],'cannot_help','Эта грядка уже готова или ей уже помогли.')
        daily(me,f'help:{other["id"]}',now,3);daily(me,'help_total',now,10)
        c['ready_at']=max(now,c['ready_at']-max(1,math.ceil((c['ready_at']-c['planted_at'])*0.2)));c['helped']=True;obj['revision']+=1
        me['stats']['helps']+=1;event(other,now,f'{me["name"]} поливает грядку. Урожай созреет раньше.','social');text='Грядка полита. Спасибо за помощь!'
    elif kind=='prank':
        social_allowed(me,other,'allow_pranks')
        need(me['settings']['allow_pranks'],'mutual_consent','Включи проделки и на своей ферме.',403)
        need(not any(p['until']>now for p in other['pranks']),'prank_active','На ферме уже гуляет гусь.')
        daily(me,f'prank:{other["id"]}',now,2);daily(me,'prank_total',now,5)
        other['pranks']=[dict(kind='goose',from_name=me['name'],until=now+1200)]
        event(other,now,f'{me["name"]} присылает гуся. Ущерб: ноль. Самоуверенность гуся: огромная.','goose');text='Гусь отправился на разведку. Урожай в безопасности.'
    elif kind=='clear_prank':
        me['pranks']=[];text='Гусь проводил сам себя за калитку.'
    elif kind=='gift':
        social_allowed(me,other,'allow_gifts')
        item=named(ITEMS,data['item']);qty=number(data['qty'],1,10)
        need(me['stats']['orders']>=1 and me['stats']['harvests']>=4,'gift_locked','Подарки откроются после первого заказа и четырёх сборов.')
        daily(me,f'gift:{other["id"]}',now,3);daily(me,'gift_total',now,5)
        inventory(me,{item['id']:qty},-1);inventory(other,{item['id']:qty});me['stats']['gifts']+=1
        event(other,now,f'{me["name"]} дарит {item["name"]} ×{qty}.','social');text='Подарок уже у соседа.'
    elif kind=='list':
        need(me['stats']['orders']>=3,'trade_locked','Лавка откроется после трёх заказов.')
        item=named(ITEMS,data['item']);qty=number(data['qty'],1,20);price=number(data['unit_price'],item['price'],item['price']*2)
        need(len(me['listings'])<3,'stall_full','В лавке три места. Продай или убери один лот.')
        inventory(me,{item['id']:qty},-1)
        me['listings'].append(dict(id=command_id,item=item['id'],qty=qty,unit_price=price,created_at=now));text='Товар выставлен для соседей.'
    elif kind=='buy':
        social_allowed(me,other,'allow_trade')
        need(me['stats']['orders']>=3,'trade_locked','Покупки у соседей открываются после трёх заказов.')
        lot=find(other['listings'],data['listing']);cost=lot['qty']*lot['unit_price']
        need(me['coins']-me['starter_credit']>=cost,'earned_coins','На рынке используются только заработанные монеты, не стартовый подарок.')
        me['coins']-=cost;fee=max(1,math.ceil(cost*0.03));other['coins']+=cost-fee
        inventory(me,{lot['item']:lot['qty']});other['listings'].remove(lot)
        event(other,now,f'{me["name"]} покупает товар: +{cost-fee} монет (комиссия {fee}).','trade');text=f'Покупка получена за {cost} монет.'
    elif kind=='cancel_listing':
        lot=find(me['listings'],data['listing']);inventory(me,{lot['item']:lot['qty']});me['listings'].remove(lot);text='Товар возвращён на склад.'
    # No irreversible poverty: emergency wheat planting is handled by an explicit
    # free starter option below, not by silently granting currency.
    expansion.detect_secrets(me,now)
    progression.touch(me,now)  # r9: successful command = activity; failed ones leave the state untouched
    if kind not in {'rescue','pay_upkeep'}:economy.bill(me,now)  # r9 stage 14: one bill per active Moscow day, after the command
    event(me,now,text,kind)
    return text


def validate_state(farm):
    from .expansion import validate_expansion
    from . import minigames
    validate_expansion(farm)
    minigames.validate(farm)
    progression.validate(farm)
    economy.validate(farm)
    from . import village_quests
    village_quests.validate(farm)
    need(type(farm['coins']) is int and 0<=farm['coins']<=10**12,'invalid_balance','Некорректное состояние баланса.',500)
    need(0<=farm['starter_credit']<=farm['coins'],'invalid_credit','Некорректное состояние средств.',500)
    need(farm['xp']>=0 and is_land_size(farm['size']),'invalid_state','Некорректное состояние фермы.',500)
    need(all(k in ITEMS and type(q) is int and 0<=q<=10**9 for k,q in farm['inventory'].items()),'invalid_inventory','Некорректное состояние склада.',500)
    used=set()
    for obj in farm['objects']:
        need(type(obj.get('level',1)) is int and 1<=obj.get('level',1)<=4,'invalid_level','Некорректный уровень постройки.',500)
        need(type(obj.get('orientation',0)) is int and obj.get('orientation',0) in (0,1),'invalid_orientation','Некорректная ориентация постройки.',500)
        cells=object_cells(obj)
        need(not cells&used and all(0<=x<farm['size'] and 0<=y<farm['size'] for x,y in cells),'invalid_layout','Некорректная планировка.',500)
        used|=cells


def project(farm, visitor, now):
    now=tick(now)
    own=farm['id']==visitor['id']
    need(can_visit(visitor,farm),'private_farm','Ферма недоступна.',404)
    if own:
        result=deepcopy(farm)
        from . import village_quests
        result['village_errands']=village_quests.public(farm,now)
        from . import minigames
        result['minigames']=minigames.public(farm,now)
        result['home_projects']=projects.owner_state(farm)
    else:
        result={k:deepcopy(farm[k]) for k in ['id','name','size','revision','objects']}
        # Only visual progress and ready flags, never production contents or economy.
        for obj in result['objects']:
            obj['jobs']=[{'ready_at':j['ready_at']} for j in obj.get('jobs',[])]
            obj.pop('last_recipe',None)
            if obj.get('animal_job'):obj['animal_job']={'ready_at':obj['animal_job']['ready_at']}
        result['equipment']={k:{'active':bool(v.get('shift') and v['shift']['status']=='working'),'last_run_at':v.get('last_run_at',0)} for k,v in farm.get('equipment',{}).items()}
        result['helpers']={k:{'active':bool(v.get('shift') and v['shift']['status']=='working')} for k,v in farm.get('helpers',{}).items()}
        result['pranks']=[{'kind':p['kind'],'until':p['until']} for p in farm['pranks'] if p['until']>now]
        result['listings']=deepcopy(farm['listings']) if farm['settings']['allow_trade'] and visitor['neighbors'].get(farm['id'],{}).get('status')=='accepted' else []
        result['home_projects']=projects.public_state(farm)
    result.update(is_owner=own,level=level(farm['xp']),server_time=now)
    if own:result.setdefault('fields',[]);result.setdefault('field_machines',{})
    if own:result['xp_bonus']=progression.status(farm,now);result['economy_status']=economy.status(farm,now)
    accepted=visitor['neighbors'].get(farm['id'],{}).get('status')=='accepted'
    result['permissions']={p:own or (accepted and farm['settings'][p]) for p in ['allow_help','allow_gifts','allow_pranks','allow_trade']}
    return result
