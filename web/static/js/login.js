document.getElementById('loginForm').addEventListener('submit', async event => {
    event.preventDefault();
    const button = event.currentTarget.querySelector('button');
    const error = document.getElementById('loginError');
    const input = document.getElementById('accessToken');
    button.disabled = true;
    error.textContent = '';
    try {
        const response = await fetch('/auth/login', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            credentials: 'same-origin', body: JSON.stringify({token: input.value}),
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || 'Не удалось войти');
        input.value = '';
        location.replace('/');
    } catch (failure) {
        error.textContent = failure.message;
    } finally { button.disabled = false; }
});
