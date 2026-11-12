const form = document.getElementById('loginForm');
const error = document.getElementById('loginError');
const tokenFields = document.getElementById('tokenFields');
const passwordFields = document.getElementById('passwordFields');
let method = null;

async function loadMethod() {
    const response = await fetch('/auth/method', {cache: 'no-store'});
    if (!response.ok) throw new Error('Не удалось узнать способ входа');
    const data = await response.json();
    method = data.method;
    const byPassword = method === 'password';
    passwordFields.hidden = !byPassword;
    tokenFields.hidden = byPassword;
    document.getElementById('username').required = byPassword;
    document.getElementById('password').required = byPassword;
    document.getElementById('accessToken').required = !byPassword;
    document.getElementById('loginDescription').textContent = byPassword
        ? 'Войди с логином и паролем.'
        : 'Первичная настройка: войди с ключом, затем задай логин и пароль.';
    document.getElementById(byPassword ? 'username' : 'accessToken').focus();
}

loadMethod().catch(failure => { error.textContent = failure.message; });

form.addEventListener('submit', async event => {
    event.preventDefault();
    const button = form.querySelector('button');
    button.disabled = true;
    error.textContent = '';
    try {
        if (!method) await loadMethod();
        const body = method === 'password'
            ? {username: document.getElementById('username').value,
               password: document.getElementById('password').value}
            : {token: document.getElementById('accessToken').value};
        const response = await fetch('/auth/login', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            credentials: 'same-origin', body: JSON.stringify(body),
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || 'Не удалось войти');
        form.reset();
        const session = await fetch('/auth/session', {credentials: 'same-origin', cache: 'no-store'});
        if (!session.ok) throw new Error('Не удалось проверить вход');
        const state = await session.json();
        location.replace(state.credentials_configured ? '/' : '/auth/credentials');
    } catch (failure) {
        error.textContent = failure.message;
    } finally { button.disabled = false; }
});
