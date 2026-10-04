(() => {
    'use strict';
    const tg = window.Telegram?.WebApp;
    const root = document.documentElement;
    const prefs = {haptics: true, theme: 'system'};
    try { const saved = JSON.parse(localStorage.getItem('mqb-ui-preferences') || '{}'); if (typeof saved.haptics === 'boolean') prefs.haptics = saved.haptics; if (['system', 'dark', 'light'].includes(saved.theme)) prefs.theme = saved.theme; } catch {}
    const call = fn => { try { return fn?.(); } catch { return undefined; } };
    function save() { try { localStorage.setItem('mqb-ui-preferences', JSON.stringify(prefs)); } catch {} }
    function theme() {
        const scheme = prefs.theme === 'system' ? (tg?.colorScheme || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')) : prefs.theme;
        root.dataset.theme = scheme;
        const bg = scheme === 'dark' ? '#101317' : '#f3f4ef';
        document.querySelector('meta[name="theme-color"]')?.setAttribute('content', bg);
        call(() => tg?.setHeaderColor?.(bg)); call(() => tg?.setBackgroundColor?.(bg)); call(() => tg?.setBottomBarColor?.(bg));
    }
    function viewport() {
        for (const [source, prefix] of [[tg?.safeAreaInset, '--tg-safe-area-inset-'], [tg?.contentSafeAreaInset, '--tg-content-safe-area-inset-']]) {
            for (const edge of ['top', 'right', 'bottom', 'left']) if (Number.isFinite(source?.[edge])) root.style.setProperty(prefix + edge, source[edge] + 'px');
        }
        if (tg?.viewportStableHeight) root.style.setProperty('--mini-viewport-height', tg.viewportStableHeight + 'px');
    }
    window.QuizTelegram = {
        configure(onBack, onSettings, onResume) {
            theme(); viewport();
            call(() => tg?.ready?.()); call(() => tg?.expand?.());
            call(() => tg?.BackButton?.onClick(onBack));
            call(() => tg?.SettingsButton?.onClick(onSettings)); call(() => tg?.SettingsButton?.show());
            for (const event of ['safeAreaChanged', 'contentSafeAreaChanged', 'viewportChanged']) call(() => tg?.onEvent?.(event, viewport));
            call(() => tg?.onEvent?.('themeChanged', theme));
            let lastResume = 0;
            call(() => tg?.onEvent?.('activated', () => { if (Date.now() - lastResume > 20000) { lastResume = Date.now(); onResume(); } }));
            matchMedia('(prefers-color-scheme: dark)').addEventListener?.('change', theme);
        },
        selection() { if (prefs.haptics) call(() => tg?.HapticFeedback?.selectionChanged()); },
        openBot(username, action) {
            if (!/^[a-zA-Z0-9_]{5,32}$/.test(username || '') || !['quiz', 'photo', 'settings', 'home'].includes(action)) return false;
            const url = 'https://t.me/' + username + (action === 'home' ? '' : '?start=' + action);
            if (tg?.initData && tg.openTelegramLink) { try { tg.openTelegramLink(url); tg.close(); } catch { return false; } }
            else window.open(url, '_blank', 'noopener,noreferrer');
            return true;
        },
        get prefs() { return {...prefs}; },
        setTheme(value) { if (['system', 'dark', 'light'].includes(value)) { prefs.theme = value; save(); theme(); } },
        toggleHaptics() { prefs.haptics = !prefs.haptics; save(); return prefs.haptics; },
        canFullscreen: Boolean(tg?.requestFullscreen && call(() => tg.isVersionAtLeast('8.0'))),
        fullscreen() { call(() => tg?.requestFullscreen?.()); },
    };
})();
