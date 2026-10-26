"""Facebook Reel Interactions Action - watch, like, comment, share to groups, and save reels."""

import time
import random
import logging
import re
from typing import Optional, List

from src.core.models import Account, AccountStatus
from src.db.repository import AccountRepository
from src.automation.base_automator import BaseAutomator
from src.automation.checkpoint_handler import CheckpointDetector

logger = logging.getLogger(__name__)

DEFAULT_REEL_COMMENTS: List[str] = [
    "Đẹp quá ạ!",
    "Tuyệt vời quá!",
    "Video hay quá bạn ơi",
    "Quá xuất sắc luôn ạ",
    "Nhìn mê quá",
    "Hay quá bạn ơi 👍",
    "Quan tâm ạ",
    "Cho em xin thêm thông tin với ạ",
    "Đẹp xuất sắc ❤️",
    "Tuyệt vời bạn ơi",
    "Quá đẹp luôn nè",
    "Hữu ích quá ạ",
    "10 điểm luôn nha",
    "Nhìn thích thật sự",
    "Thả tim ạ ❤️",
    "Đẹp quá chừng luôn",
    "Hay và chi tiết quá ạ",
    "Đỉnh quá bạn ơi 🔥",
    "Like mạnh luôn nha",
    "Nội dung hay quá 👍",
    "Quá chuẩn luôn",
    "Tuyệt vời luôn bạn ơi",
    "Nhà đẹp quá ạ",
    "Bài viết rất hữu ích ạ",
]


class FBReelInteractionsAction:
    """Automates interacting with a Facebook Reel by ID: watch simulation, like, save, comment, and share to groups."""

    def __init__(self, automator: BaseAutomator, account: Account):
        self.automator = automator
        self.account = account
        self.detector = CheckpointDetector(automator.device)

    def execute(
        self,
        reel_id: str,
        like: bool = True,
        comment: bool = False,
        comment_content: str = "",
        share: bool = False,
        share_num: int = 1,
        save: bool = False,
        watch_delay: float = 15.0,
    ) -> bool:
        """
        Executes full Reel interaction flow:
        1. Open reel via direct intent URI handler deeplink.
        2. Delay ~15s to simulate natural reel viewing.
        3. Like reel (skip if already liked).
        4. Save reel to collections and press back to main reel view.
        5. Post comment and press back to main reel view.
        6. Share reel to groups (up to share_num groups) and publish.
        """
        if not reel_id:
            logger.error(f"[{self.account.uid}] Missing required parameter 'reel_id'.")
            return False

        reel_id_clean = str(reel_id).strip()
        logger.info(
            f"[{self.account.uid}] Starting Reel interactions on ID '{reel_id_clean}' "
            f"(like={like}, comment={comment}, share={share} [num={share_num}], save={save})..."
        )

        d = self.automator.device
        if not d:
            logger.error(f"[{self.account.uid}] Automator device is not initialized.")
            return False

        # Step 1: Navigate to Reel via deeplink
        if not self.open_reel(reel_id_clean):
            return False

        # Check for checkpoint or login failure
        is_cp, cp_msg = self.detector.is_checkpoint()
        if is_cp:
            AccountRepository.update_status(self.account.uid, AccountStatus.CHECKPOINT, cp_msg)
            return False

        # Step 2: Delay ~15 seconds to simulate watching reel
        logger.info(f"[{self.account.uid}] ⏱️ Simulating watching Reel for {watch_delay}s...")
        time.sleep(watch_delay)

        # Step 3: Handle Like
        if like:
            self.handle_like()
            self.automator.smart_sleep(1.0, 2.0)

        # Step 4: Handle Save
        if save:
            self.handle_save()
            self.automator.smart_sleep(1.0, 2.0)

        # Step 5: Handle Comment
        if comment:
            final_comment = (comment_content or "").strip()
            if not final_comment:
                final_comment = random.choice(DEFAULT_REEL_COMMENTS)
                logger.info(
                    f"[{self.account.uid}] 💬 No comment_content provided. "
                    f"Picked random preset comment: '{final_comment}'"
                )
            self.handle_comment(final_comment)
            self.automator.smart_sleep(1.0, 2.0)

        # Step 6: Handle Share to Groups
        if share:
            self.handle_share_to_groups(share_num=share_num)
            self.automator.smart_sleep(1.0, 2.0)

        AccountRepository.update_status(
            self.account.uid,
            AccountStatus.LIVE,
            f"Reel interaction completed (Reel: {reel_id_clean}, Like: {like}, Comment: {comment}, Share: {share}, Save: {save})"
        )
        logger.info(f"[{self.account.uid}] ✔️ Finished Reel interactions for ID '{reel_id_clean}' successfully!")
        return True

    def open_reel(self, reel_id: str) -> bool:
        """Navigates to the Facebook Reel via direct IntentUriHandler deeplink to bypass ResolverActivity."""
        url = f"https://www.facebook.com/reel/{reel_id}"
        logger.info(f"[{self.account.uid}] Navigating to Reel via deeplink: '{url}'...")
        cmd = f'am start -a android.intent.action.VIEW -d "{url}" -n com.facebook.katana/com.facebook.katana.IntentUriHandler'

        if self.automator.device:
            self.automator.device.shell(cmd)
        else:
            self.automator.adb_client.execute_shell(cmd)

        self.automator.smart_sleep(3.0, 5.0)
        return True

    def handle_like(self) -> bool:
        """
        Analyzes and clicks the Like button on the Reel sidebar.
        If already liked (selected=True), skips this step.
        """
        d = self.automator.device
        if not d:
            return False

        logger.info(f"[{self.account.uid}] Analyzing Like status for Reel...")

        already_liked = False
        try:
            # 1. Check if any reaction button has selected=True
            if d(descriptionMatches=r"(?i).*(reactions|like).*", selected=True).exists:
                already_liked = True
            elif d.xpath('//android.widget.Button[contains(@content-desc, "reaction") and @selected="true"]').exists:
                already_liked = True
            elif d.xpath('//android.widget.Button[contains(@content-desc, "Like") and @selected="true"]').exists:
                already_liked = True
            else:
                # Inspect info of reaction buttons
                for btn in d(descriptionMatches=r"(?i).*(reactions|like).*"):
                    info = btn.info
                    if info.get("selected") is True:
                        already_liked = True
                        break
        except Exception as e:
            logger.debug(f"Error checking like status: {e}")

        if already_liked:
            logger.info(f"[{self.account.uid}] 👍 Reel is ALREADY LIKED. Skipping like step.")
            return True

        # Find Like/Reaction button (located in the right action sidebar, x > 800)
        like_btn = None
        for btn in d(descriptionMatches=r"(?i).*(reactions|like).*"):
            bounds = btn.info.get("bounds", {})
            if bounds.get("left", 0) > 800:
                like_btn = btn
                break

        if not like_btn and d(descriptionMatches=r"(?i).*(reactions|like).*").exists:
            like_btn = d(descriptionMatches=r"(?i).*(reactions|like).*")

        if like_btn and like_btn.exists:
            logger.info(f"[{self.account.uid}] Clicking Like button on Reel...")
            like_btn.click()
            self.automator.smart_sleep(1.5, 2.5)
            logger.info(f"[{self.account.uid}] ✔️ Liked reel successfully.")
            return True
        else:
            logger.warning(f"[{self.account.uid}] ⚠️ Could not locate Like button on Reel.")
            return False

    def handle_save(self) -> bool:
        """
        Clicks Save on the Reel sidebar, then presses back to dismiss
        the 'Saved / Add to collection' bottom sheet and return to the main reel screen.
        """
        d = self.automator.device
        if not d:
            return False

        logger.info(f"[{self.account.uid}] Analyzing Save status for Reel...")

        # If already saved (button desc is 'Saved')
        if d(description="Saved").exists or d(descriptionMatches=r"(?i)^saved$").exists:
            logger.info(f"[{self.account.uid}] 💾 Reel is ALREADY SAVED. Skipping save step.")
            return True

        # Locate Save button
        save_btn = None
        for candidate in [
            d(description="Save"),
            d(descriptionMatches=r"(?i)^save$"),
            d.xpath('//android.widget.Button[@content-desc="Save"]'),
            d(descriptionMatches=r"(?i).*save.*"),
        ]:
            if candidate.exists:
                # Ensure it's on the right sidebar if checking generic 'save'
                bounds = candidate.info.get("bounds", {}) if hasattr(candidate, "info") else {}
                if not bounds or bounds.get("left", 0) > 800:
                    save_btn = candidate
                    break

        if not save_btn or not save_btn.exists:
            logger.warning(f"[{self.account.uid}] ⚠️ Could not find Save button on Reel.")
            return False

        logger.info(f"[{self.account.uid}] Clicking Save button on Reel...")
        save_btn.click()
        self.automator.smart_sleep(1.5, 2.5)

        # Bottom sheet (secsion_04_save: 'Saved, Only me' / 'Add to a collection') opens
        logger.info(f"[{self.account.uid}] Pressing back to return to main reel screen...")
        d.press("back")
        self.automator.smart_sleep(1.5, 2.0)

        # Double check if bottom sheet or close button is still present
        if d(text="Add to a collection").exists or d(description="Saved, Only me").exists or d(description="Close").exists:
            d.press("back")
            self.automator.smart_sleep(1.0, 1.5)

        logger.info(f"[{self.account.uid}] ✔️ Saved reel and returned to main reel screen.")
        return True

    def handle_comment(self, comment_content: Optional[str] = None) -> bool:
        """
        Clicks Comment button, types comment_content into AutoCompleteTextView,
        clicks Send, then presses back to return to the main reel screen.
        If comment_content is empty, picks a random comment from DEFAULT_REEL_COMMENTS.
        """
        d = self.automator.device
        if not d:
            return False

        content = (comment_content or "").strip()
        if not content:
            content = random.choice(DEFAULT_REEL_COMMENTS)
            logger.info(f"[{self.account.uid}] 💬 Picked random comment: '{content}'")

        logger.info(f"[{self.account.uid}] Opening comments on Reel...")

        # Click Comment button on right sidebar or bottom bar
        comment_btn = None
        for candidate in [
            d(description="Comment"),
            d(descriptionMatches=r"(?i).*\bcomment\b.*"),
            d(description="Add a comment"),
            d.xpath('//android.widget.Button[contains(@content-desc, "comment") or contains(@content-desc, "Comment")]'),
        ]:
            if candidate.exists:
                comment_btn = candidate
                break

        if not comment_btn or not comment_btn.exists:
            logger.warning(f"[{self.account.uid}] ⚠️ Could not find Comment button on Reel.")
            return False

        comment_btn.click()
        self.automator.smart_sleep(2.0, 3.0)

        # Find comment text input field
        input_field = None
        for candidate in [
            d(className="android.widget.AutoCompleteTextView"),
            d(descriptionMatches=r"(?i).*write a comment.*|.*add a comment.*"),
            d(textMatches=r"(?i).*write a comment.*|.*add a comment.*"),
            d.xpath('//android.widget.AutoCompleteTextView'),
            d.xpath('//android.widget.EditText'),
        ]:
            if candidate.exists:
                input_field = candidate
                break

        if not input_field or not input_field.exists:
            logger.warning(f"[{self.account.uid}] ⚠️ Could not find comment input field.")
            d.press("back")
            return False

        logger.info(f"[{self.account.uid}] Typing comment: '{content}'...")
        input_field.click()
        self.automator.smart_sleep(0.5, 1.0)
        input_field.set_text(content)
        self.automator.smart_sleep(1.5, 2.5)

        # Click Send button
        send_btn = None
        for candidate in [
            d(description="Send"),
            d(descriptionMatches=r"(?i)^send$"),
            d(text="Send"),
            d.xpath('//android.widget.Button[@content-desc="Send"]'),
        ]:
            if candidate.exists:
                send_btn = candidate
                break

        if send_btn and send_btn.exists:
            logger.info(f"[{self.account.uid}] Clicking Send comment button...")
            send_btn.click()
            self.automator.smart_sleep(2.0, 4.0)
            logger.info(f"[{self.account.uid}] ✔️ Comment submitted successfully.")
        else:
            logger.warning(f"[{self.account.uid}] ⚠️ Send button not found. Attempting to press Enter/Send key...")
            d.press("enter")
            self.automator.smart_sleep(2.0, 3.0)

        # Press back to return to main reel view as specified
        logger.info(f"[{self.account.uid}] Pressing back to return to main reel screen...")
        d.press("back")
        self.automator.smart_sleep(1.5, 2.0)

        # Ensure comment tray is fully closed
        if d(className="android.widget.AutoCompleteTextView").exists or d(description="Write a comment…").exists:
            d.press("back")
            self.automator.smart_sleep(1.0, 1.5)

        return True

    def handle_share_to_groups(self, share_num: int = 1) -> bool:
        """
        Clicks Share button on Reel, selects 'Group' option,
        picks up to share_num groups RANDOMLY from the available groups (no restrictions),
        clicks Next, then clicks Post.
        """
        d = self.automator.device
        if not d:
            return False

        logger.info(f"[{self.account.uid}] Opening Share tray on Reel...")

        # 1. Click Share button on Reel
        share_btn = None
        for candidate in [
            d(descriptionMatches=r"(?i)^share.*"),
            d(textMatches=r"(?i)^share.*"),
            d(descriptionMatches=r"(?i).*(chia sẻ|share).*"),
            d(textMatches=r"(?i).*(chia sẻ|share).*"),
            d.xpath('//android.widget.Button[contains(@content-desc, "Share") or contains(@content-desc, "Chia sẻ")]'),
        ]:
            if candidate.exists:
                share_btn = candidate
                break

        if not share_btn or not share_btn.exists:
            logger.warning(f"[{self.account.uid}] ⚠️ Could not find Share button on Reel.")
            return False

        share_btn.click()
        self.automator.smart_sleep(2.0, 3.0)

        # 2. Click 'Group' button in share tray
        group_opt = None
        for attempt in range(3):
            for candidate in [
                d(description="Group"),
                d(text="Group"),
                d(description="Nhóm"),
                d(text="Nhóm"),
                d(descriptionMatches=r"(?i)^(group|nhóm)$"),
                d(textMatches=r"(?i)^(group|nhóm)$"),
                d(descriptionMatches=r"(?i).*(share to a group|chia sẻ lên nhóm|chia sẻ vào nhóm|share to group|group|nhóm).*"),
                d(textMatches=r"(?i).*(chia sẻ lên nhóm|chia sẻ vào nhóm|share to group|group|nhóm).*"),
                d.xpath('//android.widget.Button[contains(@content-desc, "Group") or contains(@content-desc, "Nhóm") or contains(@text, "Group") or contains(@text, "Nhóm")]'),
                d.xpath('//android.view.ViewGroup[(@content-desc="Group" or @content-desc="Nhóm" or @text="Group" or @text="Nhóm") and @clickable="true"]'),
            ]:
                if candidate.exists:
                    group_opt = candidate
                    break

            if group_opt and group_opt.exists:
                break

            # If not found immediately, try swiping horizontally on share tray
            if attempt < 2:
                logger.info(f"[{self.account.uid}] 'Group' option not visible immediately. Swiping share tray (attempt {attempt+1}/2)...")
                try:
                    w, h = d.window_size()
                    d.swipe(int(w * 0.85), int(h * 0.82), int(w * 0.15), int(h * 0.82), steps=10)
                except Exception:
                    pass
                self.automator.smart_sleep(1.5, 2.0)

        if not group_opt or not group_opt.exists:
            logger.warning(f"[{self.account.uid}] ⚠️ Could not find 'Group' share option.")
            d.press("back")
            return False

        logger.info(f"[{self.account.uid}] Clicking 'Group' option in Share tray...")
        group_opt.click()
        self.automator.smart_sleep(2.5, 3.5)

        # 3. Detect UI Flow: Flow 1 (Multi-select Checkbox UI) vs Flow 2 (Single-select Button List UI: 03_group_clicked_02)
        target_count = max(1, min(int(share_num), 10))
        logger.info(f"[{self.account.uid}] Waiting for group list screen to load (target: {target_count} groups)...")

        def _get_elements(selector_result):
            if selector_result is None:
                return []
            if isinstance(selector_result, (list, tuple)):
                return [x for x in selector_result if getattr(x, "exists", True)]
            try:
                if getattr(selector_result, "exists", False):
                    count = getattr(selector_result, "count", len(selector_result))
                    return [selector_result[i] for i in range(count) if getattr(selector_result[i], "exists", True)]
            except Exception:
                pass
            return []

        start_wait = time.time()
        screen_type = None  # "multi" or "single"

        while time.time() - start_wait < 12:
            # 1. Check for Multi-select UI (Checkboxes / CompoundButtons)
            comp_elems = (
                _get_elements(d(className="android.widget.CompoundButton")) or
                _get_elements(d(className="android.widget.CheckBox")) or
                _get_elements(d(className="android.widget.RadioButton"))
            )
            if comp_elems:
                screen_type = "multi"
                break

            # 2. Check for Single-select List UI (03_group_clicked_02)
            # Has 'Select group' or group buttons with no checkboxes
            if (
                d(textMatches=r"(?i)^select group$|^chọn nhóm$").exists or
                d(descriptionMatches=r"(?i)^select group$|^chọn nhóm$").exists or
                d(description="Back Button").exists
            ):
                screen_type = "single"
                break

            # Check if any full-width Button rows exist below header (y >= 300)
            btn_elems = _get_elements(d(className="android.widget.Button", clickable=True))
            if btn_elems:
                for b_item in btn_elems:
                    try:
                        b = b_item.info.get("bounds", {})
                        desc = b_item.info.get("contentDescription", "")
                        if b.get("top", 0) >= 300 and (b.get("right", 0) - b.get("left", 0) > 800):
                            if desc and not any(k in desc.lower() for k in ["back", "close", "search", "next", "tiếp", "post", "đăng"]):
                                screen_type = "single"
                                break
                    except Exception:
                        pass
                if screen_type == "single":
                    break

            self.automator.smart_sleep(1.0)

        if not screen_type:
            logger.warning(f"[{self.account.uid}] ⚠️ No groups detected on screen after waiting.")
            d.press("back")
            return False

        # =========================================================================
        # FLOW 2: SINGLE-SELECT LIST UI (03_group_clicked_02)
        # Clicking a group immediately navigates to Composer (04_next_clicked).
        # Clicking Post publishes and auto-returns to 03_group_clicked_02.
        # If share_num > 1, repeat for next random group.
        # =========================================================================
        if screen_type == "single":
            logger.info(f"[{self.account.uid}] 📋 Detected Single-Select Group UI ('Select group' / 03_group_clicked_02).")
            selected_count = 0
            shared_group_titles = set()

            while selected_count < target_count:
                # 1. Collect all currently visible group buttons
                available_group_items = []
                btn_list = _get_elements(d(className="android.widget.Button", clickable=True))
                for btn in btn_list:
                    try:
                        info = btn.info
                        desc = info.get("contentDescription", "") or info.get("text", "")
                        b = info.get("bounds", {})
                        # Filter to group row: y >= 300, y <= 1800, width > 800
                        if b.get("top", 0) >= 300 and b.get("bottom", 0) <= 1800 and (b.get("right", 0) - b.get("left", 0) > 800):
                            if desc and desc not in shared_group_titles:
                                if not any(k in desc.lower() for k in ["back", "close", "search", "tìm kiếm", "next", "tiếp", "post", "đăng"]):
                                    available_group_items.append((btn, desc))
                    except Exception:
                        pass

                # If no unshared groups visible, try swiping down once to reveal more
                if not available_group_items:
                    logger.info(f"[{self.account.uid}] Swiping down to find more unshared groups...")
                    self.automator.swipe_up(scale=0.5)
                    self.automator.smart_sleep(1.5, 2.5)
                    btn_list = _get_elements(d(className="android.widget.Button", clickable=True))
                    for btn in btn_list:
                        try:
                            info = btn.info
                            desc = info.get("contentDescription", "") or info.get("text", "")
                            b = info.get("bounds", {})
                            if b.get("top", 0) >= 300 and b.get("bottom", 0) <= 1800 and (b.get("right", 0) - b.get("left", 0) > 800):
                                if desc and desc not in shared_group_titles:
                                    if not any(k in desc.lower() for k in ["back", "close", "search", "tìm kiếm", "next", "tiếp", "post", "đăng"]):
                                        available_group_items.append((btn, desc))
                        except Exception:
                            pass

                if not available_group_items:
                    logger.warning(f"[{self.account.uid}] ⚠️ No more unshared groups available to select.")
                    break

                # 2. Pick 1 group randomly
                chosen_btn, chosen_title = random.choice(available_group_items)
                shared_group_titles.add(chosen_title)
                logger.info(f"[{self.account.uid}] 🎲 [{selected_count + 1}/{target_count}] Randomly selected group: '{chosen_title[:45]}'. Clicking...")

                chosen_btn.click()
                self.automator.smart_sleep(2.5, 4.0)

                # 3. Wait for Composer screen (04_next_clicked) and click 'Post'
                post_btn = None
                start_post_wait = time.time()
                while time.time() - start_post_wait < 10:
                    for candidate in [
                        d(description="Post"),
                        d(text="Post"),
                        d(description="Đăng"),
                        d(text="Đăng"),
                        d(descriptionMatches=r"(?i)^(post|đăng)$"),
                        d(textMatches=r"(?i)^(post|đăng)$"),
                        d.xpath('//android.widget.Button[@content-desc="Post" or @content-desc="Đăng" or @text="Post" or @text="Đăng"]'),
                    ]:
                        if candidate.exists:
                            post_btn = candidate
                            break
                    if post_btn and post_btn.exists:
                        break
                    self.automator.smart_sleep(0.5)

                if not post_btn or not post_btn.exists:
                    logger.warning(f"[{self.account.uid}] ⚠️ 'Post' button not found on composer screen for '{chosen_title[:30]}'. Pressing back...")
                    d.press("back")
                    self.automator.smart_sleep(1.5, 2.0)
                    continue

                logger.info(f"[{self.account.uid}] Clicking 'Post' button to publish share...")
                post_btn.click()
                selected_count += 1
                self.automator.smart_sleep(2.5, 4.0)

                # Check for error toast
                if d(descriptionMatches=r"(?i).*couldn't be shared.*").exists or d(textMatches=r"(?i).*couldn't be shared.*").exists:
                    logger.warning(f"[{self.account.uid}] ⚠️ Facebook showed error: Post couldn't be shared to '{chosen_title[:30]}'.")

                # 4. If more groups need to be shared, wait for UI to auto-return to 'Select group' (03_group_clicked_02)
                if selected_count < target_count:
                    logger.info(f"[{self.account.uid}] Waiting for UI to auto-return to 'Select group' screen for next share...")
                    start_return_wait = time.time()
                    returned_to_list = False
                    while time.time() - start_return_wait < 12:
                        if (
                            d(textMatches=r"(?i)^select group$|^chọn nhóm$").exists or
                            d(descriptionMatches=r"(?i)^select group$|^chọn nhóm$").exists or
                            d(description="Back Button").exists or
                            d(className="android.widget.EditText", textMatches=r"(?i).*search.*").exists
                        ):
                            returned_to_list = True
                            break
                        self.automator.smart_sleep(0.8)

                    if not returned_to_list:
                        logger.info(f"[{self.account.uid}] Checking if still on Composer screen...")
                        if d(description="Close").exists:
                            d(description="Close").click()
                            self.automator.smart_sleep(1.0, 1.5)

            # 5. After finishing all shares in Flow 2, exit 'Select group' screen back to Reel
            logger.info(f"[{self.account.uid}] Finished sharing {selected_count}/{target_count} group(s). Exiting to Reel screen...")
            if d(description="Back Button").exists:
                d(description="Back Button").click()
                self.automator.smart_sleep(1.0, 1.5)
            elif (
                d(textMatches=r"(?i)^select group$|^chọn nhóm$").exists or
                d(descriptionMatches=r"(?i)^select group$|^chọn nhóm$").exists
            ):
                d.press("back")
                self.automator.smart_sleep(1.0, 1.5)

            # Close share tray if still open
            if d(description="Close").exists:
                d(description="Close").click()
                self.automator.smart_sleep(1.0, 1.5)

            logger.info(f"[{self.account.uid}] ✔️ Shared reel to {selected_count} group(s) successfully.")
            return selected_count > 0

        # =========================================================================
        # FLOW 1: MULTI-SELECT CHECKBOX UI (02_share_to_group_clicked)
        # Selects checkboxes -> clicks Next -> clicks Post.
        # =========================================================================
        logger.info(f"[{self.account.uid}] 📋 Detected Multi-Select Group UI (Checkboxes / 02_share_to_group_clicked).")

        available_checkboxes = (
            _get_elements(d(className="android.widget.CompoundButton")) or
            _get_elements(d(className="android.widget.CheckBox")) or
            _get_elements(d(className="android.widget.RadioButton"))
        )

        if not available_checkboxes:
            logger.warning(f"[{self.account.uid}] ⚠️ No group checkboxes detected.")
            d.press("back")
            return False

        logger.info(f"[{self.account.uid}] Detected {len(available_checkboxes)} group checkboxes. Picking {min(target_count, len(available_checkboxes))} randomly...")

        sample_size = min(target_count, len(available_checkboxes))
        chosen_groups = random.sample(available_checkboxes, sample_size)

        selected_count = 0
        for item in chosen_groups:
            try:
                if item.exists:
                    info = item.info
                    g_desc = info.get("contentDescription") or info.get("text") or ""
                    if not g_desc:
                        child_tv = item.child(className="android.widget.TextView")
                        if child_tv.exists:
                            g_desc = child_tv.info.get("text", "") or ""
                    g_title = g_desc[:45] if g_desc else f"Group #{selected_count + 1}"

                    logger.info(f"[{self.account.uid}] 🎲 Randomly selected group {selected_count + 1}/{sample_size}: '{g_title}'...")
                    item.click()
                    selected_count += 1
                    self.automator.smart_sleep(0.5, 1.0)
            except Exception as e:
                logger.debug(f"Error clicking checkbox: {e}")

        if selected_count == 0:
            logger.warning(f"[{self.account.uid}] ⚠️ Failed to click any checkbox.")
            d.press("back")
            return False

        self.automator.smart_sleep(1.0, 2.0)

        # Click Next button
        next_btn = None
        for candidate in [
            d(description="Next"),
            d(text="Next"),
            d(description="Tiếp"),
            d(text="Tiếp"),
            d(descriptionMatches=r"(?i)^(next|tiếp)$"),
            d(textMatches=r"(?i)^(next|tiếp)$"),
            d.xpath('//android.widget.Button[@content-desc="Next" or @content-desc="Tiếp" or @text="Next" or @text="Tiếp"]'),
        ]:
            if candidate.exists and candidate.info.get("enabled", True):
                next_btn = candidate
                break

        if not next_btn or not next_btn.exists:
            logger.warning(f"[{self.account.uid}] ⚠️ 'Next' button not found or not enabled.")
            d.press("back")
            return False

        logger.info(f"[{self.account.uid}] Clicking 'Next' button...")
        next_btn.click()
        self.automator.smart_sleep(2.0, 3.5)

        # Click Post button
        post_btn = None
        for candidate in [
            d(description="Post"),
            d(text="Post"),
            d(description="Đăng"),
            d(text="Đăng"),
            d(descriptionMatches=r"(?i)^(post|đăng)$"),
            d(textMatches=r"(?i)^(post|đăng)$"),
            d.xpath('//android.widget.Button[@content-desc="Post" or @content-desc="Đăng" or @text="Post" or @text="Đăng"]'),
        ]:
            if candidate.exists:
                post_btn = candidate
                break

        if not post_btn or not post_btn.exists:
            logger.warning(f"[{self.account.uid}] ⚠️ 'Post' button not found on composer screen.")
            d.press("back")
            return False

        logger.info(f"[{self.account.uid}] Clicking 'Post' button to publish share...")
        post_btn.click()
        self.automator.smart_sleep(3.0, 5.0)

        # Check for error toast or leftovers
        if d(descriptionMatches=r"(?i).*couldn't be shared.*").exists or d(textMatches=r"(?i).*couldn't be shared.*").exists:
            logger.warning(f"[{self.account.uid}] ⚠️ Facebook showed error: Post couldn't be shared.")

        # Ensure return to main reel view
        if d(description="Close").exists:
            d(description="Close").click()
            self.automator.smart_sleep(1.0, 1.5)

        logger.info(f"[{self.account.uid}] ✔️ Shared reel to {selected_count} groups successfully.")
        return True
