"""Browser checks for docs/design/UI_RULES.md (Playwright).

    python tests/ui/ui_check.py nav                 # core shell: navigation, BackButton, menu, safe-area (no server)
    python tests/ui/ui_check.py errors              # automatic error reports: capture, limits, sanitising, breadcrumbs, toast (no server)
    python tests/ui/ui_check.py gaps-selftest       # the button-gap scanner catches glued buttons (no server)
    python tests/ui/ui_check.py gaps --base URL     # real screens of a running app: glued buttons, tap height
    python tests/ui/ui_check.py dasha --base URL    # real guest game view at 320/390/desktop, with screenshots

Prints "SKIP: ..." and exits 0 when no browser is available (Playwright Chromium, Edge or Chrome).
Wrapped by tests/js/ui_layout.test.cjs so it runs with the common `node --test tests/js/*.test.cjs` set.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HARNESS = (ROOT / 'tests' / 'ui' / 'shell_harness.html').as_uri()
MIN_GAP = 8
MIN_TAP = 44

# Scans visible buttons: neighbours closer than MIN_GAP (outside an explicit group) and controls below MIN_TAP.
SCANNER = r"""
([minGap, minTap]) => {
  const grouped = '.qw-btn-group,[data-qw-group],[role="tablist"],[role="radiogroup"],nav,canvas,svg,[data-qw-ui-ignore]';
  const visible = el => {
    const r = el.getBoundingClientRect(), cs = getComputedStyle(el);
    if (r.width < 1 || r.height < 1 || cs.visibility === 'hidden' || cs.display === 'none' || +cs.opacity === 0) return false;
    if (el.closest('[hidden],[aria-hidden="true"],dialog:not([open])')) return false;
    const cx = Math.min(Math.max(r.left + r.width / 2, 0), innerWidth - 1), cy = Math.min(Math.max(r.top + r.height / 2, 0), innerHeight - 1);
    if (r.bottom < 0 || r.top > innerHeight || r.right < 0 || r.left > innerWidth) return false;
    const top = document.elementFromPoint(cx, cy);
    return !top || el.contains(top) || top.contains(el);
  };
  const name = el => ((el.innerText || el.getAttribute('aria-label') || el.title || el.className || el.tagName) + '').trim().replace(/\s+/g, ' ').slice(0, 48);
  const all = [...document.querySelectorAll('button, a.btn, a.qw-btn, [role="button"], input[type="submit"]')].filter(visible);
  const free = all.filter(el => !el.parentElement?.closest(grouped));
  const issues = [];
  for (let i = 0; i < free.length; i++) {
    for (let j = i + 1; j < free.length; j++) {
      const a = free[i], b = free[j];
      if (a.contains(b) || b.contains(a)) continue;
      const ar = a.getBoundingClientRect(), br = b.getBoundingClientRect();
      const hOverlap = Math.min(ar.right, br.right) - Math.max(ar.left, br.left);
      const vOverlap = Math.min(ar.bottom, br.bottom) - Math.max(ar.top, br.top);
      if (hOverlap > 8) {
        const gap = Math.max(br.top - ar.bottom, ar.top - br.bottom);
        if (gap > -2 && gap < minGap - 0.5) issues.push({kind: 'gap', gap: Math.round(gap * 10) / 10, a: name(a), b: name(b)});
      } else if (vOverlap > 8) {
        const gap = Math.max(br.left - ar.right, ar.left - br.right);
        if (gap > -2 && gap < minGap - 0.5) issues.push({kind: 'gap', gap: Math.round(gap * 10) / 10, a: name(a), b: name(b)});
      }
    }
  }
  for (const el of all) {
    if (el.closest('canvas,svg,[data-qw-ui-ignore]')) continue;
    const r = el.getBoundingClientRect();
    if (r.height < minTap - 0.5) issues.push({kind: 'height', height: Math.round(r.height), a: name(el)});
  }
  return {buttons: all.length, issues};
}
"""


# With emulated Telegram insets (top 47px, bottom 48px) no tappable control may sit inside those zones.
ZONE_SCANNER = r"""
([top, bottom]) => {
  const root = document.documentElement;
  root.style.setProperty('--qw-tg-safe-top', top + 'px');
  root.style.setProperty('--qw-tg-safe-bottom', bottom + 'px');
  dispatchEvent(new Event('resize'));
  return new Promise(resolve => setTimeout(() => {
    const issues = [];
    const pageScrolls = document.scrollingElement.scrollHeight > innerHeight + 2;
    const pinned = el => {
      for (let node = el.parentElement; node && node !== document.documentElement; node = node.parentElement) {
        const cs = getComputedStyle(node);
        if (cs.position === 'fixed' || cs.position === 'sticky') return true;
        if (/(auto|scroll)/.test(cs.overflowY) && node.scrollHeight > node.clientHeight + 2) return false;
      }
      return !pageScrolls;
    };
    for (const el of document.querySelectorAll('button, a.btn, a.qw-btn, [role="button"], [role="tab"]')) {
      if (el.closest('canvas,svg,[data-qw-ui-ignore],[hidden],dialog:not([open])')) continue;
      const r = el.getBoundingClientRect(), cs = getComputedStyle(el);
      if (r.width < 1 || r.height < 1 || cs.visibility === 'hidden' || cs.display === 'none') continue;
      if (r.bottom <= 0 || r.top >= innerHeight || !pinned(el)) continue;
      const name = ((el.innerText || el.getAttribute('aria-label') || el.className || el.tagName) + '').trim().replace(/\s+/g, ' ').slice(0, 40);
      // A pinned control must not sit under the status bar or under the system navigation.
      if (r.top < top - 0.5) issues.push({kind: 'safe-top', a: name, y: Math.round(r.top)});
      if (r.bottom > innerHeight - bottom + 0.5) issues.push({kind: 'safe-bottom', a: name, y: Math.round(r.bottom)});
    }
    root.style.removeProperty('--qw-tg-safe-top');
    root.style.removeProperty('--qw-tg-safe-bottom');
    resolve(issues);
  }, 400));
}
"""


def browser(playwright):
    errors = []
    for options in ({}, {'channel': 'msedge'}, {'channel': 'chrome'}):
        try:
            return playwright.chromium.launch(**options)
        except Exception as error:  # noqa: BLE001 - try the next installed browser
            errors.append(str(error).splitlines()[0])
    return None


class Checks:
    def __init__(self):
        self.failures = []
        self.passed = 0

    def ok(self, condition, message):
        if condition:
            self.passed += 1
        else:
            self.failures.append(message)


def harness(page, query='', hash_=''):
    page.goto(HARNESS + query + hash_)
    if hash_:
        page.reload()  # a hash-only change does not reload the document; launch params are read at load time
    page.wait_for_function('window.QW')


def run_nav(pw_browser):
    c = Checks()
    page = pw_browser.new_page(viewport={'width': 390, 'height': 800})

    # --- outside Telegram: hub mode ---
    harness(page, '?tg=none')
    page.evaluate("""() => { QW.boot({mode:'hub'}); window.back = QW.header.mountBack(document.getElementById('head'));
        window.gear = QW.header.mountGear(document.getElementById('head')); }""")
    c.ok(page.evaluate('back.hidden') is True, 'browser hub: ‹ is hidden on a root page')
    c.ok(page.evaluate('document.getElementById("head").lastElementChild === gear'), '⚙ is the last element of the header')
    page.evaluate("QW.nav.setRoot(() => { window.wentRoot = true; })")
    c.ok(page.evaluate('back.hidden') is False, 'browser hub: ‹ shows on a nested page (root handler)')
    page.evaluate('back.click()')
    page.wait_for_timeout(50)
    c.ok(page.evaluate('window.wentRoot === true'), 'browser hub: ‹ runs the parent handler')
    page.evaluate("QW.nav.setRoot(() => {}, {onScreen: false})")
    c.ok(page.evaluate('back.hidden') is True, 'browser hub: tab roots keep ‹ hidden (onScreen:false)')
    page.evaluate('QW.nav.setRoot(null)')
    c.ok(page.evaluate("document.documentElement.classList.contains('qw-telegram')") is False, 'browser: no qw-telegram class')
    # menu in hub mode: account + game block, no «Главное меню»
    page.evaluate("""() => QW.menu.register([{id:'quiz-settings', label:'Настройки квиза', icon:'sliders', onSelect(){ window.quizSettings = true; }},
        {id:'sound', label:'Звук', toggle:() => !!window.sound, onSelect(){ window.sound = !window.sound; }}], 'Классический квиз')""")
    page.evaluate('gear.click()')
    labels = page.evaluate("[...document.querySelectorAll('.qw-menu .qw-menu-item')].map(n => n.dataset.qwItem)")
    c.ok(labels[:3] == ['qw-account', 'quiz-settings', 'sound'], f'menu order account → game items, got {labels}')
    c.ok('qw-home' not in labels, 'hub menu has no «Главное меню»')
    c.ok(page.evaluate("gear.getAttribute('aria-expanded')") == 'true', '⚙ aria-expanded=true while open')
    page.evaluate("document.querySelector('[data-qw-item=sound]').click()")
    c.ok(page.evaluate('QW.menu.isOpen() && window.sound === true'), 'toggle item keeps the menu open and flips')
    page.keyboard.press('Escape')
    c.ok(page.evaluate('QW.menu.isOpen()') is False, 'Escape closes the menu')
    page.evaluate('gear.click()')
    page.evaluate("document.querySelector('[data-qw-item=quiz-settings]').click()")
    c.ok(page.evaluate('!QW.menu.isOpen() && window.quizSettings === true'), 'action item closes the menu and runs')

    # problem report: core item, sheet in the nav stack, Esc and ‹ close it
    page.evaluate('gear.click()')
    c.ok('qw-report' in page.evaluate("[...document.querySelectorAll('.qw-menu .qw-menu-item')].map(n => n.dataset.qwItem)"), 'hub menu has «Сообщить о проблеме»')
    page.evaluate("document.querySelector('[data-qw-item=qw-report]').click()")
    c.ok(page.evaluate("!QW.menu.isOpen() && QW.report.isOpen() && QW.nav.depth === 1 && !!document.querySelector('.qw-report[role=dialog]')"), 'report item opens the sheet and pushes the nav stack')
    page.evaluate("document.querySelector('.qw-report-text').value = 'x'.repeat(5); document.querySelector('.qw-report-text').dispatchEvent(new Event('input'))")
    c.ok(page.evaluate("document.querySelector('.qw-report-counter').textContent") == '5/2000', 'report counter shows x/2000')
    page.keyboard.press('Escape')
    c.ok(page.evaluate('!QW.report.isOpen() && QW.nav.depth === 0'), 'Escape closes the report sheet and pops the stack')
    page.evaluate('QW.report.open()')
    c.ok(page.evaluate("document.querySelector('.qw-report-text').value") == 'xxxxx', 'report draft survives closing')
    page.evaluate('QW.nav.back()')
    page.wait_for_timeout(50)
    c.ok(page.evaluate('!QW.report.isOpen() && QW.nav.depth === 0'), 'nav back closes the report sheet, not the page')

    # --- outside Telegram: game mode with guarded stack and history ---
    harness(page, '?tg=none')
    page.evaluate("""() => { QW.boot({mode:'game', onHome(){ window.home = (window.home||0) + 1; }});
        window.back = QW.header.mountBack(document.getElementById('head')); window.gear = QW.header.mountGear(document.getElementById('head')); }""")
    c.ok(page.evaluate('back.hidden') is True, 'browser game root: no ‹ (exit via ⚙)')
    page.evaluate('gear.click()')
    c.ok('qw-home' in page.evaluate("[...document.querySelectorAll('.qw-menu .qw-menu-item')].map(n => n.dataset.qwItem)"), 'game menu has «Главное меню»')
    page.evaluate("document.querySelector('[data-qw-item=qw-home]').click()")
    c.ok(page.evaluate('window.home') == 1, '«Главное меню» calls onHome')
    page.evaluate("""() => { window.allow = false; QW.nav.push({id:'tractor', onBack: () => window.allow}); }""")
    c.ok(page.evaluate('back.hidden') is False and page.evaluate('QW.nav.depth') == 1, 'push shows ‹ and grows the stack')
    page.evaluate('QW.nav.back()')
    page.wait_for_timeout(50)
    c.ok(page.evaluate('QW.nav.depth') == 1, 'guard returning false keeps the screen (NAV-6)')
    page.go_back()
    page.wait_for_timeout(150)
    c.ok(page.evaluate('QW.nav.depth') == 1, 'browser Back is guarded too')
    page.evaluate('window.allow = true')
    page.go_back()
    page.wait_for_timeout(150)
    c.ok(page.evaluate('QW.nav.depth') == 0, 'browser Back pops when the guard allows')
    page.evaluate("QW.nav.push({id:'panel', onBack(){ window.closed = true; }})")
    page.evaluate("QW.nav.pop('panel')")
    page.wait_for_timeout(150)
    c.ok(page.evaluate('QW.nav.depth') == 0 and page.evaluate('history.state?.qwNav') != 'panel', 'pop(id) rewinds its history entry')

    # --- Telegram iOS: game mode ---
    harness(page, '?tg=ios&v=8.0')
    page.evaluate("""() => { QW.boot({mode:'game', onHome(){ window.home = (window.home||0) + 1; }});
        window.back = QW.header.mountBack(document.getElementById('head')); QW.header.mountGear(document.getElementById('head')); }""")
    calls = [call[0] for call in page.evaluate('__calls')]
    for expected in ('ready', 'expand', 'disableVerticalSwipes', 'requestFullscreen', 'setHeaderColor'):
        c.ok(expected in calls, f'telegram ios game: {expected}() called')
    c.ok(page.evaluate('Telegram.WebApp.BackButton.isVisible') is True, 'telegram game root: BackButton visible (decision A)')
    c.ok(page.evaluate('back.hidden') is True, 'telegram: on-screen ‹ never shown')
    c.ok(page.evaluate('Telegram.WebApp.SettingsButton.isVisible') is True, 'telegram: SettingsButton shown')
    top = page.evaluate("getComputedStyle(document.getElementById('head')).paddingTop")
    c.ok(top == '93px', f'fullscreen safe-top = device 47 + Telegram content 46, got {top}')
    c.ok(page.evaluate("document.documentElement.classList.contains('qw-desktop')") is False, 'ios is not desktop')
    page.evaluate('__tg.pressSettings()')
    c.ok(page.evaluate('QW.menu.isOpen()'), 'SettingsButton opens the ⚙ menu')
    page.evaluate('__tg.pressBack()')
    page.wait_for_timeout(50)
    c.ok(page.evaluate('QW.menu.isOpen()') is False and page.evaluate('window.home') is None, 'BackButton closes the menu first')
    page.evaluate("QW.nav.push({id:'modal', onBack(){ window.modalClosed = true; }})")
    page.evaluate('__tg.pressBack()')
    page.wait_for_timeout(50)
    c.ok(page.evaluate('window.modalClosed === true && QW.nav.depth === 0'), 'BackButton walks back through game screens')
    page.evaluate('__tg.pressBack()')
    page.wait_for_timeout(50)
    c.ok(page.evaluate('window.home') == 1, 'BackButton on the game root goes to the main menu')
    page.evaluate("__tg.emit('safeAreaChanged', {safeAreaInset:{top:59,right:0,bottom:34,left:0}})")
    top = page.evaluate("getComputedStyle(document.getElementById('head')).paddingTop")
    c.ok(top == '105px', f'safeAreaChanged updates --qw-safe-top live, got {top}')

    # --- Telegram iOS: hub mode keeps the page inline (no auto fullscreen), root hides BackButton ---
    harness(page, '?tg=ios&v=8.0')
    page.evaluate("QW.boot({mode:'hub'})")
    calls = [call[0] for call in page.evaluate('__calls')]
    c.ok('requestFullscreen' not in calls, 'hub does not force fullscreen')
    c.ok(page.evaluate('Telegram.WebApp.BackButton.isVisible') is False, 'hub root: BackButton hidden')
    page.evaluate("QW.nav.setRoot(() => { window.parent_ = true; })")
    c.ok(page.evaluate('Telegram.WebApp.BackButton.isVisible') is True, 'hub nested page: BackButton visible')
    page.evaluate('__tg.pressBack()')
    page.wait_for_timeout(50)
    c.ok(page.evaluate('window.parent_ === true'), 'hub BackButton goes to the parent page')

    # --- Telegram Desktop: desktop type scale, no forced fullscreen ---
    harness(page, '?tg=tdesktop&v=8.0')
    page.evaluate("QW.boot({mode:'game'})")
    calls = [call[0] for call in page.evaluate('__calls')]
    c.ok('requestFullscreen' not in calls, 'tdesktop: fullscreen is not forced')
    c.ok(page.evaluate("document.documentElement.classList.contains('qw-desktop')"), 'tdesktop: html.qw-desktop')
    body = page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--qw-fs-body').trim()")
    c.ok(body == '16px', f'tdesktop: body text 16px at 390px width, got {body}')

    # --- fullscreen with zero reported insets (some Android/iOS clients): fallback keeps the header clear ---
    for platform_name, expected in (('android', '84px'), ('ios', '103px')):
        harness(page, f'?tg={platform_name}&v=8.0&zero=1&fs=1&debug=1')
        page.evaluate("QW.boot({mode:'hub'})")
        top = page.evaluate("getComputedStyle(document.getElementById('head')).paddingTop")
        c.ok(top == expected, f'{platform_name}: zero insets in fullscreen use the fallback, got {top}')
        text = page.evaluate("document.getElementById('qw-debug')?.textContent || ''")
        c.ok('fallback-top' in text and 'fallback-bottom' in text and 'safe-bottom=' in text and platform_name in text
             and 'query_id' not in text, f'?debug=1 shows top and bottom insets without initData, got {text!r}')
        bottom = page.evaluate("getComputedStyle(document.getElementById('bottombar')).paddingBottom")
        c.ok(bottom == ('34px' if platform_name == 'ios' else '48px'), f'{platform_name}: zero bottom inset in fullscreen uses the fallback, got {bottom}')
        page.evaluate("__tg.emit('safeAreaChanged', {safeAreaInset:{top:0,right:0,bottom:20,left:0}})")
        bottom = page.evaluate("getComputedStyle(document.getElementById('bottombar')).paddingBottom")
        c.ok(bottom == '20px', f'{platform_name}: a real bottom inset overrides the fallback, got {bottom}')
        page.evaluate("__tg.emit('safeAreaChanged', {safeAreaInset:{top:0,right:0,bottom:0,left:0}})")
        page.evaluate("__tg.emit('contentSafeAreaChanged', {contentSafeAreaInset:{top:40,right:0,bottom:0,left:0}})")
        top = page.evaluate("getComputedStyle(document.getElementById('head')).paddingTop")
        c.ok(top == '40px', f'{platform_name}: real insets override the fallback, got {top}')

    # --- after /app -> game navigation the URL has no tgWebApp params; sessionStorage keeps Telegram mode ---
    harness(page, '?tg=android&v=8.0')
    page.evaluate("Telegram.WebApp.initData = ''; sessionStorage.setItem('__telegram__initParams', JSON.stringify({tgWebAppData: 'x', tgWebAppPlatform: 'android'}))")
    c.ok(page.evaluate('QW.isTelegram()') is True, 'Telegram mode survives navigation via sessionStorage initParams')
    page.evaluate("sessionStorage.removeItem('__telegram__initParams')")

    # --- SDK loading (UI_RULES §7): a plain browser never requests it; a Telegram launch never blocks the page ---
    harness(page, '?tg=none')
    c.ok(page.evaluate('QW.sdkState') == 'not-needed', 'browser: the Telegram SDK is not requested')
    c.ok(page.evaluate("document.querySelectorAll('script[src*=\"telegram-web-app\"]').length") == 0, 'browser: no SDK script element')
    c.ok(page.evaluate('QW.telegramReady.then(v => v === null)') is True, 'browser: telegramReady resolves to null at once')
    harness(page, '?tg=none', '#tgWebAppData=x&tgWebAppPlatform=android&tgWebAppVersion=8.0')
    page.evaluate("QW.boot({mode:'hub'}); window.headMounted = Boolean(QW.header.mountGear(document.getElementById('head')))")
    c.ok(page.evaluate('window.headMounted') is True and page.evaluate('QW.sdkState') in ('loading', 'failed', 'timeout'),
         f"Telegram launch: page boots without waiting for the SDK (state {page.evaluate('QW.sdkState')})")
    started = page.evaluate('performance.now()')
    page.evaluate('QW.telegramReady')
    waited = page.evaluate('performance.now()') - started
    c.ok(waited < 3600 and page.evaluate('QW.sdkState') in ('failed', 'timeout'), f'unreachable SDK gives up within 3 s (waited {round(waited)} ms)')

    # --- old Telegram (6.0): nothing throws, BackButton still wired ---
    harness(page, '?tg=android&v=6.0')
    page.evaluate("QW.boot({mode:'game'})")
    calls = [call[0] for call in page.evaluate('__calls')]
    c.ok('requestFullscreen' not in calls and 'disableVerticalSwipes' not in calls, 'telegram 6.0: version-gated calls skipped')
    page.close()
    return c


def run_gaps_selftest(pw_browser):
    c = Checks()
    page = pw_browser.new_page(viewport={'width': 390, 'height': 800})
    harness(page, '?tg=none')
    page.evaluate("""() => { document.getElementById('main').innerHTML = `
      <div class="gap-bad" id="bad"><button>Пройтись самому</button><button>Разобрать корзину</button><button>Отменить</button></div>
      <div class="qw-btn-stack" id="good" style="margin-top:40px"><button class="qw-btn primary">Главное</button><button class="qw-btn">Второе</button><button class="qw-btn danger">Отменить</button></div>
      <div class="qw-btn-group" style="margin-top:40px"><button aria-pressed="true">Он</button><button>Она</button><button>Не указывать</button></div>`; }""")
    result = page.evaluate(SCANNER, [MIN_GAP, MIN_TAP])
    gaps = [issue for issue in result['issues'] if issue['kind'] == 'gap']
    c.ok(len(gaps) == 2, f'scanner finds both glued pairs in the bad stack, got {gaps}')
    c.ok(all('Главное' not in issue['a'] + issue['b'] for issue in gaps), '.qw-btn-stack passes')
    c.ok(all('Она' not in issue['a'] + issue['b'] for issue in result['issues']), '.qw-btn-group is allowed to be glued')
    page.close()
    return c


SETUP_PRELUDE = ("async () => { const wait = ms => new Promise(r => setTimeout(r, ms)); "
                 "const click = re => [...document.querySelectorAll('button,a')].find(x => re.test(x.textContent))?.click(); ")


def run_startup(pw_browser, base):
    """Pages render without any other host: telegram.org (and everything off-origin) is blocked; Telegram launches
    still get the pinned SDK from our origin with working insets and BackButton."""
    from urllib.parse import urlsplit
    c = Checks()
    origin = urlsplit(base).netloc
    context = pw_browser.new_context(viewport={'width': 390, 'height': 844})
    external = []

    def guard(route):
        host = urlsplit(route.request.url).netloc
        if host and host != origin:
            external.append(route.request.url)
            return route.abort()
        return route.continue_()
    context.route('**/*', guard)
    page = context.new_page()
    for path, ready in (('/app', '[data-qw-gear]'), ('/app/farm', '[data-qw-gear], #login:not([hidden])'), ('/app/alchemy', '[data-qw-gear]')):
        started = page.evaluate('performance.now()') if page.url.startswith('http') else 0
        page.goto(base + path, wait_until='commit')
        try:
            page.wait_for_selector(ready, timeout=2500)
            shown = True
        except Exception:  # noqa: BLE001 - reported below
            shown = False
        c.ok(shown, f'{path}: rendered within 2.5 s with every other host blocked')
        c.ok(page.evaluate('window.QW?.sdkState') in ('not-needed', None), f"{path}: browser does not request the SDK (state {page.evaluate('window.QW?.sdkState')})")
        # The splash must give way within 2.5 s (polling via evaluate: the production CSP forbids string evaluation).
        left = False
        for _ in range(25):
            if page.evaluate("() => !document.body.innerText.includes('Открываем QuizzyWizzy')"):
                left = True
                break
            page.wait_for_timeout(100)
        c.ok(left, f'{path}: not stuck on the splash text')
    c.ok(not external, f'no request leaves the origin: {external[:5]}')
    tg_hash = ('#tgWebAppData=query_id%3Dx%26user%3D%257B%2522id%2522%253A1%257D%26auth_date%3D1%26hash%3Dx'
               '&tgWebAppVersion=8.0&tgWebAppPlatform=android&tgWebAppThemeParams=%7B%7D')
    page.goto(base + '/app/alchemy' + tg_hash, wait_until='load')
    page.reload(wait_until='load')
    for _ in range(40):
        if page.evaluate("() => Boolean(window.QW) && QW.sdkState !== 'loading'"):
            break
        page.wait_for_timeout(100)
    c.ok(page.evaluate('QW.sdkState') == 'loaded' and page.evaluate('QW.isTelegram()'), f"Telegram launch: pinned SDK loaded from our origin ({page.evaluate('QW.sdkState')})")
    page.evaluate("""() => { Telegram.WebView.receiveEvent('safe_area_changed', {top: 28, bottom: 0, left: 0, right: 0});
        Telegram.WebView.receiveEvent('fullscreen_changed', {is_fullscreen: true}); }""")
    page.wait_for_timeout(300)
    c.ok(page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--qw-tg-safe-bottom').trim()") == '48px', 'Telegram launch: Android bottom fallback applied')
    c.ok(page.evaluate('Telegram.WebApp.BackButton.isVisible') is True, 'Telegram launch: BackButton wired (game root → main menu)')
    c.ok(not external, f'no request leaves the origin in Telegram mode either: {external[:5]}')
    context.close()
    return c


def gap_scenarios(base):
    """(name, url, setup-js or None). Setup runs after load; screens that need data are best-effort."""
    hub = base + '/app'
    return [
        ('hub-home', hub, None),
        ('hub-chats', hub, "document.querySelector('[data-page=chats]')?.click()"),
        ('hub-rating', hub, "document.querySelector('[data-page=rating]')?.click()"),
        ('hub-profile', hub, "document.querySelector('[data-page=profile]')?.click()"),
        ('hub-menu', hub, "document.querySelector('[data-qw-gear]')?.click()"),
        ('hub-settings', hub, r"document.querySelector('[data-page=profile]')?.click(); await wait(1200); click(/^\s*Настройки\s*$/)"),
        ('hub-chat', hub, "document.querySelector('[data-page=chats]')?.click(); await wait(1200); click(/Открыть|Утренний квиз/)"),
        ('hub-quiz', hub, "click(/Играть в квиз|Классический квиз/)"),
        ('hub-night-city', hub, "click(/Открыть дело/)"),
        ('farm', base + '/app/farm', None),
        ('farm-menu', base + '/app/farm', "document.querySelector('[data-qw-gear]')?.click()"),
        ('farm-forest', base + '/app/farm', "window.__qwOpenFarmTab?.('forest') ?? document.querySelector('[data-tab=forest]')?.click()"),
        # The active trip card (owner's bad example: three glued buttons) appears only after a trip starts.
        ('farm-forest-active', base + '/app/farm', "(window.__qwOpenFarmTab?.('forest') ?? document.querySelector('[data-tab=forest]')?.click()); "
                                                   "await wait(1200); click(/Сам, без игры/); await wait(2500)"),
        ('alchemy', base + '/app/alchemy', None),
        ('alchemy-menu', base + '/app/alchemy', "document.querySelector('[data-qw-gear]')?.click()"),
    ]


def run_gaps(pw_browser, base, only=None):
    c = Checks()
    report = {}
    for width, height in ((320, 640), (390, 844), (1280, 800)):
        context = pw_browser.new_context(viewport={'width': width, 'height': height})
        page = context.new_page()
        for name, url, setup in gap_scenarios(base):
            if only and not name.startswith(only):
                continue
            try:
                page.goto(url, wait_until='load', timeout=30000)
                page.wait_for_timeout(1500)
                # Local offline stand: enter as the synthetic dev player so the hub shows real sections.
                page.evaluate("""async () => { const b = [...document.querySelectorAll('button')].find(x => /dev-игрок/.test(x.textContent));
                    if (b) { b.click(); await new Promise(r => setTimeout(r, 2000)); } }""")
                if setup:
                    page.evaluate(SETUP_PRELUDE + setup + ' }')
                    page.wait_for_timeout(900)
                result = page.evaluate(SCANNER, [MIN_GAP, MIN_TAP])
                if width < 768:
                    result['issues'] += page.evaluate(ZONE_SCANNER, [47, 48])
            except Exception as error:  # noqa: BLE001 - report and continue with other screens
                c.ok(False, f'{name}@{width}: could not open ({str(error).splitlines()[0]})')
                continue
            report[f'{name}@{width}'] = result
            for issue in result['issues']:
                if issue['kind'] == 'gap':
                    detail = f"{issue['a']} ↔ {issue['b']} gap {issue['gap']}px"
                elif issue['kind'] == 'height':
                    detail = f"{issue['a']} height {issue['height']}px"
                else:
                    detail = f"{issue['a']} at y={issue['y']}px is inside the {issue['kind']} zone"
                c.ok(False, f'{name}@{width}: {issue["kind"]}: {detail}')
            c.ok(True, f'{name}@{width} scanned')
        context.close()
    return c, report


def run_dasha(pw_browser, base, screenshots):
    """Real server-backed Dasha view at phone and desktop widths; only creates a guest session."""
    c = Checks()
    screenshots.mkdir(parents=True, exist_ok=True)
    context = pw_browser.new_context(viewport={'width': 390, 'height': 844})
    page = context.new_page()
    command_posts = []
    page_errors = []
    page.on('pageerror', lambda error: page_errors.append(str(error)))
    page.on('request', lambda request: command_posts.append(request.url) if request.method == 'POST' and '/api/farm/v1/commands' in request.url else None)
    try:
        page.goto(base + '/app', wait_until='load', timeout=30000)
        guest = page.evaluate("""async () => {
            const response = await fetch('/api/guest/start', {method:'POST', credentials:'same-origin', headers:{'X-Guest-CSRF':'1'}});
            return {ok:response.ok, status:response.status};
        }""")
        c.ok(guest['ok'], f'test guest created (HTTP {guest["status"]})')
        if not guest['ok']:
            context.close()
            return c

        for width, height in ((320, 640), (390, 844), (1280, 800)):
            page.set_viewport_size({'width': width, 'height': height})
            try:
                page.goto(base + '/app/farm?identity=guest', wait_until='load', timeout=30000)
                direct_village = page.locator('[data-tab="village"]')
                if direct_village.is_visible():
                    direct_village.click()
                else:
                    page.locator('[data-tab="more"]').click()
                    page.locator('[data-more-tab="village"]').click()
                fox = page.locator('[data-village-npc="Лиса Даша"]').first
                fox.wait_for(state='visible', timeout=15000)
                fox.click()
                play = page.locator('#panel-content [data-open-dasha="true"]')
                play.wait_for(state='visible', timeout=15000)
                play.click()
                view = page.locator('#dasha-game-view')
                view.wait_for(state='visible', timeout=10000)
                page.wait_for_selector('#dasha-game-view .dasha-round-status', state='visible', timeout=10000)

                c.ok(view.is_visible(), f'dasha@{width}: game is a visible in-shell view')
                c.ok(page.locator('[data-qw-gear]').is_visible(), f'dasha@{width}: shell settings menu remains accessible')
                page.locator('[data-qw-gear]').click()
                menu_open = page.locator('.qw-menu.qw-open').is_visible()
                c.ok(menu_open, f'dasha@{width}: settings menu opens over game')
                if menu_open:
                    page.locator('[data-qw-gear]').click()
                dimensions = page.evaluate("""() => ({
                    viewport: innerWidth,
                    document: document.documentElement.scrollWidth,
                    body: document.body.scrollWidth,
                    view: document.querySelector('#dasha-game-view').scrollWidth,
                    viewClient: document.querySelector('#dasha-game-view').clientWidth
                })""")
                c.ok(dimensions['document'] <= width + 1 and dimensions['body'] <= width + 1 and dimensions['view'] <= dimensions['viewClient'] + 1,
                     f'dasha@{width}: no horizontal overflow ({dimensions})')
                locked = page.locator('#dasha-game-view .dasha-round-status').inner_text()
                c.ok('3 уровня' in locked, f'dasha@{width}: level-locked test guest sees human-readable reason ({locked!r})')
                c.ok(page.locator('#dasha-game-view [data-role="action"]').is_disabled(), f'dasha@{width}: locked guest cannot start a wager')

                result = page.evaluate(SCANNER, [MIN_GAP, MIN_TAP])
                if width < 768:
                    result['issues'] += page.evaluate(ZONE_SCANNER, [47, 48])
                report_path = screenshots / f'dasha-{width}.png'
                page.screenshot(path=str(report_path), full_page=True)
                for issue in result['issues']:
                    if issue['kind'] == 'gap':
                        detail = f'{issue["a"]} ↔ {issue["b"]} gap {issue["gap"]}px'
                    elif issue['kind'] == 'height':
                        detail = f'{issue["a"]} height {issue["height"]}px'
                    else:
                        detail = f'{issue["a"]} at y={issue["y"]}px is inside {issue["kind"]} zone'
                    c.ok(False, f'dasha@{width}: {issue["kind"]}: {detail}')
                c.ok(True, f'dasha@{width}: button gaps/tap targets scanned; screenshot {report_path}')
            except Exception as error:  # noqa: BLE001 - report each viewport independently
                c.ok(False, f'dasha@{width}: scenario failed ({str(error).splitlines()[0]})')
        c.ok(not command_posts, f'no farm command or wager was submitted ({command_posts})')
        c.ok(not page_errors, f'no browser page errors ({page_errors})')
    finally:
        context.close()
    return c


ERRORS_ROUTE = r'/problem-reports/errors'
MANUAL_ROUTE = r'/problem-reports(\?|$)'


def run_errors(pw_browser):
    """Automatic error reports: capture, noise filter, dedup, rate limits, sanitising, breadcrumbs, soft toast, manual attach."""
    import re
    from playwright.sync_api import expect
    c = Checks()

    def count_is(locator, n):
        try:
            expect(locator).to_have_count(n, timeout=2000)
            return True
        except AssertionError:
            return False

    def clean_start(page, page_errors):
        c.ok(page.evaluate('QW.errors.last() === null') and not page_errors and page.locator('.qw-toast').count() == 0, f'clean start (errors={page_errors})')

    def diagnose(label, page, page_errors, before):
        if len(c.failures) > before:
            print(f'DIAG {label}: page_errors={page_errors} last={page.evaluate("QW.errors.last()")} toasts={page.locator(".qw-toast").count()}')

    def settle(page, ms):
        page.clock.run_for(ms)
        page.wait_for_timeout(150)  # route callbacks run on the Python side

    def fresh(clock=True, abort=False):
        context = pw_browser.new_context(viewport={'width': 390, 'height': 800})
        page = context.new_page()
        posts, manual, page_errors = [], [], []
        page.on('pageerror', lambda error: page_errors.append(str(error)))
        if abort:
            page.route(re.compile(ERRORS_ROUTE), lambda r: (posts.append(r.request.post_data), r.abort()))
        else:
            page.route(re.compile(ERRORS_ROUTE), lambda r: (posts.append(r.request.post_data), r.fulfill(status=202, content_type='application/json', body='{"accepted": true, "report_id": 7, "new": true}')))
        page.route(re.compile(MANUAL_ROUTE), lambda r: (manual.append(r.request.post_data), r.fulfill(status=201, content_type='application/json', body='{"report_id": 9, "number": 9}')) if r.request.method == 'POST'
                   else r.fulfill(status=404, content_type='application/json', body='{}'))
        if clock:
            page.clock.install(time=1_700_000_000_000)
        harness(page, '?tg=none')
        if clock:
            page.clock.pause_at(1_700_000_001_000)  # install() alone lets time flow; pause it so every run_for is deterministic
        page.evaluate("QW.boot({mode:'hub'}); QW.header.mountGear(document.getElementById('head'))")
        return context, page, posts, manual, page_errors

    fire = """(i) => window.dispatchEvent(new ErrorEvent('error', {message: 'Uncaught TypeError: boom ' + i, filename: location.href.split('#')[0] + '?q=1#h', lineno: 10 + i, colno: 3,
        error: Object.assign(new TypeError('boom ' + i), {stack: 'TypeError: boom ' + i + '\\n    at f (' + location.href + '?a=1#b:' + (10 + i) + ':3)'})}))"""

    # --- capture, noise, dedup, resource errors ---
    context, page, posts, manual, page_errors = fresh()
    page.evaluate(fire, 1)
    settle(page, 50)
    c.ok(len(posts) == 1, f'an error event is reported once, got {len(posts)}')
    body = json.loads(posts[0]) if posts else {'error': {'source': '?', 'message': ''}}
    c.ok(body['error'].get('type') == 'error' and body['error']['message'].startswith('TypeError: boom'), 'error record has type and message')
    c.ok('?' not in body['error']['source'] and '#' not in body['error']['source'], 'source is a path without query and hash')
    c.ok(bool(posts) and '?a=1' not in posts[0] and '#b' not in posts[0], 'stack URLs lose query and hash')
    c.ok(bool(re.fullmatch(r'[0-9a-f-]{36}', body.get('request_id', ''))), 'request_id is a uuid')
    page.evaluate(fire, 1)
    settle(page, 4000)
    c.ok(len(posts) == 1, 'the same fingerprint is sent once per page load')
    page.evaluate("window.dispatchEvent(new PromiseRejectionEvent('unhandledrejection', {promise: Promise.resolve(), reason: new Error('rej 1')}))")
    settle(page, 3100)
    c.ok(len(posts) == 2 and json.loads(posts[1])['error']['type'] == 'unhandledrejection', 'unhandledrejection is reported')
    page.evaluate("window.dispatchEvent(new PromiseRejectionEvent('unhandledrejection', {promise: Promise.resolve(), reason: 'plain string reason'}))")
    settle(page, 3100)
    c.ok('plain string reason' in posts[-1], 'a non-Error rejection reason becomes its string')
    n = len(posts)
    page.evaluate("window.dispatchEvent(new ErrorEvent('error', {message: 'ResizeObserver loop completed with undelivered notifications.', filename: location.href, lineno: 1}))")
    page.evaluate("window.dispatchEvent(new ErrorEvent('error', {message: 'Script error.'}))")
    page.evaluate("window.dispatchEvent(new ErrorEvent('error', {message: 'ext fail', filename: 'chrome-extension://abc/x.js', lineno: 4}))")
    page.evaluate("const i = document.createElement('img'); i.src = 'missing-image.png'; document.body.append(i)")
    settle(page, 4000)
    c.ok(len(posts) == n, 'noise (ResizeObserver, Script error., extensions) and resource errors are ignored')
    page.evaluate("(() => { const s = document.createElement('script'); s.textContent = \"throw new Error('real thrown 77')\"; document.head.append(s); Promise.reject(new Error('real rejected 88')); })()")
    settle(page, 7000)
    texts = ' '.join(posts[n:])
    c.ok('real thrown' in texts and 'real rejected' in texts, 'real browser errors and rejections are captured')
    context.close()

    # --- rate limits: 1 per 3 s, 5 per load, queue is bounded ---
    context, page, posts, manual, page_errors = fresh()
    for i in range(20, 30):
        page.evaluate(fire, i * 1000)
    settle(page, 10)
    c.ok(len(posts) == 1, f'first error goes out at once and the rest wait (3 s gap), got {len(posts)}')
    for expected in (2, 3, 4, 5):
        settle(page, 3100)
        c.ok(len(posts) == expected, f'one more error per 3 s: expected {expected}, got {len(posts)}')
    settle(page, 20000)
    page.evaluate(fire, 99000)
    settle(page, 5000)
    c.ok(len(posts) == 5, f'at most 5 reports per page load, got {len(posts)}')
    context.close()

    # --- no recursion when the endpoint fails ---
    context, page, posts, manual, page_errors = fresh(abort=True)
    page.evaluate(fire, 5)
    settle(page, 8000)
    c.ok(len(posts) == 1 and not page_errors, f'a failing endpoint causes neither retries nor page errors (posts={len(posts)}, errors={page_errors})')
    context.close()

    # --- sanitising ---
    context, page, posts, manual, page_errors = fresh()
    page.evaluate("""() => { const dirty = 'bad https://x.example/a.js?token=SECRET1#frag tgWebAppData=query_id%3DAAA&user=%7B%22id%22%3A1%7D hash=deadbeef auth_date=1700000 '
            + 'ivan@example.com +7 912 345 67 89 Bearer abc.def.ghi ' + 'A'.repeat(48);
        window.dispatchEvent(new ErrorEvent('error', {message: dirty, filename: 'https://cdn.example/app.js?x=1#y', lineno: 3,
            error: Object.assign(new Error(dirty), {stack: 'Error: ' + dirty + '\\n at q (https://cdn.example/app.js?x=1#y:3:1)'})})); }""")
    settle(page, 50)
    dirty = posts[0] if posts else ''
    c.ok(bool(dirty), 'the sanitising probe was sent')
    for needle in ('SECRET1', '#frag', 'tgWebAppData', 'user=%7B', 'hash=deadbeef', 'auth_date', 'ivan@example', '912 345', 'abc.def.ghi', 'AAAAAAAAAAAAAAAA', '?x=1', '#y'):
        c.ok(needle not in dirty, f'sanitised: {needle!r} is not sent')
    c.ok(bool(dirty) and json.loads(dirty)['error']['source'] == 'cdn.example/app.js', 'a foreign source keeps host and path only')
    context.close()

    # --- breadcrumbs: identifiers only ---
    context, page, posts, manual, page_errors = fresh()
    page.evaluate("""() => { const b = document.createElement('button'); b.className = 'plain big'; b.textContent = 'Иван Петров'; b.value = 'secret-value'; document.getElementById('main').append(b);
        const d = document.createElement('button'); d.dataset.qwItem = 'sound'; d.textContent = 'Звук'; document.getElementById('main').append(d); }""")
    page.click('button.plain')
    page.click('[data-qw-item=sound]')
    crumbs = page.evaluate('QW.errors.crumbs()')
    c.ok(crumbs[-2]['target'] == 'button.plain' and crumbs[-1]['target'] == 'sound', f'crumb targets are ids or tag.class, got {crumbs[-2:]}')
    c.ok('Иван' not in json.dumps(crumbs, ensure_ascii=False) and 'secret-value' not in json.dumps(crumbs), 'crumbs never contain text or values')
    for _ in range(14):
        page.click('button.plain')
    page.evaluate("document.querySelector('[data-qw-gear]').click()")
    page.evaluate("QW.menu.close(); QW.nav.push({id:'screen-x'}); QW.nav.pop('screen-x')")
    crumbs = page.evaluate('QW.errors.crumbs()')
    kinds = {x['kind'] for x in crumbs}
    c.ok(len(crumbs) == 10, f'the ring keeps 10 crumbs, got {len(crumbs)}')
    c.ok({'menu', 'nav'} <= kinds, f'menu and nav steps are recorded, got {kinds}')
    page.evaluate(fire, 3)
    settle(page, 50)
    sent = json.loads(posts[0])
    c.ok(len(sent['breadcrumbs']) == 10 and all(re.fullmatch(r'[A-Za-z0-9_.:#/-]{1,60}', x['target']) and isinstance(x['t'], int) for x in sent['breadcrumbs']), 'sent crumbs are 10 whitelisted ids with integer t')
    c.ok('Иван' not in posts[0], 'no button text in the request')
    context.close()

    # --- soft toast ---
    context, page, posts, manual, page_errors = fresh()
    before = len(c.failures)
    clean_start(page, page_errors)
    page.evaluate(fire, 1)
    c.ok(count_is(page.locator('.qw-toast[role=status]'), 1), 'a toast appears after the first error')
    c.ok(page.evaluate("!document.querySelector('.qw-toast').hasAttribute('aria-modal') && !document.querySelector('.qw-menu-scrim')"), 'the toast is not modal')
    c.ok(page.evaluate("[...document.querySelectorAll('.qw-toast button')].every(b => b.getBoundingClientRect().height >= 44)"), 'toast buttons are 44px tall')
    page.evaluate(fire, 2)
    c.ok(count_is(page.locator('.qw-toast'), 1), 'no second toast while one is shown')
    page.click('.qw-toast-close')
    c.ok(count_is(page.locator('.qw-toast'), 0), '✕ closes the toast')
    page.evaluate(fire, 3)
    c.ok(count_is(page.locator('.qw-toast'), 0), 'the toast is not shown again within 5 minutes')
    diagnose('toast', page, page_errors, before)
    context.close()

    context, page, posts, manual, page_errors = fresh()
    page.evaluate(fire, 1)
    settle(page, 10100)
    c.ok(count_is(page.locator('.qw-toast'), 0), 'the toast disappears after 10 s')
    context.close()

    context, page, posts, manual, page_errors = fresh()
    page.evaluate("document.querySelector('[data-qw-gear]').click()")
    page.evaluate(fire, 1)
    c.ok(count_is(page.locator('.qw-toast'), 0), 'no toast while the menu is open')
    context.close()

    # --- «Сообщить» opens the form with last_error attached and visible ---
    context, page, posts, manual, page_errors = fresh()
    before = len(c.failures)
    clean_start(page, page_errors)
    page.evaluate(fire, 1)
    settle(page, 50)
    expect(page.locator('.qw-toast-send')).to_have_count(1, timeout=3000)
    page.click('.qw-toast-send')
    c.ok(page.evaluate('QW.report.isOpen()') and count_is(page.locator('.qw-toast'), 0), '«Сообщить» closes the toast and opens the report form')
    page.click('.qw-report summary')
    c.ok('Последняя ошибка' in (page.text_content('.qw-report-list') or '') and 'boom 1' in (page.text_content('.qw-report-list') or ''), 'the last error is visible in «Что приложится»')
    page.fill('.qw-report-text', 'ошибка после нажатия')
    page.click('.qw-report-foot .qw-btn')
    page.wait_for_timeout(500)
    context_sent = json.loads(manual[0])['context'] if manual else {}
    last_error = context_sent.get('last_error', {})
    c.ok(last_error.get('message', '').startswith('TypeError: boom 1') and last_error.get('report_id') == 7 and last_error.get('line') == 11, f'manual report carries last_error with the auto report id, got {last_error}')
    diagnose('attach', page, page_errors, before)
    context.close()

    # --- URL clean-up keeps :line:col; huge input stays fast; spent budget stays cheap ---
    context, page, posts, manual, page_errors = fresh()
    page.evaluate("""() => { const stack = 'TypeError: t\\n at a (https://h.example/x.js?v=1:10:5)\\n at b (https://h.example/page#tgWebAppData=query_id%3DSECRETX&user=%7B1%7D:3:7)\\n    fn@https://h.example/y.js?v=1:20:9\\n at c (https://h.example/z.js:4:2)';
        window.dispatchEvent(new ErrorEvent('error', {message: 'TypeError: t', filename: 'https://h.example/x.js?v=1', lineno: 10, error: Object.assign(new TypeError('t'), {stack})})); }""")
    settle(page, 50)
    stack = json.loads(posts[0])['error']['stack'] if posts else ''
    for needle in ('x.js:10:5', 'page:3:7', 'y.js:20:9', 'z.js:4:2'):
        c.ok(needle in stack, f'stack keeps line and column: {needle!r} in {stack!r}')
    c.ok('SECRETX' not in stack and '?v=1' not in stack and 'tgWebAppData' not in stack, 'the secret hash and the query are gone from the stack')
    context.close()

    context, page, posts, manual, page_errors = fresh()
    started = page.evaluate("""() => { const big = 'a'.repeat(100000) + '@' + 'b'.repeat(100000); const t = performance.now();
        window.dispatchEvent(new ErrorEvent('error', {message: big, filename: location.href, lineno: 1, error: new Error(big)})); return performance.now() - t; }""")
    settle(page, 50)
    c.ok(started < 1000, f'a 200 KB message is handled quickly, took {started:.0f} ms')
    c.ok(bool(posts) and len(posts[0]) < 16000, 'the 200 KB message is cut to a small request')
    context.close()

    context, page, posts, manual, page_errors = fresh()
    for i in range(1, 30):
        page.evaluate(fire, i * 1000)
    settle(page, 20000)
    c.ok(len(posts) == 5, f'budget caps sending at 5, got {len(posts)}')
    c.ok(page.evaluate('QW.errors.last().message').startswith('TypeError: boom'), 'last() still follows later errors once the budget is spent')
    context.close()

    context, page, posts, manual, page_errors = fresh()
    c.ok(page.evaluate("""() => { const body = document.body; body.remove(); let ok = true;
        try { window.dispatchEvent(new ErrorEvent('error', {message: 'early failure', filename: location.href, lineno: 2, error: new Error('early failure')})); } catch { ok = false; }
        document.documentElement.append(body); return ok && QW.errors.last()?.message === 'Error: early failure'; }"""), 'an error before <body> exists does not throw and is recorded')
    settle(page, 50)
    c.ok(len(posts) == 1 and not page_errors, f'the early error is still sent (posts={len(posts)}, errors={page_errors})')
    context.close()

    # --- public API ---
    context, page, posts, manual, page_errors = fresh()
    c.ok(page.evaluate("typeof QW.errors.capture === 'function' && typeof QW.errors.last === 'function' && typeof QW.errors.crumb === 'function' && QW.errors.last() === null"), 'QW.errors has capture, last and crumb')
    page.evaluate("QW.errors.capture(new RangeError('manual capture'))")
    settle(page, 50)
    c.ok(page.evaluate("QW.errors.last().message") == 'RangeError: manual capture' and len(posts) == 1, 'QW.errors.capture reports a game-side error')
    context.close()
    return c


def main(argv):
    command = argv[1] if len(argv) > 1 else 'nav'
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print('FAIL: python playwright is not installed' if command == 'dasha' else 'SKIP: python playwright is not installed')
        return 1 if command == 'dasha' else 0
    with sync_playwright() as playwright:
        pw_browser = browser(playwright)
        if pw_browser is None:
            print('FAIL: no Chromium, Edge or Chrome for Playwright' if command == 'dasha' else 'SKIP: no Chromium, Edge or Chrome for Playwright')
            return 1 if command == 'dasha' else 0
        try:
            if command == 'nav':
                checks = run_nav(pw_browser)
            elif command == 'errors':
                checks = run_errors(pw_browser)
            elif command == 'startup':
                base = argv[argv.index('--base') + 1].rstrip('/') if '--base' in argv else None
                if not base:
                    print('SKIP: startup needs --base URL of a running app')
                    return 0
                checks = run_startup(pw_browser, base)
            elif command == 'gaps-selftest':
                checks = run_gaps_selftest(pw_browser)
            elif command == 'gaps':
                base = argv[argv.index('--base') + 1].rstrip('/') if '--base' in argv else None
                if not base:
                    print('SKIP: gaps needs --base URL of a running app')
                    return 0
                only = argv[argv.index('--only') + 1] if '--only' in argv else None
                checks, report = run_gaps(pw_browser, base, only)
                if '--json' in argv:
                    print(json.dumps(report, ensure_ascii=False))
            elif command == 'dasha':
                base = argv[argv.index('--base') + 1].rstrip('/') if '--base' in argv else None
                if not base:
                    print('FAIL: dasha needs --base URL of a running app')
                    return 1
                screenshots = Path(argv[argv.index('--screenshots') + 1]) if '--screenshots' in argv else ROOT / '.local' / 'dasha-integration-20261020' / 'ui'
                checks = run_dasha(pw_browser, base, screenshots)
            else:
                print(f'unknown command {command}')
                return 2
        finally:
            pw_browser.close()
    for failure in checks.failures:
        print('FAIL:', failure)
    print(f'{command}: {checks.passed} passed, {len(checks.failures)} failed')
    return 1 if checks.failures else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
