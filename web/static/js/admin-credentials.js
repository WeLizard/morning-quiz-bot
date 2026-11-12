const form = document.getElementById('credentialsForm');
const error = document.getElementById('setupError');

form.addEventListener('submit', async event => {
    event.preventDefault();
    const button = form.querySelector('button');
    const username = document.getElementById('username').value.trim();
    const password = document.getElementById('password').value;
    const confirmation = document.getElementById('confirmation').value;
    error.textContent = '';
    if (password !== confirmation) {
        error.textContent = 'Пароли не совпадают.';
        return;
    }
    button.disabled = true;
    try {
        const sessionResponse = await fetch('/auth/session', {credentials: 'same-origin', cache: 'no-store'});
        if (!sessionResponse.ok) throw new Error('Сессия истекла. Войди снова.');
        const session = await sessionResponse.json();
        const response = await fetch('/auth/credentials', {
            method: 'POST', credentials: 'same-origin',
            headers: {'Content-Type': 'application/json', 'X-CSRF-Token': session.csrf_token},
            body: JSON.stringify({username, password}),
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || 'Не удалось сохранить вход');
        form.reset();
        location.replace('/');
    } catch (failure) {
        error.textContent = failure.message;
    } finally { button.disabled = false; }
});
