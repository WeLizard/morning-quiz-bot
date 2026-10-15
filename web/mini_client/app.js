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
    const state = {authenticated: false, guest: null, demo: false, page: launch?.page || 'home', selected: launch?.chatId || '', launchLost: false, me: null, progress: null, chats: [], chatOffset: 0, moreChats: false, botUsername: '', gameModes: []};
    let generation = 0, playCommand = null, runtimeEnabled = false, guestAllowed = true, roomClassicEnabled = false, roomPhotoEnabled = false;
    let roomPhotoDispose = null, roomPhotoPending = null;
    const stopRoomPhoto = () => { const dispose = roomPhotoDispose; roomPhotoDispose = null; dispose?.(); };
    let roomClassicTimer = null;
    const roomClassicCommands = new Map();
    const stopRoomClassic = () => { clearTimeout(roomClassicTimer); roomClassicTimer = null; stopRoomPhoto(); };
    window.addEventListener?.('pagehide', stopRoomClassic);
    const el = (tag, text, cls) => { const node = document.createElement(tag); if (text !== undefined) node.textContent = text; if (cls) node.className = cls; return node; };
    const button = (label, action, cls = '') => { const node = el('button', label, cls); node.type = 'button'; node.addEventListener('click', action); return node; };
    const format = value => new Intl.NumberFormat('ru-RU', {maximumFractionDigits: 3}).format(Number(value));
    const note = (parent, text, cls = 'muted') => parent.append(el('p', text, cls));
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
                const error = new Error(typeof data.detail === 'string' ? data.detail : 'Не удалось выполнить запрос.'); error.status = response.status; throw error;
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
            if (!response.ok) { const error = new Error(typeof data.detail === 'string' ? data.detail : 'Не удалось выполнить запрос.'); error.status = response.status; throw error; }
            return data;
        } catch (error) {
            if (error.name === 'AbortError' || error instanceof TypeError) throw new Error('Нет связи с приложением. Проверь подключение и повтори.');
            throw error;
        } finally { clearTimeout(timeout); options.signal?.removeEventListener('abort', abort); }
    }
    // An invitation is a navigation hint. Only the server session identifies the player.
    function farmLaunchHint() {
        const uuid = /^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i;
        const query = typeof location !== 'undefined' ? new URLSearchParams(location.search) : new URLSearchParams();
        const explicit = query.get('invite') || query.get('tgWebAppStartParam') || query.get('startapp') || '';
        let raw = explicit || tg?.initDataUnsafe?.start_param || '';
        try { raw = raw || sessionStorage.getItem('qw-farm.incoming') || ''; } catch {}
        if (raw.startsWith('farm_')) raw = raw.slice(5);
        if (!uuid.test(raw)) return null;
        const id = raw.toLowerCase();
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
        generation++; nav.hidden = true; feedback.textContent = ''; content.replaceChildren();
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
        generation++; nav.hidden = true; feedback.textContent = ''; content.replaceChildren();
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
    function addressChooser(current, onPick) {
        const group = el('div', undefined, 'address-choice'), message = el('p', '', 'error'); message.hidden = true;
        group.setAttribute('role', 'radiogroup'); group.setAttribute('aria-label', 'Как к тебе обращаться');
        let value = current;
        const options = ADDRESS.FORMS.map(code => {
            const node = el('button', ADDRESS_TITLES[code]); node.type = 'button'; node.dataset.form = code;
            node.setAttribute('role', 'radio');
            node.addEventListener('click', async () => {
                if (code === value) return;
                options.forEach(option => { option.disabled = true; }); message.hidden = true;
                try { await onPick(code); value = code; }
                catch (error) { message.textContent = error.message; message.hidden = false; }
                finally { options.forEach(option => { option.disabled = false; }); paint(); }
            });
            return node;
        });
        const paint = () => options.forEach(node => {
            const on = node.dataset.form === value;
            node.setAttribute('aria-checked', String(on)); node.classList.toggle('selected', on);
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
    // Шаг при первом входе: его можно пропустить («Не указывать» тоже запоминается, повторно не спрашиваем).
    function addressPrompt(channel, profile) {
        if (!profile || profile.address_form_chosen) return null;
        const card = el('section', undefined, 'card address-card');
        card.append(el('span', 'Знакомство', 'eyebrow'), el('h2', 'Как к тебе обращаться?'));
        note(card, 'Чтобы игры говорили правильно: «собрал» или «собрала». Telegram пол не сообщает, поэтому мы не угадываем. Можно пропустить и поменять потом в настройках.');
        card.append(addressChooser(null, async code => { await saveAddressForm(channel, code); card.hidden = true; }));
        return card;
    }
    function addressSection(channel, profile) {
        const card = el('section', undefined, 'card address-card');
        card.append(el('h2', 'Как к тебе обращаться'));
        note(card, 'Игры будут говорить о тебе в нужной форме: «собрал» или «собрала». Выбор общий для приложения, Telegram и фермы.');
        card.append(addressChooser(profile?.address_form_chosen ? profile.address_form : null, code => saveAddressForm(channel, code)));
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
        if (registering) note(form, 'Сохрани пароль: его сброс пока недоступен. Telegram можно связать с этим профилем внутри Telegram.', 'notice warn');
        let pickedForm = null;
        if (registering && !state.guest?.address_form_chosen) {
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
    async function guestHome() {
        stopRoomClassic();
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
        window.QuizPlay?.stop(); nav.hidden = true; feedback.textContent = ''; content.replaceChildren(); content.dataset.page = 'guest';
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
        const box = el('section', undefined, 'card profile-card');
        const saved = Boolean(state.guest?.login);
        const profileTitle = el('h1', state.guest?.display_name || 'Гость');
        box.append(el('span', saved ? 'Профиль' : 'Гостевой профиль', 'eyebrow'), profileTitle);
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
                await guestHome();
            } catch (error) {
                if (version !== generation) return;
                nameMessage.textContent = error.message; nameMessage.hidden = false; saveName.disabled = false;
            }
        });
        if (saved) {
            note(box, gm(`Ты вошёл как «${state.guest.login}». `, `Ты вошла как «${state.guest.login}». `, `Вход выполнен как «${state.guest.login}». `) + 'Прогресс привязан к логину, войти можно с любого браузера.');
            note(box, 'Сброс забытого пароля пока недоступен. Связанный Telegram даёт ещё один способ входа в этот профиль.', 'muted');
        } else {
            note(box, 'Открытия «Алхимии» сохраняются в приложении. Войти снова можно в этом браузере, пока действует гостевая сессия.');
            note(box, state.guest?.telegram_user_id
                ? 'Telegram связан с этим профилем. Через него можно снова открыть ту же ферму и прогресс.'
                : 'Если очистить данные браузера или выйти, доступ к этому профилю будет потерян. Сохрани логин и пароль или свяжи Telegram в этом окне.', 'muted');
        }
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
            }, 'primary');
            box.append(link, linkMessage, linkPanel);
        } else if (!state.guest?.telegram_user_id) {
            note(box, 'Связывание доступно внутри Telegram, когда в этом же окне открыт текущий профиль. Можно войти в него по логину и паролю.', 'muted');
        }
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
                item.append(button('Открыть Ночной город', () => openGuestMafia(room), 'primary'));
                item.append(button('Открыть классический квиз', () => openGuestClassic(room)));
                item.append(button('Открыть фото-загадки', () => openGuestPhoto(room)));
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
        if (tg?.initData) box.append(button('Войти через Telegram', () => {
            state.guest = null;
            try { sessionStorage.setItem('mqb-auth-choice', 'telegram'); } catch {}
            loginScreen();
        }, 'quiet'));
        if (!saved) {
            const keep = el('section', undefined, 'card keep-card');
            keep.append(el('span', 'Аккаунт', 'eyebrow'), el('h2', 'Сохранить профиль'));
            note(keep, 'Задай логин и пароль: прогресс останется за тобой и откроется с любого браузера.');
            note(keep, 'Сброс пароля пока недоступен. Сохрани его; связанный Telegram даёт ещё один способ входа.', 'notice warn');
            const open = button('Сохранить профиль: задать логин и пароль', () => {
                open.hidden = true; keep.append(accountForm('save', guestHome));
            }, 'primary');
            keep.append(open); guestSide.append(keep);
        }
        box.append(button(saved || state.guest?.telegram_user_id ? 'Выйти' : 'Выйти и потерять доступ к гостю', async event => {
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
        }, 'quiet'));
        guestMain.append(box);
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
            if (!state.authenticated) loginScreen('Сессия истекла. Откройте Mini App из Telegram заново.');
            else feedback.textContent = error.message;
        }
    }
    function configureTelegram() {
        window.QuizTelegram.configure(() => { if (state.authenticated) navigate(state.page === 'settings' ? 'profile' : 'home'); },
            () => { if (state.authenticated) navigate('settings'); }, () => { if (state.authenticated) load(); });
    }
    async function createTelegramSession(demo = state.demo, resume = false) {
        const result = await request(demo ? '/api/dev/session' : resume ? '/api/mini/session/resume' : '/api/mini/session', {method: 'POST',
            headers: {'Content-Type': 'application/json'}, body: demo ? '{}' : JSON.stringify({init_data: tg?.initData})});
        if (!resume) try { localStorage.removeItem('mqb-telegram-logged-out'); } catch {}
        return result;
    }
    function telegramFirstStart() {
        generation++; nav.hidden = true; feedback.textContent = ''; content.replaceChildren(); content.dataset.page = 'first-start';
        const box = el('section', undefined, 'login');
        box.append(el('h1', 'Добро пожаловать в Morning Quiz'));
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
        generation++; state.guest = null; window.QuizPlay?.stop(); nav.hidden = true; content.replaceChildren(); content.dataset.page = 'login';
        const box = el('section', undefined, 'login');
        const hero = el('div', undefined, 'hero'); const image = el('img'); image.src = '/app/host.webp'; image.alt = 'Филиныч, сова-ведущий Morning Quiz'; hero.append(image); box.append(hero);
        box.append(el('span', 'Morning Quiz · Филиныч на связи', 'eyebrow'), el('h1', 'Играй. Узнавай. Возвращайся.'));
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
            const toggles = el('div', undefined, 'actions');
            const show = kind => {
                panel.replaceChildren(accountForm(kind, guestHome));
                panel.querySelector('input')?.focus();
            };
            toggles.append(button('Войти по логину', () => show('login'), 'quiet'),
                           button('Создать аккаунт', () => show('register'), 'quiet'));
            box.append(toggles, panel);
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
            if (resumeFarmInvite('telegram')) return;
            if (state.selected && !state.chats.some(c => c.chat_id === state.selected)) {
                state.launchLost = true;      // чат из ссылки недоступен: не подменяем молча
                state.selected = '';
            }
            if (!state.selected) state.selected = state.chats[0]?.chat_id || '';
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
        if (text === '/adminsettings') { navigate('settings'); return; }
        const selected = state.chats.find(chat => chat.chat_id === state.selected);
        const action = {'/quiz': 'quiz', '/photo_quiz': 'photo'}[text];
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
        item.append(button(active ? 'Продолжить игру' : 'Настроить и играть', () => play(cmd), 'primary'));
        if (active) item.append(button('Команда остановки', () => command(cmd === '/quiz' ? '/stopquiz' : '/stop_photo_quiz'), 'quiet'));
        parent.append(item);
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
            note(content, error.message, 'error'); content.append(button('К играм', () => guestHome(), 'quiet'));
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
            feedback.textContent = 'Не удалось открыть ссылку. Найди Morning Quiz в Telegram и отправь /start.';
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
                    content.replaceChildren(button('К комнатам', guestHome, 'quiet'));
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
                content.replaceChildren(button('К комнатам', guestHome, 'quiet'));
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
                content.replaceChildren(button('К комнатам', guestHome, 'quiet'));
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
                content.replaceChildren(button('К комнатам', guestHome, 'quiet'));
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
        nav.hidden = true; state.page = 'guest-mafia'; feedback.textContent = ''; content.replaceChildren();
        content.append(button('К комнатам', () => guestHome(), 'quiet'));
        try { await mafia(version, room); }
        catch (error) { if (version === generation) { note(content, error.message, 'error'); content.append(button('Повторить', () => openGuestMafia(room))); } }
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
        const top = el('section', undefined, 'mafia-case');
        const image = el('img'); image.src = '/app/mafia.webp'; image.alt = 'Филиныч в капюшоне у стола детектива';
        const copy = el('div', undefined, 'mafia-case-copy');
        copy.append(el('span', 'НОЧНОЙ ГОРОД · ДЕЛО 01', 'eyebrow'), el('h1', draft.title));
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
          content.append(boundary, button('К играм', () => navigate('home'), 'quiet'));
          if (!pendingCommand && (room || (lobbyData?.lobby && !['lobby', 'finished'].includes(lobbyData.lobby.status)))) {
              const poll = () => {
                  if (generation !== version || state.page !== (room ? 'guest-mafia' : 'mafia')) return;
                  if (pendingCommand || content.querySelector('textarea')?.value) { setTimeout(poll, 5000); return; }
                  navigate('mafia');
              };
              setTimeout(poll, 5000);
          }
    }
    async function chatHome(version) {
        const hero = el('section', undefined, 'hero home-hero'), copy = el('div', undefined, 'hero-copy');
        copy.append(el('span', 'Филиныч на связи', 'eyebrow'));
        const title = el('h1', 'Ну что, '); title.append(el('em', 'сыграем?')); copy.append(title);
        note(copy, 'Выбирай формат. Я приготовлю вопросы.');
        const image = el('img'); image.src = '/app/host.webp'; image.alt = 'Сова Филиныч с микрофоном и карточкой вопроса'; hero.append(copy, image); content.append(hero); metrics(content);
        if (!state.selected) { note(content, 'Пока нет чатов с твоим участием. Сыграй первый квиз в боте, затем обнови приложение.', 'empty'); return; }
        if (state.launchLost) note(content, 'Чат из ссылки недоступен — возможно, доступ к нему закрыт.', 'error');
        chatSelect(content, () => navigate('chat'));
        let details, games;
        try { [details, games] = await Promise.all([request(`/api/mini/chats/${state.selected}/details`), request(`/api/mini/chats/${state.selected}/games`)]); }
        catch (error) {
            if (version !== generation) return;
            if (!isChatGone(error)) throw error;
            dropUnavailableChat(state.selected);
            note(content, 'Бот больше не в этом чате. Выбери другой чат или добавь бота обратно.', 'muted');
            if (state.selected) content.append(button('Открыть другой чат', () => navigate('chat'), 'quiet'));
            return;
        }
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
        content.append(addressSection('telegram', state.me));
        const game = el('section', undefined, 'card'); game.append(el('h2', 'Игра и расписание'));
        const personal = state.chats.find(chat => chat.type === 'private' && chat.chat_id === state.me.user_id);
        const target = state.chats.find(chat => chat.chat_id === state.selected) || personal;
        if (state.chats.length > 1) chatSelect(game, () => navigate('settings'));
        if (runtimeEnabled && target) {
            const [details, categoryData] = await Promise.all([
                request(`/api/mini/chats/${target.chat_id}/details`), request('/api/mini/categories'),
            ]);
            if (!details.can_edit) {
                note(game, 'Настройки доступны только администраторам этого чата. Войти в Mini App нужно с Telegram-аккаунта администратора.', 'muted');
            } else {
            note(game, target.type === 'private'
                ? 'Личные параметры общие для Mini App и бота. Изменение применяется к следующему раунду.'
                : 'Изменения применяются к этому чату и сразу видны в Telegram-боте.');
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
                    feedback.textContent = 'Параметры сохранены для этого чата и бота.'; await navigate('settings');
                } catch (error) { feedback.textContent = error.message; save.disabled = false; }
            };
            game.append(form);
            }
        } else {
            note(game, state.chats.length
                ? 'Изменение игровых параметров в этом preview отключено. В рабочем Mini App они сохраняются для выбранного чата.'
                : 'Сначала открой бота и добавь чат — тогда здесь появятся игровые параметры.', 'muted');
            if (state.chats.length > 1) chatSelect(game, () => navigate('settings'));
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
            try { await request('/api/mini/session', {method: 'DELETE'}); clearTimeout(renewTimer); state.authenticated = false; state.me = null; state.page = 'home';
                try { localStorage.setItem('mqb-telegram-logged-out', '1'); } catch {}
                loginScreen(); }
            catch (error) { feedback.textContent = error.message; }
        }, 'quiet')); content.append(actions);
    }
    function chats() {
        content.append(el('span', 'Игровые чаты', 'eyebrow'), el('h1', 'Твои чаты')); note(content, 'У каждого чата свой рейтинг, серия и расписание.');
        if (!state.chats.length) {
            note(content, 'Запусти /start в личном чате с ботом или добавь его в группу. После этого выбери появившийся чат — квиз и фото-загадки можно будет запускать прямо здесь.', 'empty');
            if (state.botUsername) content.append(button('Открыть бота', () => openBotHome(), 'primary'));
        }
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
        content.append(el('span', 'Рейтинг', 'eyebrow'), el('h1', 'Гонка за знаниями'));
        const field = el('label', 'Рейтинг', 'field'), select = el('select'); select.setAttribute('aria-label', 'Область рейтинга');
        const global = el('option', 'Глобальный рейтинг'); global.value = ''; select.append(global);
        for (const chat of state.chats) { const option = el('option', chat.title); option.value = chat.chat_id; select.append(option); }
        select.value = state.selected; field.append(select); content.append(field);
        const list = el('ol', undefined, 'list'); content.append(list); let offset = 0, requestSequence = 0;
        const failure = error => { if (!state.authenticated) loginScreen(error.message); else feedback.textContent = error.message; more.disabled = false; };
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
        if (!state.authenticated) { loginScreen(); return; }
        window.QuizPlay?.stop();
        window.QuizPlay?.stop();
        window.QuizTelegram.selection();
        state.page = page; const version = ++generation; feedback.textContent = ''; content.replaceChildren(); content.dataset.page = page;
        const tab = page.startsWith('settings') || page === 'achievements' || page === 'history' || page === 'alchemy-top' ? 'profile' : page === 'play' ? 'home' : page === 'chat' ? 'chats' : page;
        nav.querySelectorAll('button').forEach(node => { if (node.dataset.page === tab) node.setAttribute('aria-current', 'page'); else node.removeAttribute('aria-current'); });
        if (tg?.BackButton) { if (page === 'home') tg.BackButton.hide(); else tg.BackButton.show(); }
        try {
            if (page === 'home') await home(version);
            else if (page === 'play') {
                const command = playCommand; playCommand = null;
                if (!state.selected) { noChatPlay(); return; }
                if (![null, '/quiz', '/photo_quiz'].includes(command)) {
                    throw new Error('Для этого игрового режима ещё нет прямого подключения. Выбери квиз, фото-загадки или Ночной город.');
                }
                if (!window.QuizPlay) throw new Error('Игровой экран не загрузился. Обнови приложение.');
                await window.QuizPlay.mount({host: content, request, command, chatId: state.selected, settings: false, onReplay: cmd => play(cmd), onProfile: () => { state.page = 'profile'; load(); }, onSettings: () => navigate('settings'), onHome: () => { state.page = 'home'; load(); }, selection: () => window.QuizTelegram.selection(), media: async path => {
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
    document.querySelector('.brand').addEventListener('click', event => { if (state.authenticated) { event.preventDefault(); navigate('home'); } });
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
        state.demo = info?.demo === true;
        if (state.demo) { const banner = document.getElementById('environment'); banner.hidden = false; banner.textContent = info?.synthetic_player ? 'DEV · Тестовый игрок. Без отправки сообщений в Telegram.' : 'DEV · Просмотр твоего профиля из локальной БД.'; }
        if ((state.gameModes || []).some(mode => mode.id === 'farm' && mode.status === 'development') && farmLaunchHint()) {
            await bootstrapFarmInvite().catch(error => bootstrapError(error, bootstrapFarmInvite));
            return;
        }
        await bootstrapEntry().catch(error => bootstrapError(error, bootstrapEntry));
    });
})();
