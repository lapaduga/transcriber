"""Smoke tests for Транскриптор UI using Playwright.

Requires: pip install playwright pytest-playwright
Run: python -m pytest tests/test_smoke_playwright.py -v

The server must be running on localhost:3000 before these tests.
"""

import os

import pytest

SCREENSHOT_DIR = os.path.join(os.path.dirname(__file__), "..", "test-reports", "screenshots")

try:
    from playwright.sync_api import sync_playwright

    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False

pytestmark = pytest.mark.skipif(
    not HAS_PLAYWRIGHT,
    reason="playwright not installed: pip install playwright pytest-playwright",
)

BASE_URL = "http://localhost:3000"


@pytest.fixture(scope="module")
def browser_instance(request):
    headless = not request.config.getoption("--headed", default=False)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        yield browser
        browser.close()


@pytest.fixture()
def page(browser_instance):
    pg = browser_instance.new_page(viewport={"width": 1280, "height": 800})
    pg.route("**/fonts.googleapis.com/**", lambda route: route.abort())
    pg.route("**/fonts.gstatic.com/**", lambda route: route.abort())
    yield pg
    pg.close()


def _screenshot(page, name):
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)
    path = os.path.join(SCREENSHOT_DIR, f"{name}.png")
    page.screenshot(path=path, full_page=True, timeout=60000)
    return path


class TestSmokeS1LoadPage:
    def test_page_loads(self, page):
        page.goto(BASE_URL, wait_until="domcontentloaded")
        page.wait_for_selector(".sidebar-header h2", timeout=5000)
        _screenshot(page, "s1-load-page")

    def test_title_visible(self, page):
        page.goto(BASE_URL, wait_until="domcontentloaded")
        page.wait_for_selector(".sidebar-header h2", timeout=5000)
        assert page.locator(".sidebar-header h2").is_visible()

    def test_welcome_section(self, page):
        page.goto(BASE_URL, wait_until="domcontentloaded")
        page.wait_for_selector(".welcome", timeout=5000)
        assert page.locator(".welcome").is_visible()

    def test_welcome_icon(self, page):
        page.goto(BASE_URL, wait_until="domcontentloaded")
        page.wait_for_selector(".welcome-icon", timeout=5000)
        assert page.locator(".welcome-icon").is_visible()

    def test_status_indicator(self, page):
        page.goto(BASE_URL, wait_until="domcontentloaded")
        page.wait_for_selector(".status-text", timeout=5000)
        status = page.locator(".status-text")
        assert status.is_visible()
        text = status.text_content()
        assert text and len(text) > 0


class TestSmokeS2CreateChat:
    def test_new_chat_button(self, page):
        page.goto(BASE_URL, wait_until="domcontentloaded")
        page.wait_for_selector("#new-chat-btn", timeout=5000)
        assert page.locator("#new-chat-btn").is_visible()

    def test_create_chat_and_send(self, page):
        page.goto(BASE_URL, wait_until="domcontentloaded")
        page.wait_for_selector("#new-chat-btn", timeout=5000)
        page.locator("#new-chat-btn").click()
        page.wait_for_selector(".chat-item", timeout=5000)

        assert page.locator(".chat-item").count() >= 1

        input_el = page.locator("#message-input")
        input_el.fill("Привет, это тест")
        input_el.press("Enter")
        page.wait_for_selector(".message-user", timeout=5000)

        assert page.locator(".message-user").count() >= 1

        _screenshot(page, "s2-create-chat")

    def test_chat_appears_in_sidebar(self, page):
        page.goto(BASE_URL, wait_until="domcontentloaded")
        page.wait_for_selector("#new-chat-btn", timeout=5000)
        page.locator("#new-chat-btn").click()
        page.wait_for_selector(".chat-item", timeout=5000)

        chat_items = page.locator(".chat-item")
        assert chat_items.count() >= 1
        first_chat = chat_items.first
        assert first_chat.is_visible()


class TestSmokeS3DeleteChat:
    def test_delete_chat(self, page):
        page.goto(BASE_URL, wait_until="domcontentloaded")
        page.wait_for_selector("#new-chat-btn", timeout=5000)

        page.locator("#new-chat-btn").click()
        page.wait_for_selector(".chat-item", timeout=5000)

        initial_count = page.locator(".chat-item").count()

        delete_btn = page.locator(".chat-item-delete").first
        page.locator(".chat-item").first.hover()
        page.wait_for_timeout(200)
        delete_btn.click()
        page.wait_for_timeout(300)

        new_count = page.locator(".chat-item").count()
        assert new_count < initial_count

        _screenshot(page, "s3-delete-chat")


class TestSmokeS4UploadFile:
    def test_add_file_button_visible(self, page):
        page.goto(BASE_URL, wait_until="domcontentloaded")
        page.wait_for_selector("#add-video-btn", timeout=5000)
        assert page.locator("#add-video-btn").is_visible()

    def test_file_preview_shows_on_select(self, page):
        page.goto(BASE_URL, wait_until="domcontentloaded")
        page.wait_for_selector("#add-video-btn", timeout=5000)

        file_input = page.locator("#file-input")
        test_file = os.path.join(os.path.dirname(__file__), "..", "uploads")
        os.makedirs(test_file, exist_ok=True)
        test_audio = os.path.join(test_file, "_test_smoke.mp3")
        with open(test_audio, "wb") as f:
            f.write(b"\xff\xfb\x90\x00" + b"\x00" * 1024)

        file_input.set_input_files(test_audio)
        page.wait_for_timeout(300)

        preview = page.locator("#file-preview")
        assert preview.is_visible()

        file_name_el = page.locator("#file-name")
        assert "_test_smoke.mp3" in (file_name_el.text_content() or "")

        _screenshot(page, "s4-upload-file")

        os.remove(test_audio)

    def test_remove_file_clears_preview(self, page):
        page.goto(BASE_URL, wait_until="domcontentloaded")
        page.wait_for_selector("#add-video-btn", timeout=5000)

        file_input = page.locator("#file-input")
        test_file = os.path.join(os.path.dirname(__file__), "..", "uploads")
        os.makedirs(test_file, exist_ok=True)
        test_audio = os.path.join(test_file, "_test_smoke2.mp3")
        with open(test_audio, "wb") as f:
            f.write(b"\xff\xfb\x90\x00" + b"\x00" * 1024)

        file_input.set_input_files(test_audio)
        page.wait_for_timeout(300)
        assert page.locator("#file-preview").is_visible()

        page.locator("#file-remove").click()
        page.wait_for_timeout(300)
        assert not page.locator("#file-preview").is_visible()

        os.remove(test_audio)


class TestSmokeS5StatsPanel:
    def test_stats_panel_visible(self, page):
        page.goto(BASE_URL, wait_until="domcontentloaded")
        page.wait_for_selector(".stats-panel", timeout=5000)
        assert page.locator(".stats-panel").is_visible()

    def test_cpu_value_updates(self, page):
        page.goto(BASE_URL, wait_until="domcontentloaded")
        page.wait_for_selector("#cpu-val", timeout=5000)
        page.wait_for_timeout(4000)

        cpu_val = page.locator("#cpu-val")
        text = cpu_val.text_content()
        assert text and "%" in text
        assert "--" not in text

    def test_ram_value_updates(self, page):
        page.goto(BASE_URL, wait_until="domcontentloaded")
        page.wait_for_selector("#ram-val", timeout=5000)
        page.wait_for_timeout(4000)

        ram_val = page.locator("#ram-val")
        text = ram_val.text_content()
        assert text and "GB" in text
        assert "--" not in text

    def test_stats_screenshot(self, page):
        page.goto(BASE_URL, wait_until="domcontentloaded")
        page.wait_for_selector(".stats-panel", timeout=5000)
        page.wait_for_timeout(4000)
        _screenshot(page, "s5-stats-panel")
