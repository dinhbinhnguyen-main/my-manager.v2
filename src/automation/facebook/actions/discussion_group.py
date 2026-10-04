"""Facebook Group Discussion Post Action (discussion_group).
Posts real estate discussion content with rewritten AI/template text and attached gallery images.
Supports 100% Vietnamese and English Facebook UI on Redroid/Android devices.
"""

import os
import re
import json
import time
import shutil
import random
import logging
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Dict, Any, Optional, Set, Tuple

from src.core.models import Account, AccountStatus
from src.db.repository import AccountRepository
from src.automation.base_automator import BaseAutomator
from src.automation.checkpoint_handler import CheckpointDetector
from src.services.v1_bridge import V1DatabaseBridge
from src.ai.gemini_service import GeminiService

logger = logging.getLogger(__name__)


# ==============================================================================
# UI DIAGNOSTIC DUMP HELPERS
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


# ==============================================================================
# STEP 1: OPEN FACEBOOK GROUPS TAB LIST VIA DEEPLINK
# ==============================================================================

def open_groups_tab_list(bot: BaseAutomator, timeout: int = 20) -> bool:
    """
    STEP 1:
    - Stop com.facebook.katana and reset to Home screen.
    - Open Facebook app using deeplink: 'fb://groups/tab/list'.
    - Wait logic: Wait for the Groups list tab UI ('Your groups' / 'Nhóm của bạn') to load.
    """
    bot.log("🏠 [Step 1] Resetting Facebook app state and navigating to Groups Tab List...")
    try:
        if bot.d:
            bot.d.app_stop("com.facebook.katana")
            bot.d.press("home")
        bot.smart_sleep(1.0)
    except Exception as e:
        logger.debug(f"Failed to reset app state: {e}")

    deeplink = "fb://groups/tab/list"
    bot.log(f"🚀 [Step 1] Launching deeplink: '{deeplink}'...")
    bot.launch(deeplink=deeplink)

    bot.log("⏳ Waiting for Groups Tab List page to finish loading...")
    start_time = time.time()
    while time.time() - start_time < timeout:
        if not bot.d:
            break

        # Check for indicators of groups tab
        your_groups = bot.d(textMatches=r"(?i).*Your groups.*|.*Nhóm của bạn.*|.*Nhóm bạn đã tham gia.*")
        pinned_hdr = bot.d(textMatches=r"(?i).*Pinned.*|.*Đã ghim.*|.*Other.*|.*Khác.*|.*Groups you manage.*|.*Nhóm do bạn quản lý.*")
        create_btn = bot.d(descriptionMatches=r"(?i).*Create group.*|.*Tạo nhóm.*")

        if your_groups.exists or pinned_hdr.exists or create_btn.exists:
            bot.log("✔️ Groups tab list page loaded successfully!")
            bot.smart_sleep(1.5, 2.5)
            return True

        bot.smart_sleep(1.0)

    bot.log("⚠️ Timed out waiting for Groups Tab list page indicator. Checking if any group buttons are visible...")
    if bot.d and (bot.d(className="androidx.recyclerview.widget.RecyclerView").exists or bot.d(className="android.widget.Button").exists):
        return True

    raise Exception("❌ Failed to open Groups Tab List via deeplink 'fb://groups/tab/list'")


# ==============================================================================
# STEP 2: SELECT RANDOM GROUP MATCHING TRANSACTION TYPE
# ==============================================================================

SYSTEM_GROUP_BUTTON_KEYWORDS = [
    "pinned", "đã ghim", "edit", "chỉnh sửa", "groups you manage", "nhóm do bạn quản lý",
    "create group", "tạo nhóm", "create", "tạo", "other", "khác", "sort your other groups",
    "sắp xếp nhóm khác của bạn", "back", "quay lại", "search", "tìm kiếm", "your groups", "nhóm của bạn"
]

def _is_system_button(text: str, desc: str) -> bool:
    """Checks if a UI element is a system navigation/header button rather than a group item."""
    combined = f"{text} {desc}".strip().lower()
    if not combined:
        return True
    for kw in SYSTEM_GROUP_BUTTON_KEYWORDS:
        if combined == kw or combined.startswith(kw + " button") or combined == f"{kw}":
            return True
    return False


def is_group_matching_transaction_type(group_title: str, transaction_type: str = "rental") -> Tuple[bool, bool]:
    """
    Strictly evaluates if a group title matches the target transaction type.
    Returns: (is_priority_match, is_conflicting)
    - is_priority_match: True if title directly matches transaction type (e.g. 'bán' for sale, 'cho thuê' for rental).
    - is_conflicting: True if group is exclusively for the opposite transaction type (e.g. pure rental group when trans_type='sale').
    """
    title = group_title.lower()
    t_type = str(transaction_type or "rental").lower().strip()

    rental_exclusive_terms = [
        "cho thuê", "cho thue", "for rent", "nhà trọ", "phòng trọ", "nha tro",
        "phong tro", "apartment for rent", "house for rent", "căn hộ cho thuê",
        "can ho cho thue", "nhà cho thuê", "nha cho thue"
    ]
    rental_terms = rental_exclusive_terms + [
        "thuê", "thue", "rent", "rental", "căn hộ", "can ho", "sang nhượng", "sang nhuong"
    ]

    sale_terms = [
        "bán", "ban", "mua bán", "mua ban", "sale", "mua", "đất", "dat",
        "nhà đất", "nha dat", "bất động sản", "bat dong san", "bds", "đất nền",
        "dat nen", "nhà đẹp", "nha dep", "chính chủ", "chinh chu"
    ]

    is_pure_rental = any(r in title for r in rental_exclusive_terms)
    has_rental = any(r in title for r in rental_terms) or bool(re.search(r'\b(thue|rent|rental)\b', title))
    has_sale = any(s in title for s in sale_terms) or bool(re.search(r'\b(ban|sale|mua)\b', title))

    if t_type in ("sale", "ban", "mua_ban", "0"):
        # For SALE:
        # If group is explicitly a rental-only group (e.g. 'Căn hộ cho thuê Đà Lạt', 'House for rent'), reject it!
        if is_pure_rental:
            return False, True
        if has_rental and not ("mua bán" in title or "mua ban" in title or "bán" in title or "bds" in title or "bất động sản" in title):
            return False, True

        # Matches sale terms
        if has_sale:
            return True, False
        return False, False

    elif t_type in ("rental", "rent", "thue", "cho_thue", "1"):
        # For RENTAL:
        if has_rental:
            return True, False
        # If group title is purely buy/sell without rental
        if ("chuyên bán" in title or "mua bán đất" in title) and not has_rental:
            return False, True
        if has_sale:
            return False, False
        return False, False

    return True, False


def select_random_group_by_transaction_type(
    bot: BaseAutomator,
    transaction_type: Optional[str] = "rental",
    max_scrolls: int = 2,
    timeout: int = 15
) -> str:
    """
    STEP 2:
    - Scans groups listed in 'Your groups' tab.
    - Performs random scrolls down to discover more groups and pick randomly.
    - Filters groups matching transaction_type (rental / sale / real estate).
    - Strictly avoids conflicting groups (e.g. rental groups for sale transactions).
    - Randomly clicks an eligible group item.
    - Waits for the group main page to load.
    Returns the selected group name/title.
    """
    bot.log(f"🔍 [Step 2] Selecting random group matching transaction_type '{transaction_type}'...")

    if not bot.d:
        raise Exception("Device is not connected.")

    # 1. Perform random scrolling to get deeper into the group list
    actual_scrolls = random.randint(1, max(1, max_scrolls))
    bot.log(f"📜 Scrolling down {actual_scrolls} time(s) to discover groups in the list...")
    for s_idx in range(actual_scrolls):
        bot.swipe_up(scale=random.uniform(0.4, 0.7))
        bot.smart_sleep(1.0, 2.0)

    # 2. Extract group candidate buttons from current view
    seen_titles: Set[str] = set()
    priority_candidates: List[Tuple[Any, str]] = []
    secondary_candidates: List[Tuple[Any, str]] = []

    def _collect_groups_from_view():
        buttons = bot.d(className="android.widget.Button")
        for btn in buttons:
            try:
                if not btn.exists:
                    continue
                info = btn.info
                desc = info.get("contentDescription", "") or ""
                text = info.get("text", "") or ""

                if not text and not desc:
                    child_tv = btn.child(className="android.widget.TextView")
                    if child_tv.exists:
                        text = child_tv.info.get("text", "") or ""

                raw_label = f"{text} {desc}".strip()
                if _is_system_button(text, desc):
                    continue

                group_title = text or desc.split("Button")[0].strip() or raw_label
                if not group_title or len(group_title) < 4 or group_title in seen_titles:
                    continue
                seen_titles.add(group_title)

                is_priority, is_conflicting = is_group_matching_transaction_type(group_title, transaction_type)
                if is_conflicting:
                    bot.log(f"   ⛔ Excluding conflicting group for '{transaction_type}': '{group_title}'")
                    continue

                if is_priority:
                    priority_candidates.append((btn, group_title))
                else:
                    secondary_candidates.append((btn, group_title))
            except Exception:
                continue

    _collect_groups_from_view()

    # If no priority candidates, try one slight swipe down or up to scan more
    if not priority_candidates:
        bot.log("ℹ️ No priority group on current view, scrolling slightly up to re-check...")
        bot.swipe_down(scale=0.3)
        bot.smart_sleep(1.5)
        _collect_groups_from_view()

    bot.log(f"📊 Found {len(priority_candidates)} priority group(s) and {len(secondary_candidates)} secondary group(s) for transaction_type '{transaction_type}'.")

    pool = priority_candidates if priority_candidates else secondary_candidates
    if not pool:
        bot.log("❌ Failed to find any suitable group to click in group list tab.")
        raise Exception(f"❌ No matching groups found in Groups list tab for transaction_type '{transaction_type}'.")

    chosen_elem, chosen_name = random.choice(pool)
    bot.log(f"🎯 [Step 2] Selected target Group: '{chosen_name}' (from {len(pool)} candidates). Clicking...")
    chosen_elem.click()
    bot.smart_sleep(3.0, 5.0)

    # 3. Wait for group feed page to load
    start_time = time.time()
    while time.time() - start_time < timeout:
        if not bot.d:
            break
        write_box = bot.d(textMatches=r"(?i).*Write something.*|.*Viết gì đó.*|.*Bạn đang nghĩ gì.*|.*Tạo bài viết.*|.*Bạn viết gì đi.*")
        write_desc = bot.d(descriptionMatches=r"(?i).*Write something.*|.*Viết gì đó.*|.*Bạn đang nghĩ gì.*|.*Tạo bài viết.*|.*Bạn viết gì đi.*")
        group_feed = bot.d(textMatches=r"(?i).*Joined.*|.*Đã tham gia.*|.*Invite.*|.*Mời.*|.*Featured.*|.*Đáng chú ý.*")

        if write_box.exists or write_desc.exists or group_feed.exists:
            bot.log(f"✔️ Successfully opened Group '{chosen_name}'!")
            return chosen_name
        bot.smart_sleep(1.0)

    bot.log(f"ℹ️ Proceeding with group '{chosen_name}'...")
    return chosen_name


# ==============================================================================
# STEP 3: CLICK 'WRITE SOMETHING...' BUTTON
# ==============================================================================

def click_write_something_button(bot: BaseAutomator, timeout: int = 15) -> bool:
    """
    STEP 3:
    - Finds and clicks 'Write something...' / 'Bạn viết gì đi...' / 'Viết gì đó...' in group feed.
    - Dumps: tests/dumps/step_02_write_something/step_02.01
    """
    bot.log("✍️ [Step 3] Finding and clicking 'Write something...' button...")

    write_patterns = [
        r"(?i)^Write something\.\.\.$",
        r"(?i)^Bạn viết gì đi\.\.\.$",
        r"(?i)^Viết gì đó\.\.\.$",
        r"(?i)^Bạn đang nghĩ gì\?*$",
        r"(?i)^Tạo bài viết.*",
        r"(?i)^Hãy viết gì đó\.\.\.$",
        r"(?i).*write something.*",
        r"(?i).*viết gì đó.*",
        r"(?i).*bạn đang nghĩ gì.*"
    ]

    start_time = time.time()
    while time.time() - start_time < timeout:
        if not bot.d:
            break

        # 1. By exact / pattern text
        for p in write_patterns:
            btn = bot.d(textMatches=p)
            if btn.exists:
                bot.log(f"👆 Clicking 'Write something...' button (via text: {p})...")
                btn.click()
                bot.smart_sleep(2.0, 3.0)
                return True

            desc_btn = bot.d(descriptionMatches=p)
            if desc_btn.exists:
                bot.log(f"👆 Clicking 'Write something...' button (via description: {p})...")
                desc_btn.click()
                bot.smart_sleep(2.0, 3.0)
                return True

        # 2. Via widget helpers
        for kw in ["write something", "viết gì đó", "bạn đang nghĩ gì", "bạn viết gì đi", "tạo bài viết"]:
            w_btn = bot.get_button_by_text(kw, timeout=1)
            if w_btn and w_btn.exists:
                bot.log(f"👆 Clicking button '{kw}'...")
                w_btn.click()
                bot.smart_sleep(2.0, 3.0)
                return True

        # 3. Fallback: Check if composer is already opened
        create_post_field = bot.d(className="android.widget.AutoCompleteTextView") or bot.d(className="android.widget.EditText")
        if create_post_field.exists:
            bot.log("ℹ️ Composer form is already open.")
            return True

        bot.smart_sleep(1.0)

    bot.log("❌ Could not find 'Write something...' button in group feed.")
    raise Exception("❌ Could not find 'Write something...' button.")


# ==============================================================================
# STEP 4: CLICK 'CREATE YOUR POST...' INPUT FIELD
# ==============================================================================

def click_create_post_input_field(bot: BaseAutomator, timeout: int = 15) -> Any:
    """
    STEP 4:
    - Finds and clicks 'Create your post...' / 'Tạo bài viết công khai...' text field.
    - Dumps: tests/dumps/step_02_write_something/step_02.02
    Returns the target input element.
    """
    bot.log("📝 [Step 4] Finding and focusing 'Create your post...' input field...")

    input_patterns = [
        r"(?i).*Create your post.*",
        r"(?i).*Tạo bài viết.*",
        r"(?i).*Bạn đang nghĩ gì.*",
        r"(?i).*Viết gì đó.*",
        r"(?i).*Hãy viết gì đó.*",
        r"(?i).*What's on your mind.*"
    ]

    start_time = time.time()
    while time.time() - start_time < timeout:
        if not bot.d:
            break

        # 1. By AutoCompleteTextView (Standard Facebook Composer text box)
        actv = bot.d(className="android.widget.AutoCompleteTextView")
        if actv.exists:
            bot.log("👆 Focusing AutoCompleteTextView composer field...")
            actv.click()
            bot.smart_sleep(1.0, 2.0)
            return actv

        # 2. By EditText
        edit_tv = bot.d(className="android.widget.EditText")
        if edit_tv.exists:
            bot.log("👆 Focusing EditText composer field...")
            edit_tv.click()
            bot.smart_sleep(1.0, 2.0)
            return edit_tv

        # 3. By text/description matching
        for p in input_patterns:
            field = bot.d(textMatches=p)
            if field.exists:
                bot.log(f"👆 Focusing composer field matching text: '{p}'...")
                field.click()
                bot.smart_sleep(1.0, 2.0)
                return field

            field_desc = bot.d(descriptionMatches=p)
            if field_desc.exists:
                bot.log(f"👆 Focusing composer field matching desc: '{p}'...")
                field_desc.click()
                bot.smart_sleep(1.0, 2.0)
                return field_desc

        bot.smart_sleep(1.0)

    bot.log("❌ Could not find 'Create your post...' field in composer.")
    raise Exception("❌ Could not find 'Create your post...' input field.")


# ==============================================================================
# STEP 5: PASTE REWRITTEN AI CONTENT OR DEFAULT TEMPLATE
# ==============================================================================

def paste_discussion_content(bot: BaseAutomator, content: str, timeout: int = 15) -> bool:
    """
    STEP 5:
    - Inputs post text content into the active composer field.
    - Dumps: tests/dumps/step_02_write_something/step_02.03
    """
    bot.log("💬 [Step 5] Inputting post content into composer text field...")

    if not content or not content.strip():
        content = "Thảo luận bài viết bất động sản chính chủ."

    # Try setting text on focused AutoCompleteTextView or EditText
    actv = bot.d(className="android.widget.AutoCompleteTextView") if bot.d else None
    edit_tv = bot.d(className="android.widget.EditText") if bot.d else None

    target_field = None
    if actv and actv.exists:
        target_field = actv
    elif edit_tv and edit_tv.exists:
        target_field = edit_tv

    if target_field:
        try:
            bot.log(f"📋 Setting text into input field ({len(content)} chars)...")
            target_field.set_text(content)
            bot.smart_sleep(1.5, 2.5)
            return True
        except Exception as e:
            bot.log(f"⚠️ set_text failed ({e}), attempting fallback input_text...")

    # Fallback to bot.input_text
    bot.input_text(content)
    bot.smart_sleep(1.5, 2.5)
    return True


# ==============================================================================
# STEP 6: CLICK 'DONE' / 'NEXT' BUTTON
# ==============================================================================

def click_done_or_next_button(bot: BaseAutomator, timeout: int = 10) -> bool:
    """
    STEP 6:
    - Clicks 'Done' / 'Next' / 'Xong' / 'Tiếp' button to complete text input mode.
    - Dumps: tests/dumps/step_02_write_something/step_02.03
    """
    bot.log("👌 [Step 6] Clicking 'Done' / 'Next' button after text input...")

    done_keywords = ["done", "xong", "next", "tiếp", "tiếp tục", "hoàn tất"]

    start_time = time.time()
    while time.time() - start_time < timeout:
        if not bot.d:
            break

        # 1. Check exact button by text or content-desc
        for kw in done_keywords:
            btn = bot.d(textMatches=f"(?i)^{kw}$")
            if btn.exists:
                bot.log(f"👆 Clicking '{kw}' button (via text)...")
                btn.click()
                bot.smart_sleep(1.5, 2.5)
                return True

            btn_desc = bot.d(descriptionMatches=f"(?i)^{kw}$")
            if btn_desc.exists:
                bot.log(f"👆 Clicking '{kw}' button (via desc)...")
                btn_desc.click()
                bot.smart_sleep(1.5, 2.5)
                return True

            w_btn = bot.get_button_by_text(kw, timeout=1)
            if w_btn and w_btn.exists:
                bot.log(f"👆 Clicking widget '{kw}'...")
                w_btn.click()
                bot.smart_sleep(1.5, 2.5)
                return True

        # 2. Check if already back on the main composer view (e.g. Gallery button visible)
        gallery_btn = bot.d(textMatches=r"(?i).*Gallery.*|.*Ảnh.*|.*Ảnh/video.*") or bot.d(descriptionMatches=r"(?i).*Gallery.*|.*Ảnh.*|.*Ảnh/video.*")
        if gallery_btn.exists:
            bot.log("ℹ️ Already on main composer view with Gallery button visible.")
            return True

        bot.smart_sleep(1.0)

    bot.log("⚠️ 'Done' button not found or already dismissed. Pressing back to close soft keyboard if needed...")
    try:
        if bot.d:
            bot.d.press("back")
            bot.smart_sleep(1.0)
    except Exception:
        pass
    return True


# ==============================================================================
# STEP 7: CLICK 'GALLERY' / 'PHOTO/VIDEO' BUTTON
# ==============================================================================

def click_gallery_button(bot: BaseAutomator, timeout: int = 15) -> bool:
    """
    STEP 7:
    - Finds and clicks 'Gallery' / 'Ảnh/video' / 'Ảnh' button to open media picker.
    - Dumps: tests/dumps/step_02_write_something/step_02.02
    """
    bot.log("🖼️ [Step 7] Finding and clicking 'Gallery' / 'Ảnh/video' button...")

    gallery_patterns = [
        r"(?i)^Gallery$",
        r"(?i)^Ảnh/video$",
        r"(?i)^Ảnh$",
        r"(?i)^Photo/video$",
        r"(?i)^Photo/Video$",
        r"(?i)^Thư viện ảnh$",
        r"(?i)^Bộ sưu tập$",
        r"(?i).*gallery.*",
        r"(?i).*ảnh/video.*",
        r"(?i).*photo/video.*"
    ]

    start_time = time.time()
    while time.time() - start_time < timeout:
        if not bot.d:
            break

        for p in gallery_patterns:
            btn_desc = bot.d(descriptionMatches=p)
            if btn_desc.exists:
                bot.log(f"👆 Clicking Gallery button (via desc: {p})...")
                btn_desc.click()
                bot.smart_sleep(2.0, 3.0)
                return True

            btn_text = bot.d(textMatches=p)
            if btn_text.exists:
                bot.log(f"👆 Clicking Gallery button (via text: {p})...")
                btn_text.click()
                bot.smart_sleep(2.0, 3.0)
                return True

        # Check if photo grid is already open
        photo_item = bot.d(descriptionMatches=r"(?i).*Photo, item \d+.*|.*Ảnh, mục \d+.*|.*Photo.*taken on.*")
        if photo_item.exists:
            bot.log("ℹ️ Media picker / Gallery is already open.")
            return True

        bot.smart_sleep(1.0)

    bot.log("❌ Could not find 'Gallery' / 'Ảnh/video' button.")
    raise Exception("❌ Could not find 'Gallery' / 'Ảnh/video' button.")


# ==============================================================================
# STEP 8: SELECT IMAGES PUSHED TO REDROID CONTAINER (REVERSE 5-4-3-2-1 ORDER)
# ==============================================================================

def _has_selected_photos(bot: BaseAutomator) -> bool:
    """Checks if any photo is already selected in the gallery picker to prevent double clicking/deselection."""
    if not bot.d:
        return False
    try:
        if bot.d(className="android.widget.CompoundButton", checked=True).exists:
            return True
        if bot.d(className="android.widget.CompoundButton", selected=True).exists:
            return True
        if bot.d(className="android.widget.CheckBox", checked=True).exists:
            return True
        if bot.d(className="android.widget.CheckBox", selected=True).exists:
            return True
        # Check badge indicator '1', '2' etc.
        if bot.d(className="android.widget.TextView", textMatches=r"^[1-9]\d*$").exists:
            return True
    except Exception:
        pass
    return False


def select_pushed_images(bot: BaseAutomator, photo_count: int = 1, timeout: int = 15) -> int:
    """
    STEP 8:
    - Selects the pushed images from the gallery / Camera Roll picker.
    - STRICTLY selects in reverse order (5-4-3-2-1) so the first pushed photo (oldest) becomes Photo 1.
    - De-duplicates UI elements to completely prevent double-click deselection (faithful to list_group_share).
    - Dumps: tests/dumps/step_02_write_something/step_02.04
    Returns the number of selected photos.
    """
    bot.log(f"📸 [Step 8] Selecting {photo_count} image(s) from Gallery in reverse (5-4-3-2-1) order...")

    start_time = time.time()
    photos_ready = False
    while time.time() - start_time < timeout:
        if not bot.d:
            break

        photo_elem = bot.d(descriptionMatches=r"(?i).*Photo, item \d+.*|.*Ảnh, mục \d+.*|.*Photo.*taken on.*|.*Ảnh.*chụp.*")
        grid = bot.d(className="android.widget.GridView")
        comp_btn = bot.d(className="android.widget.CompoundButton")

        if photo_elem.exists or grid.exists or comp_btn.exists:
            photos_ready = True
            break
        bot.smart_sleep(1.0)

    if not photos_ready:
        bot.log("⚠️ Photo grid not immediately detected, waiting a moment...")
        bot.smart_sleep(1.5)

    # 1. Check if photos are already selected: if so, skip to avoid deselecting
    if _has_selected_photos(bot):
        bot.log("📸 Photo(s) ALREADY selected in Gallery. Skipping re-selection to avoid deselecting!")
        return photo_count

    target_num = max(1, photo_count)
    selected_count = 0

    # 2. Collect unique photo clickable items (Primary: CompoundButton / Button with photo description)
    # Using a single specific selector class prevents multi-node duplicate matches!
    camera_images = bot.d(className="android.widget.CompoundButton", descriptionMatches=r"(?i).*Photo.*taken on.*|.*Photo, item \d+.*|.*Ảnh.*chụp.*|.*Ảnh, mục \d+.*")
    if not camera_images.exists or camera_images.count == 0:
        camera_images = bot.d(className="android.widget.Button", descriptionMatches=r"(?i).*Photo.*taken on.*|.*Photo, item \d+.*|.*Ảnh.*chụp.*|.*Ảnh, mục \d+.*")
    if not camera_images.exists or camera_images.count == 0:
        camera_images = bot.d(descriptionMatches=r"(?i)^Photo, item \d+.*|^Ảnh, mục \d+.*")
    if not camera_images.exists or camera_images.count == 0:
        camera_images = bot.d(descriptionMatches=r"(?i).*Photo.*taken on.*|.*Ảnh.*chụp.*")
    if not camera_images.exists or camera_images.count == 0:
        camera_images = bot.d(className="android.widget.CheckBox")

    if camera_images.exists and camera_images.count > 0:
        total_avail = camera_images.count
        actual_num = min(total_avail, target_num)
        bot.log(f"📸 Found {total_avail} photo items in Gallery. Selecting {actual_num} photo(s) in reverse order (5-4-3-2-1)...")

        # REVERSE ORDER: index actual_num-1 down to 0
        # This ensures the first pushed photo (at the right/bottom) is clicked first and marked as #1 in Facebook!
        for i in reversed(range(actual_num)):
            try:
                img_widget = camera_images[i]
                info = img_widget.info
                # Check if already checked/selected
                if info.get("checked") or info.get("selected"):
                    bot.log(f"   ℹ️ Photo item {i + 1} is already selected, skipping click.")
                    selected_count += 1
                    continue

                img_widget.click_exists(timeout=2)
                selected_count += 1
                bot.log(f"   ✔️ Selected photo item {i + 1}/{actual_num} (Pushed index: {actual_num - selected_count})")
                bot.smart_sleep(0.5, 0.8)
            except Exception as ce:
                logger.debug(f"Error selecting photo index {i}: {ce}")

        return selected_count

    bot.log("⚠️ Could not locate photo elements in Gallery.")
    return selected_count


# ==============================================================================
# STEP 9: CLICK 'NEXT' BUTTON AFTER PHOTO SELECTION
# ==============================================================================

def click_next_after_photos(bot: BaseAutomator, timeout: int = 15) -> bool:
    """
    STEP 9:
    - Clicks 'Next' / 'Tiếp' button to confirm selected photos and return to composer.
    - Dumps: tests/dumps/step_02_write_something/step_02.04.01
    """
    bot.log("➡️ [Step 9] Clicking 'Next' / 'Tiếp' button to confirm selected photos...")

    next_keywords = ["next", "tiếp", "tiếp tục", "xong", "done", "chọn", "thêm"]

    start_time = time.time()
    while time.time() - start_time < timeout:
        if not bot.d:
            break

        # Check if already back on composer view with Post button visible
        post_btn = bot.d(textMatches=r"(?i)^Post$|^Đăng$") or bot.d(descriptionMatches=r"(?i)^Post$|^Đăng$")
        if post_btn.exists:
            bot.log("ℹ️ Returned to composer form. Post button is visible.")
            return True

        # 1. By text
        for kw in next_keywords:
            btn = bot.d(textMatches=f"(?i)^{kw}$")
            if btn.exists:
                bot.log(f"👆 Clicking '{kw}' button (via text)...")
                btn.click()
                bot.smart_sleep(2.0, 3.0)
                return True

            desc_btn = bot.d(descriptionMatches=f"(?i)^{kw}$")
            if desc_btn.exists:
                bot.log(f"👆 Clicking '{kw}' button (via desc)...")
                desc_btn.click()
                bot.smart_sleep(2.0, 3.0)
                return True

            w_btn = bot.get_button_by_text(kw, timeout=1)
            if w_btn and w_btn.exists:
                bot.log(f"👆 Clicking widget '{kw}'...")
                w_btn.click()
                bot.smart_sleep(2.0, 3.0)
                return True

        bot.smart_sleep(1.0)

    bot.log("⚠️ Could not find Next button or already on composer form.")
    return True


# ==============================================================================
# STEP 10: CLICK 'POST' / 'ĐĂNG' BUTTON
# ==============================================================================

def click_post_button(bot: BaseAutomator, timeout: int = 25) -> bool:
    """
    STEP 10:
    - Finds and clicks 'Post' / 'Đăng' button in the top right of the composer.
    - Waits for post publication confirmation.
    - Dumps: tests/dumps/step_02_write_something/step_02.05
    """
    bot.log("🚀 [Step 10] Finding and clicking 'Post' / 'Đăng' button...")

    post_keywords = ["post", "đăng", "đăng bài", "publish", "chia sẻ"]

    start_time = time.time()
    clicked = False

    while time.time() - start_time < timeout:
        if not bot.d:
            break

        # 1. By exact text
        for kw in post_keywords:
            btn = bot.d(textMatches=f"(?i)^{kw}$")
            if btn.exists:
                bot.log(f"👆 Clicking '{kw}' button (via text)...")
                btn.click()
                clicked = True
                break

            desc_btn = bot.d(descriptionMatches=f"(?i)^{kw}$")
            if desc_btn.exists:
                bot.log(f"👆 Clicking '{kw}' button (via desc)...")
                desc_btn.click()
                clicked = True
                break

            w_btn = bot.get_button_by_text(kw, timeout=1)
            if w_btn and w_btn.exists:
                bot.log(f"👆 Clicking widget '{kw}'...")
                w_btn.click()
                clicked = True
                break

        if clicked:
            bot.log("⏳ Waiting for post to finish publishing...")
            bot.smart_sleep(4.0, 7.0)

            # Check if composer closed and returned to group feed
            write_box = bot.d(textMatches=r"(?i).*Write something.*|.*Viết gì đó.*|.*Bạn đang nghĩ gì.*")
            if write_box.exists or not bot.d(textMatches=r"(?i)^Post$|^Đăng$").exists:
                bot.log("🎉 Post successfully published!")
                return True
            else:
                bot.smart_sleep(2.0)
                return True

        bot.smart_sleep(1.0)

    if not clicked:
        bot.log("❌ Could not find or click 'Post' / 'Đăng' button.")
        raise Exception("❌ Could not find 'Post' / 'Đăng' button.")

    return True


# ==============================================================================
# MAIN FBDiscussionGroupAction CLASS
# ==============================================================================

class FBDiscussionGroupAction:
    """Facebook Group Discussion Post Action (discussion_group)."""

    def __init__(self, automator: BaseAutomator, account: Account):
        self.automator = automator
        self.account = account
        if hasattr(self.automator, "__dict__"):
            self.automator.account_uid = self.account.uid
        self.detector = CheckpointDetector(automator.device)
        self.v1_bridge = V1DatabaseBridge()
        self.ai_service = GeminiService()

    def execute_discussion_pipeline(
        self,
        content: str,
        image_paths: Optional[List[str]] = None,
        group_id: Optional[str] = None,
        transaction_type: Optional[str] = "rental"
    ) -> bool:
        """Executes full 10-step Discussion Group Posting pipeline on Redroid."""
        logger.info(f"Starting FB Discussion Group pipeline for account {self.account.uid} (transaction_type: '{transaction_type}')...")

        pushed_remotes = []
        current_step = "step_0_push_media"
        is_success = False

        try:
            # 0. Clean previous session media & cache, then push new images
            if self.automator.adb_client:
                logger.info("🧹 Preparing device storage and media permissions...")
                self.automator.adb_client.clear_media_storage()
                self.automator.adb_client.clear_facebook_cache()
                self.automator.adb_client.ensure_storage_ready()
                self.automator.adb_client.grant_app_permissions("com.facebook.katana")

                if image_paths:
                    logger.info(f"Pushing {len(image_paths)} image(s) to Redroid gallery in order 0..N-1...")
                    for idx, img in enumerate(image_paths):
                        if not os.path.exists(img):
                            logger.warning(f"Image not found on host: {img}")
                            continue
                        ext = Path(img).suffix.lower() or ".jpg"
                        remote_path = f"/sdcard/DCIM/Camera/discussion_{idx}{ext}"
                        if self.automator.adb_client.push_file(img, remote_path):
                            pushed_remotes.append(remote_path)
                            self.automator.adb_client.scan_media_file(remote_path)
                        else:
                            logger.error(f"Failed to push image to Redroid: {img}")
                    time.sleep(1.5)

            # Step 1: Open Facebook Groups tab list via deeplink
            current_step = "step_1_open_groups_tab_list"
            open_groups_tab_list(self.automator, timeout=20)

            # Checkpoint check
            is_cp, cp_msg = self.detector.is_checkpoint()
            if is_cp:
                current_step = "checkpoint_detected"
                AccountRepository.update_status(self.account.uid, AccountStatus.CHECKPOINT, cp_msg)
                return False

            # Step 2: Select random group matching transaction_type (with scroll)
            current_step = "step_2_select_random_group"
            if group_id:
                logger.info(f"Using explicitly specified group ID: {group_id}")
                deeplink = f"fb://group/{group_id}"
                self.automator.launch(deeplink=deeplink)
                self.automator.smart_sleep(3.0, 5.0)
            else:
                select_random_group_by_transaction_type(
                    self.automator,
                    transaction_type=transaction_type,
                    max_scrolls=2,
                    timeout=15
                )

            # Step 3: Click 'Write something...'
            current_step = "step_3_click_write_something"
            click_write_something_button(self.automator, timeout=15)

            # Step 4: Click 'Create your post...' input field
            current_step = "step_4_click_create_post_field"
            click_create_post_input_field(self.automator, timeout=15)

            # Step 5: Input rewritten AI / template content
            current_step = "step_5_paste_content"
            paste_discussion_content(self.automator, content=content, timeout=15)

            # Step 6: Click 'Done' / 'Next'
            current_step = "step_6_click_done_or_next"
            click_done_or_next_button(self.automator, timeout=10)

            # Step 7 & 8: If images available, open Gallery and select photos
            if image_paths and pushed_remotes:
                # Step 7: Click 'Gallery' button
                current_step = "step_7_click_gallery_button"
                click_gallery_button(self.automator, timeout=15)

                # Step 8: Select pushed images in reverse (5-4-3-2-1) order
                current_step = "step_8_select_pushed_images"
                photo_count = min(len(image_paths), 5)
                select_pushed_images(self.automator, photo_count=photo_count, timeout=15)

                # Step 9: Click 'Next' to confirm photos
                current_step = "step_9_click_next_after_photos"
                click_next_after_photos(self.automator, timeout=15)

            # Step 10: Click 'Post' / 'Đăng'
            current_step = "step_10_click_post_button"
            click_post_button(self.automator, timeout=25)

            is_success = True
            logger.info(f"✅ Successfully completed Discussion Group action for account {self.account.uid}!")
            return True

        except Exception as e:
            logger.exception(f"Error during Discussion Group execution at {current_step}: {e}")
            return False

        finally:
            if not is_success:
                logger.error(f"Execution failed at {current_step}. Dumping error view...")
                dump_error_view(self.automator, account_uid=self.account.uid, step_name=f"error_{current_step}")
            if pushed_remotes:
                logger.info(f"Cleaning up {len(pushed_remotes)} temporary image(s) from device storage...")
                for r_path in pushed_remotes:
                    self.automator.adb_client.remove_file(r_path)

    def execute(
        self,
        use_v1_product: bool = True,
        use_ai: bool = True,
        group_id: Optional[str] = None,
        custom_content: Optional[str] = None,
        image_paths: Optional[List[str]] = None,
        transaction_type: Optional[str] = None
    ) -> bool:
        """
        Public entry point for 'discussion_group' action.
        - Fetches real estate listing from v1 DB if use_v1_product is True.
        - Rewrites post using Gemini AI in 100% natural Vietnamese if use_ai is True.
        - Executes the 10-step UIAutomator2 pipeline.
        """
        logger.info(f"Preparing Discussion Group action for {self.account.uid} (use_v1_product={use_v1_product}, use_ai={use_ai})...")

        category = getattr(self.account, 'category', 'real_estate') or 'real_estate'
        trans_type = transaction_type or getattr(self.account, 'transaction_type', 'rental') or 'rental'

        images: List[str] = list(image_paths or [])
        content: str = ""

        if use_v1_product:
            product = self.v1_bridge.get_random_product_for_account(self.account)
            if not product:
                logger.warning(f"No active product found for category '{category}', transaction_type '{trans_type}' in v1 DB. Using fallback content.")
                content = custom_content or "Thảo luận chia sẻ bất động sản chính chủ Đà Lạt."
            else:
                # Synchronize trans_type with the fetched product
                prod_trans = str(product.get("transaction_type", "")).lower().strip()
                if prod_trans in ("rental", "1", "thue", "cho_thue"):
                    trans_type = "rental"
                elif prod_trans in ("sale", "0", "ban", "mua_ban"):
                    trans_type = "sale"

                is_rental = trans_type == "rental"
                raw_title, raw_desc = self.v1_bridge.format_product_summary(product)
                if not images:
                    images = self.v1_bridge.get_product_images(str(product.get("id")))[:5]

                if use_ai:
                    logger.info(f"Calling Gemini AI to rewrite discussion post (is_rental={is_rental})...")
                    rewritten = self.ai_service.rewrite_real_estate_post(raw_title, raw_desc, is_rental=is_rental)
                    if rewritten and len(rewritten.strip()) >= 15 and not rewritten.strip().startswith("```"):
                        content = rewritten.strip()
                    else:
                        content = f"{raw_title}\n\n{raw_desc}"
                else:
                    content = f"{raw_title}\n\n{raw_desc}"
        else:
            if custom_content:
                content = custom_content
            else:
                content = "Thảo luận bài viết bất động sản chính chủ Đà Lạt."

        return self.execute_discussion_pipeline(
            content=content,
            image_paths=images,
            group_id=group_id,
            transaction_type=trans_type
        )
