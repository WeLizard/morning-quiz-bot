/* Мост «Алхимия ↔ квиз»: отправляет сводку прогресса на сервер и подставляет
   серверное сохранение. Игра остаётся автономной: без сессии или без сети ничего
   не происходит, а весь блок обёрнут в try/catch. */
(() => {
    'use strict';
    const guestId = /^[0-9a-f-]{36}$/.test(window.MQB_ALCHEMY_GUEST_ID || '')
        ? window.MQB_ALCHEMY_GUEST_ID : null;
    const ENDPOINT = guestId ? '/api/guest/alchemy/sync' : '/api/mini/alchemy/sync';
    const CRAFT_ENDPOINT = '/api/mini/alchemy/craft';
    const PRIMARY = guestId ? `alchemia.atlas.guest.${guestId}` : 'alchemia.atlas';
    const LEGACY = guestId ? [] : ['alchemia.atlas.v5', 'alchemia.atlas.v4', 'alchemia.atlas.v3',
                    'alchemia.atlas.v2', 'alchemia.atlas.v1', 'elementAlchemyDiscovered'];
    const RELOADED_KEY = 'mqb-alchemy-restored';
    const INTERVAL_MS = 60000;
    const MAX_DISCOVERED = 2000;
    const MAX_CRAFTED = 4000;
    let busy = false;
    let staleGuest = false;
    let unverifiedNoticeShown = false;
    let telegramSession = false;

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

    async function verifyCraft(ingredientA, ingredientB) {
        if (guestId) return; // Guests keep their local collection; no rated rewards.
        if (!telegramSession && !(await establishSession())) return;
        try {
            const commandId = typeof crypto !== 'undefined' && crypto.randomUUID
                ? crypto.randomUUID()
                : `alchemy-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
            const response = await fetch(CRAFT_ENDPOINT, {
                method: 'POST', credentials: 'same-origin',
                headers: {'Content-Type': 'application/json', 'X-Mini-CSRF': '1'},
                body: JSON.stringify({command_id: commandId,
                    ingredient_a: ingredientA, ingredient_b: ingredientB}),
            });
            if (!response.ok) return;
            const result = await response.json();
            if (result.awarded > 0) {
                banner(`Подтверждено сервером: +${result.awarded} очков · всего ${result.points_total}`);
            } else if (!result.verified && !unverifiedNoticeShown) {
                unverifiedNoticeShown = true;
                banner('Старые открытия сохранены, но не дают рейтинговых очков. Новые подтверждённые открытия начинаются с базовых элементов.');
            }
        } catch { /* Offline play remains available; the local save is preserved. */ }
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
            if (!data.discovered.length && !(data.crafted || []).length && !data.attempts) return false;
            current = fresh();
        }
        const local = new Set(current.discovered);
        const added = data.discovered.filter(id => !local.has(id));
        const remoteRecipes = Array.isArray(data.crafted) ? data.crafted : [];
        const localRecipes = new Set(Array.isArray(current.recipeKeys) ? current.recipeKeys : []);
        const recipesAdded = remoteRecipes.filter(key => !localRecipes.has(key));
        const attempts = Number.isInteger(data.attempts) && data.attempts >= 0 ? data.attempts : 0;
        const attemptsAdded = attempts > (Number.isInteger(current.attempts) ? current.attempts : 0);
        if (data.awarded > 0) banner(`Алхимия: +${data.awarded} очков в профиль · всего ${data.points_total}`);
        if (!added.length && !recipesAdded.length && !attemptsAdded) return false;
        // Сохранение обновляем всегда: это страховка, даже если игра сейчас занята
        // или не умеет принимать чужой прогресс.
        current.discovered = [...new Set([...current.discovered, ...data.discovered])];
        current.recipeKeys = [...new Set([...localRecipes, ...remoteRecipes])];
        current.attempts = Math.max(current.attempts || 0, attempts);
        current.updatedAt = Date.now();
        try { localStorage.setItem(PRIMARY, JSON.stringify(current)); } catch { /* ниже всё равно попробуем */ }
        // Главное — влить прогресс в живую игру: она держит состояние в памяти и
        // иначе перезапишет его своим при следующем сохранении.
        try {
            const game = window.Alchemia;
            if (game && typeof game.applyRemoteState === 'function') {
                const applied = game.applyRemoteState({discovered: data.discovered,
                    recipeKeys: remoteRecipes, attempts});
                if (applied.added > 0 || applied.recipesAdded > 0 || applied.attemptsAdded) return true;
            }
        } catch { /* ниже сработает перезагрузка */ }
        let already = false;
        try { already = sessionStorage.getItem(RELOADED_KEY) === '1'; } catch {}
        if (already) return true;
        try { sessionStorage.setItem(RELOADED_KEY, '1'); } catch {}
        try { location.reload(); } catch {}
        return true;
    }

    const EMPTY = {discovered: [], recipeKeys: [], attempts: 0};

    async function sync() {
        if (busy || staleGuest) return;
        if (!guestId && !telegramSession) return;  // автономный HTML без аккаунта
        // Спрашиваем сервер даже без локального сохранения: на новом устройстве
        // игра ещё ничего не записала, и именно так подтягивается чужой прогресс.
        const state = readState() || EMPTY;
        busy = true;
        try {
            const response = await fetch(ENDPOINT, {
                method: 'POST', credentials: 'same-origin',
                headers: guestId
                    ? {'Content-Type': 'application/json', 'X-Guest-CSRF': '1', 'X-Guest-Account': guestId}
                    : {'Content-Type': 'application/json', 'X-Mini-CSRF': '1'},
                body: JSON.stringify(summary(state)),
            });
            if (guestId && response.status === 409) {
                staleGuest = true;
                banner('Гостевой профиль изменился. Открой игру заново из приложения.');
                return;
            }
            if (guestId && response.status === 401) {
                staleGuest = true;
                banner('Доступ к гостевому профилю потерян. Локальное сохранение осталось на этом устройстве.');
                return;
            }
            if (!response.ok) return;
            restore(await response.json());
        } catch { /* игра не должна страдать из-за сети */ } finally { busy = false; }
    }

    window.MQBAlchemySync = Object.freeze({verifyCraft});
    async function establishSession() {
        if (guestId) return true;
        try {
            const response = await fetch('/api/mini/me', {credentials: 'same-origin'});
            telegramSession = response.ok;
        } catch { telegramSession = false; }
        return telegramSession;
    }
    addEventListener('load', async () => { if (await establishSession()) sync(); setInterval(sync, INTERVAL_MS); });
    addEventListener('visibilitychange', () => { if (document.hidden) sync(); });
})();
