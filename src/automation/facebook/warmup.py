"""Facebook Account Warmup Action."""

import random
import logging
from src.core.models import Account, AccountStatus
from src.db.repository import AccountRepository
from src.automation.base_automator import BaseAutomator
from src.automation.checkpoint_handler import CheckpointDetector

logger = logging.getLogger(__name__)


class FBWarmupAction:
    def __init__(self, automator: BaseAutomator, account: Account):
        self.automator = automator
        self.account = account
        self.detector = CheckpointDetector(automator.device)

    def execute(self, scroll_count: int = 15, max_likes: int = 3) -> bool:
        """Executes natural feed browsing, reels watching, and post liking via fb://feed."""
        logger.info(f"Starting warmup action for {self.account.uid} (scrolls={scroll_count})...")
        self.automator.launch(deeplink="fb://feed")
        self.automator.smart_sleep(3.0, 5.0)

        d = self.automator.device
        likes_done = 0

        for i in range(scroll_count):
            self.automator.ensure_foreground()

            is_cp, cp_msg = self.detector.is_checkpoint()
            if is_cp:
                AccountRepository.update_status(self.account.uid, AccountStatus.CHECKPOINT, cp_msg)
                return False

            roll = random.random()
            if roll < 0.75:
                scale = random.uniform(0.4, 0.7)
                logger.info(f"[{i+1}/{scroll_count}] Scrolling up for new posts (Scale: {scale:.2f})...")
                self.automator.swipe_up(scale=scale)
            elif roll < 0.90:
                scale = random.uniform(0.25, 0.45)
                logger.info(f"[{i+1}/{scroll_count}] Scrolling down to re-read previous post (Scale: {scale:.2f})...")
                self.automator.swipe_down(scale=scale)
            else:
                scale = random.uniform(0.75, 0.9)
                logger.info(f"[{i+1}/{scroll_count}] Fast swipe across long post (Scale: {scale:.2f})...")
                self.automator.swipe_up(scale=scale)

            # Random See More click (25% chance)
            if random.random() < 0.25:
                self.automator.try_click_see_more()

            # Random Like / React (7% chance)
            if likes_done < max_likes and random.random() < 0.15:
                if self.automator.try_like_post():
                    likes_done += 1
                    logger.info(f"Liked post for {self.account.uid} ({likes_done}/{max_likes})")

            sleep_time = random.uniform(2.5, 6.0)
            self.automator.smart_sleep(min_sec=sleep_time, max_sec=sleep_time + 1.5)

        AccountRepository.update_status(self.account.uid, AccountStatus.LIVE, f"Warmup completed. Likes={likes_done}")
        logger.info(f"Warmup completed successfully for {self.account.uid}")
        return True
