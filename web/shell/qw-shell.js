/* QuizzyWizzy shell: Telegram bridge, safe-area, fullscreen, navigation stack and the ⚙ menu.
   Classic script (no modules) so the hub, the farm (ES modules) and the single-file Alchemy can all load it:
     <script src="https://telegram.org/js/telegram-web-app.js"></script>
     <script src="/app/shell/qw-shell.js"></script>
   Works the same with and without Telegram: outside Telegram the SDK is idle and every call degrades to the browser.
   Rules: docs/design/UI_RULES.md (§4 header, §5 menu, §6 navigation, §7 bridge). */
(() => {
    'use strict';
    if (window.QW) return;
    const root = document.documentElement;
    const tg = () => window.Telegram?.WebApp;
    const call = fn => { try { return fn(); } catch { return undefined; } };
    const DESKTOP_PLATFORMS = new Set(['tdesktop', 'macos', 'weba', 'webk', 'unigram']);
    const MOBILE_PLATFORMS = new Set(['ios', 'android', 'android_x']);
    const EDGES = ['top', 'right', 'bottom', 'left'];
    const ICONS = {
        gear: '<circle cx="12" cy="12" r="3.2"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z"/>',
        back: '<path d="m15 5-7 7 7 7"/>',
        chevron: '<path d="m9 5 7 7-7 7"/>',
        home: '<path d="M3 11 12 4l9 7v9h-6v-6H9v6H3Z"/>',
        fullscreen: '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>',
        'fullscreen-exit': '<path d="M9 4v5H4M15 4v5h5M9 20v-5H4M15 20v-5h5"/>',
        user: '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
        sliders: '<path d="M4 6h10m4 0h2M4 12h4m4 0h8M4 18h12"/><circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/>',
        help: '<circle cx="12" cy="12" r="9"/><path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .9-1 1.6M12 17h.01"/>',
        flag: '<path d="M5 21V4h11l-2 4 2 4H5"/>',
        sound: '<path d="M4 9h4l5-4v14l-5-4H4Z"/><path d="M17 9a4 4 0 0 1 0 6"/>',
        sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5"/>',
        layers: '<path d="m12 3 9 5-9 5-9-5Zm-9 9 9 5 9-5"/>',
        door: '<path d="M14 3H5v18h9M10 12h11m-3-3 3 3-3 3"/>',
        book: '<path d="M4 5a2 2 0 0 1 2-2h14v16H6a2 2 0 0 0-2 2Zm0 0v16"/>',
        download: '<path d="M12 3v12m-5-5 5 5 5-5M4 21h16"/>',
    };
    const svg = icon => {
        const body = typeof icon === 'string' && icon.trim().startsWith('<') ? icon : ICONS[icon] || '';
        return body ? '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">' + body + '</svg>' : '';
    };

    const config = {
        mode: 'hub', gameId: '', title: '', home: '/app', profileUrl: '/app#settings',
        fullscreen: 'auto', history: null, color: null,
        onResize: null, onResume: null, onHome: null, onProfile: null, onTheme: null,
    };
    let booted = false;

    /* ---------------- environment ---------------- */
    // After a same-tab navigation (/app → /app/farm) the URL has no tgWebApp* params; the SDK restores them
    // from sessionStorage. The second check keeps Telegram mode even if the SDK could not restore initData.
    function telegramSession() {
        try { return /tgWebAppData|tgWebAppPlatform/.test(sessionStorage.getItem('__telegram__initParams') || ''); } catch { return false; }
    }
    function isTelegram() { return Boolean(tg()?.initData) || (Boolean(tg()) && telegramSession() && tg().platform !== 'unknown'); }
    function platform() { return isTelegram() ? (tg().platform || 'unknown') : 'browser'; }
    function versionAtLeast(version) { return Boolean(call(() => tg()?.isVersionAtLeast?.(version))); }
    function isDesktop() { return root.classList.contains('qw-desktop') || matchMedia('(min-width: 1024px)').matches; }
    const readVar = name => getComputedStyle(root).getPropertyValue(name).trim();

    function writeInsets() {
        const t = tg();
        if (t && isTelegram()) {
            for (const [source, prefix] of [[t.safeAreaInset, '--qw-tg-safe-'], [t.contentSafeAreaInset, '--qw-tg-content-']]) {
                for (const edge of EDGES) {
                    const value = Number(source?.[edge]);
                    root.style.setProperty(prefix + edge, (Number.isFinite(value) ? value : 0) + 'px');
                }
            }
            // Some Android/iOS clients report zero insets in fullscreen: keep the header clear of the status bar
            // and Telegram's own buttons, and the bottom bars clear of the system navigation (Android three-button
            // bar ≈ 48px, iOS home indicator 34px). Real non-zero insets always win, edge by edge.
            const sum = edge => Number(t.safeAreaInset?.[edge] || 0) + Number(t.contentSafeAreaInset?.[edge] || 0);
            const fallback = Boolean(t.isFullscreen && MOBILE_PLATFORMS.has(t.platform));
            const ios = t.platform === 'ios';
            const topFallback = fallback && sum('top') === 0;
            const bottomFallback = fallback && sum('bottom') === 0;
            if (topFallback) {
                root.style.setProperty('--qw-tg-safe-top', (ios ? 47 : 28) + 'px');
                root.style.setProperty('--qw-tg-content-top', '56px');
            }
            if (bottomFallback) root.style.setProperty('--qw-tg-safe-bottom', (ios ? 34 : 48) + 'px');
            root.classList.toggle('qw-inset-fallback', topFallback || bottomFallback);
            root.classList.toggle('qw-inset-fallback-top', topFallback);
            root.classList.toggle('qw-inset-fallback-bottom', bottomFallback);
            const height = Number(t.viewportStableHeight || t.viewportHeight);
            if (height > 0) root.style.setProperty('--qw-vh', height + 'px');
        }
        root.classList.toggle('qw-fullscreen', fullscreen.active());
        renderDebug();
    }

    /* ?debug=1 — read-only diagnostics line for device checks (never shows initData). */
    let debugEl = null;
    let probe = null;
    function probeLength(name) {
        probe ||= Object.assign(document.createElement('div'), {style: 'position:absolute;visibility:hidden;pointer-events:none;width:0'});
        if (!probe.isConnected) document.body.append(probe);
        probe.style.height = 'var(' + name + ')';
        return Math.round(parseFloat(getComputedStyle(probe).height) || 0) + 'px';
    }
    function renderDebug() {
        if (!/[?&]debug=1(&|$)/.test(location.search)) return;
        if (!document.body) { addEventListener('DOMContentLoaded', renderDebug, {once: true}); return; }
        if (!debugEl) {
            debugEl = document.createElement('pre');
            debugEl.id = 'qw-debug';
            debugEl.setAttribute('aria-hidden', 'true');
            debugEl.style.cssText = 'position:fixed;left:4px;bottom:calc(4px + var(--qw-safe-bottom));z-index:2147483646;margin:0;padding:6px 8px;'
                + 'max-width:calc(100vw - 8px);white-space:pre-wrap;font:12px/1.35 ui-monospace,monospace;color:#fff;background:rgb(0 0 0/.72);border-radius:8px;pointer-events:none';
            document.body.append(debugEl);
        }
        const t = tg();
        const vars = ['--qw-safe-top', '--qw-tg-safe-top', '--qw-tg-content-top', '--qw-safe-bottom', '--qw-tg-safe-bottom', '--qw-tg-content-bottom']
            .map(name => name.replace('--qw-', '') + '=' + probeLength(name));
        debugEl.textContent = [
            'sdk ' + (t?.version || '-') + ' · ' + platform() + ' · telegram=' + isTelegram() + ' · fullscreen=' + Boolean(t?.isFullscreen),
            'safeAreaInset ' + JSON.stringify(t?.safeAreaInset || null) + ' · content ' + JSON.stringify(t?.contentSafeAreaInset || null),
            vars.slice(0, 3).join(' · ') + (root.classList.contains('qw-inset-fallback-top') ? ' · fallback-top' : ''),
            vars.slice(3).join(' · ') + (root.classList.contains('qw-inset-fallback-bottom') ? ' · fallback-bottom' : ''),
            'viewport ' + innerWidth + '×' + innerHeight + ' · screen ' + screen.width + '×' + screen.height + ' · dpr ' + devicePixelRatio,
        ].join('\n');
    }

    /* ---------------- theme and preferences (hub palette; games keep their own) ---------------- */
    const prefs = {haptics: true, theme: 'system'};
    try {
        const saved = JSON.parse(localStorage.getItem('mqb-ui-preferences') || '{}');
        if (typeof saved.haptics === 'boolean') prefs.haptics = saved.haptics;
        if (['system', 'dark', 'light'].includes(saved.theme)) prefs.theme = saved.theme;
    } catch {}
    const savePrefs = () => { try { localStorage.setItem('mqb-ui-preferences', JSON.stringify(prefs)); } catch {} };
    function applyTheme() {
        if (config.mode === 'hub') {
            const scheme = prefs.theme === 'system'
                ? (tg()?.colorScheme && isTelegram() ? tg().colorScheme : (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'))
                : prefs.theme;
            root.dataset.theme = scheme;
        }
        syncChromeColors();
        call(() => config.onTheme?.(root.dataset.theme || 'dark'));
    }
    function syncChromeColors() {
        const color = config.color || readVar('--qw-game-header') || readVar('--qw-bg') || '#101317';
        if (!/^#[0-9a-f]{6}$/i.test(color)) return;
        document.querySelector('meta[name="theme-color"]')?.setAttribute('content', color);
        if (!isTelegram()) return;
        call(() => tg().setHeaderColor?.(color));
        call(() => tg().setBackgroundColor?.(color));
        call(() => tg().setBottomBarColor?.(color));
    }

    /* ---------------- fullscreen ---------------- */
    const fullscreen = {
        canToggle() {
            if (isTelegram()) return versionAtLeast('8.0') && typeof tg().requestFullscreen === 'function';
            return typeof root.requestFullscreen === 'function' && document.fullscreenEnabled !== false;
        },
        active() { return isTelegram() ? Boolean(tg().isFullscreen) : Boolean(document.fullscreenElement); },
        async toggle() {
            if (isTelegram()) {
                if (tg().isFullscreen) call(() => tg().exitFullscreen());
                else call(() => tg().requestFullscreen());
                return;
            }
            try {
                if (document.fullscreenElement) await document.exitFullscreen();
                else await root.requestFullscreen();
            } catch {}
        },
    };
    function onViewportChange() {
        writeInsets();
        call(() => config.onResize?.());
        if (menu.isOpen()) renderMenu();
    }

    /* ---------------- navigation stack (§6) ---------------- */
    const stack = [];
    let rootBack = null;
    let rootOnScreen = true;
    let suppressPop = 0;
    const backButtons = new Set();
    const useHistory = () => config.history ?? config.mode === 'game';

    function syncBack() {
        const depth = stack.length;
        const showTelegram = depth > 0 || Boolean(rootBack) || config.mode === 'game';
        if (isTelegram()) call(() => showTelegram ? tg().BackButton.show() : tg().BackButton.hide());
        // The on-screen ‹ exists only outside Telegram and only on a nested screen.
        for (const button of backButtons) button.hidden = isTelegram() || !(depth > 0 || (rootBack && rootOnScreen));
    }
    function removeEntry(entry, fromPopstate) {
        const index = stack.indexOf(entry);
        if (index < 0) return false;
        const removed = stack.length - index;
        stack.splice(index);
        if (useHistory() && entry.historyPushed) {
            const steps = fromPopstate ? removed - 1 : removed;
            if (steps > 0) { suppressPop += 1; history.go(-steps); }
        }
        syncBack();
        return true;
    }
    async function runGuard(entry) {
        try { return (await entry.onBack?.()) !== false; } catch { return false; }
    }
    const nav = {
        push(entry) {
            if (!entry || !entry.id) throw new Error('QW.nav.push needs {id}');
            const existing = stack.find(item => item.id === entry.id);
            if (existing) { existing.onBack = entry.onBack; return existing; }
            const item = {id: String(entry.id), onBack: entry.onBack, historyPushed: false};
            stack.push(item);
            if (useHistory()) { call(() => history.pushState({qwNav: item.id}, '')); item.historyPushed = true; }
            syncBack();
            return item;
        },
        pop(id) {
            const entry = id == null ? stack[stack.length - 1] : [...stack].reverse().find(item => item.id === String(id));
            return entry ? removeEntry(entry, false) : false;
        },
        has(id) { return stack.some(item => item.id === String(id)); },
        get depth() { return stack.length; },
        clear() { while (stack.length) removeEntry(stack[stack.length - 1], false); },
        /** Hub only: what BackButton does on a root page (null hides it). onScreen:false keeps the browser ‹ hidden
         *  (tab roots: the bottom bar is the navigation there), while Telegram's BackButton still leads to the parent. */
        setRoot(handler, {onScreen = true} = {}) { rootBack = typeof handler === 'function' ? handler : null; rootOnScreen = onScreen; syncBack(); },
        async back() {
            if (menu.isOpen()) { menu.close(); return true; }
            const top = stack[stack.length - 1];
            if (top) {
                const ok = await runGuard(top);
                if (ok) removeEntry(top, false);
                return ok;
            }
            if (rootBack) { await rootBack(); return true; }
            if (config.mode === 'game') { goHome(); return true; }
            return false;
        },
    };
    window.addEventListener('popstate', async () => {
        if (suppressPop > 0) { suppressPop -= 1; return; }
        if (menu.isOpen()) { menu.close(); if (useHistory()) call(() => history.pushState({qwNav: 'menu'}, '')); return; }
        const top = stack[stack.length - 1];
        if (!top || !top.historyPushed) return;
        if (await runGuard(top)) removeEntry(top, true);
        else call(() => history.pushState({qwNav: top.id}, ''));
    });

    function goHome() {
        menu.close();
        if (config.onHome) { config.onHome(); return; }
        location.assign(config.home);
    }
    function openProfile() {
        menu.close();
        if (config.onProfile) { config.onProfile(); return; }
        location.assign(config.profileUrl);
    }

    /* ---------------- header controls (§4) ---------------- */
    function iconButton(className, icon, label) {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'qw-icon-btn ' + className;
        button.setAttribute('aria-label', label);
        button.title = label;
        button.innerHTML = svg(icon);
        return button;
    }
    const gears = new Set();
    const header = {
        /** Appends the core ⚙ as the last element of the given header row. */
        mountGear(container) {
            const button = iconButton('qw-gear', 'gear', 'Меню');
            button.setAttribute('aria-haspopup', 'dialog');
            button.setAttribute('aria-expanded', 'false');
            button.dataset.qwGear = '';
            button.addEventListener('click', () => menu.toggle(button));
            container?.append(button);
            gears.add(button);
            return button;
        },
        /** Prepends ‹ (browser only, nested screens only). */
        mountBack(container) {
            const button = iconButton('qw-back', 'back', 'Назад');
            button.addEventListener('click', () => nav.back());
            container?.prepend(button);
            backButtons.add(button);
            syncBack();
            return button;
        },
    };

    /* ---------------- ⚙ menu (§5) ---------------- */
    let gameTitle = '';
    let gameItems = [];
    let account = null;
    let menuEl = null;
    let scrimEl = null;
    let openerEl = null;

    function itemNode(item, onActivate) {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'qw-menu-item' + (item.danger ? ' qw-danger' : '') + (item.core ? ' qw-core' : '');
        button.dataset.qwItem = item.id || '';
        const disabled = typeof item.disabled === 'function' ? item.disabled() : item.disabled;
        if (disabled) button.setAttribute('aria-disabled', 'true');
        button.insertAdjacentHTML('beforeend', svg(item.icon));
        const text = document.createElement('span');
        text.className = 'qw-grow';
        text.textContent = item.label;
        if (item.hint) { const hint = document.createElement('small'); hint.textContent = item.hint; text.append(hint); }
        button.append(text);
        if (typeof item.toggle === 'function') {
            const on = Boolean(call(item.toggle));
            button.setAttribute('role', 'switch');
            button.setAttribute('aria-checked', String(on));
            const knob = document.createElement('span');
            knob.className = 'qw-switch';
            knob.dataset.on = String(on);
            button.append(knob);
        } else if (item.value != null) {
            const value = document.createElement('span');
            value.className = 'qw-value';
            value.textContent = (typeof item.value === 'function' ? call(item.value) : item.value) ?? '';
            button.append(value);
        }
        button.addEventListener('click', () => { if (!disabled) onActivate(item); });
        return button;
    }
    function section(title) {
        const node = document.createElement('div');
        node.className = 'qw-menu-section';
        node.textContent = title;
        return node;
    }
    function activate(item) {
        haptic('selection');
        if (typeof item.toggle === 'function') { call(() => item.onSelect?.(item)); renderMenu(); return; }
        menu.close();
        call(() => item.onSelect?.(item));
    }
    function coreItems() {
        const items = [];
        if (config.mode === 'game') items.push({id: 'qw-home', core: true, icon: 'home', label: 'Главное меню', onSelect: goHome});
        if (fullscreen.canToggle()) {
            const active = fullscreen.active();
            items.push({id: 'qw-fullscreen', core: true, icon: active ? 'fullscreen-exit' : 'fullscreen',
                label: active ? 'Выйти из полного экрана' : 'Во весь экран', onSelect: () => fullscreen.toggle()});
        }
        return items;
    }
    function renderMenu() {
        if (!menuEl) return;
        menuEl.replaceChildren();
        const handle = document.createElement('div');
        handle.className = 'qw-menu-handle';
        menuEl.append(handle);
        const acct = document.createElement('button');
        acct.type = 'button';
        acct.className = 'qw-menu-item qw-menu-account';
        acct.dataset.qwItem = 'qw-account';
        const avatar = document.createElement('span');
        avatar.className = 'qw-avatar';
        if (account?.avatarUrl) { const img = document.createElement('img'); img.alt = ''; img.src = account.avatarUrl; avatar.append(img); }
        else if ((account?.name || '').trim()) avatar.textContent = account.name.trim().charAt(0).toUpperCase();
        else { avatar.classList.add('qw-avatar-empty'); avatar.innerHTML = svg('user'); }
        const text = document.createElement('span');
        text.className = 'qw-grow';
        text.textContent = account?.name || 'Твой профиль';
        const sub = document.createElement('small');
        sub.textContent = account?.subtitle || 'Профиль и настройки';
        text.append(sub);
        acct.append(avatar, text);
        acct.insertAdjacentHTML('beforeend', svg('chevron'));
        acct.addEventListener('click', () => { haptic('selection'); openProfile(); });
        menuEl.append(acct);
        const visible = gameItems.filter(item => !(typeof item.hidden === 'function' ? call(item.hidden) : item.hidden));
        if (visible.length) {
            menuEl.append(section(gameTitle || config.title || 'Игра'));
            for (const item of visible) menuEl.append(itemNode(item, activate));
        }
        const core = coreItems();
        if (core.length) {
            menuEl.append(section('QuizzyWizzy'));
            for (const item of core) menuEl.append(itemNode(item, activate));
        }
    }
    function onMenuKey(event) {
        if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); menu.close(); return; }
        if (event.key !== 'Tab' || !menuEl) return;
        const focusable = [...menuEl.querySelectorAll('button:not([aria-disabled="true"])')];
        if (!focusable.length) return;
        const first = focusable[0], last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
    let swipeStart = null;
    const menu = {
        /** Game items for the middle block. Replaces the previous list. */
        register(items, title) {
            gameItems = Array.isArray(items) ? items.filter(item => item && item.label) : [];
            if (title != null) gameTitle = String(title);
            if (menu.isOpen()) renderMenu();
        },
        setTitle(title) { gameTitle = String(title || ''); if (menu.isOpen()) renderMenu(); },
        setAccount(value) { account = value ? {...value} : null; if (menu.isOpen()) renderMenu(); },
        isOpen() { return Boolean(menuEl); },
        refresh() { if (menu.isOpen()) renderMenu(); },
        open(opener) {
            if (menuEl) return;
            openerEl = opener || document.activeElement;
            scrimEl = document.createElement('div');
            scrimEl.className = 'qw-menu-scrim';
            scrimEl.addEventListener('click', () => menu.close());
            menuEl = document.createElement('div');
            menuEl.className = 'qw-menu';
            menuEl.dataset.qwGroup = 'list'; // menu rows form one list (UI_RULES §9), not loose buttons
            menuEl.setAttribute('role', 'dialog');
            menuEl.setAttribute('aria-modal', 'true');
            menuEl.setAttribute('aria-label', 'Меню');
            menuEl.addEventListener('keydown', onMenuKey);
            menuEl.addEventListener('touchstart', event => { swipeStart = menuEl.scrollTop <= 0 ? event.touches[0].clientY : null; }, {passive: true});
            menuEl.addEventListener('touchend', event => {
                if (swipeStart != null && event.changedTouches[0].clientY - swipeStart > 70) menu.close();
                swipeStart = null;
            }, {passive: true});
            renderMenu();
            // A native modal <dialog> lives in the top layer: mount inside it, otherwise the menu would be inert behind it.
            const modal = [...document.querySelectorAll('dialog[open]')].pop();
            (modal || document.body).append(scrimEl, menuEl);
            requestAnimationFrame(() => { scrimEl?.classList.add('qw-open'); menuEl?.classList.add('qw-open'); });
            for (const gear of gears) gear.setAttribute('aria-expanded', 'true');
            document.addEventListener('keydown', onMenuKey, true);
            syncBack();
            if (isTelegram()) call(() => tg().BackButton.show());
            menuEl.querySelector('button')?.focus({preventScroll: true});
        },
        close() {
            if (!menuEl) return;
            document.removeEventListener('keydown', onMenuKey, true);
            scrimEl.remove(); menuEl.remove();
            scrimEl = menuEl = null;
            for (const gear of gears) gear.setAttribute('aria-expanded', 'false');
            syncBack();
            call(() => openerEl?.focus?.({preventScroll: true}));
            openerEl = null;
        },
        toggle(opener) { if (menu.isOpen()) menu.close(); else menu.open(opener); },
    };

    /* ---------------- haptics, session ---------------- */
    function haptic(kind = 'selection') {
        if (!prefs.haptics || !isTelegram()) return;
        const feedback = tg().HapticFeedback;
        if (kind === 'selection') call(() => feedback?.selectionChanged());
        else if (['success', 'error', 'warning'].includes(kind)) call(() => feedback?.notificationOccurred(kind));
        else call(() => feedback?.impactOccurred(kind));
    }
    let renewTimer = 0;
    const session = {
        /** Keeps the platform session (cookie mqb_mini) alive while the page is open. */
        keepAlive({url = '/api/mini/session/renew', every = 8 * 60 * 1000} = {}) {
            if (renewTimer) return;
            const tick = async () => {
                if (document.hidden) return;
                try {
                    const response = await fetch(url, {method: 'POST', credentials: 'same-origin', headers: {'content-type': 'application/json', 'x-mini-csrf': '1'}, body: '{}'});
                    if (response.status === 401 || response.status === 403) { clearInterval(renewTimer); renewTimer = 0; }
                } catch {}
            };
            renewTimer = setInterval(tick, every);
        },
    };

    /* ---------------- boot ---------------- */
    function boot(options = {}) {
        Object.assign(config, options);
        root.classList.toggle('qw-mode-game', config.mode === 'game');
        root.classList.toggle('qw-mode-hub', config.mode !== 'game');
        if (config.title && !gameTitle) gameTitle = config.title;
        if (booted) { applyTheme(); syncBack(); return QW; }
        booted = true;
        const t = tg();
        if (isTelegram()) {
            root.classList.add('qw-telegram', 'in-telegram');
            if (DESKTOP_PLATFORMS.has(t.platform)) root.classList.add('qw-desktop');
            call(() => t.ready()); call(() => t.expand());
            if (versionAtLeast('7.7')) call(() => t.disableVerticalSwipes());
            call(() => t.BackButton.onClick(() => nav.back()));
            if (versionAtLeast('7.0')) { call(() => t.SettingsButton.onClick(() => menu.toggle())); call(() => t.SettingsButton.show()); }
            for (const event of ['safeAreaChanged', 'contentSafeAreaChanged', 'viewportChanged', 'fullscreenChanged']) call(() => t.onEvent(event, onViewportChange));
            call(() => t.onEvent('themeChanged', applyTheme));
            call(() => t.onEvent('fullscreenFailed', () => call(() => config.onFullscreenFailed?.())));
            let lastResume = 0;
            call(() => t.onEvent('activated', () => { if (Date.now() - lastResume > 20000) { lastResume = Date.now(); call(() => config.onResume?.()); } }));
            if (config.mode === 'game' && config.fullscreen === 'auto' && MOBILE_PLATFORMS.has(t.platform) && versionAtLeast('8.0') && !t.isFullscreen) {
                call(() => t.requestFullscreen());
            }
        }
        document.addEventListener('fullscreenchange', onViewportChange);
        addEventListener('resize', () => { if (!isTelegram()) call(() => config.onResize?.()); });
        matchMedia('(prefers-color-scheme: dark)').addEventListener?.('change', applyTheme);
        writeInsets();
        applyTheme();
        syncBack();
        return QW;
    }

    const QW = {
        version: 1,
        boot,
        /** Changes options after boot, e.g. the hub switching into game mode for Night City. */
        configure(options) {
            Object.assign(config, options);
            root.classList.toggle('qw-mode-game', config.mode === 'game');
            root.classList.toggle('qw-mode-hub', config.mode !== 'game');
            syncChromeColors(); syncBack(); menu.refresh();
            return QW;
        },
        get config() { return {...config}; },
        isTelegram, isDesktop, platform, versionAtLeast,
        get tg() { return isTelegram() ? tg() : null; },
        header, menu, nav, fullscreen, session, haptic,
        goHome, openProfile, icon: svg,
        prefs: {
            get() { return {...prefs}; },
            setTheme(value) { if (['system', 'dark', 'light'].includes(value)) { prefs.theme = value; savePrefs(); applyTheme(); } },
            setHaptics(value) { prefs.haptics = Boolean(value); savePrefs(); return prefs.haptics; },
        },
        refreshChrome() { syncChromeColors(); writeInsets(); },
    };
    window.QW = QW;
})();
