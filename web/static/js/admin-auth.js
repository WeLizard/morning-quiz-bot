// The session ID stays in an HttpOnly cookie. CSRF is held only in memory.
(() => {
    const originalFetch = window.fetch.bind(window);
    const ready = originalFetch('/auth/session', {credentials: 'same-origin', cache: 'no-store'})
        .then(async response => {
            if (!response.ok) { location.replace('/login'); throw new Error('Требуется вход'); }
            const data = await response.json();
            window.adminBackend = data.storage_backend;
            return data;
        });
    window.adminReady = ready;
    window.fetch = async (input, init = {}) => {
        const url = new URL(input instanceof Request ? input.url : input, location.href);
        if (url.origin !== location.origin || !url.pathname.startsWith('/api/')) return originalFetch(input, init);
        const session = await ready;
        const headers = new Headers(init.headers || (input instanceof Request ? input.headers : undefined));
        const method = (init.method || (input instanceof Request ? input.method : 'GET')).toUpperCase();
        if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) headers.set('X-CSRF-Token', session.csrf_token);
        const response = await originalFetch(input, {...init, headers, credentials: 'same-origin'});
        if (response.status === 401) location.replace('/login');
        return response;
    };
    window.adminLogout = async () => {
        const session = await ready;
        const response = await originalFetch('/auth/logout', {method: 'POST', credentials: 'same-origin',
            headers: {'X-CSRF-Token': session.csrf_token}});
        if (response.ok || response.status === 401) location.replace('/login');
        else alert('Не удалось выйти. Попробуйте ещё раз.');
    };
    document.addEventListener('DOMContentLoaded', () => {
        document.getElementById('adminLogoutButton')?.addEventListener('click', window.adminLogout);
    });
})();
