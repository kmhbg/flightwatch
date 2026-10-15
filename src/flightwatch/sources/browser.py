"""Shared headless Chromium for sources that only work in a real page: the computer's own Chrome/Chromium/Edge,
or a Chromium downloaded once into the cache folder (see system.browser_launch_args)."""
import contextlib

from playwright.sync_api import sync_playwright

from .. import system

UA = system.USER_AGENT


@contextlib.contextmanager
def page():
    launch = system.browser_launch_args()  # before sync_playwright(): it may set PLAYWRIGHT_BROWSERS_PATH
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, **launch)
        try:
            ctx = b.new_context(locale="sv-SE", viewport={"width": 1400, "height": 1400}, user_agent=UA)
            yield ctx.new_page()
        finally:
            b.close()


def click_if_present(pg, name, timeout=4000):
    try:
        pg.get_by_role("button", name=name).first.click(timeout=timeout)
        return True
    except Exception:
        return False
