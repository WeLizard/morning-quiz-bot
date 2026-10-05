/* Мост «Алхимия ↔ квиз»: отправляет сводку прогресса на сервер и подставляет
   серверное сохранение. Игра остаётся автономной: без сессии или без сети ничего
   не происходит, а весь блок обёрнут в try/catch. */
(() => {
    'use strict';
    const ENDPOINT = '/api/mini/alchemy/sync';
    const PRIMARY = 'alchemia.atlas';
    const LEGACY = ['alchemia.atlas.v5', 'alchemia.atlas.v4', 'alchemia.atlas.v3',
                    'alchemia.atlas.v2', 'alchemia.atlas.v1', 'elementAlchemyDiscovered'];
    const TOKEN_KEY = 'mqb-mini-token';
    const RELOADED_KEY = 'mqb-alchemy-restored';
    const INTERVAL_MS = 60000;
    const MAX_DISCOVERED = 2000;
    const MAX_CRAFTED = 4000;
    let busy = false;

    function token() {
        const fromHash = /(?:^|[#&])t=([A-Za-z0-9_-]{20,})/.exec(location.hash || '');
        if (fromHash) return fromHash[1];
        // Мини-апп кладёт токен в sessionStorage (та же вкладка) и в localStorage
        // (страница игры могла быть открыта позже и в другой вкладке).
        try { const stored = sessionStorage.getItem(TOKEN_KEY); if (stored) return stored; } catch {}
        try { const stored = localStorage.getItem(TOKEN_KEY); if (stored) return stored; } catch {}
        return '';
    }

    function readState() {
        let best = null;
        for (const key of [PRIMARY, ...LEGACY]) {
            let raw;
            try { raw = JSON.parse(localStorage.getItem(key) || 'null'); } catch { continue; }
            if (Array.isArray(raw)) {                       // самый первый формат: список id
                const state = {discovered: raw.filter(item => typeof item === 'string')};
                if (!best || state.discovered.length > best.discovered.length) best = state;
                continue;
            }
            if (raw && typeof raw === 'object' && Array.isArray(raw.discovered)) {
                if (!best || raw.discovered.length > best.discovered.length) best = raw;
            }
        }
        return best;
    }

    function summary(state) {
        const strings = value => Array.isArray(value) ? value.filter(item => typeof item === 'string') : [];
        const attempts = Number(state.attempts);
        return {
            discovered: [...new Set(strings(state.discovered))].slice(0, MAX_DISCOVERED),
            crafted: [...new Set([...strings(state.recipeKeys), ...strings(state.crafted)])].slice(0, MAX_CRAFTED),
            attempts: Number.isFinite(attempts) ? Math.max(0, Math.min(100000, Math.trunc(attempts))) : 0,
        };
    }

    function banner(text) {
        try {
            const node = document.createElement('div');
            node.textContent = text;
            node.style.cssText = 'position:fixed;left:50%;bottom:18px;transform:translateX(-50%);'
                + 'background:#101317;color:#f3f4ef;padding:10px 16px;border-radius:12px;'
                + 'font:14px/1.3 system-ui,sans-serif;box-shadow:0 6px 24px rgba(0,0,0,.35);z-index:9999;'
                + 'max-width:86vw;text-align:center;opacity:0;transition:opacity .3s';
            document.body.append(node);
            requestAnimationFrame(() => { node.style.opacity = '1'; });
            setTimeout(() => { node.style.opacity = '0'; setTimeout(() => node.remove(), 400); }, 6000);
        } catch { /* оформление не критично */ }
    }

    // Свежее состояние в формате движка. Нужно, когда игра ещё ни разу не
    // сохранялась (новое устройство): иначе подставлять серверный прогресс некуда.
    const fresh = () => ({format: 'alchemia', version: 2, release: '5.1-refined', claims: [],
        activeCampaign: null, updatedAt: Date.now(), discovered: [], recipeKeys: [], tried: [],
        favorites: [], achievements: [], history: [], attempts: 0});

    function restore(data) {
        let current;
        try { current = JSON.parse(localStorage.getItem(PRIMARY) || 'null'); } catch { current = null; }
        if (!current || typeof current !== 'object' || !Array.isArray(current.discovered)) {
            if (!data.discovered.length) return false;
            current = fresh();
        }
        const local = new Set(current.discovered);
        const added = data.discovered.filter(id => !local.has(id));
        if (data.awarded > 0) banner(`Алхимия: +${data.awarded} очков в профиль · всего ${data.points_total}`);
        if (!added.length) return false;
        current.discovered = [...new Set([...current.discovered, ...data.discovered])];
        current.updatedAt = Date.now();
        try { localStorage.setItem(PRIMARY, JSON.stringify(current)); } catch { return false; }
        // Перезагружаем страницу не больше одного раза за сессию: движок читает
        // сохранение только при старте, а петлю перезагрузок допускать нельзя.
        let already = false;
        try { already = sessionStorage.getItem(RELOADED_KEY) === '1'; } catch {}
        if (already) return true;
        try { sessionStorage.setItem(RELOADED_KEY, '1'); } catch {}
        try { location.reload(); } catch {}
        return true;
    }

    const EMPTY = {discovered: [], recipeKeys: [], attempts: 0};

    async function sync() {
        if (busy) return;
        const bearer = token();
        if (!bearer) return;                      // вне мини-аппа синхронизации нет
        // Спрашиваем сервер даже без локального сохранения: на новом устройстве
        // игра ещё ничего не записала, и именно так подтягивается чужой прогресс.
        const state = readState() || EMPTY;
        busy = true;
        try {
            const response = await fetch(ENDPOINT, {
                method: 'POST', credentials: 'same-origin',
                headers: {'Content-Type': 'application/json', Authorization: `Bearer ${bearer}`},
                body: JSON.stringify(summary(state)),
            });
            if (!response.ok) return;
            restore(await response.json());
        } catch { /* игра не должна страдать из-за сети */ } finally { busy = false; }
    }

    addEventListener('load', () => { sync(); setInterval(sync, INTERVAL_MS); });
    addEventListener('visibilitychange', () => { if (document.hidden) sync(); });
})();
