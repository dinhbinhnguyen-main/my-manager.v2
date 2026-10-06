"""Facebook Buy/Sell Group Listing & Top-Group Cross-Sharing Action.
Ported with 100% faithful logic from phonemanager.v1 / Redroid container automation.
"""

import os
import re
import sys
import json
import time
import shutil
import logging
import subprocess
import traceback
import xml.etree.ElementTree as ET
from random import randint
from pathlib import Path
from typing import List, Dict, Any, Optional, Set

from src.core.models import Account, AccountStatus
from src.db.repository import AccountRepository
from src.automation.base_automator import BaseAutomator
from src.automation.checkpoint_handler import CheckpointDetector, check_and_handle_identity_confirmation
from src.services.v1_bridge import V1DatabaseBridge
from src.ai.gemini_service import GeminiService

logger = logging.getLogger(__name__)

def dump_error_view(bot: BaseAutomator, account_uid: Optional[str] = None, step_name: str = "unknown_step"):
    """
    Automatically dumps UI hierarchy (XML, JSON, Screenshot) on error or missing elements.
    Saved to: tests/dumps/errors/{safe_uid}_{safe_step}_{timestamp}/
    Also mirrors latest error dump to tests/dumps/latest/
    """
    try:
        from tests.dump_view import parse_hierarchy_node

        uid = str(account_uid or getattr(bot, "account_uid", None) or getattr(bot, "device_id", None) or getattr(bot, "adb_port", "device"))
        safe_uid = re.sub(r'[^\w\-_\.]', '_', uid)
        safe_step = re.sub(r'[^\w\-_\.]', '_', str(step_name))
        timestamp = time.strftime("%Y%m%d_%H%M%S")

        output_dir = Path("tests/dumps/errors") / f"{safe_uid}_{safe_step}"
        output_dir.mkdir(parents=True, exist_ok=True)

        latest_dir = Path("tests/dumps/latest")
        latest_dir.mkdir(parents=True, exist_ok=True)

        bot.log(f"📸 [ERROR DUMP] Missing element / error at [{step_name}]. Auto-dumping UI to {output_dir}...")

        if not bot.d:
            bot.log("⚠️ UIAutomator2 device is not connected, cannot dump screen.")
            return

        xml_dump = bot.d.dump_hierarchy()
        xml_file = output_dir / "dumped_view.xml"
        json_file = output_dir / "dumped_view.json"
        png_file = output_dir / "dumped_screen.png"

        with open(xml_file, "w", encoding="utf-8") as f:
            f.write(xml_dump)

        root = ET.fromstring(xml_dump)
        elements = parse_hierarchy_node(root)

        app_info = {}
        try:
            app_info = bot.d.app_current()
        except Exception:
            pass

        with open(json_file, "w", encoding="utf-8") as f:
            json.dump({
                "device_id": getattr(bot, "device_id", None),
                "account_uid": uid,
                "failed_step": step_name,
                "timestamp": timestamp,
                "current_app": app_info,
                "total_elements": len(elements),
                "elements": elements
            }, f, ensure_ascii=False, indent=2)

        try:
            bot.d.screenshot(str(png_file))
        except Exception as se:
            bot.log(f"⚠️ Could not capture screenshot: {se}")

        # Mirror to latest/
        try:
            shutil.copy2(xml_file, latest_dir / "dumped_view.xml")
            shutil.copy2(json_file, latest_dir / "dumped_view.json")
            if png_file.exists():
                shutil.copy2(png_file, latest_dir / "dumped_screen.png")
        except Exception:
            pass

        bot.log(f"💾 Successfully saved UI error diagnostics to: {output_dir}")
    except Exception as dump_err:
        logger.error(f"Error dumping diagnostics ({account_uid} - {step_name}): {dump_err}")


def dump_step_view(bot: BaseAutomator, tag: str = "after_step"):
    """Dumps UI hierarchy (XML, JSON, Screenshot) to tests/dumps/ for step analysis."""
    dump_error_view(bot, step_name=tag)


def _extract_group_id(raw_input: str) -> str:
    """
    Extracts Group ID from URL or string.
    Examples:
    - 'https://www.facebook.com/groups/5857815244230418' -> '5857815244230418'
    - 'https://facebook.com/groups/muabannhadatdalat/?ref=share' -> 'muabannhadatdalat'
    - '5857815244230418' -> '5857815244230418'
    """
    raw_input = str(raw_input).strip()
    match = re.search(r'groups/([^/?]+)', raw_input)
    if match:
        return match.group(1)
    return raw_input


def _parse_member_count(desc: str) -> int:
    """
    Parses group member count from contentDescription or text strings.
    Supports both Vietnamese and English patterns:
    - 'Nhóm Công khai • 81.3K thành viên' -> 81300
    - 'Private group • 1.2M members' -> 1200000
    - 'Nhóm công khai · 500 thành viên' -> 500
    """
    if not desc:
        return 0
    match = re.search(r'([\d\.,]+)\s*([KMkmTrtrTt]?)\s*(?:members|thành viên|người tham gia)', desc, re.IGNORECASE)
    if not match:
        return 0

    num_str, multiplier = match.groups()
    num_str = num_str.replace(',', '.')
    try:
        num = float(num_str)
        multiplier_upper = multiplier.upper()
        if multiplier_upper == 'K':
            num *= 1_000
        elif multiplier_upper in ('M', 'TR', 'T'):
            num *= 1_000_000
        return int(num)
    except Exception:
        return 0


# ==============================================================================
# STEP 1: OPEN GROUP VIA DEEPLINK
# ==============================================================================

def open_facebook_group(bot: BaseAutomator, raw_group: str, timeout: int = 15) -> bool:
    """
    STEP 1:
    - Refresh state: Return to Home and close Facebook if already open.
    - Extract Group ID from URL/UID.
    - Launch Facebook app and navigate directly via Deep Link fb://group/<id>.
    - Wait logic: Wait for group page UI to finish loading.
    """
    group_id = _extract_group_id(raw_group)
    if not group_id:
        raise ValueError(f"Unable to extract Group ID from: '{raw_group}'")

    bot.log("🏠 [Init] Resetting device to Home screen and refreshing Facebook state...")
    try:
        if bot.d:
            bot.d.app_stop("com.facebook.katana")
            bot.d.press("home")
        bot.smart_sleep(1.0)
    except Exception as e:
        logger.debug(f"Failed to stop app or press home: {e}")

    bot.log(f"🚀 [Step 1] Opening Facebook and navigating to Group: {group_id}...")
    deeplink = f"fb://group/{group_id}"
    if hasattr(bot, "launch_app"):
        bot.launch_app("com.facebook.katana", deeplink=deeplink)
    elif hasattr(bot, "launch"):
        bot.launch(deeplink=deeplink)
    else:
        bot.d.app_start("com.facebook.katana")

    bot.log("⏳ Waiting for group page to load...")
    start_time = time.time()

    while time.time() - start_time < timeout:
        if not bot.d:
            break
        current_app = bot.d.app_current()
        if current_app.get("package") == "com.facebook.katana":
            selling_btn = bot.get_button_by_text("what are you selling", timeout=1)
            item_btn = bot.get_button_by_text("item", timeout=1)
            ban_btn = bot.get_button_by_text("bạn đang bán gì", timeout=1)
            public_badge = bot.get_button_by_text("public group", timeout=1)
            joined_btn = bot.get_button_by_text("joined", timeout=1)

            if (
                (selling_btn and selling_btn.exists) or 
                (item_btn and item_btn.exists) or 
                (ban_btn and ban_btn.exists) or 
                (public_badge and public_badge.exists) or 
                (joined_btn and joined_btn.exists)
            ):
                bot.log(f"✔️ Successfully accessed Group {group_id}!")
                bot.smart_sleep(1.5)
                return True

        bot.smart_sleep(1.0)

    bot.log(f"⚠️ Group {group_id} did not confirm loaded within {timeout}s.")
    return True


# ==============================================================================
# STEP 2: CLICK 'WHAT ARE YOU SELLING?' / 'BẠN ĐANG BÁN GÌ?'
# ==============================================================================

def click_what_are_you_selling(bot: BaseAutomator, timeout: int = 20) -> bool:
    """
    STEP 2:
    - Search and click 'What are you selling?' (or 'Bạn đang bán gì?', 'Sell something', 'Item', 'Tạo bài niêm yết').
    - Tries current view, and if not found, scrolls down up to 3 times.
    - If Facebook displays intermediate category layout (e.g. 'Items' / 'Mặt hàng'), click 'Items'.
    - Wait logic: Wait for Listing Composer form to load.
    """
    bot.log("🔍 [Step 2] Searching for 'What are you selling?' button (with up to 3 scroll attempts)...")

    sell_keywords = [
        "what are you selling",
        "bạn đang bán gì",
        "sell something",
        "bán gì đó",
        "tạo bài niêm yết",
        "item"
    ]

    sell_patterns = [
        r"(?i).*What are you selling.*",
        r"(?i).*Bạn đang bán gì.*",
        r"(?i).*Sell something.*",
        r"(?i).*Bán gì đó.*",
        r"(?i).*Tạo bài niêm yết.*"
    ]

    def _try_click_sell() -> bool:
        # 1. Direct regex match
        for p in sell_patterns:
            if bot.d:
                btn_txt = bot.d(textMatches=p)
                if btn_txt.exists:
                    bot.log(f"👆 Found and clicking sell element (text: {p})...")
                    btn_txt.click()
                    return True
                btn_desc = bot.d(descriptionMatches=p)
                if btn_desc.exists:
                    bot.log(f"👆 Found and clicking sell element (desc: {p})...")
                    btn_desc.click()
                    return True

        # 2. Keyword button / widget search
        for kw in sell_keywords:
            btn = bot.get_button_by_text(kw, timeout=1)
            if btn and btn.exists:
                bot.log(f"👆 Found and clicking '{kw}' button...")
                btn.click_exists(timeout=2)
                return True

            wg = bot.get_widget_by_text("android.view.ViewGroup", kw, timeout=0.5)
            if wg and wg.exists:
                bot.log(f"👆 Found ViewGroup '{kw}', clicking...")
                wg.click()
                return True

        return False

    clicked = False
    # Check initial screen
    if _try_click_sell():
        clicked = True

    # If not found, scroll down (swipe up) up to 3 times
    if not clicked:
        for scroll_idx in range(3):
            bot.log(f"📜 [Scroll {scroll_idx + 1}/3] Scrolling down to find 'What are you selling?' button...")
            bot.swipe_up(scale=0.35)
            bot.smart_sleep(1.2)
            if _try_click_sell():
                clicked = True
                break

    if not clicked:
        raise Exception("❌ Could not find 'What are you selling?' button on group page after 3 scrolls.")

    bot.log("⏳ Waiting for listing form to open...")
    start_time = time.time()
    form_opened = False
    while time.time() - start_time < timeout:
        # Check if draft discard prompt appeared ("Discard draft?" / "Bỏ bản nháp?" / "Bỏ bài viết")
        for discard_kw in ["discard", "bỏ bài viết", "bỏ bản nháp"]:
            discard_btn = bot.get_button_by_text(discard_kw, timeout=0.3)
            if discard_btn and discard_btn.exists:
                bot.log(f"🧹 Found draft discard prompt ('{discard_kw}'), clicking to reset form...")
                discard_btn.click_exists(timeout=2)
                bot.smart_sleep(1.0)
                break

        # Check if intermediate layout (category selection) is shown: "Items" / "Mặt hàng"
        for item_kw in ["items", "mặt hàng"]:
            # 1. Button or TextView matching text / content-desc (e.g. "Items Furniture, clothing, toys, etc.")
            item_btn = bot.get_button_by_text(item_kw, timeout=0.5)
            if item_btn and item_btn.exists:
                bot.log(f"👆 Found listing category button '{item_kw}', clicking...")
                item_btn.click_exists(timeout=2)
                bot.smart_sleep(1.5)
                break

            # 2. ViewGroup with text / content-desc (e.g. ViewGroup with text="Items")
            item_wg = bot.get_widget_by_text("android.view.ViewGroup", item_kw, timeout=0.5)
            if item_wg and item_wg.exists:
                bot.log(f"👆 Found listing category ViewGroup '{item_kw}', clicking...")
                item_wg.click()
                bot.smart_sleep(1.5)
                break

            # 3. Direct device selector fallback
            if bot.d:
                item_desc = bot.d(descriptionMatches=f"(?i).*{item_kw}.*")
                if item_desc.exists:
                    bot.log(f"👆 Found category element via content-desc '{item_kw}', clicking...")
                    item_desc.click()
                    bot.smart_sleep(1.5)
                    break
                item_txt = bot.d(textMatches=f"(?i)^{item_kw}$")
                if item_txt.exists:
                    bot.log(f"👆 Found category element via text '{item_kw}', clicking...")
                    item_txt.click()
                    bot.smart_sleep(1.5)
                    break

        # Check if Listing Form is loaded
        add_photos = bot.get_button_by_text("add photos", timeout=1)
        them_anh = bot.get_button_by_text("thêm ảnh", timeout=1)
        title_field = bot.get_widget_by_text("android.view.ViewGroup", "composer_v3_title", timeout=1)
        next_btn = bot.get_button_by_text("next", timeout=1)

        if (
            (add_photos and add_photos.exists) or 
            (them_anh and them_anh.exists) or 
            (title_field and title_field.exists) or 
            (next_btn and next_btn.exists)
        ):
            bot.log("✔️ Successfully opened Listing Form!")
            bot.smart_sleep(1.5)
            form_opened = True
            return True

        # Check for Confirm Identity screen blocking listing form
        if check_and_handle_identity_confirmation(bot):
            raise Exception("CONFIRM_IDENTITY: Account requires identity verification.")

        bot.smart_sleep(1.0)

    # Final check before failing
    if check_and_handle_identity_confirmation(bot):
        raise Exception("CONFIRM_IDENTITY: Account requires identity verification.")

    if not form_opened:
        raise Exception("❌ Listing form did not open after clicking 'What are you selling?'.")

    bot.log("✔️ Completed Step 2 (Clicked sell button).")
    return True


# ==============================================================================
# STEP 3: CLICK 'ADD PHOTOS' AND SELECT PHOTOS
# ==============================================================================

def click_add_photos(bot: BaseAutomator, photo_num: int = 1, timeout: int = 15, max_retries: int = 2) -> bool:
    """
    STEP 3:
    - Search and click 'Add photos' (or 'Thêm ảnh', 'Thêm hình ảnh', etc.).
    - Wait logic: Wait for Camera Roll / Photo Gallery to appear.
    - Identify photo checkboxes/grid items (NEVER matching arbitrary ImageView).
    - Select corresponding number of photos (photo_num) in reverse order (bottom up).
    - Click 'Next' / 'Done' to confirm photo selection.
    """
    bot.log("🖼️ [Step 3] Finding and clicking 'Add photos' button...")

    # Pre-grant storage permissions via ADB to avoid React Native permission SecurityException
    try:
        dev_serial = getattr(bot, "device_id", None)
        if hasattr(bot, "adb_client") and bot.adb_client and getattr(bot.adb_client, "target", None):
            dev_serial = bot.adb_client.target

        if dev_serial:
            subprocess.run(["adb", "-s", dev_serial, "shell", "pm", "grant", "com.facebook.katana", "android.permission.READ_EXTERNAL_STORAGE"], capture_output=True)
            subprocess.run(["adb", "-s", dev_serial, "shell", "pm", "grant", "com.facebook.katana", "android.permission.READ_MEDIA_IMAGES"], capture_output=True)
    except Exception as pe:
        logger.debug(f"Pre-grant permissions error: {pe}")

    def _trigger_add_photos_button() -> bool:
        """Finds and clicks 'Add photos' / 'Thêm ảnh' via multiple selectors."""
        add_photo_keywords = [
            "add photos", "thêm ảnh", "add photo", "thêm hình ảnh",
            "thêm ảnh/video", "add photos/videos", "ảnh/video", "photo/video"
        ]

        # 1. Check by resourceId
        if bot.d:
            res_elem = bot.d(resourceIdMatches=r"(?i).*(add_photos|composer_add_photos|marketplace_add_photos).*")
            if res_elem.exists:
                bot.log("👆 Found 'Add photos' by resourceId. Clicking...")
                res_elem.click()
                return True

        # 2. Check by keyword button / widget / text / description
        for kw in add_photo_keywords:
            btn = bot.get_button_by_text(kw, timeout=1.5)
            if btn and btn.exists:
                bot.log(f"👆 Clicking '{kw}' button...")
                btn.click_exists(timeout=2)
                return True
            wg = bot.get_widget_by_text("android.view.ViewGroup", kw, timeout=1.0)
            if wg and wg.exists:
                bot.log(f"👆 Clicking ViewGroup '{kw}'...")
                wg.click()
                return True
            if bot.d:
                u2_desc = bot.d(descriptionMatches=f"(?i).*{kw}.*")
                if u2_desc.exists:
                    bot.log(f"👆 Clicking description '{kw}'...")
                    u2_desc.click()
                    return True
                u2_text = bot.d(textMatches=f"(?i).*{kw}.*")
                if u2_text.exists:
                    bot.log(f"👆 Clicking text '{kw}'...")
                    u2_text.click()
                    return True
        return False

    max_open_attempts = max(max_retries, 20)
    gallery_ready = False

    for attempt in range(max_open_attempts):
        bot.log(f"🖼️ [Step 3] Finding and clicking 'Add photos' button (Attempt {attempt + 1}/{max_open_attempts})...")

        # Check if already on the Retry screen before clicking
        retry_btn = None
        if bot.d:
            retry_btn = bot.d(textMatches="(?i)^retry$|^thử lại$")
            if not retry_btn.exists:
                retry_btn = bot.get_button_by_text("retry", timeout=1) or bot.get_button_by_text("thử lại", timeout=1)

        if retry_btn and retry_btn.exists:
            bot.log("⚠️ Found 'Retry' button on UI (Error screen). Clicking 'Retry' to return to listing form...")
            retry_btn.click_exists(timeout=3)
            bot.smart_sleep(2.0)

        # 1. Click 'Add photos'
        clicked = _trigger_add_photos_button()
        if not clicked:
            bot.log(f"⚠️ Could not find 'Add photos' button on attempt {attempt + 1}. Pressing 'back' and re-clicking 'What are you selling? / Sell something'...")
            if bot.d:
                bot.d.press("back")
                bot.smart_sleep(1.5)
                # Check and handle discard draft popup if any
                for discard_kw in ["discard", "bỏ bài viết", "bỏ bản nháp", "bỏ"]:
                    discard_btn = bot.get_button_by_text(discard_kw, timeout=0.8)
                    if discard_btn and discard_btn.exists:
                        bot.log(f"🧹 Found discard dialog ('{discard_kw}'), clicking to confirm...")
                        discard_btn.click_exists(timeout=2)
                        bot.smart_sleep(1.0)
                        break
                try:
                    bot.log("🔄 Re-clicking 'What are you selling? / Sell something' button to reload listing form...")
                    click_what_are_you_selling(bot, timeout=15)
                except Exception as re_err:
                    bot.log(f"⚠️ Error re-clicking sell button: {re_err}")
            bot.smart_sleep(1.5)
            continue

        # 2. Wait and inspect screen transition
        bot.smart_sleep(2.0)

        # CASE A: Screen displays 'An unexpected error occurred' with 'Retry' button (port_5562_retry)
        err_screen = False
        if bot.d:
            err_retry = bot.d(textMatches="(?i)^retry$|^thử lại$")
            err_text = bot.d(textMatches="(?i).*unexpected error.*|.*đã xảy ra lỗi.*")
            if err_retry.exists or err_text.exists:
                err_screen = True
                bot.log("⚠️ Detected 'An unexpected error occurred' (Retry screen). Clicking 'Retry'...")
                if err_retry.exists:
                    err_retry.click()
                else:
                    r_btn = bot.get_button_by_text("retry", timeout=2) or bot.get_button_by_text("thử lại", timeout=2)
                    if r_btn and r_btn.exists:
                        r_btn.click()
                bot.smart_sleep(2.0)
                bot.log("🔄 Returned to main listing form (port_5562_main). Re-clicking 'Add photos'...")
                # Loop will re-attempt clicking 'Add photos' on main listing form
                continue

        # CASE B: Camera Roll / Gallery opened successfully
        if bot.d:
            cam_box = bot.d(descriptionMatches=r"(?i).*Photo.*taken on.*|.*Photo taken on.*|.*Ảnh.*chụp.*")
            if not cam_box.exists:
                cam_box = bot.d(descriptionMatches=r"(?i)^Photo, item \d+.*")
            if not cam_box.exists:
                cam_box = bot.d(className="android.widget.Button", descriptionMatches=r"(?i)^Photo.*|^Ảnh.*")
            if not cam_box.exists:
                cam_box = bot.d(resourceIdMatches=".*camera_roll_image.*")
            if not cam_box.exists:
                cam_box = bot.d(className="android.widget.CheckBox")
            grid = bot.get_elements_by_widget("android.widget.GridView", timeout=1) or (bot.d(className="android.widget.GridView") if bot.d else None)

            if (cam_box.exists and cam_box.count > 0) or (grid and grid.exists):
                bot.log("✔️ Gallery / Camera Roll is now open and ready!")
                gallery_ready = True
                break

        # Check if still stuck on main listing form
        main_form_check = bot.d(descriptionMatches="(?i).*add photos.*").exists or bot.d(textMatches="(?i).*add photos.*").exists
        if main_form_check:
            bot.log("⚠️ Still on main listing form, re-trying 'Add photos' click...")
            bot.smart_sleep(1.0)
            continue
        else:
            gallery_ready = True
            break

    if not gallery_ready:
        bot.log("❌ Could not open gallery / camera roll after retries.")
        raise Exception("❌ Could not open Camera Roll / Gallery.")

    bot.log("⏳ Waiting for Camera Roll to appear...")
    start_time = time.time()
    photos_found = False
    selected_count = 0

    def _is_back_on_listing_form() -> bool:
        if not bot.d:
            return False
        return (
            bot.d(resourceId="composer_v3_title").exists or
            bot.d(descriptionMatches=r"(?i)^Title.*").exists or
            bot.d(textMatches=r"(?i)^Title.*|^Tiêu đề.*").exists or
            bot.d(resourceId="composer_v3_price").exists or
            bot.d(textMatches=r"(?i)^Price.*|^Giá.*").exists or
            bot.d(textMatches=r"(?i).*What are you selling.*|.*Bạn đang bán gì.*").exists
        )

    def _click_next_confirm() -> bool:
        bot.smart_sleep(1.0)
        # Check if already navigated back to listing form directly (e.g. Single-select photo mode)
        if _is_back_on_listing_form():
            bot.log("ℹ️ Already returned to main listing form after photo selection.")
            return True

        # 1. By resourceId
        next_btn = bot.d(resourceId="marketplace_camera_roll_android_next_button")
        if next_btn.exists:
            bot.log("👆 Clicking 'Next' button (via resourceId) to confirm photos...")
            next_btn.click_exists(timeout=5)
            bot.smart_sleep(2.0)
            return True

        # 2. By description
        next_btn = bot.d(descriptionMatches=r"(?i)^(Next|Tiếp|Done|Xong|Add|Thêm|Add\s*\(\d+\)|Thêm\s*\(\d+\))$")
        if next_btn.exists:
            bot.log("👆 Clicking Next / Confirm button (via description)...")
            next_btn.click_exists(timeout=5)
            bot.smart_sleep(2.0)
            return True

        # 3. By button text / widget
        for kw in ["next", "tiếp", "done", "xong", "add", "thêm"]:
            btn = bot.get_button_by_text(kw, timeout=1)
            if btn and btn.exists:
                bot.log(f"👆 Clicking '{kw}' button to confirm photos...")
                btn.click_exists(timeout=5)
                bot.smart_sleep(2.0)
                return True
            btn_txt = bot.d(textMatches=rf"(?i)^{kw}(\s*\(\d+\))?$")
            if btn_txt.exists:
                bot.log(f"👆 Clicking text '{kw}' to confirm photos...")
                btn_txt.click()
                bot.smart_sleep(2.0)
                return True

        # Final check if back on main form
        if _is_back_on_listing_form():
            bot.log("ℹ️ Confirmed return to listing form.")
            return True
        return False

    def _has_selected_photos() -> bool:
        if not bot.d:
            return False
        # Check 1: CheckBox with selected=True or checked=True
        if bot.d(className="android.widget.CheckBox", selected=True).exists:
            return True
        if bot.d(className="android.widget.CheckBox", checked=True).exists:
            return True
        # Check 2: resourceId camera_roll_image with selected=True or checked=True
        if bot.d(resourceIdMatches=".*camera_roll_image.*", selected=True).exists:
            return True
        if bot.d(resourceIdMatches=".*camera_roll_image.*", checked=True).exists:
            return True
        # Check 3: Check info of any camera roll images
        cam_imgs = bot.d(resourceIdMatches=".*camera_roll_image.*")
        if cam_imgs.exists and cam_imgs.count > 0:
            for idx in range(cam_imgs.count):
                try:
                    info = cam_imgs[idx].info
                    if info.get("selected") or info.get("checked"):
                        return True
                except Exception:
                    pass
        # Check 4: ImageView with selected=True
        if bot.d(className="android.widget.ImageView", selected=True).exists:
            return True
        # Check 5: Button with selected=True or checked=True
        if bot.d(className="android.widget.Button", descriptionMatches=r"(?i).*Photo.*|.*Ảnh.*", selected=True).exists:
            return True
        if bot.d(className="android.widget.Button", descriptionMatches=r"(?i).*Photo.*|.*Ảnh.*", checked=True).exists:
            return True
        # Check 6: Check if selection badge (e.g. text='1') exists inside camera roll
        if bot.d(className="android.view.ViewGroup", textMatches=r"^[1-9]\d*$", selected=True).exists:
            return True
        if bot.d(className="android.view.ViewGroup", textMatches=r"^[1-9]\d*$").exists:
            try:
                badge = bot.d(className="android.view.ViewGroup", textMatches=r"^[1-9]\d*$")
                b = badge.info.get("bounds", {})
                if b and (b.get("bottom", 0) - b.get("top", 0) < 150):
                    return True
            except Exception:
                pass
        return False

    def _ensure_select_multiple_mode() -> bool:
        if not bot.d:
            return False
        try:
            # 1. Text match
            multi_text = bot.d(textMatches=r"(?i).*(select multiple|chọn nhiều|chọn nhiều ảnh|chọn nhiều mục).*")
            if multi_text.exists:
                info = multi_text.info
                if not info.get("selected") and not info.get("checked"):
                    bot.log(f"👆 Found 'Select multiple' button (text='{info.get('text', '')}'). Clicking to enable multi-selection...")
                    multi_text.click_exists(timeout=2)
                    bot.smart_sleep(1.0)
                    return True
                else:
                    bot.log("ℹ️ 'Select multiple' mode is already active.")
                    return True

            # 2. Description match
            multi_desc = bot.d(descriptionMatches=r"(?i).*(select multiple|chọn nhiều|chọn nhiều ảnh|chọn nhiều mục).*")
            if multi_desc.exists:
                info = multi_desc.info
                if not info.get("selected") and not info.get("checked"):
                    bot.log(f"👆 Found 'Select multiple' button (desc='{info.get('contentDescription', '')}'). Clicking to enable multi-selection...")
                    multi_desc.click_exists(timeout=2)
                    bot.smart_sleep(1.0)
                    return True
                else:
                    bot.log("ℹ️ 'Select multiple' mode is already active.")
                    return True

            # 3. Resource ID match
            multi_id = bot.d(resourceIdMatches=r"(?i).*(select_multiple|multi_select|multiple_selection).*")
            if multi_id.exists:
                bot.log("👆 Found 'Select multiple' button by resourceId. Clicking to enable multi-selection...")
                multi_id.click_exists(timeout=2)
                bot.smart_sleep(1.0)
                return True

            # 4. Helper get_button_by_text
            for kw in ["select multiple", "chọn nhiều", "chọn nhiều ảnh", "chọn nhiều mục"]:
                b = bot.get_button_by_text(kw, timeout=1)
                if b and b.exists:
                    bot.log(f"👆 Clicking '{kw}' button...")
                    b.click_exists(timeout=2)
                    bot.smart_sleep(1.0)
                    return True
        except Exception as ex:
            logger.debug(f"Error checking 'Select multiple' button: {ex}")
        return False

    while time.time() - start_time < timeout:
        if not bot.d:
            break

        # Check and activate 'Select multiple' mode if button is present

        # Check and activate 'Select multiple' mode if button is present
        _ensure_select_multiple_mode()

        # 1. Try detecting standard Katana camera roll photos (ViewGroup / CheckBox / Button with description)
        camera_images = bot.d(className="android.view.ViewGroup", clickable=True, descriptionMatches=r"(?i).*Photo.*taken on.*|.*Photo taken on.*|.*Ảnh.*chụp.*")
        if not camera_images.exists or camera_images.count == 0:
            camera_images = bot.d(descriptionMatches=r"(?i).*Photo.*taken on.*|.*Photo taken on.*|.*Ảnh.*chụp.*")
        if not camera_images.exists or camera_images.count == 0:
            camera_images = bot.d(descriptionMatches=r"(?i)^Photo, item \d+.*")
        if not camera_images.exists or camera_images.count == 0:
            camera_images = bot.d(className="android.widget.Button", descriptionMatches=r"(?i)^Photo.*|^Ảnh.*")
        if not camera_images.exists or camera_images.count == 0:
            camera_images = bot.d(resourceIdMatches=".*camera_roll_image.*")
        if not camera_images.exists or camera_images.count == 0:
            camera_images = bot.d(className="android.widget.CheckBox")

        if camera_images.exists and camera_images.count > 0:
            # Deduplicate by bounds to avoid clicking parent Button + child ViewGroup (which causes deselect)
            unique_items = []
            seen_bounds = set()
            for idx in range(camera_images.count):
                try:
                    img = camera_images[idx]
                    info = img.info
                    b = info.get("bounds")
                    if b:
                        key = (b.get("left") // 10, b.get("top") // 10, b.get("right") // 10, b.get("bottom") // 10)
                        if key not in seen_bounds:
                            seen_bounds.add(key)
                            unique_items.append((img, info))
                except Exception as ex:
                    logger.debug(f"Error inspecting photo item {idx}: {ex}")

            if unique_items:
                unique_items.sort(key=lambda x: (x[1].get('bounds', {}).get('top', 0), x[1].get('bounds', {}).get('left', 0)))
                count = len(unique_items)
                actual_num = min(count, max(1, photo_num))
                target_indices = list(range(count - 1, count - 1 - actual_num, -1))
                bot.log(f"📸 Gallery has {count} photo(s). Selecting {actual_num} photo(s) from bottom up (indices: {target_indices})...")

                # Deselect any checked photo that is NOT in target_indices
                for i in range(count):
                    if i not in target_indices:
                        try:
                            img, info = unique_items[i]
                            if info.get("selected") or info.get("checked"):
                                bot.log(f"   🧹 Deselecting stale photo at index {i}...")
                                img.click_exists(timeout=2)
                                bot.smart_sleep(0.3)
                        except Exception:
                            pass

                # Select target photos from bottom up
                for order, idx in enumerate(target_indices, start=1):
                    try:
                        img, info = unique_items[idx]
                        img.click_exists(timeout=3)
                        selected_count += 1
                        bot.log(f"   ✔️ Selected photo {order}/{actual_num} (index {idx}, bottom-up)")
                        bot.smart_sleep(0.5)
                    except Exception as ce:
                        logger.debug(f"Error clicking photo {idx}: {ce}")

                photos_found = True
                break

        # 2. Try legacy / modern GridView
        grid_view = bot.get_elements_by_widget("android.widget.GridView", timeout=1) or (bot.d(className="android.widget.GridView") if bot.d else None)
        if grid_view and grid_view.exists:
            # 2a. Try finding buttons / views with photo description inside GridView
            photo_widgets = bot.d(className="android.view.ViewGroup", clickable=True, descriptionMatches=r"(?i).*Photo.*|.*Ảnh.*")
            if not photo_widgets.exists or photo_widgets.count == 0:
                photo_widgets = bot.d(className="android.widget.Button", descriptionMatches=r"(?i).*Photo.*|.*Ảnh.*")
            if not photo_widgets.exists or photo_widgets.count == 0:
                photo_widgets = bot.d(descriptionMatches=r"(?i).*Photo.*|.*Ảnh.*")
            if not photo_widgets.exists or photo_widgets.count == 0:
                # 2b. Fallback to get_interactable_from_parent with text="photo"
                photo_widgets = bot.get_interactable_from_parent(
                    grid_view[0] if hasattr(grid_view, '__getitem__') else grid_view, 
                    "android.view.ViewGroup", 
                    text="photo", 
                    timeout=5
                )

            if photo_widgets and photo_widgets.exists and photo_widgets.count > 0:
                unique_grid_items = []
                seen_grid_bounds = set()
                for idx in range(photo_widgets.count):
                    try:
                        pw = photo_widgets[idx]
                        info = pw.info
                        b = info.get("bounds")
                        if b:
                            key = (b.get("left") // 10, b.get("top") // 10, b.get("right") // 10, b.get("bottom") // 10)
                            if key not in seen_grid_bounds:
                                seen_grid_bounds.add(key)
                                unique_grid_items.append((pw, info))
                    except Exception as ex:
                        logger.debug(f"Error inspecting grid item {idx}: {ex}")

                if unique_grid_items:
                    unique_grid_items.sort(key=lambda x: (x[1].get('bounds', {}).get('top', 0), x[1].get('bounds', {}).get('left', 0)))
                    count = len(unique_grid_items)
                    actual_num = min(count, max(1, photo_num))
                    target_indices = list(range(count - 1, count - 1 - actual_num, -1))
                    bot.log(f"📸 GridView has {count} photo(s). Selecting {actual_num} photo(s) from bottom up (indices: {target_indices})...")
                    
                    for i in range(count):
                        if i not in target_indices:
                            try:
                                pw, info = unique_grid_items[i]
                                if info.get("selected") or info.get("checked"):
                                    pw.click_exists(timeout=2)
                                    bot.smart_sleep(0.3)
                            except Exception:
                                pass

                    for order, idx in enumerate(target_indices, start=1):
                        try:
                            pw, info = unique_grid_items[idx]
                            pw.click_exists(timeout=3)
                            selected_count += 1
                            bot.log(f"   ✔️ Selected photo {order}/{actual_num} (index {idx}, GridView bottom-up)")
                            bot.smart_sleep(0.5)
                        except Exception as ce:
                            logger.debug(f"Error clicking photo {idx}: {ce}")
                    photos_found = True
                    break

        bot.smart_sleep(1.0)

    if not photos_found and not _has_selected_photos():
        bot.log("❌ No photos detected in Camera Roll/Gallery after timeout.")
        raise Exception("❌ No photos detected or selected in Camera Roll/Gallery.")

    # 3. Click Next / Done / Add to confirm photos
    confirmed = _click_next_confirm()
    if not confirmed:
        raise Exception("❌ Could not find or click Next / Confirm button after selecting photos.")

    bot.log(f"✔️ Completed Step 3 (Selected {selected_count} photo(s)).")
    return True


# ==============================================================================
# STEP 4: ADAPTIVE FORM FILLING (TITLE, PRICE, CATEGORY, CONDITION, LOCATION, DESCRIPTION)
# ==============================================================================

def _set_title(bot: BaseAutomator, title: str):
    """Enters listing title (max 90 characters, in UPPERCASE)."""
    if not bot.d:
        return
    t_clean = str(title).strip() if title else ""
    if not t_clean or t_clean.lower().startswith("```") or t_clean in ("{", "}", '""', "''") or len(t_clean) < 5:
        title_text = "BẤT ĐỘNG SẢN GIÁ TỐT"
    else:
        title_text = t_clean.upper()[:90]

    bot.log(f"✏️ Entering Title ({len(title_text)} chars): '{title_text[:40]}...'")

    title_elem = bot.d(resourceId="composer_v3_title")
    if not title_elem.exists:
        title_elem = bot.d(descriptionMatches="(?i)^Title.*")
    if not title_elem.exists:
        title_elem = bot.get_widget_by_text("android.view.ViewGroup", "title", timeout=5)

    if not title_elem or not title_elem.exists:
        raise Exception("❌ Could not find Title input field.")

    bot.swipe_widget_to_center(title_elem)
    title_elem.click()
    bot.smart_sleep(0.5)

    title_input = bot.d(className="android.widget.EditText", descriptionMatches="(?i)^Title.*")
    if not title_input.exists:
        title_input = bot.get_interactable_from_parent(title_elem, "android.widget.EditText", timeout=3)
    if not title_input.exists:
        title_input = bot.d(focused=True, className="android.widget.EditText")

    if title_input.exists:
        try:
            title_input.clear_text()
        except Exception:
            pass
        title_input.set_text(title_text)
    else:
        bot.d.send_keys(title_text)

    bot.smart_sleep(0.5)
    bot.hide_keyboard()
    bot.log("   ✔️ Title entered successfully.")


def _set_price(bot: BaseAutomator, price: Optional[Any] = None):
    """Enters listing price, stripping trailing zeros (e.g. 12,000,000 -> 12, 7,500 -> 75)."""
    if not bot.d:
        return
    if price is not None and str(price).strip() != "":
        # Extract digits first, then remove all trailing zeros (e.g. 12,000,000 -> 12; 7,500 -> 75)
        digits_only = re.sub(r'[^\d]', '', str(price))
        price_val = digits_only.rstrip('0')
        if not price_val:
            price_val = digits_only or "1"
    else:
        price_val = str(randint(1, 100))

    bot.log(f"💰 Entering Price: {price_val} (original: {price})...")

    price_elem = bot.d(resourceId="composer_v3_price")
    if not price_elem.exists:
        price_elem = bot.d(descriptionMatches="(?i)^Price.*")
    if not price_elem.exists:
        price_elem = bot.get_widget_by_text("android.view.ViewGroup", "price", timeout=5)

    if not price_elem or not price_elem.exists:
        raise Exception("❌ Could not find Price input field.")

    bot.swipe_widget_to_center(price_elem)
    price_elem.click()
    bot.smart_sleep(0.5)

    price_input = bot.d(className="android.widget.EditText", descriptionMatches="(?i)^Price.*")
    if not price_input.exists:
        price_input = bot.get_interactable_from_parent(price_elem, "android.widget.EditText", timeout=3)
    if not price_input.exists:
        price_input = bot.d(focused=True, className="android.widget.EditText")

    if price_input.exists:
        try:
            price_input.clear_text()
        except Exception:
            pass
        price_input.set_text(price_val)
    else:
        bot.d.send_keys(price_val)

    bot.smart_sleep(0.5)
    bot.hide_keyboard()
    bot.log("   ✔️ Price entered successfully.")


def _set_category(bot: BaseAutomator, category_name: str = "Miscellaneous", max_swipes: int = 10):
    """
    Selects listing category if Category field is present on UI.
    Supports both modal popup (with RadioButtons and Save button) and full-screen category lists.
    """
    if not bot.d:
        return
    category_btn = bot.get_button_by_text("category", timeout=2)
    if not category_btn or not category_btn.exists:
        category_btn = bot.d(descriptionMatches="(?i)^Category.*")
    if not category_btn or not category_btn.exists:
        category_btn = bot.get_widget_by_text("android.view.ViewGroup", "category", timeout=1)

    if not category_btn or not category_btn.exists:
        bot.log("⏩ 'Category' field not found or already set, skipping.")
        return

    target_category = category_name or "Miscellaneous"
    bot.log(f"🏷️ Category field found. Opening category picker...")
    bot.swipe_widget_to_center(category_btn)
    category_btn.click()
    bot.smart_sleep(1.5)

    # Category keywords for search (English and Vietnamese)
    if target_category.lower() == "miscellaneous":
        cat_keywords = ["miscellaneous", "linh tinh", "khác", "mục linh tinh", "hàng linh tinh"]
    else:
        cat_keywords = [target_category, "miscellaneous", "linh tinh", "khác"]

    save_keywords = ["save", "lưu"]

    def _click_save_if_present() -> bool:
        """Helper to click 'Save' or 'Lưu' button on modal category popup."""
        for skw in save_keywords:
            s_btn = bot.get_button_by_text(skw, timeout=1)
            if s_btn and s_btn.exists:
                bot.log(f"💾 Found '{skw}' button, clicking to confirm category...")
                s_btn.click_exists(timeout=2)
                bot.smart_sleep(1.5)
                return True
            if bot.d:
                d_save = bot.d(descriptionMatches=f"(?i)^{skw}$")
                if d_save.exists:
                    bot.log(f"💾 Found '{skw}' button via description, clicking...")
                    d_save.click()
                    bot.smart_sleep(1.5)
                    return True
                d_txt = bot.d(textMatches=f"(?i)^{skw}$")
                if d_txt.exists:
                    bot.log(f"💾 Found '{skw}' via text, clicking...")
                    d_txt.click()
                    bot.smart_sleep(1.5)
                    return True
        return False

    def _check_already_checked() -> bool:
        """Checks if target RadioButton is already checked."""
        for kw in cat_keywords:
            # 1. RadioButton with checked=True
            rb_checked = bot.d(className="android.widget.RadioButton", descriptionMatches=f"(?i).*{kw}.*", checked=True)
            if rb_checked.exists:
                return True
            rb_checked_txt = bot.d(className="android.widget.RadioButton", textMatches=f"(?i).*{kw}.*", checked=True)
            if rb_checked_txt.exists:
                return True
            # 2. Check info attribute on any matching RadioButton
            rb = bot.d(className="android.widget.RadioButton", descriptionMatches=f"(?i).*{kw}.*")
            if rb.exists:
                try:
                    if rb.info.get("checked", False):
                        return True
                except Exception:
                    pass
        return False

    def _find_and_click_radio() -> bool:
        """Finds target RadioButton or category item and clicks it."""
        for kw in cat_keywords:
            # 1. RadioButton by description (e.g. content-desc="Miscellaneous, , ")
            rb = bot.d(className="android.widget.RadioButton", descriptionMatches=f"(?i).*{kw}.*")
            if rb.exists:
                bot.log(f"👆 Found RadioButton matching '{kw}', clicking...")
                rb.click()
                bot.smart_sleep(1.0)
                return True

            # 2. RadioButton by text
            rb_txt = bot.d(className="android.widget.RadioButton", textMatches=f"(?i).*{kw}.*")
            if rb_txt.exists:
                bot.log(f"👆 Found RadioButton matching '{kw}' text, clicking...")
                rb_txt.click()
                bot.smart_sleep(1.0)
                return True

            # 3. TextView matching kw (inside category list)
            tv = bot.d(className="android.widget.TextView", textMatches=f"(?i).*{kw}.*")
            if tv.exists:
                bot.log(f"👆 Found TextView matching '{kw}', clicking...")
                tv.click()
                bot.smart_sleep(1.0)
                return True

            # 4. Standard button fallback
            btn = bot.get_button_by_text(kw, timeout=0.5)
            if btn and btn.exists:
                bot.log(f"👆 Found Button matching '{kw}', clicking...")
                btn.click_exists(timeout=2)
                bot.smart_sleep(1.0)
                return True
        return False

    # Check if category is already selected on the current view
    if _check_already_checked():
        bot.log(f"✔️ Category '{target_category}' is already selected (checked=True)!")
        if _click_save_if_present():
            bot.log("   ✔️ Category saved successfully.")
        return

    # Check and click on the current view before scrolling
    if _find_and_click_radio():
        bot.log(f"✔️ Selected category '{target_category}'.")
        _click_save_if_present()
        return

    # Otherwise scroll to search for category RadioButton
    found = False
    for swipe_idx in range(max_swipes):
        bot.log(f"🔄 Scrolling category list (Swipe {swipe_idx + 1}/{max_swipes})...")
        sig1 = bot._get_screen_signature()
        bot.swipe_up(scale=0.5)
        bot.smart_sleep(1.0)

        # Check if already checked after scroll
        if _check_already_checked():
            bot.log(f"✔️ Category '{target_category}' is already selected (checked=True)!")
            _click_save_if_present()
            found = True
            break

        # Check and click after scroll
        if _find_and_click_radio():
            bot.log(f"✔️ Selected category '{target_category}'.")
            _click_save_if_present()
            found = True
            break

        sig2 = bot._get_screen_signature()
        if sig1 == sig2 and sig1 != 0:
            bot.log("🏁 Reached end of Category list.")
            break

    if not found:
        bot.log(f"⚠️ Could not find category '{target_category}' after {max_swipes} swipes.")
        # Try closing popup or saving if available
        if not _click_save_if_present():
            close_btn = bot.d(description="Close")
            if close_btn.exists:
                close_btn.click_exists(timeout=2)
    else:
        bot.log(f"   ✔️ Category '{target_category}' processed.")


def _set_condition(bot: BaseAutomator, condition_name: str = "New", timeout: int = 5):
    """
    Selects Condition if field is visible on UI.
    Handles 2 cases:
    1. Condition already selected (e.g. "Condition, New, , ") -> Skip, do not process condition logic.
    2. Condition unselected (e.g. "Condition, , , ") -> Click button, wait for conditionbox bottom sheet, click "New".
    Guarantees dismissal of the bottom sheet so it doesn't block subsequent fields.
    """
    if not bot.d:
        return

    target_cond = condition_name or "New"

    def _is_picker_open() -> bool:
        if not bot.d:
            return False
        return (
            bot.d(description="Reset").exists
            or bot.d(text="Reset").exists
            or bot.d(className="android.widget.RadioButton", descriptionMatches=f"(?i)^{re.escape(target_cond)}.*").exists
        )

    def _dismiss_picker():
        for _ in range(3):
            if not _is_picker_open():
                break
            close_btn = bot.d(descriptionMatches="(?i)^Close$", className="android.widget.Button")
            if not close_btn.exists:
                close_btn = bot.d(description="Close")
            if close_btn.exists:
                bot.log("   Dismissing Condition bottom sheet via Close button...")
                close_btn.click_exists(timeout=2)
                bot.smart_sleep(0.8)

    # CHECK 0: Is Condition picker ALREADY open on screen?
    if not _is_picker_open():
        cond_btn = bot.d(descriptionMatches="(?i)^(Condition|Tình trạng).*")
        if not cond_btn.exists:
            cond_btn = bot.get_button_by_text("condition", timeout=1) or bot.get_button_by_text("tình trạng", timeout=1)
        if not cond_btn or not cond_btn.exists:
            cond_btn = bot.get_widget_by_text("android.view.ViewGroup", "condition", timeout=1) or bot.get_widget_by_text("android.view.ViewGroup", "tình trạng", timeout=1)
        if not cond_btn or not cond_btn.exists:
            cond_btn = bot.d(textMatches="(?i)^(Condition|Tình trạng)$")

        if not cond_btn or not cond_btn.exists:
            bot.log("⏩ 'Condition' field not found, skipping.")
            return

        # CASE 1: Check if Condition is already selected (e.g. "Condition, New, , ")
        desc = ""
        try:
            desc = cond_btn.info.get("contentDescription") or ""
            if not desc:
                parent = cond_btn.up(className="android.widget.Button")
                if parent.exists:
                    desc = parent.info.get("contentDescription") or ""
        except Exception:
            pass

        already_selected = False
        if desc:
            parts = [p.strip() for p in desc.split(",") if p.strip()]
            # Selected dump format: "Condition, New, , " -> parts: ['Condition', 'New']
            if len(parts) >= 2 and any(p.lower() == target_cond.lower() for p in parts[1:]):
                already_selected = True
            elif re.search(rf"(?i)condition[,\s:]+{re.escape(target_cond)}", desc):
                already_selected = True

        if not already_selected:
            try:
                # Check if there is an overlapping/child ViewGroup text with target_cond inside cond_btn bounds
                cond_val_elem = bot.d(className="android.view.ViewGroup", textMatches=f"(?i)^{re.escape(target_cond)}$")
                if cond_val_elem.exists:
                    b_btn = cond_btn.info.get("bounds", {})
                    b_val = cond_val_elem.info.get("bounds", {})
                    if b_btn and b_val:
                        if b_btn.get("top", 0) <= b_val.get("top", 0) and b_btn.get("bottom", 0) >= b_val.get("bottom", 0):
                            already_selected = True
            except Exception:
                pass

        if already_selected:
            bot.log(f"   ✔️ Condition is already selected ('{target_cond}'). Skipping condition selection.")
            return

        # CASE 2: Condition is unselected -> Click button, wait for conditionbox, click target option
        bot.log(f"🏷️ Condition is unselected. Clicking to open Condition picker...")
        # Avoid swipe_widget_to_center as swiping from a button center can trigger unwanted touch events
        clicked = cond_btn.click_exists(timeout=2)
        if not clicked:
            try:
                cx, cy = cond_btn.center()
                bot.d.click(cx, cy)
            except Exception:
                pass
        bot.smart_sleep(1.0)

    # Wait for conditionbox to appear (ref: tests/dumps/conditionbox_unselected)
    bot.log("⏳ Waiting for Condition picker (conditionbox) to appear...")
    start_t = time.time()
    while time.time() - start_t < timeout:
        if _is_picker_open():
            break
        bot.smart_sleep(0.3)

    try:
        # Click target condition option (e.g. "New")
        new_option = bot.d(className="android.widget.RadioButton", descriptionMatches=f"(?i)^{re.escape(target_cond)}.*")
        if not new_option.exists:
            new_option = bot.d(className="android.widget.RadioButton", textMatches=f"(?i)^{re.escape(target_cond)}.*")
        if not new_option.exists:
            new_option = bot.d(text=target_cond)
        if not new_option.exists:
            new_option = bot.d(descriptionMatches=f"(?i)^{re.escape(target_cond)}.*")
        if not new_option.exists:
            new_option = bot.get_button_by_text(target_cond, exact=False, timeout=2)

        if new_option and new_option.exists:
            bot.log(f"👆 Found option '{target_cond}'. Clicking...")
            new_option.click_exists(timeout=3)
            bot.smart_sleep(1.0)
            bot.log(f"   ✔️ Condition '{target_cond}' selected.")
        else:
            bot.log(f"⚠️ Option '{target_cond}' not found in Condition list.")
    finally:
        # Always guarantee bottom sheet is closed so it doesn't block the rest of the form
        _dismiss_picker()


def _set_location(bot: BaseAutomator, city_name: str = "Da Lat"):
    """Updates Location if needed."""
    if not bot.d:
        return
    target_city = city_name or "Da Lat"
    bot.log(f"📍 Checking location: target '{target_city}'...")

    loc_btn = bot.d(descriptionMatches="(?i).*Location.*")
    if not loc_btn.exists:
        loc_btn = bot.get_button_by_text("location", timeout=3)

    if not loc_btn or not loc_btn.exists:
        bot.log("⏩ 'Location' button not found, skipping.")
        return

    bot.swipe_widget_to_center(loc_btn)
    desc = ""
    try:
        desc = loc_btn.info.get('contentDescription', '') or loc_btn.info.get('text', '')
    except Exception:
        pass

    if target_city.lower() in desc.lower():
        bot.log(f"   ✔️ Current location already matches ('{desc}'). Keeping as is.")
        return

    bot.log(f"👆 Opening location picker for '{target_city}'...")
    loc_btn.click()
    bot.smart_sleep(1.5)

    search_input = bot.d(className="android.widget.EditText")
    if not search_input.exists:
        search_input = bot.get_widget_by_text("android.widget.EditText", "Search", timeout=3)

    if search_input and search_input.exists:
        search_input.click()
        search_input.send_keys(target_city)
        bot.smart_sleep(1.5)

        city_suggestion = bot.get_button_by_text(target_city, timeout=5)
        if city_suggestion and city_suggestion.exists:
            city_suggestion.click()
            bot.smart_sleep(1.0)

        apply_btn = bot.get_button_by_text("apply", timeout=5)
        if not apply_btn or not apply_btn.exists:
            apply_btn = bot.get_button_by_text("áp dụng", timeout=3)
        if apply_btn and apply_btn.exists:
            apply_btn.click()
            bot.smart_sleep(1.0)
            bot.log(f"   ✔️ Applied location '{target_city}'.")
    else:
        bot.log("⚠️ Could not find location search field.")


def _set_description(bot: BaseAutomator, description: str):
    """Inputs listing description."""
    if not bot.d:
        return
    d_clean = str(description).strip() if description else ""
    if not d_clean or d_clean.lower().startswith("```") or d_clean in ("{", "}", '""', "''") or len(d_clean) < 10:
        desc_text = "Bất động sản chính chủ, giá tốt, vị trí thuận tiện. Liên hệ xem nhà đất ngay."
    else:
        desc_text = d_clean
    bot.log(f"📝 Finding and entering Description ({len(desc_text)} chars)...")

    desc_elem = bot.d(resourceId="composer_v3_description")
    if not desc_elem.exists:
        desc_elem = bot.d(descriptionMatches="(?i).*Description.*")
    if not desc_elem.exists:
        desc_elem = bot.d(descriptionMatches="(?i).*Mô tả.*")
    if not desc_elem.exists:
        desc_elem = bot.d(text="Description")
    if not desc_elem.exists:
        desc_elem = bot.get_widget_by_text("android.view.ViewGroup", "description", timeout=2)
    if not desc_elem or not desc_elem.exists:
        desc_elem = bot.get_widget_by_text("android.view.ViewGroup", "mô tả", timeout=2)

    if not desc_elem or not desc_elem.exists:
        bot.log("🔄 Scrolling down to locate Description field...")
        bot.swipe_up(scale=0.5)
        bot.smart_sleep(1.0)
        desc_elem = bot.d(resourceId="composer_v3_description")
        if not desc_elem.exists:
            desc_elem = bot.d(descriptionMatches="(?i).*Description.*")
        if not desc_elem.exists:
            desc_elem = bot.d(descriptionMatches="(?i).*Mô tả.*")
        if not desc_elem.exists:
            desc_elem = bot.get_widget_by_text("android.view.ViewGroup", "description", timeout=3)

    if desc_elem and desc_elem.exists:
        bot.swipe_widget_to_center(desc_elem)
        desc_elem.click()
        bot.smart_sleep(0.5)

        desc_input = desc_elem.child(className="android.widget.EditText")
        if not desc_input.exists:
            desc_input = bot.d(className="android.widget.EditText", descriptionMatches="(?i).*Description.*")
        if not desc_input.exists:
            desc_input = bot.get_interactable_from_parent(desc_elem, "android.widget.EditText", timeout=3)
        if not desc_input.exists:
            desc_input = bot.d(focused=True, className="android.widget.EditText")

        if desc_input.exists:
            try:
                desc_input.clear_text()
            except Exception:
                pass
            desc_input.set_text(desc_text)
        else:
            bot.d.send_keys(desc_text)

        bot.smart_sleep(0.5)
        bot.hide_keyboard()
        bot.log("   ✔️ Description entered successfully.")
    else:
        bot.log("⚠️ Description field not found, skipping.")


def fill_listing_details(bot: BaseAutomator, payload: Dict[str, Any], max_scroll_cycles: int = 5):
    """
    STEP 4: Adaptive Form Filling - Flexible with UI order and scrolling.
    Detects positions of visible fields, sorts by top_y, fills them, and swipes up until all are complete.
    """
    bot.log("📝 [Step 4] Starting adaptive listing details form filling...")

    title = payload.get("title", "")
    price = payload.get("price", "")
    category = payload.get("category") or "Miscellaneous"
    condition = payload.get("condition") or "New"
    location = payload.get("location", "Da Lat")
    description = payload.get("description", "")

    field_handlers = {
        "title": lambda: _set_title(bot, title),
        "price": lambda: _set_price(bot, price),
        "category": lambda: _set_category(bot, category),
        "condition": lambda: _set_condition(bot, condition),
        "location": lambda: _set_location(bot, location),
        "description": lambda: _set_description(bot, description),
    }

    def detect_field_position(field_name: str) -> Optional[int]:
        if not bot.d:
            return None
        el = None
        if field_name == "title":
            el = bot.d(resourceId="composer_v3_title")
            if not el.exists:
                el = bot.d(descriptionMatches="(?i)^Title.*")
            if not el.exists:
                el = bot.d(text="Title")
        elif field_name == "price":
            el = bot.d(resourceId="composer_v3_price")
            if not el.exists:
                el = bot.d(descriptionMatches="(?i)^Price.*")
            if not el.exists:
                el = bot.d(text="Price")
        elif field_name == "category":
            el = bot.d(descriptionMatches="(?i)^Category.*")
            if not el.exists:
                el = bot.get_button_by_text("category", timeout=0.2)
            if not el or not el.exists:
                el = bot.d(text="Category")
        elif field_name == "condition":
            el = bot.d(descriptionMatches="(?i)^(Condition|Tình trạng).*")
            if not el.exists:
                el = bot.get_button_by_text("condition", timeout=0.2) or bot.get_button_by_text("tình trạng", timeout=0.2)
            if not el or not el.exists:
                el = bot.d(textMatches="(?i)^(Condition|Tình trạng)$")
        elif field_name == "location":
            el = bot.d(descriptionMatches="(?i).*Location.*")
            if not el.exists:
                el = bot.get_button_by_text("location", timeout=0.2)
            if not el or not el.exists:
                el = bot.d(text="Location")
        elif field_name == "description":
            el = bot.d(resourceId="composer_v3_description")
            if not el.exists:
                el = bot.d(descriptionMatches="(?i).*Description.*")
            if not el.exists:
                el = bot.d(descriptionMatches="(?i).*Mô tả.*")
            if not el.exists:
                el = bot.d(text="Description")
            if not el.exists:
                el = bot.get_widget_by_text("android.view.ViewGroup", "description", timeout=0.2)
            if not el or not el.exists:
                el = bot.get_widget_by_text("android.view.ViewGroup", "mô tả", timeout=0.2)

        if el and el.exists:
            try:
                bounds = el.info.get('bounds', {})
                if isinstance(bounds, dict) and 'top' in bounds:
                    top_y = bounds['top']
                    if 180 <= top_y <= 1850:
                        return top_y
            except Exception:
                pass
        return None

    completed_fields = set()
    all_fields = set(field_handlers.keys())

    for cycle in range(max_scroll_cycles):
        remaining_fields = all_fields - completed_fields
        if not remaining_fields:
            bot.log("🎉 All fields completed!")
            break

        visible_fields = []
        for field in remaining_fields:
            top_y = detect_field_position(field)
            if top_y is not None:
                visible_fields.append((top_y, field))

        visible_fields.sort(key=lambda item: item[0])

        if visible_fields:
            field_names_in_order = [f[1] for f in visible_fields]
            bot.log(f"📋 [Scan {cycle + 1}] Detected {len(visible_fields)} field(s) in order: {field_names_in_order}")

            for top_y, field in visible_fields:
                if field in completed_fields:
                    continue
                bot.log(f"👉 Filling field: [{field}]...")
                try:
                    field_handlers[field]()
                    completed_fields.add(field)
                    bot.smart_sleep(0.8)
                except Exception as fe:
                    bot.log(f"⚠️ Error handling field [{field}]: {fe}")
                    completed_fields.add(field)

        remaining_fields = all_fields - completed_fields
        if not remaining_fields or ({"title", "price", "description"}.issubset(completed_fields) and "location" in completed_fields):
            bot.log("🎉 All required fields completed!")
            break

        bot.log(f"🔄 Remaining fields: {list(remaining_fields)}. Scrolling down...")
        sig1 = bot._get_screen_signature()
        bot.swipe_up(scale=0.5)
        bot.smart_sleep(1.5)
        sig2 = bot._get_screen_signature()

        if sig1 == sig2 and sig1 != 0:
            bot.log("🏁 Reached the bottom of listing form. Performing final scan on remaining fields...")
            # Scan and fill any remaining fields that are visible at the bottom
            for field in list(remaining_fields):
                top_y = detect_field_position(field)
                if top_y is not None:
                    bot.log(f"👉 Filling remaining field at bottom: [{field}]...")
                    try:
                        field_handlers[field]()
                        completed_fields.add(field)
                        bot.smart_sleep(0.8)
                    except Exception as fe:
                        bot.log(f"⚠️ Error handling field [{field}] at bottom: {fe}")
            break

    # Final safety check: if description was not completed, attempt direct fill
    if "description" not in completed_fields:
        bot.log("⚠️ Description was not completed during adaptive cycles. Attempting direct description fill...")
        try:
            _set_description(bot, description)
            completed_fields.add("description")
        except Exception as e:
            bot.log(f"⚠️ Direct description fill failed: {e}")

    missing = all_fields - completed_fields
    critical_missing = missing - {"condition"}
    if critical_missing:
        bot.log(f"⚠️ Incomplete critical fields at end of Step 4: {critical_missing}")
        raise Exception(f"❌ Incomplete critical fields at end of Step 4: {critical_missing}")
    else:
        bot.log("🎉 All required fields completed!")

    bot.log(f"✔️ [Step 4] Completed listing details ({len(completed_fields)}/{len(all_fields)} fields)!")


# ==============================================================================
# STEP 5: CLICK 'NEXT' BUTTON
# ==============================================================================

def click_next_button(bot: BaseAutomator, timeout: int = 15) -> bool:
    """STEP 5: Click 'Next' on listing form to proceed to group selection. Returns False if direct Publish button is detected."""
    if not bot.d:
        return False
    bot.log("👉 [Step 5] Finding and clicking 'Next' button...")

    patterns = ["Next", "Tiếp", "Tiếp tục"]
    next_btn = None
    for p in patterns:
        next_btn = bot.d(text=p)
        if next_btn.exists: break
        next_btn = bot.d(textMatches=f"(?i)^{p}$")
        if next_btn.exists: break
        next_btn = bot.d(descriptionMatches=f"(?i)^{p}.*")
        if next_btn.exists: break
        next_btn = bot.get_button_by_text(p.lower(), timeout=0.5)
        if next_btn and next_btn.exists: break

    if not next_btn or not next_btn.exists:
        next_btn = bot.d(resourceId="mp_composer_next")

    if not next_btn or not next_btn.exists:
        bot.hide_keyboard()
        bot.smart_sleep(0.5)
        for p in patterns:
            next_btn = bot.d(textMatches=f"(?i)^{p}$") or bot.d(descriptionMatches=f"(?i)^{p}.*") or bot.get_button_by_text(p.lower(), timeout=0.5)
            if next_btn and next_btn.exists:
                break

    if not next_btn or not next_btn.exists:
        # Check if the button is directly 'Publish' or 'Đăng' on this form!
        for pub in ["Publish", "Đăng", "Đăng bài", "Xong"]:
            direct_pub = bot.d(textMatches=f"(?i)^{pub}.*")
            if not direct_pub.exists:
                direct_pub = bot.d(descriptionMatches=f"(?i)^{pub}.*")
            if direct_pub.exists:
                bot.log(f"ℹ️ Found direct '{pub}' button on listing form instead of 'Next'. Form does not require group selection, publishing directly!")
                return False

        raise Exception("❌ Could not find 'Next' or 'Publish' button on listing form.")

    next_btn.click_exists(timeout=5)
    bot.smart_sleep(2.5)
    bot.log("✔️ Clicked 'Next', transitioning to group & Marketplace selection.")
    return True


# ==============================================================================
# STEP 6: SELECT MARKETPLACE & TOP-MEMBER GROUPS
# ==============================================================================

def select_marketplace_checkbox(bot: BaseAutomator) -> bool:
    """Checks the Marketplace checkbox if not already checked."""
    if not bot.d:
        return False
    try:
        mp_box = bot.d(className="android.widget.CheckBox", descriptionMatches="(?i).*Marketplace.*")
        if not mp_box.exists:
            mp_box = bot.d(className="android.widget.CheckBox", textMatches="(?i).*Marketplace.*")
        if not mp_box.exists:
            mp_box = bot.d(descriptionMatches="(?i).*Marketplace.*")

        if mp_box.exists:
            is_checked = mp_box.info.get('checked', False)
            if not is_checked:
                bot.log("🛒 Marketplace is unchecked. Selecting...")
                mp_box.click_exists(timeout=3)
                bot.smart_sleep(0.8)
                bot.log("   ✔️ Marketplace selected for cross-posting!")
                return True
            else:
                bot.log("ℹ️ Marketplace is already checked.")
                return True
        else:
            bot.log("ℹ️ Marketplace checkbox not found on this listing.")
    except Exception as e:
        logger.debug(f"Error selecting Marketplace: {e}")
    return False


def wait_for_group_list(bot: BaseAutomator, timeout: int = 15) -> bool:
    """Waits for the group selection list ('List in more places') to load."""
    bot.log("⏳ Waiting for group list to load from server...")
    start_time = time.time()

    while time.time() - start_time < timeout:
        checkboxes = bot.get_elements_by_widget("android.widget.CheckBox", timeout=1)
        if checkboxes and checkboxes.exists and checkboxes.count > 0:
            bot.log(f"✔️ Detected {checkboxes.count} checkbox(es) on screen!")
            bot.smart_sleep(1.0)
            return True

        check_nodes = bot.d(checkable=True)
        if check_nodes.exists and check_nodes.count > 0:
            bot.log(f"✔️ Detected {check_nodes.count} checkable item(s) on screen!")
            bot.smart_sleep(1.0)
            return True

        loading = bot.get_elements_by_widget("android.widget.ProgressBar", timeout=1)
        if loading and loading.exists:
            bot.log("🔄 Loading more groups...")

        for pub in ["Publish", "Đăng", "Đăng bài"]:
            if bot.d(textMatches=f"(?i)^{pub}.*").exists:
                return True

        bot.smart_sleep(1.0)

    bot.log("ℹ️ Timeout waiting for group checkboxes. Checking available screen elements...")
    return False


def collect_available_groups(
    bot: BaseAutomator, 
    max_swipes: int = 5, 
    swipe_delay: float = 1.5
) -> Dict[str, int]:
    """Scrolls down and collects available groups and their member counts."""
    collected_groups: Dict[str, int] = {}
    bot.log(f"📋 Scanning group list (Max {max_swipes} swipes)...")

    for swipe_idx in range(max_swipes):
        checkboxes = bot.get_elements_by_widget("android.widget.CheckBox", timeout=2)
        found_in_screen = 0

        if checkboxes and checkboxes.exists:
            for i in range(checkboxes.count):
                try:
                    box = checkboxes[i]
                    desc = box.info.get('contentDescription', '') or box.info.get('text', '')
                    if "Marketplace" in desc:
                        continue
                    if desc and desc not in collected_groups:
                        members = _parse_member_count(desc)
                        collected_groups[desc] = members
                        found_in_screen += 1
                except Exception:
                    pass

        if not collected_groups:
            check_nodes = bot.d(checkable=True)
            if check_nodes.exists:
                for i in range(check_nodes.count):
                    try:
                        box = check_nodes[i]
                        desc = box.info.get('contentDescription', '') or box.info.get('text', '')
                        if "Marketplace" in desc:
                            continue
                        if desc and desc not in collected_groups:
                            members = _parse_member_count(desc)
                            collected_groups[desc] = members
                            found_in_screen += 1
                    except Exception:
                        pass

        bot.log(f"🔍 Swipe {swipe_idx + 1}/{max_swipes}: Collected {found_in_screen} new group(s). Total: {len(collected_groups)} group(s).")

        sig1 = bot._get_screen_signature()
        bot.swipe_up(scale=0.8)
        bot.smart_sleep(swipe_delay)
        sig2 = bot._get_screen_signature()

        if sig1 == sig2 and sig1 != 0:
            bot.log("🏁 Reached the end of group list.")
            break

    return collected_groups


def scroll_to_top_of_list(bot: BaseAutomator, max_swipes: int = 6):
    """Scrolls group list back to the top."""
    if not bot.d:
        return
    try:
        w, h = bot.d.window_size()
        for _ in range(max_swipes):
            bot.d.swipe(w // 2, int(h * 0.30), w // 2, int(h * 0.72), steps=15)
            bot.smart_sleep(0.4)
    except Exception as e:
        logger.debug(f"Error scrolling to top: {e}")


def select_target_groups(
    bot: BaseAutomator, 
    target_descs: Set[str], 
    max_swipes: int = 10, 
    click_delay: float = 0.8
) -> int:
    """Scrolls from top to bottom and checks target group checkboxes."""
    clicked_groups: Set[str] = set()
    total_target = len(target_descs)
    bot.log(f"🎯 Selecting {total_target} target group(s)...")

    # 1. Scroll back to top before starting selection
    scroll_to_top_of_list(bot, max_swipes=6)
    bot.smart_sleep(1.0)

    def _find_target_match(box_desc: str) -> Optional[str]:
        if not box_desc:
            return None
        # Exact match
        if box_desc in target_descs:
            return box_desc
        # Normalized match (by group name before member count/commas)
        box_clean = box_desc.split(',')[0].strip().lower()
        if len(box_clean) >= 5:
            for t in target_descs:
                t_clean = t.split(',')[0].strip().lower()
                if t_clean and (t_clean in box_clean or box_clean in t_clean):
                    return t
        return None

    # 2. Select from top to bottom
    for swipe_idx in range(max_swipes):
        checkboxes = bot.get_elements_by_widget("android.widget.CheckBox", timeout=2)

        if checkboxes and checkboxes.exists:
            for i in range(checkboxes.count):
                try:
                    box = checkboxes[i]
                    desc = box.info.get('contentDescription', '') or box.info.get('text', '')
                    is_checked = box.info.get('checked', False)

                    matched_target = _find_target_match(desc)
                    if matched_target and matched_target not in clicked_groups:
                        if not is_checked:
                            box.click_exists(timeout=3)
                            bot.smart_sleep(click_delay)

                        clicked_groups.add(matched_target)
                        bot.log(f"✔️ Selected group ({len(clicked_groups)}/{total_target}): {matched_target[:40]}...")
                except Exception as e:
                    logger.debug(f"Error interacting with checkbox: {e}")

        if len(clicked_groups) < total_target:
            check_nodes = bot.d(checkable=True)
            if check_nodes.exists:
                for i in range(check_nodes.count):
                    try:
                        box = check_nodes[i]
                        desc = box.info.get('contentDescription', '') or box.info.get('text', '')
                        is_checked = box.info.get('checked', False)

                        matched_target = _find_target_match(desc)
                        if matched_target and matched_target not in clicked_groups:
                            if not is_checked:
                                box.click_exists(timeout=3)
                                bot.smart_sleep(click_delay)

                            clicked_groups.add(matched_target)
                            bot.log(f"✔️ Selected group ({len(clicked_groups)}/{total_target}): {matched_target[:40]}...")
                    except Exception:
                        pass

        if len(clicked_groups) >= total_target:
            bot.log("🎉 All target groups selected!")
            break

        sig1 = bot._get_screen_signature()
        bot.swipe_up(scale=0.8)
        bot.smart_sleep(1.0)
        sig2 = bot._get_screen_signature()

        if sig1 == sig2 and sig1 != 0:
            bot.log("🏁 Reached the end of group list.")
            break

    return len(clicked_groups)


def _is_matching_location(desc: str) -> bool:
    """
    Mandatory check: Group title/desc must contain 'đà lạt' or 'lâm đồng'.
    Supports accented and unaccented variations.
    """
    text = desc.lower()
    location_keywords = ["đà lạt", "da lat", "dalat", "lâm đồng", "lam dong", "lamdong"]
    return any(loc in text for loc in location_keywords)


def _is_matching_transaction_type(desc: str, transaction_type: str = "rental") -> bool:
    """
    Checks if group title matches the account's transaction type:
    - Rental: ["thuê", "căn hộ", "sang nhượng", "thue", "can ho", "sang nhuong"]
    - Sale: ["mua", "bán", "ban"]
    """
    text = desc.lower()
    trans_clean = str(transaction_type or "rental").lower().strip()

    if trans_clean in ("rental", "rent", "thue", "cho_thue"):
        rental_kws = ["thuê", "căn hộ", "sang nhượng", "thue", "can ho", "sang nhuong"]
        return any(kw in text for kw in rental_kws)
    elif trans_clean in ("sale", "ban", "mua", "buy", "buy_sell"):
        sale_kws = ["mua", "bán"]
        if any(kw in text for kw in sale_kws):
            return True
        if re.search(r'\b(mua|ban)\b', text):
            return True
        return False

    return False


def filter_and_rank_groups_by_transaction_type(
    collected_groups: Dict[str, int],
    transaction_type: str = "rental",
    min_members: int = 0
) -> List[tuple]:
    """
    Filters and ranks groups based on:
    1. Mandatory: Group title must contain 'đà lạt' or 'lâm đồng'.
    2. Minimum members threshold (count >= min_members).
    3. Transaction type priority:
       - rental -> keywords in ['thuê', 'căn hộ', 'sang nhượng']
       - sale   -> keywords in ['mua', 'bán']
    4. Sorter: Prioritized matching groups first, then secondary location-matching groups,
       all sorted descending by member count.

    Returns a list of tuples: (group_desc, member_count, is_transaction_priority_match)
    """
    # 1. Filter by mandatory location & min_members
    location_matched = {
        desc: count for desc, count in collected_groups.items()
        if _is_matching_location(desc) and count >= min_members
    }

    if not location_matched:
        return []

    # 2. Separate into priority (matches transaction_type) and secondary (location matched only)
    priority_groups = []
    secondary_groups = []

    for desc, count in location_matched.items():
        if _is_matching_transaction_type(desc, transaction_type):
            priority_groups.append((desc, count, True))
        else:
            secondary_groups.append((desc, count, False))

    # Sort each group descending by member count
    priority_groups.sort(key=lambda x: x[1], reverse=True)
    secondary_groups.sort(key=lambda x: x[1], reverse=True)

    # Combine: priority groups first, then remaining location-matched groups
    return priority_groups + secondary_groups


def list_in_more_places(
    bot: BaseAutomator, 
    share_groups_count: int = 5, 
    max_swipes: int = 5,
    min_members: int = 0,
    transaction_type: str = "rental"
) -> int:
    """STEP 6: Selects Marketplace and target groups matching location and transaction type."""
    bot.log(f"📋 [Step 6] Starting Marketplace and up to {share_groups_count} groups selection (Transaction Type: '{transaction_type}')...")

    if not wait_for_group_list(bot, timeout=10):
        bot.log("⚠️ Group list screen not fully recognized, continuing with available elements...")

    select_marketplace_checkbox(bot)

    if share_groups_count <= 0:
        bot.log("ℹ️ Target share group count is 0. Skipping group selection.")
        return 0

    target_count = min(share_groups_count, 20)

    collected_groups = collect_available_groups(bot, max_swipes=max_swipes, swipe_delay=1.5)
    if not collected_groups:
        bot.log("ℹ️ No additional groups found in the list. Skipping group selection.")
        return 0

    ranked_groups = filter_and_rank_groups_by_transaction_type(
        collected_groups,
        transaction_type=transaction_type,
        min_members=min_members
    )

    if not ranked_groups:
        bot.log("⚠️ No groups matched mandatory location ('đà lạt' or 'lâm đồng'). Skipping group selection.")
        return 0

    top_groups_list = ranked_groups[:target_count]
    target_descs = {desc for desc, count, is_match in top_groups_list}

    bot.log(f"📋 Selected Top {len(target_descs)} group(s) matching criteria (Transaction Type: '{transaction_type}'):")
    for idx, (name, count, is_match) in enumerate(top_groups_list, start=1):
        tag = "⭐ [Ưu tiên]" if is_match else "📍 [Đà Lạt/Lâm Đồng]"
        bot.log(f"   {idx}. {tag} {name[:45]} ({count:,} members)")

    selected_count = select_target_groups(bot, target_descs, max_swipes=max(max_swipes + 2, 8), click_delay=0.8)
    bot.log(f"✔️ Completed selecting {selected_count} group(s).")
    return selected_count


# ==============================================================================
# STEP 7: CLICK PUBLISH
# ==============================================================================

def click_publish_or_done(bot: BaseAutomator, timeout: int = 20) -> bool:
    """STEP 7: Clicks 'Publish' button and waits for completion."""
    if not bot.d:
        return False
    bot.log("🚀 [Step 7] Finding and clicking 'Publish' button...")

    patterns = ["Publish", "Đăng", "Đăng bài", "Xong", "Done"]
    publish_btn = None
    for p in patterns:
        publish_btn = bot.d(text=p)
        if publish_btn.exists: break
        publish_btn = bot.d(textMatches=f"(?i)^{p}$")
        if publish_btn.exists: break
        publish_btn = bot.d(descriptionMatches=f"(?i)^{p}.*")
        if publish_btn.exists: break
        publish_btn = bot.get_button_by_text(p.lower(), timeout=0.5)
        if publish_btn and publish_btn.exists: break

    if not publish_btn or not publish_btn.exists:
        publish_btn = bot.d(resourceId="mp_composer_post")

    if not publish_btn or not publish_btn.exists:
        publish_btn = bot.d(resourceIdMatches="(?i).*composer.*post.*|.*publish.*")

    if not publish_btn or not publish_btn.exists:
        # Fallback: check top-right header action button if visible
        try:
            w, h = bot.d.window_size() if bot.d else (1080, 1920)
            top_right_btn = bot.d(clickable=True, boundsInside=(int(0.7 * w), 0, w, int(0.12 * h)))
            if top_right_btn.exists:
                bot.log("ℹ️ Found clickable header action button at top-right corner. Using fallback click...")
                publish_btn = top_right_btn
        except Exception:
            pass
        if top_right_btn.exists:
            bot.log("ℹ️ Found clickable header action button at top-right corner. Using fallback click...")
            publish_btn = top_right_btn

    if not publish_btn or not publish_btn.exists:
        raise Exception("❌ Could not find 'Publish' button on screen.")

    bot.log("👆 Clicking 'Publish' button...")
    publish_btn.click_exists(timeout=5)
    bot.smart_sleep(5.0)

    start_time = time.time()
    bot.log("⏳ Waiting for publishing to finalize...")
    while time.time() - start_time < timeout:
        current_app = bot.d.app_current()
        if current_app.get("package") == "com.facebook.katana":
            creating_badge = bot.get_widget_by_text("android.view.ViewGroup", "creating", timeout=1)
            dang_tao = bot.get_widget_by_text("android.view.ViewGroup", "đang tạo bài niêm yết", timeout=1)
            if not creating_badge or not creating_badge.exists:
                if not dang_tao or not dang_tao.exists:
                    bot.log("✔️ Listing creation completed successfully!")
                    bot.smart_sleep(2.0)
                    return True

        bot.smart_sleep(1.0)

    bot.log("⚠️ Publish step timed out waiting for completion confirmation.")
    raise Exception("❌ Publish step timed out waiting for completion confirmation.")


# ==============================================================================


# ==============================================================================
# CLASS-BASED ACTION WRAPPER FOR MY-MANAGER.V2
# ==============================================================================

class FBGroupShareAction:
    def __init__(self, automator: BaseAutomator, account: Account):
        self.automator = automator
        self.account = account
        if hasattr(self.automator, '__dict__'):
            self.automator.account_uid = self.account.uid
        self.detector = CheckpointDetector(automator.device)
        self.v1_bridge = V1DatabaseBridge()
        self.ai_service = GeminiService()

    def execute_7step_group_share(
        self,
        group_id: str,
        title: str,
        price: str,
        description: str,
        image_paths: List[str],
        category: str = "Miscellaneous",
        condition: str = "New",
        location: str = "Da Lat",
        max_share_groups: int = 5,
        transaction_type: Optional[str] = None
    ) -> bool:
        """Executes full 7-step Buy/Sell Group Listing & Top-Group Cross Sharing pipeline."""
        logger.info(f"Starting 7-Step Group Share pipeline for {self.account.uid} on Group '{group_id}'...")

        pushed_remotes = []
        current_step = "step_0_push_media"
        is_success = False
        try:
            if image_paths:
                pushed_remotes = self.automator.push_media(image_paths)

            # Step 1: Open Group via Deeplink
            current_step = "step_1_open_facebook_group"
            open_facebook_group(self.automator, group_id, timeout=15)

            # Checkpoint safety check
            is_cp, cp_msg = self.detector.is_checkpoint()
            if is_cp:
                current_step = "checkpoint_detected"
                AccountRepository.update_status(self.account.uid, AccountStatus.CHECKPOINT, cp_msg)
                return False

            # Step 2: Click 'What are you selling?'
            current_step = "step_2_click_what_are_you_selling"
            click_what_are_you_selling(self.automator, timeout=20)

            # Check for Confirm Identity screen after clicking sell button
            if check_and_handle_identity_confirmation(self.automator, self.account.uid):
                self.automator.log("🚨 Account required Confirm Identity after clicking sell button. Aborting pipeline.")
                return False

            # Step 3: Add Photos from Redroid gallery
            current_step = "step_3_click_add_photos"
            photo_count = min(len(image_paths), 5) if image_paths else 1
            click_add_photos(self.automator, photo_num=photo_count, timeout=15, max_retries=20)

            # Step 4: Fill Listing Details (Adaptive Form Filling)
            current_step = "step_4_fill_listing_details"
            payload = {
                "title": title,
                "price": price,
                "category": category,
                "condition": condition,
                "location": location,
                "description": description
            }
            fill_listing_details(self.automator, payload, max_scroll_cycles=5)

            # Step 5: Click Next
            current_step = "step_5_click_next_button"
            has_next = click_next_button(self.automator, timeout=15)

            if has_next:
                # Step 6: Select Marketplace & Top Groups
                current_step = "step_6_list_in_more_places"
                trans_type = transaction_type or getattr(self.account, 'transaction_type', 'rental') or 'rental'
                list_in_more_places(
                    self.automator,
                    share_groups_count=max_share_groups,
                    max_swipes=5,
                    transaction_type=trans_type
                )

            # Step 7: Click Publish
            current_step = "step_7_click_publish_or_done"
            click_publish_or_done(self.automator, timeout=20)

            is_success = True
            logger.info(f"Successfully published 7-step Group Share listing for {self.account.uid}!")
            return True

        except Exception as e:
            logger.exception(f"Error during 7-Step Group Share execution at {current_step}: {e}")
            return False

        finally:
            if not is_success:
                logger.error(f"Execution failed at {current_step}. Dumping error view in finally block...")
                dump_error_view(self.automator, account_uid=self.account.uid, step_name=current_step)
            if pushed_remotes:
                self.automator.cleanup_media()

    def execute(
        self,
        group_ids: List[str],
        use_v1_product: bool = True,
        use_ai: bool = True,
        share_groups_count: int = 5,
        custom_content: Optional[str] = None
    ) -> bool:
        """Wrapper method executing 7-step Group Share with v1 Real Estate products and Gemini AI content."""
        logger.info(f"Executing Group Share pipeline for {self.account.uid}...")

        category = getattr(self.account, 'category', 'real_estate') or 'real_estate'
        trans_type = getattr(self.account, 'transaction_type', 'rental') or 'rental'

        if use_v1_product:
            product = self.v1_bridge.get_random_product_for_account(self.account)
            if not product:
                logger.error(f"No active product found for category '{category}', transaction_type '{trans_type}' in v1 DB.")
                return False

            raw_title, raw_desc = self.v1_bridge.format_product_summary(product)
            is_rental = str(product.get("transaction_type")) in ("rental", "1")

            if use_ai:
                ai_t, ai_d = self.ai_service.rewrite_real_estate_listing(raw_title, raw_desc, is_rental=is_rental)
                t_clean = str(ai_t).strip() if ai_t else ""
                title = t_clean[:90].strip() if t_clean and not t_clean.lower().startswith("```") and len(t_clean) >= 5 else (raw_title[:90].strip() or "BẤT ĐỘNG SẢN GIÁ TỐT")
                d_clean = str(ai_d).strip() if ai_d else ""
                description = d_clean if d_clean and not d_clean.lower().startswith("```") and len(d_clean) >= 10 else raw_desc
            else:
                title = raw_title[:90].strip() or "BẤT ĐỘNG SẢN GIÁ TỐT"
                description = raw_desc

            images = self.v1_bridge.get_product_images(str(product.get("id")))[:5]
            raw_price = product.get("price", 1000000)
            unit = str(product.get("unit", "")).lower()
            try:
                p_val = float(raw_price)
                if "million_per_month" in unit or is_rental:
                    price = str(int(p_val * 1_000_000)) if p_val < 1000 else str(int(p_val))
                elif "billion" in unit or (0 < p_val < 1000):
                    price = str(int(p_val * 1_000_000_000))
                else:
                    price = str(int(p_val))
            except Exception:
                price = "1000000"
        else:
            title = "BẤT ĐỘNG SẢN GIÁ TỐT"
            description = custom_content or "Bài viết bất động sản chính chủ."
            images = []
            price = "1000000"

        first_group = group_ids[0] if group_ids else "muabannhadat"
        return self.execute_7step_group_share(
            group_id=first_group,
            title=title,
            price=price,
            description=description,
            image_paths=images,
            category="Miscellaneous",
            condition="New",
            location="Da Lat",
            max_share_groups=share_groups_count,
            transaction_type=trans_type
        )
