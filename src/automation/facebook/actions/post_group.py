"""Facebook Post to Group Action."""

import os
import logging
from pathlib import Path
from typing import List, Optional
from src.core.models import Account, AccountStatus
from src.db.repository import AccountRepository
from src.automation.base_automator import BaseAutomator
from src.automation.checkpoint_handler import CheckpointDetector

logger = logging.getLogger(__name__)


class FBPostGroupAction:
    def __init__(self, automator: BaseAutomator, account: Account):
        self.automator = automator
        self.account = account
        self.detector = CheckpointDetector(automator.device)

    def execute(
        self,
        group_id: str,
        content: str,
        image_paths: Optional[List[str]] = None
    ) -> bool:
        """Posts text and optional images into a specified Facebook Group via deeplink."""
        logger.info(f"Starting FB Group Post for {self.account.uid} on Group ID '{group_id}'...")
        
        pushed_remotes = []
        try:
            # Push images to gallery if provided
            if image_paths:
                self.automator.adb_client.ensure_storage_ready()
                self.automator.adb_client.grant_app_permissions("com.facebook.katana")
                for idx, img in enumerate(image_paths):
                    if not os.path.exists(img):
                        logger.warning(f"Image not found on host: {img}")
                        continue
                    ext = Path(img).suffix.lower() or ".jpg"
                    remote_path = f"/sdcard/DCIM/Camera/group_post_{idx}{ext}"
                    if self.automator.adb_client.push_file(img, remote_path):
                        pushed_remotes.append(remote_path)
                        self.automator.adb_client.scan_media_file(remote_path)
                    else:
                        logger.error(f"Failed to push image to Redroid: {img}")

            # Launch group page directly via deeplink
            deeplink = f"fb://group/{group_id}"
            self.automator.launch(deeplink=deeplink)
            self.automator.smart_sleep(3.0, 5.0)

            # Check for checkpoint
            is_cp, cp_msg = self.detector.is_checkpoint()
            if is_cp:
                AccountRepository.update_status(self.account.uid, AccountStatus.CHECKPOINT, cp_msg)
                return False

            d = self.automator.device
            if not d:
                return False

            # Click Write something / Bấm để viết bài
            post_box_xpaths = [
                "//*[contains(@text, 'Write something') or contains(@text, 'Viết gì đó') or contains(@text, 'Tạo bài viết')]",
                "//*[contains(@description, 'Write something') or contains(@description, 'Viết gì đó')]"
            ]
            clicked = False
            for xp in post_box_xpaths:
                if self.automator.click_element(xpath=xp):
                    clicked = True
                    break

            if not clicked:
                # Fallback click center-top area of group feed
                w, h = d.window_size()
                d.click(w // 2, int(h * 0.25))
                self.automator.smart_sleep(2.0, 3.0)

            # Fill text content
            self.automator.input_text(content)

            # Add image if available
            if image_paths and (d(text="Photo/video").exists or d(text="Ảnh/video").exists):
                self.automator.click_element(text="Photo/video") or self.automator.click_element(text="Ảnh/video")
                self.automator.smart_sleep(2.0, 3.0)
                if d(className="android.widget.ImageView").exists:
                    d(className="android.widget.ImageView")[0].click()
                    self.automator.click_element(text="Next") or self.automator.click_element(text="Tiếp")

            # Click POST / ĐĂNG
            self.automator.click_element(text="POST") or self.automator.click_element(text="ĐĂNG") or self.automator.click_element(text="Post")
            self.automator.smart_sleep(5.0, 8.0)

            logger.info(f"Successfully posted to group {group_id} for account {self.account.uid}")
            return True
        finally:
            if pushed_remotes:
                logger.info(f"Cleaning up {len(pushed_remotes)} temp image(s) from Redroid device storage...")
                for r_path in pushed_remotes:
                    self.automator.adb_client.remove_file(r_path)
