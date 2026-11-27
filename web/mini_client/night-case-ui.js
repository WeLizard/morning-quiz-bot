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
    safe.public = pick(value?.public, ['case_id', 'clock', 'world', 'art', 'locations', 'players', 'npcs', 'board', 'observations', 'modules', 'hearing', 'final', 'flags', 'locks', 'looks']);
    // Only shared scenes leave the public chronicle: id, window, text and picture.
    safe.public.scenes = arr(value?.public?.chronicle).filter(entry => entry?.kind === 'scene')
        .map(entry => ({event_id: entry.event_id, window_idx: entry.window_idx, body: entry.payload?.body, art: entry.art}));
    // A wrong verdict is the only way out of play to a removed seat: the removed screen names that hearing.
    safe.public.removals = arr(value?.public?.chronicle).filter(entry => entry?.kind === 'hearing' && entry.payload?.stage === 'closed' && entry.payload?.resolution === 'wrong')
        .map(entry => ({window_idx: entry.window_idx, suspect: entry.payload.suspect}));
    safe.public.chronicle_count = arr(value?.public?.chronicle).length;
    // The window in which each board record was published (screen 10 signs it «герой · игрок · окно N»).
    safe.public.board_windows = Object.fromEntries(arr(value?.public?.chronicle).filter(entry => entry?.kind === 'board' && entry.payload?.board_id)
        .map(entry => [entry.payload.board_id, entry.window_idx]));
    safe.self = value?.self ? pick(value.self, ['account_id', 'character_id', 'role', 'status', 'location', 'ap', 'actor_seq', 'faction', 'goal', 'secrets', 'truth', 'observations', 'nearby', 'personal', 'communication', 'modules', 'postmortem', 'finished_window', 'final_ballot']) : null;
    // Screen 8 shows the answer of a talk: only the results of the viewer's own actions leave the private events.
    if (safe.self) safe.self.results = arr(value.self.private_events).filter(event => event?.kind === 'action_result')
        .slice(-20).map(event => ({event_id: event.event_id, body: event.payload?.body, observation_ids: arr(event.payload?.observation_ids)}));
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
    unsupported_count: 'Для этого дела столько игроков не подходит.',
    seat_taken: 'Этого героя уже занял другой игрок.',
    seats_unsolvable: 'С такими местами дело не сходится: пусть кто-то сядет за сыщика или выберет «любое свободное».',
    rate_limited: 'Слишком много запросов. Подожди немного.',
    stale_epoch: 'Настройки ведущего уже изменились. Обнови дело и выбери снова.',
    request_cooldown: 'Запрос администратору уже отправлен недавно. Подожди немного.',
    request_limit: 'Лимит запросов к администратору для этой партии исчерпан.',
    invalid_config: 'Проверь провайдера, модель и ключ.',
    unsupported_preset: 'Этот провайдер сейчас недоступен.',
    ai_unavailable: 'ИИ сейчас недоступен — партия идёт на авторском тексте.',
    credential_unavailable: 'Ключ больше недоступен. Подключи его заново.',
    game_not_running: 'Партия уже не идёт.',
    game_not_lobby: 'Сбор уже закончился — обнови дело.',
    removed_from_room: 'Хозяин убрал тебя из этой компании. Вернуться можно только по приглашению.',
    age_confirm_required: 'Этот мир — 18+. Подтверди возраст, чтобы сесть за стол.',
    table_full: 'За этим столом мест больше нет.',
};
/* AI narrator (NIGHT_CASE_AI_ACCESS §7). The host's own key lives only in the password input until submit. */
const narratorStatus = {authored: 'авторский текст', pending: 'авторский текст, ждём ответа администратора',
    fallback: 'авторский текст (ИИ сейчас недоступен)'};
const narratorReasons = {ai_disabled: 'ИИ выключен на сервере.', egress_disabled: 'Сервер сейчас не выходит в облако: свой ключ не подключить.',
    vault_unavailable: 'Сервер не может безопасно сохранить ключ.', no_presets: 'Администратор не открыл ни одного провайдера.'};
const narratorFields = {organization_id: 'Organization ID', project_id: 'Project ID', workspace_id: 'Workspace ID', folder_id: 'Folder ID', scope: 'Scope'};
const errorText = error => error?.network ? 'Нет связи. Повтори тот же запрос — действие не применится дважды.' : errors[error?.code] || 'Действие сейчас недоступно. Обнови дело и попробуй снова.';

async function http(path, {method = 'GET', body, identity = 'guest', signal, expectedViewer, key} = {}) {
    const controller = new AbortController();
    const abort = () => controller.abort();
    signal?.addEventListener('abort', abort, {once: true});
    const timer = setTimeout(abort, 12000);
    const headers = method === 'GET' ? {} : {'Content-Type': 'application/json', 'X-Guest-CSRF': '1', 'X-Mini-CSRF': '1'};
    if (expectedViewer) headers['X-Night-Expected-Viewer'] = expectedViewer;
    if (key) headers['Idempotency-Key'] = key;
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
    // The window (game:seq) in which a player who finished it chose to act again (finding 4); any other window keeps them closed.
    let reopened = '';
    // Screen 8 «Разговор»: the talk the player just had ({npc, question, events, cost, key}); the place shows it until «К месту».
    let conversation = null;
    // Having the case open is «Я здесь» (owner decision 2026-11-27): the client says so on opening, in a new window and
    // every few minutes while the case is on screen; the server marks the seat once per window and keeps the time.
    const PRESENCE_EVERY = 3 * 60 * 1000;
    let pinged = {key: '', at: 0};
    // Tab badges count what appeared since the player last looked (in memory: the client keeps nothing on the device).
    const looked = {feed: null, board: null};
    let boot = options.bootstrap, fresh = null, ownDraft = '', channel = 'square', recipients = [], invitation = null, lookPick = null, lobbyDraft = '', chatFocus = false;
    // Choices of the removed-player forms outlive the poll re-render, like the chat draft.
    let askGhost = null, askText = ''; const whisperTo = new Map(), hearingPick = new Map(); let accuseOpen = false;
    let viewer = boot?.viewer_account_id || null;
    const pages = {public: {items: [], next_cursor: null}, self: {items: [], next_cursor: null}, messages: {items: [], next_cursor: null}};
    const cursors = new Set(), controller = new AbortController();
    let assets = new Map(), assetWorld = null, worldPack = null;
    let selectedOriginal = '';
    let ai = null, aiAt = 0, aiMode = null, aiPresets = null, aiKeyForm = false;
    const aiOn = () => boot?.capabilities?.ai_narrator === true;
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
            if (live() && (error.code === 'profile_changed' || error.status === 401 || error.status === 403 && error.code !== 'removed_from_room' ||
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
    // Older lobbies stored the seat id («seat02») for a player without a free name: show «Игрок 2» instead.
    const seatName = row => /^seat\d\d$/.test(row?.name || '') ? `Игрок ${Number(row.name.slice(4))}` : row?.name || 'Игрок';
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
    // Mysticism belongs to the case: only a case with signs (module ghost_visions) speaks of ghosts.
    const mystic = () => Boolean(view?.public?.modules?.ghost_visions);
    const removedWord = () => mystic() ? 'Призраки' : 'Отстранённые';
    const removedTitle = () => mystic() ? 'Ты — призрак дела' : said('Ты отстранён от расследования', 'Ты отстранена от расследования');
    // Only a wrong verdict removes a player: the closed hearing that named this character is the reason.
    const removalReason = () => {
        const own = view?.self?.character_id;
        const closed = arr(view?.public?.removals).filter(row => row.suspect === own).at(-1);
        return closed ? `Слушание в окне ${closed.window_idx}: стол поддержал обвинение, но ${said('ты не виновен', 'ты не виновна')}.` : '';
    };
    const ghostChatLine = () => `Площадь ты по-прежнему читаешь, но писать туда не можешь. Писать можно только ${mystic() ? 'другим призракам' : 'другим отстранённым'}.`;
    const ghostKinds = new Set(['ghost_share', 'ghost_whisper', 'testimony_answer', 'ghost_sign']);
    const questions = () => arr(view?.public?.modules?.ghost_testimony?.questions);
    const placeName = location => arr(view?.public?.locations).find(item => item.id === location)?.name || 'Усадьба';
    // Zero-cost bookkeeping needs no «Стоимость: 0 ОД» step: the proposal is confirmed right away.
    const instant = new Set(['seen', 'finish_window']);
    let info = '';
    const receipts = {claim: 'Версия опубликована на доске.', accuse: 'Обвинение предъявлено: открыто слушание.', vote: 'Твой голос на слушании записан.', final_vote: 'Твой голос записан. Его можно изменить, пока слушание не закрылось.',
        pin: 'Улика опубликована на доске.', finish_window: 'Окно завершено.', archive_request: 'Запрос отправлен. Ответ придёт в следующем окне — его покажут в «Досье».', seen: 'Отмечено: ты за столом.',
        ghost_share: 'Воспоминание опубликовано на доске.', ghost_whisper: 'Воспоминание передано лично.', testimony_answer: 'Ответ записан на доске.', ghost_sign: 'Знак явлен всем за столом.',
        testimony_ask: 'Вопрос задан. Ответ «да» или «нет» появится на доске.'};

    function invalidate() {
        if (locked || !alive) return;
        locked = true; epoch++; controller.abort(); clearInterval(poll); timer?.stop(); timer = null;
        view = proposal = room = game = boot = invitation = viewer = null;
        ownDraft = selectedOriginal = notice = askText = ''; recipients = []; channel = 'square'; fresh = null; lookPick = null; lobbyDraft = ''; askGhost = null; whisperTo.clear(); hearingPick.clear(); accuseOpen = false;
        ai = aiPresets = aiMode = null; aiAt = 0; aiKeyForm = false;
        outbox.clear(); clearHistory(); assets.clear(); assetWorld = null; worldPack = null; kit.useWorld?.(null);
        Q.nav.pop?.('night-case-room'); Q.nav.pop?.('night-case-section'); Q.nav.pop?.('night-case-pick'); popFlow(); Q.menu.register([], 'Ночной город');
        const header = kit.header(); header.node.classList.add('ncase-bar');
        header.set({eyebrow: 'Ночной город', title: 'Доступ к делу изменился'});
        host.replaceChildren(header.node, put(el('main', 'nc-main ncase-main'), panel('Открой дело заново',
            p('Профиль или доступ изменились. Вернись через ⚙ в главное меню, войди в нужный профиль и снова открой дело.'))));
    }

    function fail(error) {
        if (!live()) return;
        notice = errorText(error);
        if (!view && !room && !fresh) frame([panel('Связь с делом', p(notice), kit.row(button('Повторить', () => game ? refresh() : initialize())))]);
        else render();
    }
    // dock: the bottom action panel (mockups); main then keeps room for it under the last card.
    function frame(children, title = 'Усадьба', eyebrow = 'Ночной город', dock = null, mainClass = '') {
        if (!live()) return;
        timer?.stop(); timer = null;
        const header = kit.header(), clock = view?.public?.clock;
        header.node.classList.add('ncase-bar');
        kit.pageScene?.({slot: game ? 'day' : null, shell: game ? 'table' : 'entry', time: sceneTime()});
        kit.music?.follow?.(musicPlace());
        if (clock?.closes_at && !view?.public?.final) timer = kit.timer({endsAt: Date.parse(clock.closes_at) / 1000,
            serverNow: Date.parse(view.server_now) / 1000, alive: live, onExpire: refresh});
        header.set({eyebrow, title, clock: timer?.clock});
        const main = put(el('main', 'nc-main ncase-main'), ...children);
        if (info && !notice) main.prepend(kit.alert({tone: 'ok', icon: 'check', title: info}));
        // An unconfirmed write shows one banner with «Повторить»; its network error is not repeated as a second alert.
        const unconfirmed = outbox.pending && !outbox.busy;
        if (notice && !unconfirmed) main.prepend(kit.alert({title: notice}));
        if (outbox.busy && !proposal?.sending) main.prepend(status(`${sending ? sending + ': ' : ''}отправляем…`));
        if (unconfirmed) main.prepend(kit.netBanner({text: 'Запрос ещё не подтверждён сервером', onRetry: () => retry().catch(fail)}));
        if (dock) main.classList.add('has-dock');
        if (mainClass) main.classList.add(mainClass);
        if (children.some(child => /\bnc-col\b/.test(child?.className || ''))) main.classList.add('ncase-cols');
        host.replaceChildren(...[header.node, main, dock].filter(Boolean)); host.dataset.page = 'night';
    }
    /* Music of the case (MQB-012 stage 4): the shell themes outside a case, the world's day track in the lobby and in a
       morning window, its night track in an evening window, its finale once after the outcome. The player picks the file
       from the loaded world pack; without a pack or a track it stays silent. */
    function musicPlace() {
        const world = view?.public?.world;
        if (world) {
            if (view.lobby) return {world, status: 'lobby'};
            if (view.public.final || view.final_summary) return {world, status: 'finished'};
            return {world, status: ['evening', 'night'].includes(sceneTime()) ? 'night' : 'day'};
        }
        if (fresh?.screen === 'case' && worldPack?.id) return {world: worldPack.id, status: 'lobby'};
        return {shell: true};
    }
    function timeOf(stamp) {
        if (!stamp) return 'day';
        try {
            const hour = Number(new Intl.DateTimeFormat('en', {timeZone: view?.public?.clock?.timezone || 'UTC', hourCycle: 'h23', hour: '2-digit'}).format(new Date(stamp)));
            return hour < 6 || hour >= 21 ? 'night' : hour < 11 ? 'morning' : hour < 17 ? 'day' : 'evening';
        } catch { return 'day'; }
    }
    const sceneTime = () => timeOf(view?.server_now);
    // Sound and contrast are account settings (the hub profile has the same switches): applied at once on this
    // device, saved to the account, rolled back if the server refuses.
    async function saveMusic(on) {
        // The player itself belongs to the kit: the case only changes the shared preference it follows.
        const before = {...(Q.prefs?.get?.().gamePreferences || {})};
        Q.prefs?.applyAccount?.({game_preferences: {...before, music: on}});
        try { Q.prefs?.applyAccount?.(await request('/api/account/game-preferences', {method: 'POST', body: {account_id: viewer, game_preferences: {music: on}}})); }
        catch { Q.prefs?.applyAccount?.({game_preferences: before}); }
    }
    async function saveContrast(on) {
        Q.prefs?.setContrast?.(on);
        try { Q.prefs?.applyAccount?.(await request('/api/account/contrast-mode', {method: 'POST', body: {enabled: on}})); }
        catch { Q.prefs?.setContrast?.(!on); }
    }
    // The ⚙ menu of the case (mockup screen 19): glyphs from the shell's sprite, the game block first.
    function menu() {
        const glyph = name => `<use href="/app/night/shell/icons.svg#nc-i-${name}"/>`;
        Q.menu.register([
            {id: 'night-case-rules', label: 'Правила дела', icon: glyph('story'), onSelect: () => showTab('rules')},
            ...(view?.self && !view.lobby && ai?.can_configure ? [{id: 'night-case-narrator', label: 'Ведущий партии', icon: glyph('vial'), onSelect: () => showTab('narrator')}] : []),
            ...(kit.musicOn ? [{id: 'night-case-music', label: 'Музыка', hint: 'громкость — в профиле', icon: glyph('music'), toggle: () => kit.musicOn(), onSelect: () => saveMusic(!kit.musicOn())}] : []),
            ...(Q.prefs?.setContrast ? [{id: 'night-case-contrast', label: 'Контрастный режим', icon: glyph('eye'), toggle: () => Boolean(Q.prefs.get?.().contrast), onSelect: () => saveContrast(!Q.prefs.get?.().contrast)}] : []),
            {id: 'night-case-refresh', label: 'Обновить связь', icon: glyph('repeat'), onSelect: () => refresh()},
            ...(view?.self && choiceList().some(row => row.quote.kind === 'forfeit') ? [{id: 'night-case-leave', label: 'Покинуть дело', hint: 'вернуться в партию будет нельзя', icon: glyph('door'), danger: true, onSelect: () => confirmForfeit()}] : []),
        ], 'Ночной город');
    }
    function showTab(next) {
        conversation = null;
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
            proposal = {...value.proposal, label, kind: row.quote.kind,
                talk: row.quote.kind === 'talk' ? {npc: row.npc_character_id, question: row.label} : null};
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
            // The answer is the talk's own action_result among the events this command caused.
            if (sent.talk && result?.receipt?.accepted === true)
                conversation = {...sent.talk, events: arr(result.caused_event_ids), cost: Number(sent.cost) || 0, key: windowKey()};
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
            p(proposal.forfeit ? 'Ты прекратишь участие. Назад в эту партию вернуться нельзя; ранее разрешённая история сохранится.'
                : ghostKinds.has(proposal.kind) ? 'Это твоё единственное действие в этом окне. До подтверждения оно не применяется.'
                : `Стоимость: ${Number(proposal.cost) || 0} ОД. До подтверждения действие не применяется.`),
            kit.row(button('Отмена', () => { proposal = null; render(); }), button('Подтвердить', async () => {
                if (proposal.forfeit) { proposal = null; await command('forfeit', {}); }
                else await confirmProposal();
            }, proposal.forfeit ? 'danger' : 'primary')));
    }
    // In a case the choice is confirmed in the bottom dock (mockup 7): what and how much, «Отмена» and the verb.
    const CONFIRM_VERB = {move: 'Перейти', talk: 'Поговорить', archive_request: 'Запросить', story_reply: 'Ответить'};
    function confirmDock() {
        if (!proposal) return null;
        if (proposal.sending) return kit.dock({hint: `Отправляем… · ${proposal.label || 'Действие'}`, buttons: []});
        const cancel = button('Отмена', () => { proposal = null; render(); });
        if (proposal.forfeit) return kit.dock({layout: 'row', hint: 'Ты прекратишь участие. Вернуться в эту партию нельзя; твоя история до выхода сохранится.',
            buttons: [cancel, button('Покинуть дело', async () => { proposal = null; await command('forfeit', {}); }, 'danger')]});
        const cost = Number(proposal.cost) || 0, left = Number(view?.self?.ap) || 0;
        const price = ghostKinds.has(proposal.kind) ? 'твоё единственное действие в этом окне'
            : cost ? `${plural(cost, 'действие', 'действия', 'действий')} из ${left}` : 'без траты действий';
        const split = /^([^:]{2,24}):\s/.exec(proposal.label || '');
        const verb = CONFIRM_VERB[proposal.kind] || (split ? split[1] : 'Подтвердить');
        return kit.dock({layout: 'row', hint: `${proposal.label || 'Действие'} · ${price}`,
            buttons: [cancel, button(verb, () => confirmProposal().catch(fail), 'primary')]});
    }
    // A stream is read from its end (newest 50); «Раньше» walks to older pages. A refresh reads the end again and keeps the
    // older pages already read when the new end overlaps them; after a gap it starts over from the end.
    async function loadHistory(stream, more = false) {
        if (!game) return;
        const generation = epoch;
        const state = pages[stream], cursor = more ? state.next_cursor : null;
        if (more && !cursor || cursor && cursors.has(stream + cursor)) return;
        const value = await request(api(`history?stream=${stream}&limit=50&latest=true${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}${historySelection()}`));
        if (!live() || generation !== epoch) return;
        const key = row => row.event_id || row.id, page = arr(value.items).filter(key), ids = new Set(page.map(key));
        const unique = rows => { const seen = new Set(); return rows.filter(row => !seen.has(key(row)) && seen.add(key(row))); };
        if (more) { state.items = unique([...page, ...state.items]); state.next_cursor = value.next_cursor || null; }
        else if (value.next_cursor && state.items.some(row => ids.has(key(row)))) state.items = unique([...state.items.filter(row => !ids.has(key(row))), ...page]);
        else { state.items = unique(page); state.next_cursor = value.next_cursor || null; if (!more) for (const old of [...cursors]) if (old.startsWith(stream)) cursors.delete(old); }
        if (cursor) cursors.add(stream + cursor);
    }
    const loadTab = async key => {
        if (key === 'feed') { await loadHistory('public'); await loadHistory('messages'); }
        if (key === 'self') { await loadHistory('self'); await loadHistory('messages'); }
    };
    async function refresh({preserveUI = false} = {}) {
        if (!live() || reading) return;
        const generation = epoch;
        reading = true;
        try {
            if (game) {
                const value = await request(api(`view${selectedOriginal ? '?original_account_id=' + encodeURIComponent(selectedOriginal) : ''}`));
                if (!live() || generation !== epoch) return;
                present(value);
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
                // The world pack dresses the case: palette, title font, hero frame, side emblems, card backs, music.
                if (world && worldPack?.id !== world && kit.loadPack) {
                    const pack = await kit.loadPack(world);
                    if (!live() || generation !== epoch) return;
                    if (pack) { worldPack = pack; kit.useWorld(pack); }
                }
                await loadTab(tab);
                if (!live() || generation !== epoch) return;
                if (aiOn()) {
                    await loadAI();
                    if (!live() || generation !== epoch) return;
                }
            }
            render();
        } catch (error) { if (!preserveUI) fail(error); }
        finally { reading = false; }
    }
    async function loadAI(force = false) {
        if (!aiOn() || !game) { ai = null; return; }
        if (!force && ai && Date.now() - aiAt < 20000) return;
        aiAt = Date.now();
        try { ai = await request(api('ai')); } catch { ai = null; /* Status is advisory: the game never waits for it. */ }
    }
    const aiBody = extra => ({expected_epoch: Number(ai?.epoch) || 0, client_request_id: id(), ...extra});
    async function aiCommand(path, label) {
        sending = label;
        try { const result = await mutate(api(path), aiBody()); if (result) info = label + '.'; }
        finally { sending = ''; }
        await loadAI(true); render();
    }
    async function sendKey(form) {
        if (outbox.busy || outbox.pending) return;
        const settings = {preset: form.preset.input.value, model_id: (form.manual?.input.value.trim() || form.model?.input.value || '').trim()};
        const project = {};
        for (const [name, item] of Object.entries(form.extra)) if (item.input.value.trim()) project[name] = item.input.value.trim();
        if (Object.keys(project).length) settings.project_fields = project;
        const secret = form.secret.input.value;
        // Not through the outbox: a lost response must not keep the key in memory for a retry.
        form.secret.input.value = '';
        if (!settings.model_id || !secret) { notice = 'Нужны модель и ключ.'; render(); return; }
        notice = ''; info = '';
        try {
            await request(api('ai/byok'), {method: 'POST', body: aiBody({settings, secret})});
            info = view?.lobby ? 'Ключ сохранён для этой партии. Он сотрётся, когда партия закончится.' : 'Ключ подключён: новые сцены пишет ИИ.';
            aiKeyForm = false; aiMode = 'byok';
        } catch (error) { notice = errorText(error); }
        await loadAI(true); render();
    }
    function keyForm() {
        if (!aiPresets || aiPresets === 'loading') {
            if (!aiPresets) {
                aiPresets = 'loading';
                request('/api/night-case/ai/presets').then(value => { aiPresets = value; render(); }).catch(error => { aiPresets = null; fail(error); });
            }
            return [p('Загружаем список провайдеров…')];
        }
        if (!aiPresets.byok_ready) return [p(narratorReasons[aiPresets.reason] || 'Свой ключ сейчас подключить нельзя.')];
        const items = arr(aiPresets.items);
        const preset = choose('Провайдер', items.map(row => ({id: row.id, label: row.id})), items[0]?.id);
        const form = {preset, extra: {}};
        const box = el('div', 'ncase-key-fields');
        const fill = () => {
            const row = items.find(item => item.id === preset.input.value) || {};
            form.model = arr(row.models).length ? choose('Модель', arr(row.models).map(name => ({id: name, label: name}))) : null;
            form.manual = row.manual_model_id ? field(form.model ? 'Или другая модель (ID у провайдера)' : 'Модель (ID у провайдера)') : null;
            form.extra = {};
            for (const name of [...arr(row.required_fields), ...arr(row.optional_fields)]) form.extra[name] = field(narratorFields[name] || name);
            box.replaceChildren(...[form.model?.node, form.manual?.node, ...Object.values(form.extra).map(item => item.node)].filter(Boolean));
        };
        preset.input.addEventListener('change', fill); fill();
        form.secret = field('Ключ API');
        Object.assign(form.secret.input, {type: 'password', autocomplete: 'new-password', spellcheck: false, maxLength: 8192});
        form.secret.input.setAttribute('data-lpignore', 'true'); form.secret.input.setAttribute('data-1p-ignore', '');
        return [preset.node, box, form.secret.node,
            p('Ключ видит только сервер, другие игроки его не видят. Оплату за запросы спишет сам провайдер с твоего аккаунта; приложение денег не берёт.'),
            p('ИИ пишет общие сцены и твои личные; чужие личные сцены идут по авторскому тексту. Когда партия закончится, ключ сотрётся.'),
            kit.row(...(aiKeyForm ? [button('Отмена', () => { aiKeyForm = false; render(); })] : []),
                button('Подключить ключ', () => sendKey(form), 'primary'))];
    }
    function narratorLine() {
        if (!aiOn() || !ai) return null;
        return p(`Ведущий: ${ai.status === 'ai' ? `ИИ${ai.model_label ? ' · ' + ai.model_label : ''}` : narratorStatus[ai.status] || narratorStatus.authored}.`);
    }
    const lobbyMode = () => aiMode || (ai?.mode === 'byok' ? 'byok' : 'admin');
    function narratorLobby() {
        if (!aiOn() || !ai?.can_configure) return null;
        const mode = lobbyMode();
        const options = [['admin', 'У админа'], ['byok', 'Свой ключ'], ['authored', 'Авторский']];
        const group = put(el('div', 'qw-btn-group ncase-narrator-pick'), ...options.map(([key, label]) => {
            // Plain segments: the core .qw-btn-group styles them, the noir .qw-btn frame would not glue.
            const control = el('button', null, label); control.type = 'button';
            control.addEventListener('click', () => { aiMode = key; aiKeyForm = false; render(); });
            control.setAttribute('aria-pressed', String(mode === key)); return control;
        }));
        group.setAttribute('role', 'group'); group.setAttribute('aria-label', 'Кто ведёт партию');
        const until = ai.expires_at ? ' до ' + (root.QW?.prefs?.formatDate?.(ai.expires_at, 'ru-RU', {hour: '2-digit', minute: '2-digit'}) || new Date(ai.expires_at).toLocaleTimeString('ru-RU', {hour: '2-digit', minute: '2-digit'})) : '';
        const body = mode === 'admin' ? [p('Партия сразу начнётся на авторском тексте, а администратор получит запрос. Если одобрит — новые сцены будет писать ИИ.')]
            : mode === 'authored' ? [p('Сцены и ответы ведёт авторский текст дела. ИИ не подключается.')]
            : ai.staged_credential_id && !aiKeyForm ? [p(`Ключ сохранён для этой партии${until}. Если не начать дело до этого времени, ключ придётся ввести снова.`),
                kit.row(button('Заменить ключ', () => { aiKeyForm = true; render(); }))]
            : keyForm();
        return panel('Ведущий партии', group, ...body);
    }
    function startParams() {
        if (!aiOn() || !ai?.can_configure) return {};
        const mode = lobbyMode();
        if (mode === 'byok' && !ai.staged_credential_id) return null;
        return {ai: {mode, expected_epoch: Number(ai.epoch) || 0, staged_credential_id: mode === 'byok' ? ai.staged_credential_id : null}};
    }
    function startGame() {
        const params = startParams();
        if (!params) { notice = 'Сначала подключи свой ключ или выбери другого ведущего.'; render(); return; }
        aiAt = 0; // the start changes the narrator: the next view reads its fresh status
        return lobbyCommand('start', params);
    }
    function narratorTab() {
        if (!ai) return [panel('Ведущий партии', p('Статус ведущего пока не загружен.'), kit.row(button('Обновить', async () => { await loadAI(true); render(); })))];
        const pending = ai.status === 'pending';
        const actions = ai.can_configure ? [
            ...(!pending && ai.mode !== 'admin' ? [button('Запросить ИИ у администратора', () => aiCommand('ai/request', 'Запрос администратору отправлен'))] : []),
            button(ai.mode === 'byok' ? 'Заменить свой ключ' : 'Подключить свой ключ', () => { aiKeyForm = true; render(); }),
        ] : [];
        // Leaving AI is set apart from the main actions (UI_RULES §9: danger zone).
        const off = ai.can_configure && (ai.status !== 'authored' || ai.mode !== 'authored')
            ? put(el('div', 'qw-danger-zone'), button('Вернуть авторский текст', () => aiCommand('ai/off', 'Партия вернулась к авторскому тексту'), 'danger')) : null;
        return [panel('Ведущий партии', narratorLine(),
            pending && ai.expires_at ? p(`Запрос ждёт решения до ${new Date(ai.expires_at).toLocaleString('ru-RU')}. Играть можно уже сейчас.`) : null,
            ai.mode === 'byok' && ai.status === 'ai' ? p('Работает твой ключ. Чужие личные сцены идут по авторскому тексту.') : null,
            ...(aiKeyForm ? keyForm() : []), actions.length && !aiKeyForm ? kit.stack(...actions) : null, aiKeyForm ? null : off)];
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
    function present(value) {
        if (selectedOriginal || document.hidden || value?.runtime_status !== 'running' || !['active', 'fog', 'ghost'].includes(value?.self?.status)) return;
        const key = `${game}:${value.public?.clock?.window_seq}`, now = Date.now();
        if (pinged.key === key && now - pinged.at < PRESENCE_EVERY) return;
        pinged = {key, at: now};
        const generation = epoch;
        // Best effort: a lost ping is repeated by the next poll; a mark that changed the case brings a fresh view.
        request(api('presence'), {method: 'POST', body: {}}).then(result => {
            if (result?.marked === true && live() && generation === epoch) refresh({preserveUI: Boolean(proposal || outbox.busy || outbox.pending)});
        }).catch(() => { if (generation === epoch) pinged = {key: '', at: 0}; });
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
    // A company and its case are one step below the root: BackButton / ‹ returns to the list.
    async function enterRoom(next) {
        epoch++; room = next; view = null; proposal = null; tab = 'place'; fresh = null; popFlow();
        selectedOriginal = ''; clearHistory();
        Q.nav.pop?.('night-case-section');
        Q.nav.push?.({id: 'night-case-room', onBack: () => { entry().catch(fail); return true; }});
        room = await request(`/api/guest/rooms/${encodeURIComponent(room.id)}`);
        const current = await request(`/api/rooms/${encodeURIComponent(room.id)}/night-case/current`);
        if (!live()) return;
        game = current.game_id || null;
        if (game) await refresh(); else renderRoom();
    }
    // Pictures of a case pack outside a game (portraits on the root and the case card): verified once per pack, like the game's.
    const artCache = new Map();
    function packArt(binding, world) {
        const pointer = artPointer(binding);
        if (!pointer || !/^[a-z][a-z0-9_]{1,31}$/.test(text(world))) return Promise.resolve(new Map());
        if (!artCache.has(pointer)) artCache.set(pointer, request(pointer).then(value => verifiedManifest(value, world, binding))
            .catch(() => { artCache.delete(pointer); return new Map(); }));
        return artCache.get(pointer);
    }
    function artImage(map, art, cls = 'ncase-face') {
        const hit = map?.get(art?.asset_id);
        if (!hit) return put(el('span', `${cls} blank`), icon('people'));
        return Object.assign(el('img', cls), {src: hit.url, alt: '', loading: 'lazy'});
    }
    const thumbImg = (world, cls = 'thumb') => {
        const entry = kit.worldEntry?.(world), url = entry ? kit.thumbUrl?.(entry) : '';
        return url ? Object.assign(el('img', cls), {src: url, alt: ''}) : el('span', `${cls} blank`);
    };
    const popFlow = () => { Q.nav.pop?.('night-case-case'); Q.nav.pop?.('night-case-new'); };
    // «6 человек · идёт дело, окно 5» (mockup 1, «Твои компании»).
    function companyLine(row) {
        const people = plural(Number(row?.members) || 1, 'человек', 'человека', 'человек');
        const state = !row || ['none', 'stopped'].includes(row.status) ? 'свободна'
            : row.status === 'lobby' ? `сбор на дело, за столом ${row.players || 1}`
            : row.status === 'running' ? `идёт дело, окно ${row.window?.idx || 1}`
            : row.status === 'finished' ? 'дело закрыто' : row.status === 'interrupted' ? 'дело на паузе' : 'дело недоступно';
        return `${people} · ${state}`;
    }
    // A case I sit in (mockup 1, «Твои дела»): the world cover with my hero's portrait, where it stands, «Вернуться».
    function myCase(item, row, art) {
        const look = row.hero?.look, count = Number(row.window?.count) || 14, idx = Number(row.window?.idx) || 1;
        const where = row.status === 'lobby' ? `Сбор · за столом ${row.players || 1}`
            : row.phase === 'frozen' ? `Окно ${idx} из ${count} · стол ждёт возвращения`
            : row.phase === 'final_hearing' ? `Окно ${idx} из ${count} · итоговое слушание` : `Окно ${idx} из ${count}`;
        const who = [look ? text(look.title) : row.status === 'lobby' ? 'персонаж не выбран' : null, item.title].filter(Boolean).join(' · ');
        return [put(el('div', 'ncase-mycase'), put(el('span', 'art'), thumbImg(row.world, 'cover'), look ? artImage(art, look.art, 'ncase-face sm') : null),
                put(el('div'), el('strong', null, row.case_title || 'Дело'), el('span', 'nc-muted', who),
                    put(el('span', 'ncase-news'), icon(row.status === 'lobby' ? 'people' : 'moon'), where))),
            kit.stack(button(row.status === 'lobby' ? 'Вернуться к сбору' : 'Вернуться в дело', () => enterRoom(item)))];
    }
    async function entry() {
        epoch++; game = null; room = null; view = null; proposal = null; tab = 'place'; fresh = null;
        selectedOriginal = ''; clearHistory();
        Q.nav.pop?.('night-case-room'); Q.nav.pop?.('night-case-section'); Q.nav.pop?.('night-case-pick'); popFlow(); lookPick = null;
        worldPack = null; kit.useWorld?.(null);
        const generation = epoch;
        const [result, open, mine] = await Promise.all([request('/api/guest/rooms'),
            request('/api/guest/rooms/open').catch(() => null), request('/api/night-case/mine').catch(() => null), kit.worldIndex?.()]);
        if (!live() || generation !== epoch) return;
        const rooms = arr(result.items), cases = new Map(arr(mine?.items).map(row => [row.room_id, row]));
        const playing = rooms.map(item => ({item, row: cases.get(item.id)})).filter(({row}) => row?.seated && ['lobby', 'running'].includes(row.status));
        const arts = new Map(await Promise.all(playing.filter(({row}) => row.hero).map(async ({row}) => [row.room_id, await packArt(row.art, row.world)])));
        if (!live() || generation !== epoch) return;
        const mineCard = playing.length ? kit.panel({icon: 'story', title: 'Твои дела', count: String(playing.length)},
            ...playing.flatMap(({item, row}) => myCase(item, row, arts.get(row.room_id)))) : null;
        const list = el('ul', 'nc-list ncase-rows');
        for (const item of rooms) {
            const row = cases.get(item.id), action = button('Открыть', () => enterRoom(item));
            action.classList.add('compact');
            list.append(put(el('li'), thumbImg(row?.world || item.world), put(el('div'), el('span', 'ttl', item.title || 'Компания'),
                el('span', 'meta', mine ? companyLine(row) : item.role === 'owner' ? 'ты хозяин' : 'ты участник')), action));
        }
        if (!rooms.length) list.append(put(el('li', 'nc-empty'), el('span', 'nc-muted', 'Собери компанию и пригласи друзей: «Новое дело» внизу. Играть можно от 3 до 12 — сколько пришло, столько и играет, невзятых героев ведёт игра.')));
        const code = field('Код или ссылка приглашения');
        const join = kit.panel({icon: 'key', title: 'Войти по приглашению'}, code.node, kit.stack(button('Войти', async () => {
            const parsed = root.NightCity.parseInvite(code.input.value);
            if (parsed?.roomId) return enterRoom({id: parsed.roomId, title: 'Компания'});
            const token = parsed?.code || code.input.value.trim();
            const params = /^[A-Za-z0-9_-]{43}$/.test(token) ? {invite_code: token} : {short_code: token};
            const value = await mutate('/api/guest/rooms/join', params);
            if (value) await enterRoom(value);
        })));
        frame([kit.scene({shell: 'entry', size: 'tall', eyebrow: 'Детективы на неделю', title: 'Ночной город', text: 'Детективные истории в разных мирах. Компания берёт дело и неделю живёт в нём: заходи, когда удобно, игра сама напишет, что случилось.'}),
            put(el('div', 'nc-col'), mineCard, join),
            put(el('div', 'nc-col'), open ? openTables(arr(open.items).filter(item => item.game === 'night_case')) : null,
                kit.panel({icon: 'table', title: 'Твои компании', count: rooms.length ? String(rooms.length) : ''}, list))],
        'Ночной город', 'QuizzyWizzy', kit.dock({buttons: [button('Новое дело', () => showWorlds(null), 'primary')]}));
    }
    /* «Новое дело» (mockups 2–3): a world, then its case, then the company. `fresh.room` is set when an owner
       picks a case for a company that already exists; otherwise the company is created with the lobby. */
    const caseWorld = item => item.world || `case_${item.id}`;
    const casesOf = world => arr(boot?.cases).filter(item => caseWorld(item) === world);
    function showWorlds(target) {
        fresh = {room: target, world: fresh?.world || null, name: fresh?.name || '', zone: fresh?.zone || null, adult: false, screen: 'worlds'};
        popFlow();
        Q.nav.push?.({id: 'night-case-new', onBack: () => { const back = fresh?.room; fresh = null; popFlow(); (back ? enterRoom(back) : entry()).catch(fail); return true; }});
        return renderWorlds();
    }
    async function renderWorlds() {
        const generation = epoch, index = await kit.worldIndex?.();
        if (!live() || generation !== epoch || !fresh) return;
        fresh.screen = 'worlds'; worldPack = null; kit.useWorld?.(null);
        // Worlds of the index; a case whose world the index does not know still gets its own tile.
        const worlds = arr(index?.worlds).map(row => ({...row}));
        for (const item of arr(boot?.cases)) if (!worlds.some(row => row.id === caseWorld(item))) worlds.push({id: caseWorld(item), title: item.title, era: ''});
        if (!casesOf(fresh.world).length) fresh.world = worlds.find(row => casesOf(row.id).length)?.id || null;
        const grid = el('div', 'nc-worlds ncase-worlds');
        for (const world of worlds) {
            const count = casesOf(world.id).length, age = kit.worldAge?.(world.id, world.age) || 12, picked = world.id === fresh.world;
            const url = kit.thumbUrl?.(world) || '';
            const tile = put(el('button', `nc-world${count ? '' : ' soon'}`), url ? Object.assign(el('img'), {src: url, alt: ''}) : null,
                age >= 16 ? el('span', 'w-tag', `${age}+`) : null, picked ? tick() : null,
                put(el('span', 'w-copy'), el('span', 'w-name', world.title), world.era ? el('span', 'w-era', world.era) : null,
                    el('span', 'w-cases', count ? plural(count, 'дело', 'дела', 'дел') : 'дела пишутся')));
            tile.type = 'button';
            if (picked) tile.setAttribute('aria-pressed', 'true');
            if (count) tile.addEventListener('click', () => { if (fresh) { fresh.world = world.id; fresh.adult = false; renderWorlds(); } });
            else { tile.setAttribute('aria-disabled', 'true'); tile.setAttribute('aria-label', `${world.title}: дела пишутся`); }
            grid.append(tile);
        }
        const chosen = worlds.find(row => row.id === fresh.world), adultOnly = chosen && (kit.worldAge?.(chosen.id, chosen.age) || 12) >= 18;
        const next = !chosen ? null : adultOnly && !fresh.adult
            ? button('Мне есть 18', () => { fresh.adult = true; return showCase(); }, 'primary')
            : button(`Дальше: ${chosen.title}`, () => showCase(), 'primary');
        frame([kit.panel({cls: 'nc-span'}, el('p', 'nc-lead', 'Миры между собой не связаны: своё место, эпоха и правила о мистике. В каждом — свои дела на неделю.'), grid)],
            'Выбери мир', 'Ночной город · новое дело',
            kit.dock({hint: !chosen ? 'Дела пока недоступны' : adultOnly && !fresh.adult ? 'В этом мире есть сцены для взрослых' : '', buttons: next ? [next] : []}));
    }
    function showCase() {
        Q.nav.pop?.('night-case-case');
        Q.nav.push?.({id: 'night-case-case', onBack: () => { Q.nav.pop?.('night-case-case'); renderWorlds().catch(fail); return true; }});
        return renderCase();
    }
    // The device (or account) zone; the picker opens only on «Изменить пояс» (mockup 4).
    function zoneControl(zones) {
        let deviceZone = root.QW?.prefs?.deviceTimezone?.() || 'UTC';
        try { deviceZone = Intl.DateTimeFormat('en', {timeZone: deviceZone}).resolvedOptions().timeZone || deviceZone; } catch { deviceZone = 'UTC'; }
        const stored = Object.hasOwn(boot || {}, 'account_timezone');
        const preferredZone = stored ? (boot.account_timezone || deviceZone) : root.QW?.prefs?.resolvedTimezone?.() || deviceZone;
        const zone = root.QW?.prefs?.timezonePicker?.({zones, selected: fresh?.zone || preferredZone, label: 'Часовой пояс окон', searchLabel: 'Найти часовой пояс окон', fieldClass: 'ncase-field'});
        if (!zone) throw new Error('timezone_picker_unavailable');
        const line = p(`Окна дела откроются по поясу ${zone.input.value || preferredZone}: он взят с твоего ${stored && boot.account_timezone ? 'аккаунта' : 'устройства'}.`);
        zone.node.hidden = !fresh?.zone;
        line.hidden = Boolean(fresh?.zone);
        zone.input.addEventListener?.('change', () => { if (fresh) fresh.zone = zone.input.value; });
        const change = kit.button('Изменить пояс', () => { zone.node.hidden = false; line.hidden = true; change.hidden = true; zone.search?.focus?.(); }, {kind: 'text', compact: true});
        change.hidden = Boolean(fresh?.zone);
        return {nodes: [line, put(el('div', 'qw-btn-row ncase-left'), change), zone.node], value: () => zone.input.value};
    }
    async function renderCase() {
        if (!fresh) return;
        const cases = casesOf(fresh.world), item = cases.find(row => `${row.id}:${row.version}` === fresh.key) || cases[0];
        if (!item) return renderWorlds();
        fresh.key = `${item.id}:${item.version}`; fresh.screen = 'case';
        const generation = epoch;
        const [pack, art] = await Promise.all([item.world && kit.loadPack ? kit.loadPack(item.world) : null, packArt(item.art, item.world)]);
        if (!live() || generation !== epoch || !fresh) return;
        if (pack) { worldPack = pack; kit.useWorld(pack); }
        const entry = kit.worldEntry?.(item.world);
        const facts = put(el('div', 'ncase-facts'), item.players ? kit.tag(`${item.players.min}–${item.players.max} игроков`, {icon: 'people'}) : null,
            kit.tag('неделя: утро и вечер', {icon: 'calendar'}));
        const heroes = arr(item.heroes), npcs = arr(item.npc_heroes);
        const cast = heroes.length ? kit.panel({icon: 'people', title: 'Действующие лица', count: String(heroes.length)},
            p('Каждый выбирает себе персонажа. Кого не взяли, ведёт игра. Кто на чьей стороне, решит правда дела при старте.'),
            put(el('ul', 'ncase-castgrid'), ...heroes.map(hero => put(el('li'), artImage(art, arr(hero.looks)[0]?.art), el('span', 'nm', hero.title)))),
            npcRow({npc_heroes: npcs}, art)) : null;
        const step = (slot, title, body) => put(el('li'), Object.assign(el('img'), {src: kit.sceneUrl?.({slot, time: slot === 'night' ? 'night' : 'day', shell: 'table'}) || '', alt: ''}),
            put(el('div'), el('strong', null, title), el('span', null, body)));
        const how = kit.panel({icon: 'story', title: 'Как идёт дело'}, put(el('ol', 'ncase-how'),
            step('day', 'Ходи по местам дела', 'Утром и вечером открывается окно. Переход и осмотр тратят его действия.'),
            step('night', 'Находи улики', 'Находки видишь только ты, пока не выложишь их на доску дела.'),
            step('vote', 'Докажи на слушании', 'В конце недели каждый называет виновного и прикладывает улики.')));
        const zone = zoneControl(arr(item.timezones));
        const name = fresh.room ? null : field('Название компании', fresh.name);
        name?.input.addEventListener('input', () => { if (fresh) fresh.name = name.input.value; });
        const company = kit.panel({icon: 'table', title: fresh.room ? `Компания «${fresh.room.title || 'Компания'}»` : 'Твоя компания'},
            name ? name.node : null, name ? p('Компания — твои друзья по делу. Пригласишь их ссылкой из сбора.') : null, ...zone.nodes);
        const start = async () => {
            if (!fresh) return;
            if (!fresh.room && !name.input.value.trim()) { notice = 'Дай компании название.'; return renderCase(); }
            // A created company stays the target: a retry after a failed lobby does not create a second one.
            if (!fresh.room) fresh.room = await mutate('/api/guest/rooms', {request_id: id(), title: name.input.value}) || null;
            const target = fresh?.room;
            if (!target || !live()) return;
            const result = await mutate(`/api/rooms/${encodeURIComponent(target.id)}/night-case/lobby`, {command_id: id(), expected_lobby_revision: 0,
                params: {case_id: item.id, case_version: item.version, timezone: zone.value()}});
            if (!result?.view || !live()) return;
            fresh = null; popFlow(); room = target; game = result.view.game_id;
            Q.nav.push?.({id: 'night-case-room', onBack: () => { entry().catch(fail); return true; }});
            await refresh();
        };
        frame([kit.scene({slot: 'cover', size: 'tall', eyebrow: [entry?.title, entry?.era].filter(Boolean).join(' · ') || 'Дело недели', title: item.title, text: item.summary || '', body: [facts]}),
            put(el('div', 'nc-col'), cast), put(el('div', 'nc-col'), how, company)],
        item.title, `${entry?.title || 'Ночной город'} · дело`, kit.dock({buttons: [button(fresh.room ? 'Начать сбор' : 'Собрать компанию', start, 'primary')]}));
    }
    // Open lobbies of other companies: look at the table without a code; the hero is chosen in the lobby.
    function openTables(items) {
        const list = el('ul', 'nc-list ncase-rows');
        for (const table of items) {
            const seated = Number(table.seated) || 0, capacity = Number(table.capacity) || seated;
            const free = Math.max(0, capacity - seated), entry = kit.worldEntry?.(table.world), thumb = entry ? kit.thumbUrl?.(entry) : '';
            const meta = [table.case_title, free ? `свободно ${plural(free, 'место', 'места', 'мест')}` : 'мест нет',
                table.host_name ? `хозяин ${table.host_name}` : null].filter(Boolean).join(' · ');
            let action = null;
            action = table.joined ? button('Открыть', () => enterRoom({id: table.room_id, title: table.title}))
                : free ? button('Смотреть', () => joinOpen(table, action)) : el('span', 'nc-muted', 'стол полон');
            if (action.tagName === 'BUTTON') action.classList.add('compact');
            list.append(put(el('li'), thumb ? Object.assign(el('img', 'thumb'), {src: thumb, alt: ''}) : el('span'),
                put(el('div'), el('span', 'ttl', table.title || 'Компания'), el('span', 'meta', meta)), action));
        }
        if (!items.length) list.append(put(el('li', 'nc-empty'), el('span', 'nc-muted', 'Открытых сборов сейчас нет. Хозяин стола открывает сбор в карточке «Пригласить».')));
        return kit.panel({icon: 'people', title: 'Открытые сборы', count: items.length ? String(items.length) : ''}, list);
    }
    async function joinOpen(table, control, adult = false) {
        if (!adult && (Number(table.world_age) || 0) >= 18) {
            // An 18+ world: the newcomer confirms the age on the spot (the server does not store it).
            const confirm = button('Мне есть 18', () => joinOpen(table, confirm, true), 'primary'); confirm.classList.add('compact');
            control.replaceWith(confirm); return;
        }
        control.disabled = true; notice = '';
        try {
            const result = await request(`/api/guest/rooms/${encodeURIComponent(table.room_id)}/join-open`, {method: 'POST', body: adult ? {age_ok: true} : {}, key: id()});
            if (live()) await enterRoom(result?.room || {id: table.room_id, title: table.title});
        } catch (error) {
            if (!live()) return;
            control.disabled = false; notice = errorText(error);
            host.querySelector('.ncase-main')?.prepend(kit.alert({title: notice}));
        }
    }
    async function setOpen(on) {
        try {
            const next = await request(`/api/guest/rooms/${encodeURIComponent(room.id)}/open`, {method: 'POST', body: {open: on}});
            room = {...room, ...next};
        } catch (error) { notice = errorText(error); }
        render();
    }
    // The finished game stays readable from the history; the room screen offers the case list again.
    function newCase() {
        epoch++; game = null; view = null; proposal = null; tab = 'place'; worldPack = null; assetWorld = null; assets = new Map();
        kit.useWorld?.(null); clearHistory();
        renderRoom();
    }
    function renderRoom() {
        if (room?.role !== 'owner') return frame([panel(room?.title || 'Компания', p('Хозяин компании ещё не начал сбор на дело. Когда начнёт, здесь можно будет присоединиться.'), kit.row(button('Проверить', () => enterRoom(room))))], room?.title || 'Компания');
        if (!arr(boot?.cases).length) return frame([panel('Дело пока недоступно', p('Проверенные дела ещё не открыты для этой компании.'))], room?.title || 'Компания');
        frame([kit.scene({shell: 'rooms', title: room.title || 'Компания', text: 'У компании сейчас нет дела. Выбери мир и дело — каждый в компании потом сам присоединяется к сбору.'})],
            room.title || 'Компания', 'Ночной город', kit.dock({buttons: [button('Новое дело', () => showWorlds(room), 'primary')]}));
    }
    async function lobbyCommand(path, params = {}) {
        const result = await mutate(api(path), {command_id: id(), expected_lobby_revision: view.lobby.lobby_revision, params});
        if (path === 'leave') return entry();
        if (result) await refresh();
    }
    /* Free seating (lobby v2), mockup screens 4–5: every playable hero is a seat drawn as its portrait, the player is a plate on it;
       a hero with several characters opens its own pick screen. The owner's word on screen is «персонаж», not «облик». */
    const heroLook = (hero, lookId) => arr(hero?.looks).find(look => look.id === lookId) || arr(hero?.looks)[0] || {};
    const years = age => Number.isInteger(age) ? plural(age, 'год', 'года', 'лет') : '';
    const ownSeat = data => arr(data?.seats).find(row => row.seat === data.self_seat);
    const takeSeat = (heroId, lookId = null) => { lookPick = null; pickedLook = null; Q.nav.pop?.('night-case-pick'); return lobbyCommand('seat', {character_id: heroId, look_id: lookId}); };
    const openPick = hero => { lookPick = hero.id; pickedLook = null; Q.nav.push?.({id: 'night-case-pick', onBack: () => { lookPick = null; render(); return true; }}); render(); };
    const COLLECTIVE = {2: 'двоих', 3: 'троих', 4: 'четверых', 5: 'пятерых', 6: 'шестерых', 7: 'семерых', 8: 'восьмерых', 9: 'девятерых', 10: 'десятерых'};
    const FROM = {3: 'трёх', 4: 'четырёх', 5: 'пяти', 6: 'шести', 7: 'семи', 8: 'восьми', 9: 'девяти', 10: 'десяти', 11: 'одиннадцати', 12: 'двенадцати'};
    const lower = value => text(value).charAt(0).toLocaleLowerCase('ru') + text(value).slice(1);
    // The portrait of a look from the case pack; a neutral mark when the pack has none.
    function lookPortrait(look) {
        const art = assets.get(look?.art?.asset_id);
        if (!art) return put(el('span', 'blank'), icon('people'));
        const image = el('img'); image.src = art.url; image.alt = text(look.art?.alt).slice(0, 300) || art.alt || ''; image.loading = 'lazy';
        return image;
    }
    function heroCard(hero, data) {
        const sitter = arr(data.seats).find(row => row.character_id === hero.id), mine = Boolean(sitter) && sitter.seat === data.self_seat;
        const looks = arr(hero.looks), chosen = sitter && (sitter.look_id || !hero.multiple), look = chosen ? heroLook(hero, sitter.look_id) : looks[0] || {};
        const ages = [...new Set(looks.map(row => row.age).filter(Number.isInteger))];
        const sub = chosen ? [look.name, years(look.age)].filter(Boolean).join(', ')
            : [ages.length > 1 ? `${ages.slice(0, -1).join(', ')} или ${years(ages.at(-1))}` : years(ages[0]), looks.length > 1 ? plural(looks.length, 'персонаж', 'персонажа', 'персонажей') : ''].filter(Boolean).join(' · ');
        const pic = put(el('span', 'pic'), lookPortrait(look));
        if (sitter) {
            const plate = el('span', 'ncase-plate', mine ? 'ты' : seatName(sitter));
            if (sitter.ready) plate.prepend(icon('check'));
            pic.append(plate);
        }
        if (mine) pic.append(tick());
        const card = put(el('button', `ncase-hero${mine ? ' mine' : sitter ? ' taken' : ''}`), pic, put(el('span', 'cap'), el('span', 'nm', hero.title), sub ? el('span', 'sub', sub) : null));
        card.type = 'button';
        card.setAttribute('aria-label', [hero.title, sub, sitter ? `${mine ? 'твоё место' : 'занято: ' + seatName(sitter)}${sitter.ready ? ', готовность подтверждена' : ''}` : 'свободно'].filter(Boolean).join(' · '));
        if (mine) card.setAttribute('aria-pressed', 'true');
        // A free hero seats a joined player who is not yet ready; a taken one is closed; the own seat reopens the pick when the hero has several characters.
        const open = Boolean(data.self_seat) && !ownSeat(data)?.ready;
        const go = !open ? null : !sitter ? () => hero.multiple ? openPick(hero) : takeSeat(hero.id) : mine && hero.multiple ? () => openPick(hero) : null;
        card.disabled = !go && !mine || outbox.busy;
        if (go) card.addEventListener('click', () => Promise.resolve(go()).catch(fail));
        return card;
    }
    function anySeat(data) {
        const here = arr(data.seats).filter(row => !row.character_id), mine = here.some(row => row.seat === data.self_seat);
        const back = kit.art?.('card_back_role'), image = back ? el('img') : put(el('span', 'blank'), icon('people'));
        if (back) { image.src = back; image.alt = ''; }
        const who = here.length ? `Здесь: ${here.map(row => row.seat === data.self_seat ? 'ты' : seatName(row)).join(', ')}.` : '';
        const end = mine ? kit.tag('ты здесь', {tone: 'amber'}) : data.self_seat && !ownSeat(data)?.ready ? kit.button('Сесть', () => takeSeat(null).catch(fail), {compact: true, disabled: outbox.busy}) : null;
        return put(el('div', 'ncase-anyseat'), image, put(el('div'), el('strong', null, 'Любое свободное место'), el('span', 'nc-muted', ['Персонажа выберет игра при старте.', who].filter(Boolean).join(' '))), end);
    }
    function npcRow(data, map = assets) {
        const npcs = arr(data.npc_heroes);
        if (!npcs.length) return null;
        const faces = put(el('span', 'faces'), ...npcs.map(row => {
            const art = map.get(row.art?.asset_id);
            if (!art) return put(el('span', 'ncase-face xs blank'), icon('people'));
            const image = el('img', 'ncase-face xs'); image.src = art.url; image.alt = ''; image.loading = 'lazy'; return image;
        }));
        const names = npcs.map(row => lower(row.title)), shown = names.length > 5 ? [...names.slice(0, 4), 'другие'] : names;
        const list = shown.length > 1 ? `${shown.slice(0, -1).join(', ')} и ${shown.at(-1)}` : shown[0];
        return put(el('div', 'ncase-never'), faces, el('span', 'nc-muted', `${npcs.length === 1 ? 'Этого персонажа' : `Этих ${COLLECTIVE[npcs.length] || npcs.length}`} всегда ведёт игра: ${list}.`));
    }
    // «GMT+3» of a zone, or nothing when the runtime cannot name it.
    function zoneOffset(zone) {
        try { return new Intl.DateTimeFormat('en', {timeZone: zone, timeZoneName: 'shortOffset'}).formatToParts(new Date()).find(part => part.type === 'timeZoneName')?.value || ''; }
        catch { return ''; }
    }
    function windowsCard(data) {
        const slots = arr(data.windows?.slots), count = Number(data.windows?.count) || 14, zone = text(data.timezone) || 'UTC', offset = zoneOffset(zone);
        const when = slots.length === 2 ? `Утро в ${slots[0]}, вечер в ${slots[1]}` : slots.length ? `Окна открываются в ${slots.join(', ')}` : 'Окна открываются утром и вечером';
        return kit.panel({icon: 'calendar', title: 'Окна дела'}, el('p', 'nc-lead', `${when} по поясу ${zone}${offset && offset !== 'GMT' ? ` (${offset})` : ''}.`),
            p(`Пояс задал хозяин стола, когда собирал его. Неделя — ${plural(count, 'окно', 'окна', 'окон')}.`));
    }
    // Lobby talk (mockup 4, «Обсуждение»): the hero's portrait and title, the player as a plate; own lines on the right.
    // Everyone in the company reads it; only players at the table write. The draft outlives the poll re-render.
    function lobbyChat(data) {
        const lines = arr(data.chat), joined = Boolean(ownSeat(data));
        const rows = lines.map(line => {
            const hero = arr(data.heroes).find(row => row.id === line.character_id), look = hero ? heroLook(hero, line.look_id) : null;
            const who = put(el('span', 'ncase-who'), el('span', 'nm', hero ? hero.title : 'Любое место'),
                line.mine ? el('span', 'ncase-tag me', 'ты') : el('span', 'ncase-tag', seatName(line)));
            const art = assets.get(look?.art?.asset_id);
            const portrait = art ? Object.assign(el('img', 'ncase-face xs'), {src: art.url, alt: '', loading: 'lazy'}) : put(el('span', 'ncase-face xs blank'), icon('people'));
            return put(el('div', `nc-msg${line.mine ? ' mine' : ''}`), line.mine ? null : portrait, put(el('div', 'bub'), who, p(line.text)));
        });
        const feed = rows.length ? put(el('div', 'nc-chat ncase-lobbychat'), ...rows) : p('Пока тихо. Договоритесь, кто кого играет и когда начинаете.');
        if (rows.length) root.requestAnimationFrame?.(() => { feed.scrollTop = feed.scrollHeight; });
        if (!joined) return kit.panel({icon: 'talk', title: 'Обсуждение', count: lines.length ? String(lines.length) : ''}, feed, p('Писать могут игроки за столом.'));
        const input = el('input', 'nc-field'); input.type = 'text'; input.value = lobbyDraft; input.maxLength = 500;
        input.placeholder = 'Сообщение'; input.setAttribute('aria-label', 'Сообщение в обсуждении'); input.autocomplete = 'off';
        input.addEventListener('input', () => { lobbyDraft = input.value; });
        const send = button('Отправить', async () => {
            const value = lobbyDraft.trim();
            if (!value) return;
            sending = 'Сообщение';
            const result = await mutate(api('lobby-chat'), {command_id: id(), text: value});
            sending = '';
            if (result?.message) { lobbyDraft = ''; chatFocus = true; await refresh(); }
        });
        input.addEventListener('keydown', event => { if (event.key === 'Enter') { event.preventDefault?.(); send.click(); } });
        // After a sent line the field keeps the focus, so a conversation goes on without a tap.
        if (chatFocus) { chatFocus = false; root.requestAnimationFrame?.(() => input.focus?.()); }
        return kit.panel({icon: 'talk', title: 'Обсуждение', count: lines.length ? String(lines.length) : ''}, feed, put(el('div', 'nc-join'), input, send));
    }
    function openLobby() {
        const data = view.lobby, seats = arr(data.seats), mine = ownSeat(data), owner = room?.role === 'owner';
        const counts = arr(data.allowed_counts), lo = counts[0] || 3;
        const ready = seats.filter(row => row.ready).length, free = arr(data.heroes).filter(hero => !seats.some(row => row.character_id === hero.id)).length;
        const name = field('Имя в этой партии', mine?.name || '');
        const address = choose('Как обращаться в этой партии', [{id: 'n', label: 'Без рода'}, {id: 'm', label: 'Он'}, {id: 'f', label: 'Она'}], data.self?.address_form || 'n');
        if (mine?.ready) { name.input.disabled = true; address.input.disabled = true; }
        lobbyFields = {name: name.input, address: address.input};
        const scene = kit.scene({slot: 'lobby', size: 'short', eyebrow: `Сбор открыт · за столом ${seats.length}`, title: `Готовы ${ready} из ${seats.length}`,
            text: `Выбери персонажа или садись на любое свободное место. Начать можно с ${FROM[lo] || lo} игроков: невзятых персонажей поведёт игра.`,
            bar: kit.track({total: seats.length, taken: seats.length, ready, label: `Готовы ${ready} из ${seats.length}`})});
        const table = kit.panel({icon: 'people', title: 'Места за столом', count: `свободно ${free}`, cls: 'nc-span'},
            put(el('div', 'ncase-heroes'), ...arr(data.heroes).map(hero => heroCard(hero, data))), anySeat(data), npcRow(data));
        const place = mine ? kit.panel({icon: 'seal', title: 'Как тебя звать'}, p(mine.ready ? 'Готовность подтверждена. Чтобы сменить имя или место, сними её.' : 'Имя и обращение видят все за столом. Потом подтверди готовность внизу.'), name.node, address.node) : null;
        const leave = mine ? put(el('div', 'qw-danger-zone'), button('Покинуть сбор', () => { proposal = {leaveLobby: true, label: 'Покинуть сбор игроков?'}; render(); }, 'danger')) : null;
        return [scene, table, put(el('div', 'nc-col'), lobbyChat(data), place, narratorLobby()), put(el('div', 'nc-col'), owner ? invitePanel() : null, windowsCard(data), leave)];
    }
    // The ready toggle sits in the dock and reads the fields of «Как тебя звать» from main.
    let lobbyFields = null;
    function lobbyDock() {
        const data = view.lobby, mine = ownSeat(data), owner = room?.role === 'owner';
        if (!mine) return kit.dock({hint: 'Ты ещё не за столом', buttons: [button('Присоединиться к столу', () => lobbyCommand('join'), 'primary')]});
        const hero = arr(data.heroes).find(row => row.id === mine.character_id), form = data.self?.address_form || 'n';
        const look = hero && (mine.look_id || !hero.multiple) ? heroLook(hero, mine.look_id) : null;
        const who = !hero ? 'Ты на любом свободном месте' : `Ты — ${hero.title}${look ? [look.name ? ', ' + look.name : '', Number.isInteger(look.age) ? ', ' + years(look.age) : ''].join('') : ' (персонажа выберет игра)'}`;
        const state = mine.ready ? (form === 'f' ? 'готова' : form === 'm' ? 'готов' : 'готовность подтверждена') : form === 'f' ? 'ещё не готова' : form === 'm' ? 'ещё не готов' : 'готовность не подтверждена';
        const readyLabel = mine.ready ? 'Снять готовность' : form === 'f' ? 'Я готова' : 'Я готов';
        const buttons = [button(readyLabel, () => lobbyCommand('ready', {name: lobbyFields?.name.value ?? mine.name ?? '', address_form: lobbyFields?.address.value || form, ready: !mine.ready}), owner ? 'secondary' : 'primary')];
        if (owner) { const start = button('Начать дело', () => startGame(), 'primary'); start.disabled = start.disabled || !data.can_start; buttons.push(start); }
        return kit.dock({layout: 'row', hint: [who, state, owner ? 'ты хозяин стола' : ''].filter(Boolean).join(' · '), buttons});
    }
    let pickedLook = null;
    function pickScreen(hero) {
        const looks = arr(hero.looks), mine = ownSeat(view.lobby), current = mine?.character_id === hero.id ? mine.look_id : null;
        if (!looks.some(look => look.id === pickedLook)) pickedLook = current || looks[0]?.id || null;
        const cards = looks.map(look => {
            const he = look.gender === 'f' ? 'она' : look.gender === 'm' ? 'он' : '';
            const card = put(el('button', 'ncase-look'), put(el('span', 'pic'), lookPortrait(look), look.id === pickedLook ? tick() : null),
                put(el('span', 'cap'), el('span', 'nm', [look.name || look.title, Number.isInteger(look.age) ? look.age : ''].filter(Boolean).join(', ')),
                    el('span', 'sub', [he, lower(look.title || hero.title)].filter(Boolean).join(' · '))));
            card.type = 'button'; card.setAttribute('aria-pressed', String(look.id === pickedLook));
            card.addEventListener('click', () => { pickedLook = look.id; render(); });
            return card;
        });
        const about = bodyText(heroLook(hero, pickedLook).public);
        return [kit.panel({cls: 'nc-span'}, el('span', 'nc-eyebrow', `Место «${hero.title}» · ${plural(looks.length, 'персонаж', 'персонажа', 'персонажей')}`), el('h2', 'nc-h3', 'Кого ты играешь?'),
            p(`Роль в деле одна, персонажи разные: своё имя, возраст, портрет и обращение.${about ? ' ' + about : ''}`), put(el('div', 'ncase-looks'), ...cards))];
    }
    function pickDock(hero) {
        const look = heroLook(hero, pickedLook), any = arr(hero.looks).length === 2 ? 'Любой из двух' : 'Любой из них';
        return kit.dock({layout: 'row', buttons: [button(any, () => takeSeat(hero.id)), button(`Сесть: ${look.name || look.title || hero.title}`, () => takeSeat(hero.id, look.id), 'primary')]});
    }
    function lobby() {
        if (view.lobby?.seating === 'open') return openLobby();
        const data = view.lobby, own = arr(data.seats).find(row => row.seat === data.self_seat);
        const name = field('Имя в этой партии', own?.name || '');
        const address = choose('Как обращаться в этой партии', [{id: 'n', label: 'Без рода'}, {id: 'm', label: 'Он'}, {id: 'f', label: 'Она'}], data.self?.address_form || 'n');
        const buttons = data.self_seat ? [button(own?.ready ? 'Изменить имя и готовность' : 'Я готов', () => lobbyCommand('ready', {name: name.input.value, address_form: address.input.value, ready: !own?.ready})),
            ...(data.can_start ? [button('Начать дело', () => startGame(), 'primary')] : [])] : [button('Присоединиться к столу', () => lobbyCommand('join'), 'primary')];
        return [kit.scene({slot: 'lobby', title: data.case?.title || 'Собираем стол', text: `${data.seats.length} из 12 игроков. Стартуют 4, 5, 8 или 12; каждый подтверждает готовность.`}),
            panel('Стол игроков', kit.seats(arr(data.seats).map(item => ({name: seatName(item), line: item.ready ? 'Готов' : 'Ещё не готов', me: item.seat === data.self_seat})))),
            narratorLobby(),
            panel('Твоё место', ...(data.self_seat ? [name.node, address.node] : []), kit.stack(...buttons)),
            ...(room?.role === 'owner' ? [invitePanel()] : []),
            ...(data.self_seat ? [panel('Выход', kit.stack(button('Покинуть сбор', () => { proposal = {leaveLobby: true, label: 'Покинуть сбор игроков?'}; render(); }, 'danger')))] : [])];
    }
    function openToggle() {
        if (room?.role !== 'owner' || typeof room.open !== 'boolean' || !kit.toggle) return null;
        const until = room.open && room.open_expires_at ? new Date(room.open_expires_at) : null;
        const clock = until && !Number.isNaN(until.getTime()) ? `${String(until.getHours()).padStart(2, '0')}:${String(until.getMinutes()).padStart(2, '0')}` : '';
        return kit.toggle({title: 'Открытый сбор', on: room.open, onChange: on => setOpen(on),
            text: room.open ? `Стол виден в «Открытых сборах»${clock ? `; без движения за столом уйдёт из списка в ${clock}` : ''}.`
                : 'Чужие игроки увидят стол в «Открытых сборах» и смогут сесть на свободное место.'});
    }
    function invitePanel() {
        const create = button('Создать приглашение', async () => {
            create.disabled = true;
            try {
                invitation = await request(`/api/guest/rooms/${encodeURIComponent(room.id)}/invites`, {method: 'POST', body: {expires_in_seconds: 86400, max_uses: 12}});
                render();
            } finally { create.disabled = false; }
        });
        if (!invitation) return panel('Пригласить друзей', p('Ссылка добавляет в компанию. Каждый отдельно присоединится к сбору; в Telegram-чат она никого не добавляет.'), kit.row(create), openToggle());
        const link = field('Ссылка в компанию', invitation.web_url || ''); link.input.readOnly = true;
        return panel('Пригласить друзей', kit.ticket({code: invitation.short_code, onCopy: async code => { await navigator.clipboard.writeText(code); notice = 'Код скопирован.'; render(); }}),
            link.node, kit.row(button('Скопировать ссылку', async () => { await navigator.clipboard.writeText(link.input.value); notice = 'Ссылка скопирована.'; render(); })),
            p('Отправь код или ссылку друзьям. Присоединение к партии остаётся отдельным действием.'), openToggle());
    }
    // Section tabs as on the mockups: a sign over the label, a badge with what is new since the player last looked.
    // «Гостиная у камина» is the shared feed (talk and the case's shared events); the personal events are in «Досье».
    const TABS = [['place', 'house', 'Место'], ['feed', 'talk', 'Гостиная'], ['board', 'lens', 'Улики'], ['self', 'seal', 'Досье']];
    const tabCount = key => key === 'feed' ? Number(view?.public?.chronicle_count) || 0 : key === 'board' ? arr(view?.public?.board).length : 0;
    function badge(key) {
        if (!(key in looked)) return 0;
        const now = tabCount(key);
        if (looked[key] == null || tab === key || looked[key] > now) looked[key] = now;
        return now - looked[key];
    }
    function navigation() {
        const nav = el('nav', 'ncase-nav ncase-tabs'); nav.setAttribute('aria-label', 'Разделы дела');
        return put(nav, ...TABS.map(([key, sign, label]) => {
            const control = el('button', null, label); control.type = 'button';
            control.prepend(icon(sign));
            const fresh = badge(key);
            if (fresh > 0) { const mark = el('b', 'ncase-badge', fresh > 99 ? '99+' : fresh); mark.setAttribute('aria-label', `новых: ${fresh}`); control.append(mark); }
            control.addEventListener('click', () => Promise.resolve((async () => { showTab(key); await loadTab(key); render(); })()).catch(fail));
            control.setAttribute('aria-current', tab === key ? 'page' : 'false'); return control;
        }));
    }
    // Screen 6/11: the role card in the world's hero frame (portrait of this party's look, side sign), then side, secret and goal.
    const SIDES = {investigation: ['Твоя сторона — следствие', 'Знак Следствия'], shadow: ['Твоя сторона — Тень', 'Знак Тени'], independent: ['Ты сам по себе', 'Независимые']};
    function roleCard(data, faction, turning = false) {
        const artwork = assets.get(data.art?.asset_id);
        const figure = el('figure', `ncase-rolecard${turning ? ' turned' : ''}`), frame = el('span', `face${view.self?.status === 'ghost' ? ' ncase-out' : ''}`);
        if (artwork) {
            const portrait = el('img', 'ncase-role-portrait'); portrait.src = artwork.url;
            portrait.alt = text(data.art?.alt).slice(0, 300) || artwork.alt || data.title || 'Портрет роли'; frame.append(portrait);
        }
        figure.append(frame);
        const frameUrl = kit.art?.('frame_hero');
        if (frameUrl) { const border = el('img', 'frame'); border.src = frameUrl; border.alt = ''; figure.append(border); }
        const emblemUrl = kit.art?.(`emblem_${faction}`), side = el('span', 'side', (SIDES[faction] || SIDES.investigation)[1]);
        if (emblemUrl) { const emblem = el('img'); emblem.src = emblemUrl; emblem.alt = ''; side.prepend(emblem); }
        figure.append(put(el('figcaption'), el('span', 'eyebrow', 'Видишь только ты'), el('strong', null, data.title || 'Твоя роль'), side));
        if (turning) { figure.style?.setProperty?.('--dir', String(kit.flip?.dir || 1)); if (kit.flip) kit.flip.dir = 1; }
        return figure;
    }
    function role(turning = false) {
        if (!turning) return dossier();
        const own = view.self, data = own.role || {}, faction = SIDES[own.faction] ? own.faction : 'investigation';
        const look = [data.name, data.age ? plural(Number(data.age), 'год', 'года', 'лет') : ''].filter(Boolean).join(', ');
        return [put(el('section', 'ncase-reveal'), put(el('div', 'ncase-rolewrap'), roleCard(data, faction, turning), put(el('div', 'ncase-role-copy'),
            card('scales', faction === 'independent' ? said('Ты сам по себе', 'Ты сама по себе') : SIDES[faction][0], '', look ? p(look) : null, p(bodyText(data.bio))),
            arr(own.secrets).length ? card('seal', 'Твоя тайна', '', ...arr(own.secrets).map(item => kit.secret(bodyText(item)))) : null,
            card('laurel', 'Твоя цель', '', p(bodyText(own.goal?.body)), el('h3', 'nc-h3', 'Как засчитывается цель'), p(bodyText(own.goal?.criteria)),
                ...arr(own.personal?.work_progress).map(item => p(`Этапов работы завершено: ${item.completed_stages.length}`))),
            own.truth ? card('eye', 'Что ты знаешь о случившемся', '', kit.secret(bodyText(own.truth.motive)), kit.secret(bodyText(own.truth.method))) : null)))];
    }
    // Screen 11 «Досье» (mockup 11): who you are, the goal and the secret on the left; notes for you and your events on the right.
    function dossier() {
        const own = view.self, data = own.role || {}, faction = SIDES[own.faction] ? own.faction : 'investigation', char = own.character_id;
        const side = el('span', 'ncase-side', SIDES[faction][1]), emblem = kit.art?.(`emblem_${faction}`);
        if (emblem) { const image = el('img'); image.src = emblem; image.alt = ''; side.prepend(image); }
        const person = [data.name, data.age ? plural(Number(data.age), 'год', 'года', 'лет') : ''].filter(Boolean).join(', ');
        const me = card(null, '', '', put(el('div', 'ncase-me'), portraitFrame(char, face(char, 'ncase-face lg')),
            put(el('div'), el('span', 'nc-eyebrow', 'Видишь только ты'), el('strong', null, data.title || heroTitle(char) || 'Твоя роль'),
                person ? el('span', 'nc-muted', person) : null, side)),
            bodyText(data.bio) ? el('p', 'nc-muted', bodyText(data.bio)) : null);
        const goal = card('laurel', 'Цель', '', el('p', 'nc-lead', bodyText(own.goal?.body)),
            bodyText(own.goal?.criteria) ? el('p', 'nc-muted', `Как засчитывается: ${bodyText(own.goal.criteria)}`) : null,
            ...arr(own.personal?.work_progress).map(item => p(`Этапов работы завершено: ${item.completed_stages.length}`)));
        const secrets = arr(own.secrets).length ? card('seal', 'Тайна', '', put(el('div', 'ncase-secrets'), ...arr(own.secrets).map(item => kit.secret(bodyText(item))))) : null;
        const truth = own.truth ? card('eye', 'Что ты знаешь о случившемся', '', put(el('div', 'ncase-secrets'), kit.secret(bodyText(own.truth.motive)), kit.secret(bodyText(own.truth.method)))) : null;
        const archive = arr(own.modules?.archive_requests?.requests).length ? card('papers', 'Запросы в архив', '', ...arr(own.modules.archive_requests.requests)
            .map(item => p(item.status === 'pending' ? 'Запрос отправлен. Ответ придёт в следующем игровом окне.' : 'Архивный ответ — в твоих событиях.'))) : null;
        const column = (...children) => put(el('div', 'nc-col'), ...children.filter(Boolean));
        return [column(me, goal, secrets, truth), column(notes(), ownEvents(), archive)];
    }
    // «Записки»: private lines other players sent you (a private talk at one place); you answer them in «Гостиная» — «Приватно».
    function notes() {
        const own = view.self.account_id;
        const rows = pages.messages.items.filter(row => row.channel === 'whisper' && row.sender_account_id !== own).slice().reverse();
        if (!rows.length) return null;
        return card('envelope', 'Записки', plural(rows.length, 'записка', 'записки', 'записок'), ...rows.map(row => {
            const char = charOfAccount(row.sender_account_id), seat = arr(view.public.players).find(item => item.account_id === row.sender_account_id);
            return put(el('article', 'ncase-note'), put(el('div', 'from'), char ? portraitFrame(char, face(char, 'ncase-face xs')) : null,
                put(el('span', 'ncase-who'), el('span', 'nm', char ? `от ${heroAs(char, 'gen')}` : 'от участника'), seat ? el('span', 'ncase-tag', seatName(seat)) : null),
                row.window_idx ? el('span', 'nc-muted', `окно ${row.window_idx}`) : null), p(row.text));
        }), el('p', 'nc-muted', 'Записку видишь только ты. Ответить можно в «Гостиной» — «Приватно», если вы в одном месте.'));
    }
    /* Screen 6: in the first window the role comes as a card back; a tap turns it over, «Понятно, в усадьбу» goes to the
       place. Remembered for this session only: the client keeps nothing of the case on the device. */
    const seenRoles = new Set();
    let turned = false;
    const roleSeen = () => options.revealRole === false || seenRoles.has(game);
    function revealRole(clock) {
        const eyebrow = `Дело началось · окно ${clock.window_idx || 1}`;
        if (!turned) {
            const open = () => { turned = true; render(); };
            return frame([put(el('section', 'ncase-reveal ncase-turn'), kit.roleCard?.({face: false, onOpen: open}),
                p('Твоя роль — тайна дела. Переверни карту, когда никто не смотрит в твой экран.'))],
            'Твоя роль', eyebrow, kit.dock({hint: 'Нажми на карту или на кнопку', buttons: [button('Перевернуть карту', open, 'primary')]}));
        }
        const done = () => { seenRoles.add(game); turned = false; showTab('place'); render(); };
        return frame(role(true), 'Твоя роль', eyebrow, kit.dock({hint: 'Досье всегда открыто во вкладке «Досье»', buttons: [button('Понятно, в усадьбу', done, 'primary')]}));
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

    /* ---- case components (mockups docs/design/mockups/night-case, styles in night-case.css; MQB-012 stage 1) ---- */
    const TIME_WORDS = {morning: 'Утро', day: 'День', evening: 'Вечер', night: 'Ночь'};
    const icon = name => (kit.icon ? kit.icon(name) : el('span', 'ic'));
    const card = (iconName, title, count, ...children) => kit.panel({icon: iconName, title, count}, ...children);
    const plural = (n, one, few, many) => `${n} ${n % 10 === 1 && n % 100 !== 11 ? one : [2, 3, 4].includes(n % 10) && ![12, 13, 14].includes(n % 100) ? few : many}`;
    // «1 действие» over a group when every choice in it costs the same.
    const costLine = rows => { const costs = new Set(rows.map(row => Number(row.quote.cost) || 0)); const cost = costs.size === 1 ? [...costs][0] : 0; return cost ? plural(cost, 'действие', 'действия', 'действий') : ''; };
    // Action points as diamonds: lit — left in this window.
    function apMeter(left) {
        const total = Math.max(3, Number(left) || 0), node = el('span', 'ncase-ap');
        node.setAttribute('aria-label', `Действий осталось: ${left} из ${total}`);
        for (let i = 0; i < total; i++) node.append(el('i', i < left ? 'on' : ''));
        node.append(el('b', null, `${left} из ${plural(total, 'действия', 'действий', 'действий')}`));
        return node;
    }
    // The portrait of a hero in this party's look, cropped to the head; a neutral mark when the pack has none.
    const lookOf = char => { const looks = view?.public?.looks; return (looks && typeof looks === 'object' ? looks[char] : null) || null; };
    function face(char, cls = 'ncase-face') {
        const art = assets.get(lookOf(char)?.art?.asset_id);
        if (!art) return put(el('span', `${cls} blank`), icon('people'));
        const image = el('img', cls); image.src = art.url; image.alt = ''; image.loading = 'lazy';
        return image;
    }
    const heroTitle = char => text(lookOf(char)?.title) || nameOf(char);
    // Owner's answer B1 (2026-11-26): texts decline by the character — its gender and its title in the case
    // (gen/dat/acc/ins/prep from the case's title_forms), not by the player's address form.
    const heroAs = (char, form) => text(lookOf(char)?.title_forms?.[form]) || heroTitle(char);
    // In pickers: the hero first, the player beside.
    const heroLabel = char => { const seat = arr(view?.public?.players).find(row => row.character_id === char); return seat ? `${heroTitle(char)} · ${seatName(seat)}` : heroTitle(char); };
    // The hero first, the player as a small plate beside (NIGHT_CITY_MENU_DESIGN §3.4).
    function plate(row) {
        if (row.controller === 'npc') return el('span', 'ncase-tag game', 'ведёт игра');
        return row.character_id === view.self?.character_id ? el('span', 'ncase-tag me', 'ты') : el('span', 'ncase-tag', seatName(row));
    }
    // Out of play: a removed hero is darkened (owner decision); «killed» waits for a case with deaths and the owner's pick (B7).
    const removed = char => arr(view?.public?.players).some(item => item.character_id === char && item.status === 'ghost');
    const portraitFrame = (char, node) => removed(char) ? put(el('span', 'ncase-faceframe ncase-out'), node) : node;
    // Like a messenger: «в сети» while the case is open (the client reports every 3 minutes), then how long ago, by the hero's gender.
    function seenText(char) {
        const seat = arr(view?.public?.players).find(item => item.character_id === char);
        if (!seat?.seen_at || seat.account_id === view.self?.account_id || seat.status === 'departed') return '';
        const at = new Date(seat.seen_at), now = Date.parse(view.server_now) || Date.now(), minutes = Math.floor((now - at.getTime()) / 60000);
        if (!Number.isFinite(minutes)) return '';
        const was = lookOf(char)?.gender === 'f' ? 'была' : 'был', hhmm = `${at.getHours()}:${String(at.getMinutes()).padStart(2, '0')}`;
        const day = date => new Date(date).setHours(0, 0, 0, 0), days = Math.round((day(now) - day(at)) / 86400000);
        if (minutes < 5) return 'в сети';
        if (minutes < 60) return `${was} ${minutes} мин назад`;
        if (days === 0) return `${was} сегодня в ${hhmm}`;
        if (days === 1) return `${was} вчера в ${hhmm}`;
        return days < 7 ? `${was} ${plural(days, 'день', 'дня', 'дней')} назад` : `${was} давно`;
    }
    const seenLine = char => { const value = seenText(char); return value ? el('span', `ncase-seen${value === 'в сети' ? ' on' : ''}`, value) : null; };
    const person = row => put(el('li', `ncase-person${row.controller === 'npc' ? ' npc' : ''}`), portraitFrame(row.character_id, face(row.character_id)), el('span', 'nm', heroTitle(row.character_id)), plate(row),
        row.controller === 'npc' ? null : seenLine(row.character_id));
    const pressed = row => proposal?.selection_id && proposal.selection_id === row.quote.selection_id;
    // An action as a tile: the item or the speaker's portrait, else the verb's sign; the confirmation names the full action.
    function actTile(row, label, {face: speaker = null, sub = '', sign = 'eye', full = label} = {}) {
        const tile = el('button', 'ncase-act'); tile.type = 'button';
        const art = assets.get(row.art?.asset_id);
        let pic;
        if (speaker) pic = face(speaker, 'face');
        else if (art) { pic = el('img', 'obj'); pic.src = art.url; pic.alt = ''; }
        else pic = put(el('span', 'obj sign'), icon(sign));
        put(tile, pic, put(el('span'), el('span', 'nm', label), sub ? el('span', 'sub', sub) : null));
        if (pressed(row)) tile.setAttribute('aria-pressed', 'true');
        if (outbox.busy) tile.disabled = true;
        tile.addEventListener('click', () => Promise.resolve(selectAction(row, full)).catch(fail));
        return tile;
    }
    // A talk as a tile: the hero's portrait and title, the question under it (always: «Расспросить дворецкого про ночь»
    // names the butler, yet without it three tiles of one hero look the same); the confirmation names both.
    const talkTile = row => actTile(row, row.npc_title || row.label, {face: row.npc_character_id, sub: row.npc_title ? row.label : '',
        full: row.npc_title && !mentions(row.label, row.npc_title) ? `${row.label} · ${row.npc_title}` : row.label});
    // A neighbouring place as a picture at this time of day.
    function placeTile(row) {
        const target = arr(view.public.locations).find(item => item.id === row.quote.params?.location);
        const art = assets.get(target?.art?.asset_id), time = sceneTime();
        const tile = el('button', 'ncase-go'); tile.type = 'button';
        if (art) { const image = el('img'); image.src = art.variants?.[time] || art.url; image.alt = ''; image.loading = 'lazy'; tile.append(image); }
        // Who is where stays private (the public view has no positions), so the tile shows only the place.
        put(tile, put(el('span', 'cap'), el('span', 'nm', target?.name || row.label)));
        if (pressed(row)) tile.setAttribute('aria-pressed', 'true');
        if (outbox.busy) tile.disabled = true;
        tile.addEventListener('click', () => Promise.resolve(selectAction(row, `Перейти: ${target?.name || row.label}`)).catch(fail));
        return tile;
    }
    const windowKey = () => `${game}:${view?.public?.clock?.window_seq}`;
    const actingAgain = () => reopened === windowKey();
    // Finding 5: what this window's inspection here turned up stays on the place, in the evidence frame; all finds are in «Улики».
    function foundHere(own, location) {
        const idx = view.public.clock?.window_idx;
        const items = arr(own.observations).filter(item => item.source?.kind === 'action' && item.source?.window_idx === idx && item.source?.location === location?.id);
        if (!items.length) return null;
        return card('lens', 'Найдено здесь', String(items.length), ...items.map(item => evidenceCard(item, 'Твоя находка · видишь только ты')),
            kit.stack(button('Все находки — в «Уликах»', () => showTab('board'))));
    }
    // Screen 8 «Разговор» (mockup 8): the speaker, the question and the answer, what went to the finds, the next questions.
    const talking = () => Boolean(conversation && conversation.key === windowKey() && tab === 'place' && view?.self?.status === 'active');
    function talkScreen() {
        const own = view.self, npc = conversation.npc, location = arr(view.public.locations).find(item => item.id === own.location);
        const answer = arr(own.results).find(item => conversation.events.includes(item.event_id));
        const known = new Map(arr(own.observations).map(item => [item.observation_id, item]));
        const look = lookOf(npc), line = bodyText(look?.public) || text(look?.public);
        const speaker = put(el('section', 'nc-card nc-span'), put(el('div', 'ncase-npc'), face(npc, 'portrait'),
            put(el('div'), el('span', 'nc-eyebrow', `${location?.name || 'Усадьба'} · ${TIME_WORDS[sceneTime()].toLowerCase()}`),
                put(el('span', 'ncase-who'), el('span', 'nm', heroTitle(npc)), el('span', 'ncase-tag game', 'ведёт игра')),
                line ? el('p', 'nc-muted', line) : null)));
        const said_ = answer ? bodyText(answer.body) || text(answer.body) : '';
        const found = arr(answer?.observation_ids).map(id => known.get(id)).filter(Boolean);
        const chat = card('talk', 'Разговор', '', put(el('div', 'nc-chat'),
            put(el('div', 'nc-msg mine'), put(el('div', 'bub'), p(conversation.question))),
            put(el('div', 'nc-msg'), face(npc, 'ncase-face xs'), put(el('div', 'bub ncase-npc-say'), el('span', 'who', heroTitle(npc)),
                p(said_ || 'Ответ ещё в пути: он появится здесь и в «Досье».'))),
            ...found.map(item => put(el('span', 'nc-sys'), icon(item.kind === 'claim' ? 'story' : 'lens'),
                `В твои находки: «${item.title}» — ${item.kind === 'claim' ? 'утверждение' : 'доказательство'}`))));
        const more = choiceList().filter(row => row.quote.kind === 'talk' && row.npc_character_id === npc);
        const ask = card('talk', 'Расспросить', costLine(more), more.length
            ? put(el('div', `ncase-acts${more.length === 1 ? ' one' : ''}`), ...more.map(row => actTile(row, row.label, {face: npc, full: `${row.label} · ${heroTitle(npc)}`})))
            : p(`${heroTitle(npc)} сейчас больше ничего не добавит.`));
        return [speaker, put(el('div', 'nc-col'), chat), put(el('div', 'nc-col'), ask)];
    }
    function talkDock() {
        const left = Number(view.self.ap) || 0, cost = conversation.cost;
        return kit.dock({hint: `${cost ? `Разговор стоил ${plural(cost, 'действие', 'действия', 'действий')} · ` : ''}осталось ${plural(left, 'действие', 'действия', 'действий')}`,
            buttons: [button('К месту', () => { conversation = null; render(); }, 'primary')]});
    }
    // Screen 7 «Место» (mockups, MQB-012 stage 2): the place by time of day with the action points, the window's event,
    // the people nearby by portrait, where to go as place tiles and what to do as action tiles.
    function place() {
        const own = view.self, location = arr(view.public.locations).find(item => item.id === own.location);
        const over = Boolean(view.public.final || view.final_summary);
        const moves = choiceList().filter(row => row.quote.kind === 'move');
        const acts = choiceList().filter(row => ['act', 'archive_request', 'story_reply'].includes(row.quote.kind));
        const talks = choiceList().filter(row => row.quote.kind === 'talk');
        const nearby = arr(own.nearby).filter(row => row.character_id !== own.character_id);
        const time = sceneTime(), ghost = own.status === 'ghost', departed = own.status === 'departed';
        const scene = put(el('section', 'nc-hero ncase-place'), put(el('div', 'copy'),
            el('span', 'nc-eyebrow', departed ? TIME_WORDS[time] : `${TIME_WORDS[time]} · ты здесь`), el('h2', null, location?.name || 'Усадьба'), p(bodyText(location?.body)),
            over || ghost || departed ? null : put(el('div', 'ncase-hero-row'), apMeter(own.ap)), over || departed ? null : narratorLine()));
        const artwork = assets.get(location?.art?.asset_id);
        scene.style?.setProperty('--img', artwork ? `url(${artwork.variants?.[time] || artwork.url})` : 'none');
        if (over) return [scene];
        const window_ = view.public.clock?.window_idx;
        const current = arr(view.public.scenes).filter(entry => entry.window_idx === window_).at(-1);
        const shared = current ? put(el('section', 'nc-card'), put(el('div', 'ncase-event'), sceneArt(current.art, 'Сцена окна'),
            put(el('div'), el('span', 'nc-eyebrow', 'Сейчас в усадьбе'), p(bodyText(current.body))))) : null;
        if (ghost) return [scene, shared, ...removedActions()];
        // Finding 7: a player who left the case reads the place and the window's event, nothing to do or go to.
        if (departed) return [scene, shared];
        const found = foundHere(own, location);
        // Finding 4: a finished window closes the place; «Ещё действовать» in the window bar reopens it.
        const people = card('people', 'Кто рядом', nearby.length ? String(nearby.length) : '',
            nearby.length ? put(el('ul', 'ncase-people'), ...nearby.map(person)) : p(said('Сейчас ты здесь один.', 'Сейчас ты здесь одна.')));
        if (own.finished_window && !actingAgain()) return [scene, shared, found, people];
        const waiting = arr(own.modules?.archive_requests?.requests).filter(item => item.status === 'pending');
        const free = boot?.capabilities?.free_intent === true ? field('Что ты хочешь сделать?', '', true) : null;
        const go = moves.length ? card('door', 'Куда пойти', costLine(moves), put(el('div', 'ncase-map'), ...moves.map(placeTile))) : null;
        return [scene, shared, found, people,
            ...actionGroups(acts),
            talks.length ? card('talk', 'Поговорить', costLine(talks), put(el('div', 'ncase-acts'), ...talks.map(talkTile))) : null,
            acts.length || talks.length ? null : card('lens', 'Действия', '', p('Здесь пока нет доступных действий. Можно перейти в другое место или дождаться следующего окна.')),
            waiting.length ? card('papers', 'Архив', '', p(`Архивных запросов в пути: ${waiting.length}. Ответ придёт в следующем окне — в «Досье».`)) : null,
            go,
            ...(free ? [card('story', 'Своими словами', '', free.node, kit.stack(button('Предложить действие', async () => {
                    const result = await mutate(api('intent'), {request_id: id(), text: free.input.value, selection_id: null});
                    notice = result?.kind === 'clarification' ? 'Уточни действие: выбери одну из доступных кнопок. Пока ничего не потрачено.' : '';
                    if (result?.kind === 'proposal') proposal = {...result.proposal, label: 'Предложенное действие'};
                    render();
                })))] : [])];
    }
    // A removed player: one free action per window (MANOR_MODULES_V2 §9). Everything offered comes from the menu.
    function removedActions() {
        const own = view.self, rows = choiceList().filter(row => ghostKinds.has(row.quote.kind));
        const can = [mystic() ? 'показать знак' : null, 'выложить воспоминание на доску', 'передать его одному игроку лично', 'ответить «да» или «нет» на вопрос'].filter(Boolean);
        const intro = panel(removedTitle(), removalReason() ? kit.alert({tone: 'warn', icon: 'alert', title: removalReason()}) : null,
            p(`Ты больше не ходишь, не голосуешь и не обвиняешь. Раз в окно можно сделать одно: ${can.join(', ')}.`),
            p(ghostChatLine()),
            rows.length ? null : p('Сейчас действовать нечем: действие этого окна уже сделано или в памяти пока нет того, что можно передать.'));
        const asked = questions().filter(q => q.ghost_character === own.character_id && q.status === 'open').map(q => {
            const answers = rows.filter(row => row.quote.kind === 'testimony_answer' && row.quote.params.question_event_id === q.question_event_id);
            return panel(`Вопрос от ${heroAs(q.asker_character, 'gen')}`, p(`«${q.text}»`), p(`Ответ увидят все. Ответить можно до окна ${q.answer_by}.`),
                answers.length ? kit.row(...answers.map(row => button(row.quote.params.answer === 'yes' ? 'Да' : 'Нет', () => selectAction(row, `Ответить «${row.quote.params.answer === 'yes' ? 'да' : 'нет'}»`)))) : null);
        });
        const memories = new Map();
        for (const row of rows.filter(item => ['ghost_share', 'ghost_whisper'].includes(item.quote.kind))) {
            const key = row.quote.params.observation_id;
            if (!memories.has(key)) memories.set(key, {share: null, whisper: []});
            if (row.quote.kind === 'ghost_share') memories.get(key).share = row; else memories.get(key).whisper.push(row);
        }
        const all = [...arr(own.observations), ...arr(view.public.observations)];
        const cards = [...memories].map(([key, item]) => {
            const observation = all.find(entry => entry.observation_id === key) || {title: 'Воспоминание'};
            const title = observation.title || 'воспоминание';
            const offered = item.whisper.map(row => row.quote.params.recipient);
            const to = offered.length ? choose('Кому передать лично', offered.map(char => ({id: char, label: heroLabel(char)})), offered.includes(whisperTo.get(key)) ? whisperTo.get(key) : offered[0]) : null;
            to?.input.addEventListener('change', () => whisperTo.set(key, to.input.value));
            const buttons = [...(item.share ? [button('На доску', () => selectAction(item.share, `На доску: ${title}`))] : []),
                ...(to ? [button('Передать лично', () => {
                    const row = item.whisper.find(entry => entry.quote.params.recipient === to.input.value);
                    return row ? selectAction(row, `Передать «${title}» ${heroAs(row.quote.params.recipient, 'dat')}`) : null;
                })] : [])];
            return evidenceCard(observation, 'Твоё воспоминание. На доске его увидят все, лично — только тот, кому передашь.', buttons, to?.node);
        });
        const signs = rows.filter(row => row.quote.kind === 'ghost_sign');
        const sent = arr(own.modules?.ghost_whisper?.sent).map(row => p(`Окно ${row.window_idx}: «${observationTitle(row.observation_id) || 'воспоминание'}» — ${heroAs(row.recipient_character, 'dat')}`));
        return [intro, ...asked, cards.length ? card('papers', 'Твои воспоминания', plural(cards.length, 'запись', 'записи', 'записей'), ...cards) : null,
            signs.length ? panel('Явление', p('Знак увидят все за столом. Каждый знак — один раз за дело.'), kit.row(...signs.map(row => button(row.label, () => selectAction(row, `Явление: ${row.label}`))))) : null,
            sent.length ? panel(said('Ты уже передал лично', 'Ты уже передала лично'), ...sent) : null];
    }
    // Actions grouped by verb into cards of tiles: «Осмотреть · 1 действие» once, then the objects only.
    // The confirmation still names the full action.
    const GROUP_SIGN = {archive_request: 'papers', story_reply: 'envelope', act: 'eye'};
    function actionGroups(rows) {
        const groups = new Map(), VERB = /^([^:]{2,40}):\s*(.+)$/;
        // Labels without «Глагол: предмет» share one card; it is «Другие действия» only beside verb groups.
        const rest = rows.some(row => row.quote.kind === 'act' && VERB.test(row.label)) ? 'Другие действия' : 'Что сделать здесь';
        for (const row of rows) {
            const kind = row.quote.kind, split = VERB.exec(row.label);
            const [title, short] = kind === 'archive_request' ? ['Запросить в архиве', row.label] : kind === 'story_reply' ? ['Письмо', row.label]
                : split ? [split[1], split[2]] : [rest, row.label];
            if (!groups.has(title)) groups.set(title, {kind, items: []});
            groups.get(title).items.push({row, full: row.label, short});
        }
        return [...groups].map(([title, {kind, items}]) => {
            const sign = /осмотр/i.test(title) ? 'lens' : GROUP_SIGN[kind] || 'eye';
            const rowsOf = items.map(item => item.row), shared = costLine(rowsOf);
            return card(sign, title, shared, put(el('div', 'ncase-acts'), ...items.map(item => actTile(item.row, item.short, {sign, full: item.full,
                sub: !shared && item.row.quote.cost ? plural(Number(item.row.quote.cost), 'действие', 'действия', 'действий') : ''}))));
        });
    }
    // Shown on every tab. Who else has finished stays private: the kernel keeps it out of the public view.
    function windowBar() {
        const own = view.self, pub = view.public, clock = pub.clock || {};
        if (pub.final || view.final_summary || own.status !== 'active' || !['investigation', 'final_hearing'].includes(clock.phase)) return null;
        // The server lets a finished player act again (that action un-finishes the window), so the place says so plainly.
        if (own.finished_window) return panel(said('Ты завершил окно', 'Ты завершила окно'),
            p('Ждём остальных. Новое окно откроется, когда все завершат своё или выйдет время.'),
            tab !== 'place' ? null : actingAgain() ? p('Действия снова открыты: первое же из них вернёт тебя в окно.')
                : put(el('div'), p('Действия и переходы закрыты до следующего окна.'),
                    kit.stack(button('Ещё действовать', () => { reopened = windowKey(); render(); }))));
        const finish = choiceList().find(row => row.quote.kind === 'finish_window');
        return finish ? card('hourglass', 'Окно', '', p(`${said('Сделал', 'Сделала')} всё, что ${said('хотел', 'хотела')}? Заверши окно: когда завершат все, следующее откроется раньше.`), kit.stack(actionButton(finish))) : null;
    }
    // One record in the world's evidence frame (mockup screen 10): proof — found by the game, claim — words, may be false.
    // The item's picture when the pack has it, otherwise a sign on the plate.
    function evidenceCard(item, source, actions = [], extra = null) {
        const claim = item.kind === 'claim', art = assets.get(item.art?.asset_id);
        const record = kit.evidence({kind: claim ? 'claim' : 'proof', title: item.title || (claim ? 'Утверждение' : 'Доказательство'),
            image: art?.url || null, icon: claim ? 'story' : 'lens', meta: source || '', text: bodyText(item.body) || text(item.text),
            children: [extra, actions.length ? kit.row(...actions) : null]});
        record.className += ` ncase-evi${claim ? ' claim-card' : ''}`;
        return record;
    }
    // Screen 10 «Улики»: the board of the case on the left (what the table has published, signed «герой · игрок · окно»),
    // on the right the own finds with «Опубликовать», the accusation and a new version.
    function board() {
        const all = [...arr(view.public.observations), ...arr(view.self.observations)], observations = new Map(all.map(item => [item.observation_id, item]));
        const signed = account => {
            const char = charOfAccount(account), seat = arr(view.public.players).find(row => row.account_id === account);
            return [char ? heroTitle(char) : null, account === view.self.account_id ? 'ты' : seat ? seatName(seat) : null].filter(Boolean).join(' · ');
        };
        const windowOf = row => view.public.board_windows?.[row.id];
        // One card per published observation: a second publisher is a name on it, not a second copy.
        const groups = new Map();
        for (const row of arr(view.public.board)) {
            const key = row.observation_id ? `obs:${row.observation_id}` : `row:${row.id}`;
            if (!groups.has(key)) groups.set(key, {row, owners: []});
            const owner = signed(row.owner_account_id);
            if (owner && !groups.get(key).owners.includes(owner)) groups.get(key).owners.push(owner);
        }
        const publicItems = [...groups.values()].map(({row, owners}) => {
            const when = windowOf(row) ? `окно ${windowOf(row)}` : '';
            if (row.kind === 'claim') return evidenceCard({kind: 'claim', title: text(row.text) || 'Версия игрока'}, ['Версия: ' + (owners.join(', ') || 'игрок'), when].filter(Boolean).join(' · '));
            const observation = row.observation || observations.get(row.observation_id);
            const by = [owners.join(', ') || 'Опубликовано на доске', when].filter(Boolean).join(' · ');
            return observation ? evidenceCard(observation, by) : evidenceCard({kind: row.kind, title: 'Улика', text: row.text}, by);
        });
        const onBoard = new Set(arr(view.public.board).map(row => row.observation_id).filter(Boolean));
        const lost = new Set(arr(view.self.personal?.lost_observations));
        // A short button in the card names the find for screen readers and in the confirmation.
        const publish = (row, short, full) => {
            const node = kit.button(`${short}${row.quote.cost ? ` · ${row.quote.cost} ОД` : ''}`, () => Promise.resolve(selectAction(row, full)).catch(fail),
                {kind: 'secondary', compact: true, disabled: outbox.busy});
            node.setAttribute('aria-label', full);
            return node;
        };
        const personal = arr(view.self.observations).map(item => {
            const title = item.title || 'улика';
            const actions = choiceList().filter(row => ['pin', 'ghost_share'].includes(row.quote.kind) && row.quote.params.observation_id === item.observation_id)
                .map(row => row.quote.kind === 'pin'
                    ? publish(row, onBoard.has(item.observation_id) ? 'Подтвердить от себя' : 'Опубликовать', `${onBoard.has(item.observation_id) ? 'Подтвердить от себя' : 'Опубликовать'}: ${title}`)
                    : publish(row, row.label, `${row.label}: ${item.title || 'воспоминание'}`));
            const source = item.source || {};
            const where = source.kind === 'ghost' ? `Передано лично от ${heroAs(source.actor_character, 'gen')} — ${mystic() ? 'призрака дела' : 'выбывшего из дела'}`
                : [source.location ? placeName(source.location) : null, source.window_idx ? `окно ${source.window_idx}` : null].filter(Boolean).join(' · ') || 'Твоя находка';
            const state = lost.has(item.observation_id) ? 'Оригинала больше нет: от него остался пепел. Записанное тобой — всё, что от него осталось.'
                : onBoard.has(item.observation_id) ? 'Уже на доске.' : '';
            return evidenceCard(item, [where, state].filter(Boolean).join(' · '), actions);
        });
        const theories = arr(view.public.modules?.version_archive?.theories).map(item => card('story', item.title, item.state === 'archived' ? 'в архиве' : 'активная', p(bodyText(item.body)), item.state === 'archived' ? p('Версия в архиве; её источники сохранены.') : null,
            kit.row(...choiceList().filter(row => row.quote.kind === 'version_mark' && row.quote.params.version_id === item.id).map(row => actionButton(row, item.state === 'archived' ? `Вернуть версию: ${item.title}` : `В архив: ${item.title}`)))));
        const claimForm = formList().find(row => row.command_kind === 'claim');
        const draft = field('Твоя версия для доски', '', true);
        draft.input.className = 'nc-field ncase-draft'; draft.input.rows = 3;
        draft.input.placeholder = 'Например: ключ панели выдавали по журналу — сверить с распиской';
        const left = kit.row(button('Опубликовать версию', () => command('claim', {text: draft.input.value})));
        left.classList?.add('ncase-left');
        const column = (...children) => put(el('div', 'nc-col'), ...children.flat().filter(Boolean));
        return [...hearings(),
            column(card('lens', 'Доска дела', publicItems.length ? plural(publicItems.length, 'запись', 'записи', 'записей') : '',
                el('p', 'nc-muted', 'Для обвинения нужны опубликованные доказательства. Слова игроков, версии и показания остаются утверждениями.'),
                ...(publicItems.length ? publicItems : [p('Доска пока пуста. Опубликованная находка появится здесь для всех за столом.')]))),
            column(card('papers', 'Твои находки', 'видишь только ты',
                ...(personal.length ? personal : [p('Пока нет. Находки появляются после осмотров и разговоров; до публикации их не видит никто.')])),
                ...hearings(['accuse']),
                claimForm ? card('story', 'Добавить версию', '', draft.input, left) : null,
                ...testimony(), ...signsSeen(), ...theories)];
    }
    // Questions to removed players: public, answered «да» or «нет»; the answer is a claim, never evidence.
    function testimony() {
        const form = formList().find(row => row.command_kind === 'testimony_ask');
        if (!questions().length && !form) return [];
        const rows = questions().slice().reverse().map(q => put(el('article', 'ncase-event'),
            el('strong', null, `Окно ${q.window_idx} · вопрос от ${heroAs(q.asker_character, 'gen')} — ${heroAs(q.ghost_character, 'dat')}`), p(`«${q.text}»`),
            p(q.status === 'answered' ? `Ответ: ${q.answer === 'yes' ? 'да' : 'нет'}.` : q.status === 'open' ? `Ждёт ответа до окна ${q.answer_by}.` : 'Ответа не было.')));
        let ask = [];
        if (form) {
            const ghosts = arr(form.subject_ids);
            const who = choose('Кого спросить', ghosts.map(char => ({id: char, label: heroLabel(char)})), ghosts.includes(askGhost) ? askGhost : ghosts[0]);
            const question = field('Вопрос, на который можно ответить «да» или «нет»', askText, true);
            question.input.maxLength = 200;
            who.input.addEventListener('change', () => { askGhost = who.input.value; });
            question.input.addEventListener('input', () => { askText = question.input.value; });
            ask = [who.node, question.node, kit.row(button(`Спросить · ${Number(form.cost) || 0} ОД`, async () => {
                const result = await command('testimony_ask', {ghost: who.input.value, text: question.input.value.trim()});
                if (result?.receipt?.accepted === true) { askText = ''; render(); }
            }))];
        }
        return [panel(mystic() ? 'Вопросы призракам' : 'Вопросы отстранённым', p('Выбывший отвечает только «да» или «нет». Его ответ — слова, а не доказательство: улик он не добавляет.'), ...rows, ...ask)];
    }
    function signsSeen() {
        const signs = arr(view.public.modules?.ghost_visions?.signs);
        return signs.length ? [panel('Явления', ...signs.slice().reverse().map(sign => p(`Окно ${sign.window_idx} · ${placeName(sign.location)}: ${bodyText(sign.body)}`)))] : [];
    }
    // Hearings (mockup screens 12–13): who accuses whom by portrait, the attached evidence in its frame,
    // the suspect as a portrait tile, sources as rows to tick. Claims are shown but do not count, so they cannot be ticked.
    const seatOf = char => arr(view.public.players).find(row => row.character_id === char);
    const charOfAccount = account => arr(view.public.players).find(row => row.account_id === account)?.character_id || null;
    function plateFor(char) {
        const seat = seatOf(char);
        if (!seat) return el('span', 'ncase-tag game', 'ведёт игра');
        return char === view.self?.character_id ? el('span', 'ncase-tag me', 'ты') : el('span', 'ncase-tag', seatName(seat));
    }
    const heroWho = char => put(el('span', 'ncase-who'), el('span', 'nm', heroTitle(char)), plateFor(char));
    const tick = () => put(el('span', 'tick'), icon('check'));
    const boardObservation = entry => entry.observation || [...arr(view.public.observations), ...arr(view.self.observations)].find(item => item.observation_id === entry.observation_id);
    const pressToggle = (node, on) => node.setAttribute('aria-pressed', on ? 'true' : 'false');
    function accusedBlock(hearing) {
        const side = (char, role) => put(el('figure'), portraitFrame(char, face(char, 'ncase-face lg')), put(el('figcaption'), heroWho(char), el('span', 'nc-muted', role)));
        const accuser = charOfAccount(hearing.accuser);
        const attached = arr(view.public.board).filter(entry => arr(hearing.initial_citations).includes(entry.id)).map(entry => {
            const obs = boardObservation(entry);
            return evidenceCard(obs ? {...obs, kind: entry.kind} : {kind: entry.kind, title: entry.kind === 'claim' ? 'Версия игрока' : 'Улика', text: entry.text},
                entry.kind === 'claim' ? 'утверждение' : 'доказательство');
        });
        return [put(el('div', 'ncase-accuse'), accuser ? side(accuser, 'обвиняет') : null, put(el('span', 'ncase-scales'), icon('scales')), side(hearing.suspect, 'под подозрением')),
            attached.length ? el('h3', 'nc-h3', `Приложенные улики · ${attached.length}`) : null, ...attached];
    }
    // A running hearing and the final vote go first; an accusation is one per case and opens from its own card.
    function hearings(kinds = ['vote', 'final_vote']) {
        return formList().filter(row => kinds.includes(row.command_kind)).map(form => {
            const kind = form.command_kind, ballot = view.self.final_ballot, hearing = view.public.hearing;
            if (!hearingPick.has(kind)) hearingPick.set(kind, kind === 'final_vote' && ballot ? (ballot.suspect || '') : '');
            const tiles = [];
            const suspects = kind === 'vote' ? null : put(el('div', 'ncase-suspects'), ...arr(form.subject_ids).map(char => {
                const tile = put(el('button', 'ncase-suspect'), put(el('span', 'pic'), face(char, 'ncase-suspect-face'), tick()), el('span', 'nm', heroTitle(char)), plateFor(char));
                tile.type = 'button'; tile.setAttribute('aria-label', `Выбрать: ${heroTitle(char)}`);
                pressToggle(tile, hearingPick.get(kind) === char);
                tile.addEventListener('click', () => { hearingPick.set(kind, char); for (const other of tiles) pressToggle(other.node, other.char === char); });
                tiles.push({char, node: tile});
                return tile;
            }));
            const picked = new Set();
            const rows = arr(view.public.board).filter(item => arr(form.board_ids).includes(item.id)).map(entry => {
                const obs = boardObservation(entry), claim = entry.kind === 'claim', art = assets.get(obs?.art?.asset_id);
                const owner = entry.owner_account_id === view.self.account_id ? 'ты' : arr(view.public.players).find(row => row.account_id === entry.owner_account_id)?.name;
                const pic = art ? Object.assign(el('img'), {src: art.url, alt: ''}) : put(el('span', 'sign'), icon(claim ? 'story' : 'lens'));
                const box = el('span', 'box');
                const row = put(el('button', `ncase-cite${claim ? ' claim' : ''}`), pic,
                    put(el('span'), el('span', 'nm', obs?.title || entry.text || 'Публичная улика'), el('span', 'sub', claim ? 'утверждение · не считается' : `доказательство${owner ? ` · ${owner}` : ''}`)), box);
                row.type = 'button'; pressToggle(row, false);
                if (claim) row.disabled = true;
                else row.addEventListener('click', () => {
                    if (picked.has(entry.id)) picked.delete(entry.id); else if (picked.size < 5) picked.add(entry.id); else return;
                    pressToggle(row, picked.has(entry.id)); box.replaceChildren(...(picked.has(entry.id) ? [tick()] : []));
                });
                return row;
            });
            const send = choice => {
                const params = {citations: [...picked]};
                if (kind === 'vote') Object.assign(params, {hearing_id: form.hearing_id, choice});
                else if (choice === 'abstain') params.suspect = null;
                else {
                    if (!hearingPick.get(kind)) { notice = 'Выбери участника.'; render(); return null; }
                    params.suspect = hearingPick.get(kind);
                }
                return command(kind, params);
            };
            const sources = card('lens', 'Приложи улики', 'до пяти', el('p', 'nc-muted', 'Сервер проверит, хватает ли доказательств. Утверждения ключами не считаются.'),
                rows.length ? put(el('div', 'ncase-cites'), ...rows) : p('На доске пока нет записей, которые можно приложить.'));
            // Finding 3 of 2026-11-21: the accused sees the charge and cannot support it against themselves.
            const accused = hearing?.suspect && hearing.suspect === view.self.character_id;
            if (kind === 'vote') return [card('scales', 'Идёт слушание', hearing?.resolve_window ? `до окна ${hearing.resolve_window}` : '',
                    accused ? kit.alert({tone: 'warn', icon: 'alert', title: 'Обвиняют тебя. Возрази и приложи улики в свою защиту: поддержать обвинение против себя нельзя.'})
                        : el('p', 'nc-muted', 'Поддержи обвинение или возрази. Голос тайный; итог объявят, когда слушание закроется.'), ...(hearing ? accusedBlock(hearing) : [])),
                sources, accused ? kit.row(button('Возражаю', () => send('oppose'), 'primary'))
                    : kit.row(button('Возражаю', () => send('oppose')), button('Поддержать', () => send('support'), 'primary'))];
            if (kind === 'final_vote') return [card('scales', 'Итоговое слушание', '',
                    el('p', 'nc-muted', 'Кто вывел и скрывал хозяина? Если он всё сделал сам, без помощников, назови его самого. Голос можно изменить, пока слушание не закрылось; итог объявят после закрытия.'),
                    ballot ? kit.alert({tone: 'ok', icon: 'check', title: `Твой голос записан: ${ballot.suspect ? heroTitle(ballot.suspect) : 'без обвинения'}`}) : null),
                card('people', 'Твой выбор', '', suspects), sources,
                kit.row(button('Воздержаться', () => send('abstain')), button(ballot ? 'Изменить голос' : 'Отдать голос', () => send(), 'primary'))];
            const lead = el('p', 'nc-muted', 'Хватает доказательств против кого-то? Предъяви обвинение: стол решит на слушании, поддержать его или нет. Если стол поддержит обвинение невиновного, тот выбывает из дела.');
            if (!accuseOpen) return [card('scales', 'Обвинение', 'одно за дело', lead, kit.stack(button('Предъявить обвинение', () => { accuseOpen = true; render(); })))];
            return [card('scales', 'Обвинение', 'одно за дело', lead), card('people', 'Кого обвинить', '', suspects), sources,
                kit.row(button('Отмена', () => { accuseOpen = false; hearingPick.delete('accuse'); render(); }), button('Предъявить обвинение', () => send(), 'primary'))];
        }).flat();
    }
    // Screen 9 «Гостиная у камина»: the week, then one feed of the table — what the case showed everyone (a new window,
    // a scene, a publication, a hearing) and what the players said, in time order; the reply box is the dock.
    function track() {
        const now = Number(view.public.clock?.window_idx) || 1, node = el('div', 'ncase-track');
        node.setAttribute('aria-label', `Окно ${now} из 14`);
        for (let day = 1; day <= 7; day++) {
            const cell = el('span', `day${Math.ceil(now / 2) === day ? ' now' : ''}`);
            for (const idx of [day * 2 - 1, day * 2]) cell.append(el('i', idx < now ? 'done' : idx === now ? 'cur' : ''));
            node.append(put(cell, el('b', null, day)));
        }
        return node;
    }
    function sayLine(row) {
        const own = row.sender_account_id === view.self.account_id;
        const seat = arr(view.public.players).find(item => item.account_id === row.sender_account_id);
        const char = seat?.character_id || (own ? view.self.character_id : null);
        const where = row.channel === 'whisper' ? 'приватно' : row.channel === 'ghost' ? removedWord().toLowerCase() : '';
        const who = put(el('span', 'ncase-who'), el('span', 'nm', char ? heroTitle(char) : 'Участник'),
            own ? el('span', 'ncase-tag me', 'ты') : seat ? el('span', 'ncase-tag', seatName(seat)) : null, where ? el('span', 'ncase-tag game', where) : null);
        return put(el('div', `nc-msg${own ? ' mine' : ''}`), own ? null : portraitFrame(char, face(char, 'ncase-face xs')), put(el('div', 'bub'), who, p(row.text)));
    }
    const sysLine = (sign, value) => put(el('span', 'nc-sys'), icon(sign), value);
    function feedEvent(item) {
        const payload = item.payload || {}, pub = view.public;
        const describe = payload.job_id ? kit.row(button('Прочитать описание', async () => { const value = await mutate(api(`renderings/${encodeURIComponent(payload.job_id)}`), {}); notice = text(value?.text); render(); })) : null;
        if (item.kind === 'window') {
            const words = payload.phase === 'final_hearing' ? 'Началось итоговое слушание' : payload.phase === 'frozen' ? 'Стол остановился: все пропустили окна'
                : `Открылось окно ${payload.window_idx || item.window_idx} · ${TIME_WORDS[timeOf(payload.opened_at)].toLowerCase()}`;
            return sysLine(timeOf(payload.opened_at) === 'night' || timeOf(payload.opened_at) === 'evening' ? 'moon' : 'sun', words);
        }
        if (item.kind === 'scene') {
            const art = sceneArt(sceneOf(item.event_id)?.art, 'Событие окна');
            return put(el('article', 'ncase-report'), art, put(el('div'), el('span', 'nc-eyebrow', `Событие · окно ${item.window_idx}`), p(eventText(item)), describe));
        }
        if (item.kind === 'board') {
            const entry = arr(pub.board).find(row => row.id === payload.board_id);
            if (entry) {
                const claim = entry.kind === 'claim', obs = claim ? null : boardObservation(entry), art = assets.get(obs?.art?.asset_id);
                const pic = art ? Object.assign(el('img'), {src: art.url, alt: '', loading: 'lazy'}) : put(el('span', 'ncase-pub-sign'), icon(claim ? 'story' : 'lens'));
                const char = charOfAccount(entry.owner_account_id);
                return put(el('article', 'ncase-pub'), pic, put(el('div'), char ? heroWho(char) : el('span', 'ncase-who', 'Участник'),
                    el('span', 'nc-muted', claim ? 'выкладывает версию' : entry.kind === 'proof' ? 'публикует улику' : 'выкладывает показание'),
                    el('strong', null, claim ? text(entry.text) : obs?.title || 'Улика')));
            }
        }
        if (item.kind === 'hearing' && payload.stage === 'opened' && pub.hearing?.id === payload.hearing_id) {
            const accuser = charOfAccount(pub.hearing.accuser), suspect = payload.suspect;
            return put(el('article', 'ncase-hearing-note'), put(el('span', 'faces'), accuser ? portraitFrame(accuser, face(accuser, 'ncase-face sm')) : null, icon('scales'), portraitFrame(suspect, face(suspect, 'ncase-face sm'))),
                put(el('div'), el('strong', null, accuser ? `${heroTitle(accuser)} обвиняет ${heroAs(suspect, 'acc')}` : `Обвиняют ${heroAs(suspect, 'acc')}`),
                    el('span', 'nc-muted', `Идёт слушание · решение в окне ${payload.resolve_window || item.window_idx + 1}`)),
                button('К слушанию', () => showTab('board')));
        }
        const line = sysLine(EVENT_SIGN[item.kind] || 'calendar', eventText(item));
        return describe ? put(el('div', 'ncase-feed-note'), line, describe) : line;
    }
    function feed() {
        const clock = view.public.clock || {}, now = Number(clock.window_idx) || 1;
        const week = card('calendar', 'Неделя дела', `день ${Math.ceil(now / 2)} из 7`, track());
        week.classList.add('ncase-week');
        // The shared events and the lines in one order: by time, then the window for an older server without times.
        const rows = [...pages.public.items.map((item, i) => ({item, i, at: item.at, window: item.window_idx, node: feedEvent})),
            ...pages.messages.items.map((item, i) => ({item, i: 1e6 + i, at: item.at, window: item.window_idx, node: sayLine}))];
        rows.sort((a, b) => (a.at && b.at ? a.at.localeCompare(b.at) : (a.window || 0) - (b.window || 0)) || a.i - b.i);
        const older = pages.public.next_cursor || pages.messages.next_cursor;
        const whisper = formList().some(row => row.command_kind === 'say' && row.channel === 'whisper');
        const intro = view.self.status === 'ghost' ? ghostChatLine()
            : `${whisper ? 'Приватная беседа — только 2–3 игрокам рядом, за 1 действие. ' : ''}${removedWord()} разговаривают отдельно.`;
        const list = put(el('div', 'nc-chat ncase-feed'), older ? kit.row(button('Раньше', async () => { await loadHistory('public', true); await loadHistory('messages', true); render(); })) : null,
            rows.length ? rows.map(row => row.node(row.item)) : p('Пока тихо. Первая реплика может быть твоей.'));
        // Who else is at the table and when they last had the case open (owner decision 2026-11-27).
        const seated = arr(view.public.players).filter(row => row.status !== 'departed' && row.account_id !== view.self.account_id)
            .map(row => ({character_id: row.character_id, name: row.name, controller: 'player'}));
        return [week, seated.length ? card('people', 'За столом', String(seated.length), put(el('ul', 'ncase-people'), ...seated.map(person))) : null,
            kit.panel({cls: 'nc-span'}, intro ? el('p', 'nc-muted', intro) : null, list)];
    }
    // The reply box of «Гостиная» (mockup 9): the hint says who reads it and how many lines are left; a private talk names
    // its 2–3 listeners right above the box.
    function composeDock() {
        const forms = formList().filter(row => row.command_kind === 'say');
        if (!forms.length) return null;
        if (!forms.some(row => row.channel === channel)) channel = forms[0].channel;
        const form = forms.find(row => row.channel === channel), left = view.self.communication?.remaining;
        const reads = channel === 'whisper' ? 'Приватно — только тем, кого ты выбрал' : channel === 'ghost' ? `Видят только ${removedWord().toLowerCase()}` : 'Гостиную видят все за столом';
        const hint = el('p', 'nc-dock-hint', `${reads}${left == null ? '' : ` · осталось ${plural(Number(left), 'реплика', 'реплики', 'реплик')} в этом окне`}`);
        const channels = forms.length > 1 ? put(el('div', 'qw-btn-group ncase-channels'), ...forms.map(row => {
            const chip = el('button', 'qw-btn', {square: 'Всем', whisper: 'Приватно', ghost: removedWord()}[row.channel] || row.label); chip.type = 'button';
            chip.setAttribute('aria-pressed', row.channel === channel ? 'true' : 'false');
            chip.addEventListener('click', () => { channel = row.channel; recipients = []; render(); });
            return chip;
        })) : null;
        const targetRows = el('div', 'ncase-recipients');
        if (channel === 'whisper') for (const target of arr(form?.recipient_ids || form?.subject_ids)) {
            const check = el('input'); check.type = 'checkbox'; check.checked = recipients.includes(target);
            check.addEventListener('change', () => { recipients = recipients.filter(value => value !== target); if (check.checked && recipients.length < 2) recipients.push(target); else check.checked = false; });
            targetRows.append(put(el('label', 'ncase-checkbox'), check, el('span', null, heroLabel(target))));
        }
        const draftLabel = channel === 'whisper' ? 'Реплика для приватной беседы' : 'Реплика за столом', draft = field(draftLabel, ownDraft, true);
        draft.input.placeholder = draftLabel; draft.input.rows = 1;
        draft.input.addEventListener('input', () => { ownDraft = draft.input.value; });
        const send = button('Сказать', async () => {
            const result = await command('say', {channel, recipients: channel === 'whisper' ? recipients : [], text: ownDraft});
            if (result?.receipt?.accepted === true) { ownDraft = ''; await loadHistory('messages'); render(); }
        }, 'primary');
        return put(el('div', 'nc-dock ncase-compose'), put(el('div'), hint, channels, targetRows.children.length ? targetRows : null, put(el('div', 'nc-compose'), draft.input, send)));
    }
    function eventText(item) {
        const payload = item.payload || {}, own = view.self;
        const player = character => heroTitle(character), as = heroAs;
        const boardRow = arr(view.public.board).find(row => row.id === payload.board_id);
        const who = account => account === own.account_id ? 'Ты' : arr(view.public.players).find(row => row.account_id === account)?.name || 'Участник';
        if (bodyText(payload.body)) return bodyText(payload.body);
        switch (item.kind) {
        case 'window': return payload.phase === 'final_hearing' ? 'Началось итоговое слушание: каждый называет, кто скрывал хозяина.' : payload.phase === 'frozen' ? 'Стол остановился: все пропустили окна.' : `Открылось окно ${payload.window_idx || item.window_idx}.`;
        case 'board': return boardRow ? `${who(boardRow.owner_account_id)}: на доске ${boardRow.observation_id ? `улика «${observationTitle(boardRow.observation_id) || 'без названия'}»` : 'новая версия'}.` : 'На доске появилась запись.';
        case 'observation_granted': return `Находка: «${observationTitle(payload.observation_id) || 'запись'}».`;
        case 'archive_requested': return `Архивный запрос отправлен. Ответ — в окне ${payload.due_window}.`;
        case 'hearing': return payload.stage === 'opened' ? `Открыто слушание: обвиняют ${as(payload.suspect, 'acc')}.` : `Слушание закрыто${payload.resolution === 'cancelled' ? ' без решения' : ''}: обвиняли ${as(payload.suspect, 'acc')}.`;
        case 'status': return {ghost: `${player(payload.character_id)} теперь наблюдает за делом.`, fog: `${player(payload.character_id)} пропадает из виду.`, removed: `${player(payload.character_id)} покидает дело.`, active: `${player(payload.character_id)} снова за столом.`}[payload.status] || 'Состав стола изменился.';
        case 'npc_revealed': return 'Хозяин найден.';
        case 'world_changed': return 'Обстановка в усадьбе изменилась.';
        case 'version_marked': return `${who(payload.by_account)}: версия ${payload.state === 'archived' ? 'отправлена в архив' : 'возвращена'}.`;
        case 'ghost_whispered': return `Ты ${said('передал', 'передала')} ${as(payload.recipient_character, 'dat')} лично «${observationTitle(payload.observation_id) || 'воспоминание'}».`;
        case 'ghost_whisper_received': return `${player(payload.from_character)} передаёт тебе лично: «${observationTitle(payload.observation_id) || 'воспоминание'}».`;
        case 'testimony_asked': return `Вопрос от ${as(payload.asker_character, 'gen')} — ${as(payload.ghost_character, 'dat')}: «${text(payload.text)}»`;
        case 'testimony_answered': { const q = questions().find(row => row.question_event_id === payload.question_event_id); return `${q ? player(q.ghost_character) : 'Выбывший'} отвечает: ${payload.answer === 'yes' ? 'да' : 'нет'}.`; }
        case 'final': return 'Дело закрыто.';
        case 'afk_notice': return `Ты ${said('пропустил', 'пропустила')} окон подряд: ${payload.missed_windows}.`;
        case 'window_digest': return 'Итог окна готов.';
        case 'story_return_closed': return payload.decision === 'accepted' ? 'Письмо передано.' : 'Письмо не передано.';
        default: return 'Событие дела.';
        }
    }
    const EVENT_SIGN = {window: 'moon', board: 'papers', observation_granted: 'lens', archive_requested: 'papers', hearing: 'scales', status: 'people',
        npc_revealed: 'eye', world_changed: 'house', version_marked: 'story', ghost_whispered: 'envelope', ghost_whisper_received: 'envelope',
        testimony_asked: 'talk', testimony_answered: 'talk', action_result: 'lens', final: 'laurel', afk_notice: 'hourglass', window_digest: 'calendar', story_return_closed: 'envelope', scene: 'eye'};
    // «Досье» keeps the personal part of the old chronicle: own finds, moves and notes by window.
    function ownEvents() {
        const found = new Map([...arr(view.public.observations), ...arr(view.self.observations)].map(item => [item.observation_id, item]));
        const entry = item => {
            const payload = item.payload || {};
            const art = assets.get(found.get(payload.observation_id || arr(payload.observation_ids)[0])?.art?.asset_id);
            const pic = art ? Object.assign(el('img', 'obj'), {src: art.url, alt: '', loading: 'lazy'}) : put(el('span', 'sign'), icon(EVENT_SIGN[item.kind] || 'calendar'));
            return put(el('li'), pic, put(el('div'), el('span', 'when', `Окно ${item.window_idx}`), p(eventText(item)),
                ...(payload.job_id ? [kit.row(button('Прочитать описание', async () => { const value = await mutate(api(`renderings/${encodeURIComponent(payload.job_id)}`), {}); notice = text(value?.text); render(); }))] : [])));
        };
        const items = pages.self.items.slice().reverse();
        return card('calendar', 'Твои события', items.length ? plural(items.length, 'запись', 'записи', 'записей') : '',
            items.length ? put(el('ul', 'ncase-chron'), ...items.map(entry)) : p('Пока ничего: твои находки, переходы и записки появятся здесь.'),
            pages.self.next_cursor ? kit.row(button('Раньше', async () => { await loadHistory('self', true); render(); })) : null);
    }
    // 14 «Дело закрыто»: the played variant's picture and text, the own result, and who was who (hero first, player as a plate).
    const PARTS = {culprit: 'виновный', accomplice: 'сообщник Тени'};
    const SIDE_SHORT = {shadow: 'Тень', investigation: 'Следствие', independent: 'Сам за себя'};
    function finaleCards(final) {
        const own = view.self, goals = new Map(arr(final?.goal_results).map(row => [row.account_id, row.met === true]));
        const facts = arr(final?.reward_facts).find(row => row.account_id === own.account_id);
        const met = goals.get(own.account_id);
        const sideTag = faction => {
            const node = el('span', `ncase-fac ${SIDE_SHORT[faction] ? faction : 'investigation'}`);
            const emblem = kit.art?.(`emblem_${faction}`);
            if (emblem) node.append(Object.assign(el('img'), {src: emblem, alt: ''}));
            node.append(SIDE_SHORT[faction] || SIDE_SHORT.investigation);
            return node;
        };
        const mine = card('laurel', 'Твой итог', '', put(el('div', 'ncase-me'), portraitFrame(own.character_id, face(own.character_id, 'ncase-face lg')),
            put(el('div'), el('strong', null, `${heroTitle(own.character_id)} · ${met ? 'цель выполнена' : 'цель не выполнена'}`),
                el('span', 'nc-muted', facts ? (facts.faction_won ? 'Твоя сторона победила.' : 'Твоя сторона в этот раз проиграла.') : 'Подробности своей цели смотри в «Досье».'))));
        const cast = arr(final?.cast);
        const who = cast.length ? card('people', 'Кто был кем', 'роли открыты', put(el('ul', 'ncase-cast'), ...cast.map(row => put(el('li'), face(row.character_id),
            put(el('div'), put(el('span', 'ncase-who'), el('span', 'nm', heroTitle(row.character_id)), plateFor(row.character_id)),
                el('span', 'sub', PARTS[row.part] || {shadow: 'на стороне Тени', independent: 'свой интерес'}[row.faction] || 'следствие')),
            sideTag(row.faction), row.account_id ? (goals.get(row.account_id) ? kit.tag?.('цель', {tone: 'ok', icon: 'check'}) || el('span', 'nc-tag ok', 'цель') : el('span', 'nc-tag', 'не вышло')) : null)))) : null;
        return [mine, who];
    }
    function rules() {
        return [panel('Как идёт дело', p('Четырнадцать окон на семь дней. Окна открывает сервер; заходи в удобное время. На перемещения и действия тратятся очки действий.'),
            p('Личные находки известны только тебе. Публикуй доказательства на доску, сравнивай документы и проверяй показания. Архивные запросы приходят в следующее окно.'),
            p('Обвинение обсуждается на слушании. Найти хозяина — ещё не значит доказать, кто его вывел и скрывал. Личная цель указана в твоём досье и засчитывается сервером.'),
            p(`Кого стол отстранил по ошибке, тот остаётся в игре: раз в окно выкладывает воспоминание на доску, передаёт его одному игроку лично или отвечает «да» или «нет» на вопрос. Вопрос выбывшему стоит 1 ОД; его ответ — слова, а не доказательство.`))];
    }
    function render() {
        if (!live()) return;
        menu();
        if (!view) {
            // «Новое дело» redraws its own step (a notice, «отправляем…»); a failing step leaves the flow.
            if (fresh && !game) { (fresh.screen === 'case' ? renderCase() : renderWorlds()).catch(error => { fresh = null; fail(error); }); return; }
            if (game) frame([panel('Связь с твоим делом', p('Чтение партии пока недоступно. Её состояние хранится на сервере.'), kit.row(button('Обновить', refresh)))]);
            else if (room) renderRoom();
            return;
        }
        if (view.lobby) {
            const extra = proposal?.leaveLobby ? panel(proposal.label, kit.row(button('Остаться', () => { proposal = null; render(); }), button('Покинуть', () => lobbyCommand('leave'), 'danger'))) : confirmation();
            const open = view.lobby.seating === 'open', gathering = `Сбор · ${room?.title || 'компания'}`;
            const picking = open && view.lobby.self_seat && !ownSeat(view.lobby)?.ready ? arr(view.lobby.heroes).find(hero => hero.id === lookPick && hero.multiple) : null;
            if (!picking && lookPick) { lookPick = null; Q.nav.pop?.('night-case-pick'); }
            if (picking) return frame([...pickScreen(picking), extra].filter(Boolean), `${picking.title}: кого играешь`, gathering, pickDock(picking));
            if (open) return frame([...openLobby(), extra].filter(Boolean), view.lobby.case?.title || 'Сбор игроков', gathering, lobbyDock());
            frame([...lobby(), extra].filter(Boolean), view.lobby.case?.title || 'Сбор игроков'); return;
        }
        if (!view.self) return frame([panel('Дело недоступно', p('Твоё участие не найдено. Вернись к списку компаний.'))]);
        const own = view.self, pub = view.public, clock = pub.clock || {};
        if (own.status === 'active' && (clock.window_idx || 1) <= 1 && !pub.final && !view.final_summary && !selectedOriginal && !roleSeen()) return revealRole(clock);
        const stateNotice = clock.phase === 'frozen' ? panel('Стол ждёт возвращения', p('Общий простой остановил окна. Отметь возвращение, чтобы продолжить.'),
            kit.row(...choiceList().filter(row => row.quote.kind === 'seen').map(row => actionButton(row)))) : own.status === 'departed' ? panel('Участие завершено', p('Тебе доступна собственная разрешённая история до выхода и итог дела.')) : own.status === 'ghost' && tab !== 'place' ? panel(removedTitle(), p('Твоё действие окна — во вкладке «Место».')) : null;
        const final = own.postmortem;
        const over = pub.final || view.final_summary;
        const finale = !over ? null : tab === 'place' ? [card('laurel', 'Дело закрыто', '', sealedArt(final?.variant_art, 'Развязка дела'),
                el('p', 'nc-lead', bodyText(final?.ending)), bodyText(final?.variant_final_text) ? p(bodyText(final?.variant_final_text)) : null), ...(final ? finaleCards(final) : []),
                // After the final the room can take a new case (mockup 14): only its owner starts one; the server allows it once the game is over.
                room?.role === 'owner' ? kit.row(button('К компаниям', () => entry()), button('Новое дело', () => newCase(), 'primary'))
                    : card('people', 'Что дальше', '', p('Новое дело начнёт хозяин компании: сбор появится здесь же.'), kit.row(button('К компаниям', () => entry())))]
            : card('laurel', 'Дело закрыто', '', p('Развязка, твой итог и «кто был кем» — на вкладке «Место».'), kit.row(button('К итогу', () => showTab('place'), 'primary')));
        const finalHearing = clock.phase === 'final_hearing' && !pub.final;
        // «Гостиная» shows an ordinary hearing in its own feed note (mockup 9); the final hearing keeps the card everywhere.
        const hearingNotice = (pub.hearing && !(tab === 'feed' && arr(pages.public.items).some(item => item.payload?.hearing_id === pub.hearing.id)) || finalHearing) && tab !== 'board' ? card('scales', finalHearing ? 'Итоговое слушание' : 'Идёт слушание', '',
            p(finalHearing ? `Неделя подошла к концу. Назови, кто вывел и скрывал хозяина, и приложи улики с доски.${own.final_ballot ? ' Твой голос уже записан — его можно изменить.' : ''}` : 'Посмотри обвинение и опубликованные источники, затем сделай свой выбор.'),
            kit.row(button(finalHearing ? (own.final_ballot ? 'Изменить голос' : 'Перейти к голосованию') : 'Открыть слушание', () => showTab('board'), 'primary'))) : null;
        // Once the case is closed the place tab is the finale (mockup 14): no place picture or actions under it.
        if (conversation && !talking()) conversation = null;
        const current = over && tab === 'place' ? [] : tab === 'self' ? role() : tab === 'board' ? board() : tab === 'feed' ? feed() : tab === 'rules' ? rules() : tab === 'narrator' ? narratorTab() : talking() ? talkScreen() : place();
        let selector = null;
        if (['finished', 'stopped'].includes(view.runtime_status) && arr(view.history_seats).length > 1) {
            const choice = choose('Твои завершённые роли', [{id: '', label: 'Все твои роли'}, ...view.history_seats.map(seat => ({id: seat.original_account_id, label: `${seat.display_name} · ${seat.role_title}`}))], selectedOriginal);
            choice.input.addEventListener('change', async () => {
                selectedOriginal = choice.input.value; epoch++; clearHistory(); view = null; render();
                await refresh();
                await loadTab(tab); render();
            });
            selector = panel('Твоя история', choice.node);
        }
        // A closed case is headed by its title (mockup 14), not by the last place.
        const caseTitle = arr(boot?.cases).find(item => item.id === pub.case_id)?.title;
        frame([navigation(), selector, stateNotice, hearingNotice, ...[finale].flat(), ...current, tab === 'rules' || tab === 'feed' || talking() ? null : windowBar()].filter(Boolean),
            over ? caseTitle || 'Дело закрыто' : arr(pub.locations).find(item => item.id === own.location)?.name || 'Усадьба',
            over ? `Дело закрыто · окно ${clock.window_idx || '—'} из 14` : `Окно ${clock.window_idx || '—'} из 14 · ${TIME_WORDS[sceneTime()].toLowerCase()}`,
            confirmDock() || (talking() ? talkDock() : tab === 'feed' && !over ? composeDock() : null), tab === 'feed' ? 'ncase-chatmain' : '');
    }
    function close() {
        if (!alive) return;
        alive = false; epoch++; controller.abort(); clearInterval(poll); timer?.stop();
        view = proposal = room = game = boot = invitation = fresh = null; ownDraft = ''; recipients = [];
        outbox.clear(); cursors.clear(); for (const page of Object.values(pages)) page.items.length = 0;
        assets.clear(); assetWorld = null; worldPack = null;
        Q.nav.pop?.('night-case-room'); Q.nav.pop?.('night-case-section'); Q.nav.pop?.('night-case-pick'); popFlow(); kit.music?.stop?.(); kit.useWorld(null); document.documentElement.classList.remove('nc');
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
        else if (target?.roomId) await enterRoom({id: target.roomId, title: 'Компания'});
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
