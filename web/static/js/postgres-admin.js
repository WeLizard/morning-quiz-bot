// PostgreSQL adapters for the existing panel. Untrusted values use textContent.
(() => {
    const element = (tag, text, className) => {
        const node = document.createElement(tag);
        if (text !== undefined) node.textContent = text;
        if (className) node.className = className;
        return node;
    };
    // Small, local outline icons; no icon font, CDN or generated raster asset.
    const iconPaths = {
        dashboard: ['M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z'],
        questions: ['M4 4h12a3 3 0 0 1 3 3v14H7a3 3 0 0 1-3-3z', 'M4 17h15M8 8h7M8 12h5'],
        users: ['M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M22 21v-2a4 4 0 0 0-3-3.87', 'M13 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0M17 3a4 4 0 0 1 0 8'],
        chats: ['M21 11.5a8.4 8.4 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.4 8.4 0 0 1-3.8-.9L3 21l1.9-5.7a8.4 8.4 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.4 8.4 0 0 1 3.8-.9h.5a8.5 8.5 0 0 1 8 8z'],
        'photo-quiz': ['M3 3h18v18H3zM3 17l6-6 5 5 3-3 4 4', 'M9 7h.01'],
        analytics: ['M3 3v18h18M7 14l4-4 4 3 6-8'],
        clock: ['M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0M12 7v5l3 2'],
        refresh: ['M20 7v5h-5M4 17v-5h5', 'M6.1 7a7 7 0 0 1 11.5-2L20 8M4 16l2.4 3A7 7 0 0 0 18 17'],
        arrow: ['M5 12h14m-5-5 5 5-5 5'],
    };
    function icon(name) {
        const node = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        for (const [key, value] of Object.entries({viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', 'stroke-width': '1.7', 'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'aria-hidden': 'true', class: 'pg-icon'})) node.setAttribute(key, value);
        for (const path of iconPaths[name] || iconPaths.dashboard) {
            const child = document.createElementNS('http://www.w3.org/2000/svg', 'path'); child.setAttribute('d', path); node.append(child);
        }
        return node;
    }
    function brandMark() {
        const mark = element('span', undefined, 'mq-mark'); mark.setAttribute('aria-hidden', 'true'); mark.append(element('span')); return mark;
    }
    function brand() {
        const lockup = element('div', undefined, 'mq-brand'); const copy = element('span', undefined, 'mq-brand-copy');
        copy.append(element('small', 'MORNING QUIZ'), element('strong', 'За кулисами')); lockup.append(brandMark(), copy); return lockup;
    }
    const descriptions = {
        dashboard: 'Вопросы, игроки и расписание. Всё, что нужно за кулисами.',
        questions: 'Собирайте вопросы, которые хочется обсуждать после игры.',
        users: 'Участники и их прогресс — с актуальными баллами из базы.',
        chats: 'У каждого чата свой ритм. Настройте следующий квиз.',
        'photo-quiz': 'Вопросы в картинках, ответы и маленькие подсказки.',
        analytics: 'Как идут игры: участники, ответы и любимые категории.',
    };
    const button = (text, action, secondary = false) => {
        const node = element('button', text, `btn ${secondary ? 'btn-secondary' : 'btn-primary'}`);
        if (text.startsWith('Удалить')) node.className = 'btn btn-danger-outline';
        node.type = 'button'; node.addEventListener('click', action); return node;
    };
    const notice = (parent, text) => parent.appendChild(element('p', text, 'pg-note'));
    async function api(path, options) {
        let response;
        try { response = await fetch(path, options); }
        catch { throw new Error('Нет связи с панелью. Проверьте подключение и повторите действие в этой же форме.'); }
        let data;
        try { data = await response.json(); }
        catch { throw new Error('Сервер не смог завершить запрос. Введённые данные оставлены в форме; повторите позже.'); }
        if (!response.ok) {
            const detail = typeof data.detail === 'string' ? data.detail : 'Проверьте значения полей';
            const specificConflict = path.startsWith('/api/photo-quiz/uploads/') || path.endsWith('/moderation') || path.endsWith('/reset-progress');
            throw new Error(response.status === 409 && !specificConflict ? 'Данные уже изменились. Перезагрузите форму; введённые значения пока сохранены здесь.' : detail);
        }
        return {data, response};
    }
    const put = (path, value) => api(path, {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(value)});
    function screen(id, title, refresh) {
        const section = document.getElementById(id);
        const header = element('div', undefined, 'content-header');
        const copy = element('div', undefined, 'pg-header-copy');
        const heading = element('h1', title, 'page-title'); heading.tabIndex = -1;
        copy.append(element('span', 'MORNING QUIZ / УПРАВЛЕНИЕ', 'pg-eyebrow'), heading, element('p', descriptions[id], 'pg-subtitle'));
        const reload = button('Обновить', refresh, true); reload.prepend(icon('refresh'));
        header.append(copy, reload);
        const body = element('div'); section.replaceChildren(header, body);
        const loading = element('p', 'Загрузка…', 'pg-note pg-loading'); loading.setAttribute('role', 'status'); body.append(loading);
        document.title = `${title} · Morning Quiz`;
        return body;
    }
    function field(form, label, value, type = 'text', options = {}) {
        const group = element('label', undefined, 'pg-field');
        group.append(element('span', label));
        const input = element(type === 'textarea' ? 'textarea' : 'input', undefined, 'form-input');
        if (type !== 'textarea') input.type = type;
        if (type === 'checkbox') { input.checked = Boolean(value); input.className = ''; }
        else input.value = value ?? '';
        Object.assign(input, options); group.append(input); form.append(group); return input;
    }
    function modal(title, build, reload, submitLabel = 'Сохранить') {
        const dialog = element('dialog', undefined, 'pg-dialog');
        const heading = element('h2', title); heading.id = `pg-dialog-title-${++dialogIndex}`;
        dialog.setAttribute('aria-labelledby', heading.id);
        const form = element('form');
        const error = element('p', '', 'pg-error'); error.setAttribute('role', 'alert');
        const actions = element('div', undefined, 'pg-actions');
        const save = button(submitLabel, () => {}); save.type = 'submit';
        actions.append(button('Отмена', () => dialog.close(), true), save);
        if (reload) actions.prepend(button('Загрузить заново', () => { dialog.close(); reload(); }, true));
        dialog.append(heading, form); document.body.append(dialog);
        const submit = build(form);
        form.append(error, actions);
        form.addEventListener('submit', async event => {
            event.preventDefault(); save.disabled = true; error.textContent = '';
            try { await submit(); dialog.close(); }
            catch (failure) { error.textContent = failure.message; }
            finally { save.disabled = false; }
        });
        dialog.addEventListener('close', () => dialog.remove()); dialog.showModal();
    }
    let dialogIndex = 0;
    function selectField(form, label, value, options) {
        const group = element('label', label, 'pg-field');
        const input = element('select', undefined, 'form-input'); input.setAttribute('aria-label', label);
        for (const [key, title] of options) { const option = element('option', title); option.value = key; input.append(option); }
        input.value = value; group.append(input); form.append(group); return input;
    }
    const grid = parent => parent.appendChild(element('div', undefined, 'pg-grid'));
    const card = (parent, title) => {
        const node = element('article', undefined, 'card pg-card'); node.append(element('h2', title)); parent.append(node); return node;
    };
    const fail = (body, error) => {
        const message = element('p', error.message, 'pg-error'); message.setAttribute('role', 'alert'); body.replaceChildren(message);
    };
    function metric(name, value, caption, symbol) {
        const item = element('article', undefined, 'card pg-metric');
        const head = element('div', undefined, 'pg-metric-head'); head.append(element('span', name), icon(symbol));
        item.append(head, element('strong', new Intl.NumberFormat('ru-RU').format(value), 'pg-metric-value'));
        if (caption) item.append(element('span', caption, 'pg-metric-caption'));
        return item;
    }
    function directory(parent, rows, label, searchable, renderItem) {
        const search = field(parent, label, '', 'search');
        const results = element('div'); parent.append(results); let page = 0;
        const render = () => {
            const query = search.value.trim().toLocaleLowerCase();
            const filtered = rows.filter(row => searchable(row).toLocaleLowerCase().includes(query));
            results.replaceChildren();
            notice(results, `Найдено: ${filtered.length} из ${rows.length}. Страница ${page + 1} из ${Math.max(1, Math.ceil(filtered.length / 24))}`);
            if (!filtered.length) notice(results, 'Нет совпадений. Измените поисковый запрос.');
            const cards = grid(results);
            filtered.slice(page * 24, (page + 1) * 24).forEach(row => renderItem(cards, row));
            const paging = element('div', undefined, 'pg-actions');
            if (page) paging.append(button('Предыдущие', () => { page--; render(); }, true));
            if ((page + 1) * 24 < filtered.length) paging.append(button('Следующие', () => { page++; render(); }, true));
            results.append(paging);
        };
        search.addEventListener('input', () => { page = 0; render(); }); render();
    }
    const profileDate = value => value ? `${new Date(value).toLocaleString('ru-RU', {timeZone: 'UTC'})} UTC` : 'Нет данных';
    function profileTable(parent, captionText, columns, rows) {
        const wrapper = element('div', undefined, 'pg-table-wrap'); wrapper.tabIndex = 0;
        wrapper.setAttribute('role', 'region'); wrapper.setAttribute('aria-label', captionText);
        const table = element('table', undefined, 'pg-table'); table.append(element('caption', captionText));
        const head = element('thead'); const header = element('tr');
        columns.forEach(name => { const cell = element('th', name); cell.scope = 'col'; header.append(cell); });
        head.append(header); table.append(head); const body = element('tbody');
        rows.forEach(values => { const row = element('tr'); values.forEach(value => row.append(element('td', String(value)))); body.append(row); });
        table.append(body); wrapper.append(table); parent.append(wrapper);
        if (!rows.length) notice(parent, 'Пока нет данных.');
    }
    function openProfile(scope, id) {
        const dialog = element('dialog', undefined, 'pg-dialog pg-profile');
        const title = element('h2', 'Загрузка профиля…'); title.id = `pg-dialog-title-${++dialogIndex}`;
        dialog.setAttribute('aria-labelledby', title.id);
        const header = element('div', undefined, 'pg-profile-header');
        header.append(title, button('Закрыть', () => dialog.close(), true));
        const content = element('div'); dialog.append(header, content); document.body.append(dialog);
        dialog.addEventListener('close', () => dialog.remove()); dialog.showModal();
        let offset = 0, before = null, previous = [], loadVersion = 0;
        async function load() {
            const version = ++loadVersion;
            content.replaceChildren(element('p', 'Загрузка…', 'pg-note pg-loading'));
            const query = new URLSearchParams({members_offset: String(offset)});
            if (before) query.set('history_before', before);
            const path = `/api/${scope}/${id}/profile?${query}`;
            try {
                const [{data}, {data: access}] = await Promise.all([api(path), api(`/api/${scope}/${id}/moderation`)]);
                if (!dialog.isConnected || version !== loadVersion) return;
                content.replaceChildren(); title.textContent = data.name;
                notice(content, `${scope === 'users' ? 'Участник' : 'Чат'} · ID ${data.id} · срез ${profileDate(data.snapshot_at)}`);
                const metrics = element('div', undefined, 'pg-metrics'); content.append(metrics);
                for (const [name, value, hint, iconName] of [
                    ['Баллы', data.stats.score, 'Актуальный счёт', 'analytics'],
                    ['Ответы в квизе', data.stats.classic_answers, 'Классические опросы', 'questions'],
                    ['Верные ответы', data.stats.correct_answers_including_photo, 'Включая фото-квиз', 'photo-quiz'],
                    [scope === 'users' ? 'Чаты' : 'Участники', data.stats.memberships, 'В этом срезе', 'users'],
                ]) metrics.append(metric(name, value, hint, iconName));
                notice(content, `Первая активность: ${profileDate(data.stats.first_answer_at)}. Последняя: ${profileDate(data.stats.last_answer_at)}.`);
                const actions = element('div', undefined, 'pg-actions');
                const download = element('a', 'Экспорт страницы · JSON', 'btn btn-secondary');
                download.href = `${path}&download=true`; download.download = `${scope}-${id}-snapshot.json`;
                actions.append(download, button('Обновить профиль', load, true)); content.append(actions);
                const safety = element('details', undefined, 'pg-disclosure');
                safety.append(element('summary', access.blocked ? 'Доступ заблокирован · управление' : 'Доступ и безопасный сброс'));
                notice(safety, access.blocked ? `Блокировка действует. Причина: ${access.reason}` : 'Доступ к боту разрешён.');
                notice(safety, 'Блокировка действует только внутри бота — она не исключает человека из Telegram-группы.');
                const safetyActions = element('div', undefined, 'pg-actions'); safety.append(safetyActions);
                const reloadAll = async () => { await (scope === 'users' ? users() : chats()); await load(); };
                if (access.archived) notice(safety, 'Профиль находится в архиве. Восстановление сохраняет блокировку: доступ включается отдельным действием.');
                safetyActions.append(button(access.archived ? 'Восстановить профиль' : 'Удалить профиль в архив', () => modal('Архив профилей', form => {
                    notice(form, access.archived ? 'Профиль снова появится в списке. Блокировка пока останется.' : 'Профиль исчезнет из обычного списка. Очки, история, достижения и защита от повторного начисления сохраняются. Сначала заблокируйте профиль.');
                    const confirmation = field(form, `Введите ID: ${id}`, '', 'text', {required: true});
                    const actionId = crypto.randomUUID();
                    return async () => { await post(`/api/${scope}/${id}/archive`, {archived: !access.archived, expected_revision: access.revision, confirmation: confirmation.value, action_id: actionId}); await reloadAll(); };
                }, load, access.archived ? 'Восстановить' : 'Перенести в архив'), true));
                if (!access.archived) safetyActions.append(button(access.blocked ? 'Разблокировать' : 'Заблокировать', () => {
                    const actionId = crypto.randomUUID();
                    modal(access.blocked ? 'Разрешить доступ к боту' : 'Заблокировать доступ к боту', form => {
                        notice(form, `${data.name} · ID ${id}`);
                        notice(form, access.blocked ? 'Доступ будет разрешён. Расписание снова сможет запускать новые игры; прерванные игры не возобновятся.' : scope === 'chats' ? 'Текущие игры будут прерваны, расписание приостановлено без удаления настроек.' : 'Команды и начисления будут запрещены, личная фото-серия прервана. Общий квиз продолжится для остальных игроков.');
                        const reason = field(form, 'Причина изменения доступа', '', 'textarea', {required: true, maxLength: 500});
                        return async () => {
                            await put(`/api/${scope}/${id}/moderation`, {blocked: !access.blocked, reason: reason.value.trim(), expected_revision: access.revision, action_id: actionId});
                            await reloadAll();
                        };
                    }, () => load(), access.blocked ? 'Разблокировать' : 'Подтвердить блокировку');
                }, true));
                const resetError = element('p', '', 'pg-error'); resetError.setAttribute('role', 'alert'); safety.append(resetError);
                const previewButton = button('Предпросмотр сброса', async () => {
                    previewButton.disabled = true; resetError.textContent = '';
                    try {
                        const {data: preview} = await api(`/api/${scope}/${id}/reset-preview`);
                        if (preview.active_sessions.length) throw new Error('Сброс недоступен: в затронутых чатах ещё идёт игра. Дождитесь завершения.');
                        const actionId = crypto.randomUUID();
                        modal('Сброс текущего прогресса', form => {
                            notice(form, `${preview.name} · ID ${id}. Затронуто записей прогресса: ${preview.members.length}; участников: ${preview.users.length}.`);
                            notice(form, scope === 'users' ? 'Обнуляет текущий прогресс этого участника во всех чатах и его глобальный счёт.' : 'Обнуляет текущий прогресс всех участников только в этом чате. Глобальные итоги уменьшатся на его вклад.');
                            const affected = element('details', undefined, 'pg-disclosure');
                            affected.append(element('summary', 'Какие записи будут сброшены')); form.append(affected);
                            profileTable(affected, 'Текущий прогресс перед сбросом', ['ID участника', 'ID чата', 'Баллы', 'Квиз-ответы'],
                                preview.members.slice(0, 50).map(row => [row.user_id, row.chat_id, row.score, row.answered_count]));
                            if (preview.members.length > 50) notice(affected, `Показаны первые 50 из ${preview.members.length}. Сброс затронет все указанные в общем количестве записи.`);
                            notice(form, 'Очки, счётчики ответов и текущая серия станут нулевыми. История ответов, защита от повторного начисления, достижения, рекорд серии и даты активности сохранятся.');
                            notice(form, 'До и после операции сохраняется квитанция. Автоматической отмены нет; не подтверждайте, если сброс не нужен.');
                            const confirmation = field(form, `Введите ID ${id} для подтверждения`, '', 'text', {required: true, maxLength: 20, autocomplete: 'off'});
                            return async () => {
                                await api(`/api/${scope}/${id}/reset-progress`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({expected_version: preview.version, confirmation: confirmation.value, action_id: actionId})});
                                await reloadAll();
                            };
                        }, () => load(), 'Подтвердить сброс');
                    } catch (failure) { resetError.textContent = failure.message; }
                    finally { previewButton.disabled = false; }
                }, true);
                safetyActions.append(previewButton);
                if (access.actions.length) {
                    notice(safety, 'Последние 20 операций · квитанции с состоянием до и после:');
                    const receipts = element('ul');
                    for (const action of access.actions) {
                        const row = element('li'); const link = element('a', `${action.kind === 'reset' ? 'Сброс прогресса' : 'Изменение доступа'} · ${profileDate(action.created_at)}`);
                        link.href = `/api/admin-actions/${action.id}`; link.download = `admin-action-${action.id}.json`; row.append(link); receipts.append(row);
                    }
                    safety.append(receipts);
                }
                content.append(safety);
                notice(content, data.export_scope);
                if (scope === 'chats') {
                    notice(content, data.chat.daily_quiz_enabled ? 'Ежедневная викторина включена.' : 'Ежедневная викторина выключена.');
                    actions.append(button('Переименовать', () => modal('Название чата в панели', form => {
                        notice(form, 'Меняет название в локальных данных бота. Название группы в Telegram не изменяется.');
                        const input = field(form, 'Новое название', data.name, 'text', {required: true, maxLength: 255});
                        return async () => {
                            await put(`/api/chats/${id}/title?expected_revision=${data.chat.settings_revision}`, {title: input.value.trim()});
                            await chats(); await load();
                        };
                    }), true));
                    profileTable(content, 'Активные игры', ['Режим', 'Начало', 'Дедлайн'], data.active_sessions.map(game => [game.kind === 'photo' ? 'Фото-квиз' : 'Квиз', profileDate(game.started_at), profileDate(game.ends_at)]));
                }
                const membership = data.memberships;
                profileTable(content, scope === 'users' ? 'Прогресс по чатам' : 'Участники чата',
                    [scope === 'users' ? 'Чат' : 'Участник', 'Баллы', 'Квиз-ответы', 'Верно, с фото', 'Серия / рекорд', 'Достижения'],
                    membership.items.map(row => [scope === 'users' ? `${row.chat_title} · ${row.chat_id}` : `${row.name} · ${row.user_id}`,
                        row.score, row.classic_answers, row.correct_answers_including_photo, `${row.current_streak} / ${row.max_streak}`,
                        [...row.milestone_codes, ...row.streak_codes].join(', ') || '—']));
                notice(content, membership.items.length ? `Записи ${offset + 1}–${offset + membership.items.length} из ${membership.total}.` : `На этой странице нет записей. Всего: ${membership.total}.`);
                const memberPaging = element('div', undefined, 'pg-actions');
                if (offset) memberPaging.append(button('Предыдущие участники/чаты', () => { offset = Math.max(0, offset - membership.limit); load(); }, true));
                if (membership.has_more) memberPaging.append(button('Следующие участники/чаты', () => { offset += membership.limit; load(); }, true));
                content.append(memberPaging);
                notice(content, data.history.notice);
                profileTable(content, 'Журнал ответов · UTC', ['Время', 'Участник / чат', 'Режим', 'Результат', 'Начислено'],
                    data.history.items.map(event => [profileDate(event.answered_at), scope === 'users' ? event.chat_title : event.name,
                        event.kind === 'photo' ? 'Фото-квиз' : event.kind === 'classic' ? 'Квиз' : 'Не указан',
                        event.is_correct === null ? 'Не указан' : event.is_correct ? 'Верно' : 'Неверно', event.points_delta]));
                const historyPaging = element('div', undefined, 'pg-actions');
                if (previous.length) historyPaging.append(button('Более новые ответы', () => { before = previous.pop(); load(); }, true));
                if (data.history.has_more) historyPaging.append(button('Более ранние ответы', () => { previous.push(before); before = data.history.next_cursor; load(); }, true));
                content.append(historyPaging);
            } catch (error) { if (dialog.isConnected && version === loadVersion) { fail(content, error); content.append(button('Повторить загрузку', load, true)); } }
        }
        load();
    }

    async function dashboard() {
        const body = screen('dashboard', 'Пульт ведущего', dashboard);
        try {
            const [{data: overview}, {data: bank}, {data: status}, {data: schedules}] = await Promise.all([
                api('/api/analytics/overview'), api('/api/bank/categories'), api('/api/storage/status'), api('/api/schedules/status')]);
            body.replaceChildren();
            const metrics = element('div', undefined, 'pg-metrics');
            const total = bank.categories.reduce((sum, category) => sum + category.count, 0);
            const invalid = bank.categories.reduce((sum, category) => sum + category.invalid, 0);
            for (const [name, value, caption, symbol] of [
                ['Вопросы в банке', total, `${bank.categories.length} категорий`, 'questions'],
                ['Участники', overview.users, 'Во всех чатах', 'users'],
                ['Чаты', overview.chats, 'В текущей базе', 'chats'],
                ['Ответы', overview.answers, 'Включая импортированные', 'analytics'],
            ]) {
                metrics.append(metric(name, value, caption, symbol));
            }
            body.append(metrics);
            const cards = element('div', undefined, 'pg-home-grid'); body.append(cards);
            const hero = element('article', undefined, 'card pg-card pg-hero');
            hero.append(brandMark(), element('span', 'В ЦЕНТРЕ ВНИМАНИЯ', 'pg-eyebrow'), element('h2', 'Хорошая игра начинается с вопроса.'));
            notice(hero, 'Добавляйте новые темы, редактируйте ответы и собирайте следующий квиз. Изменения появятся в новых играх.');
            const openBank = button('Открыть банк вопросов', () => showSection('questions')); openBank.append(icon('arrow')); hero.append(openBank); cards.append(hero);
            const worker = element('article', undefined, 'card pg-card pg-worker'); worker.append(icon('clock'), element('span', schedules.fresh ? 'Синхронизировано' : 'Нет подтверждения бота', `pg-badge ${schedules.fresh ? 'accent' : 'waiting'}`));
            worker.append(element('h2', 'У каждого чата свой ритм'));
            notice(worker, schedules.fresh ? `Последняя проверка: ${schedules.worker_status.checked_at}` : 'Расписание сохраняется в базе, но панель сама не запускает бота. Применение настроек подтвердится, когда он подключится.');
            worker.append(button('Настроить расписание', () => showSection('chats'), true)); cards.append(worker);
            if (invalid) notice(body, `${invalid} вопросов требуют проверки в редакторе. Исходные записи сохранены.`);
            const details = element('details', undefined, 'pg-disclosure'); details.append(element('summary', 'О локальной версии и доступных функциях'));
            notice(details, status.notice);
            notice(details, 'Блокировки и безопасный сброс доступны в профилях. Рассылки и управление процессом бота ещё не перенесены. Это локальная админка, не публичный Mini App.'); body.append(details);
        } catch (error) { fail(body, error); }
    }
    let showArchivedChats = false, showArchivedUsers = false;
    async function chats() {
        const body = screen('chats', 'Чаты и расписания', chats);
        try {
            const {data} = await api(`/api/chats?include_archived=${showArchivedChats}`); body.replaceChildren();
            const showArchived = field(body, 'Показывать также архивные чаты', showArchivedChats, 'checkbox');
            showArchived.addEventListener('change', () => { showArchivedChats = showArchived.checked; chats(); });
            if (!data.length) notice(body, 'В этой базе пока нет чатов.');
            directory(body, data, 'Поиск чата по названию или ID', chat => `${chat.title} ${chat.id}`, (cards, chat) => {
                const item = card(cards, chat.title);
                if (chat.archived) item.append(element('span', 'В архиве', 'pg-badge'));
                notice(item, `ID: ${chat.id} · участников: ${chat.users_count}`);
                notice(item, chat.daily_quiz_enabled ? 'Ежедневная викторина включена' : 'Ежедневная викторина выключена');
                const actions = element('div', undefined, 'pg-actions');
                actions.append(button('Профиль чата', () => openProfile('chats', chat.id), true), button('Настроить', () => editSettings(chat)), button('Сбросить настройки', () => resetSettings(chat), true));
                actions.append(button('Сбросить использование категорий', () => resetCategories(chat), true));
                item.append(actions);
            });
        } catch (error) { fail(body, error); }
    }
    async function editSettings(chat) {
        try {
            const {data: settings, response} = await api(`/api/chats/${chat.id}/settings`);
            const revision = response.headers.get('X-Settings-Revision');
            if (revision === null) throw new Error('Сервер не вернул версию настроек');
            const daily = settings.daily_quiz || {};
            modal(`Настройки · ${chat.title}`, form => {
                notice(form, `Версия ${revision}. При конфликте чужие изменения не будут перезаписаны.`);
                const questions = field(form, 'Вопросов в обычном квизе', settings.quiz?.num_questions ?? settings.default_num_questions ?? 10, 'number', {min: 1, max: 100, required: true});
                const seconds = field(form, 'Время ответа, секунд', settings.quiz?.open_period_seconds ?? settings.default_open_period_seconds ?? 60, 'number', {min: 5, max: 600, required: true});
                const ordinaryInterval = field(form, 'Интервал обычного квиза, секунд (0 — без паузы)', settings.quiz?.interval_seconds ?? settings.default_interval_seconds ?? 30, 'number', {min: 0, max: 86400, required: true});
                const announce = field(form, 'Анонсировать обычный квиз', settings.quiz?.announce ?? settings.default_announce_quiz ?? false, 'checkbox');
                const announceDelay = field(form, 'Задержка анонса, секунд', settings.quiz?.announce_delay_seconds ?? settings.default_announce_delay_seconds ?? 30, 'number', {min: 0, max: 300, required: true});
                const poolMode = selectField(form, 'Пул категорий обычного квиза', settings.quiz?.categories_mode ?? settings.quiz_categories_mode ?? 'all', [['all', 'Все доступные'], ['random', 'Случайный выбор'], ['specific', 'Только выбранные'], ['exclude', 'Исключить выбранные']]);
                const pool = field(form, 'Категории пула — по одной на строку', (settings.quiz?.specific_categories ?? settings.quiz_categories_pool ?? []).join('\n'), 'textarea', {rows: 3});
                const poolCount = field(form, 'Количество категорий в обычном квизе', settings.quiz?.num_random_categories ?? settings.num_categories_per_quiz ?? 3, 'number', {min: 1, max: 100, required: true});
                const cleanup = field(form, 'Автоудаление сообщений', settings.auto_delete_bot_messages ?? true, 'checkbox');
                form.append(element('h3', 'Ежедневная викторина'));
                const enabled = field(form, 'Расписание включено', daily.enabled, 'checkbox');
                const times = field(form, 'Время запуска: ЧЧ:ММ, через запятую', (daily.times_msk || []).map(t => `${String(t.hour).padStart(2, '0')}:${String(t.minute).padStart(2, '0')}`).join(', '));
                const zone = field(form, 'Часовой пояс', daily.timezone || 'Europe/Moscow', 'text', {required: true});
                const count = field(form, 'Вопросов в ежедневном квизе', daily.num_questions ?? 10, 'number', {min: 1, max: 100, required: true});
                const interval = field(form, 'Интервал между вопросами, секунд', daily.interval_seconds ?? 60, 'number', {min: 0, max: 86400, required: true});
                const duration = field(form, 'Время ответа в ежедневном квизе, секунд', daily.poll_open_seconds ?? 600, 'number', {min: 5, max: 600, required: true});
                form.append(element('h3', 'Категории и мудрость дня'));
                const allowed = field(form, 'Разрешённые категории — по одной на строку', (settings.enabled_categories || []).join('\n'), 'textarea', {rows: 3});
                const blocked = field(form, 'Запрещённые категории — по одной на строку', (settings.disabled_categories || []).join('\n'), 'textarea', {rows: 3});
                const modeLabel = element('label', 'Выбор категорий ежедневного квиза', 'pg-field');
                const mode = element('select', undefined, 'form-input'); mode.setAttribute('aria-label', 'Выбор категорий ежедневного квиза');
                for (const [value, label] of [['random', 'Случайные'], ['specific', 'Указанные'], ['all_enabled', 'Все разрешённые']]) {
                    const option = element('option', label); option.value = value; mode.append(option);
                }
                mode.value = daily.categories_mode || 'random'; modeLabel.append(mode); form.append(modeLabel);
                const specific = field(form, 'Указанные категории — по одной на строку', (daily.specific_categories || []).join('\n'), 'textarea', {rows: 3});
                const randomCount = field(form, 'Сколько случайных категорий', daily.num_random_categories ?? 3, 'number', {min: 1, max: 100, required: true});
                const wisdom = field(form, 'Мудрость дня включена', settings.daily_wisdom?.enabled, 'checkbox');
                const wisdomTime = field(form, 'Время мудрости дня (в часовом поясе чата выше)', settings.daily_wisdom?.time || '12:00', 'time', {required: true});
                return async () => {
                    const lines = input => [...new Set(input.value.split('\n').map(v => v.trim()).filter(Boolean))];
                    if (mode.value === 'specific' && !lines(specific).length) throw new Error('Укажите категории для ежедневного квиза');
                    const entries = times.value.trim() ? times.value.split(',').map(t => t.trim()) : [];
                    if (entries.some(t => !/^(?:[01]\d|2[0-3]):[0-5]\d$/.test(t))) throw new Error('Время должно быть в формате ЧЧ:ММ');
                    await put(`/api/chats/${chat.id}/settings?expected_revision=${revision}`, {
                        default_num_questions: Number(questions.value), default_open_period_seconds: Number(seconds.value),
                        default_interval_seconds: Number(ordinaryInterval.value), default_announce_quiz: announce.checked,
                        default_announce_delay_seconds: Number(announceDelay.value), quiz_categories_mode: poolMode.value,
                        quiz_categories_pool: lines(pool), num_categories_per_quiz: Number(poolCount.value),
                        auto_delete_bot_messages: cleanup.checked,
                        enabled_categories: lines(allowed), disabled_categories: lines(blocked),
                        daily_wisdom: {enabled: wisdom.checked, time: wisdomTime.value},
                        daily_quiz: {enabled: enabled.checked, timezone: zone.value.trim(),
                            categories_mode: mode.value, num_random_categories: Number(randomCount.value), specific_categories: lines(specific),
                            times_msk: entries.map(t => { const [hour, minute] = t.split(':').map(Number); return {hour, minute}; }),
                            num_questions: Number(count.value), interval_seconds: Number(interval.value), poll_open_seconds: Number(duration.value)},
                    });
                    await chats();
                    notice(document.getElementById('chats'), 'Настройки сохранены. Применение расписания ботом проверяется отдельно на странице обзора.');
                };
            }, () => editSettings(chat));
        } catch (error) { alert(error.message); }
    }
    async function resetSettings(chat) {
        try {
            const {response} = await api(`/api/chats/${chat.id}/settings`);
            const revision = response.headers.get('X-Settings-Revision');
            if (revision === null) throw new Error('Не удалось прочитать версию настроек');
            const {data: defaults} = await api('/api/settings/defaults');
            modal(`Сбросить настройки · ${chat.title}`, form => {
                notice(form, 'Баллы, участники, достижения и вопросы останутся. Настройки и расписания будут заменены значениями проекта ниже.');
                const preview = element('details'); preview.append(element('summary', 'Новые настройки'), element('pre', JSON.stringify(defaults, null, 2))); form.append(preview);
                const confirmation = field(form, `Введите ID чата: ${chat.id}`, '', 'text', {required: true});
                return async () => {
                    if (confirmation.value !== String(chat.id)) throw new Error('ID чата не совпадает');
                    await api(`/api/chats/${chat.id}/reset-settings`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({expected_revision: Number(revision), confirmation: confirmation.value})});
                    await chats();
                };
            }, () => resetSettings(chat), 'Сбросить настройки');
        } catch (error) { alert(error.message); }
    }
    async function resetCategories(chat) {
        try {
            const {data} = await api(`/api/chats/${chat.id}/category-reset-preview`);
            modal(`Статистика категорий · ${chat.title}`, form => {
                notice(form, 'Сбрасывается только использование категорий в этом чате. Баллы и достижения не меняются; использование в других чатах сохраняется. Давность использования категории другими чатами не обнуляется.');
                if (data.active_sessions.length) notice(form, 'Во время игры сброс недоступен. Сначала завершите её.');
                const confirmation = field(form, `Введите ID чата: ${chat.id}`, '', 'text', {required: true});
                const actionId = crypto.randomUUID();
                return async () => {
                    await post(`/api/chats/${chat.id}/reset-categories`, {expected_version: data.version, confirmation: confirmation.value, action_id: actionId});
                    await chats(); notice(document.getElementById('chats'), 'Использование категорий сброшено. Квитанция сохранена.');
                };
            }, () => resetCategories(chat), 'Сбросить использование');
        } catch (error) { alert(error.message); }
    }

    async function systemSettings() {
        const body = screen('settings', 'Управление и обслуживание', systemSettings);
        try {
            const {data} = await api('/api/control/maintenance'); body.replaceChildren();
            const current = card(body, data.maintenance_mode ? 'Обслуживание включено' : 'Игры разрешены');
            notice(current, data.reason || 'Режим обслуживания выключен.');
            notice(current, 'Это переключатель в текущей dev-базе, не управление сервером. Включение прерывает активные игры и останавливает новые запуски/начисления. Выключение разрешает новые игры, но не возобновляет прерванные.');
            current.append(button(data.maintenance_mode ? 'Завершить обслуживание' : 'Включить обслуживание', () => modal('Изменить режим обслуживания', form => {
                const reason = field(form, 'Причина', '', 'text', {required: true, maxLength: 500});
                const confirmation = field(form, 'Я подтверждаю изменение режима текущей dev-базы', false, 'checkbox', {required: true});
                const actionId = crypto.randomUUID();
                return async () => {
                    if (!confirmation.checked) throw new Error('Подтвердите изменение');
                    await put('/api/control/maintenance', {enabled: !data.maintenance_mode, reason: reason.value, expected_revision: data.revision, action_id: actionId});
                    await systemSettings();
                };
            }, systemSettings)));
            const backups = card(body, 'Резервные копии dev');
            notice(backups, 'PostgreSQL, вопросы, изображения и история файлов — на этом компьютере. Проверка восстанавливает снимок в отдельную временную БД и сравнивает все таблицы; рабочие данные не меняются.');
            const result = element('p', '', 'pg-note'); result.setAttribute('role', 'status');
            const operation = async (trigger, action, success) => {
                trigger.disabled = true; result.textContent = 'Выполняется… Это может занять до нескольких минут.';
                try { const value = await action(); result.textContent = success(value); await listBackups(); }
                catch (error) { result.textContent = error.message; }
                finally { trigger.disabled = false; }
            };
            backups.append(button('Создать резервную копию', event => operation(event.currentTarget, () => post('/api/dev-backups', {}), value => `Снимок создан: ${value.data.id}. Теперь можно проверить восстановление.`)), result);
            const items = element('div'); backups.append(items);
            async function listBackups() {
                const {data: catalog} = await api('/api/dev-backups'); items.replaceChildren();
                if (!catalog.items.length) notice(items, 'Копий ещё нет.');
                for (const item of catalog.items) {
                    const row = card(items, item.created_at ? new Date(item.created_at).toLocaleString('ru-RU') : 'Повреждённый архив');
                    notice(row, `${item.id} · ${item.bytes ? (item.bytes / 1048576).toFixed(2) + ' МиБ' : item.error}`);
                    const actions = element('div', undefined, 'pg-actions'); row.append(actions);
                    if (!item.error) {
                        const download = element('a', 'Скачать', 'btn btn-secondary'); download.href = `/api/dev-backups/${item.id}/download`; download.download = `dev-backup-${item.id}.zip`;
                        actions.append(download, button('Проверить восстановление', event => operation(event.currentTarget,
                            () => post(`/api/dev-backups/${item.id}/verify`, {}), value => `Проверка пройдена: ${value.data.tables} таблиц и ${value.data.files} файлов. Рабочая dev-база не менялась.`), true));
                        const help = element('details'); help.append(element('summary', 'Восстановить dev целиком'));
                        notice(help, 'Остановите локальные панель и Mini App. Команда создаст страховочную копию и восстановит выбранный снимок. Сеансы входа отзываются, старые игры не возобновляются.');
                        help.append(element('pre', `.\\scripts\\Restore-LocalDevBackup.ps1 -BackupId ${item.id} -ConfirmOverwrite morning_quiz_dev`)); row.append(help);
                    }
                    actions.append(button('Удалить в корзину', () => modal('Перенести архив в корзину', form => {
                        notice(form, 'Файл останется в .local/dev-backups/trash. Другие резервные копии не затрагиваются.');
                        const confirmation = field(form, `Введите ID: ${item.id}`, '', 'text', {required: true});
                        return async () => { await post(`/api/dev-backups/${item.id}/trash`, {confirmation: confirmation.value}); await listBackups(); };
                    }, undefined, 'Перенести'), true));
                }
            }
            await listBackups();
            const mail = card(body, 'Рассылки · автономный тест');
            notice(mail, 'Проверьте текст, адресатов и отчёт. Ничего не отправляется в Telegram, даже если на компьютере есть токен бота. Для реальных отправок нужен отдельно согласованный тестовый контур.');
            const {data: chatList} = await api('/api/chats');
            const picks = chatList.map(chat => ({chat, input: field(mail, `${chat.title} · ${chat.id}`, false, 'checkbox')}));
            const message = field(mail, 'Сообщение · обычный текст, без разметки', '', 'textarea', {maxLength: 4000});
            const broadcastResult = element('p', '', 'pg-note'); broadcastResult.setAttribute('role', 'status');
            mail.append(button('Предпросмотр рассылки', async event => {
                const trigger = event.currentTarget; trigger.disabled = true; broadcastResult.textContent = '';
                try {
                    const {data: draft} = await post('/api/dev-broadcasts/preview', {draft_id: crypto.randomUUID(), message: message.value, chat_ids: picks.filter(p => p.input.checked).map(p => Number(p.chat.id))});
                    modal('Предпросмотр · без отправки в Telegram', form => {
                        form.append(element('pre', draft.message));
                        for (const target of draft.targets) notice(form, `${target.title} · ${target.id}${target.blocked ? ' · заблокирован, будет пропущен' : ''}`);
                        const confirmation = field(form, `Для теста введите: ${draft.confirmation}`, '', 'text', {required: true});
                        return async () => {
                            const {data: report} = await post(`/api/dev-broadcasts/${draft.id}/simulate`, {confirmation: confirmation.value});
                            renderDelivery(broadcastResult, report);
                        };
                    }, undefined, 'Выполнить тест');
                } catch (error) { broadcastResult.textContent = error.message; }
                finally { trigger.disabled = false; }
            }), broadcastResult);
            const {data: broadcasts} = await api('/api/dev-broadcasts');
            const history = element('details'); history.append(element('summary', 'Последние тесты и черновики')); mail.append(history);
            for (const draft of broadcasts.items) {
                const row = card(history, new Date(draft.created_at).toLocaleString('ru-RU'));
                notice(row, draft.message);
                if (draft.report) renderDelivery(row, draft.report);
                else notice(row, `Предпросмотр · ${draft.targets.length} адресатов · не выполнен`);
            }
        } catch (error) { fail(body, error); }
    }
    function renderDelivery(parent, report) {
        const labels = {simulated: 'Тест: успешно', skipped_blocked: 'Пропущен: блокировка/обслуживание', simulated_rejected: 'Тест: отказ', simulated_unknown: 'Тест: доставка неизвестна, повтор не выполнялся'};
        parent.replaceChildren(element('strong', 'Автономный отчёт. Сообщений в Telegram: 0.'));
        for (const item of report.results) parent.append(element('p', `${item.chat_id} · ${labels[item.status] || item.status}`));
    }
    const aiConversation = {provider: 'offline', model: '', messages: []};
    async function adminAI() {
        const body = screen('claude-ai', 'AI-помощник редактора', adminAI);
        try {
            const {data} = await api('/api/admin-ai/providers'); body.replaceChildren();
            notice(body, 'Вопросы, факты и формулировки обсуждаются здесь. Модель не читает базу и не меняет вопросы сама. История хранится только в памяти этой страницы; ответы выводятся обычным текстом.');
            const form = element('form'); body.append(form);
            const provider = selectField(form, 'Провайдер', aiConversation.provider, [['offline', 'Демо · без вызова модели'], ...data.providers.map(p => [p.id, `${p.name}${data.external_enabled && p.key_configured ? '' : ' · не подключён'}`])]);
            const model = field(form, 'ID модели у выбранного провайдера', aiConversation.model, 'text', {maxLength: 150});
            const transcript = element('div'); form.append(transcript);
            function history() {
                transcript.replaceChildren();
                for (const message of aiConversation.messages) { const row = card(transcript, message.role === 'user' ? 'Вы' : 'Ответ'); row.append(element('pre', message.content)); }
            }
            history();
            provider.addEventListener('change', () => { aiConversation.provider = provider.value; aiConversation.messages = []; aiConversation.model = data.providers.find(p => p.id === provider.value)?.default_model || ''; model.value = aiConversation.model; history(); });
            const prompt = field(form, 'Ваш запрос', '', 'textarea', {required: true, maxLength: 4000});
            const confirmation = field(form, 'Разрешаю передать текст этого разговора выбранному внешнему AI. Запрос может расходовать лимит аккаунта.', false, 'checkbox');
            const error = element('p', '', 'pg-error'); error.setAttribute('role', 'alert'); form.append(error);
            const send = button('Отправить запрос', () => {}); send.type = 'submit';
            const reset = button('Новый разговор', () => { aiConversation.messages = []; prompt.value = ''; history(); }, true);
            form.append(send, reset);
            form.addEventListener('submit', async event => {
                event.preventDefault(); send.disabled = true; provider.disabled = true; model.disabled = true; reset.disabled = true; error.textContent = '';
                const message = {role: 'user', content: prompt.value};
                try {
                    const {data: answer} = await post('/api/admin-ai/chat', {provider: provider.value, model: model.value,
                        messages: [...aiConversation.messages, message], confirmed_external: confirmation.checked});
                    aiConversation.messages.push(message, {role: 'assistant', content: answer.text}); aiConversation.model = model.value;
                    prompt.value = ''; history();
                } catch (failure) { error.textContent = failure.message; }
                finally { send.disabled = false; provider.disabled = false; model.disabled = false; reset.disabled = false; }
            });
        } catch (error) { fail(body, error); }
    }
    async function devBot() {
        const body = screen('bot-metrics', 'Тестовый бот', devBot);
        try {
            const {data} = await api('/api/dev-runtime'); body.replaceChildren();
            const control = card(body, data.running ? 'Автономный бот работает' : 'Автономный бот остановлен');
            notice(control, 'Настоящие обработчики классики, фото-квиза и расписаний. Тестовый чат и игрок; запросов в Telegram нет. Сообщения ниже имитируют чат, а очки и настройки сохраняются в dev PostgreSQL.');
            notice(control, `Имитировано API-вызовов: ${data.api_calls_simulated} · задач: ${data.jobs.length}`);
            const error = element('p', '', 'pg-error'); error.setAttribute('role', 'alert');
            async function perform(trigger, path, payload = {}) {
                trigger.disabled = true; error.textContent = '';
                try { await post(path, payload); await devBot(); }
                catch (failure) { error.textContent = failure.message; trigger.disabled = false; }
            }
            control.append(button(data.running ? 'Остановить' : 'Запустить автономного бота', event => perform(event.currentTarget, `/api/dev-runtime/${data.running ? 'stop' : 'start'}`)));
            if (data.running) control.append(button('Перезапустить', event => perform(event.currentTarget, '/api/dev-runtime/restart'), true));
            control.append(error);
            if (data.running) {
                const composer = card(body, 'Отправить в тестовый чат');
                const commands = element('div', undefined, 'pg-actions'); composer.append(commands);
                for (const command of ['/start', '/quiz', '/photo_quiz', '/top', '/mystats', '/categories', '/stopquiz', '/stop_photo_quiz']) {
                    commands.append(button(command, event => perform(event.currentTarget, '/api/dev-runtime/input/update', {message: command}), true));
                }
                const text = field(composer, 'Команда или текстовый ответ на фото-вопрос', '', 'text', {maxLength: 4000});
                composer.append(button('Отправить в симулятор', event => perform(event.currentTarget, '/api/dev-runtime/input/update', {message: text.value})));
            }
            const conversation = card(body, 'Ответы бота · последние 30 сообщений');
            if (!data.messages.length) notice(conversation, 'Запустите бота и отправьте /start или /quiz.');
            for (const message of data.messages.slice(-30).reverse()) {
                const item = card(conversation, `Сообщение ${message.message_id}`);
                if (message.photo) notice(item, 'Фото-вопрос · изображение из dev-каталога');
                if (message.offline_photo_url?.startsWith('/api/images/')) {
                    const photo = element('img', undefined, 'pg-photo-image'); photo.src = message.offline_photo_url; photo.alt = 'Изображение текущего фото-вопроса'; photo.loading = 'lazy'; item.append(photo);
                }
                item.append(element('pre', message.text || message.caption || message.poll?.question || 'Служебное сообщение'));
                if (message.poll) {
                    message.poll.options.forEach((option, index) => {
                        const choice = button(option.text, event => perform(event.currentTarget, '/api/dev-runtime/input/update', {poll_id: message.poll.id, option: index}), true);
                        choice.disabled = !data.running || message.poll.is_closed; item.append(choice);
                    });
                }
                for (const row of message.reply_markup?.inline_keyboard || []) {
                    const actions = element('div', undefined, 'pg-actions'); item.append(actions);
                    for (const choice of row) if (choice.callback_data) {
                        const action = button(choice.text, event => perform(event.currentTarget, '/api/dev-runtime/input/update', {message_id: message.message_id, callback: choice.callback_data}), true);
                        action.disabled = !data.running; actions.append(action);
                    }
                }
            }
            const jobs = card(body, 'Задачи планировщика');
            for (const job of data.jobs) notice(jobs, `${job.name} · ${job.next_run}`);
            if (!data.jobs.length) notice(jobs, 'Нет активных задач.');
            const log = element('details'); log.append(element('summary', 'Журнал автономного транспорта'));
            log.append(element('pre', data.events.slice(-50).map(e => `${e.at}  ${e.event}${e.error ? ': ' + e.error : ''}`).join('\n'))); body.append(log);
        } catch (error) { fail(body, error); }
    }
    async function users() {
        const body = screen('users', 'Пользователи и баллы', users);
        try {
            const {data} = await api(`/api/users?include_archived=${showArchivedUsers}`); body.replaceChildren();
            const showArchived = field(body, 'Показывать также архивных участников', showArchivedUsers, 'checkbox');
            showArchived.addEventListener('change', () => { showArchivedUsers = showArchived.checked; users(); });
            if (!data.users.length) notice(body, 'В этой базе пока нет участников.');
            directory(body, data.users, 'Поиск участника по имени или ID', user => `${user.name} ${user.user_id}`, (cards, user) => {
                const item = card(cards, user.name);
                notice(item, `ID: ${user.user_id} · общий счёт: ${user.total_score} · ответов: ${user.total_answered}`);
                item.append(button('Профиль участника', () => openProfile('users', user.user_id), true));
                for (const membership of user.chats_activity) {
                    const row = element('div', undefined, 'pg-membership');
                    row.append(element('p', `${membership.chat_title}: ${membership.score}`));
                    row.append(button('Изменить баллы', () => modal(`Баллы · ${user.name}`, form => {
                        notice(form, membership.chat_title);
                        const score = field(form, 'Новый счёт в этом чате', membership.score, 'number', {step: '.001', min: '-99999999999.999', max: '99999999999.999', required: true});
                        return async () => {
                            const query = new URLSearchParams({chat_id: membership.chat_id, new_score: score.value, expected_score: String(membership.score)});
                            await put(`/api/users/${user.user_id}/score?${query}`, {}); await users();
                            notice(document.getElementById('users'), 'Баллы сохранены.');
                        };
                    }), true)); item.append(row);
                }
            });
        } catch (error) { fail(body, error); }
    }
    let photoSearch = '', photoFilter = 'all';
    function uploadPhoto(replacement = null) {
        const uploadId = crypto.randomUUID().replaceAll('-', '');
        modal(replacement ? 'Заменить изображение фото-вопроса' : 'Новый фото-вопрос', form => {
            notice(form, 'JPEG, PNG или WebP · до 10 МиБ и 20 мегапикселей. Сервер подготовит WebP без метаданных. Исходные файлы каталога не заменяются.');
            const file = field(form, 'Изображение', '', 'file', {accept: 'image/jpeg,image/png,image/webp', required: true});
            const preview = element('img', undefined, 'pg-upload-preview'); preview.alt = 'Предпросмотр выбранного изображения'; preview.hidden = true; form.append(preview);
            file.addEventListener('change', () => {
                preview.hidden = true; preview.removeAttribute('src'); file.setCustomValidity('');
                const selected = file.files[0];
                if (!selected) return;
                if (selected.size > 10 * 1024 * 1024) { file.setCustomValidity('Максимальный размер — 10 МиБ.'); file.reportValidity(); return; }
                if (!['image/jpeg', 'image/png', 'image/webp'].includes(selected.type)) return;
                const reader = new FileReader();
                reader.addEventListener('load', () => { if (file.files[0] === selected && form.isConnected) { preview.src = reader.result; preview.hidden = false; } });
                reader.readAsDataURL(selected);
            });
            if (replacement) notice(form, 'Старый вариант попадёт в корзину. Уже начатые игры сохранят прежнюю картинку; новый вариант наследует подсказки.');
            const answer = field(form, 'Правильный ответ', replacement?.display_answer || replacement?.correct_answer || '', 'text', {required: true, maxLength: 300});
            const enabled = field(form, 'Участвует в новых сериях', replacement?.enabled ?? true, 'checkbox');
            notice(form, 'При обрыве связи повторите сохранение в этой же форме. Одинаковая загрузка не создаст второй вопрос.');
            return async () => {
                if (!file.files[0] || !answer.value.trim()) throw new Error('Выберите изображение и укажите ответ.');
                const query = new URLSearchParams({correct_answer: answer.value.trim(), enabled: String(enabled.checked)});
                if (replacement) { query.set('replace_key', replacement.name); query.set('expected_version', replacement.version); }
                await api(`/api/photo-quiz/uploads/${uploadId}?${query}`, {method: 'POST', headers: {'Content-Type': 'application/octet-stream'}, body: file.files[0]});
                photoSearch = ''; photoFilter = 'all'; await photos();
                notice(document.getElementById('photo-quiz'), 'Фото-вопрос добавлен. Он будет доступен при подготовке новых серий.');
            };
        });
    }
    async function photos() {
        const body = screen('photo-quiz', 'Фото-викторины', photos);
        try {
            const {data} = await api('/api/photo-quiz'); body.replaceChildren();
            notice(body, 'Изменения применяются к новым сериям. Отключение не удаляет картинку и историю игр.');
            body.append(button('Добавить фото-вопрос', () => uploadPhoto()));
            const search = field(body, 'Поиск по ответу или имени фото', photoSearch, 'search');
            const filterLabel = element('label', 'Показывать', 'pg-field');
            const filter = element('select', undefined, 'form-input'); filter.setAttribute('aria-label', 'Показывать');
            for (const [value, label] of [['all', 'Каталог'], ['enabled', 'Включённые'], ['disabled', 'Отключённые'], ['missing', 'Без изображения'], ['archived', 'Корзина']]) {
                const option = element('option', label); option.value = value; filter.append(option);
            }
            filter.value = photoFilter; filterLabel.append(filter); body.append(filterLabel);
            const results = element('div'); body.append(results); let page = 0;
            const render = () => {
                results.replaceChildren();
                const query = photoSearch.trim().toLocaleLowerCase();
                const filtered = data.photos.filter(photo => `${photo.name} ${photo.display_answer || ''} ${photo.correct_answer}`.toLocaleLowerCase().includes(query)
                    && (photoFilter === 'archived' ? photo.archived : !photo.archived && (photoFilter === 'all' || (photoFilter === 'enabled' && photo.enabled) || (photoFilter === 'disabled' && !photo.enabled) || (photoFilter === 'missing' && !photo.has_image))));
                notice(results, `Найдено: ${filtered.length} из ${data.photos.length}. Страница ${page + 1} из ${Math.max(1, Math.ceil(filtered.length / 24))}`);
                if (!filtered.length) notice(results, data.photos.length ? 'Нет совпадений. Попробуйте другой запрос или фильтр.' : 'Каталог пока пуст. Добавьте первый фото-вопрос.');
                const cards = grid(results);
                for (const photo of filtered.slice(page * 24, (page + 1) * 24)) {
                const title = photo.display_answer || photo.correct_answer || photo.name;
                const item = card(cards, title);
                if (photo.image_url) {
                    const img = element('img'); img.src = photo.image_url; img.alt = title; img.loading = 'lazy'; img.className = 'pg-photo'; item.prepend(img);
                } else notice(item, 'Изображение отсутствует в локальной папке');
                notice(item, `Ответ: ${photo.display_answer || photo.correct_answer}`);
                item.append(button(photo.archived ? 'Восстановить из корзины' : 'Удалить в корзину', () => modal(photo.archived ? 'Восстановить фото-вопрос?' : 'Удалить фото-вопрос в корзину?', form => {
                    notice(form, `${title}. Изображение и история игр не удаляются. Восстановление возвращает прежний статус участия в новых сериях.`);
                    return async () => { await post(`/api/photo-quiz/${encodeURIComponent(photo.name)}/archive`, {archived: !photo.archived, expected_version: photo.version}); await photos(); };
                }), true));
                if (photo.archived) continue;
                item.append(button('Заменить изображение', () => uploadPhoto(photo), true));
                item.append(element('span', photo.enabled ? 'Включено' : 'Отключено', `pg-badge ${photo.enabled ? 'accent' : ''}`));
                item.append(button('Редактировать', () => modal(`Фото · ${title}`, form => {
                    const answer = field(form, 'Ответ (как показывается в игре)', photo.display_answer || photo.correct_answer, 'text', {required: true, maxLength: 300});
                    const enabled = field(form, 'Участвует в новых сериях', photo.enabled, 'checkbox');
                    const hints = field(form, 'Подсказки · JSON', JSON.stringify(photo.hints || {}, null, 2), 'textarea', {rows: 6});
                    return async () => {
                        let parsed;
                        try { parsed = JSON.parse(hints.value); } catch { throw new Error('Подсказки: некорректный JSON'); }
                        await put(`/api/photo-quiz/${encodeURIComponent(photo.name)}?expected_version=${photo.version}`, {
                            correct_answer: answer.value.trim(), display_answer: answer.value.trim(), enabled: enabled.checked, hints: parsed,
                        }); await photos();
                        notice(document.getElementById('photo-quiz'), 'Фото-вопрос сохранён. Изменения вступят в силу для новых серий.');
                    };
                })));
            }
                const paging = element('div', undefined, 'pg-actions');
                if (page) paging.append(button('Предыдущие фото', () => { page--; render(); }, true));
                if ((page + 1) * 24 < filtered.length) paging.append(button('Следующие фото', () => { page++; render(); }, true));
                results.append(paging);
            };
            search.addEventListener('input', () => { photoSearch = search.value; page = 0; render(); });
            filter.addEventListener('change', () => { photoFilter = filter.value; page = 0; render(); });
            render();
        } catch (error) { fail(body, error); }
    }
    const post = (path, data) => api(path, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data)});
    let selectedCategory = '';
    function repairCategory(parent, category, reload) {
        notice(parent, 'Файл не удалось разобрать. Сначала скачайте исходник, затем загрузите исправленный JSON-массив. Предыдущие байты сохраняются в истории; новые вопросы проверяются до записи.');
        const path = `/api/bank/categories/${encodeURIComponent(category.name)}`;
        const download = element('a', 'Скачать исходный файл', 'btn btn-secondary'); download.href = `${path}/raw`; download.download = 'original-category.json'; parent.append(download);
        if (category.version) parent.append(button('Загрузить исправленный файл', () => modal(`Исправить ${category.name}`, form => {
            const file = field(form, 'JSON-массив вопросов', '', 'file', {accept: '.json,application/json', required: true});
            const preview = element('pre'); form.append(preview); let values = null;
            file.addEventListener('change', async () => {
                values = null;
                try { const input = file.files[0]; if (!input || input.size > 10_000_000) throw new Error('Нужен файл до 10 МБ');
                    const parsed = JSON.parse(await input.text()); if (!Array.isArray(parsed) || !parsed.length) throw new Error('Нужен непустой массив вопросов');
                    values = parsed; preview.textContent = `Будет восстановлено вопросов: ${values.length}`;
                } catch (error) { preview.textContent = error.message; }
            });
            const confirm = field(form, 'Подтверждаю замену этой категории', false, 'checkbox', {required: true});
            return async () => { if (!values || !confirm.checked) throw new Error('Выберите файл и подтвердите');
                await put(`${path}/repair?expected_version=${category.version}`, {questions: values}); await reload(); };
        }, reload, 'Восстановить JSON')));
    }
    async function malformedQuestions() {
        const body = screen('malformed-questions', 'Вопросы, требующие исправления', malformedQuestions);
        try {
            const {data} = await api('/api/bank/categories'); body.replaceChildren();
            const invalid = data.categories.filter(c => c.invalid || c.error);
            if (!invalid.length) notice(body, 'Ошибок формата в текущем банке не обнаружено.');
            for (const category of invalid) {
                const row = card(body, category.name);
                if (category.error) repairCategory(row, category, malformedQuestions);
                else { notice(row, `Некорректных вопросов: ${category.invalid}. До исправления они не попадают в игру.`);
                    row.append(button('Открыть редактор категории', () => { selectedCategory = category.name; window.showSection('questions'); })); }
            }
        } catch (error) { fail(body, error); }
    }
    async function questions() {
        const body = screen('questions', 'Банк вопросов', questions);
        try {
            const {data} = await api('/api/bank/categories'); body.replaceChildren();
            notice(body, 'Изменения появятся в следующей игре. Активная игра сохраняет свои вопросы. Предыдущие версии файлов остаются в .history.');
            const tools = element('div', undefined, 'pg-actions pg-toolbar');
            const exportAll = element('a', 'Экспорт всего банка', 'btn btn-secondary'); exportAll.href = '/api/bank/export'; exportAll.download = 'quiz-bank.json'; tools.append(exportAll);
            tools.append(button('Импорт банка', () => modal('Импорт нескольких категорий', form => {
                notice(form, 'Формат: экспортированный quiz-bank.json. Указанные категории заменяются целиком, остальные остаются. Сначала проверьте состав, затем подтвердите импорт. Предыдущие версии сохраняются в .history.');
                const file = field(form, 'Файл банка JSON', '', 'file', {accept: '.json,application/json', required: true});
                const preview = element('pre'); form.append(preview); let imported = null;
                file.addEventListener('change', async () => {
                    imported = null;
                    try {
                        if (!file.files[0] || file.files[0].size > 10 * 1024 * 1024) throw new Error('Максимум 10 МиБ');
                        const parsed = JSON.parse(await file.files[0].text());
                        if (parsed.format !== 'morning-quiz-bank-v1' || !parsed.categories || Array.isArray(parsed.categories)) throw new Error('Ожидается экспортированный банк morning-quiz-bank-v1');
                        if (!Object.values(parsed.categories).every(Array.isArray)) throw new Error('Категории должны содержать массивы вопросов');
                        imported = parsed.categories;
                        preview.textContent = Object.entries(imported).map(([name, values]) => `${name}: ${values.length} вопросов (${data.categories.some(c => c.name === name) ? 'замена' : 'новая категория'})`).join('\n');
                    } catch (error) { preview.textContent = error.message; }
                });
                const confirmation = field(form, 'Я проверил список и подтверждаю замену', false, 'checkbox', {required: true});
                return async () => {
                    if (!imported || !confirmation.checked) throw new Error('Выберите файл и подтвердите состав импорта');
                    const versions = Object.fromEntries(Object.keys(imported).map(name => [name, data.categories.find(c => c.name === name)?.version ?? null]));
                    const {data: result} = await post('/api/bank/import', {categories: imported, expected_versions: versions});
                    await questions();
                    notice(document.getElementById('questions'), `Импортировано категорий: ${result.completed.length}. ${result.failed ? `Ошибка файла ${result.failed}; не начаты: ${result.remaining.join(', ')}. Обновите список перед повтором.` : 'Все выбранные категории сохранены.'}`);
                };
            }, questions, 'Импортировать подтверждённый список'), true));
            tools.append(button('Создать категорию', () => modal('Новая категория', form => {
                const name = field(form, 'Название категории', '', 'text', {required: true, maxLength: 100});
                return async () => { await post('/api/bank/categories', {name: name.value.trim()}); selectedCategory = name.value.trim(); await questions(); };
            })));
            body.append(tools);
            const label = element('label', 'Категория', 'pg-field');
            const select = element('select', undefined, 'form-input'); select.setAttribute('aria-label', 'Категория');
            for (const category of data.categories) {
                const option = element('option', `${category.name} · ${category.count}${category.invalid ? ` · проверить: ${category.invalid}` : ''}`);
                option.value = category.name; select.append(option);
            }
            if (data.categories.some(c => c.name === selectedCategory)) select.value = selectedCategory;
            label.append(select); body.append(label);
            select.addEventListener('change', () => { selectedCategory = select.value; questions(); });
            if (!data.categories.length) { notice(body, 'Создайте первую категорию.'); return; }
            selectedCategory = select.value;
            const selected = data.categories.find(c => c.name === selectedCategory);
            if (selected?.error) { repairCategory(body, selected, questions); return; }
            const path = `/api/bank/categories/${encodeURIComponent(selectedCategory)}`;
            const {data: category} = await api(path);
            const version = `?expected_version=${category.version}`;
            const refresh = async () => { await questions(); notice(document.getElementById('questions'), 'Изменения сохранены.'); };
            function editor(item) {
                modal(item ? `Вопрос №${item.index + 1}` : 'Новый вопрос', form => {
                    const text = field(form, 'Текст вопроса', item?.question || '', 'textarea', {rows: 3, required: true, maxLength: 300});
                    const options = field(form, 'Варианты ответа — каждый с новой строки', (item?.options || []).join('\n'), 'textarea', {rows: 4, required: true});
                    const correct = field(form, 'Правильный ответ — точно как в вариантах', item?.correct || '', 'text', {required: true, maxLength: 100});
                    const explanation = field(form, 'Пояснение после ответа', item?.explanation || '', 'textarea', {rows: 2, maxLength: 200});
                    return async () => {
                        const value = {question: text.value.trim(), options: options.value.split('\n').map(v => v.trim()).filter(Boolean), correct: correct.value.trim(), explanation: explanation.value.trim()};
                        if (item) await put(`${path}/questions/${item.index}${version}`, value);
                        else await post(`${path}/questions${version}`, value);
                        await refresh();
                    };
                });
            }
            tools.append(button('Добавить вопрос', () => editor(null)), button('Импорт JSON', () => modal('Добавить вопросы из JSON', form => {
                notice(form, 'Импорт дополняет категорию, не заменяет существующие вопросы. Весь список проверяется до сохранения.');
                const input = field(form, 'Массив вопросов JSON', '[]', 'textarea', {rows: 10, required: true});
                return async () => {
                    let values; try { values = JSON.parse(input.value); } catch { throw new Error('Некорректный JSON'); }
                    await post(`${path}/import${version}`, {questions: values}); await refresh();
                };
            }), true));
            const download = element('a', 'Экспорт JSON', 'btn btn-secondary'); download.href = `${path}/export`; download.download = 'questions.json'; tools.append(download);
            tools.append(button('Удалить категорию', () => modal('Удаление категории', form => {
                notice(form, `Категория «${category.name}» и её вопросы исчезнут из новых игр. Копия останется в .history.`);
                const confirmation = field(form, 'Введите название для подтверждения', '', 'text', {required: true});
                return async () => { if (confirmation.value !== category.name) throw new Error('Название не совпадает'); await api(`${path}${version}`, {method: 'DELETE'}); selectedCategory = ''; await refresh(); };
            }), true));
            const search = field(body, 'Поиск по вопросам', '', 'search');
            const results = element('div'); body.append(results);
            let page = 0;
            const render = () => {
                results.replaceChildren();
                const query = search.value.trim().toLocaleLowerCase();
                const filtered = category.questions.filter(item => JSON.stringify(item).toLocaleLowerCase().includes(query));
                notice(results, `Найдено: ${filtered.length}. Страница ${page + 1} из ${Math.max(1, Math.ceil(filtered.length / 30))}`);
                const cards = grid(results);
                for (const item of filtered.slice(page * 30, (page + 1) * 30)) {
                    const row = card(cards, item.invalid ? `№${item.index + 1} · требуется исправление` : `№${item.index + 1} · ${item.question}`);
                    if (item.invalid) notice(row, JSON.stringify(item.raw));
                    else { notice(row, item.options.join(' / ')); notice(row, `Правильно: ${item.correct}`); if (item.explanation) notice(row, item.explanation); }
                    const actions = element('div', undefined, 'pg-actions');
                    actions.append(button('Редактировать вопрос', () => editor(item)), button('Удалить вопрос', () => modal('Удалить вопрос?', form => {
                        notice(form, item.question || `Вопрос №${item.index + 1}`);
                        notice(form, 'Предыдущая версия категории останется в .history.');
                        return async () => { await api(`${path}/questions/${item.index}${version}`, {method: 'DELETE'}); await refresh(); };
                    }), true)); row.append(actions);
                }
                const pager = element('div', undefined, 'pg-actions');
                if (page) pager.append(button('Предыдущие', () => { page--; render(); }, true));
                if ((page + 1) * 30 < filtered.length) pager.append(button('Следующие', () => { page++; render(); }, true));
                results.append(pager);
            };
            search.addEventListener('input', () => { page = 0; render(); }); render();
        } catch (error) { fail(body, error); }
    }
    const analyticsFilter = {chat: '', days: '30'};
    async function analytics() {
        const body = screen('analytics', 'Статистика · PostgreSQL', analytics);
        try {
            const query = new URLSearchParams({days: analyticsFilter.days});
            if (analyticsFilter.chat) query.set('chat_id', analyticsFilter.chat);
            const {data} = await api(`/api/analytics/report?${query}`); body.replaceChildren();
            const filters = element('form', undefined, 'pg-actions');
            const chat = selectField(filters, 'Область статистики', analyticsFilter.chat, [['', 'Все чаты'], ...data.chats.map(c => [c.id, c.title])]);
            const days = selectField(filters, 'Период новых ответов', analyticsFilter.days, [['7', '7 дней'], ['30', '30 дней'], ['90', '90 дней'], ['366', 'Год']]);
            const apply = button('Применить фильтры', () => {}); apply.type = 'submit'; filters.append(apply);
            filters.addEventListener('submit', event => { event.preventDefault(); analyticsFilter.chat = chat.value; analyticsFilter.days = days.value; analytics(); }); body.append(filters);
            const exports = element('div', undefined, 'pg-actions');
            for (const [format, label] of [['json', 'Весь отчёт · JSON'], ['csv', 'Весь рейтинг · CSV']]) {
                const link = element('a', label, 'btn btn-secondary'); link.href = `/api/analytics/report?${query}&download=${format}`; link.download = ''; exports.append(link);
            }
            body.append(exports); notice(body, data.notice);
            const cards = element('div', undefined, 'pg-metrics pg-analytics-metrics'); body.append(cards);
            for (const [title, value, symbol] of [['Участники', data.totals.users, 'users'], ['Баллы', data.totals.score, 'analytics'], ['Классические ответы', data.totals.classic_answers, 'questions'], ['Правильные, включая фото', data.totals.correct_including_photo, 'questions'], ['Рекорд серии', data.totals.best_streak, 'clock']]) {
                cards.append(metric(title, value, '', symbol));
            }
            function table(title, headings, rows) {
                body.append(element('h2', title));
                const wrapper = element('div', undefined, 'pg-table-wrap');
                const node = element('table', undefined, 'pg-table'); const caption = element('caption', title); caption.className = 'pg-visually-hidden'; node.append(caption);
                const head = element('thead'); const header = element('tr');
                for (const name of headings) { const cell = element('th', name); cell.scope = 'col'; header.append(cell); } head.append(header); node.append(head);
                const tbody = element('tbody');
                for (const values of rows) { const row = element('tr'); values.forEach(value => row.append(element('td', String(value)))); tbody.append(row); }
                node.append(tbody); wrapper.append(node); body.append(wrapper); if (!rows.length) notice(body, 'Пока нет данных.');
            }
            const ranking = element('div'); body.append(ranking); let page = 0;
            const renderRanking = () => {
                ranking.replaceChildren();
                const list = element('ol', undefined, 'pg-report-ranking');
                for (const user of data.leaderboard.slice(page * 50, (page + 1) * 50)) {
                    const row = element('li'); row.append(element('span', `#${user.rank} · ${user.score} баллов · `), button(user.name, () => openProfile('users', user.user_id), true)); list.append(row);
                }
                ranking.append(element('h2', `Рейтинг · ${data.leaderboard.length} участников`), list);
                if (!data.leaderboard.length) notice(ranking, 'В этой области пока нет участников.');
                if (page) ranking.append(button('Предыдущие 50', () => { page--; renderRanking(); }, true));
                if ((page + 1) * 50 < data.leaderboard.length) ranking.append(button('Следующие 50', () => { page++; renderRanking(); }, true));
            }; renderRanking();
            table('Использование категорий', ['Категория', 'Игр', 'Вес до фильтрации', 'Давность'], data.categories.map(c => [c.name, c.usage, c.weight ?? 'Выберите чат', c.recently_used ? 'Менее 2 дней · исключается при подборе' : 'Нет недавнего использования']));
            body.append(element('h2', 'Распределение баллов'));
            for (const bin of data.distribution) {
                const row = element('label', `${bin.label}: ${bin.users} участников`, 'pg-field'); const bar = element('progress');
                bar.max = Math.max(1, data.totals.users); bar.value = bin.users; bar.setAttribute('aria-label', `${bin.label}: ${bin.users} участников`); row.append(bar); body.append(row);
            }
            table('Новые ответы за выбранный период · UTC', ['Дата', 'Ответы', 'Верные'], data.activity.map(d => [d.date, d.answers, d.correct]));
            if (data.activity.some(d => d.answers)) {
                const figure = element('figure', undefined, 'pg-activity-chart');
                figure.append(element('figcaption', 'Ответы по дням · UTC. Точные значения — в таблице выше.'));
                const chart = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
                chart.setAttribute('viewBox', '0 0 640 150'); chart.setAttribute('role', 'img');
                chart.setAttribute('aria-label', `Активность с ${data.activity[0].date} по ${data.activity.at(-1).date}`);
                const max = Math.max(1, ...data.activity.map(d => d.answers)), width = 640 / data.activity.length;
                data.activity.forEach((day, index) => { const bar = document.createElementNS(chart.namespaceURI, 'rect');
                    for (const [key, value] of Object.entries({x: index * width, y: 150 - day.answers / max * 145, width: Math.max(.5, width - 1), height: day.answers / max * 145, fill: 'currentColor'})) bar.setAttribute(key, value);
                    const title = document.createElementNS(chart.namespaceURI, 'title'); title.textContent = `${day.date}: ${day.answers} ответов, ${day.correct} верных`; bar.append(title); chart.append(bar); });
                figure.append(chart); body.append(figure);
            }
        } catch (error) { fail(body, error); }
    }
    window.installPostgresAdmin = () => {
        document.documentElement.dataset.adminTheme = 'night';
        document.body.classList.add('pg-admin');
        const supported = new Set(['dashboard', 'chats', 'users', 'photo-quiz', 'questions', 'analytics', 'settings', 'bot-metrics', 'claude-ai', 'malformed-questions']);
        const labels = {dashboard: 'Обзор', questions: 'Банк вопросов', 'photo-quiz': 'Фото-квиз', analytics: 'Статистика', users: 'Участники', chats: 'Чаты и расписания', settings: 'Управление', 'bot-metrics': 'Тестовый бот', 'claude-ai': 'AI-помощник', 'malformed-questions': 'Проверка вопросов'};
        document.querySelectorAll('.nav-item').forEach(nav => {
            nav.hidden = !supported.has(nav.dataset.section);
            if (!nav.hidden) {
                nav.href = `#${nav.dataset.section}`;
                nav.replaceChildren(icon(nav.dataset.section), element('span', labels[nav.dataset.section]));
                if (nav.classList.contains('active')) nav.setAttribute('aria-current', 'page');
            }
        });
        const nav = document.querySelector('.sidebar-nav');
        if (nav) nav.prepend(element('span', 'РАБОЧЕЕ ПРОСТРАНСТВО', 'pg-nav-label'));
        document.querySelector('.sidebar-logo')?.replaceChildren(brand());
        document.querySelector('.mobile-header-title')?.replaceChildren(brand());
        const footer = element('div', undefined, 'pg-sidebar-footer'); footer.append(element('span', 'PostgreSQL', 'pg-badge accent'));
        notice(footer, 'Локальный контур. Доступ только для администратора.');
        const logout = document.getElementById('adminLogoutButton');
        if (logout) { logout.removeAttribute('style'); footer.append(logout); }
        document.querySelector('.sidebar').append(footer);
        const top = element('div', undefined, 'pg-topline'); const crumb = element('span', 'Рабочее пространство');
        crumb.append(element('span', '/', 'pg-separator'), element('strong', 'Morning Quiz'));
        top.append(crumb, element('span', 'Локальная админка', 'pg-badge')); document.querySelector('.main-content').prepend(top);
        Object.assign(window, {loadDashboard: dashboard, refreshDashboard: dashboard, loadChats: chats, loadUsers: users, loadPhotoQuiz: photos, loadQuestions: questions, loadMalformedQuestions: malformedQuestions, loadAnalytics: analytics, loadSettings: systemSettings, loadBotMetrics: devBot, loadAdminAI: adminAI});
    };
})();
