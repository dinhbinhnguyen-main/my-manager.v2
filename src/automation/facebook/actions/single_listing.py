"""Facebook Single Listing Action (single_listing).
Iterates over N groups (default: 3 groups):
- Opens Facebook Groups Tab List via deeplink ('fb://groups/tab/list').
- Selects random group matching transaction_type (excluding already posted groups).
- Dynamically analyzes group interface (Buy & Sell vs Discussion):
    - If Buy & Sell group ('What are you selling?' / 'Bạn đang bán gì?'):
        Executes listing flow: (Click sell -> Add photos -> Fill Adaptive Form -> Next -> Direct Publish).
    - If Discussion group ('Write something...' / 'Bạn viết gì đi...'):
        Executes discussion post flow: (Write text -> Add photos -> Next -> Post).
"""

import re
import sys
import json
import time
import shutil
import random
import logging
import traceback
from pathlib import Path
import xml.etree.ElementTree as ET
from typing import List, Dict, Any, Optional, Set, Tuple

from src.core.models import Account, AccountStatus
from src.db.repository import AccountRepository
from src.automation.base_automator import BaseAutomator
from src.automation.checkpoint_handler import CheckpointDetector, check_and_handle_identity_confirmation
from src.services.v1_bridge import V1DatabaseBridge
from src.ai.gemini_service import GeminiService

from src.automation.facebook.actions.discussion_group import (
    open_groups_tab_list,
    is_group_matching_transaction_type,
    _is_system_button,
    click_write_something_button,
    click_create_post_input_field,
    paste_discussion_content,
    click_done_or_next_button,
    click_gallery_button,
    select_pushed_images,
    click_next_after_photos,
    click_post_button,
)

from src.automation.facebook.actions.list_group_share import (
    click_what_are_you_selling,
    click_add_photos as click_add_photos_listing,
    fill_listing_details,
    click_next_button as click_next_listing,
    click_publish_or_done
)

logger = logging.getLogger(__name__)


# ==============================================================================
# UI DIAGNOSTIC DUMP HELPERS
# ==============================================================================

def dump_error_view(bot: BaseAutomator, account_uid: Optional[str] = None, step_name: str = "unknown_step"):
    """
    Automatically dumps UI hierarchy (XML, JSON, Screenshot) on error or missing anchor elements.
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
# GROUP SELECTION WITH EXCLUSION SET
# ==============================================================================

def select_random_group_with_exclusion(
    bot: BaseAutomator,
    transaction_type: Optional[str] = "rental",
    excluded_groups: Optional[Set[str]] = None,
    max_scrolls: int = 2,
    timeout: int = 15
) -> str:
    """
    Scans groups in 'Your groups' tab and selects a random group matching transaction_type,
    excluding groups that were already posted to in this session.
    """
    bot.log(f"🔍 Selecting random group matching transaction_type '{transaction_type}'...")

    if not bot.d:
        raise Exception("Device is not connected.")

    excluded = excluded_groups or set()

    # 1. Perform random scrolling to discover more groups
    actual_scrolls = random.randint(1, max(1, max_scrolls))
    bot.log(f"📜 Scrolling down {actual_scrolls} time(s) to discover groups...")
    for _ in range(actual_scrolls):
        bot.swipe_up(scale=random.uniform(0.4, 0.7))
        bot.smart_sleep(1.5)

    seen_titles: Set[str] = set()
    priority_candidates: List[Tuple[Any, str]] = []
    secondary_candidates: List[Tuple[Any, str]] = []

    def _collect_groups():
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

                # Skip already posted groups
                if group_title in excluded:
                    bot.log(f"   ⏩ Skipping already posted group: '{group_title}'")
                    continue

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

    _collect_groups()

    if not priority_candidates and not secondary_candidates:
        bot.log("ℹ️ No available groups on current view, scrolling slightly up to re-check...")
        bot.swipe_down(scale=0.3)
        bot.smart_sleep(1.5)
        _collect_groups()

    pool = priority_candidates if priority_candidates else secondary_candidates
    if not pool:
        bot.log(f"❌ No suitable new group found for transaction_type '{transaction_type}' (Excluded {len(excluded)} groups).")
        raise Exception(f"❌ [Anchor Failed] No matching unvisited groups found in Groups list tab for '{transaction_type}'.")

    chosen_elem, chosen_name = random.choice(pool)
    bot.log(f"🎯 Selected target Group: '{chosen_name}' (from {len(pool)} eligible candidates). Clicking...")
    chosen_elem.click()
    bot.smart_sleep(3.0)

    # Anchor verification: Wait for group feed page to load or dismiss onboarding screens
    start_time = time.time()
    while time.time() - start_time < timeout:
        if not bot.d:
            break
        write_box = bot.d(textMatches=r"(?i).*Write something.*|.*Viết gì đó.*|.*Bạn đang nghĩ gì.*|.*Bạn đang bán gì.*|.*What are you selling.*")
        write_desc = bot.d(descriptionMatches=r"(?i).*Write something.*|.*Viết gì đó.*|.*Bạn đang nghĩ gì.*|.*Bạn đang bán gì.*|.*What are you selling.*")
        group_feed = bot.d(textMatches=r"(?i).*Joined.*|.*Đã tham gia.*|.*Invite.*|.*Mời.*|.*Featured.*|.*Đáng chú ý.*")
        onboarding_btn = bot.d(textMatches=r"(?i)^Next$|^Skip$|^Tiếp$|^Bỏ qua$") or bot.d(descriptionMatches=r"(?i)^Next$|^Skip$|^Tiếp$|^Bỏ qua$")

        if write_box.exists or write_desc.exists or group_feed.exists or onboarding_btn.exists:
            bot.log(f"✔️ [Anchor Verified] Successfully opened Group '{chosen_name}'!")
            dismiss_group_onboarding_screens(bot, max_attempts=4)
            return chosen_name
        bot.smart_sleep(1.0)

    bot.log(f"ℹ️ Proceeding with group '{chosen_name}'...")
    dismiss_group_onboarding_screens(bot, max_attempts=4)
    return chosen_name


# ==============================================================================
# ONBOARDING / WELCOME OVERLAY DISMISSAL
# ==============================================================================

DISMISS_BUTTON_PATTERNS = [
    r"(?i)^Next$",
    r"(?i)^Skip$",
    r"(?i)^Tiếp$",
    r"(?i)^Tiếp tục$",
    r"(?i)^Bỏ qua$",
    r"(?i)^Đóng$",
    r"(?i)^Close$",
    r"(?i)^Got it$",
    r"(?i)^Đã hiểu$",
    r"(?i)^Hoàn tất$",
    r"(?i)^Done$",
    r"(?i)^Dismiss$"
]

def has_sell_or_write_button(bot: BaseAutomator) -> bool:
    """Checks if 'Sell something' or 'Write something' button is currently visible on screen."""
    if not bot.d:
        return False
    patterns = [
        r"(?i).*What are you selling.*",
        r"(?i).*Bạn đang bán gì.*",
        r"(?i).*Sell something.*",
        r"(?i).*Bán gì đó.*",
        r"(?i).*Tạo bài niêm yết.*",
        r"(?i)^Item$|^Mặt hàng$",
        r"(?i).*Write something.*",
        r"(?i).*Bạn viết gì đi.*",
        r"(?i).*Viết gì đó.*",
        r"(?i).*Bạn đang nghĩ gì.*",
        r"(?i).*Tạo bài viết.*",
        r"(?i).*Hãy viết gì đó.*"
    ]
    for p in patterns:
        if bot.d(textMatches=p).exists or bot.d(descriptionMatches=p).exists:
            return True
    return False

def dismiss_group_onboarding_screens(bot: BaseAutomator, max_attempts: int = 4) -> bool:
    """
    Checks and dismisses any overlay onboarding/welcome screens (e.g. Welcome message,
    Group rules, Introduce yourself) by clicking 'Next' / 'Skip' up to max_attempts times
    until 'Sell something' or 'Write something' button becomes visible.
    """
    if not bot.d:
        return False

    for attempt in range(max_attempts):
        if has_sell_or_write_button(bot):
            bot.log(f"✔️ Target post button ('Sell' / 'Write') is visible (dismiss attempt {attempt}).")
            return True

        clicked = False
        bot.log(f"🛡️ Checking for onboarding overlay screens (attempt {attempt + 1}/{max_attempts})...")

        for p in DISMISS_BUTTON_PATTERNS:
            btn = bot.d(textMatches=p)
            if btn.exists:
                bot.log(f"👆 Found and clicking onboarding dismiss button (text: '{p}')...")
                btn.click()
                clicked = True
                bot.smart_sleep(1.5)
                break

            desc_btn = bot.d(descriptionMatches=p)
            if desc_btn.exists:
                bot.log(f"👆 Found and clicking onboarding dismiss button (desc: '{p}')...")
                desc_btn.click()
                clicked = True
                bot.smart_sleep(1.5)
                break

            clean_kw = p.replace("(?i)^", "").replace("$", "").lower()
            w_btn = bot.get_button_by_text(clean_kw, timeout=0.5)
            if w_btn and w_btn.exists:
                bot.log(f"👆 Found and clicking onboarding widget '{clean_kw}'...")
                w_btn.click()
                clicked = True
                bot.smart_sleep(1.5)
                break

        if not clicked:
            bot.log("ℹ️ No overlay dismiss button found on current screen.")
            break

        if has_sell_or_write_button(bot):
            bot.log("🎉 Target post button is now visible after dismissing onboarding screen!")
            return True

    return has_sell_or_write_button(bot)


# ==============================================================================
# GROUP MODE DETECTION (BUY & SELL VS DISCUSSION)
# ==============================================================================

def detect_group_post_mode(bot: BaseAutomator, timeout: int = 10) -> str:
    """
    Detects whether the current group feed supports 'SELL' (Buy & Sell listing) or 'DISCUSSION' (Discussion post).
    Dismisses onboarding/welcome screens if blocking the view.
    Returns 'SELL' or 'DISCUSSION'.
    """
    bot.log("🔍 Analyzing group interface (Buy & Sell vs Discussion)...")

    # Step 0: Dismiss any onboarding overlay if post buttons are not visible
    if not has_sell_or_write_button(bot):
        dismiss_group_onboarding_screens(bot, max_attempts=4)

    sell_patterns = [
        r"(?i).*What are you selling.*",
        r"(?i).*Bạn đang bán gì.*",
        r"(?i).*Sell something.*",
        r"(?i).*Bán gì đó.*",
        r"(?i).*Tạo bài niêm yết.*"
    ]

    discussion_patterns = [
        r"(?i).*Write something.*",
        r"(?i).*Bạn viết gì đi.*",
        r"(?i).*Viết gì đó.*",
        r"(?i).*Bạn đang nghĩ gì.*",
        r"(?i).*Tạo bài viết.*",
        r"(?i).*Hãy viết gì đó.*"
    ]

    def _check_current_mode() -> Optional[str]:
        if not bot.d:
            return None

        for p in sell_patterns:
            if bot.d(textMatches=p).exists or bot.d(descriptionMatches=p).exists:
                bot.log(f"🛒 Detected BUY & SELL group interface (matched '{p}').")
                return "SELL"

        if bot.d(textMatches=r"(?i)^Item$|^Mặt hàng$").exists:
            bot.log("🛒 Detected BUY & SELL group interface (found 'Item' button).")
            return "SELL"

        for p in discussion_patterns:
            if bot.d(textMatches=p).exists or bot.d(descriptionMatches=p).exists:
                bot.log(f"📝 Detected DISCUSSION group interface (matched '{p}').")
                return "DISCUSSION"

        return None

    detected = _check_current_mode()
    if detected:
        return detected

    # If still not detected, try dismissing again or scrolling
    for scroll_idx in range(3):
        if not has_sell_or_write_button(bot):
            dismiss_group_onboarding_screens(bot, max_attempts=2)
            detected = _check_current_mode()
            if detected:
                return detected

        bot.log(f"📜 [Scroll {scroll_idx + 1}/3] Scrolling down to find group post buttons...")
        bot.swipe_up(scale=0.35)
        bot.smart_sleep(1.2)
        detected = _check_current_mode()
        if detected:
            return detected

    bot.log("⚠️ Could not definitively detect mode after 3 scrolls. Defaulting to DISCUSSION.")
    return "DISCUSSION"


# ==============================================================================
# PIPELINE EXECUTION FOR SINGLE GROUP
# ==============================================================================

def execute_single_group_post(
    bot: BaseAutomator,
    params: Dict[str, Any],
    group_name: str
) -> bool:
    """
    Executes posting flow to a single group, dynamically adapting between SELL and DISCUSSION.
    """
    bot.log(f"\n🚀 ===== POSTING TO GROUP: '{group_name}' =====")

    title = params.get("title", "")
    description = params.get("description", "")
    image_paths = params.get("image_paths", [])
    photo_count = min(len(image_paths), 5) if image_paths else int(params.get("photo_num", 1))

    mode = detect_group_post_mode(bot, timeout=10)

    if mode == "SELL":
        bot.log("🛒 [Mode: SELL] Executing Buy & Sell Listing Flow...")

        bot.log("👉 [Step S1] Clicking 'What are you selling?'...")
        click_what_are_you_selling(bot, timeout=20)

        # Check for Confirm Identity after clicking sell
        if check_and_handle_identity_confirmation(bot):
            bot.log("🚨 Account required Confirm Identity after clicking sell button. Aborting post.")
            return False

        bot.log(f"👉 [Step S2] Adding {photo_count} photo(s)...")
        click_add_photos_listing(bot, photo_num=photo_count, timeout=15, max_retries=20)

        bot.log("👉 [Step S3] Filling listing details...")
        fill_listing_details(bot, params, max_scroll_cycles=5)

        bot.log("👉 [Step S4] Clicking Next button...")
        click_next_listing(bot, timeout=15)

        bot.log("👉 [Step S5] Publishing listing to group...")
        click_publish_or_done(bot, timeout=30)

    else:
        bot.log("📝 [Mode: DISCUSSION] Executing Discussion Post Flow...")

        if title and description:
            full_content = f"{title}\n\n{description}"
        elif description:
            full_content = description
        elif title:
            full_content = title
        else:
            full_content = "Thảo luận chia sẻ thông tin bất động sản chính chủ Đà Lạt."

        bot.log("👉 [Step D1] Clicking 'Write something...' button...")
        click_write_something_button(bot, timeout=15)

        # Check for Confirm Identity after clicking write something
        if check_and_handle_identity_confirmation(bot):
            bot.log("🚨 Account required Confirm Identity after clicking write something button. Aborting post.")
            return False

        bot.log("👉 [Step D2] Focusing 'Create your post...' field...")
        click_create_post_input_field(bot, timeout=15)

        bot.log("👉 [Step D3] Pasting discussion content...")
        paste_discussion_content(bot, content=full_content, timeout=15)

        bot.log("👉 [Step D4] Clicking Done / Next...")
        click_done_or_next_button(bot, timeout=10)

        if image_paths:
            bot.log("👉 [Step D5] Opening Gallery & selecting photos...")
            click_gallery_button(bot, timeout=15)
            select_pushed_images(bot, photo_count=min(len(image_paths), 5), timeout=15)
            click_next_after_photos(bot, timeout=15)

        bot.log("👉 [Step D6] Clicking 'Post' / 'Đăng' button...")
        click_post_button(bot, timeout=25)

    bot.log(f"✔️ Successfully posted to group '{group_name}'!")
    return True


# ==============================================================================
# CLASS-BASED ACTION WRAPPER FOR MY-MANAGER.V2
# ==============================================================================

class FBSingleListingAction:
    def __init__(self, automator: BaseAutomator, account: Account):
        self.automator = automator
        self.account = account
        if hasattr(self.automator, "__dict__"):
            self.automator.account_uid = self.account.uid
        self.detector = CheckpointDetector(automator.device)
        self.v1_bridge = V1DatabaseBridge()
        self.ai_service = GeminiService()

    def execute_single_listing_pipeline(
        self,
        target_groups_count: int = 3,
        transaction_type: str = "rental",
        title: str = "",
        price: str = "1000000",
        description: str = "",
        image_paths: Optional[List[str]] = None,
        max_scrolls: int = 2
    ) -> bool:
        """Iterates over target_groups_count groups and posts to each group individually."""
        logger.info(f"Starting Single Listing pipeline for {self.account.uid} (Target: {target_groups_count} groups, Trans: '{transaction_type}')...")

        posted_groups: Set[str] = set()
        pushed_remotes: List[str] = []
        current_step = "step_0_push_media"
        is_success = False

        try:
            if image_paths:
                pushed_remotes = self.automator.push_media(image_paths)

            params = {
                "title": title,
                "price": price,
                "description": description,
                "image_paths": image_paths or [],
                "category": "Miscellaneous",
                "condition": "New",
                "location": "Da Lat",
                "transaction_type": transaction_type
            }

            for group_idx in range(target_groups_count):
                self.automator.log(f"\n=======================================================")
                self.automator.log(f"📍 PROCESSING GROUP {group_idx + 1}/{target_groups_count} (Posted so far: {len(posted_groups)})")
                self.automator.log(f"=======================================================")

                current_step = f"step_1_open_groups_tab_g{group_idx + 1}"
                open_groups_tab_list(self.automator, timeout=20)

                # Checkpoint safety check
                is_cp, cp_msg = self.detector.is_checkpoint()
                if is_cp:
                    current_step = "checkpoint_detected"
                    AccountRepository.update_status(self.account.uid, AccountStatus.CHECKPOINT, cp_msg)
                    return False

                current_step = f"step_2_select_group_g{group_idx + 1}"
                chosen_group = select_random_group_with_exclusion(
                    self.automator,
                    transaction_type=transaction_type,
                    excluded_groups=posted_groups,
                    max_scrolls=max_scrolls,
                    timeout=15
                )

                current_step = f"step_3_post_to_group_g{group_idx + 1}"
                post_ok = execute_single_group_post(
                    bot=self.automator,
                    params=params,
                    group_name=chosen_group
                )
                if not post_ok:
                    self.automator.log(f"❌ Failed to post to group '{chosen_group}' (or checkpoint/confirm identity detected). Aborting pipeline.")
                    return False

                posted_groups.add(chosen_group)
                self.automator.log(f"✅ Group {group_idx + 1}/{target_groups_count} ('{chosen_group}') completed successfully!")

                if group_idx < target_groups_count - 1:
                    pause_s = random.randint(3, 6)
                    self.automator.log(f"⏳ Pausing {pause_s}s before next group...")
                    self.automator.smart_sleep(pause_s)

            is_success = True
            logger.info(f"🎉 Successfully completed Single Listing on all {len(posted_groups)} groups!")
            return True

        except Exception as e:
            logger.exception(f"Error during Single Listing execution at {current_step}: {e}")
            return False

        finally:
            if not is_success:
                dump_error_view(self.automator, account_uid=self.account.uid, step_name=f"error_{current_step}")
            if pushed_remotes:
                self.automator.cleanup_media()

    def execute(
        self,
        group_count: int = 3,
        use_v1_product: bool = True,
        use_ai: bool = True,
        transaction_type: Optional[str] = None,
        custom_content: Optional[str] = None,
        image_paths: Optional[List[str]] = None
    ) -> bool:
        """Entry point executing Single Listing workflow across N groups."""
        logger.info(f"Preparing Single Listing action for {self.account.uid} (target: {group_count} groups)...")

        category = getattr(self.account, 'category', 'real_estate') or 'real_estate'
        trans_type = transaction_type or getattr(self.account, 'transaction_type', 'rental') or 'rental'

        images: List[str] = list(image_paths or [])
        title: str = "BẤT ĐỘNG SẢN GIÁ TỐT ĐÀ LẠT"
        description: str = custom_content or "Thảo luận chia sẻ bài viết bất động sản chính chủ Đà Lạt."
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

        return self.execute_single_listing_pipeline(
            target_groups_count=group_count,
            transaction_type=trans_type,
            title=title,
            price=price,
            description=description,
            image_paths=images
        )
