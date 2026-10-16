// Thin adapter over the shared shell (window.QW, /app/shell/qw-shell.js).
// The bridge, safe-area, theme, haptics and fullscreen live in the core; this file only keeps the
// window.QuizTelegram API that app.js and play-ui.js call. Rules: docs/design/UI_RULES.md §7.
(() => {
    'use strict';
    const QW = window.QW;
    // The SDK may arrive after this file runs (the shell loads it asynchronously for Telegram launches only).
    const webApp = () => window.Telegram?.WebApp;
    const FALLBACK_PREFS = {haptics: true, theme: 'system'};
    window.QuizTelegram = {
        // onBack is kept for the old call signature: BackButton is wired by QW.nav (app.js sets the root handler).
        // onSettings opens «Профиль → Настройки» from the ⚙ menu and from Telegram SettingsButton.
        configure(onBack, onSettings, onResume) {
            QW?.boot({mode: 'hub', onResume, onProfile: onSettings});
        },
        selection() { QW?.haptic('selection'); },
        openBot(username, action) {
            if (!/^[a-zA-Z0-9_]{5,32}$/.test(username || '') || !['quiz', 'photo', 'settings', 'home'].includes(action)) return false;
            const url = 'https://t.me/' + username + (action === 'home' ? '' : '?start=' + action);
            const tg = webApp();
            if (tg?.initData && tg.openTelegramLink) { try { tg.openTelegramLink(url); tg.close(); } catch { return false; } }
            else window.open(url, '_blank', 'noopener,noreferrer');
            return true;
        },
        get prefs() { return QW ? QW.prefs.get() : {...FALLBACK_PREFS}; },
        setTheme(value) { QW?.prefs.setTheme(value); },
        toggleHaptics() { return QW ? QW.prefs.setHaptics(!QW.prefs.get().haptics) : false; },
        get canFullscreen() { return Boolean(QW?.fullscreen.canToggle()); },
        fullscreen() { QW?.fullscreen.toggle(); },
    };
})();
