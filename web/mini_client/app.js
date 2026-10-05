(() => {
    'use strict';
    const content = document.getElementById('content'), nav = document.getElementById('navigation');
    const feedback = document.getElementById('feedback');
    const tg = window.Telegram?.WebApp;
    const LAUNCH_PAGES = {home: 'home', chats: 'chats', rating: 'rating', profile: 'profile',
                          achievements: 'achievements', history: 'history'};
    function launchTarget() {
        let raw = tg?.initDataUnsafe?.start_param || '';
        if (!raw && typeof URLSearchParams !== 'undefined' && typeof location !== 'undefined') {
            raw = new URLSearchParams(location.search).get('tgWebAppStartParam') || '';
        }
        // Ссылки вида ?startapp=chat_n100123 и mafia_n100123 несут id группы (со знаком минус).
        const scoped = /^(mafia|chat)_n([1-9][0-9]{0,15})$/.exec(raw);
        if (scoped) return {page: scoped[1], chatId: '-' + scoped[2]};
        return Object.prototype.hasOwnProperty.call(LAUNCH_PAGES, raw) ? {page: LAUNCH_PAGES[raw]} : null;
    }
    const launch = launchTarget();
    const state = {token: null, demo: false, page: launch?.page || 'home', selected: launch?.chatId || '', launchLost: false, me: null, progress: null, chats: [], chatOffset: 0, moreChats: false, botUsername: ''};
    let generation = 0, playCommand = null, runtimeEnabled = false;
    const el = (tag, text, cls) => { const node = document.createElement(tag); if (text !== undefined) node.textContent = text; if (cls) node.className = cls; return node; };
    const button = (label, action, cls = '') => { const node = el('button', label, cls); node.type = 'button'; node.addEventListener('click', action); return node; };
    const format = value => new Intl.NumberFormat('ru-RU', {maximumFractionDigits: 3}).format(Number(value));
    const note = (parent, text, cls = 'muted') => parent.append(el('p', text, cls));
    async function request(path, options = {}) {
        const controller = new AbortController(); const timeout = setTimeout(() => controller.abort(), 12000);
        try {
            const method = String(options.method || 'GET').toUpperCase();
            const headers = {...(options.headers || {}), ...(state.token ? {Authorization: `Bearer ${state.token}`} : {})};
            if (!['GET', 'HEAD'].includes(method) && path.includes('/api/mini/mafia/chats/') && !headers['Idempotency-Key']) {
                headers['Idempotency-Key'] = globalThis.crypto?.randomUUID?.() || `web-${Date.now()}-${Math.random().toString(16).slice(2)}`;
            }
            const response = await fetch(path, {...options, method, signal: controller.signal, headers});
            if (response.status === 204) return null;
            let data; try { data = await response.json(); } catch { throw new Error('Сервис временно недоступен. Повторите позже.'); }
            if (!response.ok) {
                if (response.status === 401) state.token = null;
                const error = new Error(typeof data.detail === 'string' ? data.detail : 'Не удалось выполнить запрос.'); error.status = response.status; throw error;
            }
            return data;
        } catch (error) {
            if (error.name === 'AbortError' || error instanceof TypeError) throw new Error('Нет связи с приложением. Проверьте подключение и повторите.');
            throw error;
        } finally { clearTimeout(timeout); }
    }
    const RENEW_AFTER_MS = 10 * 60 * 1000;   // сессия живёт 15 минут, продлеваем заранее
    let renewTimer = null;
    function scheduleRenewal() {
        clearTimeout(renewTimer);
        if (!state.token) return;
        renewTimer = setTimeout(renewSession, RENEW_AFTER_MS);
        // В браузере это число, в Node — объект таймера: unref не даёт таймеру
        // держать event loop в юнит-тестах.
        renewTimer?.unref?.();
    }
    async function renewSession() {
        if (!state.token) return;
        try {
            await request('/api/mini/session/renew', {method: 'POST'});
            scheduleRenewal();
        } catch (error) {
            clearTimeout(renewTimer);
            if (!state.token) loginScreen('Сессия истекла. Откройте Mini App из Telegram заново.');
            else feedback.textContent = error.message;
        }
    }
    function configureTelegram() {
        window.QuizTelegram.configure(() => { if (state.token) navigate(state.page === 'settings' ? 'profile' : 'home'); },
            () => { if (state.token) navigate('settings'); }, () => { if (state.token) load(); });
    }
    function loginScreen(message = '') {
        generation++; window.QuizGame.stop(); nav.hidden = true; content.replaceChildren();
        const box = el('section', undefined, 'login');
        const hero = el('div', undefined, 'hero'); const image = el('img'); image.src = '/app/host.webp'; image.alt = 'Филиныч, сова-ведущий Morning Quiz'; hero.append(image); box.append(hero);
        box.append(el('span', 'Morning Quiz · Филиныч на связи', 'eyebrow'), el('h1', 'Играй. Узнавай. Возвращайся.'));
        note(box, 'Квиз, фото-загадки и твой прогресс. Играй здесь или в Telegram — как удобнее.');
        if (message) note(box, message, 'error');
        const initData = tg?.initData;
        if (state.demo || initData) {
            const enter = button(state.demo ? 'Войти как dev-игрок' : 'Продолжить через Telegram', async () => {
                enter.disabled = true; feedback.textContent = '';
                try {
                    const session = await request(state.demo ? '/api/dev/session' : '/api/mini/session', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: state.demo ? '{}' : JSON.stringify({init_data: initData})});
                    state.token = session.access_token;
                    // Токен нужен странице «Алхимии» (тот же origin, своя вкладка), чтобы синхронизировать прогресс.
                    try { sessionStorage.setItem('mqb-mini-token', state.token); localStorage.setItem('mqb-mini-token', state.token); } catch {}
                    scheduleRenewal();
                    await load();
                } catch (error) { feedback.textContent = error.message; enter.disabled = false; }
            }, 'primary'); box.append(enter);
            if (initData && !state.demo && !message) queueMicrotask(() => enter.click());
        } else note(box, 'Открой Mini App из Telegram, чтобы войти в свой профиль. В обычном браузере пользовательский вход недоступен.', 'empty');
        content.append(box);
    }
    async function load() {
        const version = ++generation; window.QuizGame.stop();
        content.replaceChildren(el('p', 'Получаем твои данные…', 'muted'));
        try {
            const [me, progress, chats, achievements] = await Promise.all([request('/api/mini/me'), request('/api/mini/progress'), request('/api/mini/chats?limit=50'), request('/api/mini/achievements')]);
            if (version !== generation || !state.token) return;
            Object.assign(state, {me, progress, chats: chats.items, moreChats: chats.has_more, chatOffset: chats.items.length, achievements});
            if (state.selected && !state.chats.some(c => c.chat_id === state.selected)) {
                state.launchLost = true;      // чат из ссылки недоступен: не подменяем молча
                state.selected = '';
            }
            if (!state.selected) state.selected = state.chats[0]?.chat_id || '';
            nav.hidden = false; await navigate(state.page);
        } catch (error) {
            if (version !== generation) return;
            if (!state.token) loginScreen(error.message);
            else { content.replaceChildren(el('p', error.message, 'error'), button('Повторить', load, 'primary')); }
        }
    }
    function metrics(parent) {
        const list = el('section', undefined, 'metrics'); list.setAttribute('aria-label', 'Личный прогресс');
        for (const [value, label] of [[state.me.score, 'баллов'], [state.me.answered_count, 'квиз-ответов'], [state.progress.best_streak, 'рекорд серии']]) {
            const item = el('div', undefined, 'metric'); item.append(el('strong', format(value)), el('span', label)); list.append(item);
        }
        parent.append(list);
    }
    function chatSelect(parent, onChange) {
        const label = el('label', 'Твой чат', 'field'), select = el('select'); select.setAttribute('aria-label', 'Твой чат');
        for (const chat of state.chats) { const option = el('option', chat.title || chat.chat_id); option.value = chat.chat_id; select.append(option); }
        select.value = state.selected; label.append(select); parent.append(label);
        select.addEventListener('change', () => { state.selected = select.value; onChange(); });
    }
    async function command(text) {
        const selected = state.chats.find(chat => chat.chat_id === state.selected);
        const action = {'/quiz': 'quiz', '/photo_quiz': 'photo', '/adminsettings': 'settings'}[text];
        if (action && selected?.type === 'private' && window.QuizTelegram.openBot(state.botUsername, action)) return;
        try { await navigator.clipboard.writeText(text); feedback.textContent = `${text} скопирована. Отправь её боту в нужном чате.`; }
        catch { feedback.replaceChildren(el('span', 'Отправь в чат: '), el('code', text)); }
    }
    function modeCard(parent, title, description, cmd, active) {
        const item = el('article', undefined, 'card'); const heading = el('div', undefined, 'card-heading'); heading.append(el('h2', title));
        if (active) heading.append(el('span', 'Идёт игра', 'badge')); item.append(heading); note(item, description);
        if (active) {
            note(item, `Вопрос ${active.question_number} из ${active.question_count}`);
            const progress = el('progress'); progress.max = Math.max(1, active.question_count); progress.value = active.question_number; progress.setAttribute('aria-label', `Прогресс: ${active.question_number} из ${active.question_count}`); item.append(progress);
        }
        const canOpen = state.botUsername && state.chats.find(chat => chat.chat_id === state.selected)?.type === 'private';
        item.append(button(canOpen ? (active ? 'Вернуться к боту' : 'Настроить и играть') : `Скопировать ${cmd}`, () => active && canOpen ? window.QuizTelegram.openBot(state.botUsername, 'home') : command(cmd), 'primary'));
        if (active) item.append(button('Команда остановки', () => command(cmd === '/quiz' ? '/stopquiz' : '/stop_photo_quiz'), 'quiet'));
        parent.append(item);
    }
    function play(command) { playCommand = command; navigate('play'); }
    async function home(version) {
        const hero = el('section', undefined, 'hero home-hero'), copy = el('div', undefined, 'hero-copy');
        copy.append(el('span', 'Филиныч на связи', 'eyebrow'));
        const title = el('h1', 'Ну что, '); title.append(el('em', 'сыграем?')); copy.append(title);
        note(copy, 'Выбирай формат. Я приготовлю вопросы.');
        const image = el('img'); image.src = '/app/host.webp'; image.alt = 'Сова Филиныч, ведущий квиза'; hero.append(copy, image); content.append(hero);
        const rhythm = el('div', undefined, 'player-rhythm');
        rhythm.append(el('span', `${format(state.me.score)} баллов`), el('span', `Лучшая серия · ${format(state.progress.best_streak)}`)); content.append(rhythm);
        const choices = el('section', undefined, 'play-choices');
        for (const [title, description, command, label] of [
            ['Классический квиз', 'Один вопрос — маленькое открытие. Проверим, что подскажет интуиция?', '/quiz', 'Играть в квиз'],
            ['Фото-загадки', 'Интересная картинка. Но угадаешь ли ты, что это?', '/photo_quiz', 'Угадывать фото']]) {
            const classic = command === '/quiz';
            const card = el('article', undefined, `card play-choice ${classic ? 'featured-game' : 'photo-choice'}`), body = el('div', undefined, 'choice-copy');
            body.append(el('span', classic ? 'РАЗМИНКА ДЛЯ ЛЮБОПЫТНЫХ' : 'СЛОЖИ ОБРАЗЫ В СЛОВО', 'eyebrow'), el('h2', title)); note(body, description);
            const start = button(label, () => play(command), 'primary'); start.disabled = !runtimeEnabled; body.append(start); card.append(body);
            if (classic) { const portrait = el('img'); portrait.src = '/app/host.webp'; portrait.alt = 'Филиныч приглашает за игровой стол'; portrait.className = 'choice-host'; card.append(portrait); }
            else { const portrait = el('img'); portrait.src = '/app/photo.webp'; portrait.alt = 'Филиныч соединяет два фрагмента изображения в новую загадку'; portrait.className = 'choice-photo'; card.append(portrait); }
            choices.append(card);
        }
        content.append(choices);
        const night = el('article', undefined, 'card mafia-teaser');
        const nightImage = el('img'); nightImage.src = '/app/mafia.webp'; nightImage.alt = 'Филиныч в капюшоне ведёт ночное дело';
        const nightCopy = el('div', undefined, 'mafia-teaser-copy');
        nightCopy.append(el('span', 'НОВЫЙ РЕЖИМ · DEV', 'eyebrow'), el('h2', 'Ночной город'));
        note(nightCopy, 'Собери стол для будущей игры в мафию. Роли и состав уже сохраняются отдельно от квиза.');
        nightCopy.append(button('Открыть дело', () => navigate('mafia'), 'quiet'));
        night.append(nightImage, nightCopy); content.append(night);
        const workshop = el('article', undefined, 'card mafia-teaser');
        const workshopCopy = el('div', undefined, 'mafia-teaser-copy');
        workshopCopy.append(el('span', 'НОВЫЙ РЕЖИМ · АЛХИМИЯ', 'eyebrow'), el('h2', 'Атлас маленьких чудес'));
        note(workshopCopy, '421 элемент и 1015 рецептов из четырёх стихий. Прогресс синхронизируется с твоим профилем.');
        workshopCopy.append(button('Открыть атлас', () => {
            const token = state.token ? `#t=${encodeURIComponent(state.token)}` : '';
            window.location.assign(`/app/alchemy${token}`);
        }, 'quiet'));
        workshop.append(workshopCopy); content.append(workshop);
        if (!runtimeEnabled) note(content, 'Игровой режим подключается. Профиль и чатовый бот доступны.', 'muted');
        else {
            const current = await request('/api/mini/runtime'); if (version !== generation) return;
            if (current.games?.some(game => game.status === 'active') || current.photo_round || current.messages.some(message => message.poll && !message.poll.closed && !message.feedback)) content.append(button('Вернуться в текущую игру', () => play(null), 'resume-game'));
            else if (!current.connected) note(content, 'Telegram-ведущий сейчас не подключён. Классический квиз в Mini App доступен независимо.', 'empty');
        }
        const shortcuts = el('div', undefined, 'home-shortcuts');
        for (const [label, cmd] of [['Как играть', '/help']]) {
            const b = button(label, () => play(cmd), 'quiet'); b.disabled = !runtimeEnabled; shortcuts.append(b);
        } content.append(shortcuts);
        const inChat = el('section', undefined, 'chat-alternative'); note(inChat, 'Можно и по-старому. Баллы останутся общими.');
        inChat.append(button('Играть в чате', () => window.QuizTelegram.openBot(state.botUsername, 'home'), 'quiet')); content.append(inChat);
    }
    async function mafia(version) {
        const group = state.chats.find(chat => ['group', 'supergroup'].includes(chat.type));
        const draft = await request('/api/mini/mafia/draft');
        let lobbyData = null;
        if (group) {
            try { lobbyData = await request(`/api/mini/mafia/chats/${group.chat_id}/lobby`); }
            catch (error) { feedback.textContent = error.message; }
        }
        const top = el('section', undefined, 'mafia-case');
        const image = el('img'); image.src = '/app/mafia.webp'; image.alt = 'Филиныч в капюшоне у стола детектива';
        const copy = el('div', undefined, 'mafia-case-copy');
        copy.append(el('span', 'НОЧНОЙ ГОРОД · ДЕЛО 01', 'eyebrow'), el('h1', draft.title));
        note(copy, 'Первый рабочий слой мафии: собери состав стола. Черновик сохранится и не влияет на очки квиза.');
        top.append(image, copy); content.append(top);
        const setup = el('section', undefined, 'card mafia-setup');
        setup.append(el('h2', 'Состав дела'));
        note(setup, 'Сколько человек сядет за стол? Роли пересчитаются автоматически.');
        const people = el('div', undefined, 'mafia-people');
        for (let count = 4; count <= 12; count++) {
            const choice = button(String(count), async event => {
                event.currentTarget.disabled = true;
                try {
                    await request('/api/mini/mafia/draft', {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({players: count, expected_revision: draft.revision})});
                    await navigate('mafia');
                } catch (error) { feedback.textContent = error.message; event.currentTarget.disabled = false; }
            }, `mafia-person ${draft.players === count ? 'selected' : ''}`);
            choice.setAttribute('aria-pressed', String(draft.players === count)); people.append(choice);
        }
        setup.append(people);
        const roles = el('div', undefined, 'mafia-roles');
        for (const role of draft.roles) {
            const item = el('div', undefined, `mafia-role ${role.id}`);
            item.append(el('strong', String(role.count)), el('span', role.title)); roles.append(item);
        }
        setup.append(roles); content.append(setup);
        const table = el('section', undefined, 'card mafia-table');
        table.append(el('h2', 'Стол игроков'));
        if (!group) note(table, 'Для лобби нужен групповой чат, где бот может видеть участников. В личной игре пока доступен только черновик ролей.', 'muted');
        else if (!lobbyData) note(table, 'Не удалось прочитать лобби этого чата.');
        else if (!lobbyData.lobby) {
            note(table, `Создай лобби в «${group.title}». Никого автоматически не добавляем.`);
            table.append(button('Создать лобби', async event => {
                event.currentTarget.disabled = true;
                try { await request(`/api/mini/mafia/chats/${group.chat_id}/lobby/join`, {method: 'POST'}); await navigate('mafia'); }
                catch (error) { feedback.textContent = error.message; event.currentTarget.disabled = false; }
            }, 'primary'));
        } else {
              const lobby = lobbyData.lobby;
              note(table, `${group.title} · ${lobby.players.length} из 12 за столом`);
              if (lobby.ends_at && lobby.status !== 'finished') {
                  const remaining = Math.max(0, Math.ceil(Number(lobby.ends_at) - Date.now() / 1000));
                  note(table, `До автоматического перехода: ${remaining} сек.`, 'mafia-deadline');
              }
            const list = el('div', undefined, 'mafia-player-list');
            for (const player of lobby.players) {
                const row = el('div', undefined, `mafia-player ${player.ready ? 'ready' : ''} ${player.alive === false ? 'eliminated' : ''}`);
                const stateLabel = lobby.status === 'lobby' ? (player.ready ? 'готов' : 'думает') : (player.alive ? 'в игре' : 'выбыл');
                row.append(el('span', player.name + (player.is_me ? ' · ты' : '')), el('strong', stateLabel));
                list.append(row);
            }
            table.append(list);
            if (!lobby.joined) table.append(button('Сесть за стол', async event => {
                event.currentTarget.disabled = true;
                try { await request(`/api/mini/mafia/chats/${group.chat_id}/lobby/join`, {method: 'POST'}); await navigate('mafia'); }
                catch (error) { feedback.textContent = error.message; event.currentTarget.disabled = false; }
            }, 'primary'));
            else if (lobby.status !== 'lobby') {
                const roleCard = el('section', undefined, 'mafia-role-card');
                try {
                    const role = await request(`/api/mini/mafia/chats/${group.chat_id}/role`);
                    const phaseTitle = {night: `НОЧЬ ${role.round}`, day: `ДЕНЬ ${role.round}`, voting: 'ГОРОД ГОЛОСУЕТ', finished: 'ДЕЛО ЗАКРЫТО'}[role.phase] || role.phase;
                    roleCard.append(el('span', phaseTitle, 'eyebrow'), el('strong', role.title));
                    if (!role.alive) note(roleCard, 'Ты выбыл из дела, но можешь наблюдать за общим ходом.', 'muted');
                    else if (role.investigation) note(roleCard, `Проверка ${role.investigation.seat}: ${role.investigation.is_mafia ? 'это мафия' : 'не мафия'}.`, 'mafia-next');
                    if (role.phase === 'night' && role.alive) {
                        if (role.role === 'citizen') note(roleCard, 'Город спит. Дождись итогов ночи.');
                        else if (role.acted) note(roleCard, 'Твой выбор принят. Ведущий продолжит, когда все роли сделают ход.', 'mafia-next');
                        else {
                            note(roleCard, role.role === 'mafia' ? 'Выбери ночную цель.' : role.role === 'doctor' ? 'Кого защитить этой ночью?' : 'Кого проверить?');
                            const targets = el('div', undefined, 'mafia-targets');
                            for (const target of role.targets || []) targets.append(button(target.name, async event => {
                                event.currentTarget.disabled = true;
                                try { await request(`/api/mini/mafia/chats/${group.chat_id}/action`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({target: target.seat, expected_revision: lobby.revision})}); await navigate('mafia'); }
                                catch (error) { feedback.textContent = error.message; event.currentTarget.disabled = false; }
                            }));
                            roleCard.append(targets);
                        }
                    } else if (role.phase === 'day') note(roleCard, 'Обсудите события в чате. Ведущий откроет голосование, когда город будет готов.');
                    else if (role.phase === 'voting' && role.alive) {
                        if (role.voted) note(roleCard, 'Голос принят. Ждём остальных игроков.', 'mafia-next');
                        else {
                            note(roleCard, 'Кого город должен вывести из игры?');
                            const targets = el('div', undefined, 'mafia-targets');
                            for (const target of role.targets || []) targets.append(button(target.name, async event => {
                                event.currentTarget.disabled = true;
                                try { await request(`/api/mini/mafia/chats/${group.chat_id}/vote`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({target: target.seat, expected_revision: lobby.revision})}); await navigate('mafia'); }
                                catch (error) { feedback.textContent = error.message; event.currentTarget.disabled = false; }
                            }));
                            roleCard.append(targets);
                        }
                    } else if (role.phase === 'finished') note(roleCard, role.winner === 'citizens' ? 'Город победил. Мафия раскрыта.' : 'Мафия подчинила Ночной город.', 'mafia-next');
                } catch (error) { roleCard.append(el('p', error.message)); }
                table.append(roleCard);
                if (lobby.history?.length) {
                    const history = el('div', undefined, 'mafia-history'); history.append(el('h3', 'Ход дела'));
                    for (const event of lobby.history.slice(-6)) {
                        const text = event.type === 'started' ? 'Стол собран. Наступила первая ночь.'
                            : event.type === 'night_result' ? (event.eliminated ? `После ночи выбыл ${event.eliminated}.` : event.saved ? 'Доктор спас цель мафии.' : 'Ночь прошла без потерь.')
                            : event.eliminated ? `Город вывел из игры ${event.eliminated}.` : 'Голоса разделились — никто не выбыл.';
                        note(history, text);
                    }
                    table.append(history);
                }
                  if (lobby.can_advance && lobby.is_host) {
                    const label = lobby.status === 'night' ? 'Объявить итоги ночи' : lobby.status === 'day' ? 'Открыть голосование' : 'Подвести итоги голосования';
                    table.append(button(label, async event => {
                        event.currentTarget.disabled = true;
                        try { await request(`/api/mini/mafia/chats/${group.chat_id}/advance`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({expected_revision: lobby.revision})}); await navigate('mafia'); }
                        catch (error) { feedback.textContent = error.message; event.currentTarget.disabled = false; }
                      }, 'primary'));
                  }
                  if (lobby.status === 'finished' && lobby.is_host) table.append(button('Собрать реванш', async event => {
                      event.currentTarget.disabled = true;
                      try { await request(`/api/mini/mafia/chats/${group.chat_id}/restart`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({expected_revision: lobby.revision})}); await navigate('mafia'); }
                      catch (error) { feedback.textContent = error.message; event.currentTarget.disabled = false; }
                  }, 'primary'));
            } else {
                const mine = lobby.players.find(player => player.is_me);
                table.append(button(mine?.ready ? 'Я не готов' : 'Я готов', async event => {
                    event.currentTarget.disabled = true;
                    try { await request(`/api/mini/mafia/chats/${group.chat_id}/lobby/ready`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ready: !mine?.ready, expected_revision: lobby.revision})}); await navigate('mafia'); }
                    catch (error) { feedback.textContent = error.message; event.currentTarget.disabled = false; }
                }, mine?.ready ? 'quiet' : 'primary'));
                if (lobby.can_start) {
                    note(table, 'Стол собран. Роли будут выданы каждому игроку приватно.', 'mafia-next');
                    if (lobby.is_host) table.append(button('Начать ночь', async event => {
                        event.currentTarget.disabled = true;
                        try { await request(`/api/mini/mafia/chats/${group.chat_id}/lobby/start`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({expected_revision: lobby.revision})}); await navigate('mafia'); }
                        catch (error) { feedback.textContent = error.message; event.currentTarget.disabled = false; }
                    }, 'primary'));
                }
                else note(table, `До старта нужно минимум 4 готовых игрока. Сейчас готово: ${lobby.players.filter(player => player.ready).length}.`, 'muted');
            }
        }
        content.append(table);
        const boundary = el('section', undefined, 'mafia-boundary');
        boundary.append(el('h2', 'Полный ход дела'), el('p', 'Лобби, тайные роли, ночные действия, обсуждение, голосование, выбывание и победа сохраняются в общей партии.'));
          boundary.append(el('h2', 'Ещё предстоит'), el('p', 'Живая проверка большого стола в отдельной тестовой Telegram-группе.'));
          content.append(boundary, button('К играм', () => navigate('home'), 'quiet'));
          if (lobbyData?.lobby && !['lobby', 'finished'].includes(lobbyData.lobby.status)) {
              setTimeout(() => { if (generation === version && state.page === 'mafia') navigate('mafia'); }, 5000);
          }
    }
    async function chatHome(version) {
        const hero = el('section', undefined, 'hero home-hero'), copy = el('div', undefined, 'hero-copy');
        copy.append(el('span', 'Филиныч на связи', 'eyebrow'));
        const title = el('h1', 'Ну что, '); title.append(el('em', 'сыграем?')); copy.append(title);
        note(copy, 'Выбирай формат. Я приготовлю вопросы.');
        const image = el('img'); image.src = '/app/host.webp'; image.alt = 'Сова Филиныч с микрофоном и карточкой вопроса'; hero.append(copy, image); content.append(hero); metrics(content);
        if (!state.selected) { note(content, 'Пока нет чатов с твоим участием. Сыграй первый квиз в боте, затем обнови приложение.', 'empty'); return; }
        if (state.launchLost) note(content, 'Чат из ссылки недоступен — возможно, ты больше не участник.', 'error');
        chatSelect(content, () => navigate('chat'));
        const [details, games] = await Promise.all([request(`/api/mini/chats/${state.selected}/details`), request(`/api/mini/chats/${state.selected}/games`)]);
        if (version !== generation) return;
        const cards = el('section', undefined, 'cards');
        modeCard(cards, 'Классический квиз', `${details.classic.questions} вопросов · ${details.classic.seconds} секунд на ответ. Категории, анонс и паузы настраиваются в чате.`, '/quiz', games.items.find(g => g.kind === 'classic'));
        modeCard(cards, 'Фото-загадки', 'Узнай, что на картинке. Пиши ответ в чат, используй подсказки и получай бонус за скорость.', '/photo_quiz', games.items.find(g => g.kind === 'photo'));
        content.append(cards);
        if (details.me) {
            const stats = el('article', undefined, 'card'); stats.append(el('h2', 'Твоя статистика в этом чате'));
            const accuracy = details.me.accuracy === null || details.me.accuracy === undefined ? '—' : `${details.me.accuracy}%`;
            note(stats, `Очков: ${details.me.score} · место ${details.me.rank} из ${details.me.members}`);
            note(stats, `Ответов: ${details.me.answered}, правильных: ${details.me.correct} (${accuracy})`);
            note(stats, `Серия сейчас: ${details.me.streak}, рекорд: ${details.me.best_streak}`);
            note(stats, `Достижения чата: ${details.me.achievements_earned} из ${details.me.achievements_available}`);
            if (details.me.last_answer_at) note(stats, `Последний ответ: ${new Date(details.me.last_answer_at).toLocaleString('ru-RU')}`);
            content.append(stats);
        }
        if (details.telegram_url) {
            const link = el('a', 'Открыть этот чат в Telegram'); link.href = details.telegram_url;
            link.addEventListener('click', event => { if (tg?.openTelegramLink) { event.preventDefault(); tg.openTelegramLink(details.telegram_url); } }); content.append(link);
        }
        const schedule = el('article', undefined, 'card'); schedule.append(el('h2', 'Следующая встреча'));
        const times = (details.daily.times_msk || []).map(t => `${String(t.hour).padStart(2, '0')}:${String(t.minute).padStart(2, '0')}`).join(', ');
        note(schedule, details.daily.enabled ? `Ежедневный квиз: ${times || 'время не задано'} · ${details.daily.timezone || 'Europe/Moscow'}` : 'Ежедневный квиз пока не включён. Расписание настраивает администратор чата.');
        note(schedule, details.wisdom.enabled ? `Мудрость от Филиныча: ${details.wisdom.time || '09:00'} · ${details.wisdom.timezone}` : 'Мудрость дня выключена.'); content.append(schedule);
        const categories = el('article', undefined, 'card'); categories.append(el('h2', 'Темы этого чата'));
        note(categories, details.enabled_categories.length ? `Разрешены: ${details.enabled_categories.join(', ')}` : 'Доступны категории банка с учётом настроек пула.');
        if (details.disabled_categories.length) note(categories, `Исключены: ${details.disabled_categories.join(', ')}`);
        if (details.category_usage.length) note(categories, details.category_usage.map(c => `${c.name}: ${c.uses}`).join(' · '));
        content.append(categories);
    }
    function profile() {
        content.append(el('span', 'Твой путь в Morning Quiz', 'eyebrow'), el('h1', state.me.display_name));
        const settingsLink = button(undefined, () => navigate('settings'), 'settings-link');
        const label = el('span'); label.append(el('strong', 'Настройки'), el('small', 'Игра, расписание и оформление'));
        settingsLink.append(label); content.append(settingsLink);
        metrics(content);
        note(content, `Правильных ответов, включая фото: ${state.progress.correct_including_photo}. Лучшая из текущих серий по чатам: ${state.progress.current_streak}.`);
        content.append(el('h2', 'Достижения'));
        const summary = state.achievements?.summary;
        if (!summary) note(content, 'Достижения загружаются…', 'muted');
        else {
            note(content, `Получено ${summary.earned} из ${summary.available}: ${summary.chat_achievements} за очки в чатах и ${summary.streak_achievements} за серии подряд.`);
            const recent = el('div');
            for (const chat of state.achievements.chats) for (const item of chat.items.filter(row => row.earned).slice(0, 2)) recent.append(el('span', item.title, 'achievement'));
            if (recent.childElementCount) content.append(recent);
            content.append(button('Все достижения', () => navigate('achievements'), 'quiet'));
            content.append(button('История игр и ответов', () => navigate('history'), 'quiet'));
        }
        if (state.progress.last_activity) note(content, `Последняя активность: ${new Date(state.progress.last_activity).toLocaleString('ru-RU')}`);
        content.append(button('Обновить прогресс', load, 'quiet'));
    }
    async function settings() {
        content.append(button('К профилю', () => navigate('profile'), 'quiet'), el('span', 'Профиль / Настройки', 'eyebrow settings-path'), el('h1', 'Настройки'));
        const game = el('section', undefined, 'card'); game.append(el('h2', 'Игра и расписание'));
        const personal = state.chats.find(chat => chat.type === 'private' && chat.chat_id === state.me.user_id);
        if (runtimeEnabled && personal) {
            const [details, categoryData] = await Promise.all([
                request(`/api/mini/chats/${personal.chat_id}/details`), request('/api/mini/categories'),
            ]);
            note(game, 'Личные параметры общие для Mini App и бота. Изменение применяется к следующему раунду.');
            const form = el('form', undefined, 'native-settings');
            const numeric = (title, value, min, max) => {
                const field = el('label', title, 'field'), input = el('input'); input.type = 'number'; input.min = String(min); input.max = String(max); input.value = String(value); field.append(input); form.append(field); return input;
            };
            const questions = numeric('Вопросов в раунде', details.classic.questions, 1, 50);
            const seconds = numeric('Секунд на ответ', details.classic.seconds, 5, 600);
            const interval = numeric('Пауза между вопросами, секунд', details.classic.interval, 0, 600);
            const announceDelay = numeric('Задержка анонса, секунд', details.classic.announce_delay, 0, 300);
            const announceField = el('label', undefined, 'toggle-field'), announce = el('input'); announce.type = 'checkbox'; announce.checked = details.classic.announce;
            announceField.append(announce, el('span', 'Показывать анонс перед игрой')); form.append(announceField);
            const categoryPicker = (title, current) => {
                const section = el('details', undefined, 'category-picker'), summary = el('summary', title);
                const modeField = el('label', 'Как выбирать темы', 'field'), mode = el('select');
                for (const [value, label] of [['all', 'Все темы'], ['random', 'Случайные темы'], ['specific', 'Только выбранные'], ['exclude', 'Все, кроме выбранных']]) {
                    const option = el('option', label); option.value = value; mode.append(option);
                }
                mode.value = current.category_mode || 'all'; modeField.append(mode);
                const random = el('input'); random.type = 'number'; random.min = '1'; random.max = '10';
                random.value = String(current.random_categories || 3);
                const checks = el('div', undefined, 'category-checks'), selected = new Map();
                for (const name of categoryData.items || []) {
                    const label = el('label', undefined, 'category-choice'), input = el('input');
                    input.type = 'checkbox'; input.checked = (current.categories || []).includes(name);
                    selected.set(name, input); label.append(input, el('span', name)); checks.append(label);
                }
                const randomField = el('label', 'Сколько случайных тем', 'field'); randomField.append(random);
                section.append(summary, modeField, randomField, checks); form.append(section);
                return {mode, random, selected};
            };
            const classicCategories = categoryPicker('Темы обычного квиза', details.classic);

            form.append(el('h3', 'Расписание'));
            const dailyEnabledField = el('label', undefined, 'toggle-field'), dailyEnabled = el('input'); dailyEnabled.type = 'checkbox'; dailyEnabled.checked = !!details.daily.enabled;
            dailyEnabledField.append(dailyEnabled, el('span', 'Ежедневный квиз')); form.append(dailyEnabledField);
            const timesField = el('label', 'Время запуска через запятую, ЧЧ:ММ', 'field'), dailyTimes = el('input');
            dailyTimes.value = (details.daily.times_msk || []).map(item => `${String(item.hour).padStart(2, '0')}:${String(item.minute).padStart(2, '0')}`).join(', '); timesField.append(dailyTimes); form.append(timesField);
            const zoneField = el('label', 'Часовой пояс', 'field'), dailyZone = el('input'); dailyZone.value = details.daily.timezone || 'Europe/Moscow'; zoneField.append(dailyZone); form.append(zoneField);
            const dailyQuestions = numeric('Вопросов в ежедневном квизе', details.daily.num_questions || 10, 1, 50);
            const dailyInterval = numeric('Пауза ежедневного квиза, секунд', details.daily.interval_seconds || 60, 10, 3600);
            const dailySeconds = numeric('Время ответа в ежедневном квизе', details.daily.poll_open_seconds || 600, 30, 7200);
            const dailyCategories = categoryPicker('Темы ежедневного квиза', {
                category_mode: details.daily.categories_mode || 'random', categories: details.daily.specific_categories || [],
                random_categories: details.daily.num_random_categories || 3,
            });
            const wisdomEnabledField = el('label', undefined, 'toggle-field'), wisdomEnabled = el('input'); wisdomEnabled.type = 'checkbox'; wisdomEnabled.checked = !!details.wisdom.enabled;
            wisdomEnabledField.append(wisdomEnabled, el('span', 'Мудрость от Филиныча')); form.append(wisdomEnabledField);
            const wisdomField = el('label', 'Время мудрости, ЧЧ:ММ', 'field'), wisdomTime = el('input'); wisdomTime.value = details.wisdom.time || '09:00'; wisdomField.append(wisdomTime); form.append(wisdomField);
            const cleanupField = el('label', undefined, 'toggle-field'), autoDelete = el('input'); autoDelete.type = 'checkbox'; autoDelete.checked = details.auto_delete !== false;
            cleanupField.append(autoDelete, el('span', 'Автоматически убирать игровые сообщения')); form.append(cleanupField);
            const save = button('Сохранить параметры', () => {}, 'primary'); save.type = 'submit'; form.append(save);
            form.onsubmit = async event => {
                event.preventDefault(); save.disabled = true; feedback.textContent = '';
                try {
                    const chosen = picker => [...picker.selected].filter(([, input]) => input.checked).map(([name]) => name);
                    const times = dailyTimes.value.split(',').map(value => value.trim()).filter(Boolean);
                    await request(`/api/mini/chats/${personal.chat_id}/preferences`, {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({
                        classic: {questions: Number(questions.value), seconds: Number(seconds.value), interval: Number(interval.value), announce: announce.checked,
                            announce_delay: Number(announceDelay.value), category_mode: classicCategories.mode.value,
                            categories: chosen(classicCategories), random_categories: Number(classicCategories.random.value)},
                        daily: {enabled: dailyEnabled.checked, times, timezone: dailyZone.value.trim(), questions: Number(dailyQuestions.value),
                            interval: Number(dailyInterval.value), seconds: Number(dailySeconds.value), category_mode: dailyCategories.mode.value,
                            categories: chosen(dailyCategories), random_categories: Number(dailyCategories.random.value)},
                        wisdom: {enabled: wisdomEnabled.checked, time: wisdomTime.value.trim()}, auto_delete: autoDelete.checked,
                        expected_revision: details.settings_revision,
                    })});
                    feedback.textContent = 'Параметры сохранены для приложения и бота.'; await navigate('settings');
                } catch (error) { feedback.textContent = error.message; save.disabled = false; }
            };
            game.append(form);
            note(game, 'Настройки групп меняет администратор соответствующего чата.', 'muted');
        } else {
            note(game, 'Редактирование в этой версии доступно через чатового бота.');
            if (state.chats.length) { chatSelect(game, () => {}); game.append(button('Открыть настройки в боте', () => command('/adminsettings'))); }
        }
        content.append(game);
        const preferences = el('section', undefined, 'card'); preferences.append(el('h2', 'Как тебе удобно'));
        const themeField = el('label', 'Оформление', 'field'), themeSelect = el('select');
        for (const [value, label] of [['system', 'Как в Telegram / системе'], ['dark', 'Тёмное'], ['light', 'Светлое']]) { const option = el('option', label); option.value = value; themeSelect.append(option); }
        themeSelect.value = window.QuizTelegram.prefs.theme; themeSelect.addEventListener('change', () => window.QuizTelegram.setTheme(themeSelect.value)); themeField.append(themeSelect); preferences.append(themeField);
        const haptics = button(window.QuizTelegram.prefs.haptics ? 'Тактильный отклик: вкл' : 'Тактильный отклик: выкл', () => { const enabled = window.QuizTelegram.toggleHaptics(); haptics.textContent = enabled ? 'Тактильный отклик: вкл' : 'Тактильный отклик: выкл'; haptics.setAttribute('aria-pressed', String(enabled)); });
        haptics.setAttribute('aria-pressed', String(window.QuizTelegram.prefs.haptics)); preferences.append(haptics);
        if (window.QuizTelegram.canFullscreen) preferences.append(button('Развернуть на весь экран', () => window.QuizTelegram.fullscreen(), 'quiet'));
        content.append(preferences);
        const actions = el('div', undefined, 'actions'); actions.append(button('Выйти', async () => {
            try { await request('/api/mini/session', {method: 'DELETE'}); clearTimeout(renewTimer); state.token = null; state.me = null; state.page = 'home'; try { sessionStorage.removeItem('mqb-mini-token'); localStorage.removeItem('mqb-mini-token'); } catch {} loginScreen(); }
            catch (error) { feedback.textContent = error.message; }
        }, 'quiet')); content.append(actions);
    }
    function chats() {
        content.append(el('h1', 'Твои чаты')); note(content, 'У каждого чата свой рейтинг, серия и расписание.');
        if (!state.chats.length) note(content, 'Чаты появятся после первого взаимодействия с ботом.', 'empty');
        for (const chat of state.chats) {
            const item = el('article', undefined, 'card'); item.append(el('h2', chat.title));
            note(item, `${format(chat.own_statistics.score)} баллов · серия ${chat.own_statistics.streak} · рекорд ${chat.own_statistics.best_streak}`);
            item.append(button('Открыть игры и расписание', () => { state.selected = chat.chat_id; navigate('chat'); }, 'primary')); content.append(item);
        }
        if (state.moreChats) content.append(button('Ещё чаты', async event => {
            const trigger = event.currentTarget; trigger.disabled = true;
            try { const result = await request(`/api/mini/chats?limit=50&offset=${state.chatOffset}`); state.chats.push(...result.items); state.chatOffset += result.items.length; state.moreChats = result.has_more; navigate('chats'); }
            catch (error) { feedback.textContent = error.message; trigger.disabled = false; }
        }));
    }
    async function rating(version) {
        content.append(el('h1', 'Гонка за знаниями'));
        const field = el('label', 'Рейтинг', 'field'), select = el('select'); select.setAttribute('aria-label', 'Область рейтинга');
        const global = el('option', 'Глобальный рейтинг'); global.value = ''; select.append(global);
        for (const chat of state.chats) { const option = el('option', chat.title); option.value = chat.chat_id; select.append(option); }
        select.value = state.selected; field.append(select); content.append(field);
        const list = el('ol', undefined, 'list'); content.append(list); let offset = 0, requestSequence = 0;
        const failure = error => { if (!state.token) loginScreen(error.message); else feedback.textContent = error.message; more.disabled = false; };
        const more = button('Показать ещё', () => fetchPage().catch(failure)); more.hidden = true; content.append(more);
        async function fetchPage() {
            more.disabled = true; const selection = select.value, sequence = ++requestSequence;
            const result = await request(`${selection ? `/api/mini/chats/${selection}/leaderboard` : '/api/mini/leaderboard'}?limit=20&offset=${offset}`);
            if (version !== generation || selection !== select.value || sequence !== requestSequence) return;
            if (!offset && !result.items.length) note(list, 'Пока нет результатов.');
            for (const user of result.items) {
                const row = el('li', undefined, user.is_me ? 'me' : ''); row.append(el('span', `#${user.rank}`, 'rank'), el('span', `${user.display_name}${user.is_me ? ' · ты' : ''}`, 'name'), el('span', format(user.score), 'score')); list.append(row);
            }
            offset += result.items.length; more.hidden = !result.has_more; more.disabled = false;
        }
        select.addEventListener('change', () => { list.replaceChildren(); offset = 0; fetchPage().catch(failure); });
        await fetchPage();
    }
    function achievementLine(item) {
        const badge = el('span', `${item.earned ? '✓' : '·'} ${item.title}`, `achievement ${item.earned ? 'earned' : ''}`.trim());
        if (item.message) badge.title = item.message;
        return badge;
    }
    async function achievementsPage(version) {
        content.append(el('span', 'Твой прогресс', 'eyebrow'), el('h1', 'Достижения'));
        const alchemy = await request('/api/mini/alchemy').catch(() => null);
        if (version !== generation) return;
        if (alchemy) {
            const card = el('section', undefined, 'card');
            card.append(el('h2', 'Атлас маленьких чудес'));
            note(card, `Открыто элементов: ${alchemy.discovered} · глав ${alchemy.chapters} · достижений ${alchemy.achievements}`);
            note(card, `Очки из Алхимии: ${format(alchemy.points_total)} · место ${alchemy.rank} из ${alchemy.total_players}`);
            card.append(button('Рейтинг атласа', () => navigate('alchemy-top'), 'quiet'));
            content.append(card);
        }
        const data = state.achievements || await request('/api/mini/achievements');
        if (version !== generation) return;
        state.achievements = data;
        note(content, `Получено ${data.summary.earned} из ${data.summary.available}: ${data.summary.chat_achievements} в чатах и ${data.summary.streak_achievements} за серии.`);
        if (!data.chats.length) note(content, 'Играй в чатах — достижения появятся здесь.', 'empty');
        for (const chat of data.chats) {
            content.append(el('h2', chat.title));
            note(content, `Получено ${chat.earned} из ${chat.available}`);
            const list = el('div'); chat.items.forEach(item => list.append(achievementLine(item))); content.append(list);
        }
        content.append(el('h2', 'Серии подряд'));
        note(content, `Личный рекорд: ${data.streak.best} подряд. Получено ${data.streak.earned} из ${data.streak.available}.`);
        const streakList = el('div'); data.streak.items.forEach(item => streakList.append(achievementLine(item))); content.append(streakList);
        content.append(button('Обновить', () => navigate('achievements'), 'quiet'));
    }
    async function historyPage(version) {
        content.append(el('span', 'Твой прогресс', 'eyebrow'), el('h1', 'История'));
        const data = await request('/api/mini/history');
        if (version !== generation) return;
        const modes = {classic: 'Квиз', photo: 'Фото-загадки', mafia: 'Мафия'};
        content.append(el('h2', 'Последние игры'));
        if (!data.games.length) note(content, 'Здесь появятся игры, сыгранные после перехода на PostgreSQL.', 'empty');
        else for (const game of data.games) {
            const card = el('section', undefined, 'card');
            card.append(el('strong', `${modes[game.mode] || game.mode} · ${game.chat_title}`));
            const parts = [game.status === 'active' ? 'идёт сейчас' : 'завершена'];
            if (game.ended_at) parts.push(new Date(game.ended_at).toLocaleString('ru-RU'));
            parts.push(`мои ответы: ${game.my_correct}/${game.my_answers}`);
            card.append(el('small', parts.join(' · ')));
            content.append(card);
        }
        content.append(el('h2', 'Последние ответы'));
        if (!data.answers.length) note(content, 'Отдельные ответы начнут записываться после перехода на PostgreSQL.', 'empty');
        else {
            const list = el('div');
            for (const item of data.answers) list.append(el('span', `${item.is_correct ? '✓' : '✗'} ${item.chat_title} · ${item.points}`, 'achievement'));
            content.append(list);
        }
        content.append(el('h2', 'Активность по чатам'));
        if (!data.chats.length) note(content, 'Ты пока не играл в чатах.', 'empty');
        else for (const chat of data.chats) {
            const when = chat.last_answer_at ? ` · последний ответ ${new Date(chat.last_answer_at).toLocaleDateString('ru-RU')}` : '';
            note(content, `${chat.title}: ответов ${chat.answered}, правильных ${chat.correct}, очков ${chat.score}${when}`);
        }
        content.append(button('Обновить', () => navigate('history'), 'quiet'));
    }
    async function alchemyTop(version) {
        content.append(el('span', 'Атлас маленьких чудес', 'eyebrow'), el('h1', 'Рейтинг атласа'));
        const data = await request('/api/mini/alchemy/leaderboard?limit=20');
        if (version !== generation) return;
        note(content, 'Считаем открытые элементы, а не очки: фарм Алхимии не влияет на рейтинг квиза.');
        const list = el('section', undefined, 'card');
        if (!data.items.length) note(list, 'Пока никто не открыл ни одного элемента.', 'empty');
        else for (const row of data.items) list.append(el('p', `${row.rank}. ${row.display_name}${row.is_me ? ' — это ты' : ''} · ${row.discovered}`, row.is_me ? '' : 'muted'));
        content.append(list);
        content.append(button('Обновить', () => navigate('alchemy-top'), 'quiet'));
    }
    async function navigate(page) {
        if (!state.token) { loginScreen(); return; }
        window.QuizGame.stop();
        window.QuizTelegram.selection();
        state.page = page; const version = ++generation; feedback.textContent = ''; content.replaceChildren();
        const tab = page.startsWith('settings') || page === 'achievements' || page === 'history' || page === 'alchemy-top' ? 'profile' : page === 'play' ? 'home' : page === 'chat' ? 'chats' : page;
        nav.querySelectorAll('button').forEach(node => { if (node.dataset.page === tab) node.setAttribute('aria-current', 'page'); else node.removeAttribute('aria-current'); });
        if (tg?.BackButton) { if (page === 'home') tg.BackButton.hide(); else tg.BackButton.show(); }
        try {
            if (page === 'home') await home(version);
            else if (page === 'play') {
                const command = playCommand; playCommand = null;
                const engine = [null, '/quiz', '/photo_quiz'].includes(command) ? (window.QuizPlay || window.QuizGame) : window.QuizGame;
                await engine.mount({host: content, request, command, chatId: state.selected, settings: false, onReplay: cmd => play(cmd), onProfile: () => { state.page = 'profile'; load(); }, onHome: () => { state.page = 'home'; load(); }, selection: () => window.QuizTelegram.selection(), media: async path => {
                    const response = await fetch(path, {headers: {Authorization: `Bearer ${state.token}`}});
                    if (!response.ok) throw new Error('Фото недоступно'); return response.blob();
                }});
            }
            else if (page === 'chat') await chatHome(version);
            else if (page === 'profile') profile();
            else if (page === 'achievements') await achievementsPage(version);
            else if (page === 'alchemy-top') await alchemyTop(version);
            else if (page === 'history') await historyPage(version);
            else if (page === 'settings') await settings();
            else if (page === 'chats') chats();
            else if (page === 'mafia') await mafia(version);
            else await rating(version);
        } catch (error) {
            if (version !== generation) return;
            if (!state.token) loginScreen(error.message);
            else { note(content, error.message, 'error'); content.append(button('Повторить', () => navigate(page))); }
        }
    }
    nav.querySelectorAll('button').forEach(node => node.addEventListener('click', () => navigate(node.dataset.page)));
    document.querySelector('.brand').addEventListener('click', event => { if (state.token) { event.preventDefault(); navigate('home'); } });
    configureTelegram();
    request('/api/mini/config').catch(() => null).then(config => {
        state.botUsername = config?.bot_username || '';
        runtimeEnabled = config?.runtime_enabled === true;
        return config?.offline ? request('/api/dev/info').catch(() => null) : null;
    }).then(info => {
        state.demo = info?.demo === true;
        if (state.demo) { const banner = document.getElementById('environment'); banner.hidden = false; banner.textContent = info?.synthetic_player ? 'DEV · Тестовый игрок. Без отправки сообщений в Telegram.' : 'DEV · Просмотр твоего профиля из локальной БД.'; }
        loginScreen();
    });
})();
