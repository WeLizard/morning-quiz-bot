(() => {
    'use strict';
    // «Рейтинг» for every player, guest or Telegram: one account ranking with slices (UI_RULES §8, §9).
    // The server never sends identifiers: a row is {rank, display_name, score, is_me}.
    const SCOPES = [['global', 'Общий'], ['friends', 'Друзья'], ['room', 'Комната'], ['chat', 'Чат'], ['farm', 'Ферма'], ['alchemy', 'Алхимия']];
    const PERIODS = [['all', 'Всё время'], ['month', 'Месяц'], ['week', 'Неделя']];
    const GAMES = [['all', 'Все игры'], ['classic', 'Квиз'], ['photo', 'Фото']];
    const GAME_SCOPES = new Set(['global', 'friends', 'room', 'chat']);
    const prefs = {scope: 'global', period: 'all', game: 'all', roomId: '', chatId: '', trust: false};

    function endpoint(identity, scope, extra) {
        const query = new URLSearchParams({scope: scope.scope, period: scope.period, game: scope.game, limit: '20', offset: String(extra.offset)});
        if (scope.scope === 'room' && scope.roomId) query.set('room_id', scope.roomId);
        if (scope.scope === 'chat' && scope.chatId) query.set('chat_id', scope.chatId);
        if (identity) query.set('identity', identity);
        return `/api/account/rating?${query}`;
    }
    async function api(path, options = {}) {
        const controller = new AbortController(); const timeout = setTimeout(() => controller.abort(), 12000);
        try {
            const method = String(options.method || 'GET').toUpperCase();
            const headers = {...(options.headers || {})};
            if (method !== 'GET') Object.assign(headers, {'Content-Type': 'application/json', 'X-Mini-CSRF': '1', 'X-Guest-CSRF': '1'});
            const response = await fetch(path, {...options, method, headers, credentials: 'same-origin', signal: controller.signal});
            let data; try { data = await response.json(); } catch { throw new Error('Сервис временно недоступен. Повтори позже.'); }
            if (!response.ok) { const error = new Error(typeof data.detail === 'string' ? data.detail : 'Не удалось загрузить рейтинг.'); error.status = response.status; throw error; }
            return data;
        } catch (error) {
            if (error.name === 'AbortError' || error instanceof TypeError) throw new Error('Нет связи с приложением. Проверь подключение и повтори.');
            throw error;
        } finally { clearTimeout(timeout); }
    }

    async function render(ctx) {
        const {content, el, button, note, segmented, format, identity, isCurrent, onError, onProfile} = ctx;
        let offset = 0, sequence = 0, rows = [], options = {rooms: [], chats: [], telegram: false}, me = null;
        const controls = el('div', undefined, 'rating-controls'), picker = el('div'), notice = el('div');
        const podium = el('section', undefined, 'podium'), list = el('ol', undefined, 'list'), mine = el('p', undefined, 'me-bar');
        const visibility = el('section', undefined, 'card rating-visibility');
        mine.hidden = true;
        const more = button('Показать ещё', () => load(true).catch(fail), 'secondary'); more.hidden = true;
        const fail = error => { more.disabled = false; onError(error); };

        // A slice chosen by the host (a chat's own «Рейтинг» tab) is trusted until the first answer brings the real options.
        let trusting = prefs.trust; prefs.trust = false;
        function availableScopes() {
            if (trusting) return SCOPES;
            return SCOPES.filter(([value]) => (value !== 'room' || options.rooms.length) && (value !== 'chat' || options.chats.length));
        }
        function paintControls() {
            const scopes = availableScopes();
            if (!scopes.some(([value]) => value === prefs.scope)) prefs.scope = 'global';
            const parts = [segmented(scopes, prefs.scope, value => { prefs.scope = value; reset(); }, 'Раздел рейтинга'),
                segmented(PERIODS, prefs.period, value => { prefs.period = value; reset(); }, 'Период')];
            if (GAME_SCOPES.has(prefs.scope)) parts.push(segmented(GAMES, prefs.game, value => { prefs.game = value; reset(); }, 'Игра'));
            controls.replaceChildren(...parts);
            picker.replaceChildren();
            const pool = prefs.scope === 'room' ? options.rooms : prefs.scope === 'chat' ? options.chats : null;
            if (pool && pool.length) {
                const key = prefs.scope === 'room' ? 'room_id' : 'chat_id';
                const field = el('label', prefs.scope === 'room' ? 'Комната' : 'Чат', 'field'), select = el('select');
                select.setAttribute('aria-label', field.textContent);
                for (const item of pool) { const option = el('option', item.title); option.value = item[key]; select.append(option); }
                const current = prefs.scope === 'room' ? prefs.roomId : prefs.chatId;
                const chosen = pool.some(item => String(item[key]) === String(current)) ? String(current) : String(pool[0][key]);
                select.value = chosen;
                if (prefs.scope === 'room') prefs.roomId = chosen; else prefs.chatId = chosen;
                select.addEventListener('change', () => { if (prefs.scope === 'room') prefs.roomId = select.value; else prefs.chatId = select.value; reset(); });
                field.append(select); picker.append(field);
            }
        }
        function reset() { offset = 0; rows = []; podium.replaceChildren(); list.replaceChildren(); mine.hidden = true; more.hidden = true; notice.replaceChildren(); paintControls(); load(false).catch(fail); }
        function paintRows() {
            podium.replaceChildren(); list.replaceChildren();
            // Podium order: 2nd, 1st, 3rd. It needs a full top three with distinct places, otherwise the list shows everyone.
            const top = rows.slice(0, 3), usePodium = top.length === 3 && top.every((row, index) => row.rank === index + 1);
            if (usePodium) for (const row of [top[1], top[0], top[2]]) {
                const place = el('div', undefined, `podium-place p${row.rank}${row.me ? ' me' : ''}`);
                place.append(el('span', ['🥇', '🥈', '🥉'][row.rank - 1], 'medal'), el('strong', row.name + (row.me ? ' · ты' : '')), el('small', format(row.score)));
                podium.append(place);
            }
            for (const row of usePodium ? rows.slice(3) : rows) {
                const node = el('li', undefined, row.me ? 'me' : '');
                node.append(el('span', `#${row.rank}`, 'rank'), el('span', `${row.name}${row.me ? ' · ты' : ''}`, 'name'), el('span', format(row.score), 'score'));
                list.append(node);
            }
            if (!rows.length) note(list, 'Пока нет результатов.');
        }
        function paintMine() {
            notice.replaceChildren();
            if (!me) { mine.hidden = true; return; }
            mine.hidden = false;
            mine.textContent = me.rank ? `Ты — №${me.rank} · ${format(me.score)}` : 'У тебя пока нет очков в этом разделе.';
            if (me.needs_nickname) {
                const card = el('section', undefined, 'card');
                note(card, 'Свой результат ты видишь, но в общем списке тебя нет, пока ты не выберешь ник. Ник — это имя, которое видят другие игроки.');
                const actions = el('div', undefined, 'qw-btn-stack'); actions.append(button('Выбрать ник', onProfile, 'primary')); card.append(actions);
                notice.append(card);
            }
        }
        function paintVisibility() {
            visibility.replaceChildren(el('h3', 'Видимость в рейтинге'));
            note(visibility, me?.hidden ? 'Тебя не видно в рейтинге. Своё место ты видишь.' : 'Другие игроки видят твой ник и очки. Только ник приложения: ни Telegram, ни id не показываются.');
            const actions = el('div', undefined, 'qw-btn-stack');
            const toggle = button(me?.hidden ? 'Показывать меня' : 'Не показывать меня в рейтинге', async event => {
                const trigger = event.currentTarget; trigger.disabled = true;
                try { await api(`/api/account/rating-visibility${identity ? `?identity=${identity}` : ''}`, {method: 'POST', body: JSON.stringify({hidden: !me?.hidden})}); reset(); }
                catch (error) { trigger.disabled = false; onError(error); }
            }, 'text');
            actions.append(toggle); visibility.append(actions);
        }
        async function load(append) {
            more.disabled = true;
            const ticket = ++sequence;
            const result = await api(endpoint(identity, prefs, {offset}));
            if (!isCurrent() || ticket !== sequence) return;
            if (result.options) { options = result.options; trusting = false; }
            for (const row of result.items) rows.push({rank: row.rank, name: row.display_name, me: Boolean(row.is_me), score: row.score});
            me = result.me || me;
            offset += result.items.length;
            more.hidden = !result.has_more; more.disabled = false;
            if (!append && result.options) { const before = prefs.scope; paintControls(); if (before !== prefs.scope) return reset(); }
            paintRows(); paintMine(); paintVisibility();
        }
        content.append(controls, picker, notice, podium, list, more, mine, visibility);
        paintControls();
        await load(false);
    }
    // The host asks for a slice before rendering (e.g. the «Рейтинг» tab of one chat).
    function prefer({scope = 'global', chatId = '', roomId = ''} = {}) {
        prefs.scope = scope; prefs.period = 'all'; prefs.game = 'all'; prefs.trust = true;
        if (chatId) prefs.chatId = String(chatId);
        if (roomId) prefs.roomId = String(roomId);
    }
    window.QuizRating = {render, prefer};
})();
