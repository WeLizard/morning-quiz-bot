/* Night Case player controller. All permissions, costs, clues and transitions come from the server.
   Reuses the approved NightCity kit and QW shell. No local game rules, secret persistence or audio. */
(function (root) {
'use strict';
const id = () => root.crypto?.randomUUID?.() || 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, char => {
    const value = Math.floor(Math.random() * 16); return (char === 'x' ? value : (value & 3) | 8).toString(16);
});
const text = value => typeof value === 'string' ? value : '';
const bodyText = value => text(value?.text);
const arr = value => Array.isArray(value) ? value : [];
const copy = value => JSON.parse(JSON.stringify(value));
const pick = (value, keys) => Object.fromEntries(keys.filter(key => value && Object.hasOwn(value, key)).map(key => [key, value[key]]));
function playerView(value) {
    const safe = pick(value, ['game_id', 'mode', 'server_now', 'runtime_status', 'final_summary', 'lobby', 'menu', 'history_seats', 'selected_original_account_id']);
    safe.public = pick(value?.public, ['clock', 'world', 'art', 'locations', 'players', 'npcs', 'board', 'observations', 'modules', 'hearing', 'final', 'flags', 'locks']);
    // Only shared scenes leave the public chronicle: id, window, text and picture.
    safe.public.scenes = arr(value?.public?.chronicle).filter(entry => entry?.kind === 'scene')
        .map(entry => ({event_id: entry.event_id, window_idx: entry.window_idx, body: entry.payload?.body, art: entry.art}));
    safe.self = value?.self ? pick(value.self, ['account_id', 'character_id', 'role', 'status', 'location', 'ap', 'actor_seq', 'faction', 'goal', 'secrets', 'truth', 'observations', 'nearby', 'personal', 'communication', 'modules', 'postmortem', 'finished_window', 'final_ballot']) : null;
    return safe;
}
function artPointer(binding) {
    return /^[a-f0-9]{64}$/.test(binding?.manifest_sha256) && binding.manifest_url === `/app/night/packs/${binding.manifest_sha256}/assets.json` ? binding.manifest_url : null;
}
function assetManifest(value, world, binding) {
    const result = new Map();
    const pointer = artPointer(binding);
    if (!pointer || !/^[a-z][a-z0-9_]{1,31}$/.test(world) || value?.schema !== 'nc-assets/2' || value.world !== world) return result;
    const files = value.files;
    if (!files || Array.isArray(files) || typeof files !== 'object' || Object.keys(files).length > 1000) return result;
    const relative = /^assets\/[a-z0-9_-]+\.webp$/;
    if (Object.entries(files).some(([path, hash]) => !relative.test(path) || !/^[a-f0-9]{64}$/.test(hash))) return result;
    const allowed = path => typeof path === 'string' && relative.test(path) && Object.hasOwn(files, path);
    const url = path => pointer.slice(0, -'assets.json'.length) + path;
    for (const [key, row] of Object.entries(value.assets || {}).slice(0, 1000)) {
        if (!/^[a-z][a-z0-9_]{1,63}$/.test(key) || !allowed(row?.url)) continue;
        const variants = {};
        for (const period of ['morning', 'day', 'evening', 'night']) if (allowed(row.variants?.[period])) variants[period] = url(row.variants[period]);
        result.set(key, {url: url(row.url), alt: text(row.alt).slice(0, 300), variants});
    }
    return result;
}
const canonical = value => Array.isArray(value) ? value.map(canonical) : value && typeof value === 'object' ? Object.fromEntries(Object.keys(value).sort().map(key => [key, canonical(value[key])])) : value;
async function verifiedManifest(value, world, binding) {
    if (!artPointer(binding) || !root.crypto?.subtle) return new Map();
    const bytes = new TextEncoder().encode(JSON.stringify(canonical(value)));
    const hash = [...new Uint8Array(await root.crypto.subtle.digest('SHA-256', bytes))].map(byte => byte.toString(16).padStart(2, '0')).join('');
    return hash === binding.manifest_sha256 ? assetManifest(value, world, binding) : new Map();
}
const errors = {
    actor_stale: 'Состояние изменилось. Обнови дело и выбери действие снова.',
    window_closed: 'Окно завершилось. Доступные действия обновлены.',
    proposal_stale: 'Предложение устарело. Выбери действие снова.',
    command_conflict: 'Запрос уже использован. Обнови дело перед новым действием.',
    unavailable: 'Эта партия или запись тебе недоступна.',
    runtime_delayed: 'Сервис восстанавливается. Повтори запрос позже.',
    game_interrupted: 'Партия приостановлена.',
    game_quarantined: 'Партия временно приостановлена для проверки.',
    players_not_ready: 'Сначала все должны подтвердить готовность.',
    unsupported_count: 'Нужны 4, 5, 8 или 12 игроков.',
    rate_limited: 'Слишком много запросов. Подожди немного.',
};
const errorText = error => error?.network ? 'Нет связи. Повтори тот же запрос — действие не применится дважды.' : errors[error?.code] || 'Действие сейчас недоступно. Обнови дело и попробуй снова.';

async function http(path, {method = 'GET', body, identity = 'guest', signal, expectedViewer} = {}) {
    const controller = new AbortController();
    const abort = () => controller.abort();
    signal?.addEventListener('abort', abort, {once: true});
    const timer = setTimeout(abort, 12000);
    const headers = method === 'GET' ? {} : {'Content-Type': 'application/json', 'X-Guest-CSRF': '1', 'X-Mini-CSRF': '1'};
    if (expectedViewer) headers['X-Night-Expected-Viewer'] = expectedViewer;
    try {
        const response = await fetch(`${path}${path.includes('?') ? '&' : '?'}identity=${encodeURIComponent(identity)}`, {
            method, headers, credentials: 'same-origin', cache: 'no-store', signal: controller.signal,
            ...(method === 'GET' ? {} : {body: JSON.stringify(body ?? {})}),
        });
        if (response.status === 204) return null;
        let value; try { value = await response.json(); } catch { value = null; }
        if (!response.ok || !value) {
            const error = new Error('night_case_request');
            error.status = response.status; error.code = text(value?.code);
            throw error;
        }
        return value;
    } catch (error) {
        if (error.status) throw error;
        const lost = new Error('night_case_network'); lost.network = true; throw lost;
    } finally { clearTimeout(timer); signal?.removeEventListener('abort', abort); }
}

/* A lost response keeps exactly the same path/body/command ID. One pending write per controller. */
function createOutbox(send) {
    let pending = null, busy = false;
    return {
        get pending() { return pending ? copy(pending) : null; },
        get busy() { return busy; },
        async send(path, body) {
            if (busy || pending) throw new Error('pending_write');
            pending = {path, body: copy(body)};
            return this.retry();
        },
        async retry() {
            if (!pending || busy) throw new Error('no_pending_write');
            busy = true;
            try {
                const result = await send(pending.path, pending.body);
                pending = null; return result;
            } catch (error) {
                if (error.status && error.status < 500 && error.status !== 429) pending = null;
                throw error;
            } finally { busy = false; }
        },
        clear() { pending = null; busy = false; },
    };
}

function envelope(view, kind, params, commandId = id()) {
    return {command_id: commandId, kind, params: copy(params), window_idx: view.public.clock.window_idx,
        window_seq: view.public.clock.window_seq, actor_seq: view.self.actor_seq};
}

let active = null;
function open(options) {
    active?.close();
    const kit = root.NightCity?.kit, Q = root.QW, host = options.host;
    if (!kit || !Q) throw new Error('night_case_shell_required');
    let alive = true, locked = false, epoch = 0, poll = null, timer = null, reading = false, identityReading = false, commandBusy = false;
    let view = null, room = null, game = null, tab = 'place', notice = '', proposal = null, sending = '';
    let boot = options.bootstrap, selectedCase = null, ownDraft = '', channel = 'square', recipients = [], invitation = null;
    let viewer = boot?.viewer_account_id || null;
    const pages = {public: {items: [], next_cursor: null}, self: {items: [], next_cursor: null}, messages: {items: [], next_cursor: null}};
    const cursors = new Set(), controller = new AbortController();
    let assets = new Map(), assetWorld = null;
    let selectedOriginal = '';
    const historySelection = () => selectedOriginal ? `&original_account_id=${encodeURIComponent(selectedOriginal)}` : '';
    function clearHistory() { cursors.clear(); for (const page of Object.values(pages)) { page.items.length = 0; page.next_cursor = null; } }
    const live = () => alive && !locked && options.isCurrent?.() !== false;
    const request = async (path, init = {}) => {
        if (!live()) throw new Error('night_controller_closed');
        if (!viewer && path !== '/api/night-case/bootstrap') { invalidate(); throw new Error('night_viewer_missing'); }
        const generation = epoch;
        try {
            const result = await (options.request || http)(path, {...init, identity: options.identity || 'guest', signal: controller.signal, expectedViewer: viewer});
            if (!live() || generation !== epoch) throw new Error('night_controller_closed');
            return result;
        } catch (error) {
            if (live() && (error.code === 'profile_changed' || [401, 403].includes(error.status) ||
                error.status === 404 && /^\/api\/night-case\/games\/[^/]+\/view(?:\?|$)/.test(path))) invalidate();
            throw error;
        }
    };
    const outbox = createOutbox((path, payload) => request(path, {method: 'POST', body: payload}));
    const api = suffix => `/api/night-case/games/${encodeURIComponent(game)}/${suffix}`;
    const el = (tag, cls, value) => { const node = document.createElement(tag); if (cls) node.className = cls; if (value != null) node.textContent = String(value); return node; };
    const put = (node, ...children) => { for (const child of children.flat(Infinity)) if (child != null) node.append(child); return node; };
    const p = value => el('p', 'nc-note', value);
    const status = value => { const node = el('p', 'nc-note ncase-sending', value); node.setAttribute('role', 'status'); return node; };
    const button = (label, callback, kind = 'secondary') => kit.button(label, () => Promise.resolve(callback()).catch(fail), {kind, disabled: outbox.busy});
    const panel = (title, ...children) => kit.panel({title}, ...children);
    const field = (label, value = '', multi = false) => {
        const input = el(multi ? 'textarea' : 'input', 'nc-field'); input.value = value;
        input.setAttribute('aria-label', label); input.maxLength = multi ? 1000 : 120;
        return {input, node: put(el('label', 'ncase-field'), el('span', null, label), input)};
    };
    const choose = (label, choices, value) => {
        const select = el('select', 'nc-field'); select.setAttribute('aria-label', label);
        for (const item of choices) { const option = el('option', null, item.label); option.value = item.id; select.append(option); }
        if (value != null) select.value = value;
        return {input: select, node: put(el('label', 'ncase-field'), el('span', null, label), select)};
    };
    const displayName = row => row?.title || row?.name || 'Участник';
    const nameOf = char => displayName([...arr(view?.public?.players), ...arr(view?.public?.npcs), ...arr(view?.self?.nearby)]
        .find(row => row.character_id === char));
    const choiceList = () => arr(view?.menu).filter(row => row.kind === 'choice' && row.quote);
    const formList = () => arr(view?.menu).filter(row => row.kind === 'form');
    // «Выслушать дворецкого · Дворецкий»: the speaker is appended only when the label does not already name them.
    const mentions = (label, title) => { const stem = text(title).toLowerCase().slice(0, Math.max(4, text(title).length - 2)); return Boolean(stem) && text(label).toLowerCase().includes(stem); };
    const actionButton = (row, label = row.npc_title && !mentions(row.label, row.npc_title) ? `${row.label} · ${row.npc_title}` : row.label) => button(`${label}${row.quote.cost ? ` · ${row.quote.cost} ОД` : ''}`, () => selectAction(row, label));
    const female = () => view?.self?.role?.gender === 'f';
    const said = (male, fem) => female() ? fem : male;
    const observationTitle = observationId => [...arr(view?.public?.observations), ...arr(view?.self?.observations)].find(item => item.observation_id === observationId)?.title;
    // Zero-cost bookkeeping needs no «Стоимость: 0 ОД» step: the proposal is confirmed right away.
    const instant = new Set(['seen', 'finish_window']);
    let info = '';
    const receipts = {claim: 'Версия опубликована на доске.', accuse: 'Обвинение предъявлено: открыто слушание.', vote: 'Твой голос на слушании записан.', final_vote: 'Твой голос записан. Его можно изменить, пока слушание не закрылось.',
        pin: 'Улика опубликована на доске.', finish_window: 'Окно завершено.', archive_request: 'Запрос отправлен. Ответ придёт в следующем окне — его покажут в хронике и досье.', seen: 'Отмечено: ты за столом.'};

    function invalidate() {
        if (locked || !alive) return;
        locked = true; epoch++; controller.abort(); clearInterval(poll); timer?.stop(); timer = null;
        view = proposal = room = game = boot = invitation = viewer = null;
        ownDraft = selectedOriginal = notice = ''; recipients = []; channel = 'square'; selectedCase = null;
        outbox.clear(); clearHistory(); assets.clear(); assetWorld = null;
        Q.nav.pop?.('night-case-section'); Q.menu.register([], 'Ночной город');
        const header = kit.header(); header.node.classList.add('ncase-bar');
        header.set({eyebrow: 'Ночной город', title: 'Доступ к делу изменился'});
        host.replaceChildren(header.node, put(el('main', 'nc-main ncase-main'), panel('Открой дело заново',
            p('Профиль или доступ изменились. Вернись через ⚙ в главное меню, войди в нужный профиль и снова открой дело.'))));
    }

    function fail(error) {
        if (!live()) return;
        notice = errorText(error);
        if (!view && !room) frame([panel('Связь с делом', p(notice), kit.row(button('Повторить', () => game ? refresh() : initialize())))]);
        else render();
    }
    function frame(children, title = 'Усадьба') {
        if (!live()) return;
        timer?.stop(); timer = null;
        const header = kit.header(), clock = view?.public?.clock;
        header.node.classList.add('ncase-bar');
        kit.pageScene?.({slot: game ? 'day' : null, shell: game ? 'table' : 'entry', time: sceneTime()});
        if (clock?.closes_at && !view?.public?.final) timer = kit.timer({endsAt: Date.parse(clock.closes_at) / 1000,
            serverNow: Date.parse(view.server_now) / 1000, alive: live, onExpire: refresh});
        header.set({eyebrow: 'Ночной город', title, clock: timer?.clock});
        const main = put(el('main', 'nc-main ncase-main'), ...children);
        if (info && !notice) main.prepend(kit.alert({tone: 'ok', icon: 'check', title: info}));
        if (notice) main.prepend(kit.alert({title: notice}));
        if (outbox.busy && !proposal?.sending) main.prepend(status(`${sending ? sending + ': ' : ''}отправляем…`));
        if (outbox.pending && !outbox.busy) main.prepend(kit.netBanner({text: 'Запрос ещё не подтверждён сервером', onRetry: () => retry().catch(fail)}));
        host.replaceChildren(header.node, main); host.dataset.page = 'night';
    }
    function sceneTime() {
        if (!view?.server_now) return 'day';
        try {
            const hour = Number(new Intl.DateTimeFormat('en', {timeZone: view.public?.clock?.timezone || 'UTC', hourCycle: 'h23', hour: '2-digit'}).format(new Date(view.server_now)));
            return hour < 6 || hour >= 21 ? 'night' : hour < 11 ? 'morning' : hour < 17 ? 'day' : 'evening';
        } catch { return 'day'; }
    }
    function menu() {
        Q.menu.register([
            {id: 'night-case-rules', label: 'Правила дела', onSelect: () => showTab('rules')},
            {id: 'night-case-refresh', label: 'Обновить связь', onSelect: () => refresh()},
            ...(view?.self && choiceList().some(row => row.quote.kind === 'forfeit') ? [{id: 'night-case-leave', label: 'Покинуть дело', danger: true, onSelect: () => confirmForfeit()}] : []),
        ], 'Ночной город');
    }
    function showTab(next) {
        if (next !== 'place' && tab === 'place') Q.nav.push?.({id: 'night-case-section', title: next, onBack: () => { tab = 'place'; render(); return true; }});
        else if (next === 'place' && tab !== 'place') Q.nav.pop?.('night-case-section');
        tab = next; render();
    }
    async function mutate(path, payload) {
        if (outbox.pending || outbox.busy) return;
        notice = ''; info = ''; render();
        const result = await outbox.send(path, payload);
        if (!live()) return result;
        if (result?.receipt?.accepted === false) notice = errors[result.receipt.code] || 'Сервер не применил действие. Выбери доступный вариант снова.';
        return result;
    }
    async function retry() {
        const pending = outbox.pending;
        const result = await outbox.retry();
        if (!live()) return;
        notice = result?.receipt?.accepted === false ? 'Сервер не применил действие.' : '';
        if (result?.kind === 'proposal') proposal = {...result.proposal, label: 'Подтвердить выбранное действие'};
        if (pending?.path?.endsWith('/confirm') && result?.receipt) proposal = null;
        if (result?.view?.game_id) game = result.view.game_id;
        if (!game && result?.id && pending?.path?.startsWith('/api/guest/rooms')) return enterRoom(result);
        await refresh();
    }
    async function command(kind, params) {
        if (!view?.self || commandBusy || outbox.pending || outbox.busy) return null;
        commandBusy = true;
        try {
            await request(api('quote'), {method: 'POST', body: {kind, params}});
            const result = await mutate(api('commands'), envelope(view, kind, params));
            if (result?.receipt?.accepted === true && receipts[kind]) info = receipts[kind];
            await refresh();
            return result;
        } finally { commandBusy = false; }
    }
    async function selectAction(row, label = row.label) {
        if (row.quote.kind === 'forfeit') return confirmForfeit();
        sending = label; info = '';
        try {
            const value = await mutate(api('intent'), {request_id: id(), selection_id: row.quote.selection_id, text: null});
            if (value?.kind !== 'proposal') return;
            proposal = {...value.proposal, label, kind: row.quote.kind};
            if (instant.has(row.quote.kind)) return await confirmProposal();
        } finally { if (!proposal?.sending) sending = ''; }
        render();
    }
    async function confirmProposal() {
        if (!proposal || proposal.sending) return;
        const sent = proposal;
        proposal = {...sent, sending: true}; sending = sent.label || 'Действие';
        try {
            const result = await mutate(api('confirm'), {proposal_id: sent.proposal_id});
            if (result?.receipt?.accepted !== false && receipts[sent.kind]) info = receipts[sent.kind];
        } finally {
            // The dialog leaves at once; the fresh view arrives after.
            proposal = null; sending = ''; render();
        }
        await refresh();
    }
    function confirmForfeit() {
        proposal = {forfeit: true, label: 'Покинуть дело?'}; render();
    }
    function confirmation() {
        if (!proposal) return null;
        if (proposal.sending) return panel(proposal.label || 'Подтвердить действие', status('Отправляем…'));
        return panel(proposal.label || 'Подтвердить действие',
            p(proposal.forfeit ? 'Ты прекратишь участие. Назад в эту партию вернуться нельзя; ранее разрешённая история сохранится.' : `Стоимость: ${Number(proposal.cost) || 0} ОД. До подтверждения действие не применяется.`),
            kit.row(button('Отмена', () => { proposal = null; render(); }), button('Подтвердить', async () => {
                if (proposal.forfeit) { proposal = null; await command('forfeit', {}); }
                else await confirmProposal();
            }, proposal.forfeit ? 'danger' : 'primary')));
    }
    async function loadHistory(stream, more = false) {
        if (!game) return;
        const generation = epoch;
        const state = pages[stream], cursor = more ? state.next_cursor : null;
        if (more && !cursor || cursor && cursors.has(stream + cursor)) return;
        const value = await request(api(`history?stream=${stream}&limit=50${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}${historySelection()}`));
        if (!live() || generation !== epoch) return;
        const merged = more ? [...state.items, ...arr(value.items)] : arr(value.items);
        const seen = new Set(); state.items = merged.filter(row => { const key = row.event_id || row.id; if (!key || seen.has(key)) return false; seen.add(key); return true; });
        state.next_cursor = value.next_cursor || null;
        if (cursor) cursors.add(stream + cursor);
    }
    async function refresh({preserveUI = false} = {}) {
        if (!live() || reading) return;
        const generation = epoch;
        reading = true;
        try {
            if (game) {
                const value = await request(api(`view${selectedOriginal ? '?original_account_id=' + encodeURIComponent(selectedOriginal) : ''}`));
                if (!live() || generation !== epoch) return;
                // Focused drafts and pending confirmations retain their exact nodes.
                // This read still checks both the viewer fence and current game ACL.
                if (preserveUI) return;
                view = playerView(value);
                const world = view.public?.world, pointer = artPointer(view.public?.art);
                if (assetWorld !== pointer) {
                    assetWorld = pointer; assets = new Map();
                    try {
                        const manifest = pointer ? await request(pointer) : null;
                        if (!live() || generation !== epoch) return;
                        assets = manifest ? await verifiedManifest(manifest, world, view.public.art) : new Map();
                    } catch { /* Missing export is an image-free view, never a guessed file or hidden case lookup. */ }
                }
                if (tab === 'chat') await loadHistory('messages');
            }
            render();
        } catch (error) { if (!preserveUI) fail(error); }
        finally { reading = false; }
    }
    async function identityProbe() {
        if (!live() || !viewer || identityReading) return;
        identityReading = true;
        try {
            const result = await request('/api/night-case/bootstrap');
            if (result.viewer_account_id !== viewer || result.enabled !== true) invalidate();
        }
        catch { /* The request fence already purges lost identity; transient failure keeps drafts. */ }
        finally { identityReading = false; }
    }
    function backgroundPoll() {
        if (!live()) { close(); return; }
        if (document.hidden || !viewer) return;
        // An in-flight view already checks game ACL. Probe identity cheaply without
        // starting another projection; otherwise one view per poll checks both.
        if (!game || reading) return identityProbe();
        const editing = ['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName);
        return refresh({preserveUI: Boolean(editing || proposal || outbox.busy || outbox.pending)});
    }
    async function enterRoom(next) {
        epoch++; room = next; view = null; proposal = null;
        selectedOriginal = ''; clearHistory();
        room = await request(`/api/guest/rooms/${encodeURIComponent(room.id)}`);
        const current = await request(`/api/rooms/${encodeURIComponent(room.id)}/night-case/current`);
        if (!live()) return;
        game = current.game_id || null;
        if (game) await refresh(); else renderRoom();
    }
    async function entry() {
        epoch++; game = null; room = null; view = null; proposal = null;
        selectedOriginal = ''; clearHistory();
        const result = await request('/api/guest/rooms');
        if (!live()) return;
        const rooms = panel('Твои комнаты', ...arr(result.items).map(item =>
            button(item.title || 'Комната', () => enterRoom(item))));
        if (!arr(result.items).length) rooms.append(p('Создай комнату и пригласи друзей. Дело начнётся, когда соберутся 4, 5, 8 или 12 готовых игроков.'));
        const title = field('Название комнаты');
        const code = field('Код или ссылка приглашения');
        const legacy = boot?.capabilities?.legacy_mafia === true && typeof options.openLegacy === 'function'
            ? panel('Классическая Мафия', p('Столы с дневным обсуждением и ночными действиями, в комнатах и Telegram-группах.'),
                kit.stack(button('Классическая Мафия', () => { if (live()) options.openLegacy(); }))) : null;
        frame([kit.scene({shell: 'entry', size: 'tall', title: 'Хозяин исчез', text: 'Запертая библиотека, метель и двадцать домашних тайн. Одно дело на неделю: играй в удобное время.'}), ...(legacy ? [legacy] : []), rooms,
            panel('Создать комнату', title.node, kit.stack(button('Создать', async () => {
                const value = await mutate('/api/guest/rooms', {request_id: id(), title: title.input.value});
                if (value) await enterRoom(value);
            }))),
            panel('Принять приглашение', code.node, kit.stack(button('Войти в комнату', async () => {
                const parsed = root.NightCity.parseInvite(code.input.value);
                if (parsed?.roomId) return enterRoom({id: parsed.roomId, title: 'Комната'});
                const token = parsed?.code || code.input.value.trim();
                const params = /^[A-Za-z0-9_-]{43}$/.test(token) ? {invite_code: token} : {short_code: token};
                const value = await mutate('/api/guest/rooms/join', params);
                if (value) await enterRoom(value);
            })))], 'Ночной город');
    }
    function renderRoom() {
        if (room?.role !== 'owner') return frame([panel(room?.title || 'Комната', p('Владелец комнаты ещё не открыл стол. После открытия здесь появится явное присоединение к делу.'), kit.row(button('Проверить стол', () => enterRoom(room))))]);
        const cases = arr(boot?.cases);
        if (!cases.length) return frame([panel('Дело пока недоступно', p('Проверенные дела ещё не открыты для этой комнаты.'))], room?.title || 'Комната');
        const choice = choose('Дело', cases.map(item => ({id: `${item.id}:${item.version}`, label: item.title})), selectedCase);
        const zones = [...new Set(cases.flatMap(item => arr(item.timezones)))];
        const zone = choose('Часовой пояс окон', zones.map(value => ({id: value, label: value})), zones[0]);
        frame([kit.scene({shell: 'rooms', title: room.title || 'Комната', text: 'Выбери дело. Участники комнаты отдельно присоединяются к его столу.'}),
            panel('Начать сбор игроков', choice.node, zone.node, kit.stack(button('Создать стол', async () => {
                selectedCase = choice.input.value;
                const selected = cases.find(item => `${item.id}:${item.version}` === selectedCase);
                const result = await mutate(`/api/rooms/${encodeURIComponent(room.id)}/night-case/lobby`, {command_id: id(), expected_lobby_revision: 0,
                    params: {case_id: selected.id, case_version: selected.version, timezone: zone.input.value}});
                if (result?.view) { game = result.view.game_id; await refresh(); }
            }, 'primary')))], room.title || 'Комната');
    }
    async function lobbyCommand(path, params = {}) {
        const result = await mutate(api(path), {command_id: id(), expected_lobby_revision: view.lobby.lobby_revision, params});
        if (path === 'leave') return entry();
        if (result) await refresh();
    }
    function lobby() {
        const data = view.lobby, own = arr(data.seats).find(row => row.seat === data.self_seat);
        const name = field('Имя в этой партии', own?.name || '');
        const address = choose('Как обращаться в этой партии', [{id: 'n', label: 'Без рода'}, {id: 'm', label: 'Он'}, {id: 'f', label: 'Она'}], data.self?.address_form || 'n');
        const buttons = data.self_seat ? [button(own?.ready ? 'Изменить имя и готовность' : 'Я готов', () => lobbyCommand('ready', {name: name.input.value, address_form: address.input.value, ready: !own?.ready})),
            ...(data.can_start ? [button('Начать дело', () => lobbyCommand('start'), 'primary')] : [])] : [button('Присоединиться к столу', () => lobbyCommand('join'), 'primary')];
        return [kit.scene({slot: 'lobby', title: data.case?.title || 'Собираем стол', text: `${data.seats.length} из 12 игроков. Стартуют 4, 5, 8 или 12; каждый подтверждает готовность.`}),
            panel('Стол игроков', kit.seats(arr(data.seats).map(item => ({name: item.name, line: item.ready ? 'Готов' : 'Ещё не готов', me: item.seat === data.self_seat})))),
            panel('Твоё место', ...(data.self_seat ? [name.node, address.node] : []), kit.stack(...buttons)),
            ...(room?.role === 'owner' ? [invitePanel()] : []),
            ...(data.self_seat ? [panel('Выход', kit.stack(button('Покинуть сбор', () => { proposal = {leaveLobby: true, label: 'Покинуть сбор игроков?'}; render(); }, 'danger')))] : [])];
    }
    function invitePanel() {
        const create = button('Создать приглашение', async () => {
            create.disabled = true;
            try {
                invitation = await request(`/api/guest/rooms/${encodeURIComponent(room.id)}/invites`, {method: 'POST', body: {expires_in_seconds: 86400, max_uses: 12}});
                render();
            } finally { create.disabled = false; }
        });
        if (!invitation) return panel('Пригласить друзей', p('Ссылка добавляет в комнату. Каждый отдельно присоединится к столу; в Telegram-чат она никого не добавляет.'), kit.row(create));
        const link = field('Ссылка в комнату', invitation.web_url || ''); link.input.readOnly = true;
        return panel('Пригласить друзей', kit.ticket({code: invitation.short_code, onCopy: async code => { await navigator.clipboard.writeText(code); notice = 'Код скопирован.'; render(); }}),
            link.node, kit.row(button('Скопировать ссылку', async () => { await navigator.clipboard.writeText(link.input.value); notice = 'Ссылка скопирована.'; render(); })),
            p('Отправь код или ссылку друзьям. Присоединение к партии остаётся отдельным действием.'));
    }
    function navigation() {
        return put(el('nav', 'qw-btn-row ncase-tabs'), ...[['place', 'Место'], ['self', 'Досье'], ['board', 'Улики'], ['chat', 'Беседа'], ['history', 'Хроника']].map(([key, label]) => {
            const control = button(label, async () => { showTab(key); if (key === 'chat') { await loadHistory('messages'); render(); } if (key === 'history') { await loadHistory('public'); await loadHistory('self'); render(); } });
            control.setAttribute('aria-current', tab === key ? 'page' : 'false'); return control;
        }));
    }
    function role() {
        const own = view.self, data = own.role || {};
        // Portrait, title and alt follow the look sealed for this party (role.art is the look's art).
        const artwork = assets.get(data.art?.asset_id);
        const portrait = artwork ? el('img', 'ncase-role-portrait') : null;
        if (portrait) { portrait.src = artwork.url; portrait.alt = text(data.art?.alt).slice(0, 300) || artwork.alt || data.title || 'Портрет роли'; }
        return panel('Твоё досье', kit.roleBadge({title: data.title || 'Твоя роль', faction: own.faction, line: 'Видишь только ты'}),
            portrait,
            p(bodyText(data.bio)), p(bodyText(own.goal?.body)), el('h3', 'nc-h3', 'Как засчитывается цель'), p(bodyText(own.goal?.criteria)),
            ...arr(own.secrets).map(item => kit.secret(bodyText(item))),
            ...(own.truth ? [el('h3', 'nc-h3', 'Что ты знаешь о случившемся'), kit.secret(bodyText(own.truth.motive)), kit.secret(bodyText(own.truth.method))] : []),
            ...arr(own.personal?.work_progress).map(item => p(`Этапов работы завершено: ${item.completed_stages.length}`)),
            ...arr(own.modules?.archive_requests?.requests).map(item => p(item.status === 'pending' ? 'Запрос отправлен. Ответ придёт в следующем игровом окне.' : 'Архивный ответ сохранён в твоей хронике.')));
    }
    // Event and finale pictures: only assets of the verified pack, alt from the case.
    function sceneArt(art, fallback) {
        const artwork = assets.get(art?.asset_id);
        if (!artwork) return null;
        return sceneImage(artwork.url, text(art?.alt).slice(0, 300) || artwork.alt || fallback);
    }
    // The played variant's finale is not in the public pack: after the final the server gives
    // its sealed address (named by the file's sha256). Nothing else is accepted.
    function sealedArt(art, fallback) {
        const url = typeof art?.url === 'string' && /^\/app\/night\/sealed\/[a-f0-9]{64}\.webp$/.test(art.url) ? art.url : null;
        return url ? sceneImage(url, text(art?.alt).slice(0, 300) || fallback) : null;
    }
    function sceneImage(url, alt) {
        const image = el('img', 'ncase-scene-art');
        image.src = url; image.alt = alt;
        image.loading = 'lazy';
        return image;
    }
    const sceneOf = eventId => arr(view?.public?.scenes).find(entry => entry.event_id === eventId);
    function place() {
        const own = view.self, location = arr(view.public.locations).find(item => item.id === own.location);
        const over = Boolean(view.public.final || view.final_summary);
        const moves = choiceList().filter(row => row.quote.kind === 'move');
        const acts = choiceList().filter(row => ['act', 'talk', 'archive_request', 'story_reply'].includes(row.quote.kind));
        const nearby = arr(own.nearby).filter(row => row.character_id !== own.character_id);
        const scene = put(el('section', 'nc-hero short'), put(el('div', 'copy'), el('h2', null, location?.name || 'Усадьба'), p(bodyText(location?.body)), over ? null : p(`Осталось действий: ${own.ap}`)));
        const artwork = assets.get(location?.art?.asset_id);
        scene.style?.setProperty('--img', artwork ? `url(${artwork.variants[sceneTime()] || artwork.url})` : 'none');
        if (over) return [scene];
        const window_ = view.public.clock?.window_idx;
        const current = arr(view.public.scenes).filter(entry => entry.window_idx === window_).at(-1);
        const shared = current ? panel('Сейчас в усадьбе', sceneArt(current.art, 'Сцена окна'), p(bodyText(current.body))) : null;
        const waiting = arr(own.modules?.archive_requests?.requests).filter(item => item.status === 'pending');
        const free = boot?.capabilities?.free_intent === true ? field('Что ты хочешь сделать?', '', true) : null;
        return [scene, shared,
            panel('Доступные действия', ...(acts.length ? actionGroups(acts) : [p('Здесь пока нет доступных действий. Можно перейти в другое место или дождаться следующего окна.')]),
                ...(waiting.length ? [p(`Архивных запросов в пути: ${waiting.length}. Ответ придёт в следующем окне — в хронику и досье.`)] : [])),
            panel('Карта усадьбы', p('Можно перейти только в соседние места.'), ...actionGroups(moves)),
            panel('Кто рядом', ...nearby.map(row => p(`${displayName(row)}${row.controller === 'npc' ? ' · собеседник' : ''}`)), ...(nearby.length ? [] : [p(own.role?.gender === 'f' ? 'Сейчас ты здесь одна.' : 'Сейчас ты здесь один.')]),
                ...(free ? [free.node, kit.stack(button('Предложить действие', async () => {
                    const result = await mutate(api('intent'), {request_id: id(), text: free.input.value, selection_id: null});
                    notice = result?.kind === 'clarification' ? 'Уточни действие: выбери одну из доступных кнопок. Пока ничего не потрачено.' : '';
                    if (result?.kind === 'proposal') proposal = {...result.proposal, label: 'Предложенное действие'};
                    render();
                }))] : [])),
            ...choiceList().filter(row => row.quote.kind === 'seen').map(row => panel(row.label, kit.stack(actionButton(row))))];
    }
    // Shown on every tab: finishing the window, or who is still playing it.
    // Actions grouped by verb: «Осмотреть · 1 ОД» once, then short buttons with the object only.
    // The confirmation still names the full action.
    function actionGroups(rows) {
        const groups = new Map();
        for (const row of rows) {
            const kind = row.quote.kind, full = row.npc_title && !mentions(row.label, row.npc_title) ? `${row.label} · ${row.npc_title}` : row.label;
            const split = /^([^:]{2,40}):\s*(.+)$/.exec(row.label);
            const [title, short] = kind === 'move' ? ['Перейти', row.label] : kind === 'archive_request' ? ['Запросить в архиве', row.label]
                : kind === 'talk' ? ['Поговорить', full]
                : kind === 'story_reply' ? ['Письмо', row.label]
                : split ? [split[1], split[2]] : ['Другие действия', row.label];
            if (!groups.has(title)) groups.set(title, []);
            groups.get(title).push({row, full, short});
        }
        return [...groups].map(([title, items]) => {
            const costs = new Set(items.map(item => Number(item.row.quote.cost) || 0)), same = costs.size === 1 ? [...costs][0] : null;
            const buttons = items.map(item => {
                const node = button(`${item.short}${same == null && item.row.quote.cost ? ` · ${item.row.quote.cost} ОД` : ''}`, () => selectAction(item.row, item.full));
                node.classList?.add('compact'); return node;
            });
            return put(el('section', 'ncase-group'), el('h3', 'nc-h3', `${title}${same ? ` · ${same} ОД` : ''}`), kit.row(...buttons));
        });
    }
    // Shown on every tab. Who else has finished stays private: the kernel keeps it out of the public view.
    function windowBar() {
        const own = view.self, pub = view.public, clock = pub.clock || {};
        if (pub.final || view.final_summary || own.status !== 'active' || !['investigation', 'final_hearing'].includes(clock.phase)) return null;
        if (own.finished_window) return panel(said('Ты завершил окно', 'Ты завершила окно'),
            p('Ждём остальных. Новое окно откроется, когда все завершат своё или выйдет время.'));
        const finish = choiceList().find(row => row.quote.kind === 'finish_window');
        return finish ? panel('Окно', p(`${said('Сделал', 'Сделала')} всё, что ${said('хотел', 'хотела')}? Заверши окно: когда завершат все, следующее откроется раньше.`), kit.stack(actionButton(finish))) : null;
    }
    function evidenceCard(item, source, actions = []) {
        return panel(item.title || (item.kind === 'claim' ? 'Утверждение' : 'Доказательство'),
            el('strong', item.kind === 'claim' ? 'ncase-claim' : 'ncase-proof', item.kind === 'claim' ? 'Утверждение — требует проверки' : 'Доказательство'),
            p(bodyText(item.body) || text(item.text)), source ? p(source) : null, actions.length ? kit.row(...actions) : null);
    }
    function board() {
        const all = [...arr(view.public.observations), ...arr(view.self.observations)], observations = new Map(all.map(item => [item.observation_id, item]));
        const playerName = account => arr(view.public.players).find(row => row.account_id === account)?.name;
        // One card per published observation: a second publisher is a name on it, not a second copy.
        const groups = new Map();
        for (const row of arr(view.public.board)) {
            const key = row.observation_id ? `obs:${row.observation_id}` : `row:${row.id}`;
            if (!groups.has(key)) groups.set(key, {row, owners: []});
            const owner = row.owner_account_id === view.self.account_id ? 'ты' : playerName(row.owner_account_id);
            if (owner && !groups.get(key).owners.includes(owner)) groups.get(key).owners.push(owner);
        }
        const publicItems = [...groups.values()].map(({row, owners}) => {
            const observation = row.observation || observations.get(row.observation_id);
            const by = owners.length ? `Опубликовал${owners.length > 1 ? 'и' : ''}: ${owners.join(', ')}` : 'Опубликовано на доске';
            return observation ? evidenceCard(observation, by) : evidenceCard({kind: row.kind, title: row.kind === 'claim' ? 'Версия игрока' : 'Улика', text: row.text}, by);
        });
        const onBoard = new Set(arr(view.public.board).map(row => row.observation_id).filter(Boolean));
        const lost = new Set(arr(view.self.personal?.lost_observations));
        const personal = arr(view.self.observations).map(item => {
            const actions = choiceList().filter(row => ['pin', 'ghost_share'].includes(row.quote.kind) && row.quote.params.observation_id === item.observation_id)
                .map(row => actionButton(row, row.quote.kind === 'pin' ? `${onBoard.has(item.observation_id) ? 'Подтвердить от себя' : 'Опубликовать'}: ${item.title || 'улика'}` : `${row.label}: ${item.title || 'воспоминание'}`));
            const source = lost.has(item.observation_id) ? 'Твоя находка. Оригинала больше нет: от него остался пепел. Записанное тобой — всё, что от него осталось.'
                : onBoard.has(item.observation_id) ? 'Твоя находка. Эта улика уже на доске.' : 'Твоя находка';
            return evidenceCard(item, source, actions);
        });
        const theories = arr(view.public.modules?.version_archive?.theories).map(item => panel(item.title, p(bodyText(item.body)), p(item.state === 'archived' ? 'Версия в архиве; её источники сохранены.' : 'Активная версия'),
            kit.row(...choiceList().filter(row => row.quote.kind === 'version_mark' && row.quote.params.version_id === item.id).map(row => actionButton(row, item.state === 'archived' ? `Вернуть версию: ${item.title}` : `В архив: ${item.title}`)))));
        const claimForm = formList().find(row => row.command_kind === 'claim');
        const draft = field('Твоя версия для доски', '', true);
        return [...hearings(), panel('Доска дела', p('Текст игрока и показания остаются утверждениями. Для обвинения нужны опубликованные доказательства.')),
            ...publicItems, ...(claimForm ? [panel('Добавить версию', draft.node, kit.row(button('Опубликовать версию', () => command('claim', {text: draft.input.value}))))] : []),
            panel('Твои находки', p('Они не становятся известны другим до публикации.')), ...personal, ...theories];
    }
    function hearings() {
        return formList().filter(row => ['accuse', 'vote', 'final_vote'].includes(row.command_kind)).map(form => {
            const subjects = choose('Кто вывел и скрывал хозяина? Если он всё сделал сам — выбери его.', [{id: '', label: 'Выбери участника'}, ...arr(form.subject_ids).map(char => ({id: char, label: nameOf(char)})),
                ...(form.command_kind === 'final_vote' ? [{id: 'abstain', label: 'Воздержаться'}] : [])], form.command_kind === 'final_vote' && view.self.final_ballot ? (view.self.final_ballot.suspect || 'abstain') : '');
            const citations = el('div', 'ncase-citations');
            const picked = new Set();
            for (const entry of arr(view.public.board).filter(item => arr(form.board_ids).includes(item.id))) {
                const input = el('input'); input.type = 'checkbox'; input.value = entry.id;
                input.addEventListener('change', () => { if (input.checked && picked.size < 5) picked.add(entry.id); else { picked.delete(entry.id); input.checked = false; } });
                const obs = entry.observation || [...arr(view.public.observations), ...arr(view.self.observations)].find(item => item.observation_id === entry.observation_id);
                const owner = entry.owner_account_id === view.self.account_id ? 'ты' : arr(view.public.players).find(row => row.account_id === entry.owner_account_id)?.name;
                citations.append(put(el('label', 'ncase-checkbox'), input, el('span', null, `${entry.kind === 'proof' ? 'Доказательство' : 'Утверждение'}: ${obs?.title || entry.text || 'Публичная улика'}${owner ? ` · ${owner}` : ''}`)));
            }
            const send = choice => {
                const kind = form.command_kind, params = {citations: [...picked]};
                if (kind === 'vote') Object.assign(params, {hearing_id: form.hearing_id, choice});
                else {
                    if (!subjects.input.value) { notice = 'Выбери участника в списке.'; render(); return null; }
                    params.suspect = subjects.input.value === 'abstain' ? null : subjects.input.value;
                }
                return command(kind, params);
            };
            return panel(form.command_kind === 'vote' ? 'Идёт слушание' : form.command_kind === 'final_vote' ? 'Итоговое слушание' : 'Предъявить обвинение',
                ...(form.command_kind === 'final_vote' ? [p('Назови, кто вывел и скрывал хозяина, и приложи улики с доски. Голос можно изменить, пока слушание не закрылось; итог объявят после закрытия.'),
                    ...(view.self.final_ballot ? [kit.alert({tone: 'ok', icon: 'check', title: `Твой голос записан: ${view.self.final_ballot.suspect ? nameOf(view.self.final_ballot.suspect) : 'без обвинения'}`})] : [])] : []),
                p('Выбери до пяти источников. Сервер проверит, хватает ли доказательств; утверждения ключами не считаются.'),
                ...(form.command_kind === 'vote' ? [] : [subjects.node]), citations,
                kit.row(...(form.command_kind === 'vote' ? [button('Возражаю', () => send('oppose')), button('Поддержать', () => send('support'))] : [button(form.command_kind === 'final_vote' ? (view.self.final_ballot ? 'Изменить голос' : 'Отдать голос') : 'Предъявить обвинение', () => send(), 'primary')])));
        });
    }
    function chat() {
        const forms = formList().filter(row => row.command_kind === 'say');
        if (!forms.some(row => row.channel === channel)) channel = forms[0]?.channel || '';
        const form = forms.find(row => row.channel === channel);
        const channels = choose('Беседа', forms.map(row => ({id: row.channel, label: row.label})), channel);
        channels.input.addEventListener('change', () => { channel = channels.input.value; recipients = []; render(); });
        const targetRows = el('div', 'ncase-recipients');
        for (const target of arr(form?.recipient_ids || form?.subject_ids)) {
            const check = el('input'); check.type = 'checkbox'; check.checked = recipients.includes(target);
            check.addEventListener('change', () => { recipients = recipients.filter(value => value !== target); if (check.checked && recipients.length < 2) recipients.push(target); else check.checked = false; });
            targetRows.append(put(el('label', 'ncase-checkbox'), check, el('span', null, nameOf(target))));
        }
        const draft = field('Сообщение', ownDraft, true);
        draft.input.addEventListener('input', () => { ownDraft = draft.input.value; });
        const messages = pages.messages.items.map(row => {
            const own = row.sender_account_id === view.self.account_id;
            const sender = `${arr(view.public.players).find(p => p.account_id === row.sender_account_id)?.name || 'Участник'}${own ? ' (ты)' : ''}`;
            return put(el('article', 'ncase-message'), el('strong', null, sender), el('span', 'nc-note', row.channel === 'whisper' ? 'Приватная беседа' : row.channel === 'ghost' ? 'Призраки' : 'Площадь'), p(row.text));
        });
        return [panel('Переписка', p('Площадь — всем за столом. Приватная беседа — только 2–3 игрокам рядом, за 1 ОД. Призраки разговаривают отдельно.'), ...messages,
            ...(pages.messages.next_cursor ? [kit.row(button('Ещё сообщения', async () => { await loadHistory('messages', true); render(); }))] : [])),
            panel('Написать', ...(forms.length ? [channels.node, targetRows, draft.node, p(`Сообщений осталось в этом окне: ${view.self.communication?.remaining ?? '—'}`),
                kit.row(button('Отправить', async () => {
                    const result = await command('say', {channel, recipients: channel === 'whisper' ? recipients : [], text: ownDraft});
                    if (result?.receipt?.accepted === true) { ownDraft = ''; render(); }
                }))] : [p('Сейчас отправка недоступна. Ранее разрешённая переписка сохранена.')]))];
    }
    function eventText(item) {
        const payload = item.payload || {}, own = view.self;
        const player = character => nameOf(character);
        const boardRow = arr(view.public.board).find(row => row.id === payload.board_id);
        const who = account => account === own.account_id ? 'Ты' : arr(view.public.players).find(row => row.account_id === account)?.name || 'Участник';
        if (bodyText(payload.body)) return bodyText(payload.body);
        switch (item.kind) {
        case 'window': return payload.phase === 'final_hearing' ? 'Началось итоговое слушание: каждый называет, кто скрывал хозяина.' : payload.phase === 'frozen' ? 'Стол остановился: все пропустили окна.' : `Открылось окно ${payload.window_idx || item.window_idx}.`;
        case 'board': return boardRow ? `${who(boardRow.owner_account_id)}: на доске ${boardRow.observation_id ? `улика «${observationTitle(boardRow.observation_id) || 'без названия'}»` : 'новая версия'}.` : 'На доске появилась запись.';
        case 'observation_granted': return `Находка: «${observationTitle(payload.observation_id) || 'запись'}».`;
        case 'archive_requested': return `Архивный запрос отправлен. Ответ — в окне ${payload.due_window}.`;
        case 'hearing': return payload.stage === 'opened' ? `Открыто слушание: обвиняют ${player(payload.suspect)}.` : `Слушание закрыто${payload.resolution === 'cancelled' ? ' без решения' : ''}: обвиняли ${player(payload.suspect)}.`;
        case 'status': return {ghost: `${player(payload.character_id)} теперь наблюдает за делом.`, fog: `${player(payload.character_id)} пропадает из виду.`, removed: `${player(payload.character_id)} покидает дело.`, active: `${player(payload.character_id)} снова за столом.`}[payload.status] || 'Состав стола изменился.';
        case 'npc_revealed': return 'Хозяин найден.';
        case 'world_changed': return 'Обстановка в усадьбе изменилась.';
        case 'version_marked': return `${who(payload.by_account)}: версия ${payload.state === 'archived' ? 'отправлена в архив' : 'возвращена'}.`;
        case 'final': return 'Дело закрыто.';
        case 'afk_notice': return `Ты ${said('пропустил', 'пропустила')} окон подряд: ${payload.missed_windows}.`;
        case 'window_digest': return 'Итог окна записан в хронику.';
        case 'story_return_closed': return payload.decision === 'accepted' ? 'Письмо передано.' : 'Письмо не передано.';
        default: return 'Событие дела.';
        }
    }
    function history() {
        const eventCards = (stream, title) => panel(title, ...pages[stream].items.map(item => {
            const payload = item.payload || {};
            return put(el('article', 'ncase-event'), el('strong', null, `Окно ${item.window_idx}`),
                item.kind === 'scene' ? sceneArt(sceneOf(item.event_id)?.art, 'Сцена окна') : null, p(eventText(item)),
                ...(payload.job_id ? [kit.row(button('Прочитать описание', async () => { const value = await mutate(api(`renderings/${encodeURIComponent(payload.job_id)}`), {}); notice = text(value?.text); render(); }))] : []));
        }), ...(pages[stream].next_cursor ? [kit.row(button('Ещё записи', async () => { await loadHistory(stream, true); render(); }))] : []));
        return [eventCards('public', 'Общий ход дела'), eventCards('self', 'Твои события')];
    }
    function rules() {
        return [panel('Как идёт дело', p('Четырнадцать окон на семь дней. Окна открывает сервер; заходи в удобное время. На перемещения и действия тратятся очки действий.'),
            p('Личные находки известны только тебе. Публикуй доказательства на доску, сравнивай документы и проверяй показания. Архивные запросы приходят в следующее окно.'),
            p('Обвинение обсуждается на слушании. Найти хозяина — ещё не значит доказать, кто его вывел и скрывал. Личная цель указана в твоём досье и засчитывается сервером.'))];
    }
    function render() {
        if (!live()) return;
        menu();
        if (!view) {
            if (game) frame([panel('Связь с твоим делом', p('Чтение партии пока недоступно. Её состояние хранится на сервере.'), kit.row(button('Обновить', refresh)))]);
            else if (room) renderRoom();
            return;
        }
        if (view.lobby) {
            const extra = proposal?.leaveLobby ? panel(proposal.label, kit.row(button('Остаться', () => { proposal = null; render(); }), button('Покинуть', () => lobbyCommand('leave'), 'danger'))) : confirmation();
            frame([...lobby(), extra].filter(Boolean), view.lobby.case?.title || 'Сбор игроков'); return;
        }
        if (!view.self) return frame([panel('Дело недоступно', p('Твоё участие не найдено. Вернись к своей комнате.'))]);
        const own = view.self, pub = view.public, clock = pub.clock || {};
        const stateNotice = clock.phase === 'frozen' ? panel('Стол ждёт возвращения', p('Общий простой остановил окна. Отметь возвращение, чтобы продолжить.'),
            kit.row(...choiceList().filter(row => row.quote.kind === 'seen').map(row => actionButton(row)))) : own.status === 'departed' ? panel('Участие завершено', p('Тебе доступна собственная разрешённая история до выхода и итог дела.')) : own.status === 'ghost' ? panel('Ты наблюдаешь за делом', p('Обычные действия недоступны. Переписка призраков и разрешённые воспоминания остаются отдельными.')) : null;
        const final = own.postmortem;
        const finale = pub.final || view.final_summary ? panel('Дело завершено', sealedArt(final?.variant_art, 'Развязка дела'), p(bodyText(final?.ending)), p(bodyText(final?.variant_final_text)),
            p(final?.goal_results?.find(row => row.account_id === own.account_id)?.met ? 'Твоя личная цель выполнена.' : 'Подробности своей личной цели смотри в итоговом досье.')) : null;
        const finalHearing = clock.phase === 'final_hearing' && !pub.final;
        const hearingNotice = (pub.hearing || finalHearing) && tab !== 'board' ? panel(finalHearing ? 'Итоговое слушание' : 'Идёт слушание',
            p(finalHearing ? `Неделя подошла к концу. Назови, кто вывел и скрывал хозяина, и приложи улики с доски.${own.final_ballot ? ' Твой голос уже записан — его можно изменить.' : ''}` : 'Посмотри обвинение и опубликованные источники, затем сделай свой выбор.'),
            kit.row(button(finalHearing ? (own.final_ballot ? 'Изменить голос' : 'Перейти к голосованию') : 'Открыть слушание', () => showTab('board'), 'primary'))) : null;
        const current = tab === 'self' ? [role()] : tab === 'board' ? board() : tab === 'chat' ? chat() : tab === 'history' ? history() : tab === 'rules' ? rules() : place();
        let selector = null;
        if (['finished', 'stopped'].includes(view.runtime_status) && arr(view.history_seats).length > 1) {
            const choice = choose('Твои завершённые роли', [{id: '', label: 'Все твои роли'}, ...view.history_seats.map(seat => ({id: seat.original_account_id, label: `${seat.display_name} · ${seat.role_title}`}))], selectedOriginal);
            choice.input.addEventListener('change', async () => {
                selectedOriginal = choice.input.value; epoch++; clearHistory(); view = null; render();
                await refresh();
                if (tab === 'history') { await loadHistory('public'); await loadHistory('self'); render(); }
            });
            selector = panel('Твоя история', choice.node);
        }
        frame([navigation(), selector, stateNotice, hearingNotice, finale, confirmation(), ...current, tab === 'rules' ? null : windowBar()].filter(Boolean), `Окно ${clock.window_idx || '—'} · ${arr(pub.locations).find(item => item.id === own.location)?.name || 'Усадьба'}`);
    }
    function close() {
        if (!alive) return;
        alive = false; epoch++; controller.abort(); clearInterval(poll); timer?.stop();
        view = proposal = room = game = boot = invitation = null; ownDraft = ''; recipients = [];
        outbox.clear(); cursors.clear(); for (const page of Object.values(pages)) page.items.length = 0;
        assets.clear(); assetWorld = null;
        Q.nav.pop?.('night-case-section'); kit.useWorld(null); document.documentElement.classList.remove('nc');
    }
    active = {close, refresh};
    document.documentElement.classList.add('nc');
    kit.loadShell(); kit.useWorld(null);
    Q.configure({mode: 'game', screen: 'night-case', title: 'Ночной город', identity: options.identity});
    menu();
    frame([panel('Ночной город', p('Загружаем твой стол…'))], 'Ночной город');
    poll = setInterval(backgroundPoll, 8000);
    document.addEventListener?.('visibilitychange', backgroundPoll, {signal: controller.signal});
    async function initialize() {
        if (!/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(viewer || '')) {
            viewer = null; boot = await request('/api/night-case/bootstrap'); viewer = boot?.viewer_account_id;
        }
        if (!/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(viewer || '')) { invalidate(); return; }
        const target = typeof options.target === 'string' ? root.NightCity.parseLaunch(options.target) : options.target;
        if (target?.room?.id) await enterRoom(target.room);
        else if (target?.roomId) await enterRoom({id: target.roomId, title: 'Комната'});
        else if (target?.code) {
            const token = target.code, params = /^[A-Za-z0-9_-]{43}$/.test(token) ? {invite_code: token} : {short_code: token};
            const joined = await mutate('/api/guest/rooms/join', params); if (joined) await enterRoom(joined);
        } else await entry();
    }
    initialize().catch(fail);
    return active;
}
const api = {open, close() { active?.close(); active = null; }, http, createOutbox, envelope, playerView, artPointer, assetManifest, verifiedManifest, errorText};
if (typeof module !== 'undefined' && module.exports) module.exports = api;
if (root) root.NightCase = api;
})(typeof window !== 'undefined' ? window : globalThis);
