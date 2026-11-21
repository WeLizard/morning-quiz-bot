// Admin section "Ведущий «Ночного города»": narrator profiles, incoming requests, active bindings.
// The provider key is write-only: it lives in a password input until submit and is never read back.
// Every server value is inserted with textContent.
(() => {
    const BASE = '/api/admin/night-case/ai';
    const ERRORS = {
        invalid_config: 'Проверь поля профиля: модель, адаптер, ключ и поля проекта.',
        stale_revision: 'Профиль уже изменили в другой вкладке. Обнови список.',
        stale_epoch: 'Состояние партии изменилось. Обнови список.',
        request_stale: 'Запрос уже решён или истёк.',
        profile_disabled: 'Профиль выключен — сначала включи его.',
        credential_unavailable: 'Ключ профиля недоступен. Сохрани новый ключ.',
        idempotency_conflict: 'Повтор с другими данными. Обнови страницу.',
        ai_unavailable: 'Сервис ведущего сейчас недоступен (ключи шифрования не настроены?).',
        not_found: 'Не найдено.', forbidden: 'Нет доступа.', rate_limited: 'Слишком часто. Подожди.',
        unsupported_preset: 'Этот провайдер не разрешён оператором.',
        unsupported_model_contract: 'Модель не разрешена для этого провайдера.',
    };
    const REQUEST = {pending: 'ждёт решения', approved: 'одобрен', denied: 'отказ', expired: 'истёк', cancelled: 'отменён', superseded: 'заменён'};
    const BINDING = {active: 'активна', revoked: 'отозвана', expired: 'истекла', closed: 'закрыта', superseded: 'заменена'};
    const FIELD = {organization_id: 'Organization ID', project_id: 'Project ID', workspace_id: 'Workspace ID', folder_id: 'Folder ID', scope: 'Scope'};
    const state = {catalog: null, profiles: [], editing: null};

    const el = (tag, text, className) => {
        const node = document.createElement(tag);
        if (text !== undefined && text !== null) node.textContent = text;
        if (className) node.className = className;
        return node;
    };
    const when = (iso) => iso ? new Date(iso).toLocaleString('ru-RU') : '—';
    const requestId = () => crypto.randomUUID().replaceAll('-', '');
    async function api(path, body) {
        const options = body === undefined ? {cache: 'no-store'} : {method: 'POST', cache: 'no-store',
            headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)};
        const response = await fetch(BASE + path, options);
        let data = null;
        try { data = await response.json(); } catch (_) { /* empty body */ }
        if (!response.ok) throw new Error((data && ERRORS[data.code]) || (data && data.detail) || `Ошибка ${response.status}`);
        return data;
    }
    const button = (label, kind, onClick) => {
        const node = el('button', label, `btn ${kind}`);
        node.type = 'button';
        node.addEventListener('click', async () => {
            node.disabled = true;
            try { await onClick(); } catch (error) { say(error.message, true); } finally { node.disabled = false; }
        });
        return node;
    };
    function say(text, error = false) {
        const box = document.getElementById('nightAiMessage');
        if (!box) return;
        box.replaceChildren(text ? el('p', text, error ? 'night-ai-error' : 'night-ai-note') : '');
        if (text) box.setAttribute('role', error ? 'alert' : 'status');
    }
    function table(headers, rows) {
        if (!rows.length) return el('p', 'Пока пусто.', 'night-ai-note');
        const wrap = el('div', undefined, 'night-ai-table');
        const node = el('table', undefined, 'data-table');
        const head = el('tr');
        headers.forEach((name) => head.append(el('th', name)));
        node.append(head, ...rows);
        wrap.append(node);
        return wrap;
    }
    const cells = (values) => {
        const row = el('tr');
        for (const value of values) {
            const cell = el('td');
            if (value instanceof Node) cell.append(value); else cell.textContent = value ?? '—';
            row.append(cell);
        }
        return row;
    };
    const actions = (...nodes) => { const box = el('div', undefined, 'night-ai-actions'); box.append(...nodes); return box; };

    function field(label, control, hint) {
        const group = el('label', undefined, 'form-group');
        group.append(el('span', label, 'form-label'), control);
        if (hint) group.append(el('span', hint, 'form-hint'));
        return group;
    }
    function select(options, value) {
        const node = el('select', undefined, 'form-select');
        for (const [key, label] of options) {
            const option = el('option', label);
            option.value = key;
            node.append(option);
        }
        if (value !== undefined) node.value = value;
        return node;
    }
    const input = (value = '', type = 'text') => {
        const node = el('input', undefined, 'form-input');
        node.type = type;
        node.value = value;
        return node;
    };

    function profileForm(box) {
        const catalog = state.catalog;
        const editing = state.editing;
        const form = el('form', undefined, 'card night-ai-form');
        form.noValidate = true;
        form.append(el('h3', editing ? `Профиль «${editing.label}» — новая ревизия` : 'Новый профиль ведущего'));
        const label = input(editing ? editing.label : '');
        label.maxLength = 80;
        label.required = true;
        const presets = catalog.presets.map((row) => [row.id, row.local ? `${row.id} (локальный)` : row.id]);
        const preset = select(presets, editing ? editing.preset : presets[0]?.[0]);
        const policy = el('select', undefined, 'form-select');
        const adapter = el('select', undefined, 'form-select');
        const auth = el('select', undefined, 'form-select');
        const model = input(editing ? editing.model_id : '');
        model.setAttribute('list', 'nightAiModels');
        model.autocomplete = 'off';
        model.spellcheck = false;
        const models = el('datalist');
        models.id = 'nightAiModels';
        const extra = el('div', undefined, 'night-ai-extra');
        const extraInputs = {};
        // Secret: write-only, never prefilled, not remembered by the browser.
        const secret = input('', 'password');
        secret.autocomplete = 'new-password';
        secret.spellcheck = false;
        secret.setAttribute('data-1p-ignore', '');
        secret.setAttribute('data-lpignore', 'true');
        const localNote = el('p', 'Адрес этой модели доступен воркеру на сервере, а не компьютеру игрока.', 'form-hint');
        const sync = () => {
            const row = catalog.presets.find((item) => item.id === preset.value);
            if (!row) return;
            const allowed = catalog.policies.filter((item) => item.presets.includes(row.id));
            policy.replaceChildren(...allowed.map((item) => { const o = el('option', item.label); o.value = JSON.stringify([item.policy_id, item.version]); return o; }));
            adapter.replaceChildren(...row.adapters.map((name) => { const o = el('option', name); o.value = name; return o; }));
            auth.replaceChildren(...row.auth_modes.map((name) => { const o = el('option', name === 'none' ? 'без ключа' : name); o.value = name; return o; }));
            models.replaceChildren(...catalog.known_models.filter(([id]) => id === row.id).map(([, name]) => { const o = el('option'); o.value = name; return o; }));
            extra.replaceChildren();
            for (const key of Object.keys(extraInputs)) delete extraInputs[key];
            for (const name of [...row.required_fields, ...row.optional_fields]) {
                extraInputs[name] = input();
                extra.append(field(FIELD[name] || name, extraInputs[name], row.required_fields.includes(name) ? 'обязательно' : 'необязательно'));
            }
            localNote.hidden = !row.local;
            model.placeholder = row.manual_model_id ? 'ID модели у провайдера' : 'выбери из разрешённых';
        };
        preset.addEventListener('change', sync);
        sync();
        form.append(field('Название', label), field('Провайдер', preset), field('Подключение', policy), localNote,
            field('Адаптер', adapter), field('Авторизация', auth), field('Модель', model), models, extra,
            field('Ключ API', secret, editing ? (editing.credential_configured ? 'Ключ сохранён (••••). Оставь пустым, чтобы не менять.' : 'Ключа нет.') : 'Сохраняется зашифрованным, обратно не показывается.'));
        const save = el('button', editing ? 'Сохранить ревизию' : 'Создать профиль', 'btn btn-primary');
        save.type = 'submit';
        const cancel = button('Отмена', 'btn-secondary', async () => { state.editing = null; renderForm(box); });
        form.append(actions(save, ...(editing ? [cancel] : [])));
        form.addEventListener('submit', async (event) => {
            event.preventDefault();
            const settings = {preset: preset.value, model_id: model.value.trim(), adapter: adapter.value, auth_mode: auth.value};
            if (policy.value) settings.endpoint_policy = JSON.parse(policy.value);
            const project = {};
            for (const [name, node] of Object.entries(extraInputs)) if (node.value.trim()) project[name] = node.value.trim();
            if (Object.keys(project).length) settings.project_fields = project;
            if (!label.value.trim() || !settings.model_id) { say('Нужны название и модель.', true); return; }
            const body = {expected_revision: editing ? editing.current_revision : 0, label: label.value.trim(), settings, client_request_id: requestId()};
            if (secret.value) body.secret = secret.value;
            save.disabled = true;
            try {
                await api(editing ? `/profiles/${editing.profile_id}/revisions` : '/profiles', body);
                secret.value = '';
                state.editing = null;
                say('Профиль сохранён. Новый профиль выключен — включи его, чтобы одобрять запросы.');
                await load();
            } catch (error) { say(error.message, true); } finally { save.disabled = false; secret.value = ''; }
        });
        return form;
    }
    function renderForm(box) {
        box.replaceChildren(state.catalog.presets.length ? profileForm(box)
            : el('p', 'Оператор не разрешил ни одного провайдера (манифест пуст).', 'night-ai-note'));
    }

    function profilesTable() {
        return table(['Название', 'Провайдер', 'Модель', 'Ключ', 'Ревизия', 'Состояние', ''], state.profiles.map((item) => cells([
            item.label, item.preset, item.model_id, item.masked_key || 'нет', String(item.current_revision),
            `${item.enabled ? 'включён' : 'выключен'}${item.is_default ? ' · по умолчанию' : ''}`,
            actions(
                button(item.enabled ? 'Выключить' : 'Включить', 'btn-secondary', async () => {
                    await api(`/profiles/${item.profile_id}/enabled`, {enabled: !item.enabled, client_request_id: requestId()});
                    await load();
                }),
                button(item.is_default ? 'Снять умолчание' : 'По умолчанию', 'btn-secondary', async () => {
                    await api('/profiles/default', {profile_id: item.is_default ? null : item.profile_id, client_request_id: requestId()});
                    await load();
                }),
                button('Изменить', 'btn-secondary', async () => {
                    state.editing = item;
                    const box = document.getElementById('nightAiForm');
                    renderForm(box);
                    box.scrollIntoView({block: 'nearest'});
                })),
        ])));
    }

    function requestsTable(items) {
        const usable = state.profiles.filter((item) => item.enabled);
        return table(['Когда', 'Комната', 'Кто просит', 'Статус', 'Решение'], items.map((item) => {
            let decision = el('span', item.reason || '—');
            if (item.status === 'pending') {
                if (!usable.length) decision = el('span', 'Нет включённых профилей', 'night-ai-note');
                const chosen = select(usable.map((p) => [p.profile_id, `${p.label} · ${p.model_id}`]),
                    (usable.find((p) => p.is_default) || usable[0] || {}).profile_id);
                const approve = button('Одобрить', 'btn-primary', async () => {
                    const profile = usable.find((p) => p.profile_id === chosen.value);
                    await api(`/requests/${item.request_id}/decision`, {decision: 'approve', profile_id: profile.profile_id,
                        profile_revision: profile.current_revision, caps: null, client_request_id: requestId()});
                    say(state.catalog.narration_ready ? 'Одобрено: новые сцены этой партии пишет ведущий-ИИ.'
                        : 'Одобрено. Генерация сцен на сервере ещё не подключена — партия пока идёт на авторском тексте.');
                    await load();
                });
                const deny = button('Отказать', 'btn-secondary', async () => {
                    await api(`/requests/${item.request_id}/decision`, {decision: 'deny', profile_id: null,
                        profile_revision: null, caps: null, client_request_id: requestId()});
                    say('Отказ отправлен. Партия продолжается на авторском тексте.');
                    await load();
                });
                decision = usable.length ? actions(chosen, approve, deny) : actions(decision, deny);
            }
            return cells([when(item.created_at), item.room_title, item.requester_display_name,
                `${REQUEST[item.status] || item.status}${item.status === 'pending' ? ' до ' + when(item.expires_at) : ''}`, decision]);
        }));
    }

    function bindingsTable(items) {
        return table(['С', 'Партия', 'Режим', 'Статус', 'До', ''], items.map((item) => cells([
            when(item.created_at), item.game_id, item.mode === 'byok' ? 'свой ключ игрока' : 'профиль админа',
            `${BINDING[item.status] || item.status}${item.health && item.health !== 'ok' ? ' · ' + item.health : ''}`,
            when(item.valid_until),
            item.status === 'active' ? button('Отозвать', 'btn-secondary', async () => {
                await api(`/bindings/${item.binding_id}/revoke`, {client_request_id: requestId()});
                say('Отозвано: партия вернулась к авторскому тексту.');
                await load();
            }) : '',
        ])));
    }

    async function load() {
        const root = document.getElementById('nightAiContent');
        if (!root) return;
        try {
            state.catalog = await api('/catalog');
            if (!state.catalog.enabled) {
                root.replaceChildren(el('p', 'Ведущий-ИИ выключен на этом сервере (NIGHT_NARRATOR_ENABLED). Партии идут на авторском тексте.', 'night-ai-note'));
                return;
            }
            const [profiles, requests, bindings] = await Promise.all([api('/profiles?limit=100'), api('/requests?limit=100'), api('/bindings?limit=100')]);
            state.profiles = profiles.items;
            const status = el('p', [
                state.catalog.external_allowed ? 'Облачные провайдеры разрешены.' : 'Выход в облако запрещён: работают только локальные подключения.',
                state.catalog.vault_ready ? 'Ключи шифруются.' : 'Ключи шифрования не настроены — профили с ключом сохранить нельзя.',
                state.catalog.narration_ready ? '' : 'Генерация сцен ещё не подключена на этом сервере: одобренные партии пока идут на авторском тексте.',
            ].filter(Boolean).join(' '), 'night-ai-note');
            const formBox = el('div');
            formBox.id = 'nightAiForm';
            const pending = requests.items.filter((item) => item.status === 'pending').length;
            root.replaceChildren(status,
                el('h2', 'Профили'), profilesTable(), formBox,
                el('h2', `Запросы${pending ? ` · ${pending} ждут` : ''}`), requestsTable(requests.items),
                el('h2', 'Привязки к партиям'), bindingsTable(bindings.items));
            renderForm(formBox);
        } catch (error) { root.replaceChildren(el('p', error.message, 'night-ai-error')); }
    }

    window.loadNightAi = load;
    document.addEventListener('DOMContentLoaded', () => {
        document.getElementById('nightAiRefresh')?.addEventListener('click', () => { say(''); load(); });
        document.querySelector('[data-section="night-ai"]')?.addEventListener('click', load);
        if (location.hash === '#night-ai') load();
    });
})();
