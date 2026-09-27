"""Facebook Join Group Action."""

import logging
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

    def execute(self, group_id: str) -> bool:
        """Navigates to a Facebook Group via deeplink and clicks Join Group."""
        logger.info(f"Navigating to join FB Group ID '{group_id}' for {self.account.uid}...")
        deeplink = f"fb://group/{group_id}"
        self.automator.launch(deeplink=deeplink)
        self.automator.smart_sleep(3.0, 5.0)

        is_cp, cp_msg = self.detector.is_checkpoint()
        if is_cp:
            AccountRepository.update_status(self.account.uid, AccountStatus.CHECKPOINT, cp_msg)
            return False

        # Click Join / Tham gia button
        join_btn = (
            self.automator.click_element(text="Join group") or
            self.automator.click_element(text="Tham gia nhóm") or
            self.automator.click_element(text="Join") or
            self.automator.click_element(text="Tham gia")
        )

        if join_btn:
            logger.info(f"Sent join request to FB Group {group_id} for account {self.account.uid}")
            return True

        logger.info(f"Account {self.account.uid} is already a member or Join button not found for group {group_id}.")
        return True
