"""Facebook News Feed Scrolling Action (Ported & Enhanced from phonemanager.v1)."""

import random
import logging
from typing import Optional
from src.core.models import Account, AccountStatus
from src.db.repository import AccountRepository
from src.automation.base_automator import BaseAutomator
from src.automation.checkpoint_handler import CheckpointDetector

logger = logging.getLogger(__name__)


class FBScrollFeedAction:
    def __init__(self, automator: BaseAutomator, account: Account):
        self.automator = automator
        self.account = account
        self.detector = CheckpointDetector(automator.device)

    def execute(
        self,
        max_swipes: int = 20,
        min_delay: float = 3.0,
        max_delay: float = 8.0,
        max_likes: int = 0
    ) -> bool:
        """
        Simulates human-like scrolling through Facebook News Feed with random reading pauses,
        'See more' clicks, post likes, and comment viewing.
        """
        logger.info(f"Starting News Feed scroll for {self.account.uid} (planned swipes={max_swipes})...")
        self.automator.launch(deeplink="fb://feed")
        self.automator.smart_sleep(3.0, 5.0)

        d = self.automator.device
        if not d:
            return False

        # Check for checkpoint
        is_cp, cp_msg = self.detector.is_checkpoint()
        if is_cp:
            AccountRepository.update_status(self.account.uid, AccountStatus.CHECKPOINT, cp_msg)
            return False

        # Check login status
        login_keywords = ["Log In", "Log in", "Đăng nhập", "Create new account", "Tạo tài khoản mới"]
        for kw in login_keywords:
            if d(text=kw).exists:
                logger.warning(f"Cannot scroll Feed: Account {self.account.uid} is at login screen.")
                return False

        likes_done = 0
        swipes_performed = 0

        while swipes_performed < max_swipes:
            self.automator.ensure_foreground()

            # Check for checkpoint during scrolling
            is_cp, cp_msg = self.detector.is_checkpoint()
            if is_cp:
                AccountRepository.update_status(self.account.uid, AccountStatus.CHECKPOINT, cp_msg)
                return False

            # Decide scroll behavior
            roll = random.random()
            if roll < 0.75:
                scale = random.uniform(0.4, 0.7)
                logger.info(f"[{swipes_performed + 1}/{max_swipes}] 📜 Scrolling up for new posts (Scale: {scale:.2f})...")
                self.automator.swipe_up(scale=scale)
            elif roll < 0.90:
                scale = random.uniform(0.25, 0.45)
                logger.info(f"[{swipes_performed + 1}/{max_swipes}] 📜 Scrolling down to re-read previous post (Scale: {scale:.2f})...")
                self.automator.swipe_down(scale=scale)
            else:
                scale = random.uniform(0.75, 0.9)
                logger.info(f"[{swipes_performed + 1}/{max_swipes}] ⚡ Fast swipe across long post (Scale: {scale:.2f})...")
                self.automator.swipe_up(scale=scale)

            swipes_performed += 1

            # Pause to simulate human reading
            sleep_time = random.uniform(min_delay, max_delay)
            logger.info(f"⏳ Reading post for {sleep_time:.1f}s...")
            self.automator.smart_sleep(min_sec=sleep_time, max_sec=sleep_time + 1.0)

            # --- RANDOM USER INTERACTIONS ---

            # Interaction 1: Click "See more" if found (25% chance)
            if random.random() < 0.25:
                if self.automator.try_click_see_more():
                    logger.info("🔍 Clicked 'See more' to read full post.")

            # Interaction 2: Like / React to post (7% chance)
            if likes_done < max_likes and random.random() < 0.07:
                like_clicked = False
                # Try via UIAutomator2 native selector first
                like_btn = d(className="android.widget.Button", descriptionMatches=r"(?i).*(Like button|Nút thích|Nút Thích|^Like$|^Thích$).*")
                if not like_btn.exists:
                    like_btn = d(descriptionMatches=r"(?i).*(Like button|Nút thích|Nút Thích|^Like$|^Thích$).*")
                if not like_btn.exists:
                    like_btn = d(textMatches=r"(?i)^(Like|Thích)$")

                if like_btn.exists:
                    try:
                        like_btn.click()
                        likes_done += 1
                        logger.info(f"❤️ Liked random post to increase engagement ({likes_done}/{max_likes})")
                        self.automator.smart_sleep(1.5, 3.0)
                        like_clicked = True
                    except Exception as e:
                        logger.debug(f"Could not click Like: {e}")

                if not like_clicked:
                    like_xpaths = [
                        "//android.widget.Button[contains(@content-desc, 'Like button') or contains(@content-desc, 'Nút thích') or contains(@content-desc, 'Nút Thích') or @content-desc='Like' or @content-desc='Thích']",
                        "//android.widget.Button[contains(@text, 'Like') or contains(@text, 'Thích')]",
                        "//*[@content-desc='Like' or @content-desc='Thích' or contains(@content-desc, 'Like button') or contains(@content-desc, 'Nút thích')]"
                    ]
                    for xpath in like_xpaths:
                        if d.xpath(xpath).exists:
                            try:
                                d.xpath(xpath).click()
                                likes_done += 1
                                logger.info(f"❤️ Liked random post to increase engagement ({likes_done}/{max_likes})")
                                self.automator.smart_sleep(1.5, 3.0)
                                break
                            except Exception as e:
                                logger.debug(f"Could not click Like via xpath: {e}")

            # Interaction 3: Open comments (4% chance)
            if random.random() < 0.04:
                comment_btn = d(className="android.widget.Button", descriptionMatches=r"(?i).*(Comment|Bình luận).*") or d(descriptionMatches=r"(?i).*(Comment|Bình luận).*")
                if comment_btn and comment_btn.exists:
                    try:
                        logger.info("💬 Opening post comments...")
                        comment_btn.click()
                        self.automator.smart_sleep(4.0, 7.0)
                        if random.random() < 0.5:
                            self.automator.swipe_up(scale=0.3)
                            self.automator.smart_sleep(2.0, 4.0)
                        logger.info("↩️ Returning to News Feed...")
                        d.press("back")
                        self.automator.smart_sleep(2.0, 3.0)
                    except Exception as e:
                        logger.debug(f"Could not open comments: {e}")
                else:
                    comment_xpaths = [
                        "//android.widget.Button[contains(@content-desc, 'Comment') or contains(@content-desc, 'Bình luận') or @content-desc='Comment' or @content-desc='Bình luận']",
                        "//android.widget.Button[contains(@text, 'Comment') or contains(@text, 'Bình luận')]",
                        "//*[@content-desc='Comment' or @content-desc='Bình luận']"
                    ]
                    for xpath in comment_xpaths:
                        if d.xpath(xpath).exists:
                            try:
                                logger.info("💬 Opening post comments...")
                                d.xpath(xpath).click()
                                self.automator.smart_sleep(4.0, 7.0)
                                if random.random() < 0.5:
                                    self.automator.swipe_up(scale=0.3)
                                    self.automator.smart_sleep(2.0, 4.0)
                                logger.info("↩️ Returning to News Feed...")
                                d.press("back")
                                self.automator.smart_sleep(2.0, 3.0)
                                break
                            except Exception as e:
                                logger.debug(f"Could not open comments via xpath: {e}")

        AccountRepository.update_status(self.account.uid, AccountStatus.LIVE, f"Feed scroll completed ({swipes_performed} swipes, Likes={likes_done})")
        logger.info(f"✔️ News Feed scroll task completed for {self.account.uid}!")
        return True
