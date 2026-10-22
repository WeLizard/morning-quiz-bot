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
from . import economy, invites, undo, minigames, oleg, progression, trip_games
from .sharing import (invite_digest, invite_secret, link_token, new_invite_nonce, MAX_ACTIVE_SHARE_INVITES_PER_FARM,
                      SHARE_INVITE_MAX_USES, SHARE_INVITE_TTL)
from . import wagers

# The client pulses every 10 s, the lease is 25 s: persistence every other pulse is enough to keep it live.
PRESENCE_PERSIST_EVERY=15

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
        await wagers.expire(self.u,farm,self.p.account_id,self.clock())
        await wagers.claim_pending(self.u,farm,self.p.account_id,self.clock())
        projection=project(farm,farm,self.clock());projection['wager']=await wagers.projection(self.u,farm,self.p.account_id,self.clock())
        return dict(farm=projection,catalog=dict(public_catalog(),undo=undo.public_rules(),trip_games=trip_games.public_rules()),speed=self.speed,village=await self._village(farm),
                    invites=await self._invites(farm),address_form=self.p.address_form)

    async def share_link_status(self):
        """Read-only state of the current reusable link (no token is issued), or None."""
        farm=await self.me()
        row=await self.u.share_invite_current(farm['id'],self.clock())
        return dict(uses=row['uses'],max_uses=row['max_uses'],expires_at=row['expires_at']) if row else None

    async def share_link(self, rotate=False):
        """The farm's reusable invite link: the same one until it is full, expires or rotate=True replaces it.

        Only the digest is persisted; the token is recomputed from the server secret and the row's nonce.
        Returns dict(token, uses, max_uses, expires_at).
        """
        await self.u.lock('account:'+self.p.account_id)
        farm=await self.me()
        await self.u.lock('farm:'+farm['id'])
        now=self.clock()
        secret=invite_secret(getattr(self,'invite_secret',None))
        row=None if rotate else await self.u.share_invite_current(farm['id'],now)
        if row is not None:
            token=link_token(secret,farm['id'],row['nonce'])
            if invite_digest(token)==row['token_hash']:
                return dict(token=token,uses=row['uses'],max_uses=row['max_uses'],expires_at=row['expires_at'])
        # Rotation, or a changed secret that cannot rebuild the link: close the old links, issue a new one.
        await self.u.share_invite_expire_all(farm['id'],now)
        nonce=new_invite_nonce()
        token=link_token(secret,farm['id'],nonce)
        await self.u.share_invite_create(invite_digest(token),farm['id'],now+SHARE_INVITE_TTL,now,
                                         MAX_ACTIVE_SHARE_INVITES_PER_FARM,nonce=nonce,max_uses=SHARE_INVITE_MAX_USES)
        return dict(token=token,uses=0,max_uses=SHARE_INVITE_MAX_USES,expires_at=now+SHARE_INVITE_TTL)

    async def _invite_farm(self, code):
        """Resolve a one-use opaque token or a legacy manually-entered UUID."""
        if isinstance(code,str) and re.fullmatch(r'[A-Za-z0-9_-]{43}',code):
            row=await self.u.share_invite(invite_digest(code))
            return str(row['farm_id']) if row and row['uses']<row['max_uses'] and row['expires_at']>self.clock() else None
        try:return str(UUID(str(code)))
        except (ValueError,TypeError,AttributeError):return None

    async def _attach_invite(self, farm, code):
        """Link a FRESH farm to its inviter (any channel: Telegram, web link or typed code) and pay the starting bonus once."""
        if not hasattr(self.u,'invite_add'):return farm
        inviter_id=await self._invite_farm(code)
        need(inviter_id is not None,'invalid_invite','Некорректный код приглашения.',422)
        now=self.clock()
        need(inviter_id!=farm['id'],'self_invite','Нельзя пригласить самого себя.',422)
        need(invites.fresh(farm,now),'invite_late','Приглашение можно ввести только на новой ферме.')
        inviter=await self.u.get(inviter_id)
        need(inviter is not None and await self.u.owner_account(inviter_id)!=self.p.account_id,'invite_unknown','Приглашение не найдено.',404)
        if not await self.u.invite_add(farm['id'],inviter_id,now):return farm
        before=deepcopy(farm)
        invites.give_bonus(farm,inviter_id,inviter['name'],now)
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

    async def join_share_invite(self, token):
        """Explicit recipient action: atomically establish accepted status both ways and pay once."""
        need(isinstance(token,str) and re.fullmatch(r'[A-Za-z0-9_-]{43}',token) is not None,
             'invalid_invite','Некорректная ссылка-приглашение.',422)
        digest=invite_digest(token)
        await self.u.lock('account:'+self.p.account_id)
        me=await self.me()
        await self.u.lock('share-invite:'+digest)
        row=await self.u.share_invite(digest)
        need(row is not None,'invite_unknown','Приглашение не найдено.',404)
        now=self.clock()
        inviter_id=str(row['farm_id'])
        need(inviter_id!=me['id'],'self_invite','Нельзя стать соседом самому себе.',422)
        need(row['expires_at']>now,'invite_expired','Срок приглашения истёк.',410)
        if await self.u.share_invite_used_by(digest,me['id']):
            return dict(neighbor_reward_paid=False,notice='Приглашение уже принято.',
                        neighbors=await self.neighbors())
        need(row['uses']<row['max_uses'],'invite_used',
             'По этой ссылке уже вступило максимум соседей. Попроси у друга новую.',409)
        await self.u.lock('farm:'+me['id'],'farm:'+inviter_id)
        me=await self.u.get(me['id']); other=await self.u.get(inviter_id)
        need(other is not None,'invite_unknown','Приглашение не найдено.',404)
        need(me['id'] not in other['blocked'] and other['id'] not in me['blocked'],
             'blocked','Взаимодействие недоступно.',403)
        own_edge=me['neighbors'].get(other['id']); other_edge=other['neighbors'].get(me['id'])
        already=bool(own_edge or other_edge)
        if already:
            need(own_edge and other_edge and own_edge.get('status')=='accepted' and other_edge.get('status')=='accepted',
                 'invite_state','Сначала разреши текущее приглашение или удали существующее соседство.',409)
            # A neighbor who taps the shared link again takes no place out of the link's limit;
            # an unpaid old neighborhood is claimed with the gift button.
            return dict(neighbor_reward_paid=False,notice='Вы уже соседи.',neighbors=await self.neighbors())
        else:
            need(len(me['neighbors'])<100 and len(other['neighbors'])<100,
                 'neighbors_full','Список соседей заполнен.',409)
        await self._settle(me,own=True)
        await self._settle(other,await self.u.owner_account(other['id']))
        before=deepcopy(me); before_other=deepcopy(other)
        if not already:
            me['neighbors'][other['id']]={'name':other['name'],'status':'accepted'}
            other['neighbors'][me['id']]={'name':me['name'],'status':'accepted'}
            from .domain import event
            event(me,now,f'Ты стал(а) соседом с «{other["name"]}».','social')
            event(other,now,f'{me["name"]} принял(а) приглашение. Теперь вы соседи!','social')
        # Match ordinary accept_neighbor semantics: quota-limited pairs still
        # become neighbours, with the reward left claimable when its limits reset.
        reward_notice,reward_paid=await self._neighbor_reward(me,other,now)
        need(await self.u.share_invite_accept(digest,me['id'],now),'invite_used',
             'По этой ссылке уже вступило максимум соседей. Попроси у друга новую.',409)
        me['revision']+=1; validate_state(me); await self.u.save(me)
        await self.u.record(self.p.account_id,'share-invite:'+digest[:32],'accept_neighbor',before,me,now)
        other['revision']+=1; validate_state(other); await self.u.save(other)
        await self.u.record(self.p.account_id,'share-invite:'+digest[:32],'accept_neighbor',before_other,other,now)
        return dict(neighbor_reward_paid=reward_paid,notice='Теперь вы соседи!'+reward_notice,
                    neighbors=await self.neighbors())

    async def revoke_share_invite(self, token):
        """Expire a link owned by the current farm; neighborhoods made through it stay."""
        need(isinstance(token,str) and re.fullmatch(r'[A-Za-z0-9_-]{43}',token) is not None,
             'invalid_invite','Некорректная ссылка-приглашение.',422)
        digest=invite_digest(token)
        await self.u.lock('account:'+self.p.account_id)
        me=await self.me()
        await self.u.lock('share-invite:'+digest)
        row=await self.u.share_invite(digest)
        need(row is not None and str(row['farm_id'])==me['id'],
             'invite_unknown','Приглашение не найдено.',404)
        need(await self.u.share_invite_revoke(digest,me['id'],self.clock()),
             'invite_expired','Ссылка уже отменена или истекла.',409)
        return dict(revoked=True)

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
            quiet={'market','events','revision','economy','village_errands'}
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
        await wagers.expire(self.u,me,self.p.account_id,self.clock())
        await wagers.claim_pending(self.u,me,self.p.account_id,self.clock())
        if farm is not me:
            await self._settle(farm,await self.u.owner_account(farm['id']))
        projected=project(farm,me,self.clock())
        if farm is me:projected['wager']=await wagers.projection(self.u,me,self.p.account_id,self.clock())
        return dict(farm=projected,speed=self.speed,village=await self._village(me) if farm is me else None,
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

    async def village_presence(self, action, session):
        """Persist one visible village lease; only an earned theft enters the ledger."""
        from . import village_quests
        need(isinstance(action,str) and action in {'enter','pulse','talk','leave'} and isinstance(session,str),
             'invalid_command','Некорректное присутствие.',422)
        try: session=str(UUID(session))
        except (ValueError, TypeError, AttributeError):
            raise FarmError('invalid_command','Некорректное присутствие.',422)
        me=await self.me()
        await self.u.lock('farm:'+me['id'])
        me=await self.u.get(me['id'])
        before=deepcopy(me)
        now=self.clock()
        stolen=village_quests.presence(me,action,session,now)
        if me!=before:
            old_village=before.get('village_errands') or {}
            new_village=me.get('village_errands') or {}
            old_presence=old_village.get('presence')
            new_presence=new_village.get('presence')
            heartbeat_only=(old_presence is not None and new_presence is not None and
                {k:v for k,v in old_presence.items() if k!='last_at'}==
                {k:v for k,v in new_presence.items() if k!='last_at'} and
                all(old_village.get(k)==new_village.get(k) for k in ('quests','theft_next_at','theft_total')))
            if heartbeat_only:
                # Keep the lease alive without rewriting the aggregate or bumping the client-visible revision.
                if new_presence['last_at']-old_presence['last_at']>=PRESENCE_PERSIST_EVERY:
                    if hasattr(self.u,'save_presence'):
                        await self.u.save_presence(me['id'],new_presence)
                    else:
                        await self.u.save(me)
            else:
                if stolen or any(old_village.get(k)!=new_village.get(k) for k in ('theft_next_at','theft_total')):
                    me['revision']+=1
                validate_state(me)
                await self.u.save(me)
                if stolen:
                    await self.u.record(self.p.account_id,'village-theft:'+str(now),'village_theft',before,me,now)
        return dict(stolen=stolen,notice=(f'Лиса Даша стащила {stolen} мон. из кармана!' if stolen else ''),
                    server_time=now,coins=me['coins'],revision=me['revision'])

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
        if kind in {'wager_start','wager_choose','oleg_start','oleg_answer'}:
            need(target_id==me['id'],'not_owner','Это не твоя ферма.',403)
        # UUID spelling must not create two different advisory locks for the
        # same row (uppercase/lowercase or alternate UUID notation).
        fingerprint=sha256(json.dumps([kind,target_id,data],sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
        cached=await self.u.receipt(self.p.account_id,key)
        if cached:
            need(cached['fingerprint']==fingerprint,'key_reused','Этот номер уже относится к другому действию.')
            if kind in {'wager_start','wager_choose','oleg_start','oleg_answer'}:
                await self.u.lock('farm:'+me['id'])
                me=await self.u.get(me['id'])
                need(target_id==me['id'],'not_owner','Это не твоя ферма.',403)
                refreshed=deepcopy(cached['result'])
                if kind in {'wager_start','wager_choose'}:
                    await self._settle(me,own=True)
                    await wagers.expire(self.u,me,self.p.account_id,self.clock())
                    await wagers.claim_pending(self.u,me,self.p.account_id,self.clock())
                    refreshed['wager']=await wagers.projection(self.u,me,self.p.account_id,self.clock())
                else:
                    refreshed['oleg_game']=oleg.public(me,self.clock())
                    refreshed['revision']=me['revision']
                return refreshed
            # Receipt contains only the actor's acknowledgement, no secret
            # snapshot from a farm whose permissions could have since changed.
            return deepcopy(cached['result'])
        await self.u.lock('farm:'+me['id'],'farm:'+str(target_id))
        me=await self.u.get(me['id'])
        other=me if target_id==me['id'] else await self.u.get(target_id)
        need(other is not None,'not_found','Ферма не найдена.',404)
        # Materialize past paid work BEFORE the new command, in the same transaction.
        await self._settle(me,own=True)
        await wagers.expire(self.u,me,self.p.account_id,self.clock())
        await wagers.claim_pending(self.u,me,self.p.account_id,self.clock())
        if other is not me:
            await self._settle(other,await self.u.owner_account(other['id']))
        before=deepcopy(me);before_other=deepcopy(other)
        now=self.clock()
        mini_kind=kind in {'minigame_start','minigame_answer'}
        wager_kind=kind in {'wager_start','wager_choose'}
        oleg_kind=kind in {'oleg_start','oleg_answer'}
        if wager_kind:
            need(other is me,'not_owner','Это не твоя ферма.',403)
            notice,ledger_kind=await wagers.command(self.u,me,self.p.account_id,kind,data,now)
        elif mini_kind:
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
        elif oleg_kind:
            need(other is me,'not_owner','Это не твоя ферма.',403)
            notice,changed=(oleg.start(me,data,now) if kind=='oleg_start'
                            else oleg.answer(me,data,now))
            if not changed:
                result=dict(command_id=key,notice=notice,server_time=now,revision=me['revision'],
                            oleg_game=oleg.public(me,now))
                await self.u.remember(self.p.account_id,key,fingerprint,result,now)
                return result
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
        await self.u.record(self.p.account_id,key,ledger_kind if wager_kind else kind,before,me,now)
        if me['id']!=other['id'] and other!=before_other:
            other['revision']+=1;validate_state(other);await self.u.save(other)
            await self.u.record(self.p.account_id,key,kind,before_other,other,now)
        await wagers.claim_pending(self.u,me,self.p.account_id,now)
        result=dict(command_id=key,notice=notice,server_time=now,revision=me['revision'])
        if mini_kind:result['minigames']=minigames.public(me,now)
        if oleg_kind:result['oleg_game']=oleg.public(me,now)
        if wager_kind:result['wager']=await wagers.projection(self.u,me,self.p.account_id,now)
        if neighbor_reward_paid:result['neighbor_reward_paid']=True
        # Wager projections may reveal a settled result to the live owner response;
        # receipts are replay acknowledgements and must never persist either cup.
        receipt_result={k:v for k,v in result.items() if k!='wager'} if wager_kind else result
        await self.u.remember(self.p.account_id,key,fingerprint,receipt_result,now)
        return result
