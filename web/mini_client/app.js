(() => {
    'use strict';
    const content = document.getElementById('content'), nav = document.getElementById('navigation');
    const feedback = document.getElementById('feedback');
    // Telegram launch data arrives with the SDK, which the shell loads asynchronously and only for Telegram launches;
    // the entry below awaits QW.telegramReady before choosing between the Telegram and the browser path.
    let tg = window.Telegram?.WebApp || null;
    const telegramReady = (window.QW?.telegramReady || Promise.resolve(null)).then(webApp => { tg = webApp || tg; }, () => {});
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
    const state = {authenticated: false, guest: null, demo: false, page: launch?.page || 'home', selected: launch?.chatId || '', launchLost: false, me: null, progress: null, chats: [], chatOffset: 0, moreChats: false, botUsername: '', gameModes: []};
    let generation = 0, playCommand = null, runtimeEnabled = false, guestAllowed = true, roomClassicEnabled = false, roomPhotoEnabled = false;
    let roomPhotoDispose = null, roomPhotoPending = null;
    const stopRoomPhoto = () => { const dispose = roomPhotoDispose; roomPhotoDispose = null; dispose?.(); };
    let roomClassicTimer = null;
    const roomClassicCommands = new Map();
    const stopRoomClassic = () => { clearTimeout(roomClassicTimer); roomClassicTimer = null; stopRoomPhoto(); };
    window.addEventListener?.('pagehide', stopRoomClassic);
    const el = (tag, text, cls) => { const node = document.createElement(tag); if (text !== undefined) node.textContent = text; if (cls) node.className = cls; return node; };
    // Core button classes (qw-shell.css): 'primary' / 'secondary' / 'text' / 'danger'; legacy 'quiet' maps to secondary.
    // Self-styled buttons (mafia seats, play options, cards) keep their own classes without .qw-btn.
    const BARE_BUTTON = /mafia-person|settings-link|resume-game|play-option|answer-option/;
    const button = (label, action, cls = '') => {
        const node = el('button', label, BARE_BUTTON.test(cls) ? cls : ('qw-btn ' + cls.replace(/\bquiet\b/, 'secondary quiet')).trim());
        node.type = 'button'; node.addEventListener('click', action); return node;
    };
    const format = value => new Intl.NumberFormat('ru-RU', {maximumFractionDigits: 3}).format(Number(value));
    const note = (parent, text, cls = 'muted') => parent.append(el('p', text, cls));
    // Shared shell (web/shell/qw-shell.js): header ‹ ⚙, ⚙ menu, back stack. Without the core every call is a no-op.
    const QW = window.QW || {nav: {setRoot() {}}, menu: {register() {}, setAccount() {}}, header: {mountBack() {}, mountGear() {}}, configure() {}};
    const hubBar = document.getElementById('hubbar'), hubTitle = document.getElementById('hubTitle'), brandLink = document.querySelector('.brand');
    if (hubBar) { QW.header.mountBack(hubBar); QW.header.mountGear(hubBar); }
    // Parent screen of every hub page: «назад» goes one level up, not always home (UI_RULES §6).
    const PARENT = {home: null, mafia: null, chats: 'home', rating: 'home', profile: 'home', play: 'home', help: 'home',
                    settings: 'profile', achievements: 'profile', history: 'profile', 'alchemy-top': 'achievements', chat: 'chats'};
    const PAGE_TITLES = {chats: 'Чаты', chat: 'Чат', rating: 'Рейтинг', profile: 'Профиль', settings: 'Настройки', achievements: 'Достижения',
                         history: 'История', 'alchemy-top': 'Рейтинг атласа', help: 'Как играть', play: 'Игра'};
    let openSettingsOnLoad = typeof location !== 'undefined' && location.hash === '#settings';
    function consumeSettingsHash() {
        openSettingsOnLoad = false;
        try { if (location.hash === '#settings') history.replaceState(history.state, '', location.pathname + location.search); } catch {}
    }
    function setHubTitle(title) {
        if (hubTitle) { hubTitle.hidden = !title; hubTitle.textContent = title || ''; }
        if (brandLink) brandLink.hidden = Boolean(title);
    }
    // One place for the shell state of a screen: back target, mode (hub or game), header title, account row.
    // Called by every screen entry (Telegram pages, guest pages, login), because guests never pass navigate().
    const TAB_ROOTS = new Set(['chats', 'rating', 'profile']);
    function shell({page = null, back, title = null, game = false, onHome = null} = {}) {
        const parent = page ? PARENT[page] : null;
        // Tab roots (Чаты, Рейтинг, Профиль): the bottom bar is the navigation, so no on-screen ‹ (UI_RULES §4).
        QW.nav.setRoot(back !== undefined ? back : parent ? () => navigate(parent) : null, {onScreen: !TAB_ROOTS.has(page)});
        // Same identity rule as the account API calls: the Telegram session when signed in through it, else the guest cookie; '' = unknown.
        const identity = state.authenticated ? 'telegram' : state.guest ? 'guest' : '';
        QW.configure(game ? {mode: 'game', onHome, screen: 'mafia', identity} : {mode: 'hub', onHome: null, screen: page || 'hub', identity});
        QW.menu.register([]);
        setHubTitle(game ? null : title ?? (page ? PAGE_TITLES[page] || null : null));
        const profile = state.authenticated ? state.me : state.guest;
        QW.menu.setAccount(profile ? {name: profile.display_name || 'Гость',
            subtitle: state.authenticated ? 'Telegram · профиль и настройки' : profile.login ? `${profile.login} · профиль` : 'Гостевой профиль'} : null);
    }
    async function request(path, options = {}) {
        const controller = new AbortController(); const timeout = setTimeout(() => controller.abort(), 12000);
        try {
            const method = String(options.method || 'GET').toUpperCase();
            const headers = {...(options.headers || {})};
            if (!['GET', 'HEAD'].includes(method)) headers['X-Mini-CSRF'] = '1';
            if (!['GET', 'HEAD'].includes(method) && path.includes('/api/mini/mafia/chats/') && !headers['Idempotency-Key']) {
                headers['Idempotency-Key'] = globalThis.crypto?.randomUUID?.() || `web-${Date.now()}-${Math.random().toString(16).slice(2)}`;
            }
            const response = await fetch(path, {...options, method, credentials: 'same-origin', signal: controller.signal, headers});
            if (response.status === 204) return null;
            let data; try { data = await response.json(); } catch { throw new Error('Сервис временно недоступен. Повторите позже.'); }
            if (!response.ok) {
                if (response.status === 401) state.authenticated = false;
                const error = new Error(typeof data.detail === 'string' ? data.detail : 'Не удалось выполнить запрос.'); error.status = response.status; if (typeof data.code === 'string') error.code = data.code; throw error;
            }
            return data;
        } catch (error) {
            if (error.name === 'AbortError' || error instanceof TypeError) throw new Error('Нет связи с приложением. Проверьте подключение и повторите.');
            throw error;
        } finally { clearTimeout(timeout); }
    }
    async function guestRequest(path, method = 'GET', options = {}) {
        const controller = new AbortController(); const timeout = setTimeout(() => controller.abort(), 12000);
        const abort = () => controller.abort();
        if (options.signal?.aborted) abort();
        else options.signal?.addEventListener('abort', abort, {once: true});
        try {
            const response = await fetch(path, {...options, method, credentials: 'same-origin', signal: controller.signal,
                headers: {...(options.headers || {}), ...(method === 'GET' ? {} : {'X-Guest-CSRF': '1'})}});
            if (response.status === 204) return null;
            let data; try { data = await response.json(); } catch { throw new Error('Сервис временно недоступен. Повтори позже.'); }
            if (!response.ok) { const error = new Error(typeof data.detail === 'string' ? data.detail : 'Не удалось выполнить запрос.'); error.status = response.status; if (typeof data.code === 'string') error.code = data.code; throw error; }
            return data;
        } catch (error) {
            if (error.name === 'AbortError' || error instanceof TypeError) throw new Error('Нет связи с приложением. Проверь подключение и повтори.');
            throw error;
        } finally { clearTimeout(timeout); options.signal?.removeEventListener('abort', abort); }
    }
    // An invitation is a navigation hint. Only the server session identifies the player.
    function farmLaunchHint() {
        const uuid = /^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i;
        const shareToken = /^[A-Za-z0-9_-]{43}$/;
        const query = typeof location !== 'undefined' ? new URLSearchParams(location.search) : new URLSearchParams();
        const explicit = query.get('invite') || query.get('tgWebAppStartParam') || query.get('startapp') || '';
        let raw = explicit || tg?.initDataUnsafe?.start_param || '';
        try { raw = raw || sessionStorage.getItem('qw-farm.incoming') || ''; } catch {}
        if (raw.startsWith('farm_')) raw = raw.slice(5);
        if (!uuid.test(raw) && !shareToken.test(raw)) return null;
        const id = uuid.test(raw) ? raw.toLowerCase() : raw;
        try {
            // Telegram keeps start_param when returning to /app. Only a fresh
            // URL query may reopen the invitation after it was consumed.
            if (!explicit && sessionStorage.getItem('qw-farm.launch-consumed') === id) return null;
            sessionStorage.setItem('qw-farm.incoming', id);
        } catch {}
        return id;
    }
    function resumeFarmInvite(identity, pendingInvite = null) {
        if (!(state.gameModes || []).some(mode => mode.id === 'farm' && mode.status === 'development')) return false;
        if (!['guest', 'telegram'].includes(identity)) return false;
        const id = pendingInvite || farmLaunchHint();
        if (!id) return false;
        const target = '/app/farm?' + new URLSearchParams({identity, invite: id});
        const navigationFailed = () => {
            try {
                if (sessionStorage.getItem('qw-farm.launch-consumed') === id) sessionStorage.removeItem('qw-farm.launch-consumed');
            } catch {}
            generation++; nav.hidden = true;
            content.replaceChildren(el('p', 'Не удалось открыть ферму в этом окне. Попробуй снова.', 'error'),
                button('Повторить', () => resumeFarmInvite(identity, id), 'primary'));
            return true;
        };
        const originalUrl = location.href;
        try {
            const current = new URL(location.href);
            if (['invite', 'startapp', 'tgWebAppStartParam'].some(key => current.searchParams.has(key))) {
                for (const key of ['invite', 'startapp', 'tgWebAppStartParam']) current.searchParams.delete(key);
                history.replaceState(history.state, '', current.pathname + current.search + current.hash);
            }
        } catch {
            if (typeof window.location.replace === 'function') {
                try {
                    window.location.replace(target);
                    try { sessionStorage.setItem('qw-farm.launch-consumed', id); } catch {}
                    return true;
                } catch { /* Stay on the platform if this WebView blocks navigation too. */ }
            }
            return navigationFailed();
        }
        try { window.location.assign(target); }
        catch {
            try { history.replaceState(history.state, '', originalUrl); } catch {}
            return navigationFailed();
        }
        try { sessionStorage.setItem('qw-farm.launch-consumed', id); } catch {}
        return true;
    }
    async function continueFarmInvite(identity) {
        if (identity === 'guest') {
            state.guest = await guestRequest('/api/guest/resume', 'POST');
            if (state.guest?.authentication !== 'guest') throw new Error('Гостевая сессия недоступна. Повтори вход.');
            try { sessionStorage.setItem('mqb-auth-choice', 'guest'); } catch {}
            guestHome();
        } else {
            state.authenticated = true;
            try { sessionStorage.setItem('mqb-auth-choice', 'telegram'); } catch {}
            scheduleRenewal();
            await load();
        }
    }
    function farmSessionChoice(savedGuest, savedTelegram) {
        generation++; nav.hidden = true; feedback.textContent = ''; content.replaceChildren(); shell();
        const box = el('section', undefined, 'login');
        box.append(el('h1', 'С какой фермы войти?'));
        note(box, 'В этом браузере доступны два профиля. Выбери один для приглашения соседа. Профили не объединяются.');
        const choices = [];
        const choose = (label, identity) => {
            const control = button(label, async () => {
                choices.forEach(node => { node.disabled = true; }); feedback.textContent = '';
                try {
                    if (identity === 'telegram' && !savedTelegram) await createTelegramSession(false);
                    await continueFarmInvite(identity);
                } catch (error) {
                    feedback.textContent = error.message;
                    choices.forEach(node => { node.disabled = false; });
                }
            }, 'primary');
            choices.push(control); box.append(control);
        };
        choose(`Гостевой профиль · ${savedGuest.display_name || 'Гость'}`, 'guest');
        choose(`Telegram · ${savedTelegram?.display_name || 'Игрок'}`, 'telegram');
        content.append(box);
    }
    async function bootstrapFarmInvite() {
        try { if (localStorage.getItem('mqb-telegram-logged-out') === '1') { loginScreen(); return; } } catch {}
        const [guest, telegram] = await Promise.allSettled([
            guestAllowed ? guestRequest('/api/guest/me') : Promise.resolve(null),
            request('/api/mini/me'),
        ]);
        for (const result of [guest, telegram]) {
            if (result.status === 'rejected' && result.reason.status !== 401) throw result.reason;
        }
        const savedGuest = guest.status === 'fulfilled' && guest.value?.authentication === 'guest' ? guest.value : null;
        let savedTelegram = telegram.status === 'fulfilled' ? telegram.value : null;
        let loggedOut = false;
        try { loggedOut = localStorage.getItem('mqb-telegram-logged-out') === '1'; } catch {}
        if (!savedTelegram && tg?.initData && !loggedOut) {
            try {
                await createTelegramSession(false, true);
                savedTelegram = await request('/api/mini/me');
            } catch (error) { if (error.status !== 404) throw error; }
        }
        if (savedGuest && savedTelegram && savedGuest.account_id !== savedTelegram.account_id) {
            farmSessionChoice(savedGuest, savedTelegram); return;
        }
        if (savedGuest) { await continueFarmInvite('guest'); return; }
        if (savedTelegram) { await continueFarmInvite('telegram'); return; }
        if (tg?.initData && !loggedOut) { telegramFirstStart(); return; }
        loginScreen();
    }
    function bootstrapError(error, retry) {
        generation++; nav.hidden = true; feedback.textContent = ''; content.replaceChildren(); shell();
        const box = el('section', undefined, 'login');
        box.append(el('h1', 'Не удалось проверить профили'));
        note(box, error.message, 'error');
        box.append(button('Повторить', () => retry().catch(failed => bootstrapError(failed, retry)), 'primary'));
        content.append(box);
    }
    async function bootstrapEntry() {
        try { if (localStorage.getItem('mqb-telegram-logged-out') === '1') { loginScreen(); return; } } catch {}
        let choice = ''; try { choice = sessionStorage.getItem('mqb-auth-choice') || ''; } catch {}
        const saved = guestAllowed ? await guestRequest('/api/guest/me').catch(error => {
            if (error.status === 401) return null;
            throw error;
        }) : null;
        if (saved?.authentication === 'guest' && choice !== 'telegram') {
            state.guest = await guestRequest('/api/guest/resume', 'POST');
            guestHome(); return;
        }
        let telegramProfile;
        try { telegramProfile = await request('/api/mini/me'); }
        catch (error) { if (error.status !== 401) throw error; }
        if (!telegramProfile && tg?.initData && !state.demo) {
            let loggedOut = false;
            try { loggedOut = localStorage.getItem('mqb-telegram-logged-out') === '1'; } catch {}
            if (!loggedOut) {
                try { await createTelegramSession(false, true); telegramProfile = await request('/api/mini/me'); }
                catch (error) { if (error.status !== 404) throw error; }
            }
        }
        if (!telegramProfile) {
            if (saved?.authentication === 'guest') {
                state.guest = await guestRequest('/api/guest/resume', 'POST');
                guestHome(); return;
            }
            if (tg?.initData && !state.demo) {
                let loggedOut = false;
                try { loggedOut = localStorage.getItem('mqb-telegram-logged-out') === '1'; } catch {}
                if (!loggedOut) { telegramFirstStart(); return; }
            }
            loginScreen(); return;
        }
        state.authenticated = true;
        scheduleRenewal();
        await load();
    }
    // Форма обращения (он / она / не указывать): одна настройка Account для всех игр и каналов.
    const ADDRESS = window.QWAddress;
    const ADDRESS_TITLES = {m: 'Он', f: 'Она', n: 'Не указывать'};
    // Wording for the signed-in player's own form (Telegram profile or guest account); neutral until chosen.
    const gm = (m, f, n) => ADDRESS.g((state.me || state.guest)?.address_form, m, f, n);
    // The chosen option is marked explicitly (aria-pressed, fill, bold and ✓ from the core CSS), never by shade alone (UI_RULES §9).
    function addressChooser(current, onPick, {allowSame = false} = {}) {
        const group = el('div', undefined, 'qw-btn-group address-choice'), message = el('p', '', 'error'); message.hidden = true;
        group.setAttribute('role', 'group'); group.setAttribute('aria-label', 'Как к тебе обращаться');
        let value = current;
        const options = ADDRESS.FORMS.map(code => {
            const node = el('button', ADDRESS_TITLES[code]); node.type = 'button'; node.dataset.form = code;
            node.addEventListener('click', async () => {
                if (code === value && !allowSame) return;
                options.forEach(option => { option.disabled = true; }); message.hidden = true;
                try { await onPick(code); value = code; }
                catch (error) { message.textContent = error.message; message.hidden = false; }
                finally { options.forEach(option => { option.disabled = false; }); paint(); }
            });
            return node;
        });
        const paint = () => options.forEach(node => {
            const on = node.dataset.form === value;
            node.setAttribute('aria-pressed', String(on)); node.classList.toggle('selected', on);
        });
        paint(); group.append(...options);
        const wrap = el('div'); wrap.append(group, message); return wrap;
    }
    // channel: 'guest' (cookie профиля) | 'telegram' (сессия Mini App); профиль обновляется ответом сервера.
    async function saveAddressForm(channel, code) {
        const path = `/api/account/address-form?identity=${channel}`, headers = {'Content-Type': 'application/json'}, body = JSON.stringify({address_form: code});
        const result = channel === 'guest'
            ? await guestRequest(path, 'POST', {headers, body})
            : await request(path, {method: 'POST', headers: {...headers, 'X-Guest-CSRF': '1'}, body});
        const profile = channel === 'guest' ? state.guest : state.me;
        if (profile) Object.assign(profile, {address_form: result.address_form, address_form_chosen: true});
        return result;
    }
    // The choice counts as made only when the server sent a known form and did not flag it as the default.
    const addressChosen = profile => Boolean(profile) && profile.address_form_chosen !== false && ADDRESS.FORMS.includes(profile.address_form);
    const ADDRESS_EXAMPLES = {m: 'Ты собрал урожай', f: 'Ты собрала урожай', n: 'Урожай собран'};
    // Шаг при первом входе: его можно пропустить («Не указывать» тоже запоминается, повторно не спрашиваем).
    function addressPrompt(channel, profile) {
        if (!profile || addressChosen(profile)) return null;
        const card = el('section', undefined, 'card address-card');
        card.append(el('span', 'Знакомство', 'eyebrow'), el('h2', 'Как к тебе обращаться?'));
        note(card, 'Чтобы игры говорили правильно: «собрал» или «собрала». Telegram пол не сообщает, поэтому мы не угадываем. Можно пропустить и поменять потом в настройках.');
        card.append(addressChooser(null, async code => { await saveAddressForm(channel, code); card.hidden = true; }));
        return card;
    }
    // Chosen once: collapsed to an example plus «Исправить»; not chosen yet: the choice is open at once (UI_RULES §9).
    function addressSection(channel, profile) {
        const card = el('section', undefined, 'card address-card');
        const render = editing => {
            card.replaceChildren(el('h2', 'Как к тебе обращаться'));
            const chosen = addressChosen(profile);
            if (chosen && !editing) {
                note(card, 'Так игры будут к тебе обращаться');
                card.append(el('p', ADDRESS_EXAMPLES[profile.address_form], 'address-example'));
                const row = el('div', undefined, 'address-actions');
                const scissors = el('span', '✂️', 'address-snip'); scissors.setAttribute('aria-hidden', 'true');
                row.append(button('Исправить', () => { render(true); card.querySelector('.address-choice button')?.focus?.(); }, 'secondary'), scissors);
                card.append(row);
                return;
            }
            note(card, 'Игры будут говорить о тебе в нужной форме: «собрал» или «собрала». Выбор общий для приложения, Telegram и фермы.');
            card.append(addressChooser(chosen ? profile.address_form : null, async code => {
                if (chosen && code === profile.address_form) { render(false); return; }
                await saveAddressForm(channel, code); render(false);
            }, {allowSame: true}));
        };
        render(false);
        return card;
    }
    // Логин и пароль без почты: сессия та же, что у гостя (cookie выдаёт сервер).
    function accountForm(kind, onDone) {
        const registering = kind !== 'login';
        const form = el('form', undefined, 'account-form');
        const field = (label, type, name, auto, max) => {
            const wrap = el('label', label, 'field'); const input = el('input');
            Object.assign(input, {type, name, autocomplete: auto, maxLength: max, required: true});
            if (type === 'text') { input.autocapitalize = 'none'; input.spellcheck = false; }
            wrap.append(input); form.append(wrap); return input;
        };
        const login = field('Логин (латиница, цифры, _ . -)', 'text', 'username', 'username', 32);
        const password = field(registering ? 'Пароль (не короче 8 символов)' : 'Пароль', 'password', 'password',
            registering ? 'new-password' : 'current-password', 128);
        if (registering) note(form, 'Сохрани пароль. Если забудешь, а Telegram связан с профилем, войди через Telegram и задай новый пароль в разделе «Вход и устройства».', 'notice warn');
        let pickedForm = null;
        if (registering && !addressChosen(state.guest)) {
            form.append(el('p', 'Как к тебе обращаться (можно пропустить)', 'field-label'));
            form.append(addressChooser(null, async code => { pickedForm = code; }));
        }
        const message = el('p', '', 'error'); message.hidden = true;
        const submit = el('button', kind === 'login' ? 'Войти' : kind === 'save' ? 'Сохранить профиль' : 'Создать аккаунт', 'primary');
        submit.type = 'submit'; form.append(message, submit);
        form.addEventListener('submit', async event => {
            event.preventDefault(); submit.disabled = true; message.hidden = true;
            try {
                state.guest = await guestRequest(registering ? '/api/account/register' : '/api/account/login', 'POST', {
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({login: login.value, password: password.value, ...(registering && pickedForm ? {address_form: pickedForm} : {})})});
                password.value = '';
                try { sessionStorage.setItem('mqb-auth-choice', 'guest'); } catch {}
                try { localStorage.removeItem('mqb-telegram-logged-out'); } catch {}
                onDone();
            } catch (error) { message.textContent = error.message; message.hidden = false; submit.disabled = false; }
        });
        return form;
    }
    const guestNameImports = new Map();
    const guestNamesEdited = new Set();
    function importGuestTelegramName() {
        if (state.guest?.display_name !== 'Гость' || !tg?.initData || guestNamesEdited.has(state.guest.account_id)) return null;
        const key = JSON.stringify([state.guest.account_id, tg.initData]);
        if (!guestNameImports.has(key)) {
            // Cache the in-flight attempt too: returning home cannot start a
            // second request, including after initData has expired.
            guestNameImports.set(key, guestRequest('/api/guest/telegram-name', 'POST', {
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({init_data: tg.initData})}).catch(() => null));
        }
        return guestNameImports.get(key);
    }
    // ---- Сквозной аккаунт: вход через Telegram в браузере, слияние профилей, устройства ----
    const JSON_HEADERS = {'Content-Type': 'application/json'};
    const TG_LOGIN = '/api/account/telegram-login';
    const FORGOT_PASSWORD = () => gm('Забыл пароль? ', 'Забыла пароль? ', 'Не помнишь пароль? ')
        + 'Если Telegram связан с профилем, войди через Telegram и задай новый пароль в разделе «Вход и устройства».';
    // identity: 'guest' (cookie профиля) | 'telegram' (сессия Mini App). guestRequest не сбрасывает вход при 401.
    function accountApi(identity, path, method = 'GET', body = undefined) {
        const url = `${path}?identity=${identity}`;
        const headers = {...(body === undefined ? {} : JSON_HEADERS), ...(identity === 'telegram' ? {'X-Mini-CSRF': '1'} : {})};
        return guestRequest(url, method, {headers, ...(body === undefined ? {} : {body: JSON.stringify(body)})});
    }
    function enterProfile(profile, message) {
        state.guest = profile;
        try { sessionStorage.setItem('mqb-auth-choice', 'guest'); } catch {}
        try { localStorage.removeItem('mqb-telegram-logged-out'); } catch {}
        guestHome(); feedback.textContent = message;
    }
    // Вход (или привязка) через Telegram в браузере: ссылка в бота, опрос статуса, завершение с тем же cookie.
    function telegramLogin(host, startLabel) {
        const version = generation;
        let run = 0, timer = null, polls = 0;
        const live = mine => version === generation && mine === run;
        // Every 3 s for the first minute (20 polls), then every 5 s.
        const pollDelay = () => polls < 20 ? 3000 : 5000;
        const stop = () => { run++; clearTimeout(timer); timer = null; };
        const idle = (message = '', cls = 'muted', label = startLabel) => {
            stop(); host.replaceChildren();
            if (message) note(host, message, cls);
            host.append(button(label, begin, 'quiet'));
        };
        async function begin() {
            stop(); polls = 0; const mine = run; host.replaceChildren(); note(host, 'Готовим ссылку для входа…');
            let started;
            try { started = await guestRequest(TG_LOGIN + '/start', 'POST'); }
            catch (error) { if (live(mine)) idle(error.message, 'error', 'Начать заново'); return; }
            if (!live(mine)) return;
            host.replaceChildren();
            note(host, 'Открой Telegram и нажми «Войти» в сообщении бота.');
            const link = el('a', 'Открыть Telegram', 'link-button');
            link.href = started.link; link.target = '_blank'; link.rel = 'noopener';
            host.append(link, el('p', 'Ждём подтверждения…', 'muted'), button('Отмена', () => idle(), 'quiet'));
            timer = setTimeout(() => poll(mine), pollDelay()); timer?.unref?.();
        }
        async function poll(mine) {
            if (!live(mine)) return;
            polls++;
            let status;
            try { status = await guestRequest(TG_LOGIN + '/status'); }
            catch (error) { if (live(mine)) idle(error.message, 'error', 'Начать заново'); return; }
            if (!live(mine)) return;
            if (status.status === 'pending') { timer = setTimeout(() => poll(mine), pollDelay()); timer?.unref?.(); return; }
            if (status.status === 'approved') { await finish('auto', mine); return; }
            idle(status.status === 'cancelled' ? 'Вход отменили в Telegram. Можно начать заново.'
                : status.status === 'expired' ? 'Время на подтверждение вышло. Начни заново.'
                    : 'Эта ссылка уже использована. Начни заново.', 'notice warn', 'Начать заново');
        }
        async function finish(mode, mine) {
            host.replaceChildren(); note(host, 'Входим…');
            let result;
            try {
                result = await guestRequest(TG_LOGIN + '/complete', 'POST', {headers: JSON_HEADERS, body: JSON.stringify({mode})});
            } catch (error) {
                if (!live(mine)) return;
                if (error.code === 'telegram_other_linked') {
                    host.replaceChildren(); note(host, error.message, 'notice warn');
                    host.append(button('Войти в профиль этого Telegram', () => finish('switch', mine), 'primary'),
                        button('Отмена', () => idle(), 'quiet'));
                } else idle(error.message, 'error', 'Начать заново');
                return;
            }
            if (!live(mine)) return;
            if (result.result === 'link_required') {
                host.replaceChildren();
                note(host, `Связать профиль «${result.display_name || 'Игрок'}» с Telegram «${result.telegram_display_name || 'без имени'}»?`, 'notice warn');
                host.append(button('Связать', () => finish('link', mine), 'primary'), button('Отмена', () => idle(), 'quiet'));
                return;
            }
            stop();
            if (result.result === 'merge_required') {
                mergeScreen({preview: result.preview, auto: result.auto === true,
                    ids: {account_id: result.account_id, telegram_account_id: result.telegram_account_id},
                    confirm: body => guestRequest(TG_LOGIN + '/merge', 'POST', {headers: JSON_HEADERS, body: JSON.stringify(body)}),
                    onCancel: () => state.guest ? guestSettings() : loginScreen()});
                return;
            }
            enterProfile(result.profile, result.result === 'linked' ? 'Telegram связан с профилем.'
                : result.result === 'already_linked' ? 'Этот Telegram уже связан с профилем.'
                    : result.result === 'merged' ? 'Профили объединены.'
                        : gm('Ты вошёл через Telegram.', 'Ты вошла через Telegram.', 'Вход через Telegram выполнен.'));
        }
        idle();
    }
    // Russian noun form for a count: plural(5, 'открытие', 'открытия', 'открытий').
    function plural(count, one, few, many) {
        const n = Math.abs(Number(count)) % 100, last = n % 10;
        return n > 10 && n < 20 ? many : last === 1 ? one : last >= 2 && last <= 4 ? few : many;
    }
    function mergeCard(title, info) {
        const card = el('section', undefined, 'card merge-card');
        card.append(el('h3', title), el('strong', info.display_name || 'Игрок'));
        note(card, info.login ? `Логин: ${info.login}` : 'Без логина');
        const found = Number(info.alchemy?.discovered || 0), points = Number(info.alchemy?.points_total || 0);
        note(card, `Алхимия: ${format(found)} ${plural(found, 'открытие', 'открытия', 'открытий')}, ${format(points)} ${plural(Math.floor(points), 'очко', 'очка', 'очков')}`);
        note(card, info.farm?.exists ? `Ферма: уровень ${info.farm.level ?? '—'}, монет ${format(info.farm.coins || 0)}` : 'Фермы пока нет');
        note(card, `Комнаты: ${(info.rooms_owned || 0) + (info.rooms_member || 0)}, игры: ${info.games || 0}`);
        return card;
    }
    // Экран слияния: confirm(body) -> {result:'merged', profile, lost_login}; при auto главный выбирает сервер.
    function mergeScreen({preview, auto, ids, confirm, onCancel}) {
        generation++; stopRoomClassic(); window.QuizPlay?.stop(); nav.hidden = true; feedback.textContent = ''; content.replaceChildren(); content.dataset.page = 'merge';
        const version = generation, box = el('section', undefined, 'login merge');
        shell({back: () => { if (version === generation) onCancel(); }});
        box.append(el('h1', 'Объединить профили?'));
        note(box, 'Этот профиль и профиль этого Telegram — разные. Их можно собрать в один.');
        const grid = el('div', undefined, 'merge-grid');
        grid.append(mergeCard('Этот профиль', preview.current), mergeCard('Профиль Telegram', preview.telegram)); box.append(grid);
        if ((preview.rules || []).length) {
            const rules = el('ul', undefined, 'merge-rules');
            for (const rule of preview.rules) rules.append(el('li', rule));
            box.append(rules);
        }
        let main = auto ? 'current' : null;
        // Which login stops working depends on the chosen main profile; before a choice show both cases.
        const warning = el('p', '', 'notice warn'); box.append(warning);
        const updateWarning = () => {
            const split = 'lost_login_if_current_main' in preview || 'lost_login_if_telegram_main' in preview;
            const ifCurrent = split ? preview.lost_login_if_current_main : preview.lost_login;
            const ifTelegram = split ? preview.lost_login_if_telegram_main : preview.lost_login;
            let text = '';
            if (auto || !split) text = preview.lost_login ? `Вход по логину «${preview.lost_login}» перестанет работать.` : '';
            else if (main) { const login = main === 'current' ? ifCurrent : ifTelegram; text = login ? `Вход по логину «${login}» перестанет работать.` : ''; }
            else if (ifCurrent && ifTelegram) text = `Один из логинов перестанет работать: если главным станет этот профиль — «${ifCurrent}», если профиль Telegram — «${ifTelegram}».`;
            warning.textContent = text; warning.hidden = !text;
        };
        updateWarning();
        const message = el('p', '', 'error'); message.hidden = true;
        const submit = button(auto ? 'Объединить профили' : 'Объединить', async () => {
            if (!main) return;
            submit.disabled = true; message.hidden = true;
            try {
                const result = await confirm({main, ...ids});
                if (version !== generation) return;
                enterProfile(result.profile, 'Профили объединены.' + (result.lost_login ? ` Вход по логину «${result.lost_login}» больше не работает.` : ''));
            } catch (error) {
                if (version !== generation) return;
                message.textContent = error.message; message.hidden = false; submit.disabled = false;
            }
        }, 'primary');
        if (!auto) {
            note(box, 'Выбери главный профиль: его очки, рейтинг и логин сохранятся.');
            const group = el('div', undefined, 'qw-btn-stack merge-choice'), picks = [];
            group.setAttribute('role', 'radiogroup'); group.setAttribute('aria-label', 'Главный профиль');
            for (const [value, label] of [['current', 'Главный — этот профиль'], ['telegram', 'Главный — профиль Telegram']]) {
                const pick = button(label, () => {
                    main = value; submit.disabled = false; updateWarning();
                    picks.forEach(node => { const on = node === pick; node.setAttribute('aria-checked', String(on)); node.classList.toggle('selected', on); });
                });
                pick.setAttribute('role', 'radio'); pick.setAttribute('aria-checked', 'false'); picks.push(pick); group.append(pick);
            }
            box.append(group); submit.disabled = true;
        }
        box.append(message, submit, button('Отмена', () => { if (version === generation) onCancel(); }, 'quiet'));
        content.append(box);
    }
    function deviceTime(value) {
        const date = new Date(value);
        return Number.isNaN(date.getTime()) ? '' : date.toLocaleString('ru-RU');
    }
    // «Вход и устройства»: логин/пароль, смена пароля, список входов с отзывом.
    function devicesSection(identity, {credentials = true} = {}) {
        const version = generation, card = el('section', undefined, 'card devices-card'), body = el('div');
        card.append(el('span', 'Безопасность', 'eyebrow'), el('h2', 'Вход и устройства'), body);
        const live = () => version === generation;
        const VIA = {guest: 'Гость', password: 'Логин', telegram: 'Telegram'};
        const field = (form, label, type, name, auto, required) => {
            const wrap = el('label', label, 'field'), input = el('input');
            Object.assign(input, {type, name, autocomplete: auto, maxLength: 128, required});
            if (type === 'text') { input.autocapitalize = 'none'; input.spellcheck = false; }
            wrap.append(input); form.append(wrap); return input;
        };
        const act = async (control, path, payload) => {
            control.disabled = true; feedback.textContent = '';
            try { await accountApi(identity, path, 'POST', payload); if (live()) await refresh(); }
            catch (error) { if (live()) { feedback.textContent = error.message; control.disabled = false; } }
        };
        const credentialsForm = () => {
            const form = el('form', undefined, 'account-form');
            form.append(el('h3', 'Логин и пароль для входа в браузере'));
            const login = field(form, 'Логин (латиница, цифры, _ . -)', 'text', 'username', 'username', true);
            const password = field(form, 'Пароль (не короче 8 символов)', 'password', 'password', 'new-password', true);
            const message = el('p', '', 'error'); message.hidden = true;
            const submit = el('button', 'Сохранить логин и пароль', 'primary'); submit.type = 'submit'; form.append(message, submit);
            form.addEventListener('submit', async event => {
                event.preventDefault(); submit.disabled = true; message.hidden = true;
                try {
                    await accountApi(identity, '/api/account/credentials', 'POST', {login: login.value, password: password.value});
                    if (!live()) return;
                    password.value = '';
                    if (identity === 'guest' && state.guest) { state.guest.login = login.value; guestSettings(); feedback.textContent = 'Логин и пароль сохранены.'; return; }
                    await refresh(); feedback.textContent = 'Логин и пароль сохранены.';
                } catch (error) { if (!live()) return; message.textContent = error.message; message.hidden = false; submit.disabled = false; }
            });
            return form;
        };
        const passwordForm = () => {
            const form = el('form', undefined, 'account-form');
            form.append(el('h3', 'Сменить пароль'));
            const current = field(form, 'Текущий пароль', 'password', 'current_password', 'current-password', false);
            const next = field(form, 'Новый пароль (не короче 8 символов)', 'password', 'new_password', 'new-password', true);
            note(form, gm('Если ты вошёл через Telegram в последние 15 минут, текущий пароль можно не вводить.',
                'Если ты вошла через Telegram в последние 15 минут, текущий пароль можно не вводить.',
                'Если вход через Telegram был в последние 15 минут, текущий пароль можно не вводить.'));
            const message = el('p', '', 'error'); message.hidden = true;
            const submit = el('button', 'Сменить пароль', 'primary'); submit.type = 'submit'; form.append(message, submit);
            form.addEventListener('submit', async event => {
                event.preventDefault(); submit.disabled = true; message.hidden = true;
                try {
                    await accountApi(identity, '/api/account/password', 'POST',
                        {new_password: next.value, ...(current.value ? {current_password: current.value} : {})});
                    if (!live()) return;
                    current.value = ''; next.value = '';
                    await refresh(); feedback.textContent = 'Пароль изменён.';
                } catch (error) { if (!live()) return; message.textContent = error.message; message.hidden = false; submit.disabled = false; }
            });
            return form;
        };
        const render = data => {
            body.replaceChildren();
            if (data.has_password && data.login) note(body, `Логин для входа в браузере: «${data.login}».`);
            if (data.telegram_sessions > 0) note(body, `Активных входов через Telegram: ${data.telegram_sessions}.`);
            // An unsaved guest already sees the «Сохранить профиль» card; one login form is enough.
            if (data.has_password) body.append(passwordForm());
            else if (credentials) body.append(credentialsForm());
            if (data.has_password) note(body, FORGOT_PASSWORD(), 'muted');
            body.append(el('h3', 'Устройства', 'devices-title'));
            const list = el('ul', undefined, 'device-list');
            for (const item of data.sessions || []) {
                const row = el('li', undefined, 'device-row'), copy = el('div', undefined, 'device-copy');
                const when = deviceTime(item.created_at);
                copy.append(el('strong', item.user_agent || 'Неизвестное устройство'),
                    el('small', [VIA[item.created_via] || 'Вход', when && `вход ${when}`, item.current && 'это устройство'].filter(Boolean).join(' · ')));
                row.append(copy);
                if (!item.current) row.append(button('Выйти', event => act(event.currentTarget, '/api/account/sessions/revoke', {id: item.id}), 'quiet'));
                list.append(row);
            }
            body.append(list);
            if ((data.sessions || []).some(item => !item.current)) {
                body.append(button('Выйти на других устройствах', event => act(event.currentTarget, '/api/account/sessions/revoke-others'), 'quiet'));
            }
        };
        const refresh = async () => {
            try { const data = await accountApi(identity, '/api/account/sessions'); if (live()) render(data); }
            catch (error) {
                if (!live()) return;
                body.replaceChildren(); note(body, error.message, 'error'); body.append(button('Повторить', refresh, 'quiet'));
            }
        };
        refresh();
        return card;
    }
    async function guestHome() {
        stopRoomClassic();
        window.QW?.prefs?.applyAccount(state.guest); // the Account's «Контрастный режим» wins over this device's cache
        const version = ++generation, accountId = state.guest?.account_id;
        const nameImport = importGuestTelegramName();
        const pendingFarmInvite = (state.gameModes || []).some(mode => mode.id === 'farm' && mode.status === 'development')
            ? farmLaunchHint() : null;
        if (pendingFarmInvite && nameImport) {
            const profile = await nameImport;
            if (version !== generation || state.guest?.account_id !== accountId) return;
            if (profile && !guestNamesEdited.has(accountId) && state.guest.display_name === 'Гость') state.guest = profile;
        }
        if (version !== generation || state.guest?.account_id !== accountId) return;
        if (pendingFarmInvite && resumeFarmInvite('guest', pendingFarmInvite)) return;
        if (openSettingsOnLoad) { consumeSettingsHash(); await guestSettings(); return; }
        window.QuizPlay?.stop(); showGuestTab('home'); feedback.textContent = ''; content.replaceChildren(); content.dataset.page = 'guest'; shell(); consumeSettingsHash();
        // Same hero and game cards as the Telegram home, limited to modes a guest can play.
        const hero = el('section', undefined, 'hero home-hero'), heroCopy = el('div', undefined, 'hero-copy');
        heroCopy.append(el('span', 'Филиныч на связи', 'eyebrow'));
        const heroTitle = el('h1', 'Ну что, '); heroTitle.append(el('em', 'сыграем?')); heroCopy.append(heroTitle);
        note(heroCopy, 'Выбирай игру: квизы, Атлас и ферма доступны и без Telegram, а Ночной город собирается в комнате с друзьями.');
        const heroImage = el('img'); heroImage.src = '/app/host.webp'; heroImage.alt = 'Сова Филиныч, ведущий квиза';
        hero.append(heroCopy, heroImage); content.append(hero);
        const guestLayout = el('div', undefined, 'guest-layout'), guestMain = el('div', undefined, 'guest-main'), guestSide = el('div', undefined, 'guest-side');
        guestLayout.append(guestMain, guestSide); content.append(guestLayout);
        const guestCards = el('section', undefined, 'play-choices game-mode-list');
        let guestRoomsSection = null;
        const farmLive = (state.gameModes || []).some(mode => mode.id === 'farm' && mode.status === 'development');
        HOME_GAME_CARDS.forEach(spec => guestCards.append(homeGameCard(guestCardSpec(spec, {farmLive,
            focusRooms: () => {
                guestRoomsSection?.scrollIntoView?.({behavior: 'smooth', block: 'start'});
                feedback.textContent = 'Ночной город играют компанией: создай комнату ниже и пригласи друзей по коду.';
            }}))));
        const guestAddressPrompt = addressPrompt('guest', state.guest);
        if (guestAddressPrompt) guestMain.append(guestAddressPrompt);
        guestMain.append(guestCards);
        const rooms = el('section', undefined, 'card guest-rooms'); guestRoomsSection = rooms;
        rooms.append(el('span', 'Играть вместе', 'eyebrow'), el('h2', 'Твои комнаты'));
        note(rooms, 'Создавай закрытые комнаты, приглашай друзей и играйте в Ночной город.');
        const title = el('input'); title.type = 'text'; title.maxLength = 80;
        title.placeholder = 'Например, «Вечерняя компания»'; title.setAttribute('aria-label', 'Название комнаты');
        const secureIds = typeof globalThis.crypto?.randomUUID === 'function';
        let requestId = secureIds ? globalThis.crypto.randomUUID() : null;
        let attemptedTitle = null;
        const create = button('Создать комнату', async event => {
            if (!requestId) { feedback.textContent = 'Безопасное создание комнаты не поддерживается этим браузером.'; return; }
            if (attemptedTitle === null) attemptedTitle = title.value;
            event.currentTarget.disabled = true; title.disabled = true;
            try {
                await guestRequest('/api/guest/rooms', 'POST', {
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({request_id: requestId, title: attemptedTitle}),
                });
                guestHome();
            } catch (error) {
                feedback.textContent = error.message; event.currentTarget.disabled = false;
                if (error.status === 400 || error.status === 409) {
                    requestId = secureIds ? globalThis.crypto.randomUUID() : null;
                    attemptedTitle = null; title.disabled = false;
                }
            }
        }, 'primary');
        if (!secureIds) create.disabled = true;
        rooms.append(title, create);
        const joinPanel = el('div', undefined, 'guest-room-join');
        joinPanel.append(el('h3', 'Войти по приглашению'));
        const inviteInput = el('input'); inviteInput.type = 'text'; inviteInput.maxLength = 64;
        inviteInput.autocomplete = 'off'; inviteInput.spellcheck = false;
        inviteInput.placeholder = 'Вставь код от владельца комнаты';
        inviteInput.setAttribute('aria-label', 'Код приглашения в комнату');
        const joinButton = button('Присоединиться', async event => {
            const inviteCode = inviteInput.value.trim();
            if (!inviteCode) { feedback.textContent = 'Вставь код приглашения.'; inviteInput.focus(); return; }
            event.currentTarget.disabled = true;
            try {
                const joined = await guestRequest('/api/guest/rooms/join', 'POST', {
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({invite_code: inviteCode}),
                });
                guestHome();
                feedback.textContent = joined.joined ? gm(`Ты присоединился к комнате «${joined.title}».`, `Ты присоединилась к комнате «${joined.title}».`, `Комната «${joined.title}»: ты в игре.`)
                    : `Ты уже состоишь в комнате «${joined.title}».`;
            } catch (error) { feedback.textContent = error.message; event.currentTarget.disabled = false; }
        }, 'quiet');
        joinPanel.append(inviteInput, joinButton); rooms.append(joinPanel);
        rooms.append(button('Обновить комнаты', () => guestHome(), 'quiet'));
        const roomList = el('div', undefined, 'guest-room-list'); rooms.append(roomList);
        const requestVersion = generation;
        const refreshInvites = async (roomId, list) => {
            list.replaceChildren();
            const data = await guestRequest(`/api/guest/rooms/${encodeURIComponent(roomId)}/invites`);
            if (requestVersion !== generation) return;
            const now = Date.now();
            const items = data.items || [];
            if (!items.length) note(list, 'Активных кодов пока нет.', 'muted');
            for (const invite of items) {
                const row = el('div', undefined, 'guest-invite-row');
                const expired = Date.parse(invite.expires_at) <= now;
                const full = invite.uses >= invite.max_uses;
                row.append(el('span', invite.revoked ? 'Отозван' : expired ? 'Срок истёк'
                    : full ? 'Лимит использований исчерпан'
                        : `Использований: ${invite.uses} из ${invite.max_uses}`));
                if (!invite.revoked && !expired && !full) row.append(button('Отозвать', async event => {
                    event.currentTarget.disabled = true;
                    try {
                        await guestRequest(`/api/guest/rooms/${encodeURIComponent(roomId)}/invites/${encodeURIComponent(invite.id)}`, 'DELETE');
                        await refreshInvites(roomId, list);
                    } catch (error) { feedback.textContent = error.message; event.currentTarget.disabled = false; }
                }, 'quiet'));
                list.append(row);
            }
        };
        guestRequest('/api/guest/rooms').then(data => {
            if (requestVersion !== generation) return;
            if (!data.items?.length) note(roomList, 'Комнат пока нет.', 'muted');
            else for (const room of data.items) {
                const item = el('article', undefined, 'guest-room-item');
                item.append(el('strong', room.title), el('span', room.role === 'owner' ? 'Твоя комната' : 'Ты в комнате'));
                const roomActions = el('div', undefined, 'qw-btn-stack');
                roomActions.append(button('Открыть Ночной город', () => openGuestMafia(room), 'primary'),
                    button('Открыть классический квиз', () => openGuestClassic(room), 'secondary'),
                    button('Открыть фото-загадки', () => openGuestPhoto(room), 'secondary'));
                item.append(roomActions);
                if (room.role !== 'owner') {
                    const leavePanel = el('div', undefined, 'guest-room-leave');
                    const leave = button('Выйти из комнаты', () => {
                        leave.disabled = true;
                        note(leavePanel, 'Для возвращения понадобится действующее приглашение.');
                        const cancel = button('Остаться', () => { leavePanel.replaceChildren(leave); leave.disabled = false; }, 'quiet');
                        const confirm = button('Подтвердить выход', async () => {
                            confirm.disabled = true; cancel.disabled = true;
                            try {
                                await guestRequest(`/api/guest/rooms/${encodeURIComponent(room.id)}/leave`, 'POST', {
                                    headers: {'Content-Type': 'application/json'},
                                    body: JSON.stringify({membership_version: room.membership_version}),
                                });
                                if (requestVersion === generation) guestHome();
                            } catch (error) {
                                if (requestVersion === generation) feedback.textContent = error.message;
                                confirm.disabled = false; cancel.disabled = false;
                            }
                        }, 'quiet');
                        leavePanel.append(confirm, cancel);
                    }, 'quiet');
                    leavePanel.append(leave); item.append(leavePanel);
                }
                if (room.role === 'owner') {
                    const details = el('details', undefined, 'guest-room-invite');
                    details.append(el('summary', 'Пригласить друзей'));
                    const controls = inviteIssuer(room, {
                        mount: codeBox => details.insertBefore(codeBox, inviteList),
                        afterIssue: () => refreshInvites(room.id, inviteList),
                    });
                    details.append(controls);
                    const inviteList = el('div', undefined, 'guest-invite-list'); details.append(inviteList);
                    item.append(details);
                    refreshInvites(room.id, inviteList).catch(error => {
                        if (requestVersion === generation) note(inviteList, error.message, 'error');
                    });
                }
                roomList.append(item);
            }
        }).catch(error => { if (requestVersion === generation) note(roomList, error.message, 'error'); });
        guestSide.append(rooms);
    }
    // «Профиль» of a guest: the player card and a way into «Настройки», the same shape as for a Telegram player.
    async function guestProfile() {
        stopRoomClassic();
        const version = ++generation, accountId = state.guest?.account_id;
        const nameImport = importGuestTelegramName();
        window.QuizPlay?.stop(); showGuestTab('profile'); feedback.textContent = ''; content.replaceChildren(); content.dataset.page = 'guest-profile'; shell({page: 'profile'}); consumeSettingsHash();
        const me = state.guest, saved = Boolean(me?.login), viaTelegram = Boolean(me?.telegram_user_id);
        const card = el('section', undefined, 'card player-card'), who = el('div', undefined, 'player-who'), title = el('h1', me?.display_name || 'Гость');
        who.append(title, el('small', saved ? `Профиль QuizzyWizzy · ${me.login}` : viaTelegram ? 'Профиль QuizzyWizzy · Telegram связан' : 'Гостевой профиль'));
        card.append(el('span', initialOf(me?.display_name || 'Гость'), 'qw-avatar'), who, button('Настройки', () => guestSettings(), 'secondary settings-open'));
        content.append(card);
        if (!saved && !viaTelegram) note(content, 'Прогресс пока хранится только в этом браузере. Логин, пароль и привязка Telegram — в «Настройках».');
        nameImport?.then(profile => {
            if (version !== generation || state.guest?.account_id !== accountId || guestNamesEdited.has(accountId) || !profile) return;
            if (state.guest.display_name === 'Гость') { state.guest = profile; title.textContent = profile.display_name; }
        });
    }
    // «Профиль → Настройки» of a guest: name, form of address, login and Telegram link, devices, exit.
    async function guestSettings({focusLink = false} = {}) {
        stopRoomClassic();
        const version = ++generation, accountId = state.guest?.account_id;
        const nameImport = importGuestTelegramName();
        window.QuizPlay?.stop(); showGuestTab('profile'); feedback.textContent = ''; content.replaceChildren(); content.dataset.page = 'guest-settings'; shell({page: 'settings'}); consumeSettingsHash();
        content.append(el('span', 'Профиль / Настройки', 'eyebrow settings-path'), el('h1', 'Настройки'));
        const guestLayout = el('div', undefined, 'guest-layout'), guestMain = el('div', undefined, 'guest-main'), guestSide = el('div', undefined, 'guest-side');
        guestLayout.append(guestMain, guestSide); content.append(guestLayout);
        const box = el('section', undefined, 'card profile-card');
        const saved = Boolean(state.guest?.login);
        const profileTitle = el('h2', state.guest?.display_name || 'Гость');
        const viaTelegram = Boolean(state.guest?.telegram_user_id);
        box.append(el('span', saved ? 'Профиль' : viaTelegram ? 'Профиль · Telegram' : 'Гостевой профиль', 'eyebrow'), profileTitle);
        const nameNotice = el('p', '', 'muted'); nameNotice.hidden = true; box.append(nameNotice);
        const nameForm = el('form', undefined, 'account-form');
        const nameLabel = el('label', 'Твоё имя', 'field'), nameInput = el('input');
        Object.assign(nameInput, {type: 'text', name: 'display_name', autocomplete: 'name',
            maxLength: 40, required: true, value: state.guest?.display_name || ''});
        nameLabel.append(nameInput);
        const nameMessage = el('p', '', 'error'); nameMessage.hidden = true;
        const saveName = el('button', 'Сохранить имя', 'primary'); saveName.type = 'submit';
        nameForm.append(nameLabel, nameMessage, saveName); box.append(nameForm);
        box.append(addressSection('guest', state.guest));
        nameImport?.then(profile => {
            if (version !== generation || state.guest?.account_id !== accountId || guestNamesEdited.has(accountId)) return;
            if (!profile) {
                nameNotice.textContent = 'Имя из Telegram не удалось получить. Его можно указать ниже.';
                nameNotice.hidden = false;
            } else if (state.guest.display_name === 'Гость') {
                state.guest = profile;
                profileTitle.textContent = profile.display_name;
                if (nameInput.value === 'Гость') nameInput.value = profile.display_name;
            }
        });
        nameForm.addEventListener('submit', async event => {
            event.preventDefault(); saveName.disabled = true; nameMessage.hidden = true;
            try {
                const profile = await guestRequest('/api/guest/profile', 'POST', {
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({display_name: nameInput.value})});
                if (state.guest?.account_id !== accountId) return;
                guestNamesEdited.add(accountId);
                state.guest = profile;
                if (version !== generation) return;
                await guestSettings();
            } catch (error) {
                if (version !== generation) return;
                nameMessage.textContent = error.message; nameMessage.hidden = false; saveName.disabled = false;
            }
        });
        if (saved) {
            note(box, gm(`Ты вошёл как «${state.guest.login}». `, `Ты вошла как «${state.guest.login}». `, `Вход выполнен как «${state.guest.login}». `) + 'Прогресс привязан к логину, войти можно с любого браузера.');
            note(box, FORGOT_PASSWORD(), 'muted');
        } else if (viaTelegram) {
            note(box, 'Профиль привязан к Telegram: войти в него можно в любом браузере через Telegram, прогресс общий для всех игр.');
            note(box, 'Логин и пароль для входа без Telegram можно задать в разделе «Вход и устройства».', 'muted');
        } else {
            note(box, 'Открытия «Алхимии» сохраняются в приложении. Войти снова можно в этом браузере, пока действует гостевая сессия.');
            note(box, 'Если очистить данные браузера или выйти, доступ к этому профилю будет потерян. Сохрани логин и пароль или свяжи Telegram.', 'muted');
        }
        const linkAnchor = el('div'); linkAnchor.id = 'telegram-link'; box.append(linkAnchor);
        if (tg?.initData) {
            const linkPanel = el('div'), linkMessage = el('p', '', 'muted');
            const current = () => version === generation && state.guest?.account_id === accountId;
            const link = button(state.guest?.telegram_user_id ? 'Проверить связь с Telegram' : 'Связать с Telegram', async () => {
                link.disabled = true; linkPanel.replaceChildren(); linkMessage.textContent = '';
                const initData = tg.initData;
                try {
                    const preview = await guestRequest('/api/account/telegram-link/preview', 'POST', {
                        headers: {'Content-Type': 'application/json'}, body: JSON.stringify({init_data: initData})});
                    if (!current()) return;
                    if (preview.merge_required) {
                        mergeScreen({preview: preview.preview, auto: preview.auto === true,
                            ids: {account_id: preview.account_id, telegram_account_id: preview.telegram_account_id},
                            confirm: body => guestRequest('/api/account/telegram-link/merge', 'POST', {headers: JSON_HEADERS,
                                body: JSON.stringify({init_data: initData, ...body})}),
                            onCancel: () => guestSettings()});
                        return;
                    }
                    if (preview.already_linked) {
                        state.guest.telegram_user_id = preview.telegram_user_id;
                        linkMessage.textContent = 'Этот Telegram уже связан с текущим профилем.';
                        link.disabled = false; return;
                    }
                    note(linkPanel, `Связать профиль «${preview.display_name}» с Telegram «${preview.telegram_display_name}» (ID ${preview.telegram_user_id})? Ферма и прогресс останутся в этом профиле.`);
                    const agree = el('input'); agree.type = 'checkbox';
                    const consent = el('label', undefined, 'field');
                    consent.append(agree, el('span', 'Я подтверждаю связь текущего профиля с этим Telegram.'));
                    const confirm = button('Подтвердить связь', async () => {
                        if (!agree.checked || !current()) return;
                        confirm.disabled = true;
                        try {
                            const result = await guestRequest('/api/account/telegram-link/confirm', 'POST', {
                                headers: {'Content-Type': 'application/json'},
                                body: JSON.stringify({init_data: initData, confirm: true,
                                    account_id: preview.account_id, telegram_user_id: preview.telegram_user_id})});
                            if (!current()) return;
                            state.guest = result.profile;
                            linkPanel.replaceChildren(); link.textContent = 'Проверить связь с Telegram';
                            linkMessage.textContent = 'Telegram связан. Ты продолжаешь играть в том же профиле. Для следующего входа можно выбрать Telegram.';
                            link.disabled = false;
                        } catch (error) {
                            if (!current()) return;
                            linkPanel.replaceChildren(); linkMessage.textContent = error.message; link.disabled = false;
                        }
                    }, 'primary');
                    confirm.disabled = true;
                    agree.addEventListener('change', () => { confirm.disabled = !agree.checked; });
                    linkPanel.append(consent, confirm, button('Отмена', () => {
                        linkPanel.replaceChildren(); link.disabled = false;
                    }, 'quiet'));
                } catch (error) {
                    if (!current()) return;
                    linkMessage.textContent = error.message; link.disabled = false;
                }
            }, 'secondary');
            box.append(link, linkMessage, linkPanel);
        } else if (!state.guest?.telegram_user_id) {
            if (state.botUsername) {
                const linkHost = el('div', undefined, 'telegram-login');
                telegramLogin(linkHost, 'Связать с Telegram'); box.append(linkHost);
            } else note(box, 'Связывание доступно внутри Telegram, когда в этом же окне открыт текущий профиль. Можно войти в него по логину и паролю.', 'muted');
        }
        guestSide.append(devicesSection('guest', {credentials: saved || viaTelegram}));
        if (tg?.initData) box.append(button('Войти через Telegram', guestSignInViaTelegram, 'secondary'));
        if (!saved && !viaTelegram) {
            const keep = el('section', undefined, 'card keep-card');
            keep.append(el('span', 'Аккаунт', 'eyebrow'), el('h2', 'Сохранить профиль'));
            note(keep, 'Задай логин и пароль: прогресс останется за тобой и откроется с любого браузера.');
            note(keep, 'Сохрани пароль. Если забудешь, а Telegram связан с профилем, войди через Telegram и задай новый пароль в разделе «Вход и устройства».', 'notice warn');
            const open = button('Сохранить профиль: задать логин и пароль', () => {
                open.hidden = true; keep.append(accountForm('save', guestSettings));
            }, 'primary');
            keep.append(open); guestSide.append(keep);
        }
        const guestExit = el('div', undefined, 'qw-danger-zone');
        guestExit.append(button(saved || state.guest?.telegram_user_id ? 'Выйти' : 'Выйти и потерять доступ к гостю', async event => {
            event.currentTarget.disabled = true;
            try {
                await guestRequest(saved ? '/api/account/logout' : '/api/guest/logout', 'POST');
                if (!saved) try {
                    const key = `alchemia.atlas.guest.${state.guest.account_id}`;
                    localStorage.removeItem(key); localStorage.removeItem(key + '.backup');
                } catch {}
                state.guest = null;
                try { sessionStorage.removeItem('mqb-auth-choice'); } catch {}
                try { localStorage.setItem('mqb-telegram-logged-out', '1'); } catch {}
                loginScreen();
            } catch (error) { feedback.textContent = error.message; event.currentTarget.disabled = false; }
        }, 'danger'));
        box.append(guestExit);
        guestMain.append(box, appearanceCard('guest'), farmRequestNotificationsCard('guest'));
        if (focusLink) { linkAnchor.scrollIntoView?.({block: 'center'}); linkAnchor.nextElementSibling?.focus?.(); }
    }
    // Guest «Чаты» / «Рейтинг»: both depend on Telegram chats, so a guest sees one clear step instead of an empty list.
    function guestSignInViaTelegram() {
        state.guest = null;
        try { sessionStorage.setItem('mqb-auth-choice', 'telegram'); } catch {}
        loginScreen();
    }
    function guestStub(page) {
        stopRoomClassic(); generation++; window.QuizPlay?.stop(); showGuestTab(page);
        feedback.textContent = ''; content.replaceChildren(); content.dataset.page = 'guest-stub'; shell({page});
        const linked = Boolean(state.guest?.telegram_user_id), card = el('section', undefined, 'card guest-stub');
        card.append(el('span', page === 'chats' ? 'Чаты' : 'Рейтинг', 'eyebrow'),
            el('h2', page === 'chats' ? 'Чатов пока нет' : 'Рейтинга пока нет'));
        note(card, linked ? 'Профиль связан с Telegram. Войди через Telegram, чтобы увидеть чаты и рейтинг чатов.'
            : 'Чаты и рейтинг чатов появятся, когда ты свяжешь Telegram с профилем.');
        card.append(linked ? button('Войти через Telegram', guestSignInViaTelegram, 'primary')
            : button('Связать Telegram', () => guestSettings({focusLink: true}), 'primary'));
        content.append(card);
    }
    // The same bottom bar as for Telegram players: the guest's four tabs share one structure.
    function showGuestTab(tab) {
        nav.hidden = false;
        nav.querySelectorAll('button').forEach(node => { if (node.dataset.page === tab) node.setAttribute('aria-current', 'page'); else node.removeAttribute('aria-current'); });
    }
    function guestNavigate(page) {
        window.QuizTelegram.selection();
        if (page === 'profile') return guestProfile();
        if (page === 'rating') return guestRating().catch(error => { feedback.textContent = error.message; });
        if (page === 'chats') return guestStub(page);
        return guestHome();
    }
    const RENEW_AFTER_MS = 10 * 60 * 1000;   // сессия живёт 15 минут, продлеваем заранее
    let renewTimer = null;
    function scheduleRenewal() {
        clearTimeout(renewTimer);
        if (!state.authenticated) return;
        renewTimer = setTimeout(renewSession, RENEW_AFTER_MS);
        // В браузере это число, в Node — объект таймера: unref не даёт таймеру
        // держать event loop в юнит-тестах.
        renewTimer?.unref?.();
    }
    async function renewSession() {
        if (!state.authenticated) return;
        try {
            await request('/api/mini/session/renew', {method: 'POST'});
            scheduleRenewal();
        } catch (error) {
            clearTimeout(renewTimer);
            if (!state.authenticated) loginScreen('Сессия истекла. Войди снова: как гость, по логину и паролю или через Telegram.');
            else feedback.textContent = error.message;
        }
    }
    function configureTelegram() {
        // BackButton is owned by QW.nav (shell() sets the root handler per screen); ⚙ → «Профиль и настройки» lands here.
        window.QuizTelegram.configure(null, openAccountSettings, () => { if (state.authenticated) load(); });
    }
    // Chat game settings (admin form, read-only for members) are a segment of the chat page, not part of the account settings.
    function openChatSettings() {
        if (!state.selected) { navigate('chats'); return; }
        state.chatTab = 'settings'; navigate('chat');
    }
    function openAccountSettings() {
        if (state.authenticated) navigate('settings');
        else if (state.guest) guestSettings();
    }
    async function createTelegramSession(demo = state.demo, resume = false) {
        const result = await request(demo ? '/api/dev/session' : resume ? '/api/mini/session/resume' : '/api/mini/session', {method: 'POST',
            headers: {'Content-Type': 'application/json'}, body: demo ? '{}' : JSON.stringify({init_data: tg?.initData})});
        if (!resume) try { localStorage.removeItem('mqb-telegram-logged-out'); } catch {}
        return result;
    }
    function telegramFirstStart() {
        generation++; nav.hidden = true; feedback.textContent = ''; content.replaceChildren(); content.dataset.page = 'first-start'; shell();
        const box = el('section', undefined, 'login');
        box.append(el('h1', 'Добро пожаловать в QuizzyWizzy'));
        note(box, 'Создай игровой профиль, чтобы сохранять прогресс.');
        const start = button('Начать играть', async () => {
            start.disabled = true; feedback.textContent = '';
            try { await createTelegramSession(false); await continueFarmInvite('telegram'); }
            catch (error) { feedback.textContent = error.message; start.disabled = false; }
        }, 'primary');
        box.append(start, button('Уже есть профиль? Войти', () => loginScreen(), 'quiet'));
        content.append(box);
    }
    function loginScreen(message = '') {
        stopRoomClassic();
        generation++; state.guest = null; window.QuizPlay?.stop(); nav.hidden = true; content.replaceChildren(); content.dataset.page = 'login'; shell();
        const box = el('section', undefined, 'login');
        const hero = el('div', undefined, 'hero'); const image = el('img'); image.src = '/app/host.webp'; image.alt = 'Филиныч, сова-ведущий QuizzyWizzy'; hero.append(image); box.append(hero);
        box.append(el('span', 'QuizzyWizzy · Филиныч на связи', 'eyebrow'), el('h1', 'Играй. Узнавай. Возвращайся.'));
        note(box, 'Квиз, фото-загадки и твой прогресс. Играй здесь или в Telegram — как удобнее.');
        if (message) note(box, message, 'error');
        const initData = tg?.initData;
        if (initData && guestAllowed) {
            note(box, 'Если у тебя уже есть профиль по логину, войди в него ниже. Связать Telegram можно после входа в профиле.', 'notice');
        }
        if (state.demo || initData) {
            const enter = button(state.demo ? 'Войти как dev-игрок' : 'Продолжить через Telegram', async () => {
                enter.disabled = true; feedback.textContent = '';
                try {
                    await createTelegramSession();
                    await continueFarmInvite('telegram');
                } catch (error) { feedback.textContent = error.message; enter.disabled = false; }
            }, 'primary'); box.append(enter);
            // Вход выбирает игрок: гостевой профиль не объединяется с Telegram автоматически.
        }
        if (guestAllowed) {
            const guest = button('Продолжить как гость', async () => {
                guest.disabled = true; feedback.textContent = '';
                try {
                    state.guest = await guestRequest('/api/guest/start', 'POST');
                    try { sessionStorage.setItem('mqb-auth-choice', 'guest'); } catch {}
                    try { localStorage.removeItem('mqb-telegram-logged-out'); } catch {}
                    guestHome();
                } catch (error) {
                    feedback.textContent = error.message;
                    guest.disabled = false;
                    if (error.status === 401 && !box.querySelector('[data-new-guest]')) {
                        note(box, 'Прежняя гостевая сессия закончилась. Старый профиль без привязки восстановить нельзя.', 'notice warn');
                        const fresh = button('Создать нового гостя', async () => {
                            fresh.disabled = true; feedback.textContent = '';
                            try {
                                await guestRequest('/api/guest/logout', 'POST');
                                state.guest = await guestRequest('/api/guest/start', 'POST');
                                try { sessionStorage.setItem('mqb-auth-choice', 'guest'); } catch {}
                                try { localStorage.removeItem('mqb-telegram-logged-out'); } catch {}
                                guestHome();
                            } catch (failed) { feedback.textContent = failed.message; fresh.disabled = false; }
                        }, 'quiet');
                        fresh.dataset.newGuest = '1'; box.append(fresh);
                    }
                }
            }, 'quiet');
            guest.classList.add('guest-entry'); box.append(guest);
            note(box, 'Гостевой вход работает без Telegram. Открытия «Алхимии» сохраняются на сервере и привязаны к гостевой сессии этого браузера.', 'muted');
            const panel = el('div', undefined, 'account-panel');
            const toggles = el('div', undefined, 'actions qw-btn-row');
            const show = kind => {
                panel.replaceChildren(accountForm(kind, guestHome));
                panel.querySelector('input')?.focus();
            };
            toggles.append(button('Войти по логину', () => show('login'), 'quiet'),
                           button('Создать аккаунт', () => show('register'), 'quiet'));
            box.append(toggles, panel);
            note(box, FORGOT_PASSWORD(), 'muted');
        }
        if (!initData && state.botUsername && guestAllowed) {
            const telegramHost = el('div', undefined, 'telegram-login');
            telegramLogin(telegramHost, 'Войти через Telegram'); box.append(telegramHost);
        }
        content.append(box);
    }
    function isChatGone(error) { return error && (error.status === 404 || error.status === 410); }
    function dropUnavailableChat(chatId) {
        state.chats = state.chats.filter(chat => chat.chat_id !== chatId);
        if (state.selected === chatId) state.selected = state.chats[0]?.chat_id || '';
    }
    async function load() {
        const version = ++generation; window.QuizPlay?.stop();
        content.replaceChildren(el('p', 'Получаем твои данные…', 'muted'));
        try {
            const [me, progress, chats, achievements] = await Promise.all([request('/api/mini/me'), request('/api/mini/progress'), request('/api/mini/chats?limit=50'), request('/api/mini/achievements')]);
            if (version !== generation || !state.authenticated) return;
            Object.assign(state, {me, progress, chats: chats.items, moreChats: chats.has_more, chatOffset: chats.items.length, achievements});
            window.QW?.prefs?.applyAccount(me); // the Account's «Контрастный режим» wins over this device's cache
            if (resumeFarmInvite('telegram')) return;
            if (state.selected && !state.chats.some(c => c.chat_id === state.selected)) {
                state.launchLost = true;      // чат из ссылки недоступен: не подменяем молча
                state.selected = '';
            }
            if (!state.selected) state.selected = state.chats[0]?.chat_id || '';
            // /app#settings (the ⚙ menu of a game) opens «Профиль → Настройки» once the player is in.
            if (openSettingsOnLoad) { consumeSettingsHash(); state.page = 'settings'; }
            nav.hidden = false; await navigate(state.page);
        } catch (error) {
            if (version !== generation) return;
            if (!state.authenticated) loginScreen(error.message);
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
        if (text === '/help') { navigate('help'); return; }
        if (text === '/adminsettings') { openChatSettings(); return; }
        const selected = state.chats.find(chat => chat.chat_id === state.selected);
        const action = {'/quiz': 'quiz', '/photo_quiz': 'photo'}[text];
        if (action && selected?.type === 'private' && window.QuizTelegram.openBot(state.botUsername, action)) return;
        try { await navigator.clipboard.writeText(text); feedback.textContent = `${text} скопирована. Отправь её боту в нужном чате.`; }
        catch { feedback.replaceChildren(el('span', 'Отправь в чат: '), el('code', text)); }
    }
    // Segmented control (.qw-btn-group): one choice among equals (UI_RULES §9).
    function segmented(options, current, onPick, label) {
        const group = el('div', undefined, 'qw-btn-group seg-scroll'); group.setAttribute('role', 'radiogroup');
        if (label) group.setAttribute('aria-label', label);
        const items = options.map(([value, text]) => {
            const node = el('button', text); node.type = 'button'; node.dataset.value = value;
            node.setAttribute('role', 'radio'); node.setAttribute('aria-checked', String(value === current));
            node.addEventListener('click', () => { items.forEach(item => item.setAttribute('aria-checked', String(item === node))); onPick(value); });
            return node;
        });
        group.append(...items); return group;
    }
    const initialOf = name => (name || '').trim().charAt(0).toUpperCase() || '?';
    function modeCard(parent, title, description, cmd, active) {
        const item = el('article', undefined, 'card'); const heading = el('div', undefined, 'card-heading'); heading.append(el('h2', title));
        if (active) heading.append(el('span', 'Идёт игра', 'badge')); item.append(heading); note(item, description);
        if (active) {
            note(item, `Вопрос ${active.question_number} из ${active.question_count}`);
            const progress = el('progress'); progress.max = Math.max(1, active.question_count); progress.value = active.question_number; progress.setAttribute('aria-label', `Прогресс: ${active.question_number} из ${active.question_count}`); item.append(progress);
        }
        const actions = el('div', undefined, 'qw-btn-stack');
        actions.append(button(active ? 'Продолжить игру' : 'Настроить и играть', () => play(cmd), 'primary'));
        if (active) actions.append(button('Команда остановки', () => command(cmd === '/quiz' ? '/stopquiz' : '/stop_photo_quiz'), 'danger'));
        item.append(actions); parent.append(item);
    }
    function play(command) { playCommand = command; navigate('play'); }
    const HOME_GAME_CARDS = [
        {
            id: 'classic', side: 'left', palette: 'green', image: '/app/host-card.webp',
            alt: 'Филиныч ведёт классический квиз в студии', eyebrow: 'РАЗМИНКА ДЛЯ ЛЮБОПЫТНЫХ',
            title: 'Классический квиз',
            description: 'Один вопрос — одно маленькое открытие.',
            label: 'Играть в квиз', action: () => play('/quiz'), runtime: true, position: '24% 44%'
        },
        {
            id: 'photo', side: 'right', palette: 'green', image: '/app/photo.webp',
            alt: 'Филиныч рассматривает фотографии и ищет подсказки', eyebrow: 'СЛОЖИ ОБРАЗЫ В СЛОВО',
            title: 'Фото-загадки',
            description: 'Смотри внимательнее: детали важны.',
            label: 'Угадывать фото', action: () => play('/photo_quiz'), runtime: true, position: '72% 62%'
        },
        {
            id: 'night', side: 'left', palette: 'brown', image: '/app/mafia-card.webp',
            alt: 'Филиныч в капюшоне ведёт ночное дело', eyebrow: 'НОВЫЙ РЕЖИМ · DEV',
            title: 'Ночной город',
            description: 'Собери стол, настрой роли и раскрой городскую историю.',
            label: 'Открыть дело', action: () => navigate('mafia'), position: '24% 46%'
        },
        {
            id: 'atlas', side: 'right', palette: 'brown', image: '/app/alchemy.webp',
            alt: 'Сова-алхимик у светящегося атласа элементов', eyebrow: 'НОВЫЙ РЕЖИМ · АЛХИМИЯ',
            title: 'Атлас маленьких чудес',
            description: 'Смешивай стихии, открывай цепочки и заполняй свой атлас.',
            label: 'Открыть атлас', action: () => {
                window.location.assign('/app/alchemy?mode=telegram');
            }, position: '72% 50%'
        },
        {
            id: 'farm', side: 'left', illustration: '🌱',
            alt: 'Саженец для будущего режима Филиныча', eyebrow: 'ТИХО РАСТЁТ · СКОРО',
            title: 'Весёлый фермер',
            description: 'Свой маленький участок, урожай и заказы. Готовим игру — пока без фальшивой кнопки запуска.',
            label: 'Скоро', action: null,
        },
    ];
    // Guest/password accounts see the same HOME_GAME_CARDS; only the action differs per card.
    function guestCardSpec(spec, ctx) {
        const soon = {...spec, label: 'Скоро', disabled: true, runtime: false, action: () => {}};
        if (spec.id === 'classic') return roomClassicEnabled ? {...spec, runtime: false, action: () => openSoloGame('classic')} : soon;
        if (spec.id === 'photo') return roomPhotoEnabled ? {...spec, runtime: false, action: () => openSoloGame('photo')} : soon;
        if (spec.id === 'night') return {...spec, label: 'Собрать компанию', action: () => openCompanyGame()};
        if (spec.id === 'atlas') return {...spec, action: () => window.location.assign('/app/alchemy?mode=guest')};
        if (spec.id === 'farm') return ctx.farmLive
            ? {...spec, image: '/app/farm-card-v2.webp', alt: 'Филиныч с урожаем на своей ферме', palette: 'green', position: '45% center',
               eyebrow: 'НОВЫЙ РЕЖИМ · АЛЬФА', label: 'На свою ферму',
               description: 'Выращивай урожай, запускай мастерские и заглядывай к соседям.',
               action: () => window.location.assign('/app/farm?identity=guest')}
            : soon;
        return soon; // future games stay visible and disabled until given a guest action
    }
    const SOLO_ROOM_TITLE = 'Моя игра';
    let soloOpening = false;
    // Full play screen (the same one Telegram uses) for solo games. Set to false to fall back to the
    // simplified room screens openGuestClassic/openGuestPhoto, which stay reachable from the rooms list.
    const SOLO_FULL_PLAY_UI = true;
    const roomPlayRequest = (path, options = {}) => guestRequest(path, options.method || 'GET', {headers: options.headers, body: options.body});
    async function mountSoloPlay(kind, room) {
        stopRoomClassic(); window.QuizPlay?.stop();
        const version = ++generation;
        state.page = 'guest-play'; nav.hidden = true; feedback.textContent = ''; content.replaceChildren(); content.dataset.page = 'guest-play';
        shell({back: () => guestHome(), title: kind === 'photo' ? 'Фото-загадки' : 'Классический квиз'});
        const api = window.QuizPlay.roomApi(room.id, roomPlayRequest, {accountId: state.guest?.account_id || null});
        const command = kind === 'photo' ? '/photo_quiz' : '/quiz';
        try {
            await window.QuizPlay.mount({host: content, request: roomPlayRequest, api, command, selection: () => {},
                onHome: () => guestHome(), onReplay: () => openSoloGame(kind), onProfile: () => guestHome(),
                media: async path => {
                    const response = await fetch(path, {credentials: 'same-origin'});
                    if (!response.ok) throw new Error('Фото недоступно'); return response.blob();
                }});
        } catch (error) {
            if (version !== generation) return;
            note(content, error.message, 'error'); content.append(button('Повторить', () => mountSoloPlay(kind, room), 'quiet'));
        }
    }
    // Solo play for guests: reuse the personal owner room, creating it on first use.
    // Night City needs company: open (or create) the player's own «Ночной город» room and its lobby.
    let companyOpening = false;
    async function openCompanyGame() {
        if (companyOpening) return;
        companyOpening = true; feedback.textContent = '';
        try {
            const data = await guestRequest('/api/guest/rooms');
            let room = (data.items || []).find(item => item.role === 'owner' && item.title === 'Ночной город');
            if (!room) {
                if (typeof globalThis.crypto?.randomUUID !== 'function') throw new Error('Безопасное создание комнаты не поддерживается этим браузером.');
                room = await guestRequest('/api/guest/rooms', 'POST', {headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({request_id: globalThis.crypto.randomUUID(), title: 'Ночной город'})});
            }
            companyOpening = false;
            await openGuestMafia({...room, role: 'owner', title: room.title || 'Ночной город'});
        } catch (error) { feedback.textContent = error.message; }
        finally { companyOpening = false; }
    }
    async function openSoloGame(kind) {
        if (soloOpening) return;
        soloOpening = true; feedback.textContent = '';
        try {
            const data = await guestRequest('/api/guest/rooms');
            let room = (data.items || []).find(item => item.role === 'owner' && item.title === SOLO_ROOM_TITLE);
            if (!room) {
                if (typeof globalThis.crypto?.randomUUID !== 'function') throw new Error('Безопасное создание комнаты не поддерживается этим браузером.');
                room = await guestRequest('/api/guest/rooms', 'POST', {headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({request_id: globalThis.crypto.randomUUID(), title: SOLO_ROOM_TITLE})});
            }
            const target = {...room, role: 'owner', title: room.title || SOLO_ROOM_TITLE};
            soloOpening = false;
            if (SOLO_FULL_PLAY_UI && window.QuizPlay?.roomApi) await mountSoloPlay(kind, target);
            else await (kind === 'photo' ? openGuestPhoto(target, {autostart: true}) : openGuestClassic(target, {autostart: true}));
        } catch (error) { feedback.textContent = error.message; }
        finally { soloOpening = false; }
    }
    function homeGameCard(spec) {
        const classes = ['card', 'play-choice', 'game-mode-card', spec.palette && `palette-${spec.palette}`,
            spec.side && `image-${spec.side}`, `mode-${spec.id}`].filter(Boolean).join(' ');
        const card = el('article', undefined, classes);
        card.dataset.gameMode = spec.id; card.dataset.modeStatus = spec.status || 'available';
        if (spec.image) {
            const image = el('img'); image.src = spec.image; image.alt = spec.alt; image.className = 'mode-choice-host';
            image.style.objectPosition = spec.position || (spec.side === 'left' ? '25% center' : '75% center'); card.append(image);
        } else {
            const illustration = el('span', spec.illustration, 'mode-coming-illustration'); illustration.setAttribute('aria-hidden', 'true'); card.append(illustration);
        }
        const body = el('div', undefined, 'choice-copy');
        body.append(el('span', spec.eyebrow, 'eyebrow'), el('h2', spec.title));
        note(body, spec.description);
        if (spec.action) {
            const start = button(spec.label, spec.action, 'primary');
            if (spec.runtime) start.disabled = !runtimeEnabled || !state.selected;
            if (spec.disabled) start.disabled = true;
            body.append(start);
        } else {
            const status = el('span', spec.label, 'mode-coming-status'); status.setAttribute('aria-label', 'Режим пока не запущен'); body.append(status);
        }
        card.append(body);
        return card;
    }
    async function home(version) {
        const hero = el('section', undefined, 'hero home-hero'), copy = el('div', undefined, 'hero-copy');
        copy.append(el('span', 'Филиныч на связи', 'eyebrow'));
        const title = el('h1', 'Ну что, '); title.append(el('em', 'сыграем?')); copy.append(title);
        note(copy, 'Выбирай формат. Я приготовлю вопросы.');
        const image = el('img'); image.src = '/app/host.webp'; image.alt = 'Сова Филиныч, ведущий квиза'; hero.append(copy, image); content.append(hero);
        const rhythm = el('div', undefined, 'player-rhythm');
        rhythm.append(el('span', `${format(state.me.score)} баллов`), el('span', `Лучшая серия · ${format(state.progress.best_streak)}`)); content.append(rhythm);
        const telegramAddressPrompt = addressPrompt('telegram', state.me);
        if (telegramAddressPrompt) content.append(telegramAddressPrompt);
        const choices = el('section', undefined, 'play-choices game-mode-list');
        const modes = new Map((state.gameModes || []).map(mode => [mode.id, mode]));
        HOME_GAME_CARDS.filter(spec => modes.has(spec.id)).forEach(spec => {
            const mode = modes.get(spec.id);
            const actual = spec.id === 'farm' && mode.status === 'development'
                ? {...spec, image: '/app/farm-card-v2.webp', alt: 'Филиныч с урожаем на своей ферме', side: 'left', palette: 'green', position: '45% center',
                   eyebrow: 'НОВЫЙ РЕЖИМ · АЛЬФА', label: 'На свою ферму',
                   description: 'Выращивай урожай, запускай мастерские и заглядывай к соседям.',
                   action: () => window.location.assign('/app/farm?identity=telegram')}
                : spec;
            choices.append(homeGameCard({...actual, title: mode.title, status: mode.status}));
        });
        content.append(choices);
        if (!runtimeEnabled) note(content, 'Игровой режим подключается. Профиль и чатовый бот доступны.', 'muted');
        else {
            // Сбой одного чата не должен ломать главную: недоступный чат тихо скрываем,
            // остальные ошибки просто означают «текущей игры не видно».
            let active = {items: []};
            if (state.selected) {
                try { active = await request(`/api/mini/chats/${state.selected}/games`); }
                catch (error) { if (isChatGone(error)) dropUnavailableChat(state.selected); }
            }
            if (version !== generation) return;
            if (active.items?.length) content.append(button('Вернуться в текущую игру', () => play(null), 'resume-game'));
        }
        const shortcuts = el('div', undefined, 'home-shortcuts');
        shortcuts.append(button('Как играть', () => navigate('help'), 'quiet')); content.append(shortcuts);
        const inChat = el('section', undefined, 'chat-alternative');
        if (!state.selected) {
            note(inChat, 'Для игры в приложении нужен личный или групповой чат, где уже работает бот. Запусти /start в личке или добавь бота в группу — чат появится здесь.');
            inChat.append(button('Открыть чаты', () => navigate('chats'), 'quiet'));
            if (state.botUsername) inChat.append(button('Открыть бота', () => openBotHome(), 'quiet'));
        } else {
            note(inChat, 'Можно и в чате Telegram. Баллы и состояние раунда останутся общими.');
            inChat.append(button('Играть в чате', () => window.QuizTelegram.openBot(state.botUsername, 'home'), 'quiet'));
        }
        content.append(inChat);
    }
    function openBotHome() {
        if (!window.QuizTelegram.openBot(state.botUsername, 'home')) {
            feedback.textContent = 'Не удалось открыть ссылку. Найди QuizzyWizzy в Telegram и отправь /start.';
        }
    }
    function noChatPlay() {
        const card = el('section', undefined, 'card no-chat-play');
        card.append(el('span', 'СНАЧАЛА ПОДКЛЮЧИ ЧАТ', 'eyebrow'), el('h1', 'Где будем играть?'));
        note(card, 'Квиз и фото-загадки используют тот же игровой чат и те же очки, что Telegram-бот. Запусти /start с ботом или добавь его в группу, затем выбери чат в приложении.');
        card.append(button('Открыть чаты', () => navigate('chats'), 'primary'));
        if (state.botUsername) card.append(button('Открыть бота', () => openBotHome(), 'quiet'));
        content.append(card);
    }
    function help() {
        content.append(el('span', 'Короткий маршрут', 'eyebrow'), el('h1', 'Как играть'));
        note(content, 'Выбирай режим на главной. Вопросы, ответы и игровой прогресс обрабатывает сервер.');
        const classic = el('section', undefined, 'card');
        classic.append(el('h2', 'Классический квиз'));
        note(classic, 'Выбери чат и настрой раунд. Отвечай на вопросы до конца серии; результаты сохраняются в общей статистике.');
        classic.append(button('Открыть классический квиз', () => play('/quiz'), 'primary'));
        content.append(classic);
        const photo = el('section', undefined, 'card');
        photo.append(el('h2', 'Фото-загадки'));
        note(photo, 'Рассмотри квадратную картинку и подсказку, затем введи слово-ответ.');
        photo.append(button('Открыть фото-загадки', () => play('/photo_quiz'), 'primary'));
        content.append(photo);
        const profileCard = el('section', undefined, 'card');
        profileCard.append(el('h2', 'Твой профиль'));
        note(profileCard, 'В профиле собраны личный прогресс, история, достижения и настройки. Результат доступен и через интерфейс бота.');
        profileCard.append(button('Настройки', () => navigate('settings'), 'quiet'));
        profileCard.append(button('Мой профиль', () => navigate('profile'), 'quiet'));
        content.append(profileCard);
    }
    async function openGuestPhoto(room, {autostart = false} = {}) {
        stopRoomClassic(); generation++; window.QuizPlay?.stop();
        const version = generation, base = `/api/guest/rooms/${encodeURIComponent(room.id)}/photo`;
        const key = `${state.guest?.account_id}:${room.id}`, lifetime = new AbortController();
        let timer = null, submitting = false, refreshing = false, startNow = false, rendered, draft = '', roundKey = '', setup, setupError;
        const clearTimer = () => { clearTimeout(timer); timer = null; };
        roomPhotoDispose = () => { clearTimer(); lifetime.abort(); };
        state.page = 'guest-photo'; nav.hidden = true; feedback.textContent = '';
        shell({back: () => guestHome(), title: 'Фото-загадки'});
        const active = () => !lifetime.signal.aborted && version === generation && state.page === 'guest-photo';
        const call = (path, method = 'GET', options = {}) => guestRequest(base + path, method, {...options, signal: lifetime.signal});
        const pending = () => roomPhotoPending?.key === key ? roomPhotoPending : null;
        const command = async (action, body) => {
            if (submitting || !active()) return;
            submitting = true; clearTimer();
            if (!pending()) roomPhotoPending = {key, action, body, id: crypto.randomUUID()};
            const receipt = pending();
            try {
                await call(`/${receipt.action}`, 'POST', {headers: {'Content-Type': 'application/json', 'Idempotency-Key': receipt.id}, body: JSON.stringify(receipt.body)});
                if (roomPhotoPending === receipt) roomPhotoPending = null;
                if (receipt.action === 'answer' || receipt.action === 'start') draft = '';
                rendered = undefined;
            } catch (error) {
                if (error.status && error.status < 500 && roomPhotoPending === receipt) roomPhotoPending = null;
                if (active()) feedback.textContent = error.message;
            } finally { submitting = false; }
            if (active()) await refresh();
        };
        const refreshOnce = async () => {
            if (!active() || submitting || refreshing) return;
            clearTimer(); refreshing = true;
            try {
                if (!setup) {
                    try { setup = await call('/setup'); setupError = null; }
                    catch (error) { setupError = error.message; }
                    if (!active()) return;
                }
                const data = await call('/current');
                if (!active()) return;
                const current = data.current, q = current?.question;
                if (autostart && room.role === 'owner' && roomPhotoEnabled && setup?.can_start && !data.occupied && !pending()
                    && (!current || ['finished', 'stopped', 'interrupted'].includes(current.status))) { startNow = true; autostart = false; return; }
                if (autostart && (current || setupError || data.occupied)) autostart = false;
                const nextRound = `${current?.game_id || ''}:${q?.round_id || ''}`;
                if (nextRound !== roundKey) { roundKey = nextRound; draft = ''; }
                const fingerprint = JSON.stringify({data, setup, setupError, pending: pending()});
                if (fingerprint !== rendered) {
                    rendered = fingerprint;
                    const focused = document.activeElement?.getAttribute?.('aria-label') === 'Твой ответ на фото';
                    const selection = focused ? [document.activeElement.selectionStart, document.activeElement.selectionEnd] : null;
                    content.replaceChildren();
                    const box = el('section', undefined, 'card'); content.append(box);
                    box.append(el('h1', room.title), el('h2', 'Фото-загадки'));
                    note(box, 'Личная серия владельца комнаты.');
                    if (setupError && room.role === 'owner' && roomPhotoEnabled) {
                        note(box, setupError, 'error');
                        box.append(button('Повторить каталог', () => { rendered = undefined; return refresh(); }, 'quiet'));
                    }
                    if (pending()) {
                        note(box, 'Ответ сервера не получен. Повтори ту же команду.');
                        box.append(button('Повторить команду', () => command(pending().action, pending().body), 'primary'));
                    } else if (data.occupied) {
                        note(box, 'Фото-серия занята другим игроком.');
                    } else if (!current || ['finished', 'stopped', 'interrupted'].includes(current.status)) {
                        note(box, current ? `Серия завершена. Верно: ${current.correct}. Очки: ${format(current.score)}.` : 'Фото-серия ещё не началась.');
                        if (room.role === 'owner' && roomPhotoEnabled && setup) {
                            note(box, `${setup.question_count} картинки · ${setup.open_seconds} секунд · ${setup.hints_enabled ? 'с подсказками' : 'без подсказок'}`);
                            const start = button('Начать фото-серию', () => command('start', {question_count: setup.question_count, open_seconds: setup.open_seconds, hints_enabled: setup.hints_enabled}), 'primary');
                            start.disabled = !setup.can_start; box.append(start);
                            if (!setup.can_start) note(box, 'В каталоге пока нет доступных фото-загадок.');
                        }
                    } else if (q) {
                        note(box, `Фото ${q.question_number}/${q.question_count} · до ${new Date(q.ends_at * 1000).toLocaleTimeString('ru-RU')}`);
                        const image = el('img'); image.alt = 'Что изображено на фото?'; image.className = 'play-photo';
                        const imageStatus = el('p'); let imageRetry = 0;
                        const retryImage = button('Повторить загрузку фото', () => {
                            retryImage.hidden = true; imageStatus.textContent = 'Загружаю фото…';
                            image.src = `${q.image_url}&retry=${++imageRetry}`;
                        }, 'quiet'); retryImage.hidden = true;
                        image.addEventListener('error', () => {
                            if (!active()) return;
                            imageStatus.textContent = 'Фото не загрузилось. Повтори загрузку.'; retryImage.hidden = false;
                        });
                        image.addEventListener('load', () => { imageStatus.textContent = ''; retryImage.hidden = true; });
                        image.src = q.image_url; box.append(image, imageStatus, retryImage);
                        if (q.mask) note(box, q.mask, 'photo-mask');
                        if (q.feedback === 'almost') note(box, 'Очень близко — собери точное слово.');
                        else if (q.feedback === 'wrong') note(box, 'Пока мимо. Попробуй ещё.');
                        const form = el('form'), input = el('input'); input.type = 'text'; input.value = draft; input.maxLength = 300;
                        input.setAttribute('aria-label', 'Твой ответ на фото'); input.autocomplete = 'off'; input.disabled = q.closed;
                        input.addEventListener('input', () => { draft = input.value; });
                        const answer = button('Ответить', () => command('answer', {game_id: current.game_id, round_id: q.round_id, answer: input.value}), 'primary'); answer.type = 'button'; answer.disabled = q.closed;
                        form.addEventListener('submit', event => { event.preventDefault(); if (!q.closed) command('answer', {game_id: current.game_id, round_id: q.round_id, answer: input.value}); });
                        form.append(input, answer); box.append(form);
                        if (focused) { input.focus?.(); if (selection) input.setSelectionRange?.(...selection); }
                        if (room.role === 'owner') box.append(button('Остановить фото-серию', () => command('stop', {game_id: current.game_id, expected_revision: current.revision}), 'quiet'));
                        note(box, `Верно: ${current.correct}. Очки этой серии: ${format(current.score)}.`);
                    }
                    if (current?.last_result) note(box, `${current.last_result.correct ? 'Верно!' : 'Раунд завершён.'} ${current.last_result.answer} · ${format(current.last_result.points)} очков.`);
                }
                if (active() && !pending()) timer = setTimeout(refresh, 3000);
            } catch (error) {
                if (!active()) return;
                rendered = undefined;
                content.replaceChildren();
                note(content, error.message, 'error'); content.append(button('Повторить', refresh));
            } finally { refreshing = false; }
        };
        // Solo autostart runs after the read finished so command() can refresh normally.
        const refresh = async () => {
            await refreshOnce();
            if (startNow && active()) {
                startNow = false;
                await command('start', {question_count: setup.question_count, open_seconds: setup.open_seconds, hints_enabled: setup.hints_enabled});
            }
        };
        // Catalog failure must not prevent continuing a persisted series.
        if (active()) await refresh();
    }
    async function openGuestClassic(room, {autostart = false} = {}) {
        stopRoomClassic();
        generation++; window.QuizPlay?.stop();
        const version = generation, base = `/api/guest/rooms/${encodeURIComponent(room.id)}/classic`;
        const key = `${state.guest?.account_id}:${room.id}`;
        let submitting = false;
        let lastAnswer = null, rendered = undefined;
        state.page = 'guest-classic'; nav.hidden = true; feedback.textContent = '';
        shell({back: () => guestHome(), title: 'Классический квиз'});
        const active = () => version === generation && state.page === 'guest-classic';
        const command = async (action, body) => {
            if (submitting) return;
            submitting = true; stopRoomClassic();
            if (!roomClassicCommands.has(key)) roomClassicCommands.set(key, {action, body, id: crypto.randomUUID()});
            const pending = roomClassicCommands.get(key);
            try {
                const result = await guestRequest(`${base}/${pending.action}`, 'POST', {headers: {'Content-Type': 'application/json', 'Idempotency-Key': pending.id}, body: JSON.stringify(pending.body)});
                if (pending.action === 'answer') {
                    const accepted = result.accepted_answer || result.question;
                    if (accepted?.answered) lastAnswer = accepted;
                }
                if (pending.action === 'start') lastAnswer = null;
                roomClassicCommands.delete(key);
                rendered = undefined;
            } catch (error) {
                if (error.status && error.status < 500) roomClassicCommands.delete(key);
                if (active()) feedback.textContent = error.message;
            }
            submitting = false;
            if (active()) await refresh();
        };
        const refresh = async () => {
            stopRoomClassic();
            if (!active()) return;
            try {
                const data = await guestRequest(`${base}/current`);
                if (!active()) return;
                const current = data.current;
                const pending = roomClassicCommands.get(key);
                const fingerprint = JSON.stringify({current, pending, lastAnswer});
                if (fingerprint === rendered) { roomClassicTimer = setTimeout(refresh, 3000); return; }
                rendered = fingerprint;
                content.replaceChildren();
                const box = el('section', undefined, 'card'); content.append(box);
                box.append(el('h1', room.title), el('h2', 'Классический квиз'));
                if (pending) {
                    note(box, 'Ответ сервера не получен. Повтори ту же команду.');
                    box.append(button('Повторить команду', () => command(pending.action, pending.body), 'primary'));
                    return;
                }
                if (autostart && room.role === 'owner' && roomClassicEnabled && (!current || ['finished', 'stopped', 'interrupted'].includes(current.status))) {
                    autostart = false; await command('start', {count: 5, open_seconds: 30, interval_seconds: 0}); return;
                }
                autostart = false;
                if (!current || ['finished', 'stopped', 'interrupted'].includes(current.status)) {
                    note(box, current ? 'Викторина завершена.' : 'Викторина ещё не началась.');
                    if (room.role === 'owner' && roomClassicEnabled) {
                        const count = el('input'); count.type = 'number'; count.min = '1'; count.max = '50'; count.value = '5'; count.setAttribute('aria-label', 'Количество вопросов');
                        const seconds = el('input'); seconds.type = 'number'; seconds.min = '5'; seconds.max = '600'; seconds.value = '30'; seconds.setAttribute('aria-label', 'Секунд на вопрос');
                        box.append(count, seconds, button('Начать квиз', () => command('start', {count: Number(count.value), open_seconds: Number(seconds.value), interval_seconds: 0}), 'primary'));
                    }
                } else {
                    box.append(el('p', `Вопрос ${current.game.current}/${current.game.total}`));
                    const q = current.question;
                    if (q) {
                        box.append(el('h2', q.question));
                        note(box, `Ответы до ${new Date(q.ends_at).toLocaleTimeString('ru-RU')}`);
                        q.options.forEach((option, index) => {
                            const choice = button(option, () => command('answer', {game_id: current.game_id, round_id: q.round_id, selected_option: index}));
                            choice.disabled = q.answered || q.closed;
                            box.append(choice);
                        });
                        if (q.answered) note(box, `${q.is_correct ? 'Верно!' : 'Неверно.'} Очки: ${q.points ?? '0'}`);
                        if (Number.isInteger(q.correct_option)) note(box, `Правильный ответ: ${q.options[q.correct_option]}`);
                        if (q.explanation) note(box, q.explanation);
                    }
                    if (room.role === 'owner') box.append(button('Остановить квиз', () => command('stop', {game_id: current.game_id, expected_revision: current.revision}), 'quiet'));
                }
                if (current?.scores?.length) {
                    box.append(el('h2', 'Очки этой партии'));
                    current.scores.forEach(player => note(box, `${player.name}: ${format(player.score)}`));
                }
                const terminal = current && ['finished', 'stopped', 'interrupted'].includes(current.status);
                const shownAnswer = lastAnswer || (terminal ? current.question : null);
                if (shownAnswer && (terminal || current?.question?.round_id !== shownAnswer.round_id)) {
                    const previous = el('section', undefined, 'card');
                    previous.append(el('h2', terminal ? 'Результат ответа' : 'Твой ответ на предыдущий вопрос'), el('p', shownAnswer.question));
                    note(previous, shownAnswer.answered ? `${shownAnswer.is_correct ? 'Верно!' : 'Неверно.'} Очки: ${shownAnswer.points ?? '0'}` : 'Вопрос завершён.');
                    if (Number.isInteger(shownAnswer.correct_option)) note(previous, `Правильный ответ: ${shownAnswer.options[shownAnswer.correct_option]}`);
                    if (shownAnswer.explanation) note(previous, shownAnswer.explanation);
                    content.append(previous);
                }
                roomClassicTimer = setTimeout(refresh, 3000);
            } catch (error) {
                if (!active()) return;
                rendered = undefined;
                content.replaceChildren();
                note(content, error.message, 'error');
                content.append(button('Повторить', refresh));
            }
        };
        await refresh();
    }

    // Shared by the room list and the Night City lobby: expiry/uses pickers (unless compact) plus
    // the button that issues a one-time invite code and shows it with a copy button.
    function inviteIssuer(room, {mount, afterIssue, compact = false}) {
        const controls = el('div', undefined, 'guest-invite-controls');
        const expiry = el('select'); expiry.setAttribute('aria-label', 'Срок действия кода');
        for (const [seconds, text] of [[3600, '1 час'], [86400, '1 день'], [604800, '7 дней'], [2592000, '30 дней']]) {
            const option = el('option', text); option.value = String(seconds); expiry.append(option);
        }
        expiry.value = '86400';
        const uses = el('select'); uses.setAttribute('aria-label', 'Число приглашённых');
        for (const count of [1, 2, 5, 10, 25, 100]) {
            const option = el('option', String(count)); option.value = String(count); uses.append(option);
        }
        uses.value = '5';
        const issue = button(compact ? 'Позвать друзей' : 'Создать код', async event => {
            event.currentTarget.disabled = true;
            try {
                const created = await guestRequest(`/api/guest/rooms/${encodeURIComponent(room.id)}/invites`, 'POST', {
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({expires_in_seconds: Number(expiry.value), max_uses: Number(uses.value)}),
                });
                const codeBox = el('div', undefined, 'guest-invite-created');
                codeBox.append(el('span', `Код действует до ${new Date(created.expires_at).toLocaleString('ru-RU')}. Отправь его только приглашённым игрокам.`, 'muted'));
                const code = el('input'); code.type = 'text'; code.readOnly = true; code.value = created.invite_code;
                code.setAttribute('aria-label', 'Одноразово показанный код приглашения');
                const copy = button(compact ? 'Скопировать' : 'Скопировать код', async () => {
                    try {
                        if (!navigator.clipboard?.writeText) throw new Error('clipboard unavailable');
                        await navigator.clipboard.writeText(code.value);
                        feedback.textContent = 'Код скопирован. Его можно отправить друзьям.';
                    } catch { code.focus(); code.select(); feedback.textContent = 'Код выделен — скопируй его вручную.'; }
                }, 'quiet');
                codeBox.append(code, copy); mount(codeBox);
                if (afterIssue) await afterIssue();
            } catch (error) { feedback.textContent = error.message; }
            finally { event.currentTarget.disabled = false; }
        }, 'quiet');
        if (compact) controls.append(issue); else controls.append(expiry, uses, issue);
        return controls;
    }

    async function openGuestMafia(room) {
        stopRoomClassic();
        const version = ++generation;
        window.QuizPlay?.stop();
        nav.hidden = true; state.page = 'guest-mafia'; feedback.textContent = ''; content.replaceChildren(); content.dataset.page = 'guest-mafia';
        // Night City is a game inside /app: own header, no tab bar. Back: Telegram BackButton, ⚙ → «Главное меню».
        shell({game: true, onHome: () => guestHome()});
        try { await mafia(version, room); }
        catch (error) { if (version === generation) { note(content, error.message, 'error'); content.append(button('Повторить', () => openGuestMafia(room))); } }
    }
    // One persistent header row for Night City (the page re-renders on every poll; ⚙ is mounted once).
    let gameBar = null, gameBarTitle = null;
    function mafiaBar(title) {
        if (!gameBar) {
            gameBar = el('header', undefined, 'game-bar'); const box = el('div', undefined, 'game-bar-title');
            gameBarTitle = el('h1'); box.append(el('small', 'Ночной город · Дело 01'), gameBarTitle);
            gameBar.append(box); QW.header.mountGear(gameBar);
        }
        gameBarTitle.textContent = title; return gameBar;
    }
    const telegramMafiaRequest = request;
    const telegramMafiaNavigate = navigate;
    const guestMafiaCommands = new Map();
    async function mafia(version, room = null) {
        let pendingCommand = room ? guestMafiaCommands.get(room.id) || null : null;
        const showPending = message => {
            if (version !== generation) return;
            feedback.replaceChildren(el('span', message + ' '), button('Проверить / повторить', async () => {
                const command = pendingCommand;
                if (!command) return;
                try {
                    await guestRequest(command.endpoint, 'POST', {headers: {'Content-Type': 'application/json', 'Idempotency-Key': command.id}, body: command.body});
                    pendingCommand = null; guestMafiaCommands.delete(room.id);
                    await navigate('mafia');
                } catch (error) {
                    if (error.status && error.status < 500) { pendingCommand = null; guestMafiaCommands.delete(room.id); if (version === generation) { feedback.textContent = error.message; await navigate('mafia'); } }
                    else showPending(error.message);
                }
            }, 'quiet'));
        };
        const request = room ? async (path, options = {}) => {
            const endpoint = path;
            if (!options.method || options.method === 'GET') return guestRequest(endpoint);
            const body = options.body || '{}';
            if (pendingCommand && (pendingCommand.endpoint !== endpoint || pendingCommand.body !== body)) throw new Error('Сначала повтори предыдущее действие, чтобы узнать его результат.');
            if (!pendingCommand) { pendingCommand = {endpoint, body, id: crypto.randomUUID()}; guestMafiaCommands.set(room.id, pendingCommand); }
            try {
                const result = await guestRequest(endpoint, 'POST', {headers: {'Content-Type': 'application/json', 'Idempotency-Key': pendingCommand.id}, body});
                pendingCommand = null; guestMafiaCommands.delete(room.id); return result;
            } catch (error) {
                if (error.status && error.status < 500) { pendingCommand = null; guestMafiaCommands.delete(room.id); }
                else showPending(error.message);
                throw error;
            }
        } : telegramMafiaRequest;
        const navigate = page => version !== generation ? undefined : room ? (page === 'mafia' ? openGuestMafia(room) : guestHome()) : telegramMafiaNavigate(page);
        const group = room || state.chats.find(chat => ['group', 'supergroup'].includes(chat.type));
        const base = room ? `/api/guest/rooms/${encodeURIComponent(room.id)}/mafia` : group ? `/api/mini/mafia/chats/${group.chat_id}` : null;
        const draft = room ? {title: 'Ночной город'} : await request('/api/mini/mafia/draft');
        let lobbyData = null;
        if (group) {
            try { lobbyData = await request(`${base}/lobby`); }
            catch (error) { if (version === generation) feedback.textContent = error.message; }
        }
        if (version !== generation) return;
        if (pendingCommand) showPending('Действие могло быть принято. Проверь его результат.');
        content.append(mafiaBar(draft.title));
        const top = el('section', undefined, 'mafia-case');
        const image = el('img'); image.src = '/app/mafia.webp'; image.alt = 'Филиныч в капюшоне у стола детектива';
        const copy = el('div', undefined, 'mafia-case-copy');
        note(copy, room ? 'Собери друзей за столом. Город засыпает, а ваше дело продолжается.' : 'Собери состав стола. Черновик сохранится и не влияет на очки квиза.');
        top.append(image, copy); content.append(top);
        if (!room) {
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
                } catch (error) { if (version === generation) { if (!pendingCommand) feedback.textContent = error.message; event.currentTarget.disabled = false; } }
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
        }
        if (room && room.role === 'owner') {
            const invite = el('section', undefined, 'card mafia-invite');
            invite.append(el('h2', 'Позвать друзей'));
            note(invite, 'Друзья вводят код в разделе «Войти по приглашению».', 'muted');
            const issued = el('div', undefined, 'mafia-invite-code');
            invite.append(inviteIssuer(room, {compact: true, mount: codeBox => issued.replaceChildren(codeBox)}), issued);
            content.append(invite);
        }
        const table = el('section', undefined, 'card mafia-table');
        table.append(el('h2', 'Стол игроков'));
        if (!group) note(table, 'Для лобби нужен групповой чат, где бот может видеть участников. В личной игре пока доступен только черновик ролей.', 'muted');
        else if (!lobbyData) note(table, 'Не удалось прочитать лобби этого чата.');
        else if (!lobbyData.lobby) {
            note(table, `Создай лобби в «${group.title}». Никого автоматически не добавляем.`);
            if (!room || room.role === 'owner') table.append(button('Создать лобби', async event => {
                event.currentTarget.disabled = true;
                try { await request(`${base}/${room ? 'lobby' : 'lobby/join'}`, {method: 'POST'}); if (version === generation) await navigate('mafia'); }
                catch (error) { if (version === generation) { if (!pendingCommand) feedback.textContent = error.message; event.currentTarget.disabled = false; } }
            }, 'primary'));
            else note(table, 'Владелец комнаты скоро соберёт стол.');
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
                try { await request(`${base}/lobby/join`, {method: 'POST'}); await navigate('mafia'); }
                catch (error) { if (version === generation) { if (!pendingCommand) feedback.textContent = error.message; event.currentTarget.disabled = false; } }
            }, 'primary'));
            else if (lobby.status !== 'lobby') {
                const roleCard = el('section', undefined, 'mafia-role-card');
                try {
                    const role = await request(`${base}/role`);
                    const phaseTitle = {night: `НОЧЬ ${role.round}`, day: `ДЕНЬ ${role.round}`, voting: 'ГОРОД ГОЛОСУЕТ', finished: 'ДЕЛО ЗАКРЫТО'}[role.phase] || role.phase;
                    roleCard.append(el('span', phaseTitle, 'eyebrow'), el('strong', role.title));
                    if (!role.alive) note(roleCard, gm('Ты выбыл из дела, но можешь наблюдать за общим ходом.', 'Ты выбыла из дела, но можешь наблюдать за общим ходом.', 'Для тебя дело закончено, но можно наблюдать за общим ходом.'), 'muted');
                    else if (role.investigation) note(roleCard, `Проверка ${role.investigation.seat}: ${role.investigation.is_mafia ? 'это мафия' : 'не мафия'}.`, 'mafia-next');
                    if (role.phase === 'night' && role.alive) {
                        if (role.role === 'citizen') note(roleCard, 'Город спит. Дождись итогов ночи.');
                        else if (role.acted) note(roleCard, 'Твой выбор принят. Ведущий продолжит, когда все роли сделают ход.', 'mafia-next');
                        else {
                            note(roleCard, role.role === 'mafia' ? 'Выбери ночную цель.' : role.role === 'doctor' ? 'Кого защитить этой ночью?' : 'Кого проверить?');
                            const targets = el('div', undefined, 'mafia-targets');
                            for (const target of role.targets || []) targets.append(button(target.name, async event => {
                                event.currentTarget.disabled = true;
                                try { await request(`${base}/action`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({target: target.seat, expected_revision: lobby.phase_revision})}); await navigate('mafia'); }
                                catch (error) { if (version === generation) { if (!pendingCommand) feedback.textContent = error.message; event.currentTarget.disabled = false; } }
                            }));
                            roleCard.append(targets);
                        }
                    } else if (role.phase === 'day') note(roleCard, 'Обсудите события ниже. Ведущий откроет голосование, когда город будет готов.');
                    else if (role.phase === 'voting' && role.alive) {
                        if (role.voted) note(roleCard, 'Голос принят. Ждём остальных игроков.', 'mafia-next');
                        else {
                            note(roleCard, 'Кого город должен вывести из игры?');
                            const targets = el('div', undefined, 'mafia-targets');
                            for (const target of role.targets || []) targets.append(button(target.name, async event => {
                                event.currentTarget.disabled = true;
                                try { await request(`${base}/vote`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({target: target.seat, expected_revision: lobby.phase_revision})}); await navigate('mafia'); }
                                catch (error) { if (version === generation) { if (!pendingCommand) feedback.textContent = error.message; event.currentTarget.disabled = false; } }
                            }));
                            roleCard.append(targets);
                        }
                    } else if (role.phase === 'finished') note(roleCard, role.winner === 'citizens' ? 'Город победил. Мафия раскрыта.' : 'Мафия подчинила Ночной город.', 'mafia-next');
                } catch (error) { roleCard.append(el('p', error.message)); }
                if (version !== generation) return;
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
                        try { await request(`${base}/advance`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({expected_revision: lobby.revision})}); await navigate('mafia'); }
                        catch (error) { if (version === generation) { if (!pendingCommand) feedback.textContent = error.message; event.currentTarget.disabled = false; } }
                      }, 'primary'));
                  }
                  if (lobby.status === 'finished' && lobby.is_host) table.append(button('Собрать реванш', async event => {
                      event.currentTarget.disabled = true;
                      try { await request(`${base}/restart`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({expected_revision: lobby.revision})}); await navigate('mafia'); }
                      catch (error) { if (version === generation) { if (!pendingCommand) feedback.textContent = error.message; event.currentTarget.disabled = false; } }
                  }, 'primary'));
            } else {
                const mine = lobby.players.find(player => player.is_me);
                table.append(button(mine?.ready ? gm('Я не готов', 'Я не готова', 'Снять готовность') : gm('Я готов', 'Я готова', 'Отметить готовность'), async event => {
                    event.currentTarget.disabled = true;
                    try { await request(`${base}/lobby/ready`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ready: !mine?.ready, expected_revision: lobby.revision})}); await navigate('mafia'); }
                    catch (error) { if (version === generation) { if (!pendingCommand) feedback.textContent = error.message; event.currentTarget.disabled = false; } }
                }, mine?.ready ? 'quiet' : 'primary'));
                if (lobby.can_start) {
                    note(table, 'Стол собран. Роли будут выданы каждому игроку приватно.', 'mafia-next');
                    if (lobby.is_host) table.append(button('Начать ночь', async event => {
                        event.currentTarget.disabled = true;
                        try { await request(`${base}/lobby/start`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({expected_revision: lobby.revision})}); await navigate('mafia'); }
                        catch (error) { if (version === generation) { if (!pendingCommand) feedback.textContent = error.message; event.currentTarget.disabled = false; } }
                    }, 'primary'));
                }
                else note(table, `До старта нужно минимум 4 готовых игрока. Сейчас готово: ${lobby.players.filter(player => player.ready).length}.`, 'muted');
            }
        }
        content.append(table);
        if (group && lobbyData?.lobby?.joined) {
            const discussion = el('section', undefined, 'card mafia-discussion');
            discussion.append(el('h2', 'Обсуждение'));
            note(discussion, 'Сообщения видны участникам стола. Писать можно во время сбора игроков и дневной фазы.');
            try {
                const feed = await request(`${base}/discussion`);
                if (version !== generation) return;
                if (!feed.items?.length) note(discussion, 'Пока тихо. Начните разговор здесь.', 'muted');
                for (const message of feed.items || []) {
                    const item = el('article', undefined, `mafia-message ${message.is_me ? 'mine' : ''}`);
                    item.append(el('strong', message.author), el('p', message.message));
                    if (message.created_at) item.append(el('time', new Date(message.created_at).toLocaleString('ru-RU')));
                    discussion.append(item);
                }
                if (feed.enabled) {
                    const input = el('textarea'); input.maxLength = 1000; input.rows = 3;
                    input.placeholder = 'Напиши участникам стола…'; input.setAttribute('aria-label', 'Сообщение участникам стола');
                    discussion.append(input);
                    discussion.append(button('Отправить', async event => {
                        const message = input.value;
                        if (!message.trim()) { feedback.textContent = 'Напиши сообщение перед отправкой.'; return; }
                        event.currentTarget.disabled = true;
                        const commandId = globalThis.crypto?.randomUUID?.() || `web-${Date.now()}-${Math.random().toString(16).slice(2)}`;
                        try {
                            await request(`${base}/discussion`, {
                                method: 'POST', headers: {'Content-Type': 'application/json', 'Idempotency-Key': commandId},
                                body: JSON.stringify({message}),
                            });
                            await navigate('mafia');
                        } catch (error) { if (version === generation) { if (!pendingCommand) feedback.textContent = error.message; event.currentTarget.disabled = false; } }
                    }, 'primary'));
                } else note(discussion, 'Новая переписка сейчас закрыта до начала следующей дневной фазы.', 'muted');
            } catch (error) { note(discussion, error.message, 'error'); }
            if (version !== generation) return;
            content.append(discussion);
        }
        if (version !== generation) return;
        const boundary = el('section', undefined, 'mafia-boundary');
        boundary.append(el('h2', 'Полный ход дела'), el('p', 'Лобби, тайные роли, ночные действия, обсуждение, голосование, выбывание и победа сохраняются в общей партии.'));
          if (!room) boundary.append(el('h2', 'Ещё предстоит'), el('p', 'Живая проверка большого стола в отдельной тестовой Telegram-группе.'));
          content.append(boundary);
          if (!pendingCommand && (room || (lobbyData?.lobby && !['lobby', 'finished'].includes(lobbyData.lobby.status)))) {
              const poll = () => {
                  if (generation !== version || state.page !== (room ? 'guest-mafia' : 'mafia')) return;
                  if (pendingCommand || content.querySelector('textarea')?.value) { setTimeout(poll, 5000); return; }
                  navigate('mafia');
              };
              setTimeout(poll, 5000);
          }
    }
    // Chat page: segments «Играть · Рейтинг · Статистика · Настройки». Settings are editable for admins and read-only for others.
    function scheduleCard(details) {
        const schedule = el('article', undefined, 'card'); schedule.append(el('h2', 'Следующая встреча'));
        const times = (details.daily.times_msk || []).map(t => `${String(t.hour).padStart(2, '0')}:${String(t.minute).padStart(2, '0')}`).join(', ');
        note(schedule, details.daily.enabled ? `Ежедневный квиз: ${times || 'время не задано'} · ${details.daily.timezone || 'Europe/Moscow'}` : 'Ежедневный квиз пока не включён. Расписание настраивает администратор чата.');
        note(schedule, details.wisdom.enabled ? `Мудрость от Филиныча: ${details.wisdom.time || '09:00'} · ${details.wisdom.timezone}` : 'Мудрость дня выключена.');
        return schedule;
    }
    function categoriesCard(details) {
        const categories = el('article', undefined, 'card'); categories.append(el('h2', 'Темы этого чата'));
        const enabled = details.enabled_categories || [], disabled = details.disabled_categories || [], usage = details.category_usage || [];
        note(categories, enabled.length ? `Разрешены: ${enabled.join(', ')}` : 'Доступны категории банка с учётом настроек пула.');
        if (disabled.length) note(categories, `Исключены: ${disabled.join(', ')}`);
        if (usage.length) note(categories, usage.map(c => `${c.name}: ${c.uses}`).join(' · '));
        return categories;
    }
    async function chatHome(version) {
        if (!state.selected) { note(content, 'Пока нет чатов с твоим участием. Сыграй первый квиз в боте, затем обнови приложение.', 'empty'); return; }
        if (state.launchLost) note(content, 'Чат из ссылки недоступен — возможно, доступ к нему закрыт.', 'error');
        const tab = ['play', 'stats', 'settings'].includes(state.chatTab) ? state.chatTab : 'play';
        content.append(segmented([['play', 'Играть'], ['rating', 'Рейтинг'], ['stats', 'Статистика'], ['settings', 'Настройки']], tab, value => {
            if (value === 'rating') { window.QuizRating?.prefer({scope: 'chat', chatId: state.selected}); navigate('rating'); }
            else { state.chatTab = value; navigate('chat'); }
        }, 'Разделы чата'));
        let details, games;
        try { [details, games] = await Promise.all([request(`/api/mini/chats/${state.selected}/details`), request(`/api/mini/chats/${state.selected}/games`)]); }
        catch (error) {
            if (version !== generation) return;
            if (!isChatGone(error)) throw error;
            dropUnavailableChat(state.selected);
            note(content, 'Бот больше не в этом чате. Выбери другой чат или добавь бота обратно.', 'muted');
            if (state.selected) content.append(button('Открыть другой чат', () => navigate('chat'), 'secondary'));
            return;
        }
        if (version !== generation) return;
        if (tab === 'play') {
            const cards = el('section', undefined, 'cards');
            modeCard(cards, 'Классический квиз', `${details.classic.questions} вопросов · ${details.classic.seconds} секунд на ответ. Категории, анонс и паузы настраиваются в настройках чата.`, '/quiz', games.items.find(g => g.kind === 'classic'));
            modeCard(cards, 'Фото-загадки', 'Узнай, что на картинке. Пиши ответ в чат, используй подсказки и получай бонус за скорость.', '/photo_quiz', games.items.find(g => g.kind === 'photo'));
            content.append(cards, scheduleCard(details));
            if (details.telegram_url) {
                const link = el('a', 'Открыть этот чат в Telegram', 'qw-btn secondary'); link.href = details.telegram_url;
                link.addEventListener('click', event => { if (tg?.openTelegramLink) { event.preventDefault(); tg.openTelegramLink(details.telegram_url); } }); content.append(link);
            }
        } else if (tab === 'stats') {
            metrics(content);
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
            content.append(categoriesCard(details));
        } else await chatSettings(version, details);
    }
    async function chatSettings(version, details) {
        const target = state.chats.find(chat => chat.chat_id === state.selected);
        const game = el('section', undefined, 'card'); game.append(el('h2', 'Игра и расписание'));
        if (!runtimeEnabled || !target) {
            note(game, 'Изменение игровых параметров в этом preview отключено. В рабочем Mini App они сохраняются для выбранного чата.', 'muted');
            content.append(game, scheduleCard(details), categoriesCard(details)); return;
        }
        if (!details.can_edit) {
            note(game, 'Настройки меняют администраторы чата, ниже текущие значения. Чтобы изменить их, открой Mini App с Telegram-аккаунта администратора.', 'muted');
            content.append(game, scheduleCard(details), categoriesCard(details)); return;
        }
        const categoryData = await request('/api/mini/categories');
        if (version !== generation) return;
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
                await request(`/api/mini/chats/${target.chat_id}/preferences`, {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({
                    classic: {questions: Number(questions.value), seconds: Number(seconds.value), interval: Number(interval.value), announce: announce.checked,
                        announce_delay: Number(announceDelay.value), category_mode: classicCategories.mode.value,
                        categories: chosen(classicCategories), random_categories: Number(classicCategories.random.value)},
                    daily: {enabled: dailyEnabled.checked, times, timezone: dailyZone.value.trim(), questions: Number(dailyQuestions.value),
                        interval: Number(dailyInterval.value), seconds: Number(dailySeconds.value), category_mode: dailyCategories.mode.value,
                        categories: chosen(dailyCategories), random_categories: Number(dailyCategories.random.value)},
                    wisdom: {enabled: wisdomEnabled.checked, time: wisdomTime.value.trim()}, auto_delete: autoDelete.checked,
                    expected_revision: details.settings_revision,
                })});
                feedback.textContent = 'Параметры сохранены для этого чата и бота.'; await navigate('chat');
            } catch (error) { feedback.textContent = error.message; save.disabled = false; }
        };
        game.append(form);
        content.append(game);
    }
    function profile() {
        const me = state.me, grid = el('div', undefined, 'profile-grid');
        const card = el('section', undefined, 'card player-card'), avatar = el('span', initialOf(me.display_name), 'qw-avatar'), who = el('div', undefined, 'player-who');
        who.append(el('h1', me.display_name), el('small', 'Telegram · профиль QuizzyWizzy'));
        card.append(avatar, who, button('Настройки', () => navigate('settings'), 'secondary settings-open'));
        content.append(card);
        const stats = el('section', undefined, 'metrics profile-metrics'); stats.setAttribute('aria-label', 'Личный прогресс');
        for (const [value, label] of [[me.score, 'очков всего'], [me.answered_count, 'квиз-ответов'], [state.progress.correct_including_photo, 'правильных, включая фото'],
            [state.progress.current_streak, 'серия сейчас'], [state.progress.best_streak, 'рекорд серии'], [state.chats.length, 'чатов']]) {
            const item = el('div', undefined, 'metric'); item.append(el('strong', format(value)), el('span', label)); stats.append(item);
        }
        grid.append(stats);
        const summary = state.achievements?.summary, ach = el('section', undefined, 'card');
        const head = el('div', undefined, 'card-heading'); head.append(el('h2', 'Достижения'));
        if (summary) head.append(el('span', `${summary.earned} / ${summary.available}`, 'badge'));
        ach.append(head);
        if (!summary) note(ach, 'Достижения загружаются…', 'muted');
        else {
            note(ach, `Получено ${summary.earned} из ${summary.available}: ${summary.chat_achievements} за очки в чатах и ${summary.streak_achievements} за серии подряд.`);
            const recent = el('div');
            for (const chat of state.achievements.chats) for (const item of chat.items.filter(row => row.earned).slice(0, 2)) recent.append(el('span', item.title, 'achievement'));
            if (recent.childElementCount) ach.append(recent);
            const links = el('div', undefined, 'qw-btn-stack');
            links.append(button('Все достижения', () => navigate('achievements'), 'secondary'), button('История игр и ответов', () => navigate('history'), 'secondary'));
            ach.append(links);
        }
        grid.append(ach); content.append(grid);
        if (state.progress.last_activity) note(content, `Последняя активность: ${new Date(state.progress.last_activity).toLocaleString('ru-RU')}`);
        content.append(button('Обновить прогресс', load, 'text'));
    }
    // «Контрастный режим»: an Account setting for the hub and every game (UI_RULES §16). The shell applies it on this
    // device at once; the server keeps it for the other devices. channel: 'telegram' (Mini App session) | 'guest'.
    function contrastSetting(channel) {
        const wrap = el('div'), label = el('label', undefined, 'setting-row contrast-setting'), copy = el('span'), input = el('input');
        copy.append(el('strong', 'Контрастный режим'), el('small', 'Чётче текст, рамки и кнопки во всех играх. Хранится в профиле.'));
        input.type = 'checkbox'; input.name = 'contrast_mode'; input.setAttribute('role', 'switch');
        input.checked = Boolean(window.QW?.prefs?.get().contrast);
        const message = el('p', '', 'error'); message.hidden = true;
        input.addEventListener('change', async () => {
            const on = input.checked; input.disabled = true; message.hidden = true;
            window.QW?.prefs?.setContrast(on);
            try {
                const path = `/api/account/contrast-mode?identity=${channel}`, headers = {'Content-Type': 'application/json'}, body = JSON.stringify({enabled: on});
                const result = channel === 'guest'
                    ? await guestRequest(path, 'POST', {headers, body})
                    : await request(path, {method: 'POST', headers: {...headers, 'X-Guest-CSRF': '1'}, body});
                const profile = channel === 'guest' ? state.guest : state.me;
                if (profile) profile.contrast_mode = result.contrast_mode;
                window.QW?.prefs?.applyAccount(result);
                input.checked = Boolean(result.contrast_mode);
            } catch (error) {
                window.QW?.prefs?.setContrast(!on); input.checked = !on;
                message.textContent = error.message; message.hidden = false;
            } finally { input.disabled = false; }
        });
        label.append(copy, input); wrap.append(label, message); return wrap;
    }
    // Theme and haptics: per device, the same card for a Telegram player and a guest; the contrast mode follows the account.
    function appearanceCard(channel) {
        const preferences = el('section', undefined, 'card'); preferences.append(el('h2', 'Внешний вид'), el('p', 'Тема', 'field-label'));
        preferences.append(segmented([['system', 'Как в системе'], ['dark', 'Тёмная'], ['light', 'Светлая']], window.QuizTelegram.prefs.theme, value => window.QuizTelegram.setTheme(value), 'Тема оформления'));
        const haptics = button(window.QuizTelegram.prefs.haptics ? 'Тактильный отклик: вкл' : 'Тактильный отклик: выкл', () => { const enabled = window.QuizTelegram.toggleHaptics(); haptics.textContent = enabled ? 'Тактильный отклик: вкл' : 'Тактильный отклик: выкл'; haptics.setAttribute('aria-pressed', String(enabled)); }, 'secondary');
        haptics.setAttribute('aria-pressed', String(window.QuizTelegram.prefs.haptics)); preferences.append(haptics);
        preferences.append(contrastSetting(channel));
        return preferences;
    }
    // Notification preferences have one entry point: Profile → Settings, for both sign-in methods.
    function farmRequestNotificationsCard(identity) {
        const version = generation, account = (identity === 'guest' ? state.guest : state.me)?.account_id;
        const current = () => version === generation && account === (identity === 'guest' ? state.guest : state.me)?.account_id;
        const box = el('section', undefined, 'card farm-request-notifications');
        box.append(el('h2', 'Уведомления фермы'));
        const label = el('label', undefined, 'setting-row'), input = el('input');
        input.type = 'checkbox'; input.disabled = true; input.checked = true;
        label.append(el('span', 'Уведомления о просьбах соседей'), input);
        const message = el('p', 'Загрузка настройки…', 'muted'); box.append(label, message);
        const endpoint = `/api/farm/v1/me?identity=${identity}`;
        const farmRequest = (url, method = 'GET', body) => identity === 'guest'
            ? guestRequest(url, method, {headers: {'Content-Type': 'application/json', 'X-QW-Farm': '1'}, ...(body ? {body: JSON.stringify(body)} : {})})
            : request(url, {method, headers: {'Content-Type': 'application/json', 'X-QW-Farm': '1'}, ...(body ? {body: JSON.stringify(body)} : {})});
        farmRequest(endpoint).then(result => {
            if (!current()) return;
            input.checked = result.farm.settings.notify_requests !== false; input.disabled = false;
            message.textContent = 'Сводка в Telegram — раз в день; посылки — не чаще раза в час. Карточки и журнал остаются в игре.';
        }).catch(error => { if (current()) message.textContent = error.status === 404 ? 'Настройка станет доступна после начала игры на ферме.' : error.message; });
        input.addEventListener('change', async () => {
            const checked = input.checked; input.disabled = true;
            try {
                const {farm} = await farmRequest(endpoint); if (!current()) return;
                const commandId = globalThis.crypto?.randomUUID?.();
                if (!commandId) throw new Error('Обнови браузер для безопасного сохранения настройки.');
                const data = {name: farm.name, visibility: farm.settings.visibility, notify_requests: checked};
                for (const key of ['allow_help', 'allow_gifts', 'allow_pranks', 'allow_trade', 'allow_requests']) data[key] = farm.settings[key] !== false;
                await farmRequest(`/api/farm/v1/commands?identity=${identity}`, 'POST', {actor: farm.id, target: null, command_id: commandId, kind: 'settings', data});
                if (current()) message.textContent = 'Настройка сохранена.';
            } catch (error) { if (current()) { input.checked = !checked; message.textContent = error.message; } }
            finally { if (current()) input.disabled = false; }
        });
        return box;
    }
    // «Профиль → Настройки»: only the account (UI_RULES §11). Game and schedule settings live on the chat page.
    async function settings() {
        content.append(el('span', 'Профиль / Настройки', 'eyebrow settings-path'), el('h1', 'Настройки'));
        content.append(addressSection('telegram', state.me));
        const via = el('section', undefined, 'card login-card'); via.append(el('h2', 'Вход'));
        const row = el('div', undefined, 'setting-row'), copy = el('div'); copy.append(el('strong', 'Telegram'), el('small', `${state.me.display_name} · привязан`));
        row.append(copy, el('span', '✓', 'badge')); via.append(row);
        content.append(via, devicesSection('telegram'));
        content.append(appearanceCard('telegram'), farmRequestNotificationsCard('telegram'));
        const actions = el('div', undefined, 'qw-danger-zone'); actions.append(button('Выйти', async () => {
            try { await request('/api/mini/session', {method: 'DELETE'}); clearTimeout(renewTimer); state.authenticated = false; state.me = null; state.page = 'home';
                try { localStorage.setItem('mqb-telegram-logged-out', '1'); } catch {}
                loginScreen(); }
            catch (error) { feedback.textContent = error.message; }
        }, 'danger')); content.append(actions);
    }
    function chats() {
        content.append(el('p', 'Чаты, где ты играешь с ботом. Рейтинг, статистика и расписание — внутри каждого.', 'muted'));
        if (!state.chats.length) {
            note(content, 'Запусти /start в личном чате с ботом или добавь его в группу. После этого выбери появившийся чат — квиз и фото-загадки можно будет запускать прямо здесь.', 'empty');
            if (state.botUsername) content.append(button('Открыть бота', () => openBotHome(), 'primary'));
        }
        for (const chat of state.chats) {
            const item = el('article', undefined, 'card chat-card'), head = el('div', undefined, 'card-heading'), own = chat.own_statistics || {};
            head.append(el('h2', chat.title));
            if (typeof chat.can_edit === 'boolean') head.append(el('span', chat.can_edit ? 'админ' : 'участник', chat.can_edit ? 'badge admin' : 'badge'));
            item.append(head);
            const facts = [`${format(own.score ?? 0)} очков`];
            if (own.rank != null) facts.push(own.members != null ? `№${own.rank} из ${own.members}` : `№${own.rank}`);
            if (own.streak != null) facts.push(`серия ${own.streak}`);
            if (own.best_streak != null) facts.push(`рекорд ${own.best_streak}`);
            note(item, facts.join(' · '));
            item.append(button('Открыть игры и расписание', () => { state.selected = chat.chat_id; state.chatTab = 'play'; navigate('chat'); }, 'primary')); content.append(item);
        }
        if (state.moreChats) content.append(button('Ещё чаты', async event => {
            const trigger = event.currentTarget; trigger.disabled = true;
            try { const result = await request(`/api/mini/chats?limit=50&offset=${state.chatOffset}`); state.chats.push(...result.items); state.chatOffset += result.items.length; state.moreChats = result.has_more; navigate('chats'); }
            catch (error) { feedback.textContent = error.message; trigger.disabled = false; }
        }, 'secondary'));
        if (state.chats.length && state.botUsername) content.append(button('Добавить бота в чат', () => openBotHome(), 'secondary'));
    }
    // Rating: one account ranking for guests and Telegram players alike; the UI lives in rating-ui.js.
    async function rating(version) {
        const identity = state.authenticated ? 'telegram' : state.guest ? 'guest' : '';
        await window.QuizRating.render({content, el, button, note, segmented, format, identity,
            isCurrent: () => version === generation,
            onError: error => { if (error.status === 401) loginScreen(error.message); else feedback.textContent = error.message; },
            onProfile: () => (state.authenticated ? navigate('profile') : guestProfile())});
    }
    async function guestRating() {
        stopRoomClassic(); generation++; window.QuizPlay?.stop(); showGuestTab('rating');
        feedback.textContent = ''; content.replaceChildren(); content.dataset.page = 'rating'; shell({page: 'rating'});
        await rating(generation);
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
            const goal = alchemy.daily_goal || {target: 10, progress: alchemy.points_today || 0, done: false};
            card.append(el('h2', 'Атлас маленьких чудес'));
            note(card, `Коллекция: ${alchemy.discovered} элементов · рейтинг: ${alchemy.verified_discovered ?? 0} · подтверждено глав ${alchemy.verified_chapters ?? 0} и достижений ${alchemy.verified_achievements ?? 0}`);
            note(card, `Очки из Алхимии: ${format(alchemy.points_total)} · место ${alchemy.rank} из ${alchemy.total_players}`);
            note(card, goal.done
                ? `Цель дня выполнена: ${format(goal.progress)} из ${format(goal.target)} очков.`
                : `Цель дня: ${format(goal.progress)} из ${format(goal.target)} очков, осталось ${format(Math.max(0, goal.target - goal.progress))}.`);
            if (goal.streak > 0) {
                const days = n => `${n} ${n % 10 === 1 && n % 100 !== 11 ? 'день' : [2, 3, 4].includes(n % 10) && ![12, 13, 14].includes(n % 100) ? 'дня' : 'дней'}`;
                note(card, goal.done
                    ? `Серия: ${days(goal.streak)} подряд с закрытой целью.`
                    : `Серия: ${days(goal.streak)}. Закрой цель дня, чтобы её продолжить.`);
            }
            note(card, (alchemy.remaining_today ?? 0) > 0
                ? `Сегодня можно набрать ещё ${format(alchemy.remaining_today)} очков.`
                : 'Суточный лимит выбран: новые очки начислятся завтра.', 'muted');
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
        if (!data.chats.length) note(content, gm('Ты пока не играл в чатах.', 'Ты пока не играла в чатах.', 'Пока нет сыгранных партий в чатах.'), 'empty');
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
        note(content, 'В рейтинг входят только открытия, подтверждённые сервером. Старые и офлайн-сохранения остаются в коллекции, но сами по себе не дают место в рейтинге.');
        const list = el('section', undefined, 'card');
        if (!data.items.length) note(list, 'Пока никто не открыл ни одного элемента.', 'empty');
        else for (const row of data.items) list.append(el('p', `${row.rank}. ${row.display_name}${row.is_me ? ' — это ты' : ''} · ${row.discovered}`, row.is_me ? '' : 'muted'));
        content.append(list);
        content.append(button('Обновить', () => navigate('alchemy-top'), 'quiet'));
    }
    async function navigate(page) {
        stopRoomClassic();
        if (!state.authenticated) { if (state.guest) guestNavigate(page); else loginScreen(); return; }
        window.QuizPlay?.stop();
        window.QuizPlay?.stop();
        window.QuizTelegram.selection();
        state.page = page; const version = ++generation; feedback.textContent = ''; content.replaceChildren(); content.dataset.page = page;
        const tab = page.startsWith('settings') || page === 'achievements' || page === 'history' || page === 'alchemy-top' ? 'profile' : page === 'play' ? 'home' : page === 'chat' ? 'chats' : page;
        nav.querySelectorAll('button').forEach(node => { if (node.dataset.page === tab) node.setAttribute('aria-current', 'page'); else node.removeAttribute('aria-current'); });
        if (page === 'mafia') shell({game: true, onHome: () => navigate('home')});
        else {
            const chatTitle = state.chats.find(chat => chat.chat_id === state.selected)?.title;
            shell({page, title: page === 'play' ? (playCommand === '/photo_quiz' ? 'Фото-загадки' : 'Классический квиз')
                : page === 'chat' ? chatTitle || 'Чат' : undefined});
        }
        try {
            if (page === 'home') await home(version);
            else if (page === 'play') {
                const command = playCommand; playCommand = null;
                if (!state.selected) { noChatPlay(); return; }
                if (![null, '/quiz', '/photo_quiz'].includes(command)) {
                    throw new Error('Для этого игрового режима ещё нет прямого подключения. Выбери квиз, фото-загадки или Ночной город.');
                }
                if (!window.QuizPlay) throw new Error('Игровой экран не загрузился. Обнови приложение.');
                await window.QuizPlay.mount({host: content, request, command, chatId: state.selected, settings: false, onReplay: cmd => play(cmd), onProfile: () => { state.page = 'profile'; load(); }, onSettings: () => openChatSettings(), onHome: () => { state.page = 'home'; load(); }, selection: () => window.QuizTelegram.selection(), media: async path => {
                    const response = await fetch(path, {credentials: 'same-origin'});
                    if (!response.ok) throw new Error('Фото недоступно'); return response.blob();
                }});
            }
            else if (page === 'chat') await chatHome(version);
            else if (page === 'profile') profile();
            else if (page === 'achievements') await achievementsPage(version);
            else if (page === 'alchemy-top') await alchemyTop(version);
            else if (page === 'history') await historyPage(version);
            else if (page === 'settings') await settings();
            else if (page === 'help') help();
            else if (page === 'chats') chats();
            else if (page === 'mafia') await mafia(version);
            else await rating(version);
        } catch (error) {
            if (version !== generation) return;
            if (!state.authenticated) loginScreen(error.message);
            else { note(content, error.message, 'error'); content.append(button('Повторить', () => navigate(page))); }
        }
    }
    nav.querySelectorAll('button').forEach(node => node.addEventListener('click', () => navigate(node.dataset.page)));
    brandLink?.addEventListener('click', event => { if (state.authenticated) { event.preventDefault(); navigate('home'); } });
    configureTelegram();
    request('/api/mini/config').catch(() => null).then(config => {
        state.botUsername = config?.bot_username || '';
        state.gameModes = Array.isArray(config?.game_modes) ? config.game_modes : [];
        runtimeEnabled = config?.runtime_enabled === true;
        roomClassicEnabled = config?.room_classic_enabled === true;
        roomPhotoEnabled = config?.room_photo_enabled === true;
        guestAllowed = config?.guest_enabled ?? config?.private_test !== true;
        return config?.offline ? request('/api/dev/info').catch(() => null) : null;
    }).then(async info => {
        await telegramReady;
        state.demo = info?.demo === true;
        if (state.demo) { const banner = document.getElementById('environment'); banner.hidden = false; banner.textContent = info?.synthetic_player ? 'DEV · Тестовый игрок. Без отправки сообщений в Telegram.' : 'DEV · Просмотр твоего профиля из локальной БД.'; }
        if ((state.gameModes || []).some(mode => mode.id === 'farm' && mode.status === 'development') && farmLaunchHint()) {
            await bootstrapFarmInvite().catch(error => bootstrapError(error, bootstrapFarmInvite));
            return;
        }
        await bootstrapEntry().catch(error => bootstrapError(error, bootstrapEntry));
    });
})();
