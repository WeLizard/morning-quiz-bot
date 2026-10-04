(() => {
  'use strict';

  const app = document.querySelector('#app');
  const phone = document.querySelector('#phone');
  const toast = document.querySelector('#toast');
  const localMainButton = document.querySelector('#local-main-button');
  const description = document.querySelector('#demo-description');
  const themeMeta = document.querySelector('meta[name="theme-color"]');
  const tg = window.Telegram?.WebApp ?? null;
  const isTelegram = Boolean(tg?.initData);
  const state = { view:'home', answer:null, answerSubmitted:false, caseAction:null, toastTimer:null };

  const views = {
    home: { description:'Главный экран показывает только то, что важно сейчас: квиз дня, личный ритм и живой рейтинг чата.', mainText:null },
    quiz: { description:'Вопрос занимает первый экран, ответ выбирается одним касанием, а подтверждение живёт в нативной Telegram MainButton.', mainText:'Ответить' },
    case: { description:'Digest заменяет длинный чат: игрок сразу видит изменения, дедлайн и одно разрешённое действие.', mainText:'Подтвердить действие' }
  };

  function haptic(kind, value) {
    if (!isTelegram || !tg.HapticFeedback) return;
    try {
      if (kind === 'selection') tg.HapticFeedback.selectionChanged();
      if (kind === 'impact') tg.HapticFeedback.impactOccurred(value ?? 'light');
      if (kind === 'notification') tg.HapticFeedback.notificationOccurred(value ?? 'success');
    } catch (_) {}
  }

  function showToast(message) {
    clearTimeout(state.toastTimer);
    toast.textContent = message;
    toast.classList.add('visible');
    state.toastTimer = setTimeout(() => toast.classList.remove('visible'), 2200);
  }

  function mainActionEnabled() {
    if (state.view === 'quiz') return Boolean(state.answer);
    if (state.view === 'case') return Boolean(state.caseAction);
    return false;
  }

  function syncMainButton() {
    const config = views[state.view];
    const visible = Boolean(config.mainText);
    const enabled = mainActionEnabled();
    const text = state.view === 'quiz' && state.answerSubmitted ? 'Следующий вопрос' : config.mainText;
    phone.classList.toggle('has-local-main', visible && !isTelegram);
    localMainButton.hidden = !visible;
    localMainButton.disabled = !enabled;
    localMainButton.textContent = text ?? '';

    if (!isTelegram || !tg.MainButton) return;
    if (!visible) { tg.MainButton.hide(); return; }
    tg.MainButton.setParams({ text, is_visible:true, is_active:enabled });
    if (enabled) tg.MainButton.enable(); else tg.MainButton.disable();
  }

  function syncBackButton() {
    if (!isTelegram || !tg.BackButton) return;
    if (state.view === 'home') tg.BackButton.hide(); else tg.BackButton.show();
  }

  function updateControls() {
    document.querySelectorAll('[data-view]').forEach(button => {
      const active = button.dataset.view === state.view;
      button.classList.toggle('active', active);
      if (button.getAttribute('role') === 'tab') button.setAttribute('aria-selected', String(active));
    });
    description.textContent = views[state.view].description;
  }

  function selectAnswer(button) {
    if (state.answerSubmitted) return;
    state.answer = button.dataset.answer;
    app.querySelectorAll('[data-answer]').forEach(item => item.setAttribute('aria-checked', String(item === button)));
    haptic('selection');
    syncMainButton();
  }

  function selectCaseAction(button) {
    state.caseAction = button.dataset.caseAction;
    app.querySelectorAll('[data-case-action]').forEach(item => item.setAttribute('aria-checked', String(item === button)));
    haptic('selection');
    syncMainButton();
  }

  function submitAnswer() {
    if (!state.answer) return;
    state.answerSubmitted = true;
    const correct = app.querySelector('[data-answer="c"]');
    const selected = app.querySelector(`[data-answer="${state.answer}"]`);
    app.querySelectorAll('[data-answer]').forEach(item => { item.disabled = true; });
    correct?.classList.add('is-correct');
    if (state.answer !== 'c') selected?.classList.add('is-wrong');
    app.querySelector('#explanation')?.classList.add('visible');
    haptic('notification', state.answer === 'c' ? 'success' : 'warning');
    showToast(state.answer === 'c' ? '+10 очков · серия продолжается' : 'Ответ сохранён · правильный вариант показан');
    syncMainButton();
  }

  function handlePrimaryAction() {
    if (state.view === 'quiz') {
      if (!state.answerSubmitted) submitAnswer();
      else showToast('В рабочей версии здесь откроется вопрос 3 из 5');
    } else if (state.view === 'case' && state.caseAction) {
      haptic('notification', 'success');
      showToast(state.caseAction === 'clues' ? 'Открываем доску улик' : 'Переходим к выбору игрока');
    }
  }

  function goBack() { if (state.view !== 'home') setView('home'); }

  function bindView() {
    app.querySelectorAll('[data-go]').forEach(button => button.addEventListener('click', () => setView(button.dataset.go)));
    app.querySelectorAll('[data-back]').forEach(button => button.addEventListener('click', goBack));
    app.querySelectorAll('[data-toast]').forEach(button => button.addEventListener('click', () => { haptic('impact','light'); showToast(button.dataset.toast); }));
    app.querySelectorAll('[data-answer]').forEach(button => button.addEventListener('click', () => selectAnswer(button)));
    app.querySelectorAll('[data-case-action]').forEach(button => button.addEventListener('click', () => selectCaseAction(button)));
  }

  function setView(view) {
    if (!views[view]) return;
    state.view = view; state.answer = null; state.answerSubmitted = false; state.caseAction = null;
    document.body.dataset.view = view;
    app.replaceChildren(document.querySelector(`#${view}-template`).content.cloneNode(true));
    updateControls(); bindView(); syncBackButton(); syncMainButton();
    app.querySelector('.screen')?.scrollTo(0,0);
  }

  function applyTelegramChrome() {
    if (!isTelegram) return;
    document.documentElement.dataset.previewTheme = tg.colorScheme === 'light' ? 'light' : 'dark';
    const bg = tg.themeParams?.bg_color ?? (tg.colorScheme === 'light' ? '#ffffff' : '#101317');
    themeMeta.setAttribute('content', bg);
    try {
      tg.setHeaderColor('bg_color');
      tg.setBackgroundColor('bg_color');
      if (tg.isVersionAtLeast?.('7.10')) tg.setBottomBarColor('bottom_bar_bg_color');
    } catch (_) {}
  }

  function renderError() {
    app.innerHTML = '<div class="error-state"><div><h1>Не удалось открыть экран</h1><p>Закройте Mini App и попробуйте ещё раз. Ваши данные не изменены.</p><button type="button" class="cta-button" id="retry">Повторить</button></div></div>';
    document.querySelector('#retry')?.addEventListener('click', boot);
  }

  function boot() {
    try {
      document.body.classList.toggle('telegram-runtime', isTelegram);
      document.querySelectorAll('[data-view]').forEach(button => button.addEventListener('click', () => setView(button.dataset.view)));
      document.querySelectorAll('[data-theme]').forEach(button => button.addEventListener('click', () => {
        if (isTelegram) return;
        const theme = button.dataset.theme;
        document.documentElement.dataset.previewTheme = theme;
        document.querySelectorAll('[data-theme]').forEach(item => item.classList.toggle('active', item === button));
        themeMeta.setAttribute('content', theme === 'light' ? '#f2f4f7' : '#101317');
      }));
      localMainButton.addEventListener('click', handlePrimaryAction);
      if (isTelegram) {
        applyTelegramChrome();
        tg.onEvent('themeChanged', applyTelegramChrome);
        tg.BackButton?.onClick(goBack);
        tg.MainButton?.onClick(handlePrimaryAction);
        try { if (tg.isVersionAtLeast?.('7.7')) tg.enableVerticalSwipes(); tg.expand(); } catch (_) {}
      }
      const startParam = tg?.initDataUnsafe?.start_param;
      setView(['home','quiz','case'].includes(startParam) ? startParam : 'home');
      requestAnimationFrame(() => tg?.ready?.());
    } catch (error) {
      console.error('Mini App boot failed', error);
      renderError();
      tg?.ready?.();
    }
  }
  boot();
})();
