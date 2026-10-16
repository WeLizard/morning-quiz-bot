// Admin section "Отчёты": list, card with context and screenshots, status buttons.
// All server values are inserted with textContent; images load from the same origin.
(() => {
    const STATUS = {new: 'Новый', in_progress: 'В работе', done: 'Готово'};
    const el = (tag, text, className) => {
        const node = document.createElement(tag);
        if (text !== undefined) node.textContent = text;
        if (className) node.className = className;
        return node;
    };
    const api = async (path, options) => {
        const response = await fetch(path, options);
        if (!response.ok) {
            let detail = response.statusText;
            try { detail = (await response.json()).detail || detail; } catch (_) { /* keep status text */ }
            throw new Error(detail);
        }
        return response.json();
    };
    const when = (iso) => iso ? new Date(iso).toLocaleString('ru-RU') : '—';

    async function openCard(id) {
        const box = document.getElementById('problemReportCard');
        box.replaceChildren(el('p', 'Загрузка...'));
        try {
            const report = await api(`/api/admin/problem-reports/${id}`);
            const card = el('div', undefined, 'card');
            card.append(el('h2', `Отчёт №${report.id} · ${STATUS[report.status] || report.status}`));
            card.append(el('p', `${report.display_name} · ${report.channel}${report.telegram_user_id ? ' · tg ' + report.telegram_user_id : ''} · ${when(report.created_at)}`));
            const text = el('p', report.text);
            text.style.whiteSpace = 'pre-wrap';
            card.append(text);
            const actions = el('div');
            for (const [value, label] of Object.entries(STATUS)) {
                const button = el('button', label, 'btn btn-secondary');
                button.type = 'button';
                button.disabled = report.status === value;
                button.addEventListener('click', async () => {
                    try {
                        await api(`/api/admin/problem-reports/${id}`, {method: 'PATCH',
                            headers: {'Content-Type': 'application/json'}, body: JSON.stringify({status: value})});
                        await load();
                        await openCard(id);
                    } catch (error) { box.prepend(el('p', error.message)); }
                });
                actions.append(button, ' ');
            }
            card.append(actions);
            const context = {version: report.build, account: report.account_id, request: report.request_id, ...report.context};
            const pre = el('pre', JSON.stringify(context, null, 2));
            pre.style.overflow = 'auto';
            card.append(el('h3', 'Контекст'), pre);
            if (report.images.length) {
                const row = el('div');
                row.style.cssText = 'display:flex;flex-wrap:wrap;gap:8px';
                for (const image of report.images) {
                    const link = el('a');
                    link.href = `/api/admin/problem-reports/${id}/images/${image.position}`;
                    link.target = '_blank';
                    link.rel = 'noopener';
                    const img = el('img');
                    img.src = link.href;
                    img.alt = `Скриншот ${image.position + 1}`;
                    img.loading = 'lazy';
                    img.style.cssText = 'max-width:240px;max-height:240px;border-radius:8px';
                    link.append(img);
                    row.append(link);
                }
                card.append(el('h3', 'Скриншоты'), row);
            }
            box.replaceChildren(card);
        } catch (error) { box.replaceChildren(el('p', error.message)); }
    }

    async function load() {
        const list = document.getElementById('problemReportsList');
        const status = document.getElementById('problemReportsStatus').value;
        try {
            const data = await api('/api/admin/problem-reports?limit=100' + (status ? `&status=${status}` : ''));
            if (!data.items.length) { list.replaceChildren(el('p', 'Отчётов нет.')); return; }
            const table = el('table', undefined, 'data-table');
            const head = el('tr');
            for (const name of ['№', 'Время', 'Статус', 'Кто', 'Экран', 'Текст', 'Фото']) head.append(el('th', name));
            table.append(head);
            for (const item of data.items) {
                const row = el('tr');
                row.style.cursor = 'pointer';
                row.tabIndex = 0;
                for (const value of [item.id, when(item.created_at), STATUS[item.status] || item.status,
                    `${item.display_name} (${item.channel})`, item.screen || '—', item.text, item.images]) row.append(el('td', String(value)));
                row.addEventListener('click', () => openCard(item.id));
                row.addEventListener('keydown', (event) => { if (event.key === 'Enter') openCard(item.id); });
                table.append(row);
            }
            const wrap = el('div');
            wrap.style.overflowX = 'auto';
            wrap.append(table);
            list.replaceChildren(wrap);
        } catch (error) { list.replaceChildren(el('p', error.message)); }
    }

    window.loadProblemReports = load;
    document.addEventListener('DOMContentLoaded', () => {
        document.getElementById('problemReportsStatus')?.addEventListener('change', load);
        document.getElementById('problemReportsRefresh')?.addEventListener('click', load);
        document.querySelector('[data-section="problem-reports"]')?.addEventListener('click', load);
    });
})();
