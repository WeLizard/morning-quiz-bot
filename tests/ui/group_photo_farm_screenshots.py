"""Capture current rehearsal farm screens for the Group Photo UI baseline.

This is a read-only visual smoke apart from creating one fresh test guest and
choosing its neutral pronoun. It never places, harvests, or submits farm commands.
"""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("TEMP", r"F:\Temp")
os.environ.setdefault("TMP", r"F:\Temp")
os.environ.setdefault("TMPDIR", r"F:\Temp")

from playwright.sync_api import sync_playwright  # noqa: E402


BASE_URL = "https://quiz.mr-lizard.ru"
OUTPUT = Path(r"F:\Temp\mqb-group-photo-20261115\farm-before")
FARM_URL = BASE_URL + "/app/farm?identity=guest"
CHROMIUM = Path(
    r"F:\Caches\ms-playwright\chromium-1248\chrome-win64\chrome.exe"
)
VIEWPORTS = ((360, 780), (384, 832))
THEMES = ("day", "night")


def screenshot_state(page, path: Path) -> None:
    page.wait_for_timeout(450)
    page.screenshot(path=str(path), full_page=False, animations="disabled")
    print(f"saved {path} ({page.viewport_size['width']}x{page.viewport_size['height']})")


def main() -> int:
    if not CHROMIUM.is_file():
        raise FileNotFoundError(f"Expected installed Chromium at {CHROMIUM}")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    page_errors: list[str] = []
    post_paths: list[str] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=str(CHROMIUM))
        context = browser.new_context(
            viewport={"width": 390, "height": 844}, device_scale_factor=1
        )
        page = context.new_page()
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.on(
            "request",
            lambda request: post_paths.append(request.url.split("?", 1)[0])
            if request.method == "POST"
            else None,
        )
        try:
            page.goto(BASE_URL + "/app", wait_until="networkidle", timeout=45000)
            page.locator("button.guest-entry").click(timeout=10000)
            page.get_by_role("button", name="Не указывать", exact=True).click(timeout=15000)
            farm_entry = page.get_by_role("button", name="На свою ферму", exact=True)
            farm_entry.wait_for(state="visible", timeout=15000)
            farm_entry.click()

            for width, height in VIEWPORTS:
                page.set_viewport_size({"width": width, "height": height})
                for theme in THEMES:
                    # Lighting is a browser-local preference; setting it does not
                    # change account, farm, or player data on the server.
                    page.evaluate(
                        "mode => localStorage.setItem('qw-farm.lighting', mode)", theme
                    )
                    page.goto(FARM_URL, wait_until="networkidle", timeout=45000)
                    page.wait_for_selector("#harvest-all", state="visible", timeout=30000)
                    page.wait_for_selector("#farm-menu-button", state="visible", timeout=30000)
                    page.wait_for_selector("#catalog-button", state="visible", timeout=30000)
                    page.evaluate(
                        "document.documentElement.style.setProperty('--qw-safe-top', '48px')"
                    )
                    page.wait_for_function(
                        "theme => document.documentElement.dataset.farmTheme === theme",
                        arg=theme,
                    )

                    stem = f"farm-{theme}-{width}x{height}"
                    screenshot_state(page, OUTPUT / f"{stem}-home.png")

                    page.locator("#farm-menu-button").click()
                    page.locator("#rail").wait_for(state="visible", timeout=8000)
                    screenshot_state(page, OUTPUT / f"{stem}-menu.png")
                    page.keyboard.press("Escape")
                    page.wait_for_function(
                        "document.getElementById('farm-menu-button')?.getAttribute('aria-expanded') === 'false'"
                    )

                    page.locator("#catalog-button").click()
                    page.locator("#panel").wait_for(state="visible", timeout=8000)
                    screenshot_state(page, OUTPUT / f"{stem}-catalog-all.png")
                    page.keyboard.press("Escape")

            farm_commands = [path for path in post_paths if "/api/farm/v1/commands" in path]
            if farm_commands:
                raise RuntimeError(f"Unexpected farm command POSTs: {farm_commands}")
            if page_errors:
                raise RuntimeError(f"Browser page errors: {page_errors}")
            print(f"PASS: 12 rehearsal farm screenshots; no farm commands; output={OUTPUT}")
            print(f"POST endpoint paths observed: {post_paths}")
            return 0
        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    raise SystemExit(main())
