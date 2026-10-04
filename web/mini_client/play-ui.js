(() => {
    'use strict';
    const clean = text => String(text || '').replace(/\\([_\[\]()~`>#+\-=|{}.!*])/g, '$1').replace(/<\/?(?:b|i|code|pre|u|s)>/g, '').replace(/[*`]/g, '').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');
    const label = text => clean(text).replace(/^[^\p{L}\p{N}]+/u, '').trim();
    const el = (tag, text, cls) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (cls) n.className = cls; return n; };
    const number = value => new Intl.NumberFormat('ru-RU', {maximumFractionDigits: 1}).format(Number(value) || 0);
    const at = m => m.updated_at || m.at || 0;
    // Presentation only. Commands still enter the existing engine and scores come from its ledger.
    function model(data, preferred) {
        const games = data.games || [], messages = data.messages || [];
        const game = preferred ? games.find(g => g.kind === preferred) : games.find(g => g.status === 'active') || [...games].sort((a, b) => b.started_at - a.started_at)[0];
        const kind = preferred || game?.kind || (data.photo_round ? 'photo' : 'classic');
        const prefix = kind === 'photo' ? 'pqcfg_' : 'qcfg_';
        const menu = [...messages].filter(m => m.buttons?.some(row => row.some(b => b.data.startsWith(prefix)))).sort((a, b) => at(b) - at(a))[0];
        if (menu && game?.status !== 'active' && (!game || at(menu) >= game.started_at)) return {phase: 'setup', kind, menu};
        if (!game) return {phase: 'idle', kind};
        const related = messages.filter(m => m.at >= game.started_at - 1);
        const question = kind === 'classic' ? [...messages].reverse().find(m => m.poll && (game.poll_ids.includes(m.poll.id) || m.at >= game.started_at)) : [...related].reverse().find(m => m.media);
        if (game.status !== 'active') return {phase: 'result', kind, game, question};
        return {phase: kind === 'photo' ? 'photo' : question ? 'question' : 'waiting', kind, game, question,
            previous: [...related].reverse().find(m => m.feedback && m.id !== question?.id),
            hints: related.filter(m => m.at >= (question?.at || 0) && !m.media && /подсказка|попробуйте ещё|неверно/i.test(clean(m.text))).slice(-2)};
    }
    let dispose = () => {};
    window.QuizPlay = {
        model,
        stop() { dispose(); dispose = () => {}; },
        async mount({host, request, media, command, chatId, selection, onHome, onReplay, onProfile}) {
            window.QuizPlay.stop();
            document.body?.classList.add('is-playing');
            let active = true, timer, ticker, snapshot, direct, directPhoto, current, busy = false, pending = null, lastHash = '', chosen = null, questionKey = '', draft = '', offset = 0, starting = !!command;
            const preferred = command === '/photo_quiz' ? 'photo' : command === '/quiz' ? 'classic' : null;
            const images = new Map();
            const page = el('section', undefined, 'play-screen'), top = el('div', undefined, 'play-topline');
            const button = (text, fn, cls = '') => { const b = el('button', text, cls); b.type = 'button'; b.onclick = fn; return b; };
            const back = button('К играм', onHome, 'quiet'), mode = el('span', 'Твой ход', 'eyebrow'); top.append(back, mode);
            const status = el('p', '', 'play-connection'); status.setAttribute('role', 'status');
            const stage = el('div', undefined, 'play-stage'), notice = el('div', '', 'play-notice'); notice.setAttribute('role', 'status');
            page.append(top, status, stage, notice); host.append(page);
            dispose = () => { active = false; clearTimeout(timer); clearInterval(ticker); images.forEach(url => URL.revokeObjectURL(url)); document.body?.classList.toggle('is-playing', false); };
            const callback = (item, data) => send({type: 'callback', value: data, message_id: item.id, revision: item.revision});
            function hostLine(text, cls = '') {
                const row = el('div', undefined, `host-line ${cls}`), image = el('img'); image.src = '/app/host.webp'; image.alt = ''; row.append(image, el('p', text)); return row;
            }
            function stats(game) {
                const bar = el('div', undefined, 'round-progress');
                bar.append(el('span', `${game.current} / ${game.total}`, 'round-count'), el('span', `${number(game.points)} баллов`, 'round-points'));
                const meter = el('progress'); meter.max = Math.max(1, game.total); meter.value = game.current; meter.setAttribute('aria-label', `Вопрос ${game.current} из ${game.total}`);
                stage.append(bar, meter);
            }
            function picture(path) {
                const image = el('img'); image.alt = 'Что изображено на фото?'; image.className = 'play-photo';
                if (images.has(path)) image.src = images.get(path);
                else media(path).then(blob => { if (!active) return; const url = URL.createObjectURL(blob); images.set(path, url); image.src = url; }).catch(() => { if (active) image.alt = 'Фото не загрузилось. Проверь подключение.'; });
                return image;
            }
            function countdown(end, closed = false) {
                const clock = el('span', '', 'play-clock'); clock.dataset.deadline = end; clock.dataset.closed = String(closed); clock.setAttribute('aria-label', 'Оставшееся время'); clock.setAttribute('aria-live', 'off'); return clock;
            }
            function setup(view) {
                const menu = view.menu, buttons = menu.buttons.flat(), prefix = view.kind === 'photo' ? 'pqcfg_' : 'qcfg_';
                const start = buttons.find(b => b.data === prefix + 'start');
                if (start) {
                    stage.append(el('span', 'ПЕРЕД ПЕРВЫМ ВОПРОСОМ', 'eyebrow'), el('h1', view.kind === 'photo' ? 'Присмотримся?' : 'Проверим интуицию?'));
                    stage.append(hostLine(view.kind === 'photo' ? 'Покажу картинку. Ты — напиши, что узнал. Подсказки можно включить в параметрах раунда.' : 'Не нужно знать всё. Выбирай ответ и собирай серию. А если сомневаешься — доверься интуиции.'));
                    const facts = el('div', undefined, 'preparation-facts');
                    for (const b of buttons.filter(b => ['qcfg_num_menu', 'qcfg_open_period', 'pqcfg_qcount', 'pqcfg_time'].includes(b.data))) facts.append(el('span', label(b.text))); stage.append(facts);
                    const fields = el('div', undefined, 'round-summary');
                    for (const b of buttons.filter(b => !/start|cancel|noop/.test(b.data) && b.data.startsWith(prefix))) {
                        const name = label(b.text); fields.append(button(name, () => callback(menu, b.data), 'round-field'));
                    }
                    const details = el('details', undefined, 'round-options'); details.append(el('summary', 'Параметры этого раунда'), fields); stage.append(details);
                    stage.append(button('Начать игру', () => callback(menu, start.data), 'primary play-primary'));
                    stage.append(el('p', 'Общие настройки — в профиле. Этот раунд можно пройти здесь или в чате.', 'play-footnote'));
                } else {
                    const text = clean(menu.text).trim();
                    stage.append(el('span', 'ПАРАМЕТРЫ РАУНДА', 'eyebrow'), el('h1', text.split('\n')[0] || 'Выбери вариант'));
                    if (text.includes('\n')) stage.append(el('p', text.split('\n').slice(1).join('\n'), 'muted'));
                    const grid = el('div', undefined, 'setup-options');
                    for (const b of buttons.filter(b => b.data.startsWith(prefix))) grid.append(button(label(b.text), () => callback(menu, b.data), b.style === 'success' ? 'primary' : ''));
                    stage.append(grid);
                    if (/введите|напишите|отправьте/i.test(text)) inputForm('Твоё значение', null);
                }
            }
            function inputForm(title, round, disabled = false, directPhotoAnswer = false) {
                const form = el('form', undefined, 'play-answer-form'), field = el('label', title), input = el('input');
                input.value = draft; input.autocomplete = 'off'; input.maxLength = 300; input.placeholder = round ? 'Кажется, это…' : 'Введи значение'; input.disabled = disabled;
                input.addEventListener('input', () => { draft = input.value; }); field.append(input);
                const submit = button(round ? 'Проверить ответ' : 'Применить', () => {}, 'primary play-primary'); submit.type = 'submit'; submit.disabled = disabled || busy;
                form.append(field, submit); form.onsubmit = event => {
                    event.preventDefault();
                    if (!disabled && !busy && input.value.trim()) {
                        if (directPhotoAnswer) sendPhotoDirect(round, input.value.trim());
                        else send({type: 'text', value: input.value.trim(), round});
                    }
                }; stage.append(form);
            }
            function question(view) {
                const item = view.question, poll = item.poll, result = item.feedback;
                if (view.previous?.feedback) { const answer = view.previous.feedback; stage.append(el('p', `Предыдущий ответ: ${answer.correct ? 'верно ✓' : 'мимо'} · ${Number(answer.points) > 0 ? '+' : ''}${number(answer.points)} баллов`, 'previous-answer')); }
                // Separate only the engine's optional headers, preserving literal question text.
                const lines = poll.question.split('\n');
                if (lines.length > 1 && /^(?:Ежедневный )?[Вв]опрос(?: \d+\/\d+)?$/.test(lines[0].trim())) lines.shift();
                const category = lines.length > 1 && lines[0].startsWith('Категория: ') ? lines.shift().slice(11) : 'ОДИН ВОПРОС. ТВОЁ РЕШЕНИЕ.';
                const head = el('div', undefined, 'question-top'); head.append(el('span', category, 'eyebrow'), countdown(poll.ends_at, poll.closed || !!result)); stage.append(head);
                const title = lines.join('\n');
                stage.append(el('h1', title, 'play-question'));
                const answers = el('div', undefined, 'play-answers');
                poll.options.forEach((option, index) => {
                    const b = button(undefined, () => { if (!busy && snapshot.connected && !poll.closed && !result && Date.now() + offset < poll.ends_at * 1000) { chosen = index; send({type: 'vote', value: index, message_id: item.id}); } }, 'play-option');
                    b.append(el('span', String.fromCharCode(65 + index), 'option-letter'), el('span', option));
                    b.setAttribute('aria-pressed', String(chosen === index));
                    if (chosen === index) b.classList.add('selected');
                    if (result && index === result.answer) { b.classList.add('correct'); b.append(el('span', '✓', 'option-mark')); }
                    if (result && index === result.selected && !result.correct) { b.classList.add('incorrect'); b.append(el('span', '×', 'option-mark')); }
                    b.disabled = busy || !snapshot.connected || poll.closed || !!result; answers.append(b);
                }); stage.append(answers);
                if (result) {
                    const feedback = el('section', undefined, `play-verdict ${result.correct ? 'is-correct' : ''}`);
                    feedback.append(el('strong', result.correct ? 'Есть! Именно так.' : 'Не в этот раз. Зато теперь знаешь.'), el('span', `${Number(result.points) > 0 ? '+' : ''}${number(result.points)} баллов`));
                    if (result.explanation) feedback.append(el('p', clean(result.explanation))); stage.append(feedback);
                    stage.append(el('p', 'Следующий вопрос появится автоматически — в темпе общей игры.', 'play-footnote'));
                } else if (poll.closed) stage.append(hostLine('Время вышло. Не страшно — продолжим со следующим вопросом.'));
                else {
                    stage.append(el('p', busy ? 'Ответ отправляется…' : 'Нажми на вариант — это и будет твой ответ.', 'play-footnote'));
                }
            }
            function sharedQuestion(view) {
                const poll = view.question, game = view.game || {current: poll.question_number, total: poll.question_number};
                stats({...game, points: 0});
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
                if (poll.answered) {
                    const verdict = el('section', undefined, `play-verdict ${poll.is_correct ? 'is-correct' : ''}`);
                    verdict.append(el('strong', poll.is_correct ? 'Есть! Именно так.' : 'Не в этот раз. Зато теперь знаешь.'),
                        el('span', `${Number(poll.points) > 0 ? '+' : ''}${number(poll.points)} баллов`));
                    if (poll.explanation) verdict.append(el('p', poll.explanation)); stage.append(verdict);
                    stage.append(el('p', 'Ответ сохранён в общей игре. Следующий вопрос появится здесь и в чате.', 'play-footnote'));
                } else if (poll.closed) stage.append(hostLine('Время вышло. Ждём следующий вопрос общей игры.'));
                else stage.append(el('p', busy ? 'Ответ сохраняется…' : 'Нажми на вариант — ответ сразу попадёт в общую игру.', 'play-footnote'));
                if (view.revision !== undefined && !['finished', 'stopped', 'interrupted'].includes(view.status)) {
                    const exit = el('details', undefined, 'round-exit');
                    exit.append(el('summary', 'Завершить раунд'), el('p', 'Уже полученные баллы сохранятся.'));
                    exit.append(button('Да, завершить', stopDirect, 'quiet')); stage.append(exit);
                }
            }
            function sharedPhoto(view) {
                const question = view.question;
                stats({current: question.question_number, total: question.question_count, points: view.score});
                const head = el('div', undefined, 'question-top');
                head.append(el('span', 'УЗНАЁШЬ?', 'eyebrow'), countdown(Date.parse(question.ends_at) / 1000, question.closed)); stage.append(head);
                stage.append(el('h1', 'Что скрывается\nна картинке?', 'play-question'), picture(question.image_url));
                if (question.mask) stage.append(el('p', question.mask, 'photo-mask'));
                if (view.last_result) {
                    const result = view.last_result, verdict = el('section', undefined, `play-verdict ${result.correct ? 'is-correct' : ''}`);
                    verdict.append(el('strong', result.correct ? 'Угадал! Следующая картинка уже здесь.' : 'Время вышло. Идём дальше.'),
                        el('span', result.correct ? `+${number(result.points)} баллов` : `Ответ: ${result.answer}`)); stage.append(verdict);
                }
                if (question.feedback === 'almost') stage.append(el('p', 'Очень близко — образ верный, собери точное слово.', 'photo-hint'));
                else if (question.feedback === 'wrong') stage.append(el('p', 'Пока мимо. Посмотри, какие два образа соединяются.', 'photo-hint'));
                if (!question.closed) inputForm('Твой ответ', question.round_id, false, true);
                else stage.append(hostLine('Этот фото-вопрос уже закрыт. Готовим следующий.'));
                stage.append(el('p', 'Картинка загружена из общей игровой сессии, без копии сообщения Telegram.', 'play-footnote'));
                const exit = el('details', undefined, 'round-exit'); exit.append(el('summary', 'Завершить раунд'), el('p', 'Уже полученные баллы сохранятся.'));
                exit.append(button('Да, завершить', stopPhotoDirect, 'quiet')); stage.append(exit);
            }
            function sharedPhotoResult(view) {
                const complete = view.status === 'finished';
                stage.append(el('span', complete ? 'ФОТО-СЕРИЯ ЗАВЕРШЕНА' : 'ФОТО-СЕРИЯ ОСТАНОВЛЕНА', 'eyebrow'),
                    el('h1', complete ? 'Образы сложились.' : 'Продолжим в другой раз.', 'result-title'));
                const score = el('div', undefined, 'result-score'); score.append(el('strong', number(view.score)), el('span', 'баллов за серию')); stage.append(score);
                stage.append(el('p', `${view.correct} правильных из ${view.game.total}`, 'previous-answer'));
                if (view.last_result?.answer) stage.append(hostLine(`Последний ответ: ${view.last_result.answer}`));
                stage.append(button('Сыграть ещё', () => onReplay('/photo_quiz'), 'primary play-primary'), button('Мой прогресс', onProfile, 'quiet play-secondary'));
            }
            function result(view) {
                const game = view.game, complete = game.status === 'completed';
                stage.append(el('span', complete ? 'РАУНД ЗАВЕРШЁН' : 'РАУНД ОСТАНОВЛЕН', 'eyebrow'), el('h1', complete ? 'Ещё одна история\nв копилку.' : 'Продолжим в другой раз.', 'result-title'));
                const score = el('div', undefined, 'result-score'); score.append(el('strong', `${Number(game.points) > 0 ? '+' : ''}${number(game.points)}`), el('span', 'баллов за этот раунд')); stage.append(score);
                const total = el('div', undefined, 'result-facts'); total.append(el('span', `${game.correct} правильных из ${game.total}`), el('span', `${game.total ? Math.round(game.correct / game.total * 100) : 0}% точность`)); stage.append(total);
                stage.append(hostLine(game.correct ? 'Хорошая игра. Пара неожиданных фактов — и день уже интереснее.' : 'Любопытство важнее идеального счёта. Сыграем ещё?'));
                if (view.question?.feedback) { const review = el('details', undefined, 'round-options'); review.append(el('summary', 'Последний вопрос и объяснение'), el('p', view.question.poll.question)); const answer = view.question.feedback.answer; if (Number.isInteger(answer)) review.append(el('strong', view.question.poll.options[answer])); if (view.question.feedback.explanation) review.append(el('p', clean(view.question.feedback.explanation))); stage.append(review); }
                stage.append(button('Сыграть ещё', () => onReplay(view.kind === 'photo' ? '/photo_quiz' : '/quiz'), 'primary play-primary'), button('Мой прогресс', onProfile, 'quiet play-secondary'));
            }
            function render() {
                if (!snapshot || !active) return;
                if (starting) { stage.replaceChildren(hostLine('Готовлю твою игру. Сейчас начнём.')); return; }
                if (directPhoto?.question) {
                    const hash = JSON.stringify([directPhoto, snapshot.connected, busy]); if (hash === lastHash) return;
                    lastHash = hash; stage.replaceChildren(); mode.textContent = 'Фото-загадки'; sharedPhoto(directPhoto); tick(); return;
                }
                if (directPhoto) {
                    const hash = JSON.stringify([directPhoto, busy]); if (hash === lastHash) return;
                    lastHash = hash; stage.replaceChildren(); mode.textContent = 'Фото-загадки'; sharedPhotoResult(directPhoto); return;
                }
                if (direct?.question) {
                    const hash = JSON.stringify([direct, busy, chosen]); if (hash === lastHash) return;
                    const directKey = direct.question.round_id || direct.question.poll_id;
                    if (directKey !== questionKey) { chosen = null; questionKey = directKey; }
                    lastHash = hash; stage.replaceChildren(); mode.textContent = 'Классический квиз'; sharedQuestion(direct); tick(); return;
                }
                current = model(snapshot, preferred);
                const hash = JSON.stringify([current, snapshot.photo_round, snapshot.connected, busy, chosen]); if (hash === lastHash) return;
                const key = current.question?.poll?.id || snapshot.photo_round || current.menu?.id || current.game?.key;
                const input = stage.querySelector('input'), focus = input && input === document.activeElement;
                const optionsOpen = stage.querySelector('.round-options')?.open;
                if (key !== questionKey) { chosen = null; draft = ''; questionKey = key; } else if (input) draft = input.value;
                lastHash = hash; stage.replaceChildren(); mode.textContent = current.kind === 'photo' ? 'Фото-загадки' : 'Классический квиз';
                if (current.phase === 'setup') setup(current);
                else if (current.phase === 'result') result(current);
                else if (['question', 'photo', 'waiting'].includes(current.phase)) {
                    stats(current.game);
                    if (current.phase === 'question') question(current);
                    else if (current.phase === 'photo' && current.question) {
                        const roundActive = current.game.phase === 'active' && !!snapshot.photo_round;
                        const head = el('div', undefined, 'question-top'); head.append(el('span', 'УЗНАЁШЬ?', 'eyebrow'), countdown(Date.parse(current.game.question_started_at) / 1000 + current.game.time_limit, !roundActive)); stage.append(head);
                        stage.append(el('h1', 'Что скрывается\nна картинке?', 'play-question'), picture(current.question.media));
                        const mask = clean(current.question.text).match(/Слово:\s*([^\n]+)/); if (mask) stage.append(el('p', mask[1], 'photo-mask'));
                        for (const hint of current.hints) stage.append(el('p', clean(hint.text), 'photo-hint'));
                        if (roundActive) inputForm('Твой ответ', snapshot.photo_round, !snapshot.connected);
                        else stage.append(hostLine(current.game.outcome?.correct ? 'Узнал! Готовлю следующую картинку.' : 'Готовлю следующую картинку.'));
                    } else stage.append(hostLine('Выбираю следующий вопрос. Сейчас начнём.'));
                    const exit = el('details', undefined, 'round-exit'); exit.append(el('summary', 'Завершить раунд'), el('p', 'Уже полученные баллы сохранятся.'));
                    exit.append(button('Да, завершить', () => send({type: 'command', value: current.kind === 'photo' ? '/stop_photo_quiz' : '/stopquiz'}), 'quiet')); stage.append(exit);
                } else { stage.append(hostLine('Готов, когда готов ты. Выбирай игру — начнём.')); stage.append(button('Выбрать игру', onHome, 'primary play-primary')); }
                if (busy || !snapshot.connected) stage.querySelectorAll('button').forEach(b => { b.disabled = true; });
                if (optionsOpen && current.phase === 'setup' && stage.querySelector('.round-options')) stage.querySelector('.round-options').open = true;
                if (focus) stage.querySelector('input')?.focus({preventScroll: true});
                tick();
            }
            function tick() {
                stage.querySelectorAll('[data-deadline]').forEach(clock => {
                    const remaining = Math.max(0, Math.ceil(Number(clock.dataset.deadline) - (Date.now() + offset) / 1000));
                    clock.textContent = clock.dataset.closed === 'true' ? '✓' : Number.isFinite(remaining) ? `${remaining} с` : '…';
                    clock.classList.toggle('urgent', remaining <= 5 && clock.dataset.closed !== 'true');
                    if (!remaining && clock.dataset.closed !== 'true') { stage.querySelectorAll('.play-option, .confirm-answer, .play-answer-form button').forEach(b => { b.disabled = true; }); }
                });
            }
            async function refresh(renderPage = true) {
                if (!active) return; clearTimeout(timer);
                try {
                    const [data, shared, sharedPhotoView] = await Promise.all([
                        request('/api/mini/runtime'),
                        preferred === 'photo' || !chatId ? Promise.resolve(null) : request(`/api/mini/classic/chats/${chatId}/sync`, {method: 'POST'}).catch(error => error.status === 404 ? (direct?.status && direct.status !== 'active' ? direct : null) : Promise.reject(error)),
                        preferred === 'classic' || !chatId ? Promise.resolve(null) : request(`/api/mini/photo/chats/${chatId}/current`).catch(error => error.status === 404 ? null : Promise.reject(error)),
                    ]);
                    if (!active) return; snapshot = data; direct = shared; directPhoto = sharedPhotoView; offset = data.server_time * 1000 - Date.now();
                    status.textContent = direct || directPhoto ? '' : data.connected ? '' : 'Связь с ведущим прервалась. Попробуем подключиться снова.';
                    if (pending) { const receipt = data.requests.find(r => r.id === pending.request_id); if (receipt && !['pending', 'running'].includes(receipt.status)) { busy = false; starting = false; pending = null; notice.textContent = receipt.error || receipt.notice || ''; } }
                    if (renderPage) render();
                } catch (error) { if (active) { status.textContent = error.message; stage.querySelectorAll('button').forEach(b => { b.disabled = true; }); lastHash = ''; } }
                finally { if (active) timer = setTimeout(refresh, document.hidden ? 10000 : busy ? 1000 : 2000); }
            }
            async function sendDirect(questionId, selectedOption, internalRound) {
                if (!active || busy) return;
                busy = true; chosen = selectedOption; selection(); notice.textContent = 'Сохраняю ответ…'; render();
                try {
                    const payload = {selected_option: selectedOption, command_id: crypto.randomUUID()};
                    payload[internalRound ? 'round_id' : 'poll_id'] = questionId;
                    direct = await request(`/api/mini/classic/chats/${chatId}/answer`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)});
                    notice.textContent = '';
                } catch (error) { notice.textContent = error.message; }
                finally { busy = false; lastHash = ''; await refresh(); }
            }
            async function startDirect() {
                if (!active || busy) return;
                busy = true; starting = true; notice.textContent = 'Готовлю вопросы…'; render();
                try {
                    direct = await request(`/api/mini/classic/chats/${chatId}/start`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({command_id: crypto.randomUUID()})});
                    starting = false; notice.textContent = '';
                } catch (error) { starting = false; notice.textContent = error.message; }
                finally { busy = false; lastHash = ''; await refresh(); }
            }
            async function stopDirect() {
                if (!active || busy || direct?.revision === undefined) return;
                busy = true; notice.textContent = 'Завершаю раунд…'; render();
                try {
                    direct = await request(`/api/mini/classic/chats/${chatId}/stop`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({command_id: crypto.randomUUID(), expected_revision: direct.revision})});
                    notice.textContent = 'Раунд завершён. Все баллы сохранены.';
                } catch (error) { notice.textContent = error.message; }
                finally { busy = false; lastHash = ''; render(); }
            }
            async function sendPhotoDirect(roundId, answer) {
                if (!active || busy) return;
                busy = true; selection(); notice.textContent = 'Проверяю ответ…'; render();
                try {
                    directPhoto = await request(`/api/mini/photo/chats/${chatId}/answer`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({round_id: roundId, answer, command_id: crypto.randomUUID()})});
                    draft = ''; notice.textContent = directPhoto.verdict === 'correct' ? 'Есть! Ответ сохранён.' : '';
                } catch (error) { notice.textContent = error.message; }
                finally { busy = false; lastHash = ''; await refresh(); }
            }
            async function startPhotoDirect() {
                if (!active || busy) return;
                busy = true; starting = true; notice.textContent = 'Раскладываю фото-загадки…'; render();
                try {
                    directPhoto = await request(`/api/mini/photo/chats/${chatId}/start`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({command_id: crypto.randomUUID()})});
                    starting = false; notice.textContent = '';
                } catch (error) { starting = false; notice.textContent = error.message; }
                finally { busy = false; lastHash = ''; await refresh(); }
            }
            async function stopPhotoDirect() {
                if (!active || busy || directPhoto?.revision === undefined) return;
                busy = true; notice.textContent = 'Завершаю фото-серию…'; render();
                try {
                    directPhoto = await request(`/api/mini/photo/chats/${chatId}/stop`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({command_id: crypto.randomUUID(), expected_revision: directPhoto.revision})});
                    notice.textContent = 'Серия завершена. Баллы сохранены.';
                } catch (error) { notice.textContent = error.message; }
                finally { busy = false; lastHash = ''; render(); }
            }
            async function send(action) {
                if (!active || busy) return;
                busy = true; pending = {...action, request_id: crypto.randomUUID()}; selection(); notice.textContent = 'Секунду…'; render();
                const transmit = async () => {
                    try { await request('/api/mini/runtime/actions', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(pending)}); await refresh(); }
                    catch (error) {
                        if (!active) return;
                        if (error.status) { busy = false; starting = false; pending = null; notice.textContent = error.message; await refresh(); }
                        else { notice.replaceChildren(el('p', error.message), button('Проверить отправку', () => { if (pending) transmit(); }, 'quiet')); }
                    }
                }; await transmit();
            }
            stage.append(hostLine('Филиныч раскладывает карточки…'));
            await refresh(false);
            if (command === '/quiz' && active && snapshot) await startDirect();
            else if (command === '/photo_quiz' && active && snapshot) await startPhotoDirect();
            else if (command && active && snapshot) await send({type: 'command', value: command});
            else render();
            if (active) ticker = setInterval(tick, 500);
        },
    };
})();
