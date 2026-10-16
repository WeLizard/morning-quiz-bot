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
        bug: '<path d="M9 7.5V7a3 3 0 0 1 6 0v.5M7 9h10v5a5 5 0 0 1-10 0Zm5 0v10M3 13h4m10 0h4M4.5 7.5 7 9.5m12.5-2L17 9.5M4.5 19 7 17m12.5 2L17 17"/>',
        close: '<path d="m6 6 12 12M18 6 6 18"/>',
        plus: '<path d="M12 5v14M5 12h14"/>',
    };
    const svg = icon => {
        const body = typeof icon === 'string' && icon.trim().startsWith('<') ? icon : ICONS[icon] || '';
        return body ? '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">' + body + '</svg>' : '';
    };

    const config = {
        mode: 'hub', gameId: '', title: '', home: '/app', profileUrl: '/app#settings',
        fullscreen: 'auto', history: null, color: null, screen: '', identity: '',
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
        items.push({id: 'qw-report', core: true, icon: 'bug', label: 'Сообщить о проблеме', onSelect: () => report.open()});
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

    /* ---------------- problem report (core menu item «Сообщить о проблеме», §5) ---------------- */
    const report = (() => {
        const DEFAULTS = {text_max: 2000, images_max: 3, image_bytes_max: 1572864, image_side_max: 1600};
        const SOURCE_MAX = 15 * 1024 * 1024;
        const ID = 'qw-report';
        const draft = {text: '', images: [], requestId: null}; // images: {data: base64, canvas}; kept while the sheet is closed, cleared after a send
        let meta = null;
        let metaRequest = null;
        let ui = null;
        let sending = false;
        let processing = 0;
        let openerNode = null;

        const limits = () => ({...DEFAULTS, ...Object.fromEntries(Object.entries(meta || {}).filter(([key, value]) => key in DEFAULTS && Number(value) > 0))});
        function loadMeta() {
            if (meta) return Promise.resolve(meta);
            metaRequest ||= fetch('/api/account/problem-reports/meta', {credentials: 'same-origin', headers: {accept: 'application/json'}})
                .then(response => (response.ok ? response.json() : null))
                .then(data => { meta = data && typeof data === 'object' ? data : null; return meta; })
                .catch(() => null)
                .finally(() => { metaRequest = null; });
            return metaRequest;
        }
        function uuid() {
            if (typeof crypto?.randomUUID === 'function') return crypto.randomUUID();
            const bytes = crypto.getRandomValues(new Uint8Array(16));
            bytes[6] = (bytes[6] & 15) | 64; bytes[8] = (bytes[8] & 63) | 128;
            const hex = [...bytes].map(byte => byte.toString(16).padStart(2, '0')).join('');
            return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
        }
        function isoLocal(date = new Date()) {
            const pad = (value, length = 2) => String(value).padStart(length, '0');
            const offset = -date.getTimezoneOffset(), abs = Math.abs(offset);
            return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
                + `.${pad(date.getMilliseconds(), 3)}${offset >= 0 ? '+' : '-'}${pad(Math.floor(abs / 60))}:${pad(abs % 60)}`;
        }
        const insets = source => (source && typeof source === 'object' ? Object.fromEntries(EDGES.map(edge => [edge, Math.round(Number(source[edge]) || 0)])) : null);
        function identity() {
            const fromQuery = (() => { try { return new URLSearchParams(location.search).get('identity'); } catch { return null; } })();
            for (const value of [config.identity, fromQuery]) if (value === 'guest' || value === 'telegram') return value;
            return null; // unknown: no ?identity= at all, the server picks by the single cookie
        }
        /** Everything that is attached to a report. Query, hash, initData and cookies are never included. */
        function collectContext() {
            const t = isTelegram() ? tg() : null;
            const px = name => Math.round(parseFloat(probeLength(name)) || 0);
            return {
                screen: String(config.screen || config.gameId || 'hub').slice(0, 64),
                title: String(config.title || gameTitle || document.title || '').slice(0, 80),
                path: location.pathname,
                user_agent: navigator.userAgent.slice(0, 400),
                platform: platform(),
                telegram: Boolean(t),
                tg_version: t?.version ? String(t.version) : null,
                tg_platform: t?.platform ? String(t.platform) : null,
                fullscreen: Boolean(fullscreen.active()),
                safe_area: t ? insets(t.safeAreaInset) : null,
                content_safe_area: t ? insets(t.contentSafeAreaInset) : null,
                css_safe: {top: px('--qw-safe-top'), bottom: px('--qw-safe-bottom')},
                inset_fallback: {top: root.classList.contains('qw-inset-fallback-top'), bottom: root.classList.contains('qw-inset-fallback-bottom')},
                viewport: {width: innerWidth, height: innerHeight},
                screen_size: {width: screen.width, height: screen.height},
                dpr: devicePixelRatio,
                client_time: isoLocal(),
                language: String(navigator.language || '').slice(0, 16),
            };
        }
        function contextRows() {
            const c = collectContext();
            const pair = (name, value) => `${name} ↑${value?.top ?? 0} ↓${value?.bottom ?? 0}`;
            return [
                ['Экран', `${c.title || '—'} (${c.screen})`],
                ['Страница', c.path],
                ['Версия', meta?.build || 'неизвестна'],
                ['Платформа', c.platform + (c.telegram ? ` · Telegram ${c.tg_version || ''}`.trimEnd() : '') + (c.fullscreen ? ' · во весь экран' : '')],
                ['Окно', `${c.viewport.width}×${c.viewport.height} · экран ${c.screen_size.width}×${c.screen_size.height} · dpr ${c.dpr}`],
                ['Отступы', [c.safe_area && pair('Telegram', c.safe_area), c.content_safe_area && pair('контент', c.content_safe_area), pair('css', c.css_safe)]
                    .filter(Boolean).join(' · ') + (c.inset_fallback.top || c.inset_fallback.bottom ? ' (запасные)' : '')],
                ['Устройство', c.user_agent],
                ['Время и язык', `${c.client_time} · ${c.language}`],
                ['Аккаунт', account?.name ? `${account.name} (способ входа определит сервер)` : 'аккаунт и способ входа определит сервер'],
            ];
        }

        /* ----- screenshots: decode → canvas ≤ side → JPEG → base64. Previews are canvases: the page CSP has no blob:/data: for <img>. ----- */
        async function toBitmap(file) {
            try { return await createImageBitmap(file, {imageOrientation: 'from-image'}); } catch { return await createImageBitmap(file); }
        }
        const canvasBlob = (canvas, quality) => new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg', quality));
        const blobBase64 = blob => new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => resolve(String(reader.result).split(',')[1] || '');
            reader.onerror = () => reject(reader.error);
            reader.readAsDataURL(blob);
        });
        async function compress(file) {
            if (!String(file.type).startsWith('image/')) throw new Error('Это не картинка. Выбери скриншот или фото.');
            if (file.size > SOURCE_MAX) throw new Error('Файл больше 15 МБ. Выбери картинку поменьше.');
            let bitmap;
            try { bitmap = await toBitmap(file); } catch { throw new Error('Не удалось открыть картинку. Подойдёт обычный скриншот в PNG или JPEG.'); }
            try {
                const {image_side_max: side, image_bytes_max: maxBytes} = limits();
                const base = Math.min(1, side / Math.max(bitmap.width, bitmap.height));
                // 0.82 first, 0.6 when still too heavy, then smaller canvases as a last resort.
                for (const [factor, quality] of [[1, 0.82], [1, 0.6], [0.75, 0.6], [0.5, 0.6]]) {
                    const canvas = document.createElement('canvas');
                    canvas.width = Math.max(1, Math.round(bitmap.width * base * factor));
                    canvas.height = Math.max(1, Math.round(bitmap.height * base * factor));
                    const context = canvas.getContext('2d');
                    context.fillStyle = '#fff'; // JPEG has no alpha
                    context.fillRect(0, 0, canvas.width, canvas.height);
                    context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
                    const blob = await canvasBlob(canvas, quality);
                    if (blob && blob.size <= maxBytes) return {data: await blobBase64(blob), canvas};
                }
                throw new Error('Картинка слишком тяжёлая даже после сжатия. Выбери другую.');
            } finally { call(() => bitmap.close()); }
        }
        function drawThumb(target, source) {
            const size = 224; // 112 css px at 2x
            target.width = size; target.height = size;
            const crop = Math.min(source.width, source.height);
            target.getContext('2d').drawImage(source, (source.width - crop) / 2, (source.height - crop) / 2, crop, crop, 0, 0, size, size);
        }

        /* ----- sheet ----- */
        function el(tag, className, text) {
            const node = document.createElement(tag);
            if (className) node.className = className;
            if (text != null) node.textContent = text;
            return node;
        }
        function setStatus(message, isError = false) {
            if (!ui) return;
            ui.status.textContent = message || '';
            ui.status.classList.toggle('qw-error', Boolean(message) && isError);
            ui.status.hidden = !message;
        }
        function update() {
            if (!ui) return;
            const max = limits();
            const length = ui.text.value.length;
            ui.counter.textContent = `${length}/${max.text_max}`;
            ui.counter.classList.toggle('qw-error', length >= max.text_max);
            ui.text.maxLength = max.text_max;
            ui.text.readOnly = sending;
            ui.add.disabled = sending || processing > 0 || draft.images.length >= max.images_max;
            ui.send.disabled = sending || processing > 0;
            ui.send.textContent = sending ? 'Отправляю…' : processing > 0 ? 'Готовлю картинку…' : 'Отправить';
            ui.hint.textContent = `Картинок: ${draft.images.length} из ${max.images_max}`;
            ui.close.disabled = sending;
        }
        function renderThumbs() {
            if (!ui) return;
            ui.thumbs.replaceChildren();
            draft.images.forEach((image, index) => {
                const cell = el('div', 'qw-report-thumb');
                const canvas = document.createElement('canvas');
                canvas.setAttribute('role', 'img');
                canvas.setAttribute('aria-label', `Скриншот ${index + 1}`);
                drawThumb(canvas, image.canvas);
                const remove = el('button', 'qw-report-remove');
                remove.type = 'button';
                remove.setAttribute('aria-label', `Убрать скриншот ${index + 1}`);
                remove.innerHTML = svg('close');
                remove.disabled = sending;
                remove.addEventListener('click', () => {
                    if (sending) return;
                    draft.images.splice(index, 1);
                    draft.requestId = null;
                    renderThumbs(); update();
                    ui.add.focus({preventScroll: true});
                });
                cell.append(canvas, remove);
                ui.thumbs.append(cell);
            });
            ui.thumbs.hidden = !draft.images.length;
        }
        function renderDetails() {
            if (!ui) return;
            ui.details.replaceChildren();
            for (const [name, value] of contextRows()) {
                const row = el('div', 'qw-report-row');
                row.append(el('dt', null, name), el('dd', null, value));
                ui.details.append(row);
            }
        }
        async function addFiles(files) {
            const max = limits();
            const room = max.images_max - draft.images.length;
            if (!files.length) return;
            setStatus(files.length > room ? `Можно приложить не больше ${max.images_max} картинок.` : '', files.length > room);
            processing += 1; update();
            for (const file of files.slice(0, Math.max(0, room))) {
                try {
                    draft.images.push(await compress(file));
                    draft.requestId = null;
                    renderThumbs();
                } catch (error) { setStatus(error.message || 'Не удалось добавить картинку.', true); }
            }
            processing -= 1; update();
        }
        function trapKeys(event) {
            if (!ui) return;
            if (event.key === 'Escape') {
                if (menu.isOpen()) return;
                event.preventDefault(); event.stopPropagation();
                if (!sending) close();
                return;
            }
            if (event.key !== 'Tab') return;
            const focusable = [...ui.sheet.querySelectorAll('button:not(:disabled), textarea, summary')].filter(node => node.offsetParent !== null);
            if (!focusable.length) return;
            const first = focusable[0], last = focusable[focusable.length - 1];
            if (!ui.sheet.contains(document.activeElement)) { event.preventDefault(); first.focus(); }
            else if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
            else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
        }
        function teardown() {
            if (!ui) return;
            draft.text = ui.text.value;
            document.removeEventListener('keydown', trapKeys, true);
            ui.scrim.remove(); ui.sheet.remove();
            ui = null;
            call(() => openerNode?.focus?.({preventScroll: true}));
            openerNode = null;
        }
        function close() {
            if (!ui) return;
            teardown();
            nav.pop(ID);
        }
        function showDone(number) {
            draft.text = ''; draft.images = []; draft.requestId = null;
            ui.form.hidden = true;
            ui.footer.hidden = true;
            ui.status.hidden = true;
            ui.done.hidden = false;
            ui.doneText.textContent = number != null ? `Спасибо! Отчёт №${number} отправлен` : 'Спасибо! Отчёт отправлен';
            ui.close.disabled = false;
            ui.doneClose.focus({preventScroll: true});
        }
        async function submit() {
            if (!ui || sending || processing > 0) return;
            const text = ui.text.value.trim();
            if (!text) { setStatus('Опиши, что случилось: без текста отчёт не отправить.', true); ui.text.focus(); return; }
            setStatus('');
            sending = true; update(); renderThumbs();
            draft.requestId ||= uuid();
            const controller = new AbortController();
            const timer = setTimeout(() => controller.abort(), 60000);
            let message = '', ok = false, number = null;
            try {
                const response = await fetch('/api/account/problem-reports' + (identity() ? '?identity=' + encodeURIComponent(identity()) : ''), {
                    method: 'POST', credentials: 'same-origin', signal: controller.signal,
                    headers: {'content-type': 'application/json', 'x-guest-csrf': '1'},
                    body: JSON.stringify({request_id: draft.requestId, text, context: collectContext(), images: draft.images.map(image => image.data)}),
                });
                let data = null;
                try { data = await response.json(); } catch {}
                if (response.status === 201 || response.status === 200) { ok = true; number = data?.number ?? data?.report_id ?? null; }
                else if (response.status === 429) message = 'Слишком много отчётов, попробуй позже.';
                else message = (typeof data?.detail === 'string' && data.detail) || `Не получилось отправить (код ${response.status}). Попробуй ещё раз.`;
            } catch {
                // The next tap reuses request_id: the server answers 200 instead of creating a duplicate.
                message = 'Нет связи с сервером. Нажми «Отправить» ещё раз: отчёт не продублируется.';
            } finally { clearTimeout(timer); sending = false; }
            if (ok) { haptic('success'); if (ui) showDone(number); else { draft.text = ''; draft.images = []; draft.requestId = null; } return; }
            haptic('error');
            if (ui) { setStatus(message, true); renderThumbs(); update(); }
        }
        function build() {
            const scrim = el('div', 'qw-menu-scrim qw-report-scrim');
            scrim.addEventListener('click', () => { if (!sending) close(); });
            const sheet = el('div', 'qw-report');
            sheet.setAttribute('role', 'dialog');
            sheet.setAttribute('aria-modal', 'true');
            sheet.setAttribute('aria-labelledby', 'qw-report-title');
            sheet.tabIndex = -1;

            const head = el('div', 'qw-report-head');
            const title = el('h2', null, 'Сообщить о проблеме');
            title.id = 'qw-report-title';
            const closeButton = iconButton('qw-report-close', 'close', 'Закрыть');
            closeButton.addEventListener('click', () => close());
            head.append(title, closeButton);

            const body = el('div', 'qw-report-body');
            const form = el('div', 'qw-report-form');
            const intro = el('p', 'qw-report-intro', 'Опиши, что пошло не так. Вместе с текстом уйдут данные об экране и версии — их видно ниже.');
            const label = el('label', 'qw-report-label', 'Что случилось');
            label.htmlFor = 'qw-report-text';
            const text = el('textarea', 'qw-report-text');
            text.id = 'qw-report-text';
            text.rows = 5;
            text.value = draft.text;
            text.placeholder = 'Например: нажимаю «Собрать», а ничего не происходит';
            const counter = el('div', 'qw-report-counter');
            text.addEventListener('input', () => { if (sending) return; draft.requestId = null; setStatus(''); update(); });

            const shots = el('div', 'qw-report-shots');
            const file = document.createElement('input');
            file.type = 'file'; file.accept = 'image/*'; file.multiple = true; file.hidden = true; file.tabIndex = -1;
            file.addEventListener('change', () => { const picked = [...file.files]; file.value = ''; addFiles(picked); });
            const add = el('button', 'qw-btn secondary', 'Добавить скриншот');
            add.type = 'button';
            add.insertAdjacentHTML('afterbegin', svg('plus'));
            add.addEventListener('click', () => file.click());
            const hint = el('div', 'qw-report-hint');
            const thumbs = el('div', 'qw-report-thumbs');
            shots.append(add, hint, thumbs, file);

            const attach = el('details', 'qw-report-attach');
            attach.append(el('summary', null, 'Что приложится'));
            const list = el('dl', 'qw-report-list');
            attach.append(list);
            attach.addEventListener('toggle', () => { if (attach.open) renderDetails(); });
            form.append(intro, label, text, counter, shots, attach);

            const status = el('div', 'qw-report-status');
            status.setAttribute('role', 'status');
            status.hidden = true;

            const done = el('div', 'qw-report-done');
            done.hidden = true;
            const doneText = el('p', 'qw-report-thanks');
            const doneClose = el('button', 'qw-btn primary', 'Закрыть');
            doneClose.type = 'button';
            doneClose.addEventListener('click', () => close());
            const doneStack = el('div', 'qw-btn-stack');
            doneStack.append(doneClose);
            done.append(doneText, doneStack);
            body.append(form, status, done);

            const footer = el('div', 'qw-report-foot qw-btn-stack');
            const send = el('button', 'qw-btn primary', 'Отправить');
            send.type = 'button';
            send.addEventListener('click', submit);
            footer.append(send);

            sheet.append(head, body, footer);
            ui = {scrim, sheet, text, counter, add, hint, thumbs, details: list, status, send, close: closeButton, form, footer, done, doneText, doneClose};
        }
        function open() {
            if (ui) { ui.text.focus({preventScroll: true}); return; }
            openerNode = document.activeElement;
            build();
            const modal = [...document.querySelectorAll('dialog[open]')].pop(); // top layer: mount inside an open modal <dialog>
            (modal || document.body).append(ui.scrim, ui.sheet);
            document.addEventListener('keydown', trapKeys, true);
            nav.push({id: ID, onBack: () => { if (sending) return false; teardown(); return true; }});
            renderThumbs(); renderDetails(); update();
            requestAnimationFrame(() => { ui?.scrim.classList.add('qw-open'); ui?.sheet.classList.add('qw-open'); });
            if (isDesktop()) ui.text.focus({preventScroll: true}); else ui.sheet.focus({preventScroll: true});
            loadMeta().then(() => { if (ui) { update(); renderDetails(); } });
        }
        return {open, close, isOpen: () => Boolean(ui)};
    })();

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
        header, menu, nav, fullscreen, session, haptic, report,
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
