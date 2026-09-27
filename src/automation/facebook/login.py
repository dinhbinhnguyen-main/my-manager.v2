"""Facebook Automated Login and 2FA Action."""

import logging
import pyotp
from typing import Optional
from src.core.models import Account, AccountStatus
from src.db.repository import AccountRepository
from src.automation.base_automator import BaseAutomator
from src.automation.checkpoint_handler import CheckpointDetector

logger = logging.getLogger(__name__)


class FBLoginAction:
    def __init__(self, automator: BaseAutomator, account: Account):
        self.automator = automator
        self.account = account
        self.detector = CheckpointDetector(automator.device)

    def execute(self) -> bool:
        """Executes full FB Login flow with 2FA support."""
        logger.info(f"Starting login flow for account UID {self.account.uid}...")
        self.automator.launch()
        self.automator.smart_sleep(3.0, 5.0)
        self.automator.handle_system_popups()

        # Check for checkpoint early
        is_cp, cp_msg = self.detector.is_checkpoint()
        if is_cp:
            AccountRepository.update_status(self.account.uid, AccountStatus.CHECKPOINT, cp_msg)
            return False

        # Input credentials if login form is visible
        d = self.automator.device

        # Click username/email field or ID field
        login_identifier = self.account.username if self.account.username else self.account.uid
        if d(description="Số điện thoại hoặc email").exists or d(text="Mobile number or email").exists:
            self.automator.click_element(text="Mobile number or email")
            self.automator.input_text(login_identifier)

        # Password field
        if d(description="Mật khẩu").exists or d(text="Password").exists:
            self.automator.click_element(text="Password")
            self.automator.input_text(self.account.password)

        # Login button
        if self.automator.click_element(text="Log In") or self.automator.click_element(text="Đăng nhập"):
            logger.info(f"Clicked Log In button for {self.account.uid}")
            self.automator.smart_sleep(4.0, 7.0)

        # Handle 2FA OTP if requested
        if self.account.two_fa and (d(text="Nhập mã xác thực 2 yếu tố").exists or d(text="Enter 2-factor code").exists or d(text="Code").exists):
            logger.info(f"Generating 2FA TOTP code for {self.account.uid}...")
            totp = pyotp.TOTP(self.account.two_fa.replace(" ", ""))
            code = totp.now()

            self.automator.input_text(code)
            self.automator.click_element(text="Tiếp tục") or self.automator.click_element(text="Continue") or self.automator.click_element(text="Submit")
            self.automator.smart_sleep(3.0, 5.0)

        # Verify login status
        is_cp, cp_msg = self.detector.is_checkpoint()
        if is_cp:
            AccountRepository.update_status(self.account.uid, AccountStatus.CHECKPOINT, cp_msg)
            return False

        # If logged in successfully (home icon / news feed visible)
        AccountRepository.update_status(self.account.uid, AccountStatus.LIVE, "Logged in successfully via Redroid")
        logger.info(f"Account {self.account.uid} logged in successfully!")
        return True
