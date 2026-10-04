(() => {
    'use strict';
    let dispose = () => {};
    const node = (tag, text, className) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (className) n.className = className; return n; };
    function plain(text) {
        // Telegram formatting is display text, never HTML inserted into the page.
        return String(text || '').replace(/\\([_\[\]()~`>#+\-=|{}.!*])/g, '$1').replace(/<\/?(?:b|i|code|pre|u|s)>/g, '').replace(/\*([^*]+)\*/g, '$1').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');
    }
    window.QuizGame = {
        stop() { dispose(); dispose = () => {}; window.QuizPlay?.stop(); },
        async mount({host, request, media, onHome, command, selection, settings = false}) {
            window.QuizGame.stop();
            let active = true, timer, ticker, busy = false, lastHash = '', snapshot, pending = null, inputRound = null, lastMessage = null, serverOffset = 0;
            const images = new Map();
            const heading = node('div', undefined, 'game-heading');
            heading.append(node('span', settings ? 'Профиль / Настройки' : 'Играем вместе с Филинычем', 'eyebrow'), node('h1', settings ? 'Игра и расписание' : 'Твоя игра'));
            const back = node('button', settings ? 'К настройкам' : 'К играм', 'quiet'); back.type = 'button'; back.onclick = onHome; heading.append(back);
            const status = node('p', 'Подключаемся к игре…', 'muted'); status.setAttribute('role', 'status');
            const stage = node('section', undefined, 'game-stage');
            const feedback = node('p', '', 'game-feedback'); feedback.setAttribute('role', 'status');
            const controls = node('div', undefined, 'game-tools');
            for (const [label, value] of settings ? [] : [['Главное меню', '/start'], ['Остановить квиз', '/stopquiz'], ['Остановить фото', '/stop_photo_quiz']]) {
                const b = node('button', label, 'quiet'); b.type = 'button'; b.onclick = () => send({type: 'command', value}); controls.append(b);
            }
            host.append(heading, status, stage, feedback, controls);
            dispose = () => { active = false; clearTimeout(timer); clearInterval(ticker); images.forEach(url => URL.revokeObjectURL(url)); };
            async function send(action) {
                if (busy || !active) return;
                busy = true; selection(); feedback.textContent = 'Передаём действие…';
                stage.querySelectorAll('button').forEach(b => { b.disabled = true; });
                pending = {...action, request_id: crypto.randomUUID()};
                try {
                    await request('/api/mini/runtime/actions', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(pending)});
                    await refresh();
                } catch (error) {
                    if (error.status) { busy = false; pending = null; lastHash = ''; feedback.textContent = error.message; await refresh(); return; }
                    // Keep the SAME request ID: an ambiguous response must not start a second game.
                    feedback.replaceChildren(node('span', error.message + ' '));
                    const retry = node('button', 'Проверить / повторить', 'quiet');
                    retry.onclick = async () => { try { await request('/api/mini/runtime/actions', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(pending)}); await refresh(); } catch (e) { feedback.firstChild.textContent = e.message + ' '; } };
                    feedback.append(retry);
                }
            }
            function render(data) {
                const cards = data.messages.filter(m => (m.text || m.poll || m.media || m.buttons?.some(row => row.length)) &&
                    (settings || !m.buttons?.some(row => row.some(b => b.data?.startsWith('admcfg_')))));
                const hash = JSON.stringify([cards, data.photo_round]);
                if (hash === lastHash) return;
                const oldInput = stage.querySelector('input'), typing = oldInput === document.activeElement;
                const draft = inputRound === data.photo_round ? oldInput?.value || '' : '';
                inputRound = data.photo_round;
                lastHash = hash; stage.replaceChildren();
                if (!cards.length) stage.append(node('p', 'Выбери игру на главной или открой меню.', 'empty'));
                // Keep earlier notices available without burying the active question/menu.
                const recent = cards.slice(-12);
                for (const item of recent) {
                    const card = node('article', undefined, 'game-card' + (item.poll ? ' question-card' : ''));
                    card.dataset.message = item.id;
                    if (item.text) card.append(node('p', plain(item.text), 'game-copy'));
                    if (item.media) {
                        const image = node('img'); image.alt = 'Изображение фото-загадки'; image.className = 'game-photo'; card.append(image);
                        if (images.has(item.media)) image.src = images.get(item.media);
                        else media(item.media).then(blob => { if (!active) return; const url = URL.createObjectURL(blob); images.set(item.media, url); image.src = url; }).catch(() => { image.alt = 'Не удалось загрузить фото. Проверь подключение.'; });
                    }
                    if (item.poll) {
                        const poll = item.poll, result = item.feedback;
                        const meta = node('div', undefined, 'question-meta'); meta.append(node('span', result ? 'Ответ принят' : 'Выбери один ответ', 'eyebrow'));
                        const clock = node('span', '', 'question-clock'); clock.dataset.deadline = poll.ends_at; clock.dataset.closed = poll.closed || !!result; meta.append(clock); card.append(meta);
                        card.append(node('h2', poll.question));
                        const answers = node('div', undefined, 'answer-options');
                        poll.options.forEach((option, index) => {
                            const b = node('button', undefined, 'answer-option'); b.type = 'button';
                            b.append(node('span', String.fromCharCode(65 + index), 'answer-letter'), node('span', option));
                            if (result && index === result.answer) b.classList.add('correct');
                            if (result && index === result.selected && !result.correct) b.classList.add('incorrect');
                            b.disabled = busy || poll.closed || !!result;
                            b.onclick = () => send({type: 'vote', value: index, message_id: item.id}); answers.append(b);
                        }); card.append(answers);
                        if (result) {
                            card.append(node('p', (result.correct ? 'Верно! ' : 'В этот раз не угадал. ') + `${Number(result.points) > 0 ? '+' : ''}${Number(result.points)} баллов`, result.correct ? 'answer-result correct-text' : 'answer-result'));
                            if (result.explanation) card.append(node('p', plain(result.explanation), 'muted'));
                        } else if (poll.closed) card.append(node('p', 'Время на этот вопрос закончилось.', 'muted'));
                    }
                    if (item.buttons?.length) {
                        const keyboard = node('div', undefined, 'game-keyboard');
                        for (const row of item.buttons) {
                            const line = node('div', undefined, 'keyboard-row');
                            for (const b of row) {
                                // Global settings have one entry point: Profile → Settings.
                                if (b.data === 'nav:settings') continue;
                                const button = node('button', b.text, b.style === 'success' || b.style === 'primary' ? 'primary' : b.style === 'danger' ? 'danger' : ''); button.type = 'button'; button.disabled = busy;
                                button.onclick = b.data === 'nav:home' ? onHome : () => send({type: 'callback', value: b.data, message_id: item.id, revision: item.revision}); line.append(button);
                            }
                            if (line.childElementCount) keyboard.append(line);
                        } card.append(keyboard);
                    }
                    stage.append(card);
                }
                const form = node('form', undefined, 'game-input');
                form.hidden = !data.photo_round && !/введи|введите|отправьте|напишите/i.test(recent.at(-1)?.text || '');
                const label = node('label', data.photo_round ? 'Твой ответ на фото-загадку' : 'Значение настройки, если бот попросил его ввести');
                const input = node('input'); input.maxLength = 300; input.autocomplete = 'off'; input.placeholder = data.photo_round ? 'Что изображено на фото?' : 'Например, число или время';
                input.value = draft;
                label.append(input); const submit = node('button', 'Отправить', 'primary'); submit.type = 'submit';
                form.append(label, submit); form.onsubmit = event => { event.preventDefault(); if (input.value.trim()) send({type: 'text', value: input.value.trim(), round: data.photo_round}); }; stage.append(form);
                if (typing) input.focus({preventScroll: true});
                else if (recent.length && lastMessage !== recent.at(-1).id) stage.querySelector(`[data-message="${recent.at(-1).id}"]`)?.scrollIntoView({block: 'nearest', behavior: 'smooth'});
                lastMessage = recent.at(-1)?.id;
            }
            async function refresh() {
                if (!active) return;
                clearTimeout(timer);
                try {
                    const data = await request('/api/mini/runtime'); if (!active) return; snapshot = data; serverOffset = data.server_time * 1000 - Date.now();
                    status.textContent = data.connected ? 'Те же вопросы и правила, что в боте. Прогресс общий.' : 'Бот сейчас не подключён. Игра продолжится после его запуска.';
                    if (pending) {
                        const receipt = data.requests.find(r => r.id === pending.request_id);
                        if (receipt && !['pending', 'running'].includes(receipt.status)) { busy = false; pending = null; lastHash = ''; feedback.textContent = receipt.error || receipt.notice || ''; }
                    }
                    render(data);
                } catch (error) { if (active) status.textContent = error.message; }
                finally { if (active) timer = setTimeout(refresh, document.hidden ? 6000 : 1600); }
            }
            ticker = setInterval(() => {
                if (!snapshot) return;
                stage.querySelectorAll('[data-deadline]').forEach(clock => {
                    const seconds = Math.max(0, Math.ceil(Number(clock.dataset.deadline) - (Date.now() + serverOffset) / 1000));
                    clock.textContent = clock.dataset.closed === 'true' ? '✓' : `${seconds} с`;
                    if (!seconds) clock.closest('article').querySelectorAll('.answer-option').forEach(b => { b.disabled = true; });
                });
            }, 500);
            await refresh();
            if (command && active) await send({type: 'command', value: command});
        },
    };
})();
