import os
import json
import time
import hashlib
import tempfile
import threading
import pytest
from PIL import Image
from werkzeug.serving import make_server
from playwright.sync_api import sync_playwright, expect

from media_server import database as db_utils
from media_server import server as media_server_module
from media_server.settings import Settings, SettingsManager


@pytest.fixture(scope="module")
def app_server():
    temp_dir = tempfile.mkdtemp(prefix="pb_ui_test_")
    db_path = db_utils.get_db_path(temp_dir)
    thumbnail_dir = os.path.join(temp_dir, "thumbnails")
    uploads_dir = os.path.join(temp_dir, "uploads")
    os.makedirs(thumbnail_dir, exist_ok=True)
    os.makedirs(uploads_dir, exist_ok=True)

    db_utils.init_db(temp_dir)
    settings_file = os.path.join(temp_dir, "settings.json")
    settings_mgr = SettingsManager(settings_file)
    settings_mgr.write_settings(Settings(rescan_interval=0, tagging_model="Off", archival_backend="Off", archival_bucket=""))
    media_server_module.settings_manager = settings_mgr

    sha1 = hashlib.sha256(b"photo1.jpg").hexdigest()
    sha2 = hashlib.sha256(b"portrait.jpg").hexdigest()
    sha3 = hashlib.sha256(b"sample_video.mp4").hexdigest()
    sha4 = hashlib.sha256(b"old_pic.jpg").hexdigest()

    def create_dummy_img(name, sha, color, width=600, height=400):
        img_path = os.path.join(temp_dir, name)
        img = Image.new("RGB", (width, height), color=color)
        img.save(img_path, format="JPEG")
        thumb_filename = f"{sha}.jpg"
        thumb_path = os.path.join(thumbnail_dir, thumb_filename)
        thumb = Image.new("RGB", (200, 200), color=color)
        thumb.save(thumb_path, format="JPEG")
        return img_path, thumb_filename

    _, thumb1 = create_dummy_img("photo1.jpg", sha1, "blue", 1920, 1080)
    _, thumb2 = create_dummy_img("portrait.jpg", sha2, "red", 1080, 1920)
    _, thumb3 = create_dummy_img("sample_video.mp4", sha3, "purple", 1920, 1080)
    _, thumb4 = create_dummy_img("old_pic.jpg", sha4, "green", 1920, 1080)

    test_records = [
        {
            "sha256_hex": sha1,
            "filename": "photo1.jpg",
            "original_filename": "photo1.jpg",
            "file_path": "photo1.jpg",
            "last_modified": time.time(),
            "original_creation_date": 1715774400,  # May 15, 2024
            "thumbnail_file": thumb1,
            "width": 1920,
            "height": 1080,
            "city": "Paris",
            "country": "France",
            "mime_type": "image/jpeg",
            "filesize": 1024 * 500,
            "tags": json.dumps(["travel", "eiffel"]),
            "tagging_model": "Off",
        },
        {
            "sha256_hex": sha2,
            "filename": "portrait.jpg",
            "original_filename": "portrait.jpg",
            "file_path": "portrait.jpg",
            "last_modified": time.time(),
            "original_creation_date": 1715342400,  # May 10, 2024
            "thumbnail_file": thumb2,
            "width": 1080,
            "height": 1920,
            "city": "Tokyo",
            "country": "Japan",
            "mime_type": "image/jpeg",
            "filesize": 1024 * 600,
            "tags": json.dumps(["city", "night"]),
            "tagging_model": "Off",
        },
        {
            "sha256_hex": sha3,
            "filename": "sample_video.mp4",
            "original_filename": "sample_video.mp4",
            "file_path": "sample_video.mp4",
            "last_modified": time.time(),
            "original_creation_date": 1713614400,  # April 20, 2024
            "thumbnail_file": thumb3,
            "width": 1920,
            "height": 1080,
            "city": "Rome",
            "country": "Italy",
            "mime_type": "video/mp4",
            "filesize": 1024 * 1024 * 5,
            "tags": json.dumps(["colosseum"]),
            "tagging_model": "Off",
        },
        {
            "sha256_hex": sha4,
            "filename": "old_pic.jpg",
            "original_filename": "old_pic.jpg",
            "file_path": "old_pic.jpg",
            "last_modified": time.time(),
            "original_creation_date": 1701432000,  # Dec 1, 2023
            "thumbnail_file": thumb4,
            "width": 1920,
            "height": 1080,
            "city": "New York",
            "country": "USA",
            "mime_type": "image/jpeg",
            "filesize": 1024 * 400,
            "tags": json.dumps(["architecture"]),
            "tagging_model": "Off",
        },
    ]
    db_utils.batch_add_or_update_media_files(db_path, test_records)

    app = media_server_module.app
    app.config["STORAGE_DIR"] = temp_dir
    app.config["DATABASE_PATH"] = db_path
    app.config["THUMBNAIL_DIR"] = thumbnail_dir
    app.config["TESTING"] = True

    media_server_module.scan_status.update(
        is_scanning=False,
        initial_scan_in_progress=False,
        initial_scan_completed=True,
        phase="complete",
        percent=100.0,
    )

    server = make_server("127.0.0.1", 0, app)
    port = server.port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    base_url = f"http://127.0.0.1:{port}"
    yield base_url

    server.shutdown()


def test_gallery_initial_load_and_grouping(app_server):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto(app_server)

        # 1. App header & search bar
        expect(page.locator(".brand-title")).to_have_text("PhotoBackup")
        expect(page.locator("#searchInput")).to_be_visible()

        # 2. Month-year section dividers
        expect(page.locator("h2.month-year-divider-header:has-text('May 2024')")).to_be_visible()
        expect(page.locator("h2.month-year-divider-header:has-text('April 2024')")).to_be_visible()
        expect(page.locator("h2.month-year-divider-header:has-text('December 2023')")).to_be_visible()

        # 3. Media cards count
        cards = page.locator(".gallery-item")
        expect(cards).to_have_count(4)

        # 4. Video indicator badge
        video_card = page.locator(".gallery-item:has(span.card-title:has-text('sample_video.mp4'))")
        expect(video_card.locator(".video-indicator")).to_be_visible()

        # 5. Stats bar summary
        expect(page.locator("#statsCount")).to_contain_text("4 items")

        browser.close()


def test_photoswipe_lightbox_flow(app_server):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto(app_server)

        # Click photo1.jpg card link
        page.locator(".gallery-item a[data-filename='photo1.jpg']").click()

        # Wait for PhotoSwipe modal
        pswp = page.locator(".pswp")
        expect(pswp).to_be_visible()

        # Check custom caption overlay
        caption = page.locator(".pswp-custom-caption")
        expect(caption).to_be_visible()
        expect(caption).to_contain_text("photo1.jpg")
        expect(caption).to_contain_text("Paris, France")
        expect(caption).to_contain_text("#travel")

        # Navigate to next slide (portrait.jpg)
        page.locator(".pswp__button--arrow--next").click()
        page.wait_for_timeout(300)
        expect(caption).to_contain_text("portrait.jpg")
        expect(caption).to_contain_text("Tokyo, Japan")

        # Navigate to video slide (sample_video.mp4)
        page.locator(".pswp__button--arrow--next").click()
        page.wait_for_timeout(300)
        video_el = page.locator(".pswp-video-player").first
        expect(video_el).to_be_attached()
        expect(caption).to_contain_text("sample_video.mp4")
        expect(caption).to_contain_text("Rome, Italy")

        # Close lightbox via close button
        page.locator(".pswp__button--close").click()
        page.wait_for_timeout(300)
        expect(pswp).not_to_have_class("pswp--open")

        browser.close()


def test_mobile_portrait_responsiveness(app_server):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        # iPhone SE (375px)
        page = browser.new_page(viewport={"width": 375, "height": 667})
        page.goto(app_server)

        scroll_width = page.evaluate("document.documentElement.scrollWidth")
        client_width = page.evaluate("document.documentElement.clientWidth")
        assert scroll_width <= client_width, f"Horizontal overflow on 375px: {scroll_width} vs {client_width}"

        upload_btn = page.locator("#uploadButton")
        expect(upload_btn).to_be_visible()
        upload_text = page.locator("#uploadButton .upload-btn-text")
        expect(upload_text).to_be_hidden()

        search_input = page.locator("#searchInput")
        expect(search_input).to_be_visible()
        box = search_input.bounding_box()
        assert box and box["width"] >= 60, f"Search box too small: {box}"

        # Galaxy Z Fold outer (320px)
        page.set_viewport_size({"width": 320, "height": 600})
        page.wait_for_timeout(200)

        scroll_width_320 = page.evaluate("document.documentElement.scrollWidth")
        client_width_320 = page.evaluate("document.documentElement.clientWidth")
        assert scroll_width_320 <= client_width_320, f"Horizontal overflow on 320px: {scroll_width_320} vs {client_width_320}"
        expect(upload_btn).to_be_visible()
        expect(page.locator("#settingsButton")).to_be_visible()
        expect(page.locator("#themeToggle")).to_be_visible()

        # Mobile Drawer toggle & backdrop
        drawer_btn = page.locator("#sidebarToggleButton")
        expect(drawer_btn).to_be_visible()
        drawer_btn.click()

        sidebar = page.locator("#navigation-sidebar")
        expect(sidebar).to_have_class("timeline-sidebar expanded")
        backdrop = page.locator("#drawerBackdrop")
        expect(backdrop).to_have_class("drawer-backdrop active")

        backdrop.click(force=True)
        expect(sidebar).not_to_have_class("timeline-sidebar expanded")
        expect(backdrop).not_to_have_class("drawer-backdrop active")

        browser.close()


def test_theme_toggle_and_persistence(app_server):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto(app_server)

        page.locator("#themeToggle").click()
        theme = page.locator("html").get_attribute("data-theme")
        assert theme in ["light", "dark"]

        if theme != "light":
            page.locator("#themeToggle").click()

        expect(page.locator("html")).to_have_attribute("data-theme", "light")
        stored_theme = page.evaluate("localStorage.getItem('photobackup_theme')")
        assert stored_theme == "light"

        page.reload()
        expect(page.locator("html")).to_have_attribute("data-theme", "light")

        browser.close()


def test_search_filtering_and_clear(app_server):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto(app_server)

        search_input = page.locator("#searchInput")
        search_input.fill("Tokyo")
        page.wait_for_timeout(300)

        cards = page.locator(".gallery-item")
        expect(cards).to_have_count(1)
        expect(cards.first.locator(".card-title")).to_have_text("portrait.jpg")

        reset_btn = page.locator("#resetButton")
        expect(reset_btn).to_be_visible()
        reset_btn.click()
        page.wait_for_timeout(300)

        expect(page.locator(".gallery-item")).to_have_count(4)

        browser.close()


def test_media_type_filter_pills(app_server):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto(app_server)

        page.locator(".filter-pill[data-type='video']").click()
        expect(page.locator(".gallery-item")).to_have_count(1)
        expect(page.locator(".gallery-item .card-title")).to_have_text("sample_video.mp4")

        page.locator(".filter-pill[data-type='image']").click()
        expect(page.locator(".gallery-item")).to_have_count(3)

        page.locator(".filter-pill[data-type='all']").click()
        expect(page.locator(".gallery-item")).to_have_count(4)

        browser.close()


def test_settings_modal_test_connection_and_save(app_server):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto(app_server)

        page.locator("#settingsButton").click()
        overlay = page.locator("#settingsOverlay")
        expect(overlay).to_be_visible()

        page.locator("#testArchivalBtn").click()
        toast = page.locator(".toast.success")
        expect(toast).to_be_visible()

        page.locator("#rescanInterval").fill("300")
        page.locator("#saveSettings").click()

        page.wait_for_timeout(500)
        expect(overlay).to_be_hidden()

        browser.close()


def test_keyboard_shortcuts(app_server):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto(app_server)

        # 1. Press '/' to focus search
        page.keyboard.press("/")
        search_input = page.locator("#searchInput")
        assert page.evaluate("document.activeElement.id") == "searchInput"

        # 2. Press Escape to clear and blur
        search_input.fill("testing")
        page.keyboard.press("Escape")
        expect(search_input).to_have_value("")
        assert page.evaluate("document.activeElement.id") != "searchInput"

        # 3. Open settings modal, type '/' in input -> should not jump to search
        page.locator("#settingsButton").click()
        expect(page.locator("#settingsOverlay")).to_be_visible()
        bucket_input = page.locator("#archivalBucket")
        bucket_input.focus()
        bucket_input.type("my/bucket")
        assert page.evaluate("document.activeElement.id") == "archivalBucket"
        expect(bucket_input).to_have_value("my/bucket")

        # 4. Press Escape to close modal
        page.keyboard.press("Escape")
        expect(page.locator("#settingsOverlay")).to_be_hidden()

        browser.close()


def test_upload_dock_flow(app_server):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto(app_server)

        # Verify initial hidden state
        dock = page.locator("#uploadDock")
        expect(dock).to_be_hidden()

        # Trigger file input change with a mock file
        page.set_input_files("#fileInput", {
            "name": "new_upload.jpg",
            "mimeType": "image/jpeg",
            "buffer": b"fake_image_bytes",
        })

        # Dock should display progress
        expect(dock).to_be_visible()
        expect(page.locator("#uploadDockTitle")).to_contain_text("Uploaded")

        # Close dock
        page.locator("#uploadDockClose").click()
        expect(dock).to_be_hidden()

        browser.close()


def test_scanning_page_in_progress(app_server):
    media_server_module.scan_status.update(
        is_scanning=True,
        initial_scan_in_progress=True,
        initial_scan_completed=False,
        phase="processing",
        message="Scanning files 2/5",
        current=2,
        total=5,
        percent=40.0,
    )
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            page.goto(f"{app_server}/scanning")

            expect(page.locator("#scanTitle")).to_have_text("Scanning Media Library")
            expect(page.locator("#phaseLabel")).to_have_text("Indexing")
            expect(page.locator("#percentLabel")).to_have_text("40%")
            expect(page.locator("#progressFill")).to_be_visible()

            browser.close()
    finally:
        media_server_module.scan_status.update(
            is_scanning=False,
            initial_scan_in_progress=False,
            initial_scan_completed=True,
            phase="complete",
            percent=100.0,
        )


def test_gallery_empty_state_and_skeleton_loading(app_server):
    """Verify skeleton cards during loading and empty state when 0 items exist."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 800})

        # Intercept /api/media and /list to simulate 0 items
        page.route("**/api/media*", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"items": [], "total": 0, "has_more": false}'
        ))
        page.route("**/list", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body="{}"
        ))
        page.route("**/api/stats", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"total_count": 0, "image_count": 0, "video_count": 0, "total_size_bytes": 0}'
        ))

        page.goto(app_server)

        # Assert empty state after load completes
        empty_state = page.locator(".empty-state")
        expect(empty_state).to_be_visible()
        expect(empty_state.locator("h3")).to_have_text("No media found")
        expect(page.locator("#timelineLinks")).to_contain_text("No dates available")

        browser.close()


def test_photoswipe_video_lifecycle_and_resource_cleanup(app_server):
    """Verify video controls and resource destruction on modal close."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto(app_server)

        # Open lightbox at video card
        page.locator(".gallery-item a[data-filename='sample_video.mp4']").click()
        pswp = page.locator(".pswp")
        expect(pswp).to_be_visible()

        video = page.locator(".pswp-video-player").first
        expect(video).to_be_attached()
        expect(video).to_have_attribute("controls", "")
        expect(video).to_have_attribute("playsinline", "")

        # Close lightbox -> verify lightbox closes cleanly
        page.locator(".pswp__button--close").click()
        page.wait_for_timeout(300)
        expect(pswp).not_to_have_class("pswp--open")

        browser.close()


def test_timeline_navigation_virtualization_and_scrollspy(app_server):
    """Verify timeline anchor clicking, dynamic section mounting, and ScrollSpy activation."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto(app_server)

        # 1. Timeline list populated with months (at least 3 months)
        timeline_links = page.locator(".timeline-link")
        expect(timeline_links.first).to_be_visible()

        # 2. Click 'December 2023' timeline link -> smoothly scrolls & mounts
        dec_link = page.locator(".timeline-link:has-text('December 2023')")
        expect(dec_link).to_be_visible()
        dec_link.click()
        page.wait_for_timeout(500)

        # Section should be mounted and visible in viewport
        dec_section = page.locator("section[id*='December_2023']")
        expect(dec_section.locator(".gallery-item")).to_have_count(1)
        expect(dec_section.locator(".card-title")).to_have_text("old_pic.jpg")

        browser.close()


def test_manual_rescan_button_flow(app_server):
    """Verify manual library rescan trigger and feedback toast."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto(app_server)

        rescan_btn = page.locator("#rescanButton")
        expect(rescan_btn).to_be_visible()

        # Click rescan
        rescan_btn.click()

        # Check info toast
        toast = page.locator(".toast.info")
        expect(toast).to_be_visible()
        expect(toast).to_contain_text("Starting library rescan")

        browser.close()


def test_upload_statuses_duplicate_and_error_handling(app_server):
    """Verify upload dock duplicate handling and unsupported file skip toast."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto(app_server)

        # 1. Upload an unsupported file (.txt) alongside valid .jpg
        page.set_input_files("#fileInput", [
            {"name": "readme.txt", "mimeType": "text/plain", "buffer": b"test file"},
        ])

        # Assert skip toast appeared
        skip_toast = page.locator(".toast.info")
        expect(skip_toast).to_be_visible()
        expect(skip_toast).to_contain_text("Skipped 1 unsupported file(s)")

        browser.close()
