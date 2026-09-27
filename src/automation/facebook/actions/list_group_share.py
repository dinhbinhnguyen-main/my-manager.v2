"""Facebook Buy/Sell Group Listing & Top-Group Cross-Sharing Action.
Ported with 100% faithful logic from phonemanager.v1 (Adaptive Form Filling, Strict Media Picker, Top-Member Cross-Sharing).
"""

import os
import re
import json
import time
import shutil
import logging
import subprocess
import xml.etree.ElementTree as ET
from random import randint
from pathlib import Path
from typing import List, Dict, Any, Optional, Set

from src.core.models import Account, AccountStatus
from src.db.repository import AccountRepository
from src.automation.base_automator import BaseAutomator
from src.automation.checkpoint_handler import CheckpointDetector
from src.services.v1_bridge import V1DatabaseBridge
from src.ai.gemini_service import GeminiService

logger = logging.getLogger(__name__)


# ==============================================================================
# HELPER FUNCTIONS & UI DIAGNOSTIC DUMP
# ==============================================================================

def dump_error_view(bot: BaseAutomator, account_uid: Optional[str] = None, step_name: str = "unknown_step"):
    """
    Automatically dumps UI hierarchy (XML, JSON, Screenshot) on error or missing elements.
    Saved to: tests/dumps/errors/{safe_uid}_{safe_step}_{timestamp}/
    Also mirrors latest error dump to tests/dumps/latest/
    """
    try:
        from tests.dump_view import parse_hierarchy_node

        uid = str(account_uid or getattr(bot, "account_uid", None) or getattr(bot, "adb_port", "device"))
        safe_uid = re.sub(r'[^\w\-_\.]', '_', uid)
        safe_step = re.sub(r'[^\w\-_\.]', '_', str(step_name))
        timestamp = time.strftime("%Y%m%d_%H%M%S")

        output_dir = Path("tests/dumps/errors") / f"{safe_uid}_{safe_step}_{timestamp}"
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
                "adb_port": getattr(bot, "adb_port", None),
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
    bot.launch(deeplink=deeplink)

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
    dump_error_view(bot, step_name="step_1_open_facebook_group_failed")
    return True


# ==============================================================================
# STEP 2: CLICK 'WHAT ARE YOU SELLING?' / 'BẠN ĐANG BÁN GÌ?'
# ==============================================================================

def click_what_are_you_selling(bot: BaseAutomator, timeout: int = 15) -> bool:
    """
    STEP 2:
    - Search and click 'What are you selling?' (or 'Bạn đang bán gì?', 'Sell something', 'Item').
    - Wait logic: Wait for Listing Composer form to load.
    """
    bot.log("🔍 [Step 2] Searching for 'What are you selling?' button...")

    sell_keywords = [
        "what are you selling",
        "bạn đang bán gì",
        "sell something",
        "bán gì đó",
        "item"
    ]

    clicked = False
    for kw in sell_keywords:
        btn = bot.get_button_by_text(kw, timeout=2)
        if btn and btn.exists:
            bot.log(f"👆 Found and clicking '{kw}' button...")
            btn.click_exists(timeout=3)
            clicked = True
            break

        wg = bot.get_widget_by_text("android.view.ViewGroup", kw, timeout=1)
        if wg and wg.exists:
            bot.log(f"👆 Found ViewGroup '{kw}', clicking...")
            wg.click()
            clicked = True
            break

    if not clicked:
        bot.log("🔄 Scrolling slightly to find 'What are you selling?' button...")
        bot.swipe_down(scale=0.3)
        bot.smart_sleep(1.0)
        for kw in sell_keywords:
            btn = bot.get_button_by_text(kw, timeout=2)
            if btn and btn.exists:
                btn.click_exists(timeout=3)
                clicked = True
                break

    if not clicked:
        dump_error_view(bot, step_name="step_2_what_are_you_selling_not_found")
        raise Exception("❌ Could not find 'What are you selling?' button on group page.")

    bot.log("⏳ Waiting for listing form to open...")
    start_time = time.time()
    form_opened = False
    while time.time() - start_time < timeout:
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

        bot.smart_sleep(1.0)

    if not form_opened:
        dump_error_view(bot, step_name="step_2_listing_form_not_opened")

    bot.log("✔️ Completed Step 2 (Clicked sell button).")
    return True


# ==============================================================================
# STEP 3: CLICK 'ADD PHOTOS' AND SELECT PHOTOS
# ==============================================================================

def click_add_photos(bot: BaseAutomator, photo_num: int = 1, timeout: int = 15, max_retries: int = 2) -> bool:
    """
    STEP 3:
    - Search and click 'Add photos' (or 'Thêm ảnh').
    - If not found, try pressing 'back' (handling discard draft popup if any) and calling click_what_are_you_selling again.
    - Wait logic: Wait for Camera Roll / Photo Gallery to appear.
    - Identify photo checkboxes/grid items (NEVER matching arbitrary ImageView).
    - Select corresponding number of photos (photo_num) in reverse order (bottom up).
    - Click 'Next' / 'Done' to confirm photo selection.
    """
    bot.log("🖼️ [Step 3] Finding and clicking 'Add photos' button...")

    # Pre-grant storage permissions via ADB to avoid React Native permission SecurityException
    try:
        if hasattr(bot, "adb_client") and bot.adb_client and getattr(bot.adb_client, "target", None):
            target = bot.adb_client.target
            subprocess.run(["adb", "-s", target, "shell", "pm", "grant", "com.facebook.katana", "android.permission.READ_EXTERNAL_STORAGE"], capture_output=True)
            subprocess.run(["adb", "-s", target, "shell", "pm", "grant", "com.facebook.katana", "android.permission.READ_MEDIA_IMAGES"], capture_output=True)
    except Exception as pe:
        logger.debug(f"Pre-grant permissions error: {pe}")

    def _trigger_add_photos_button() -> bool:
        """Finds and clicks 'Add photos' / 'Thêm ảnh' via multiple selectors."""
        add_photo_keywords = ["add photos", "thêm ảnh", "add photo", "thêm hình ảnh"]
        for kw in add_photo_keywords:
            btn = bot.get_button_by_text(kw, timeout=2)
            if btn and btn.exists:
                bot.log(f"👆 Clicking '{kw}' button...")
                btn.click_exists(timeout=2)
                return True
            wg = bot.get_widget_by_text("android.view.ViewGroup", kw, timeout=1.5)
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

    max_open_attempts = max(max_retries, 4)
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
            bot.log(f"⚠️ Could not find 'Add photos' button on attempt {attempt + 1}. Waiting...")
            bot.smart_sleep(1.5)
            # If still on previous screen, try backup/draft discard logic on late attempts
            if attempt >= 2 and bot.d:
                bot.d.press("back")
                bot.smart_sleep(1.5)
                discard_btn = bot.get_button_by_text("discard", timeout=1) or bot.get_button_by_text("bỏ bài viết", timeout=1)
                if discard_btn and discard_btn.exists:
                    discard_btn.click_exists(timeout=2)
                try:
                    click_what_are_you_selling(bot)
                except Exception:
                    pass
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
            cam_box = bot.d(descriptionMatches="(?i).*Photo taken on.*")
            if not cam_box.exists:
                cam_box = bot.d(resourceIdMatches=".*camera_roll_image.*")
            if not cam_box.exists:
                cam_box = bot.d(className="android.widget.CheckBox")
            grid = bot.get_elements_by_widget("android.widget.GridView", timeout=1)

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
        dump_error_view(bot, step_name="step_3_add_photos_button_not_found")
        raise Exception("❌ Could not open Camera Roll / Gallery.")

    bot.log("⏳ Waiting for Camera Roll to appear...")
    start_time = time.time()
    photos_found = False
    selected_count = 0

    while time.time() - start_time < timeout:
        if not bot.d:
            break
        # 1. Try detecting standard Katana camera roll photos (ViewGroup / CheckBox)
        camera_images = bot.d(descriptionMatches="(?i).*Photo taken on.*")
        if not camera_images.exists:
            camera_images = bot.d(resourceIdMatches=".*camera_roll_image.*")
        if not camera_images.exists:
            camera_images = bot.d(className="android.widget.CheckBox")

        if camera_images.exists and camera_images.count > 0:
            count = camera_images.count
            actual_num = min(count, photo_num)
            bot.log(f"📸 Found {count} photos in Camera Roll. Selecting {actual_num} photos from bottom up...")

            for i in reversed(range(actual_num)):
                try:
                    img = camera_images[i]
                    img.click_exists(timeout=3)
                    selected_count += 1
                    bot.log(f"   ✔️ Selected photo {i + 1}/{actual_num} (bottom up)")
                    bot.smart_sleep(0.5)
                except Exception as ce:
                    logger.debug(f"Error clicking photo {i}: {ce}")

            photos_found = True
            break

        # 2. Try legacy GridView
        grid_view = bot.get_elements_by_widget("android.widget.GridView", timeout=1)
        if grid_view and grid_view.exists:
            photo_widgets = bot.get_interactable_from_parent(
                grid_view[0], 
                "android.view.ViewGroup", 
                text="photo", 
                timeout=5
            )
            if photo_widgets and photo_widgets.count > 0:
                count = photo_widgets.count
                actual_num = min(count, photo_num)
                bot.log(f"📸 Found {count} photos in GridView. Selecting {actual_num} photos...")
                for i in reversed(range(actual_num)):
                    photo_widgets[i].click_exists(timeout=3)
                    selected_count += 1
                    bot.smart_sleep(0.5)
                photos_found = True
                break

        bot.smart_sleep(1.0)

    if not photos_found:
        bot.log("⚠️ No photos detected in Camera Roll/Gallery after timeout.")
        dump_error_view(bot, step_name="step_3_no_photos_detected")

    # 3. Click Next / Done / Add to confirm photos
    bot.smart_sleep(1.0)
    next_keywords = ["next", "tiếp", "done", "xong", "add", "thêm"]
    confirmed = False
    for kw in next_keywords:
        btn = bot.get_button_by_text(kw, timeout=3)
        if btn and btn.exists:
            bot.log(f"👆 Clicking '{kw}' button to confirm adding {selected_count} photo(s) to listing...")
            btn.click_exists(timeout=5)
            bot.smart_sleep(2.0)
            confirmed = True
            break

    if not confirmed and selected_count > 0:
        bot.log("⚠️ Could not find confirm button after selecting photos.")
        dump_error_view(bot, step_name="step_3_confirm_photos_btn_not_found")

    bot.log(f"✔️ Completed Step 3 (Selected {selected_count} photo(s)).")
    return True


# ==============================================================================
# STEP 4: ADAPTIVE FORM FILLING (TITLE, PRICE, CATEGORY, CONDITION, LOCATION, DESCRIPTION)
# ==============================================================================

def _set_title(bot: BaseAutomator, title: str):
    """Enters listing title (in UPPERCASE)."""
    if not bot.d:
        return
    title_text = str(title).strip().upper() if title else "BẤT ĐỘNG SẢN GIÁ TỐT"
    bot.log(f"✏️ Entering Title: '{title_text[:35]}...'")

    title_elem = bot.d(resourceId="composer_v3_title")
    if not title_elem.exists:
        title_elem = bot.d(descriptionMatches="(?i)^Title.*")
    if not title_elem.exists:
        title_elem = bot.get_widget_by_text("android.view.ViewGroup", "title", timeout=5)

    if not title_elem or not title_elem.exists:
        dump_error_view(bot, step_name="step_4_title_field_not_found")
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
        title_input.send_keys(title_text)
    else:
        bot.d.send_keys(title_text)

    bot.smart_sleep(0.5)
    bot.log("   ✔️ Title entered successfully.")


def _set_price(bot: BaseAutomator, price: Optional[Any] = None):
    """Enters listing price with strict integer cleaning."""
    if not bot.d:
        return
    if price is not None and str(price).strip() != "":
        price_val = re.sub(r'[^\d]', '', str(price))
        if not price_val:
            price_val = str(price)
    else:
        price_val = str(randint(1, 1000))

    bot.log(f"💰 Entering Price: {price_val}...")

    price_elem = bot.d(resourceId="composer_v3_price")
    if not price_elem.exists:
        price_elem = bot.d(descriptionMatches="(?i)^Price.*")
    if not price_elem.exists:
        price_elem = bot.get_widget_by_text("android.view.ViewGroup", "price", timeout=5)

    if not price_elem or not price_elem.exists:
        dump_error_view(bot, step_name="step_4_price_field_not_found")
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
        price_input.send_keys(price_val)
    else:
        bot.d.send_keys(price_val)

    bot.smart_sleep(0.5)
    bot.log("   ✔️ Price entered successfully.")


def _set_category(bot: BaseAutomator, category_name: str = "Miscellaneous", max_swipes: int = 10):
    """Selects listing category if Category field is present on UI."""
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
    bot.log(f"🏷️ Category field found. Opening list and searching for '{target_category}'...")
    bot.swipe_widget_to_center(category_btn)
    category_btn.click()
    bot.smart_sleep(1.5)

    start_time = time.time()
    while time.time() - start_time < 5:
        if bot.d(resourceId="mp_categories_list").exists or bot.d(text="Select Category").exists:
            break
        bot.smart_sleep(0.5)

    found = False
    for swipe_idx in range(max_swipes):
        cat_node = bot.d(textMatches=f"(?i).*{target_category}.*")
        if not cat_node.exists:
            cat_node = bot.d(descriptionMatches=f"(?i).*{target_category}.*")
        if not cat_node.exists:
            cat_node = bot.get_button_by_text(target_category, timeout=1)

        if cat_node and cat_node.exists:
            bot.log(f"✔️ Found category '{target_category}' (Swipe {swipe_idx})! Selecting...")
            cat_node.click_exists(timeout=3)
            found = True
            bot.smart_sleep(1.5)
            break

        sig1 = bot._get_screen_signature()
        bot.swipe_up(scale=0.7)
        bot.smart_sleep(0.8)
        sig2 = bot._get_screen_signature()

        if sig1 == sig2 and sig1 != 0:
            bot.log("🏁 Reached end of Category list.")
            break

    if not found:
        bot.log(f"⚠️ Could not find category '{target_category}' after {max_swipes} swipes.")
        dump_error_view(bot, step_name=f"step_4_category_{target_category}_not_found")
        if bot.d(text="Select Category").exists or bot.d(resourceId="mp_categories_list").exists:
            back_btn = bot.d(description="Back")
            if back_btn.exists:
                back_btn.click_exists(timeout=3)
    else:
        bot.log(f"   ✔️ Category '{target_category}' selected.")


def _set_condition(bot: BaseAutomator, condition_name: str = "New", timeout: int = 5):
    """Selects Condition if field is visible on UI."""
    if not bot.d:
        return
    cond_btn = bot.d(descriptionMatches="(?i)^Condition.*")
    if not cond_btn.exists:
        cond_btn = bot.get_button_by_text("condition", timeout=2)
    if not cond_btn or not cond_btn.exists:
        cond_btn = bot.get_widget_by_text("android.view.ViewGroup", "condition", timeout=1)

    if not cond_btn or not cond_btn.exists:
        bot.log("⏩ 'Condition' field not found, skipping.")
        return

    target_cond = condition_name or "New"
    bot.log(f"🏷️ Condition field found. Opening and selecting '{target_cond}'...")
    bot.swipe_widget_to_center(cond_btn)
    cond_btn.click()
    bot.smart_sleep(1.0)

    new_option = bot.d(className="android.widget.RadioButton", descriptionMatches=f"(?i)^{target_cond}.*")
    if not new_option.exists:
        new_option = bot.d(text=target_cond)
    if not new_option.exists:
        new_option = bot.d(descriptionMatches=f"(?i)^{target_cond}.*")
    if not new_option.exists:
        new_option = bot.get_button_by_text(target_cond, exact=False, timeout=timeout)

    if new_option and new_option.exists:
        bot.log(f"👆 Found option '{target_cond}'. Clicking...")
        new_option.click_exists(timeout=3)
        bot.smart_sleep(1.0)
        bot.log(f"   ✔️ Condition '{target_cond}' selected.")
    else:
        bot.log(f"⚠️ Option '{target_cond}' not found in Condition list.")
        dump_error_view(bot, step_name=f"step_4_condition_{target_cond}_not_found")


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
        dump_error_view(bot, step_name="step_4_location_search_field_not_found")


def _set_description(bot: BaseAutomator, description: str):
    """Inputs listing description."""
    if not bot.d:
        return
    desc_text = str(description).strip() if description else "Bất động sản chính chủ, giá tốt. Liên hệ xem nhà đất ngay."
    bot.log(f"📝 Finding and entering Description ({len(desc_text)} chars)...")

    desc_elem = bot.d(descriptionMatches="(?i).*Description.*")
    if not desc_elem.exists:
        desc_elem = bot.get_widget_by_text("android.view.ViewGroup", "description", timeout=2)
    if not desc_elem or not desc_elem.exists:
        desc_elem = bot.get_widget_by_text("android.view.ViewGroup", "mô tả", timeout=2)

    if not desc_elem or not desc_elem.exists:
        bot.log("🔄 Scrolling down to locate Description field...")
        bot.swipe_up(scale=0.5)
        bot.smart_sleep(1.0)
        desc_elem = bot.d(descriptionMatches="(?i).*Description.*")
        if not desc_elem.exists:
            desc_elem = bot.get_widget_by_text("android.view.ViewGroup", "description", timeout=3)

    if desc_elem and desc_elem.exists:
        bot.swipe_widget_to_center(desc_elem)
        desc_elem.click()
        bot.smart_sleep(0.5)

        desc_input = bot.d(className="android.widget.EditText", descriptionMatches="(?i).*Description.*")
        if not desc_input.exists:
            desc_input = bot.get_interactable_from_parent(desc_elem, "android.widget.EditText", timeout=3)
        if not desc_input.exists:
            desc_input = bot.d(focused=True, className="android.widget.EditText")

        if desc_input.exists:
            desc_input.send_keys(desc_text)
        else:
            bot.d.send_keys(desc_text)

        bot.smart_sleep(0.5)
        bot.log("   ✔️ Description entered successfully.")
    else:
        bot.log("⚠️ Description field not found, skipping.")
        dump_error_view(bot, step_name="step_4_description_field_not_found")


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
            el = bot.d(descriptionMatches="(?i)^Condition.*")
            if not el.exists:
                el = bot.get_button_by_text("condition", timeout=0.2)
            if not el or not el.exists:
                el = bot.d(text="Condition")
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
                    bot.smart_sleep(1.0)
                except Exception as fe:
                    bot.log(f"⚠️ Error handling field [{field}]: {fe}")
                    dump_error_view(bot, step_name=f"step_4_field_{field}_error")
                    completed_fields.add(field)

        remaining_fields = all_fields - completed_fields
        if not remaining_fields:
            bot.log("🎉 All fields completed!")
            break

        bot.log(f"🔄 Remaining fields: {list(remaining_fields)}. Scrolling down...")
        sig1 = bot._get_screen_signature()
        bot.swipe_up(scale=0.5)
        bot.smart_sleep(1.5)
        sig2 = bot._get_screen_signature()

        if sig1 == sig2 and sig1 != 0:
            bot.log("🏁 Reached the bottom of listing form.")
            break

    missing = all_fields - completed_fields
    if missing:
        bot.log(f"⚠️ Incomplete fields at end of Step 4: {missing}")
        dump_error_view(bot, step_name="step_4_incomplete_fields")

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
        # Check if the button is directly 'Publish' or 'Đăng' on this form!
        for pub in ["Publish", "Đăng", "Đăng bài", "Xong"]:
            direct_pub = bot.d(textMatches=f"(?i)^{pub}.*")
            if not direct_pub.exists:
                direct_pub = bot.d(descriptionMatches=f"(?i)^{pub}.*")
            if direct_pub.exists:
                bot.log(f"ℹ️ Found direct '{pub}' button on listing form instead of 'Next'. Form does not require group selection, publishing directly!")
                return False

        dump_error_view(bot, step_name="step_5_next_button_not_found")
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


def select_target_groups(
    bot: BaseAutomator, 
    target_descs: Set[str], 
    max_swipes: int = 10, 
    click_delay: float = 0.8
) -> int:
    """Scrolls back up and checks target group checkboxes."""
    clicked_groups: Set[str] = set()
    total_target = len(target_descs)
    bot.log(f"🎯 Selecting {total_target} target group(s)...")

    for swipe_idx in range(max_swipes):
        checkboxes = bot.get_elements_by_widget("android.widget.CheckBox", timeout=2)

        if checkboxes and checkboxes.exists:
            for i in range(checkboxes.count):
                try:
                    box = checkboxes[i]
                    desc = box.info.get('contentDescription', '') or box.info.get('text', '')
                    is_checked = box.info.get('checked', False)

                    if desc in target_descs and desc not in clicked_groups:
                        if not is_checked:
                            box.click_exists(timeout=3)
                            bot.smart_sleep(click_delay)

                        clicked_groups.add(desc)
                        bot.log(f"✔️ Selected group ({len(clicked_groups)}/{total_target}): {desc[:40]}...")
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

                        if desc in target_descs and desc not in clicked_groups:
                            if not is_checked:
                                box.click_exists(timeout=3)
                                bot.smart_sleep(click_delay)

                            clicked_groups.add(desc)
                            bot.log(f"✔️ Selected group ({len(clicked_groups)}/{total_target}): {desc[:40]}...")
                    except Exception:
                        pass

        if len(clicked_groups) >= total_target:
            bot.log("🎉 All target groups selected!")
            break

        sig1 = bot._get_screen_signature()
        bot.swipe_down(scale=0.8)
        bot.smart_sleep(1.0)
        sig2 = bot._get_screen_signature()

        if sig1 == sig2 and sig1 != 0:
            bot.log("🏁 Scrolled back to top of group list.")
            break

    return len(clicked_groups)


def list_in_more_places(
    bot: BaseAutomator, 
    share_groups_count: int = 20, 
    max_swipes: int = 5,
    min_members: int = 0
) -> int:
    """STEP 6: Selects Marketplace and highest-member groups."""
    bot.log(f"📋 [Step 6] Starting Marketplace and up to {share_groups_count} groups selection...")

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

    filtered_groups = {
        name: count for name, count in collected_groups.items() 
        if count >= min_members
    }
    if not filtered_groups:
        filtered_groups = collected_groups

    sorted_groups = sorted(filtered_groups.items(), key=lambda item: item[1], reverse=True)
    top_groups = dict(sorted_groups[:target_count])
    target_descs = set(top_groups.keys())

    bot.log(f"📋 Selected Top {len(target_descs)} group(s) with highest member count:")
    for idx, (name, count) in enumerate(top_groups.items(), start=1):
        bot.log(f"   {idx}. {name[:45]} ({count:,} members)")

    selected_count = select_target_groups(bot, target_descs, max_swipes=max_swipes, click_delay=0.8)
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
        w, h = bot.get_screen_resolution()
        top_right_btn = bot.d(clickable=True, boundsInside=(int(0.7 * w), 0, w, int(0.12 * h)))
        if top_right_btn.exists:
            bot.log("ℹ️ Found clickable header action button at top-right corner. Using fallback click...")
            publish_btn = top_right_btn

    if not publish_btn or not publish_btn.exists:
        dump_error_view(bot, step_name="step_7_publish_button_not_found")
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
    dump_error_view(bot, step_name="step_7_publish_timeout")
    return True


# ==============================================================================
# MAIN FBGroupShareAction CLASS
# ==============================================================================

class FBGroupShareAction:
    def __init__(self, automator: BaseAutomator, account: Account):
        self.automator = automator
        self.account = account
        # Attach account_uid for dump_error_view
        if hasattr(self.automator, "__dict__"):
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
        max_share_groups: int = 20
    ) -> bool:
        """Executes full 7-step Buy/Sell Group Listing & Top-Group Cross Sharing pipeline."""
        logger.info(f"Starting 7-Step Group Share pipeline for {self.account.uid} on Group '{group_id}'...")

        pushed_remotes = []
        current_step = "step_0_push_media"
        try:
            # 0. Push images to /sdcard/DCIM/Camera and trigger media scanner
            if image_paths and self.automator.adb_client:
                logger.info(f"Pushing {len(image_paths)} image(s) to Redroid gallery...")
                self.automator.adb_client.ensure_storage_ready()
                self.automator.adb_client.grant_app_permissions("com.facebook.katana")
                for idx, img in enumerate(image_paths):
                    if not os.path.exists(img):
                        logger.warning(f"Image not found on host: {img}")
                        continue
                    ext = Path(img).suffix.lower() or ".jpg"
                    remote_path = f"/sdcard/DCIM/Camera/share_{idx}{ext}"
                    if self.automator.adb_client.push_file(img, remote_path):
                        pushed_remotes.append(remote_path)
                        self.automator.adb_client.scan_media_file(remote_path)
                    else:
                        logger.error(f"Failed to push image to Redroid: {img}")
                time.sleep(1.5)

            # Step 1: Open Group via Deeplink
            current_step = "step_1_open_facebook_group"
            open_facebook_group(self.automator, group_id, timeout=15)

            # Checkpoint safety check
            is_cp, cp_msg = self.detector.is_checkpoint()
            if is_cp:
                AccountRepository.update_status(self.account.uid, AccountStatus.CHECKPOINT, cp_msg)
                return False

            # Step 2: Click 'What are you selling?'
            current_step = "step_2_click_what_are_you_selling"
            click_what_are_you_selling(self.automator, timeout=15)

            # Step 3: Add Photos from Redroid gallery
            current_step = "step_3_click_add_photos"
            photo_count = min(len(image_paths), 5) if image_paths else 1
            try:
                click_add_photos(self.automator, photo_num=photo_count, timeout=15, max_retries=2)
            except Exception as e:
                logger.warning(f"Could not add photos: {e}")
                dump_error_view(self.automator, account_uid=self.account.uid, step_name="step_3_photos_failed")

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
                list_in_more_places(self.automator, share_groups_count=max_share_groups, max_swipes=5)

            # Step 7: Click Publish
            current_step = "step_7_click_publish_or_done"
            click_publish_or_done(self.automator, timeout=20)

            logger.info(f"Successfully published 7-step Group Share listing for {self.account.uid}!")
            return True

        except Exception as e:
            logger.exception(f"Error during 7-Step Group Share execution at {current_step}: {e}")
            dump_error_view(self.automator, account_uid=self.account.uid, step_name=f"exception_{current_step}")
            return False

        finally:
            if pushed_remotes:
                logger.info(f"Cleaning up {len(pushed_remotes)} temp image(s) from Redroid device storage...")
                for r_path in pushed_remotes:
                    self.automator.adb_client.remove_file(r_path)

    def execute(
        self,
        group_ids: List[str],
        use_v1_product: bool = True,
        use_ai: bool = True,
        share_groups_count: int = 20,
        custom_content: Optional[str] = None
    ) -> bool:
        """Wrapper method executing 7-step Group Share with v1 BĐS products and AI Gemini content."""
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
                description = self.ai_service.rewrite_real_estate_post(raw_title, raw_desc, is_rental=is_rental)
                title = raw_title[:80]
            else:
                title = raw_title[:80]
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
            max_share_groups=share_groups_count
        )
