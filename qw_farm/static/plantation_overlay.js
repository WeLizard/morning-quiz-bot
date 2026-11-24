const DIRECTIONS = { U: -8, L: -1, D: 8, R: 1 };
const KEYS = { ArrowUp: 'U', ArrowLeft: 'L', ArrowDown: 'D', ArrowRight: 'R',
  KeyW: 'U', KeyA: 'L', KeyS: 'D', KeyD: 'R', Space: 'C', KeyX: 'X' };

function element(tag, classes, text) {
  const node = document.createElement(tag);
  if (classes) node.className = classes;
  if (text) node.textContent = text;
  return node;
}

function control(text, classes, action) {
  const button = element('button', 'qw-btn ' + classes, text);
  button.type = 'button';
  button.addEventListener('click', action);
  return button;
}

export function openPlantationGame({ run, itemIcon, title, serverNow, currentRun, finish, onClose }) {
  const prune = run.op === 'prune';
  const targets = new Set(run.targets);
  const used = new Set();
  const path = [];
  const previousFocus = document.activeElement;
  const overlay = element('section', 'field-game plantation-game');
  overlay.dataset.theme = document.documentElement.dataset.farmTheme || 'day';
  overlay.setAttribute('role', 'dialog');
  overlay.setAttribute('aria-modal', 'true');
  overlay.setAttribute('aria-label', title);
  const frame = element('div', 'plantation-game-frame');
  const header = element('header', 'plantation-game-header qw-btn-row');
  const heading = element('h2', '', title);
  const closeButton = control('Закрыть', 'secondary', close);
  header.append(heading, closeButton);
  const instructions = element('p', 'plantation-game-hint', prune
    ? 'Срезай помеченные побеги. Чтобы получить бонус, зачти три четверти срезов за вычетом ошибок.'
    : 'Собирай помеченные кусты. Доставляй корзину к повозке в верхнем левом углу.');
  const summary = element('p', 'plantation-game-summary');
  summary.setAttribute('role', 'status');
  const stage = element('div', 'plantation-game-stage');
  const board = element('div', 'plantation-game-grid');
  board.setAttribute('aria-hidden', 'true');
  const squares = Array.from({ length: 64 }, (_, index) => {
    const cell = element('span', 'plantation-game-cell');
    cell.dataset.index = index;
    if (index === 0) {
      if (!prune) cell.append(itemIcon('fest_flw_cart'));
    } else {
      cell.append(itemIcon());
      if (targets.has(index)) cell.dataset.target = prune ? 'prune' : 'harvest';
    }
    board.append(cell);
    return cell;
  });
  board.addEventListener('click', event => {
    const index = event.target.closest('[data-index]')?.dataset.index;
    if (index === undefined) return;
    const cell = Number(index);
    if (cell === position) act('C');
    else {
      const direction = Object.keys(DIRECTIONS).find(move => neighbor(move) === cell);
      if (direction) act(direction);
    }
  });
  stage.append(board);
  const controls = element('div', 'plantation-game-controls');
  const pad = element('div', 'plantation-game-dpad');
  pad.setAttribute('aria-label', 'Движение по рядам');
  const arrows = [
    ['U', '↑', 'Вверх'], ['L', '←', 'Влево'], ['D', '↓', 'Вниз'], ['R', '→', 'Вправо']
  ].map(([move, label, name]) => {
    const button = control(label, 'secondary', () => act(move));
    button.setAttribute('aria-label', name);
    button.dataset.move = move;
    pad.append(button);
    return button;
  });
  const work = element('div', 'qw-btn-stack');
  const cut = control(prune ? 'Срезать побег' : 'Собрать с куста', 'secondary', () => act('C'));
  const unload = prune ? null : control('Выгрузить корзину', 'secondary', () => act('X'));
  const done = control(prune ? 'Завершить обрезку' : 'Сдать урожай', 'primary', submit);
  work.append(cut);
  if (unload) work.append(unload);
  work.append(done);
  controls.append(pad, work);
  frame.append(header, instructions, summary, stage, controls);
  overlay.append(frame);

  let position = 0;
  let correct = 0;
  let missed = 0;
  let basket = 0;
  let delivered = 0;
  let sending = false;
  let message = '';
  let closed = false;
  const paused = [...document.body.children].filter(node => !node.inert);
  paused.forEach(node => { node.inert = true; });
  document.body.append(overlay);
  const abort = new AbortController();
  window.addEventListener('keydown', event => {
    if (event.altKey || event.ctrlKey || event.metaKey) return;
    if (event.code === 'Escape') {
      event.preventDefault();
      close();
      return;
    }
    const move = KEYS[event.code];
    if (!move || (event.code === 'Space' && event.target instanceof HTMLButtonElement)) return;
    event.preventDefault();
    act(move);
  }, { signal: abort.signal });
  const clock = setInterval(render, 1000);
  render();
  closeButton.focus();

  function neighbor(move) {
    if ((move === 'L' && position % 8 === 0) || (move === 'R' && position % 8 === 7)) return -1;
    const next = position + DIRECTIONS[move];
    return next >= 0 && next < 64 ? next : -1;
  }

  function expired() {
    return run.expires_at <= serverNow() || currentRun()?.id !== run.id;
  }

  function act(move) {
    if (closed || sending || expired() || path.length >= run.limit) return;
    if (move === 'C') {
      if (position === 0 || used.has(position) || (!prune && basket >= run.capacity)) return;
      used.add(position);
      if (targets.has(position)) {
        correct++;
        if (!prune) basket++;
        message = prune ? 'Помеченный побег срезан.' : 'Урожай в корзине.';
      } else {
        missed++;
        message = prune ? 'Этот побег нужно было оставить.' : 'Куст ещё не созрел.';
      }
    } else if (move === 'X') {
      if (prune || position !== 0 || !basket) return;
      delivered += basket;
      basket = 0;
      message = 'Корзина выгружена.';
    } else {
      const next = neighbor(move);
      if (next < 0) return;
      position = next;
    }
    path.push(move);
    render();
  }

  function render() {
    if (closed) return;
    const old = expired();
    const locked = old || sending;
    const full = path.length >= run.limit;
    const blocked = locked || full;
    const score = Math.max(0, correct - missed);
    const need = Math.ceil(targets.size * 3 / 4);
    const progress = prune
      ? `Срезы ${score} из ${need} · Осталось действий ${run.limit - path.length}`
      : `Корзина ${basket}/${run.capacity} · Доставлено ${delivered}/${targets.size} · Ошибки ${missed}`;
    const row = `Ряд ${Math.floor(position / 8) + 1}, место ${position % 8 + 1}`;
    const shoot = used.has(position) ? 'обработано' : targets.has(position) ? (prune ? 'побег с меткой' : 'спелый куст')
      : position === 0 ? (prune ? 'начало ряда' : 'повозка') : (prune ? 'побег без метки' : 'неспелый куст');
    const status = old ? 'Заход завершился. Вернись к гектару, чтобы начать снова.'
      : [progress, `${row}: ${shoot}`, message].filter(Boolean).join(' · ');
    if (summary.textContent !== status) summary.textContent = status;
    cut.disabled = blocked || position === 0 || used.has(position) || (!prune && basket >= run.capacity);
    if (unload) unload.disabled = blocked || position !== 0 || basket === 0;
    done.disabled = locked || (prune ? score < need && !full : delivered === 0 || basket > 0);
    arrows.forEach(button => { button.disabled = blocked || neighbor(button.dataset.move) < 0; });
    squares.forEach((cell, index) => {
      cell.classList.toggle('is-current', index === position);
      cell.classList.toggle('is-used', used.has(index));
    });
  }

  async function submit() {
    if (done.disabled) return;
    sending = true;
    message = 'Сохраняем результат…';
    render();
    try {
      if (await finish(path.join(''))) close();
      else message = 'Результат не подтверждён. Проверь связь и повтори отправку.';
    } catch {
      message = 'Результат не подтверждён. Проверь связь и повтори отправку.';
    } finally {
      sending = false;
      render();
    }
  }

  function close() {
    if (closed) return true;
    closed = true;
    clearInterval(clock);
    abort.abort();
    overlay.remove();
    paused.forEach(node => { node.inert = false; });
    onClose();
    if (previousFocus?.isConnected) previousFocus.focus({ preventScroll: true });
    return true;
  }

  return { close, requestClose: close };
}
