(() => {
    'use strict';
    const el = (tag, text, cls) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (cls) n.className = cls; return n; };
    const number = value => new Intl.NumberFormat('ru-RU', {maximumFractionDigits: 1}).format(Number(value) || 0);
    let dispose = () => {};
    const seconds = value => typeof value === 'number' ? value : Date.parse(value) / 1000;
    // Transport adapters. play-ui only talks to an `api` object, so the same screen plays a
    // Telegram chat game (chatApi) or a standalone room game (roomApi). Command methods take
    // the idempotency id chosen by play-ui: it is reused unchanged when a command is retried.
    function chatApi(chatId, request) {
        if (!chatId) throw new Error('Выбери чат и игровой режим перед запуском.');
        const base = kind => `/api/mini/${kind}/chats/${chatId}`;
        const post = (path, body) => request(path, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
        return {
            kind: 'chat',
            async setup(kind) {
                if (kind === 'classic') return (await request(`/api/mini/chats/${chatId}/details`))?.classic || null;
                return request(`${base('photo')}/setup`);
            },
            async current(kind) {
                try { return await request(`${base(kind)}/sync`, {method: 'POST'}); }
                catch (error) { if (error.status === 404) return null; throw error; }
            },
            start(kind, params, id) {
                return post(`${base(kind)}/start`, kind === 'classic' ? {command_id: id} : {...params, command_id: id});
            },
            answer(kind, params, id) {
                if (kind === 'classic') {
                    const body = {selected_option: params.selectedOption};
                    body[params.internal ? 'round_id' : 'poll_id'] = params.questionId;
                    return post(`${base('classic')}/answer`, {...body, command_id: id});
                }
                return post(`${base('photo')}/answer`, {round_id: params.questionId, answer: params.answer, command_id: id});
            },
            stop(kind, params, id) { return post(`${base(kind)}/stop`, {expected_revision: params.revision, command_id: id}); },
            imageUrl: question => question.image_url,
        };
    }
    function roomApi(roomId, request, {accountId = null} = {}) {
        if (!roomId) throw new Error('Выбери комнату перед запуском.');
        const base = kind => `/api/guest/rooms/${encodeURIComponent(roomId)}/${kind}`;
        const post = (path, body, id) => request(path, {method: 'POST', headers: {'Content-Type': 'application/json', 'Idempotency-Key': id}, body: JSON.stringify(body)});
        return {
            kind: 'room', accountId,
            async setup(kind) {
                return request(`${base(kind)}/setup`);
            },
            async current(kind) {
                try {
                    const data = await request(`${base(kind)}/current`);
                    if (kind === 'photo' && data?.occupied) return {occupied: true};
                    const view = data?.current || null;
                    // A finished room game stays "current" with its last question: show the result, not the question.
                    if (view && ['finished', 'stopped', 'interrupted'].includes(view.status)) return {...view, question: null, finished_view: true};
                    return view;
                } catch (error) { if (error.status === 404) return null; throw error; }
            },
            start(kind, params, id) {
                return post(`${base(kind)}/start`, kind === 'classic'
                    ? {count: params.count, open_seconds: params.open_seconds, interval_seconds: params.interval_seconds,
                        ...(params.category_mode ? {category_mode: params.category_mode, categories: params.categories || [], random_categories: params.random_categories} : {})}
                    : {question_count: params.question_count, open_seconds: params.open_seconds, hints_enabled: params.hints_enabled}, id);
            },
            answer(kind, params, id) {
                return post(`${base(kind)}/answer`, kind === 'classic'
                    ? {game_id: params.gameId, round_id: params.questionId, selected_option: params.selectedOption}
                    : {game_id: params.gameId, round_id: params.questionId, answer: params.answer}, id);
            },
            stop(kind, params, id) { return post(`${base(kind)}/stop`, {game_id: params.gameId, expected_revision: params.revision}, id); },
            imageUrl: question => question.image_url,
        };
    }
    window.QuizPlay = {
        chatApi, roomApi,
        stop() { dispose(); dispose = () => {}; },
        async mount({host, request, media, command, chatId, api: adapter, selection, onHome, onReplay, onProfile, onSettings}) {
            window.QuizPlay.stop();
            if (!(adapter || chatId) || ![null, undefined, '/quiz', '/photo_quiz'].includes(command)) {
                throw new Error('Выбери чат и игровой режим перед запуском.');
            }
            const api = adapter || chatApi(chatId, request), room = api.kind === 'room';
            document.body?.classList.add('is-playing');
            let active = true, timer, ticker, direct, directPhoto, classicSetup = null, classicChoice = null, photoSetup = null, photoOccupied = false, lastAccepted = null, skipGame = null, setupError = null, busy = false, pendingCommand = null, lastHash = '', chosen = null, questionKey = '', draft = '', starting = false;
            let preferred = command === '/photo_quiz' ? 'photo' : command === '/quiz' ? 'classic' : null;
            const images = new Map();
            const page = el('section', undefined, 'play-screen'), top = el('div', undefined, 'play-topline');
            // Core classes from qw-shell.css; self-styled option buttons keep only their own class.
            const button = (text, fn, cls = '') => {
                const b = el('button', text, /play-option|qw-btn/.test(cls) ? cls : ('qw-btn ' + cls.replace('quiet', 'secondary quiet')).trim());
                b.type = 'button'; b.onclick = fn; return b;
            };
            const mode = el('span', 'Твой ход', 'eyebrow'); top.append(mode);
            const status = el('p', '', 'play-connection'); status.setAttribute('role', 'status');
            const stage = el('div', undefined, 'play-stage'), notice = el('div', '', 'play-notice'); notice.setAttribute('role', 'status');
            // Confirmation for «Завершить раунд» (menu item). In-page: confirm() is unreliable inside Telegram.
            const exitBox = el('section', undefined, 'round-exit card'); exitBox.hidden = true; exitBox.setAttribute('role', 'alert');
            page.append(top, status, stage, exitBox, notice); host.append(page);
            let screen = 'setup', shown = null;
            const kindNow = () => shown || preferred;
            const canStop = () => screen === 'question' && (shown === 'photo' ? directPhoto?.revision !== undefined : direct?.revision !== undefined
                && !['finished', 'stopped', 'interrupted'].includes(direct?.status));
            const canSettings = () => typeof onSettings === 'function' && !room && screen === 'setup' && preferred === 'classic' && Boolean(classicSetup);
            function closeExit() { exitBox.hidden = true; exitBox.replaceChildren(); }
            function askStop() {
                if (!canStop()) return;
                const stop = shown === 'photo' ? stopPhotoDirect : stopDirect;
                const row = el('div', undefined, 'qw-btn-row');
                row.append(button('Отмена', closeExit, 'qw-btn secondary'), button('Да, завершить', () => { closeExit(); stop(); }, 'qw-btn danger'));
                exitBox.replaceChildren(el('h3', 'Завершить раунд?'), el('p', 'Уже полученные баллы сохранятся.', 'muted'), row);
                exitBox.hidden = false;
                exitBox.scrollIntoView?.({block: 'nearest'});
            }
            // Page items of the ⚙ menu (UI_RULES §5): replaced on every render, cleared on leaving the page.
            function syncMenu() {
                if (!active || !window.QW?.menu) return;
                window.QW.menu.register([
                    {id: 'quiz-settings', icon: 'sliders', label: 'Настройки квиза', hint: 'Темы, число вопросов и время ответа', hidden: () => !canSettings(), onSelect: () => onSettings()},
                    {id: 'round-stop', icon: 'flag', label: 'Завершить раунд', danger: true, hidden: () => !canStop(), onSelect: askStop},
                ], kindNow() === 'photo' ? 'Фото-загадки' : 'Классический квиз');
            }
            dispose = () => { active = false; window.QW?.menu?.register([]); clearTimeout(timer); clearInterval(ticker); images.forEach(url => URL.revokeObjectURL(url)); document.body?.classList.toggle('is-playing', false); };
            // Action groups never stand as bare neighbours (UI_RULES §9): one .qw-btn-stack, the main action first.
            function actionStack(...buttons) { const group = el('div', undefined, 'qw-btn-stack'); group.append(...buttons); stage.append(group); }
            function hostLine(text, cls = '') {
                const row = el('div', undefined, `host-line ${cls}`), image = el('img'); image.src = '/app/host.webp'; image.alt = ''; row.append(image, el('p', text)); return row;
            }
            function stats(game) {
                const bar = el('div', undefined, 'round-progress');
                bar.append(el('span', `${game.current} / ${game.total}`, 'round-count'), el('span', `${number(game.points)} баллов`, 'round-points'));
                const meter = el('progress'); meter.max = Math.max(1, game.total); meter.value = game.current; meter.setAttribute('aria-label', `Вопрос ${game.current} из ${game.total}`);
                stage.append(bar, meter);
            }
            function picture(question) {
                const path = api.imageUrl(question);
                const image = el('img'); image.alt = 'Что изображено на фото?'; image.className = 'play-photo';
                if (images.has(path)) image.src = images.get(path);
                else media(path).then(blob => { if (!active) return; const url = URL.createObjectURL(blob); images.set(path, url); image.src = url; }).catch(() => { if (active) image.alt = 'Фото не загрузилось. Проверь подключение.'; });
                return image;
            }
            function countdown(end, closed = false) {
                const clock = el('span', '', 'play-clock'); clock.dataset.deadline = end; clock.dataset.closed = String(closed); clock.setAttribute('aria-label', 'Оставшееся время'); clock.setAttribute('aria-live', 'off'); return clock;
            }
            function directSetup() {
                stage.append(el('span', 'ПЕРЕД ПЕРВЫМ ВОПРОСОМ', 'eyebrow'));
                if (setupError) {
                    stage.append(el('h1', 'Не удалось подготовить игру'), el('p', setupError, 'muted'));
                    stage.append(button('Повторить', async () => {
                        try { await loadDirectSetup(preferred); await refresh(); }
                        catch (error) { setupError = error.message; lastHash = ''; render(); }
                    }, 'quiet'));
                    return;
                }
                if (preferred === 'classic') {
                    const config = classicSetup;
                    if (!config) { stage.append(hostLine('Загружаю параметры квиза…')); return; }
                    stage.append(el('h1', 'Проверим интуицию?'));
                    if (room && classicChoice) {
                        stage.append(hostLine('Настрой партию: сколько вопросов, сколько времени на ответ и какие темы.'));
                        roomClassicForm(config);
                        stage.append(button('Начать игру', startDirect, 'primary play-primary'));
                        return;
                    }
                    stage.append(hostLine(room ? 'Вопросы подбираются из общего каталога. Это твоя личная партия.' : 'Вопросы и правила берутся из настроек выбранного чата. Ответы и очки будут общими с игрой в чате.'));
                    const facts = el('div', undefined, 'preparation-facts');
                    facts.append(el('span', `${number(config.questions)} вопросов`), el('span', `${number(config.seconds)} секунд на ответ`));
                    if (Number(config.interval) > 0) facts.append(el('span', `Пауза ${number(config.interval)} секунд`));
                    const categoryText = config.category_mode === 'specific' && config.categories?.length
                        ? `Темы: ${config.categories.join(', ')}`
                        : config.category_mode === 'exclude' && config.categories?.length
                            ? `Без тем: ${config.categories.join(', ')}` : (room ? 'Темы — любые' : 'Темы — по настройкам чата');
                    facts.append(el('span', categoryText)); stage.append(facts);
                    stage.append(button('Начать игру', startDirect, 'primary play-primary'));
                } else if (preferred === 'photo') {
                    if (!photoSetup) { stage.append(hostLine('Проверяю фото-каталог…')); return; }
                    stage.append(el('h1', 'Присмотримся?'));
                    stage.append(hostLine(room ? 'Каждая загадка соединяет образы в слово. Ответы сохраняются в твоём аккаунте.' : 'Каждая загадка соединяет образы в слово. Ответы через Mini App сохраняются в ту же игровую систему.'));
                    const facts = el('div', undefined, 'preparation-facts');
                    facts.append(el('span', `${photoSetup.question_count} картинки`),
                        el('span', `${photoSetup.open_seconds} секунд на картинку`),
                        el('span', photoSetup.hints_enabled ? 'Подсказки включены' : 'Без подсказок'),
                        el('span', `Доступно загадок: ${photoSetup.available_questions}`));
                    stage.append(facts);
                    stage.append(button('Начать фото-серию', startPhotoDirect, 'primary play-primary'));
                    if (photoSetup.available_questions < photoSetup.question_count) {
                        stage.append(el('p', 'В каталоге пока меньше картинок, чем вопросов в серии — некоторые загадки могут повториться.', 'play-footnote'));
                    }
                    if (photoOccupied) {
                        stage.querySelector('button')?.setAttribute('disabled', '');
                        stage.append(el('p', 'Фото-серия занята другим игроком.', 'play-notice'));
                    } else if (!photoSetup.can_start) {
                        stage.querySelector('button')?.setAttribute('disabled', '');
                        stage.append(el('p', 'Сейчас в каталоге нет доступных изображений.', 'play-notice'));
                    }
                } else {
                    stage.append(el('h1', 'Выбери игру'));
                    stage.append(hostLine('Можно начать классический квиз или фото-загадки. Настройки квиза открываются из меню ⚙.'));
                    actionStack(button('Классический квиз', () => chooseDirectMode('classic'), 'primary play-primary'), button('Фото-загадки', () => chooseDirectMode('photo'), 'quiet play-secondary'));
                }
                if (!room) stage.append(el('p', 'Настройки квиза — в меню ⚙. Этот раунд использует состояние выбранного чата.', 'play-footnote'));
            }
            // Room Classic setup: the same options as the Telegram settings (count, time, pause, theme mode and themes).
            function roomClassicForm(config) {
                const limits = config.limits || {}, choice = classicChoice;
                const form = el('form', undefined, 'native-settings room-classic-setup');
                form.onsubmit = event => { event.preventDefault(); startDirect(); };
                const numeric = (title, key, range, fallback) => {
                    const field = el('label', title, 'field'), input = el('input');
                    input.type = 'number'; input.name = key; input.min = String((limits[range] || fallback)[0]); input.max = String((limits[range] || fallback)[1]);
                    input.value = String(choice[key]);
                    input.addEventListener('input', () => { choice[key] = input.value === '' ? NaN : Number(input.value); });
                    field.append(input); form.append(field); return input;
                };
                numeric('Вопросов в раунде', 'questions', 'questions', [1, 50]);
                numeric('Секунд на ответ', 'seconds', 'seconds', [5, 600]);
                numeric('Пауза между вопросами, секунд', 'interval', 'interval', [0, 600]);
                const picker = el('details', undefined, 'category-picker'); picker.open = true;
                picker.append(el('summary', 'Темы квиза'));
                const modeField = el('label', 'Как выбирать темы', 'field'), mode = el('select'); mode.name = 'category_mode';
                for (const [value, label] of [['all', 'Все темы'], ['random', 'Случайные темы'], ['specific', 'Только выбранные'], ['exclude', 'Все, кроме выбранных']]) {
                    const option = el('option', label); option.value = value; mode.append(option);
                }
                mode.value = choice.category_mode; modeField.append(mode);
                const randomField = el('label', 'Сколько случайных тем', 'field'), random = el('input');
                random.type = 'number'; random.name = 'random_categories'; random.min = String((limits.random_categories || [1, 10])[0]); random.max = String((limits.random_categories || [1, 10])[1]);
                random.value = String(choice.random_categories);
                random.addEventListener('input', () => { choice.random_categories = random.value === '' ? NaN : Number(random.value); });
                randomField.append(random);
                const checks = el('div', undefined, 'category-checks');
                for (const name of config.available_categories || []) {
                    const label = el('label', undefined, 'category-choice'), input = el('input');
                    input.type = 'checkbox'; input.checked = choice.categories.has(name);
                    input.addEventListener('change', () => { if (input.checked) choice.categories.add(name); else choice.categories.delete(name); });
                    label.append(input, el('span', name)); checks.append(label);
                }
                const sync = () => {
                    choice.category_mode = mode.value;
                    randomField.hidden = !['random', 'all', 'exclude'].includes(mode.value) ? true : mode.value === 'all';
                    checks.hidden = !['specific', 'exclude'].includes(mode.value);
                };
                mode.addEventListener('change', sync); sync();
                picker.append(modeField, randomField, checks); form.append(picker);
                stage.append(form);
            }
            async function loadDirectSetup(kind) {
                setupError = null;
                try {
                    if (kind === 'classic') {
                        classicSetup = await api.setup('classic');
                        classicChoice = room && classicSetup && Array.isArray(classicSetup.available_categories) ? {
                            questions: classicSetup.questions, seconds: classicSetup.seconds, interval: classicSetup.interval,
                            category_mode: classicSetup.category_mode || 'all', categories: new Set(classicSetup.categories || []),
                            random_categories: classicSetup.random_categories || 3,
                        } : null;
                        photoSetup = null;
                    } else {
                        photoSetup = await api.setup('photo');
                        classicSetup = null;
                    }
                } catch (error) { setupError = error.message; throw error; }
            }
            async function chooseDirectMode(kind) {
                if (busy || !active) return;
                preferred = kind; direct = null; directPhoto = null; lastHash = '';
                stage.replaceChildren(hostLine('Загружаю параметры игры…'));
                try { await loadDirectSetup(kind); await refresh(); }
                catch (error) { notice.textContent = error.message; stage.replaceChildren(button('Повторить', () => chooseDirectMode(kind), 'quiet')); }
            }
            function inputForm(title, round, disabled = false) {
                const form = el('form', undefined, 'play-answer-form'), field = el('label', title), input = el('input');
                input.value = draft; input.autocomplete = 'off'; input.maxLength = 300; input.placeholder = round ? 'Кажется, это…' : 'Введи значение'; input.disabled = disabled;
                input.addEventListener('input', () => { draft = input.value; }); field.append(input);
                const submit = button(round ? 'Проверить ответ' : 'Применить', () => {}, 'primary play-primary'); submit.type = 'submit'; submit.disabled = disabled || busy;
                form.append(field, submit); form.onsubmit = event => {
                    event.preventDefault();
                    if (!disabled && !busy && input.value.trim()) sendPhotoDirect(round, input.value.trim());
                }; stage.append(form);
            }
            function myScore(view) {
                const list = view.scores || [];
                const mine = list.find(item => api.accountId && item.account_id === api.accountId) || (list.length === 1 ? list[0] : null);
                return mine ? Number(mine.score) || 0 : 0;
            }
            function acceptedVerdict(view) {
                const accepted = lastAccepted;
                if (!accepted || accepted.round_id === view.question?.round_id) return;
                const verdict = el('section', undefined, `play-verdict ${accepted.is_correct ? 'is-correct' : ''}`);
                verdict.append(el('strong', accepted.is_correct ? 'Верно! Ответ принят.' : 'Не в этот раз.'),
                    el('span', `${Number(accepted.points) > 0 ? '+' : ''}${number(accepted.points)} баллов`));
                if (Number.isInteger(accepted.correct_option) && accepted.options) verdict.append(el('p', `Правильный ответ: ${accepted.options[accepted.correct_option]}`));
                if (accepted.explanation) verdict.append(el('p', accepted.explanation));
                stage.append(verdict);
            }
            function scoreList(view) {
                if (!view.scores?.length) return;
                const box = el('section', undefined, 'play-scores');
                box.append(el('span', 'ОЧКИ ПАРТИИ', 'eyebrow'));
                view.scores.forEach(item => box.append(el('p', `${item.name}: ${number(item.score)}`)));
                stage.append(box);
            }
            function classicResult(view) {
                const complete = view.status === 'finished';
                stage.append(el('span', complete ? 'ПАРТИЯ ЗАВЕРШЕНА' : 'ПАРТИЯ ОСТАНОВЛЕНА', 'eyebrow'),
                    el('h1', complete ? 'Квиз пройден.' : 'Продолжим в другой раз.', 'result-title'));
                const score = el('div', undefined, 'result-score'); score.append(el('strong', number(myScore(view))), el('span', 'баллов за партию')); stage.append(score);
                acceptedVerdict(view); scoreList(view);
                actionStack(button('Сыграть ещё', () => replay('classic'), 'primary play-primary'), button('Мой прогресс', onProfile, 'quiet play-secondary'));
            }
            function sharedQuestion(view) {
                const poll = view.question, game = view.game || {current: poll.question_number, total: poll.question_number};
                stats({...game, points: myScore(view)});
                const lines = poll.question.split('\n');
                if (lines.length > 1 && /^(?:Ежедневный )?[Вв]опрос(?: \d+\/\d+)?$/.test(lines[0].trim())) lines.shift();
                const category = lines.length > 1 && lines[0].startsWith('Категория: ') ? lines.shift().slice(11) : 'ОДИН ВОПРОС. ТВОЁ РЕШЕНИЕ.';
                const deadline = Date.parse(poll.ends_at) / 1000;
                const head = el('div', undefined, 'question-top');
                head.append(el('span', category, 'eyebrow'), countdown(deadline, poll.closed || poll.answered)); stage.append(head);
                stage.append(el('h1', lines.join('\n'), 'play-question'));
                const answers = el('div', undefined, 'play-answers');
                poll.options.forEach((option, index) => {
                    const b = button(undefined, () => {
                        if (!busy && !poll.closed && !poll.answered && Date.now() < Date.parse(poll.ends_at)) sendDirect(poll.round_id || poll.poll_id, index, !!poll.round_id);
                    }, 'play-option');
                    b.append(el('span', String.fromCharCode(65 + index), 'option-letter'), el('span', option));
                    if (chosen === index || poll.selected_option === index) b.classList.add('selected');
                    if (poll.answered && index === poll.correct_option) { b.classList.add('correct'); b.append(el('span', '✓', 'option-mark')); }
                    if (poll.answered && index === poll.selected_option && !poll.is_correct) { b.classList.add('incorrect'); b.append(el('span', '×', 'option-mark')); }
                    b.disabled = busy || poll.closed || poll.answered; answers.append(b);
                });
                stage.append(answers);
                acceptedVerdict(view);
                if (poll.answered) {
                    const verdict = el('section', undefined, `play-verdict ${poll.is_correct ? 'is-correct' : ''}`);
                    verdict.append(el('strong', poll.is_correct ? 'Есть! Именно так.' : 'Не в этот раз. Зато теперь знаешь.'),
                        el('span', `${Number(poll.points) > 0 ? '+' : ''}${number(poll.points)} баллов`));
                    if (poll.explanation) verdict.append(el('p', poll.explanation)); stage.append(verdict);
                    stage.append(el('p', room ? 'Ответ сохранён. Следующий вопрос появится здесь.' : 'Ответ сохранён в общей игре. Следующий вопрос появится здесь и в чате.', 'play-footnote'));
                } else if (poll.closed) stage.append(hostLine(room ? 'Время вышло. Ждём следующий вопрос.' : 'Время вышло. Ждём следующий вопрос общей игры.'));
                else stage.append(el('p', busy ? 'Ответ сохраняется…' : room ? 'Нажми на вариант — ответ сразу сохранится.' : 'Нажми на вариант — ответ сразу попадёт в общую игру.', 'play-footnote'));
                scoreList(view);
            }
            function sharedPhoto(view) {
                const question = view.question;
                stats({current: question.question_number, total: question.question_count, points: view.score});
                const head = el('div', undefined, 'question-top');
                head.append(el('span', 'УЗНАЁШЬ?', 'eyebrow'), countdown(seconds(question.ends_at), question.closed)); stage.append(head);
                stage.append(el('h1', 'Что скрывается\nна картинке?', 'play-question'), picture(question));
                if (question.mask) stage.append(el('p', question.mask, 'photo-mask'));
                if (view.last_result) {
                    const result = view.last_result, verdict = el('section', undefined, `play-verdict ${result.correct ? 'is-correct' : ''}`);
                    verdict.append(el('strong', result.correct ? 'Верно! Следующая картинка уже здесь.' : 'Время вышло. Идём дальше.'),
                        el('span', result.correct ? `+${number(result.points)} баллов` : `Ответ: ${result.answer}`)); stage.append(verdict);
                }
                if (question.feedback === 'almost') stage.append(el('p', 'Очень близко — образ верный, собери точное слово.', 'photo-hint'));
                else if (question.feedback === 'wrong') stage.append(el('p', 'Пока мимо. Посмотри, какие два образа соединяются.', 'photo-hint'));
                if (!question.closed) inputForm('Твой ответ', question.round_id, false, true);
                else stage.append(hostLine('Этот фото-вопрос уже закрыт. Готовим следующий.'));
                stage.append(el('p', room ? 'Картинка загружена из текущей серии.' : 'Картинка загружена из общей игровой сессии, без копии сообщения Telegram.', 'play-footnote'));
            }
            function sharedPhotoResult(view) {
                const complete = view.status === 'finished';
                stage.append(el('span', complete ? 'ФОТО-СЕРИЯ ЗАВЕРШЕНА' : 'ФОТО-СЕРИЯ ОСТАНОВЛЕНА', 'eyebrow'),
                    el('h1', complete ? 'Образы сложились.' : 'Продолжим в другой раз.', 'result-title'));
                const score = el('div', undefined, 'result-score'); score.append(el('strong', number(view.score)), el('span', 'баллов за серию')); stage.append(score);
                stage.append(el('p', `${view.correct} правильных из ${view.game.total}`, 'previous-answer'));
                if (view.last_result?.answer) stage.append(hostLine(`Последний ответ: ${view.last_result.answer}`));
                actionStack(button('Сыграть ещё', () => room ? replay('photo') : onReplay('/photo_quiz'), 'primary play-primary'), button('Мой прогресс', onProfile, 'quiet play-secondary'));
            }
            function render() {
                if (!active) return;
                if (starting) { screen = 'setup'; }
                else if (directPhoto) { shown = 'photo'; screen = directPhoto.question ? 'question' : 'result'; }
                else if (direct?.question) { shown = 'classic'; screen = 'question'; }
                else if (direct && ['finished', 'stopped', 'interrupted'].includes(direct.status)) { shown = 'classic'; screen = 'result'; }
                else { shown = null; screen = 'setup'; }
                if (screen !== 'question') closeExit();
                renderView(); syncMenu();
            }
            function renderView() {
                if (starting) { stage.replaceChildren(hostLine('Готовлю твою игру. Сейчас начнём.')); return; }
                if (directPhoto?.question) {
                    const hash = JSON.stringify([directPhoto, busy]); if (hash === lastHash) return;
                    lastHash = hash; stage.replaceChildren(); mode.textContent = 'Фото-загадки'; sharedPhoto(directPhoto); tick(); return;
                }
                if (directPhoto) {
                    const hash = JSON.stringify([directPhoto, busy]); if (hash === lastHash) return;
                    lastHash = hash; stage.replaceChildren(); mode.textContent = 'Фото-загадки'; sharedPhotoResult(directPhoto); return;
                }
                if (direct?.question) {
                    const hash = JSON.stringify([direct, busy, chosen, lastAccepted]); if (hash === lastHash) return;
                    const directKey = direct.question.round_id || direct.question.poll_id;
                    if (directKey !== questionKey) { chosen = null; questionKey = directKey; }
                    lastHash = hash; stage.replaceChildren(); mode.textContent = 'Классический квиз'; sharedQuestion(direct); tick(); return;
                }
                if (direct && !direct.question && ['finished', 'stopped', 'interrupted'].includes(direct.status)) {
                    const hash = JSON.stringify([direct, busy, lastAccepted]); if (hash === lastHash) return;
                    lastHash = hash; stage.replaceChildren(); mode.textContent = 'Классический квиз'; classicResult(direct); return;
                }
                const hash = JSON.stringify([preferred, classicSetup, photoSetup, photoOccupied, busy]);
                if (hash === lastHash) return;
                lastHash = hash; stage.replaceChildren();
                mode.textContent = preferred === 'photo' ? 'Фото-загадки' : preferred === 'classic' ? 'Классический квиз' : 'Выбор игры';
                directSetup();
                tick();
            }
            function tick() {
                stage.querySelectorAll('[data-deadline]').forEach(clock => {
                    const remaining = Math.max(0, Math.ceil(Number(clock.dataset.deadline) - Date.now() / 1000));
                    clock.textContent = clock.dataset.closed === 'true' ? '✓' : Number.isFinite(remaining) ? `${remaining} с` : '…';
                    clock.classList.toggle('urgent', remaining <= 5 && clock.dataset.closed !== 'true');
                    if (!remaining && clock.dataset.closed !== 'true') { stage.querySelectorAll('.play-option, .confirm-answer, .play-answer-form button').forEach(b => { b.disabled = true; }); }
                });
            }
            // A finished room game stays "current" on the server; after "play again" it is hidden locally.
            const hidden = view => (view && skipGame && view.game_id === skipGame) ? null : view;
            // Opening a game must not land on a game that had already ended before this screen opened.
            let firstLoad = true; const staleGames = new Set();
            const fresh = view => (view && view.finished_view && staleGames.has(view.game_id)) ? null : view;
            async function refresh(renderPage = true) {
                if (!active) return; clearTimeout(timer);
                try {
                    const [shared, sharedPhotoView] = await Promise.all([
                        preferred === 'photo' ? Promise.resolve(null) : api.current('classic').then(view => view ?? (direct?.status && direct.status !== 'active' ? direct : null)),
                        preferred === 'classic' ? Promise.resolve(null) : api.current('photo').then(view => view ?? (directPhoto?.status && directPhoto.status !== 'active' ? directPhoto : null)),
                    ]);
                    if (!active) return;
                    if (firstLoad) { firstLoad = false; [shared, sharedPhotoView].forEach(view => { if (view?.finished_view && view.game_id) staleGames.add(view.game_id); }); }
                    photoOccupied = !!sharedPhotoView?.occupied;
                    direct = fresh(hidden(shared)); directPhoto = photoOccupied ? null : fresh(hidden(sharedPhotoView)); status.textContent = '';
                    if (renderPage) render();
                } catch (error) { if (active) { status.textContent = error.message; stage.querySelectorAll('button').forEach(b => { b.disabled = true; }); lastHash = ''; } }
                finally { if (active) timer = setTimeout(refresh, document.hidden ? 10000 : busy ? 1000 : 2000); }
            }
            function replay(kind) {
                skipGame = (kind === 'photo' ? directPhoto : direct)?.game_id || null;
                direct = null; directPhoto = null; lastAccepted = null; chosen = null; draft = ''; lastHash = '';
                notice.textContent = ''; render();
            }
            // The idempotency id lives with the pending command: an uncertain retry sends the same id.
            async function runCommand(action, params, call, progress, retry) {
                if (!active || busy) return null;
                const key = action + JSON.stringify(params);
                const pending = pendingCommand?.key === key ? pendingCommand : {key, id: crypto.randomUUID()};
                pendingCommand = pending;
                busy = true; notice.textContent = progress; render();
                try {
                    const result = await call(pending.id);
                    pendingCommand = null;
                    notice.textContent = '';
                    return result;
                } catch (error) {
                    const uncertain = !error.status || error.status >= 500;
                    if (!uncertain) pendingCommand = null;
                    notice.replaceChildren(el('p', error.message));
                    if (uncertain) notice.append(button('Проверить отправку', retry || (() => runCommand(action, params, call, 'Проверяю сохранённую команду…')), 'quiet'));
                    return null;
                } finally { busy = false; lastHash = ''; if (active) render(); }
            }
            async function sendDirect(questionId, selectedOption, internalRound) {
                if (!active || busy) return;
                chosen = selectedOption; selection();
                const params = {gameId: direct?.game_id || null, questionId, internal: internalRound, selectedOption};
                const result = await runCommand('classic.answer', params, id => api.answer('classic', params, id), 'Сохраняю ответ…', () => sendDirect(questionId, selectedOption, internalRound));
                if (result) { lastAccepted = result.accepted_answer || null; direct = result; await refresh(); }
            }
            async function startDirect() {
                if (!active || busy) return;
                starting = true; render();
                const params = classicChoice ? {
                    count: classicChoice.questions, open_seconds: classicChoice.seconds, interval_seconds: classicChoice.interval,
                    category_mode: classicChoice.category_mode, categories: [...classicChoice.categories].filter(name => ['specific', 'exclude'].includes(classicChoice.category_mode)),
                    random_categories: classicChoice.random_categories,
                } : {count: classicSetup?.questions, open_seconds: classicSetup?.seconds, interval_seconds: classicSetup?.interval};
                if (classicChoice && classicChoice.category_mode === 'specific' && !params.categories.length || classicChoice && classicChoice.category_mode === 'exclude' && !params.categories.length) {
                    starting = false; notice.textContent = 'Выбери хотя бы одну тему.'; return render();
                }
                const result = await runCommand('classic.start', params, id => api.start('classic', params, id), 'Готовлю вопросы…', () => startDirect());
                starting = false;
                if (result) { lastAccepted = null; skipGame = null; direct = result; await refresh(); }
                else render();
            }
            async function stopDirect() {
                if (!active || busy || direct?.revision === undefined) return;
                const params = {gameId: direct.game_id || null, revision: direct.revision};
                const result = await runCommand('classic.stop', params, id => api.stop('classic', params, id), 'Завершаю раунд…', () => stopDirect());
                if (result) { direct = result; notice.textContent = 'Раунд завершён. Все баллы сохранены.'; render(); }
            }
            async function sendPhotoDirect(roundId, answer) {
                if (!active || busy) return;
                selection();
                const params = {gameId: directPhoto?.game_id || null, questionId: roundId, answer};
                const result = await runCommand('photo.answer', params, id => api.answer('photo', params, id), 'Проверяю ответ…', () => sendPhotoDirect(roundId, answer));
                if (result) { directPhoto = result; draft = ''; notice.textContent = result.verdict === 'correct' ? 'Есть! Ответ сохранён.' : ''; await refresh(); }
            }
            async function startPhotoDirect() {
                if (!active || busy) return;
                starting = true; render();
                const params = {question_count: photoSetup.question_count, open_seconds: photoSetup.open_seconds, hints_enabled: photoSetup.hints_enabled};
                const result = await runCommand('photo.start', params, id => api.start('photo', params, id), 'Раскладываю фото-загадки…', () => startPhotoDirect());
                starting = false;
                if (result) { skipGame = null; directPhoto = result; await refresh(); }
                else render();
            }
            async function stopPhotoDirect() {
                if (!active || busy || directPhoto?.revision === undefined) return;
                const params = {gameId: directPhoto.game_id || null, revision: directPhoto.revision};
                const result = await runCommand('photo.stop', params, id => api.stop('photo', params, id), 'Завершаю фото-серию…', () => stopPhotoDirect());
                if (result) { directPhoto = result; notice.textContent = 'Серия завершена. Баллы сохранены.'; render(); }
            }
            stage.append(hostLine('Филиныч раскладывает карточки…'));
            if (preferred) {
                try { await loadDirectSetup(preferred); }
                catch (error) { notice.textContent = error.message; }
            }
            await refresh(false);
            render();
            if (active) ticker = setInterval(tick, 500);
        },
    };
})();
