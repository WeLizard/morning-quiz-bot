"""Application commands, scoped idempotency and projections. No HTTP or Telegram."""
from dataclasses import dataclass
from copy import deepcopy
from hashlib import sha256
from uuid import uuid4, UUID
import json
import re
import time
from .domain import new_farm, apply, project, validate_state, can_visit, FarmError, need, event
from .catalog import tick, public_catalog, VERSION, level, FUND_LEVEL, INVITE
from .expansion import upgrade_state, settle
from . import economy, invites, undo, minigames, progression, trip_games

@dataclass(frozen=True)
class Principal:
    account_id: str
    name: str
    authentication: str = 'account'  # transport identity label, never a credential
    address_form: str = 'n'  # Account-level 'm'|'f'|'n' (domain/address.py); never inferred

class FarmService:
    def __init__(self, unit, principal: Principal, *, clock=time.time, speed=1, question_provider=None):
        self.u,self.p=unit,principal
        self.question_provider=question_provider
        self.clock=lambda:tick(clock())  # whole seconds everywhere: the single time normalisation point
        need(isinstance(speed,(int,float)) and 1<=speed<=60,'invalid_speed','Недопустимый темп сервера.',500)
        self.speed=speed

    async def open(self, invite=None):
        await self.u.lock('account:'+self.p.account_id)
        farm=await self.u.by_account(self.p.account_id)
        if farm is None:
            farm=upgrade_state(new_farm(str(uuid4()),self.p.name,self.clock()))
            validate_state(farm)
            await self.u.save(farm,self.p.account_id)
            await self.u.record(self.p.account_id,'bootstrap','bootstrap',None,farm,self.clock())
        await self.u.lock('farm:'+farm['id'])
        farm=await self.u.get(farm['id'])
        if invite:
            try:farm=await self._attach_invite(farm,invite)
            except FarmError:pass  # a stale/foreign/late link never blocks opening the farm
        await self._settle(farm,own=True)
        return dict(farm=project(farm,farm,self.clock()),catalog=dict(public_catalog(),undo=undo.public_rules(),trip_games=trip_games.public_rules()),speed=self.speed,village=await self._village(farm),
                    invites=await self._invites(farm),address_form=self.p.address_form)

    async def _attach_invite(self, farm, code):
        """Link a FRESH farm to its inviter (any channel: Telegram, web link or typed code) and pay the starting bonus once."""
        if not hasattr(self.u,'invite_add'):return farm
        try:code=str(UUID(str(code)))
        except (ValueError,TypeError,AttributeError):raise FarmError('invalid_invite','Некорректный код приглашения.',422)
        now=self.clock()
        need(code!=farm['id'],'self_invite','Нельзя пригласить самого себя.',422)
        need(invites.fresh(farm,now),'invite_late','Приглашение можно ввести только на новой ферме.')
        inviter=await self.u.get(code)
        need(inviter is not None and await self.u.owner_account(code)!=self.p.account_id,'invite_unknown','Приглашение не найдено.',404)
        if not await self.u.invite_add(farm['id'],code,now):return farm
        before=deepcopy(farm)
        invites.give_bonus(farm,code,inviter['name'],now)
        farm['revision']+=1
        validate_state(farm);await self.u.save(farm)
        await self.u.record(self.p.account_id,'invite-bonus','invite_bonus',before,farm,now)
        return farm

    async def accept_invite(self, code):
        """Typed invitation code (same rules and the same reward as a link)."""
        await self.u.lock('account:'+self.p.account_id)
        me=await self.me()
        await self.u.lock('farm:'+me['id'])
        farm=await self.u.get(me['id'])
        farm=await self._attach_invite(farm,code)
        return dict(invites=await self._invites(farm),coins=farm['coins'])

    async def _invites(self, farm):
        if not hasattr(self.u,'invite_list'):return None
        return invites.view(farm,await self.u.invite_list(farm['id']),self.clock())

    async def _neighbor_reward(self, me, other, now, *, strict=False):
        """Pay both sides atomically for a new or previously unpaid neighbourhood."""
        if not hasattr(self.u,'neighbor_pair_claim'):return '',False
        if strict:
            paid=await self.u.neighbor_pairs_paid(me['id'])
            need(other['id'] not in paid,'already_claimed','Награда за это соседство уже получена.')
            need(invites.neighbor_state(me)['total']<invites.NEIGHBOR['total'] and
                 invites.neighbor_state(other)['total']<invites.NEIGHBOR['total'],
                 'neighbor_reward_limit','Общий лимит наград за соседей исчерпан.')
        if not (invites.neighbor_room(me,now) and invites.neighbor_room(other,now)):
            if strict:raise FarmError('neighbor_reward_limit','Сегодня лимит наград у одного из вас исчерпан. Попробуй позже.')
            return ' Лимит наград за соседей исчерпан у одного из вас — награда не выдана.',False
        if not await self.u.neighbor_pair_claim(me['id'],other['id'],now):
            if strict:raise FarmError('already_claimed','Награда за это соседство уже получена.')
            return '',False
        invites.pay_neighbor(me,other,now);invites.pay_neighbor(other,me,now)
        return f' Награда за соседство: +{invites.NEIGHBOR["reward"]} монет каждому.',True

    async def _pay_invites(self, farm, now):
        """Lazy reward on the inviter's own visit: once per invited farm that reached the level, within the daily/total limits."""
        if not hasattr(self.u,'invite_list'):return
        before=deepcopy(farm)
        for row in await self.u.invite_list(farm['id']):
            if row['rewarded_at'] is None and level(row['xp'])>=INVITE['level'] and invites.room(farm,now):
                if await self.u.invite_mark(row['id'],now):invites.pay_inviter(farm,row['name'],now)
        if farm!=before:
            farm['revision']+=1
            validate_state(farm);await self.u.save(farm)
            await self.u.record(self.p.account_id,'invite:'+str(farm['revision']),'invite_reward',before,farm,now)

    async def me(self):
        farm=await self.u.by_account(self.p.account_id)
        need(farm is not None,'farm_not_started','Сначала открой свою ферму.',404)
        return farm

    async def _village(self, farm):
        """Shared fund counter for the client (own farm only; None until the fund opens or when the store has no counter)."""
        if not hasattr(self.u,'village_peek') or level(farm['xp'])<FUND_LEVEL:
            return None
        now=self.clock();season=economy.season_of(now)
        row=await self.u.village_peek(season)
        if row is None:row=dict(season=season,total=0,goal=await self.u.village_goal(now))
        return dict(season=season,total=row['total'],goal=row['goal'],ends_at=economy.season_end(season))

    async def _claim_village(self, farm, now):
        """Lazy common reward: pay it on the owner's visit when the village counter of a season they joined reached its goal."""
        if not hasattr(self.u,'village_peek'):return
        for season in economy.claimable_seasons(farm):
            row=await self.u.village_peek(season)
            economy.claim_village(farm,season,bool(row and row['total']>=row['goal']),now)

    async def _settle(self, farm, actor=None, own=False):
        before=deepcopy(farm)
        # Normalize the comparison copy too: adding save fields (including
        # home_projects/minigames) is persistence housekeeping, not earned work.
        baseline=upgrade_state(deepcopy(before))
        settle(farm,self.clock())
        if own:await self._claim_village(farm,self.clock())
        if farm!=before:
            farm['revision']+=1
            validate_state(farm)
            await self.u.save(farm)
            # Market housekeeping (a caravan arriving, the daily contracts rolling over) changes no balance:
            # it is saved, but only real work leaves a receipt in the economic ledger.
            quiet={'market','events','revision','economy'}
            if any(farm.get(k)!=baseline.get(k) for k in set(farm)|set(baseline) if k not in quiet):
                # Stable per-version economic receipt for automatically completed work.
                key='auto:'+str(farm['revision'])
                owner=actor or self.p.account_id
                await self.u.record(owner,key,'automation',before,farm,self.clock())
        if own:await self._pay_invites(farm,self.clock())

    async def view(self,farm_id=None):
        me=await self.me()
        try: target_id=str(UUID(str(farm_id or me['id'])))
        except (ValueError,TypeError,AttributeError):
            raise FarmError('not_found','Ферма не найдена.',404)
        await self.u.lock('farm:'+me['id'],'farm:'+target_id)
        me=await self.u.get(me['id'])
        farm=me if target_id==me['id'] else await self.u.get(target_id)
        need(farm is not None and can_visit(me,farm),'not_found','Ферма недоступна.',404)
        await self._settle(me,own=True)
        if farm is not me:
            await self._settle(farm,await self.u.owner_account(farm['id']))
        return dict(farm=project(farm,me,self.clock()),speed=self.speed,village=await self._village(me) if farm is me else None,
                    invites=await self._invites(me) if farm is me else None,
                    address_form=self.p.address_form)

    async def neighbors(self):
        me=await self.me()
        now=self.clock()
        paid=await self.u.neighbor_pairs_paid(me['id'])
        entries=[]
        claimable=pending=0
        for fid,edge in me['neighbors'].items():
            farm=await self.u.get(fid)
            if farm and fid not in me['blocked'] and me['id'] not in farm['blocked']:
                eligible=(edge['status']=='accepted' and
                          farm['neighbors'].get(me['id'],{}).get('status')=='accepted' and fid not in paid)
                room_forever=(invites.neighbor_state(me)['total']<invites.NEIGHBOR['total'] and
                              invites.neighbor_state(farm)['total']<invites.NEIGHBOR['total'])
                ready=eligible and invites.neighbor_room(me,now) and invites.neighbor_room(farm,now)
                waiting=eligible and room_forever and not ready
                claimable+=int(ready);pending+=int(waiting)
                entries.append(dict(id=fid,name=farm['name'],status=edge['status'],can_visit=can_visit(me,farm),
                                    reward_claimable=bool(ready),reward_pending=bool(waiting),
                                    reward_unavailable=bool(eligible and not room_forever)))
        public=[dict(id=f['id'],name=f['name']) for f in await self.u.public_farms()
                if f['id']!=me['id'] and can_visit(me,f) and f['id'] not in me['neighbors']]
        return dict(neighbors=entries,public=public,blocked=list(me['blocked']),
                    claimable_rewards=min(claimable,invites.neighbor_left(me,now)),pending_rewards=pending,
                    reward_per_neighbor=invites.NEIGHBOR['reward'])

    async def history(self):
        me=await self.me()
        return dict(entries=await self.u.history(me['id']))

    async def command(self,key,kind,data,target_id=None):
        need(isinstance(key,str) and re.fullmatch(r'[a-zA-Z0-9_:-]{8,64}',key),'invalid_key','Нет идентификатора команды.',422)
        # Serialize only this exact command key; unrelated commands never get a
        # revision conflict merely because another part of the farm changed.
        await self.u.lock('command:'+self.p.account_id+':'+key)
        me=await self.me()
        try:
            target_id=str(UUID(str(target_id or me['id'])))
        except (ValueError,TypeError,AttributeError):
            raise FarmError('not_found','Ферма не найдена.',404)
        # UUID spelling must not create two different advisory locks for the
        # same row (uppercase/lowercase or alternate UUID notation).
        fingerprint=sha256(json.dumps([kind,target_id,data],sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
        cached=await self.u.receipt(self.p.account_id,key)
        if cached:
            need(cached['fingerprint']==fingerprint,'key_reused','Этот номер уже относится к другому действию.')
            # Receipt contains only the actor's acknowledgement, no secret
            # snapshot from a farm whose permissions could have since changed.
            return deepcopy(cached['result'])
        await self.u.lock('farm:'+me['id'],'farm:'+str(target_id))
        me=await self.u.get(me['id'])
        other=me if target_id==me['id'] else await self.u.get(target_id)
        need(other is not None,'not_found','Ферма не найдена.',404)
        # Materialize past paid work BEFORE the new command, in the same transaction.
        await self._settle(me,own=True)
        if other is not me:
            await self._settle(other,await self.u.owner_account(other['id']))
        before=deepcopy(me);before_other=deepcopy(other)
        now=self.clock()
        mini_kind=kind in {'minigame_start','minigame_answer'}
        if mini_kind:
            need(other is me,'not_owner','Это не твоя ферма.',403)
            question=None
            if kind=='minigame_start':
                if minigames.should_select_question(me,data,now) and self.question_provider is not None:
                    selected=await self.question_provider(self.u.connection)
                    question=selected[0] if selected else None
                notice,changed=minigames.start(me,data,now,question)
            else:
                notice,changed=minigames.answer(me,data,now)
            if not changed:
                result=dict(command_id=key,notice=notice,server_time=now,revision=me['revision'],
                            minigames=minigames.public(me,now))
                await self.u.remember(self.p.account_id,key,fingerprint,result,now)
                return result
            # A newly started or answered game is an owner action. Replays above
            # remain true no-ops, including the activity and daily upkeep state.
            progression.touch(me,now)
            economy.bill(me,now)
        else:
            notice=apply(me,other,kind,data,now,key,self.speed,self.p.address_form)
        neighbor_reward_paid=False
        if kind in {'accept_neighbor','claim_neighbor_reward'}:
            reward_notice,neighbor_reward_paid=await self._neighbor_reward(me,other,now,strict=kind=='claim_neighbor_reward')
            notice+=reward_notice
        # Fund contributions: the farm booked the value; the shared counter is a separate atomic row in the same transaction.
        sent=me['economy']['stats']['fund_village']-before['economy']['stats']['fund_village']
        if sent>0 and hasattr(self.u,'village_add'):
            await self.u.village_add(economy.season_of(now),sent,now)
        me['revision']+=1
        validate_state(me);await self.u.save(me)
        await self.u.record(self.p.account_id,key,kind,before,me,now)
        if me['id']!=other['id'] and other!=before_other:
            other['revision']+=1;validate_state(other);await self.u.save(other)
            await self.u.record(self.p.account_id,key,kind,before_other,other,now)
        result=dict(command_id=key,notice=notice,server_time=now,revision=me['revision'])
        if mini_kind:result['minigames']=minigames.public(me,now)
        if neighbor_reward_paid:result['neighbor_reward_paid']=True
        await self.u.remember(self.p.account_id,key,fingerprint,result,now)
        return result
