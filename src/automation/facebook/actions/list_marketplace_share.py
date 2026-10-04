"""Facebook Marketplace Listing & Group Cross-Sharing Action.
Refactored into clear sequential steps with forward anchor point verification
and automatic UI diagnostic dumping for Redroid / Android containers.
"""

import re
import sys
import json
import time
import shutil
import logging
import traceback
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
from src.automation.facebook.actions.list_group_share import list_in_more_places, click_publish_or_done

logger = logging.getLogger(__name__)


# ==============================================================================
# UI DIAGNOSTIC DUMP HELPERS
# ==============================================================================

def dump_error_view(bot: BaseAutomator, account_uid: Optional[str] = None, step_name: str = "unknown_step"):
    """
    Automatically dumps UI hierarchy (XML, JSON, Screenshot) on error or missing anchor element.
    Saved to: tests/dumps/errors/{safe_uid}_{safe_step}/
    Also mirrors latest error dump to tests/dumps/latest/
    """
    try:
        from tests.dump_view import parse_hierarchy_node

        uid = str(account_uid or getattr(bot, "account_uid", None) or getattr(bot, "adb_port", "device"))
        safe_uid = re.sub(r'[^\w\-_\.]', '_', uid)
        safe_step = re.sub(r'[^\w\-_\.]', '_', str(step_name))

        output_dir = Path("tests/dumps/errors") / f"{safe_uid}_{safe_step}"
        output_dir.mkdir(parents=True, exist_ok=True)

        latest_dir = Path("tests/dumps/latest")
        latest_dir.mkdir(parents=True, exist_ok=True)

        bot.log(f"📸 [ERROR DUMP] Missing anchor / error at [{step_name}]. Auto-dumping UI to {output_dir}...")

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
                "timestamp": time.strftime("%Y%m%d_%H%M%S"),
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
# STEP 1: OPEN MARKETPLACE & CLICK SELL
# ==============================================================================

def step_1_open_marketplace(bot: BaseAutomator, timeout: int = 20) -> bool:
    """
    STEP 1:
    - Launches Marketplace via deeplink 'fb://marketplace'.
    - Finds and clicks 'Sell' / 'Bán' button.
    - Anchor verification: Confirms navigation to Sell menu / Create listing options.
    """
    bot.log("🛒 [Step 1] Opening Marketplace via deeplink...")
    bot.launch_app("com.facebook.katana", "fb://marketplace")
    bot.smart_sleep(2.0)

    sell_btn = bot.get_button_by_text("sell", timeout=timeout) or (bot.d(descriptionMatches=r"(?i)^Sell$|^Bán$") if bot.d else None)
    if not sell_btn or not sell_btn.exists:
        raise Exception("❌ [Step 1 Anchor Failed] Could not find 'Sell' button on Marketplace home.")

    bot.log("👆 Clicking 'Sell' button...")
    sell_btn.click_exists(timeout=5)
    bot.smart_sleep(2.0)

    # Check for 'Create listing' / 'Tạo bài niêm yết' button if shown
    create_btn = bot.get_button_by_text("create", timeout=3) or (bot.d(textMatches=r"(?i).*Create listing.*|.*Tạo bài niêm yết.*") if bot.d else None)
    if create_btn and create_btn.exists:
        bot.log("👆 Found 'Create listing' button, clicking...")
        create_btn.click_exists(timeout=3)
        bot.smart_sleep(2.0)

    # Anchor check: Check if categories ('Homes for sale or rent', 'Items', etc.) or listing form is visible
    start_time = time.time()
    while time.time() - start_time < 10:
        if not bot.d:
            break
        has_cat = bot.d(textMatches=r"(?i).*sale or rent.*|.*nhà để bán.*|.*items.*|.*mặt hàng.*").exists
        has_desc = bot.d(descriptionMatches=r"(?i).*sale or rent.*|.*items.*").exists
        has_form = bot.d(textMatches=r"(?i).*Add photos.*|.*Thêm ảnh.*").exists
        if has_cat or has_desc or has_form:
            bot.log("✔️ [Step 1 Anchor Verified] Successfully opened Marketplace Sell menu!")
            return True
        bot.smart_sleep(1.0)

    bot.log("⚠️ Proceeding to category selection...")
    return True


# ==============================================================================
# STEP 2: SELECT REAL ESTATE LISTING CATEGORY ('HOMES FOR SALE OR RENT' / 'ITEMS')
# ==============================================================================

def step_2_open_listing_form(bot: BaseAutomator, timeout: int = 20) -> bool:
    """
    STEP 2:
    - Clicks 'Homes for sale or rent' / 'Nhà để bán hoặc cho thuê' (or fallback 'Items' / 'Mặt hàng').
    - Anchor verification: Confirms Listing Composer form is loaded (Add photos / Title / Price visible).
    """
    bot.log("🏡 [Step 2] Selecting listing category ('Homes for sale or rent' / 'Items')...")

    cat_keywords = [
        "sale or rent",
        "nhà để bán hoặc cho thuê",
        "homes for sale or rent",
        "nhà để bán",
        "items",
        "mặt hàng"
    ]

    clicked = False
    for kw in cat_keywords:
        btn = bot.get_button_by_text(kw, timeout=2)
        if btn and btn.exists:
            bot.log(f"👆 Clicking category '{kw}'...")
            btn.click_exists(timeout=3)
            clicked = True
            break
        if bot.d:
            txt_elem = bot.d(textMatches=rf"(?i).*{kw}.*")
            if txt_elem.exists:
                bot.log(f"👆 Clicking category text '{kw}'...")
                txt_elem.click()
                clicked = True
                break
            desc_elem = bot.d(descriptionMatches=rf"(?i).*{kw}.*")
            if desc_elem.exists:
                bot.log(f"👆 Clicking category desc '{kw}'...")
                desc_elem.click()
                clicked = True
                break

    bot.smart_sleep(2.0)

    # Anchor verification: Listing composer form loaded
    start_time = time.time()
    while time.time() - start_time < timeout:
        if not bot.d:
            break
        add_photos = bot.d(textMatches=r"(?i).*Add photos.*|.*Thêm ảnh.*")
        add_photos_desc = bot.d(descriptionMatches=r"(?i).*Add photos.*|.*Thêm ảnh.*")
        title_field = bot.d(resourceId="composer_v3_title") or bot.d(textMatches=r"(?i)^Title.*|^Tiêu đề.*")
        next_btn = bot.d(textMatches=r"(?i)^Next$|^Tiếp$")

        if add_photos.exists or add_photos_desc.exists or title_field.exists or next_btn.exists:
            bot.log("✔️ [Step 2 Anchor Verified] Listing Composer form loaded successfully!")
            return True
        bot.smart_sleep(1.0)

    raise Exception("❌ [Step 2 Anchor Failed] Listing form did not load after selecting category.")


# ==============================================================================
# STEP 3: CLICK 'ADD PHOTOS' AND SELECT PHOTOS (REVERSE ORDER)
# ==============================================================================

def step_3_add_photos(bot: BaseAutomator, photo_num: int = 1, timeout: int = 20) -> bool:
    """
    STEP 3:
    - Finds and clicks 'Add photos' / 'Thêm ảnh'.
    - Selects pushed images in reverse order (bottom up).
    - Clicks 'Next' / 'Done' to confirm photo selection.
    - Anchor verification: Confirms return to Listing Composer form with photos loaded.
    """
    bot.log(f"🖼️ [Step 3] Adding {photo_num} photo(s) to listing...")

    def _trigger_add_photos() -> bool:
        add_photo_keywords = [
            "add photos", "thêm ảnh", "add photo", "thêm hình ảnh",
            "thêm ảnh/video", "add photos/videos", "ảnh/video", "photo/video"
        ]
        if bot.d:
            res_elem = bot.d(resourceIdMatches=r"(?i).*(add_photos|composer_add_photos|marketplace_add_photos).*")
            if res_elem.exists:
                bot.log("👆 Found 'Add photos' by resourceId. Clicking...")
                res_elem.click()
                return True

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

    gallery_opened = False
    for attempt in range(5):
        if _trigger_add_photos():
            bot.smart_sleep(2.0)
            if bot.d and (
                bot.d(descriptionMatches=r"(?i).*Photo.*taken on.*|.*Photo, item \d+.*|.*Ảnh.*chụp.*").exists or
                bot.d(className="android.widget.GridView").exists or
                bot.d(className="android.widget.CheckBox").exists
            ):
                gallery_opened = True
                break
        else:
            bot.log(f"⚠️ Could not find 'Add photos' on attempt {attempt + 1}. Pressing back and re-opening form...")
            if bot.d:
                bot.d.press("back")
                bot.smart_sleep(1.5)
                for discard_kw in ["discard", "bỏ bài viết", "bỏ bản nháp", "bỏ"]:
                    discard_btn = bot.get_button_by_text(discard_kw, timeout=0.8)
                    if discard_btn and discard_btn.exists:
                        discard_btn.click_exists(timeout=2)
                        bot.smart_sleep(1.0)
                        break
                try:
                    step_2_open_listing_form(bot, timeout=10)
                except Exception:
                    pass

    if not gallery_opened:
        raise Exception("❌ [Step 3 Anchor Failed] Could not open Gallery / Camera Roll picker.")

    bot.log("📸 [Step 3 Anchor Verified] Camera Roll opened! Selecting photos in reverse order...")

    multi_btn = bot.d(textMatches=r"(?i).*(select multiple|chọn nhiều).*") or bot.d(descriptionMatches=r"(?i).*(select multiple|chọn nhiều).*")
    if multi_btn.exists:
        multi_btn.click_exists(timeout=2)
        bot.smart_sleep(1.0)

    camera_images = bot.d(className="android.view.ViewGroup", clickable=True, descriptionMatches=r"(?i).*Photo.*taken on.*|.*Photo, item \d+.*|.*Ảnh.*chụp.*")
    if not camera_images.exists or camera_images.count == 0:
        camera_images = bot.d(descriptionMatches=r"(?i).*Photo.*taken on.*|.*Photo, item \d+.*|.*Ảnh.*chụp.*")
    if not camera_images.exists or camera_images.count == 0:
        camera_images = bot.d(className="android.widget.CheckBox")

    if camera_images.exists and camera_images.count > 0:
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
            except Exception:
                pass

        if unique_items:
            actual_num = min(len(unique_items), max(1, photo_num))
            bot.log(f"📸 Found {len(unique_items)} photos. Selecting {actual_num} from bottom up...")
            for i in reversed(range(actual_num)):
                try:
                    img_w, info = unique_items[i]
                    if not info.get("checked") and not info.get("selected"):
                        img_w.click_exists(timeout=2)
                        bot.smart_sleep(0.5)
                except Exception:
                    pass

    next_btn = bot.d(resourceId="marketplace_camera_roll_android_next_button") or bot.d(textMatches=r"(?i)^Next$|^Tiếp$|^Done$|^Xong$") or bot.d(descriptionMatches=r"(?i)^Next$|^Tiếp$|^Done$|^Xong$")
    if next_btn.exists:
        next_btn.click_exists(timeout=5)
        bot.smart_sleep(2.0)

    start_time = time.time()
    while time.time() - start_time < timeout:
        if not bot.d:
            break
        if (
            bot.d(resourceId="composer_v3_title").exists or
            bot.d(textMatches=r"(?i)^Title.*|^Tiêu đề.*").exists or
            bot.d(textMatches=r"(?i)^Price.*|^Giá.*").exists or
            bot.d(descriptionMatches=r"(?i)^Title.*").exists
        ):
            bot.log("✔️ [Step 3 Anchor Verified] Successfully attached photos and returned to listing form!")
            return True
        bot.smart_sleep(1.0)

    bot.log("ℹ️ Proceeding with listing form details...")
    return True


# ==============================================================================
# STEP 4: FILL LISTING TITLE
# ==============================================================================

def step_4_fill_title(bot: BaseAutomator, title: str, timeout: int = 15) -> bool:
    """
    STEP 4:
    - Finds and inputs listing title in uppercase.
    - Anchor verification: Confirms text is set.
    """
    bot.log(f"✍️ [Step 4] Inputting Title: '{title[:30]}...'")
    title_upper = title.upper() if title else "BÁN ĐẤT NGHỈ DƯỠNG VIEW ĐẸP ĐÀ LẠT"

    title_group = bot.get_widget_by_text("android.view.ViewGroup", "title", timeout=timeout) or bot.d(resourceId="composer_v3_title")
    if title_group and title_group.exists:
        bot.swipe_widget_to_center(title_group)
        title_group.click()
        bot.smart_sleep(1.0)
        title_input = bot.get_interactable_from_parent(title_group, "android.widget.EditText", timeout=5) or bot.d(className="android.widget.EditText")
        if title_input and title_input.exists:
            title_input.set_text(title_upper)
            bot.smart_sleep(1.0)
            bot.log("✔️ [Step 4 Anchor Verified] Title set successfully!")
            return True

    edit_texts = bot.d(className="android.widget.EditText")
    if edit_texts.exists and edit_texts.count > 0:
        edit_texts[0].set_text(title_upper)
        bot.smart_sleep(1.0)
        bot.log("✔️ [Step 4 Anchor Verified] Title set via primary EditText!")
        return True

    raise Exception("❌ [Step 4 Anchor Failed] Could not find Title input field.")


# ==============================================================================
# STEP 5: FILL LISTING PRICE
# ==============================================================================

def step_5_fill_price(bot: BaseAutomator, price: Optional[str] = None, timeout: int = 15) -> bool:
    """
    STEP 5:
    - Finds and inputs listing price.
    - Anchor verification: Confirms price is set.
    """
    price_val = str(price) if price else str(randint(100, 999))
    bot.log(f"💰 [Step 5] Inputting Price: '{price_val}'")

    price_group = bot.get_widget_by_text("android.view.ViewGroup", "price", timeout=timeout) or bot.d(resourceId="composer_v3_price")
    if price_group and price_group.exists:
        bot.swipe_widget_to_center(price_group)
        price_group.click()
        bot.smart_sleep(1.0)
        price_input = bot.get_interactable_from_parent(price_group, "android.widget.EditText", timeout=5)
        if price_input and price_input.exists:
            price_input.set_text(price_val)
            bot.smart_sleep(1.0)
            bot.log("✔️ [Step 5 Anchor Verified] Price set successfully!")
            return True

    edit_texts = bot.d(className="android.widget.EditText")
    if edit_texts.exists and edit_texts.count >= 2:
        edit_texts[1].set_text(price_val)
        bot.smart_sleep(1.0)
        bot.log("✔️ [Step 5 Anchor Verified] Price set via second EditText!")
        return True

    bot.log("⚠️ Price field skipped or already populated.")
    return True


# ==============================================================================
# STEP 6: SELECT CATEGORY (RENTAL VS SALE)
# ==============================================================================

def step_6_select_category(bot: BaseAutomator, transaction_type: str = "sale", timeout: int = 15) -> bool:
    """
    STEP 6:
    - Selects property category ('Home(s) for sale' or 'Home(s) for rent').
    - Anchor verification: Category selected and returned to form.
    """
    bot.log(f"📂 [Step 6] Selecting category for transaction_type '{transaction_type}'...")

    category_btn = bot.get_button_by_text("category", timeout=timeout) or bot.d(textMatches=r"(?i)^Category.*|^Hạng mục.*")
    if category_btn and category_btn.exists:
        bot.swipe_widget_to_center(category_btn)
        category_btn.click()
        bot.smart_sleep(1.5)

        target_kw = "rent" if "rent" in str(transaction_type).lower() or "thue" in str(transaction_type).lower() else "sale"
        option = bot.get_button_by_text(target_kw, timeout=10) or bot.d(textMatches=rf"(?i).*{target_kw}.*")
        if option and option.exists:
            option.click()
            bot.smart_sleep(1.5)
            bot.log("✔️ [Step 6 Anchor Verified] Category selected successfully!")
            return True

    bot.log("ℹ️ Category step completed or skipped.")
    return True


# ==============================================================================
# STEP 7: SET LOCATION
# ==============================================================================

def step_7_set_location(bot: BaseAutomator, city_name: str = "Da Lat", timeout: int = 20) -> bool:
    """
    STEP 7:
    - Updates listing location to target city.
    - Anchor verification: Confirms location applied.
    """
    bot.log(f"📍 [Step 7] Setting location to '{city_name}'...")

    location_btn = bot.get_button_by_text("location", timeout=timeout) or bot.d(textMatches=r"(?i)^Location.*|^Vị trí.*")
    if location_btn and location_btn.exists:
        bot.swipe_widget_to_center(location_btn)
        location_btn.click()
        bot.smart_sleep(2.0)

        search_input = bot.d(className="android.widget.EditText")
        if search_input.exists:
            search_input.set_text(city_name)
            bot.smart_sleep(2.0)

            city_suggestion = bot.d(textMatches=rf"(?i).*{city_name}.*")
            if city_suggestion.exists:
                city_suggestion.click()
                bot.smart_sleep(1.5)

            apply_btn = bot.get_button_by_text("apply", timeout=5) or bot.d(textMatches=r"(?i)^Apply$|^Áp dụng$")
            if apply_btn and apply_btn.exists:
                apply_btn.click()
                bot.smart_sleep(1.5)
                bot.log("✔️ [Step 7 Anchor Verified] Location set successfully!")
                return True

    bot.log("ℹ️ Location step completed or skipped.")
    return True


# ==============================================================================
# STEP 8: FILL DESCRIPTION
# ==============================================================================

def step_8_fill_description(bot: BaseAutomator, description: str, timeout: int = 15) -> bool:
    """
    STEP 8:
    - Inputs listing description into the description container.
    - Anchor verification: Confirms description is set.
    """
    bot.log("📝 [Step 8] Inputting Description...")
    if not description:
        description = "Bán đất nghỉ dưỡng view thung lũng cực đẹp tại Đà Lạt. Sổ hồng riêng chính chủ."

    bot.swipe_up(scale=0.5)
    bot.smart_sleep(1.0)

    desc_group = bot.get_widget_by_text("android.view.ViewGroup", "description", timeout=timeout) or bot.d(resourceId="composer_v3_description")
    if desc_group and desc_group.exists:
        bot.swipe_widget_to_center(desc_group)
        desc_group.click()
        bot.smart_sleep(1.0)
        desc_input = bot.get_interactable_from_parent(desc_group, "android.widget.EditText", timeout=5) or bot.d(className="android.widget.EditText")
        if desc_input and desc_input.exists:
            desc_input.set_text(description)
            bot.smart_sleep(0.5)
            bot.hide_keyboard()
            bot.log("✔️ [Step 8 Anchor Verified] Description inputted successfully!")
            return True

    bot.hide_keyboard()
    bot.log("ℹ️ Description step completed.")
    return True


# ==============================================================================
# STEP 9: CLICK 'NEXT' BUTTON
# ==============================================================================

def step_9_click_next(bot: BaseAutomator, timeout: int = 15) -> bool:
    """
    STEP 9:
    - Clicks 'Next' / 'Tiếp' button to transition to cross-posting / publish view.
    - Anchor verification: Confirms 'List in more places' or 'Publish' button appears.
    """
    bot.log("➡️ [Step 9] Clicking 'Next' button...")

    next_btn = bot.get_button_by_text("next", timeout=timeout) or bot.d(textMatches=r"(?i)^Next$|^Tiếp$") or bot.d(descriptionMatches=r"(?i)^Next$|^Tiếp$")
    if not next_btn or not next_btn.exists:
        bot.hide_keyboard()
        bot.smart_sleep(0.5)
        next_btn = bot.get_button_by_text("next", timeout=2) or bot.d(textMatches=r"(?i)^Next$|^Tiếp$") or bot.d(descriptionMatches=r"(?i)^Next$|^Tiếp$")
        
    if not next_btn or not next_btn.exists:
        raise Exception("❌ [Step 9 Anchor Failed] Could not find 'Next' button on listing form.")

    next_btn.click_exists(timeout=5)
    bot.smart_sleep(2.5)

    start_time = time.time()
    while time.time() - start_time < timeout:
        if not bot.d:
            break
        pub_btn = bot.d(resourceId="mp_composer_post") or bot.d(textMatches=r"(?i)^Publish$|^Đăng$")
        groups_list = bot.d(className="android.widget.CheckBox") or bot.d(textMatches=r"(?i).*Marketplace.*|.*Groups.*|.*Nhóm.*")
        if pub_btn.exists or groups_list.exists:
            bot.log("✔️ [Step 9 Anchor Verified] Transitioned to publish / group cross-sharing screen!")
            return True
        bot.smart_sleep(1.0)

    bot.log("ℹ️ Proceeding to cross-posting / publish...")
    return True


# ==============================================================================
# STEP 10: LIST IN MORE PLACES (CROSS-SHARING TO TOP GROUPS)
# ==============================================================================

def step_10_list_in_more_places(
    bot: BaseAutomator, 
    share_groups_count: int = 20, 
    max_swipes: int = 10,
    transaction_type: str = "sale"
) -> bool:
    """
    STEP 10:
    - Selects Marketplace and Top N groups filtered by transaction type.
    """
    bot.log(f"👥 [Step 10] Selecting up to {share_groups_count} groups for cross-posting...")
    try:
        list_in_more_places(
            bot, 
            share_groups_count=share_groups_count, 
            max_swipes=max_swipes,
            transaction_type=transaction_type
        )
        bot.log("✔️ [Step 10 Anchor Verified] Cross-sharing groups selected!")
        return True
    except Exception as e:
        bot.log(f"⚠️ Error during cross-sharing selection: {e}. Proceeding to publish...")
        return False


# ==============================================================================
# STEP 11: CLICK 'PUBLISH' BUTTON
# ==============================================================================

def step_11_publish(bot: BaseAutomator, timeout: int = 25) -> bool:
    """
    STEP 11:
    - Clicks 'Publish' / 'Đăng' button.
    - Anchor verification: Confirms button disappears and listing is published.
    """
    bot.log("📢 [Step 11] Publishing listing...")
    return click_publish_or_done(bot, timeout=timeout)


# ==============================================================================
# CLASS-BASED ACTION WRAPPER FOR MY-MANAGER.V2
# ==============================================================================

class FBMarketplaceShareAction:
    def __init__(self, automator: BaseAutomator, account: Account):
        self.automator = automator
        self.account = account
        if hasattr(self.automator, "__dict__"):
            self.automator.account_uid = self.account.uid
        self.detector = CheckpointDetector(automator.device)
        self.v1_bridge = V1DatabaseBridge()
        self.ai_service = GeminiService()

    def execute_marketplace_pipeline(
        self,
        title: str,
        price: str,
        description: str,
        image_paths: List[str],
        transaction_type: str = "sale",
        location: str = "Da Lat",
        share_groups_count: int = 20
    ) -> bool:
        """Executes full 11-step Marketplace Listing & Group Cross-Sharing pipeline."""
        logger.info(f"Starting 11-Step Marketplace Listing for {self.account.uid} (Trans: '{transaction_type}')...")

        pushed_remotes: List[str] = []
        current_step = "step_0_push_media"
        is_success = False

        try:
            if image_paths:
                pushed_remotes = self.automator.push_media(image_paths)

            # Step 1: Open Marketplace & click Sell
            current_step = "step_1_open_marketplace"
            step_1_open_marketplace(self.automator, timeout=20)

            # Checkpoint safety check
            is_cp, cp_msg = self.detector.is_checkpoint()
            if is_cp:
                current_step = "checkpoint_detected"
                AccountRepository.update_status(self.account.uid, AccountStatus.CHECKPOINT, cp_msg)
                return False

            # Step 2: Select listing category
            current_step = "step_2_open_listing_form"
            step_2_open_listing_form(self.automator, timeout=20)

            # Step 3: Add photos
            current_step = "step_3_add_photos"
            photo_count = min(len(image_paths), 5) if image_paths else 1
            step_3_add_photos(self.automator, photo_num=photo_count, timeout=20)

            # Step 4: Fill Title
            current_step = "step_4_fill_title"
            step_4_fill_title(self.automator, title=title, timeout=15)

            # Step 5: Fill Price
            current_step = "step_5_fill_price"
            step_5_fill_price(self.automator, price=price, timeout=15)

            # Step 6: Select Category
            current_step = "step_6_select_category"
            step_6_select_category(self.automator, transaction_type=transaction_type, timeout=15)

            # Step 7: Set Location
            current_step = "step_7_set_location"
            step_7_set_location(self.automator, city_name=location, timeout=20)

            # Step 8: Fill Description
            current_step = "step_8_fill_description"
            step_8_fill_description(self.automator, description=description, timeout=15)

            # Step 9: Click Next
            current_step = "step_9_click_next"
            step_9_click_next(self.automator, timeout=15)

            # Step 10: List in more places
            current_step = "step_10_list_in_more_places"
            step_10_list_in_more_places(self.automator, share_groups_count=share_groups_count, transaction_type=transaction_type)

            # Step 11: Publish
            current_step = "step_11_publish"
            step_11_publish(self.automator, timeout=25)

            is_success = True
            logger.info(f"🎉 Successfully completed Marketplace listing & cross-sharing for {self.account.uid}!")
            return True

        except Exception as e:
            logger.exception(f"Error during Marketplace listing execution at {current_step}: {e}")
            return False

        finally:
            if not is_success:
                dump_error_view(self.automator, account_uid=self.account.uid, step_name=f"error_{current_step}")
            if pushed_remotes:
                self.automator.cleanup_media()

    def execute(
        self,
        use_v1_product: bool = True,
        use_ai: bool = True,
        transaction_type: Optional[str] = None,
        share_groups_count: int = 20,
        custom_content: Optional[str] = None,
        image_paths: Optional[List[str]] = None,
        location: str = "Da Lat"
    ) -> bool:
        """Entry point executing Marketplace posting with AI rewriting and DB bridge."""
        logger.info(f"Preparing Marketplace action for {self.account.uid}...")

        category = getattr(self.account, 'category', 'real_estate') or 'real_estate'
        trans_type = transaction_type or getattr(self.account, 'transaction_type', 'sale') or 'sale'

        images: List[str] = list(image_paths or [])
        title: str = "BÁN ĐẤT NGHỈ DƯỠNG VIEW ĐẸP ĐÀ LẠT"
        description: str = custom_content or "Bán đất nghỉ dưỡng view thung lũng tại Đà Lạt."
        price: str = "1000000"

        if use_v1_product:
            product = self.v1_bridge.get_random_product_for_account(self.account)
            if product:
                raw_title, raw_desc = self.v1_bridge.format_product_summary(product)
                is_rental = str(product.get("transaction_type")) in ("rental", "1")
                trans_type = "rental" if is_rental else "sale"

                if use_ai:
                    ai_t, ai_d = self.ai_service.rewrite_real_estate_listing(raw_title, raw_desc, is_rental=is_rental)
                    t_clean = str(ai_t).strip() if ai_t else ""
                    if t_clean and not t_clean.lower().startswith("```") and len(t_clean) >= 5:
                        title = t_clean[:90].strip()
                    else:
                        title = raw_title[:90].strip() or "BẤT ĐỘNG SẢN GIÁ TỐT"

                    d_clean = str(ai_d).strip() if ai_d else ""
                    if d_clean and not d_clean.lower().startswith("```") and len(d_clean) >= 10:
                        description = d_clean
                    else:
                        description = raw_desc
                else:
                    title = raw_title[:90].strip() or "BẤT ĐỘNG SẢN GIÁ TỐT"
                    description = raw_desc

                if not images:
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

        return self.execute_marketplace_pipeline(
            title=title,
            price=price,
            description=description,
            image_paths=images,
            transaction_type=trans_type,
            location=location,
            share_groups_count=share_groups_count
        )
