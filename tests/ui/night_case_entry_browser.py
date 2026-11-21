"""Bounded real Case entry QA, own browser DB: the game root, a company and Back, no Mafia prototype."""
import asyncio
import json
import os
from pathlib import Path

from night_case_browser import Harness
from ui_check import SCANNER


async def capture(page, path):
    await page.evaluate('scrollTo(0,0)')
    await page.screenshot(path=str(path), full_page=True)
    issues = []
    height = await page.evaluate('document.documentElement.scrollHeight')
    for y in range(0, height, page.viewport_size['height'] - 100):
        await page.evaluate('(y) => scrollTo(0,y)', y)
        issues.extend((await page.evaluate(SCANNER, [8, 44]))['issues'])
    await page.evaluate('scrollTo(0,0)')
    assert not issues, issues
    return {'issues': issues}


async def main():
    from playwright.async_api import async_playwright
    output = Path(os.environ['NIGHT_ENTRY_OUTPUT'])
    output.mkdir(parents=True, exist_ok=True)
    harness = Harness(4899)
    report = {'scope': 'night_entry_compatibility', 'frames': [], 'errors': [], 'audio_requests': [],
              'limits': ['Entry shell is always dark; day/night have identical approved static shell art.']}
    try:
        await harness.start()
        async with async_playwright() as p:
            browser = await p.chromium.launch(channel='msedge')
            context = await browser.new_context(viewport={'width': 390, 'height': 844}, reduced_motion='reduce')
            def audit(request):
                if request.resource_type == 'media':
                    report['audio_requests'].append(request.url)
            context.on('request', audit)
            page = await context.new_page()
            page.on('pageerror', lambda error: report['errors'].append(str(error)))
            response = await context.request.post(harness.origin + '/api/guest/start',
                headers={'Origin': harness.origin, 'X-Guest-CSRF': '1'})
            assert response.ok
            await page.goto(harness.origin + '/app')
            await page.get_by_role('button', name='Открыть дело', exact=True).click()
            await page.get_by_role('heading', name='Твои компании', exact=True).wait_for()
            body = await page.locator('body').inner_text()
            assert 'Классическая Мафия' not in body and 'Хозяин исчез' not in body, body[:400]
            report['case_root_without_mafia'] = True
            for period in ['day', 'night']:
                for width, height in [(375, 812), (390, 844), (1280, 800)]:
                    await page.set_viewport_size({'width': width, 'height': height})
                    path = output / f'case-entry-{period}-{width}.png'
                    gaps = await capture(page, path)
                    report['frames'].append({'path': str(path), 'gaps': gaps})
                    assert not gaps['issues'], gaps
            # A company is one step below the root: the browser ‹ appears there and returns to the list.
            back = page.get_by_role('button', name='Назад', exact=True)
            assert not await back.is_visible()
            await page.get_by_label('Название компании', exact=True).fill('Пятничная компания')
            await page.get_by_role('button', name='Создать', exact=True).click()
            await back.wait_for()
            path = output / 'company-390.png'
            await page.set_viewport_size({'width': 390, 'height': 844})
            await page.screenshot(path=str(path), full_page=True); report['frames'].append({'path': str(path)})
            await back.click()
            await page.get_by_role('heading', name='Твои компании', exact=True).wait_for()
            await page.get_by_role('button', name='Пятничная компания', exact=True).wait_for()
            assert not await back.is_visible()
            report['back_from_company'] = True
            # A room link opens the case directly: no mode choice.
            await page.goto(harness.origin + '/app?room=' + 'Z' * 43)
            await page.get_by_text('Ночной город').first.wait_for()
            await page.wait_for_timeout(1500)
            assert await page.get_by_role('button', name='Недельное расследование', exact=True).count() == 0
            report['room_link_without_mode_choice'] = True
            assert not report['audio_requests'], report['audio_requests']
            assert not report['errors'], report['errors']
            report['passed'] = True
            await browser.close()
    finally:
        await harness.stop()
        await harness.database.dispose()
        (output / 'entry-browser-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')


if __name__ == '__main__':
    asyncio.run(main())
