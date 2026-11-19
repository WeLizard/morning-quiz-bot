"""Real building UI cycle. Run only inside the isolated building QA Docker app.

The companion app must expose POST /__qa/building-effects/setup (seed the
current guest) and /__qa/building-effects/advance {seconds}. Neither endpoint
belongs to the product app. Screenshots are viewport-only, with panel scrolling.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from playwright.sync_api import expect, sync_playwright
from ui_check import MIN_GAP, MIN_TAP, SCANNER

BASE = "http://127.0.0.1:4185"
OUTPUT = Path(os.environ.get("BUILDING_QA_OUTPUT", "/qa-output/building-effects"))
VIEWPORTS = ((375, 812), (390, 844), (1280, 800))
SCENES = tuple(name for name in ("greenhouse", "tavern", "fairground")
               if name in os.environ.get("BUILDING_QA_SCENES", "greenhouse,tavern,fairground").split(","))


def main() -> None:
    if not Path("/.dockerenv").exists():
        raise RuntimeError("Building QA may run only inside Docker")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    gap_results: list[dict] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=["--no-sandbox", "--mute-audio"],
            executable_path=os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH", "/usr/bin/chromium"))
        context = browser.new_context(viewport={"width": 390, "height": 844})
        # Block every remote request, including accidentally added production URLs.
        context.route("**/*", lambda route: route.continue_()
                      if route.request.url.startswith(BASE + "/")
                      or route.request.url.startswith(("data:", "blob:"))
                      else route.abort())
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))

        def post(path: str, data: dict | None = None) -> dict:
            response = context.request.post(BASE + path, data=data or {},
                headers={"X-Building-QA": "docker-only", "Origin": BASE,
                         "X-QW-Farm": "1", "X-Guest-CSRF": "1", "X-Mini-CSRF": "1"})
            assert response.ok, f"{path}: {response.status} {response.text()}"
            return response.json()

        post("/api/guest/start")
        post("/api/account/address-form?identity=guest", {"address_form": "n"})
        farm = post("/api/farm/v1/start?identity=guest")
        setup = post("/__qa/building-effects/setup", {"farm_id": farm["farm"]["id"]})
        for asset in ('village-building-effects.svg', 'village_building_effects_manifest.js'):
            response = context.request.get(BASE + '/app/farm/assets/' + asset)
            assert response.ok, f"Missing approved scene asset: {asset}"

        def load(theme: str) -> None:
            page.goto(BASE + "/app/farm?identity=guest", wait_until="networkidle")
            page.evaluate("m => localStorage.setItem('qw-farm.lighting',m)", theme)
            page.reload(wait_until="networkidle")
            page.wait_for_selector("#harvest-all", state="visible")
            page.evaluate("document.documentElement.style.setProperty('--qw-safe-top','48px')")

        def village() -> None:
            if page.locator('#village-scene').is_visible():
                return
            if page.locator("#farm-menu-button").is_visible():
                page.locator("#farm-menu-button").click()
            page.locator('#rail button[data-tab="village"]').click()

        def site(name: str) -> None:
            village()
            target = page.locator(f'[data-village-site="{name}"]')
            # Pan the actual scrollable map; clipped targets return when inside it.
            target.evaluate("n => n.scrollIntoView({block:'center',inline:'center'})")
            expect(target).to_be_visible()
            target.click()
            page.locator("#panel-content").wait_for(state="visible")
            title = {"greenhouse": "Оранжерея", "tavern": "Игривая кобыла",
                     "fairground": "Ярмарочное поле"}[name]
            expect(page.locator("#panel-head h2")).to_have_text(title, timeout=15000)
            page.wait_for_timeout(450)

        def click(key: str) -> None:
            page.wait_for_function("() => !document.body.classList.contains('is-saving')")
            target = page.locator(f'[data-village-focus="{key}"]')
            expect(target).to_be_enabled()
            with page.expect_response(lambda response:
                    "/api/farm/v1/commands" in response.url
                    and response.request.method == "POST") as pending:
                target.click()
            response = pending.value
            assert response.ok, f"{key}: {response.status} {response.text()}"
            page.wait_for_function("() => !document.body.classList.contains('is-saving')")
            page.wait_for_timeout(450)

        def capture(stem: str) -> None:
            page.wait_for_timeout(250)
            page.screenshot(path=str(OUTPUT / f"{stem}.png"), full_page=False,
                            animations="disabled")
            result = page.evaluate(SCANNER, [MIN_GAP, MIN_TAP])
            if result['issues']:
                result['controls'] = page.locator('button').evaluate_all("nodes => nodes.map(n => ({text:n.innerText,label:n.getAttribute('aria-label'),cls:n.className,rect:n.getBoundingClientRect().toJSON()})).filter(n=>n.rect.width&&n.rect.height)")
            gap_results.append({"screen": stem, **result})
            (OUTPUT / "gaps.json").write_text(json.dumps(gap_results,
                ensure_ascii=False, indent=2), encoding="utf-8")

        if os.environ.get("BUILDING_QA_CAPTURE_ONLY") != "1":
            load("day")
            site("fairground")
            page.get_by_role("button", name="К праздникам", exact=True).click()
            expect(page.get_by_text("Первый час ярмарки", exact=True)).to_be_visible()
            capture("festival-early-hour")
            load("day")
            site("greenhouse")
            click("greenhouse-vote")
            click("greenhouse-plant")
            expect(page.locator('[data-village-focus="greenhouse-plant"]')).to_have_count(0)
            post("/__qa/building-effects/advance", {"seconds": 172800})
            load("day")
            site("greenhouse")
            click("greenhouse-harvest")
            expect(page.locator('[data-village-focus="greenhouse-plant"]')).to_be_visible()
            load("day")
            site("tavern")
            click("tavern-order-0")
            click("tavern-order-1")
            click("tavern-favorite")
            expect(page.get_by_text("Сегодня ужин", exact=False)).to_be_visible()
            expect(page.locator('[data-favorite-dish]')).to_have_count(1)

        for width, height in VIEWPORTS:
            page.set_viewport_size({"width": width, "height": height})
            for theme in ("day", "night"):
                for building in SCENES:
                    load(theme)
                    site(building)
                    stem = f"{building}-{theme}-{width}x{height}"
                    if os.environ.get("BUILDING_QA_SCENE_ONLY") != "1":
                        capture(stem)
                        panel = page.locator("#panel-content")
                        panel.evaluate("n => n.scrollTop = n.scrollHeight")
                        capture(stem + "-lower")
                        panel.screenshot(path=str(OUTPUT / f"{stem}-closeup.png"),
                                         animations="disabled")
                    if building in ('tavern', 'fairground'):
                        page.locator('#panel-head .panel-close').click()
                        scene = page.locator(f'.village-build-base > [data-build="{building}"]')
                        scene.evaluate("n => n.scrollIntoView({block:'center',inline:'center'})")
                        for piece in ('tavern-honor-bench', 'tavern-favorite-menu', 'fairground-honor-flag',
                                      'fairground-kaya-podium', 'fairground-extra-stall-agata', 'fairground-extra-stall-sonya'):
                            expect(page.locator(f'[data-build="effect-{piece}"]')).to_have_count(1)
                        capture(stem + '-scene')
                        scene.screenshot(path=str(OUTPUT / f"{stem}-scene-closeup.png"), animations='disabled')
                        if building == 'fairground':
                            target = page.locator('[data-fair-stall="agata"]')
                            target.evaluate("n => n.scrollIntoView({block:'center',inline:'center'})")
                            target.click()
                if "fairground" in SCENES:
                    expect(page.get_by_text("Твоя скидка строителя:", exact=False)).to_be_visible()
                    capture(f"festival-{theme}-{width}x{height}")

        if os.environ.get("BUILDING_QA_BUDGET", "1") == "1":
            for remaining in (0, 1):
                post("/__qa/building-effects/budget", {"farm_id": setup["farm_id"], "remaining": remaining})
                sizes = VIEWPORTS if remaining == 0 else ((390, 844),)
                themes = ("day", "night") if remaining == 0 else ("day",)
                for width, height in sizes:
                    page.set_viewport_size({"width": width, "height": height})
                    for theme in themes:
                        load(theme)
                        for npc, game in (("Петух Олег", "oleg"), ("Медведь Пух", "ballista")):
                            if game not in os.environ.get('BUILDING_QA_BUDGET_GAMES', 'oleg,ballista,house,barn').split(','):
                                continue
                            village()
                            target = page.locator(f'[data-village-npc="{npc}"]')
                            target.evaluate("n => n.scrollIntoView({block:'center',inline:'center'})")
                            expect(target).to_be_visible()
                            target.click()
                            opener = page.locator('[data-open-oleg]' if game == 'oleg' else '[data-open-ballista]')
                            expect(opener).to_be_visible(timeout=15000)
                            opener.click()
                            budget = page.locator('.oleg-reward' if game == 'oleg' else '.ballista-rules')
                            expect(budget).to_contain_text(f"{remaining} из")
                            budget.scroll_into_view_if_needed()
                            rect = budget.bounding_box()
                            header_bottom = page.locator('.topbar').evaluate('n => n.getBoundingClientRect().bottom')
                            assert rect and rect['y'] >= header_bottom - .5 and rect['y'] + rect['height'] <= height + .5, f'{game}: budget text clipped: {rect}'
                            capture(f"budget-{remaining}-{game}-{theme}-{width}x{height}")
                            page.locator(f'.{game}-back').click()
                            expect(page.locator(f'#{game}-game-view')).to_be_hidden()
                            if page.locator('#panel-head .panel-close').is_visible():
                                page.locator('#panel-head .panel-close').click()
                        if page.locator('#village-scene').is_visible():
                            page.locator('.farm-card-door').click()
                        for game, title in (("house", "Дом Филиныча"), ("barn", "Склад")):
                            if game not in os.environ.get('BUILDING_QA_BUDGET_GAMES', 'oleg,ballista,house,barn').split(','):
                                continue
                            page.locator('#find-button').click()
                            page.locator('.object-card').filter(has=page.get_by_text(title, exact=True)).click()
                            budget = page.locator(f'.minigame-{game}').get_by_text('Общий денежный бонус', exact=False)
                            expect(budget).to_contain_text(f"{remaining} из")
                            budget.scroll_into_view_if_needed()
                            capture(f"budget-{remaining}-{game}-{theme}-{width}x{height}")
        assert not errors, errors
        assert not any(row["issues"] for row in gap_results), gap_results
        (OUTPUT / "result.json").write_text(json.dumps({"fixture": "isolated-docker",
            "viewports": VIEWPORTS, "errors": errors, "passed": True}, ensure_ascii=False), encoding="utf-8")
        print(f"PASS: {len(gap_results)} viewport scans, no issues; output={OUTPUT}", flush=True)
        context.close()
        browser.close()


if __name__ == "__main__":
    main()
