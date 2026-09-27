"""Checkpoint detector and status handler for Facebook accounts."""

import logging
from typing import Tuple
import uiautomator2 as u2

logger = logging.getLogger(__name__)

CHECKPOINT_KEYWORDS = [
    "Tài khoản của bạn đã bị khóa",
    "Your account has been locked",
    "Tải lên giấy tờ tùy thân",
    "Upload Your ID",
    "Xác nhận danh tính",
    "Confirm your identity",
    "Nhập mã xác nhận",
    "Enter confirmation code",
    "Phê duyệt từ thiết bị khác",
    "Approve from another device",
    "Chúng tôi phát hiện hoạt động bất thường",
    "We noticed unusual activity",
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
