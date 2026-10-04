"""Checkpoint detector and status handler for Facebook accounts."""

import logging
import re
from typing import Tuple, Optional
import uiautomator2 as u2

logger = logging.getLogger(__name__)

CHECKPOINT_KEYWORDS = [
    "Tài khoản của bạn đã bị khóa",
    "Your account has been locked",
    "Tải lên giấy tờ tùy thân",
    "Upload Your ID",
    "Xác nhận danh tính",
    "Xác minh danh tính",
    "Confirm your identity",
    "Confirm identity",
    "Nhập mã xác nhận",
    "Enter confirmation code",
    "Phê duyệt từ thiết bị khác",
    "Approve from another device",
    "Chúng tôi phát hiện hoạt động bất thường",
    "Chúng tôi nhận thấy hoạt động bất thường",
    "We noticed unusual activity",
    "record a video selfie",
    "video selfie",
    "Before you can access groups",
    "Before you can join groups",
]

CONFIRM_IDENTITY_PATTERNS = [
    r"(?i).*confirm your identity.*",
    r"(?i).*confirm identity.*",
    r"(?i).*xác nhận danh tính.*",
    r"(?i).*xác minh danh tính.*",
    r"(?i).*we noticed unusual activity.*",
    r"(?i).*hoạt động bất thường.*",
    r"(?i).*record a video selfie.*",
    r"(?i).*video selfie.*",
    r"(?i).*before you can access groups.*",
    r"(?i).*before you can join groups.*",
]


class CheckpointDetector:
    def __init__(self, device: u2.Device):
        self.device = device

    def is_checkpoint(self) -> Tuple[bool, str]:
        """Scans current screen hierarchy for checkpoint indicators."""
        if not self.device:
            return False, ""

        try:
            xml_dump = self.device.dump_hierarchy()
            for kw in CHECKPOINT_KEYWORDS:
                if kw.lower() in xml_dump.lower():
                    logger.warning(f"Checkpoint detected on screen: '{kw}'")
                    return True, f"Checkpoint detected: {kw}"
        except Exception as e:
            logger.error(f"Error checking checkpoint screen: {e}")

        return False, ""


def check_and_handle_identity_confirmation(bot, account_uid: Optional[str] = None) -> bool:
    """
    Checks if Facebook is asking for identity confirmation ('Confirm Identity' / 'Xác nhận danh tính').
    If detected:
    - Logs warning
    - Updates account in DB: status=CHECKPOINT, note='Confirm Identify'
    - Returns True (indicating identity confirmation screen is blocking)
    """
    if not bot or not getattr(bot, "d", None):
        return False

    uid = str(account_uid or getattr(bot, "account_uid", None) or getattr(bot, "adb_port", "")).strip()

    try:
        # 1. Check UI hierarchy elements by regex
        for p in CONFIRM_IDENTITY_PATTERNS:
            elem_text = bot.d(textMatches=p)
            elem_desc = bot.d(descriptionMatches=p)
            if elem_text.exists or elem_desc.exists:
                bot.log(f"🚨 [CONFIRM IDENTITY DETECTED] Facebook is requiring identity confirmation on screen (matched '{p}').")
                if uid:
                    from src.db.repository import AccountRepository
                    from src.core.models import AccountStatus
                    AccountRepository.update_status(uid, AccountStatus.CHECKPOINT, note="Confirm Identify")
                    bot.log(f"📝 Updated account UID {uid} -> status=CHECKPOINT, note='Confirm Identify'")
                return True

        # 2. Fallback: scan XML dump
        xml_dump = bot.d.dump_hierarchy().lower()
        id_kws = [
            "confirm identity",
            "confirm your identity",
            "xác nhận danh tính",
            "xác minh danh tính",
            "we noticed unusual activity",
            "hoạt động bất thường",
            "video selfie",
            "before you can access groups",
        ]
        for kw in id_kws:
            if kw in xml_dump:
                bot.log(f"🚨 [CONFIRM IDENTITY DETECTED] Screen contains '{kw}'.")
                if uid:
                    from src.db.repository import AccountRepository
                    from src.core.models import AccountStatus
                    AccountRepository.update_status(uid, AccountStatus.CHECKPOINT, note="Confirm Identify")
                    bot.log(f"📝 Updated account UID {uid} -> status=CHECKPOINT, note='Confirm Identify'")
                return True

    except Exception as e:
        logger.debug(f"Error checking identity confirmation: {e}")

    return False
