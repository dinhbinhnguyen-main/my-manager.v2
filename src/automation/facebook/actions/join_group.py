"""Facebook Join Group Action - supports direct group_id or search keyword with group_count."""

import time
import random
import logging
import urllib.parse
from typing import Optional, Set, Tuple

from src.core.models import Account, AccountStatus
from src.db.repository import AccountRepository
from src.automation.base_automator import BaseAutomator
from src.automation.checkpoint_handler import CheckpointDetector

logger = logging.getLogger(__name__)


class FBJoinGroupAction:
    def __init__(self, automator: BaseAutomator, account: Account):
        self.automator = automator
        self.account = account
        self.detector = CheckpointDetector(automator.device)

    def execute(
        self,
        keyword: Optional[str] = None,
        group_count: int = 3,
        group_id: Optional[str] = None,
        **kwargs
    ) -> bool:
        """
        Executes join group action.
        - If 'keyword' is provided: searches groups by keyword and joins up to 'group_count' groups.
        - If 'group_id' is provided (legacy mode): navigates directly to the group via deeplink.
        """
        if keyword:
            return self.join_groups_by_keyword(keyword=keyword, group_count=group_count)
        elif group_id:
            return self.join_group_by_id(group_id=str(group_id))
        else:
            logger.error(f"[{self.account.uid}] Missing both 'keyword' and 'group_id' for join_group.")
            return False

    def join_group_by_id(self, group_id: str) -> bool:
        """Navigates to a specific Facebook Group via deeplink and clicks Join Group (Legacy mode)."""
        logger.info(f"[{self.account.uid}] Navigating to join FB Group ID '{group_id}'...")
        deeplink = f"fb://group/{group_id}"
        self.automator.launch(deeplink=deeplink)
        self.automator.smart_sleep(3.0, 5.0)

        is_cp, cp_msg = self.detector.is_checkpoint()
        if is_cp:
            AccountRepository.update_status(self.account.uid, AccountStatus.CHECKPOINT, cp_msg)
            return False

        join_btn = (
            self.automator.click_element(text="Join group") or
            self.automator.click_element(text="Tham gia nhóm") or
            self.automator.click_element(text="Join") or
            self.automator.click_element(text="Tham gia")
        )

        if join_btn:
            self._handle_membership_questions()
            logger.info(f"[{self.account.uid}] Sent join request to FB Group {group_id}")
            return True

        logger.info(f"[{self.account.uid}] Already a member or Join button not found for group {group_id}.")
        return True

    def join_groups_by_keyword(self, keyword: str, group_count: int = 3) -> bool:
        """
        Searches groups on Facebook by keyword and joins up to group_count groups.
        Handles switching to Groups tab, clicking Join, solving membership questionnaires, and scrolling.
        """
        d = self.automator.device
        if not d:
            logger.error(f"[{self.account.uid}] Device is not connected.")
            return False

        logger.info(f"[{self.account.uid}] 🔍 Searching FB Groups for keyword: '{keyword}' (target: {group_count} groups)")

        # 1. Check initial checkpoint
        is_cp, cp_msg = self.detector.is_checkpoint()
        if is_cp:
            AccountRepository.update_status(self.account.uid, AccountStatus.CHECKPOINT, cp_msg)
            return False

        # 2. Open Native Search via Deeplink
        encoded_query = urllib.parse.quote(keyword)
        deeplink = f"fb://search?query={encoded_query}"
        self.automator.launch(deeplink=deeplink)
        self.automator.smart_sleep(2.5, 4.0)

        # 3. Submit keyword query if needed
        if d(text=keyword).exists:
            d(text=keyword).click()
        else:
            d.press("enter")
        self.automator.smart_sleep(3.0, 4.5)

        # 4. Switch to 'Groups' (Nhóm) tab
        if not self._switch_to_groups_tab():
            logger.warning(f"[{self.account.uid}] Could not navigate to Groups tab. Aborting join_group.")
            return False

        # 5. Iterate through groups and click Join
        joined_count = 0
        clicked_coords: Set[Tuple[int, int]] = set()
        consecutive_no_new_buttons = 0
        max_scroll_attempts = 12

        scroll_count = 0
        while joined_count < group_count and scroll_count < max_scroll_attempts:
            is_cp, cp_msg = self.detector.is_checkpoint()
            if is_cp:
                AccountRepository.update_status(self.account.uid, AccountStatus.CHECKPOINT, cp_msg)
                return False

            # Query all Join buttons currently on screen
            # Matching <node class="android.widget.Button" text="Join" / "Tham gia" ...>
            join_btn_xpath = (
                "//android.widget.Button[(@text='Join' or @text='Tham gia' or "
                "@content-desc='Join' or @content-desc='Tham gia') and @clickable='true']"
            )
            buttons = d.xpath(join_btn_xpath).all()
            found_new_on_screen = False

            for btn in buttons:
                if joined_count >= group_count:
                    break

                bounds = btn.bounds
                # Key by (top_x, top_y) to avoid clicking same button twice on same screen
                coord_key = (bounds[0], bounds[1])
                if coord_key in clicked_coords:
                    continue

                clicked_coords.add(coord_key)
                found_new_on_screen = True

                # Try extracting group title for logging
                group_title = self._extract_group_title(btn)
                logger.info(f"[{self.account.uid}] 👉 Found group ({joined_count + 1}/{group_count}): '{group_title}'. Clicking Join...")

                try:
                    btn.click()
                    self.automator.smart_sleep(2.0, 3.5)
                except Exception as e:
                    logger.warning(f"[{self.account.uid}] Failed to click Join button: {e}")
                    continue

                # Handle membership questions / rules dialog if prompted
                self._handle_membership_questions()

                joined_count += 1
                consecutive_no_new_buttons = 0

                # Human-like delay between group joins to prevent Meta spam detection
                if joined_count < group_count:
                    delay = random.uniform(5.5, 9.5)
                    logger.info(f"[{self.account.uid}] ⏳ Sleeping {delay:.1f}s before next group join...")
                    time.sleep(delay)

            if joined_count >= group_count:
                break

            if not found_new_on_screen:
                consecutive_no_new_buttons += 1
                if consecutive_no_new_buttons >= 3:
                    logger.info(f"[{self.account.uid}] No new unjoined groups found after 3 consecutive scrolls.")
                    break

            # Scroll down to load more search results
            logger.info(f"[{self.account.uid}] Scrolling down to discover more groups...")
            self.automator.swipe_up(scale=0.55)
            self.automator.smart_sleep(2.0, 3.0)
            scroll_count += 1

        logger.info(
            f"[{self.account.uid}] 🎉 Join group action finished. Successfully requested/joined {joined_count}/{group_count} groups for '{keyword}'."
        )
        return joined_count > 0

    def _switch_to_groups_tab(self, max_swipes: int = 3) -> bool:
        """
        Navigates to 'Groups' / 'Nhóm' tab on the search results screen.
        Handles horizontal scrolling on the top TabWidget if necessary.
        """
        d = self.automator.device
        tab_patterns = [
            r"(?i).*(groups|nhóm).*search results.*",
            r"(?i)^Groups$",
            r"(?i)^Nhóm$",
            r"(?i).*Groups.*",
            r"(?i).*Nhóm.*"
        ]

        for attempt in range(max_swipes):
            # Check by content-desc or text
            for pattern in tab_patterns:
                tab_desc = d(descriptionMatches=pattern)
                if tab_desc.exists:
                    logger.info(f"[{self.account.uid}] Found Groups tab by description ('{pattern}'). Clicking...")
                    tab_desc.click()
                    self.automator.smart_sleep(2.5, 4.0)
                    return True

                tab_text = d(textMatches=pattern)
                if tab_text.exists:
                    logger.info(f"[{self.account.uid}] Found Groups tab by text ('{pattern}'). Clicking...")
                    tab_text.click()
                    self.automator.smart_sleep(2.5, 4.0)
                    return True

            # If not visible, swipe horizontally across tab bar (safely below status bar)
            try:
                w, h = d.window_size()
                tab_y = int(h * 0.16)
                d.swipe(int(w * 0.85), tab_y, int(w * 0.15), tab_y, steps=12)
                self.automator.smart_sleep(1.0, 1.5)
            except Exception as e:
                logger.warning(f"Error swiping tab bar: {e}")

        logger.warning(f"[{self.account.uid}] Could not locate Groups tab after {max_swipes} horizontal swipes.")
        return False

    def _extract_group_title(self, btn_node) -> str:
        """Helper to extract group name near the Join button."""
        try:
            # Check parent node for text containing '· Join'
            parent = btn_node.parent
            if parent:
                parent_desc = parent.attrib.get("content-desc") or parent.attrib.get("text", "")
                if "·" in parent_desc:
                    return parent_desc.split("·")[0].strip()
                if parent_desc:
                    return parent_desc.strip()
        except Exception:
            pass
        return "Unknown Group"

    def _handle_membership_questions(self, timeout_sec: float = 3.0) -> bool:
        """
        Detects and handles group membership questionnaire / rules agreement dialogs:
        - Ticks 'Agree to rules' checkboxes
        - Fills brief standard answers if EditText is required
        - Clicks Submit / Gửi button
        """
        d = self.automator.device
        if not d:
            return False

        # Check for questionnaire / rules dialog markers
        question_markers = [
            "//android.widget.TextView[contains(@text, 'quy tắc') or contains(@text, 'câu hỏi')]",
            "//android.widget.TextView[contains(@text, 'rules') or contains(@text, 'questions')]",
            "//*[@content-desc='Submit answers' or @text='Submit answers']",
            "//*[@text='Gửi câu trả lời' or @content-desc='Gửi câu trả lời']"
        ]

        is_question_screen = any(d.xpath(xp).exists for xp in question_markers)
        if not is_question_screen:
            return False

        logger.info(f"[{self.account.uid}] 📋 Group membership questionnaire detected. Auto-resolving...")

        # 1. Tick all unchecked CheckBoxes
        checkboxes = d(className="android.widget.CheckBox")
        if checkboxes.exists:
            for i in range(checkboxes.count):
                try:
                    cb = checkboxes[i]
                    if not cb.info.get("checked", False):
                        cb.click()
                        self.automator.smart_sleep(0.4, 0.8)
                except Exception:
                    pass

        # 2. Fill empty EditText fields if any
        edit_texts = d(className="android.widget.EditText")
        if edit_texts.exists:
            for i in range(edit_texts.count):
                try:
                    et = edit_texts[i]
                    if not et.get_text():
                        et.set_text("I agree to the group rules / Đồng ý tuân thủ quy tắc nhóm")
                        self.automator.smart_sleep(0.4, 0.8)
                except Exception:
                    pass

        # 3. Click Submit / Gửi / Hoàn tất
        submit_candidates = [
            "//android.widget.Button[@text='Gửi' or @text='Nộp' or @text='Submit' or @text='Hoàn tất']",
            "//android.widget.Button[contains(@text, 'Gửi') or contains(@text, 'Submit')]",
            "//*[@content-desc='Gửi' or @content-desc='Submit' or @content-desc='Nộp']",
            "//*[@text='Gửi câu trả lời' or @text='Submit answers']"
        ]

        for sb_xp in submit_candidates:
            submit_btn = d.xpath(sb_xp)
            if submit_btn.exists:
                submit_btn.click()
                self.automator.smart_sleep(2.0, 3.0)
                logger.info(f"[{self.account.uid}] ✅ Submitted membership questionnaire answers.")
                return True

        return False
