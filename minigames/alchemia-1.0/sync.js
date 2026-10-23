/* Server collection recovery and verified expedition commands. Offline play stays local. */
(() => {
    'use strict';
    const guestId = /^[0-9a-f-]{36}$/.test(window.MQB_ALCHEMY_GUEST_ID || '')
        ? window.MQB_ALCHEMY_GUEST_ID : null;
    const API = guestId ? '/api/guest/alchemy/' : '/api/mini/alchemy/';
    const PRIMARY = guestId ? `alchemia.atlas.guest.${guestId}` : 'alchemia.atlas';
    const LEGACY = guestId ? [] : ['alchemia.atlas.v5', 'alchemia.atlas.v4', 'alchemia.atlas.v3',
        'alchemia.atlas.v2', 'alchemia.atlas.v1', 'elementAlchemyDiscovered'];
    const RELOADED_KEY = 'mqb-alchemy-restored';
    const strings = value => Array.isArray(value) ? value.filter(item => typeof item === 'string') : [];
    let busy = false, staleGuest = false, staleMini = false, telegramSession = false, unverifiedNoticeShown = false;
    let miniUserId = null, hadSession = false, sessionAttempt = null, craftQueue = Promise.resolve();
    let sessionGeneration = 0;
    const claimsInFlight = new Map(), pendingMemory = new Map();
    const revision = () => window.Alchemia?.catalogRevision;
    const status = value => window.Alchemia?.setServerStatus?.(value);
    const headers = () => guestId
        ? {'Content-Type': 'application/json', 'X-Guest-CSRF': '1', 'X-Guest-Account': guestId}
        : {'Content-Type': 'application/json', 'X-Mini-CSRF': '1', 'X-Mini-User': miniUserId};
    const commandId = () => typeof crypto !== 'undefined' && crypto.randomUUID
        ? crypto.randomUUID() : `alchemy-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
    const pendingKey = () => `${PRIMARY}.pending-claims.${guestId || miniUserId || 'session'}`;

    function readState() {
        let best = null;
        for (const key of [PRIMARY, ...LEGACY]) {
            let raw;
            try { raw = JSON.parse(localStorage.getItem(key) || 'null'); } catch { continue; }
            if (Array.isArray(raw)) raw = {discovered: strings(raw)};
            if (raw && Array.isArray(raw.discovered) && (!best || raw.discovered.length > best.discovered.length)) best = raw;
        }
        return best;
    }
    function summary(state) {
        const attempts = Number(state.attempts);
        return {
            discovered: [...new Set(strings(state.discovered))].slice(0, 2000),
            crafted: [...new Set([...strings(state.recipeKeys), ...strings(state.crafted)])].slice(0, 4000),
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
        } catch { /* Visual notice is optional. */ }
    }
    function pendingClaims() {
        const key = pendingKey();
        if (pendingMemory.has(key)) return pendingMemory.get(key);
        let commands = {};
        try {
            const raw = JSON.parse(localStorage.getItem(key) || '{}');
            if (raw && !Array.isArray(raw) && typeof raw === 'object') {
                for (const [id, command] of Object.entries(raw).slice(0, 200)) {
                    if (command && command.stage_id === id && typeof command.command_id === 'string'
                        && /^[0-9a-f]{64}$/.test(command.catalog_revision)) commands[id] = {
                            command_id: command.command_id, stage_id: id, catalog_revision: command.catalog_revision};
                }
            }
        } catch { /* Keep the in-memory retry when storage is unavailable. */ }
        pendingMemory.set(key, commands);
        return commands;
    }
    function savePending(commands) {
        try { localStorage.setItem(pendingKey(), JSON.stringify(commands)); } catch {}
    }
    function hasPendingClaim(id) { return Boolean(pendingClaims()[id]); }

    const fresh = () => ({format: 'alchemia', version: 2, release: '5.1-refined', claims: [],
        serverClaims: [], expeditionPoints: 0, claimReceipts: [], activeCampaign: null,
        updatedAt: Date.now(), discovered: [], recipeKeys: [], tried: [], favorites: [],
        achievements: [], history: [], attempts: 0});

    function restore(data) {
        if (staleGuest || staleMini) return false;
        if (!data || typeof data !== 'object') return false;
        const discovered = strings(data.discovered), recipes = strings(data.crafted);
        const attempts = Number.isInteger(data.attempts) && data.attempts >= 0 ? data.attempts : 0;
        let current;
        try { current = JSON.parse(localStorage.getItem(PRIMARY) || 'null'); } catch {}
        if (!current || !Array.isArray(current.discovered)) current = fresh();
        const added = discovered.some(id => !current.discovered.includes(id));
        const localRecipes = strings(current.recipeKeys);
        const recipesAdded = recipes.some(key => !localRecipes.includes(key));
        const attemptsAdded = attempts > (current.attempts || 0);
        const hasClaims = Array.isArray(data.claims);
        const claimsChanged = hasClaims && (JSON.stringify(current.serverClaims || []) !== JSON.stringify(data.claims)
            || current.expeditionPoints !== data.expedition_points || current.catalogRevision !== data.catalog_revision
            || JSON.stringify(current.claimReceipts || []) !== JSON.stringify(data.claim_receipts || []));
        current.discovered = [...new Set([...current.discovered, ...discovered])];
        current.recipeKeys = [...new Set([...localRecipes, ...recipes])];
        current.attempts = Math.max(current.attempts || 0, attempts);
        if (hasClaims) {
            current.serverClaims = strings(data.claims);
            current.expeditionPoints = Number.isInteger(data.expedition_points) ? Math.max(0, data.expedition_points) : 0;
            current.claimReceipts = Array.isArray(data.claim_receipts) ? data.claim_receipts : [];
            current.catalogRevision = data.catalog_revision;
        }
        current.updatedAt = Date.now();
        try { localStorage.setItem(PRIMARY, JSON.stringify(current)); } catch {}
        if (data.awarded > 0) banner(`Алхимия: +${data.awarded} очков в профиль · всего ${data.points_total}`);
        // Apply even an unchanged collection: claims and verified ingredients are independent.
        try {
            const game = window.Alchemia;
            if (game && typeof game.applyRemoteState === 'function') {
                const applied = game.applyRemoteState({...data, discovered, recipeKeys: recipes, attempts});
                if (applied?.accepted || applied?.added > 0 || applied?.recipesAdded > 0
                    || applied?.attemptsAdded || applied?.claimsChanged) return true;
            }
        } catch {}
        if (!added && !recipesAdded && !attemptsAdded && !claimsChanged) return false;
        try { if (sessionStorage.getItem(RELOADED_KEY) === '1') return true; } catch {}
        try { sessionStorage.setItem(RELOADED_KEY, '1'); } catch {}
        try { location.reload(); } catch {}
        return true;
    }
    async function errorBody(response) {
        try { return await response.json(); } catch { return {}; }
    }
    function authFailure(response, error = {}) {
        if (response.status === 401 || (response.status === 409 && error.code === 'profile_changed')) {
            sessionGeneration += 1;
            telegramSession = false;
            if (guestId) staleGuest = true;
            else if (response.status === 409) staleMini = true;
            status(response.status === 409 ? 'profile-changed' : 'unauthorized');
            banner(response.status === 409 ? (guestId ? 'Гостевой профиль изменился. Открой игру заново из приложения.'
                : 'Профиль изменился. Открой игру заново из приложения.')
                : guestId ? 'Доступ к гостевому профилю потерян. Локальное сохранение осталось на этом устройстве.'
                : 'Сессия истекла. Открой игру из приложения. Локальное сохранение осталось на этом устройстве.');
            return true;
        }
        return false;
    }
    /* The Mini session cookie lives 15 minutes. While the page is open it is renewed (the same call as
       QW.session.keepAlive, but with the X-Mini-CSRF header the server requires for cookie-authenticated POSTs). */
    let renewTimer = 0, lastRenew = Date.now();
    async function renewSession() {
        if (guestId || document.hidden || !telegramSession) return;
        lastRenew = Date.now();
        try {
            const response = await fetch('/api/mini/session/renew', {method: 'POST', credentials: 'same-origin',
                headers: {'Content-Type': 'application/json', 'X-Mini-CSRF': '1'}, body: '{}'});
            if (response.status === 401 || response.status === 403) { clearInterval(renewTimer); renewTimer = 0; }
        } catch {}
    }
    function keepSessionAlive() {
        if (guestId || renewTimer) return;
        renewTimer = setInterval(renewSession, 8 * 60 * 1000);
    }
    async function establishSession() {
        if (guestId) return !staleGuest;
        if (staleMini) return false;
        if (telegramSession) return true;
        if (sessionAttempt) return sessionAttempt;
        sessionAttempt = (async () => {
            try {
                const response = await fetch('/api/mini/me', {credentials: 'same-origin'});
                telegramSession = response.ok;
                if (response.ok) {
                    const profile = await response.json();
                    // The Account's «Контрастный режим» (UI_RULES §16) wins over this device's cache.
                    window.QW?.prefs?.applyAccount?.(profile);
                    const userId = String(profile.user_id || 'session');
                    if (miniUserId !== null && miniUserId !== userId) {
                        sessionGeneration += 1;
                        staleMini = true; telegramSession = false; status('profile-changed');
                        banner('Профиль изменился. Открой игру заново из приложения.');
                        return false;
                    }
                    miniUserId = userId;
                    hadSession = true;
                    status('connecting');
                } else status(hadSession ? 'unauthorized' : 'local');
            } catch { status(location.protocol === 'file:' && !hadSession ? 'local' : 'offline'); }
            return telegramSession;
        })();
        try { return await sessionAttempt; } finally { sessionAttempt = null; }
    }
    async function sync() {
        if (busy || staleGuest) return;
        if (!guestId && !telegramSession && !(await establishSession())) return;
        busy = true;
        try {
            const generation = sessionGeneration;
            const response = await fetch(API + 'sync', {method: 'POST', credentials: 'same-origin',
                headers: headers(), body: JSON.stringify(summary(readState() || {}))});
            if (generation !== sessionGeneration) return;
            if (!response.ok) {
                if (authFailure(response, await errorBody(response))) return;
                status('offline'); return;
            }
            const data = await response.json();
            if (generation !== sessionGeneration) return;
            restore(data);
        } catch { status('offline'); } finally { busy = false; }
    }
    function verifyCraft(ingredientA, ingredientB) {
        craftQueue = craftQueue.then(async () => {
            if (!(await establishSession())) return;
            try {
                const generation = sessionGeneration;
                const response = await fetch(API + 'craft', {method: 'POST', credentials: 'same-origin',
                    headers: headers(), body: JSON.stringify({command_id: commandId(),
                        ingredient_a: ingredientA, ingredient_b: ingredientB})});
                if (generation !== sessionGeneration) return;
                if (!response.ok) {
                    if (authFailure(response, await errorBody(response))) return;
                    status('offline'); return;
                }
                const result = await response.json();
                if (generation !== sessionGeneration) return;
                restore({...result, awarded: 0});
                if (result.awarded > 0) {
                    banner(`Подтверждено сервером: +${result.awarded} очков · всего ${result.points_total}`);
                } else if (!result.verified && !unverifiedNoticeShown) {
                    unverifiedNoticeShown = true;
                    banner('Старые открытия сохранены. Для подтверждения награды получи элементы заново из базовых стихий.');
                }
            } catch { status('offline'); }
        });
        return craftQueue;
    }
    function claimStage(stageId) {
        if (claimsInFlight.has(stageId)) return claimsInFlight.get(stageId);
        const attempt = (async () => {
            await craftQueue;
            if (!(await establishSession())) return {ok: false, message: 'Нет активной сессии. Печать не подтверждена.'};
            const pending = pendingClaims();
            if (!pending[stageId]) {
                if (!/^[0-9a-f]{64}$/.test(revision() || '')) return {ok: false, message: 'Не удалось проверить версию каталога. Открой игру заново.'};
                pending[stageId] = {command_id: commandId(), stage_id: stageId, catalog_revision: revision()};
                savePending(pending);
            }
            const command = pending[stageId];
            try {
                const generation = sessionGeneration;
                const response = await fetch(API + 'claim-stage', {method: 'POST', credentials: 'same-origin',
                    headers: headers(), body: JSON.stringify(command)});
                if (generation !== sessionGeneration) return {ok: false, message: 'Сессия изменилась. Открой игру заново из приложения.'};
                if (!response.ok) {
                    const error = await errorBody(response);
                    if (authFailure(response, error)) return {ok: false, message: 'Доступ к профилю потерян. Локальное сохранение осталось.'};
                    // A definitive rejection cannot have granted this command. Unknown server
                    // failures retain the exact command for a safe retry, including its revision.
                    if (response.status >= 400 && response.status < 500 && response.status !== 429) {
                        delete pending[stageId]; savePending(pending);
                    }
                    if (response.status === 409) await sync();
                    if (error.code === 'catalog_changed') status('catalog-mismatch');
                    else if (response.status !== 409) status('offline');
                    return {ok: false, message: typeof error.detail === 'string' ? error.detail
                        : 'Сервер не подтвердил печать. Повтори после восстановления связи.'};
                }
                const data = await response.json();
                if (generation !== sessionGeneration) return {ok: false, message: 'Сессия изменилась. Открой игру заново из приложения.'};
                if (data.command_id !== command.command_id || data.stage_id !== stageId
                    || !Array.isArray(data.claims) || !data.claims.includes(stageId)
                    || !Number.isInteger(data.awarded_expedition_points)) {
                    status('offline');
                    return {ok: false, message: 'Ответ не подтвердил печать. Повтори ту же команду.'};
                }
                restore(data);
                delete pending[stageId]; savePending(pending);
                return {ok: true, data};
            } catch {
                status('offline');
                return {ok: false, message: 'Нет связи. Результат неизвестен; повтор отправит ту же команду без двойной награды.'};
            }
        })();
        claimsInFlight.set(stageId, attempt);
        attempt.finally(() => claimsInFlight.delete(stageId));
        return attempt;
    }
    window.MQBAlchemySync = Object.freeze({verifyCraft, claimStage, hasPendingClaim});
    status('connecting');
    addEventListener('load', async () => {
        if (await establishSession()) await sync();
        setInterval(sync, 60000);
        keepSessionAlive();
    });
    addEventListener('visibilitychange', () => {
        if (document.hidden) sync();
        else if (renewTimer && Date.now() - lastRenew > 5 * 60 * 1000) renewSession();
    });
})();
