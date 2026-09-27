import subprocess
from typing import List, Dict, Any, Optional
from src.core.models import Account, AccountStatus
from src.db.repository import AccountRepository
from src.automation.base_automator import BaseAutomator
from src.automation.checkpoint_handler import CheckpointDetector
from src.services.v1_bridge import V1DatabaseBridge
from src.ai.gemini_service import GeminiService
import logging

logger = logging.getLogger(__name__)


class FBMarketplaceAction:
    def __init__(self, automator: BaseAutomator, account: Account):
        self.automator = automator
        self.account = account
        self.detector = CheckpointDetector(automator.device)
        self.v1_bridge = V1DatabaseBridge()
        self.ai_service = GeminiService()

    def push_images_to_gallery(self, local_image_paths: List[str]) -> List[str]:
        """Pushes local product images to Redroid gallery storage and returns remote destination paths."""
        self.automator.adb_client.ensure_storage_ready()
        self.automator.adb_client.grant_app_permissions("com.facebook.katana")
        remotes = []
        for idx, img_path in enumerate(local_image_paths):
            if not os.path.exists(img_path):
                logger.warning(f"Image not found on host: {img_path}")
                continue
            ext = Path(img_path).suffix.lower() or ".jpg"
            remote_dest = f"/sdcard/DCIM/Camera/product_{idx}{ext}"
            if self.automator.adb_client.push_file(img_path, remote_dest):
                self.automator.adb_client.scan_media_file(remote_dest)
                remotes.append(remote_dest)
            else:
                logger.error(f"Failed to push product image to Redroid: {img_path}")
        return remotes

    def execute_v1_real_estate_post(self, transaction_type: str = "rental", use_ai: bool = True) -> bool:
        """Fetches active product matching account category and transaction_type from v1 DB, rewrites with Gemini AI, and posts to Marketplace."""
        product = self.v1_bridge.get_random_product_for_account(self.account)
        if not product:
            logger.error("No active product available in v1 DB for this account.")
            return False

        raw_title, raw_desc = self.v1_bridge.format_product_summary(product)
        is_rental = product.get("transaction_type") == "rental"

        if use_ai:
            logger.info(f"Rewriting real estate post with Gemini AI for product '{product.get('id')}'...")
            final_content = self.ai_service.rewrite_real_estate_post(raw_title, raw_desc, is_rental=is_rental)
            title = raw_title[:80]
            description = final_content
        else:
            title = raw_title[:80]
            description = raw_desc

        images = self.v1_bridge.get_product_images(str(product.get("id")))
        price_str = str(int(product.get("price", 1000000)))

        return self.execute_post(
            title=title,
            price=price_str,
            category="Property",
            description=description,
            images=images
        )

    def execute_post(self, title: str, price: str, category: str, description: str, images: List[str]) -> bool:
        """Fills out Marketplace creation form and posts listing."""
        logger.info(f"Starting Marketplace listing for {self.account.uid}: '{title}'...")
        pushed_remotes = []
        try:
            if images:
                pushed_remotes = self.push_images_to_gallery(images)

            self.automator.launch()
            self.automator.smart_sleep(2.0, 4.0)

            d = self.automator.device

            # Navigate to Marketplace tab
            if not self.automator.click_element(description="Marketplace") and not self.automator.click_element(text="Marketplace"):
                logger.error("Could not find Marketplace tab on screen")
                return False

            self.automator.smart_sleep(2.0, 3.0)

            # Click Sell / Bán button
            self.automator.click_element(text="Sell") or self.automator.click_element(text="Bán")
            self.automator.click_element(text="Items") or self.automator.click_element(text="Mặt hàng")

            self.automator.smart_sleep(2.0, 3.0)

            # Fill in listing details
            # Add Photos
            self.automator.click_element(text="Add Photos") or self.automator.click_element(text="Thêm ảnh")
            self.automator.smart_sleep(2.0, 3.0)

            # Select first available image
            if d(resourceId="com.facebook.katana:id/media_picker_grid").exists or d(text="Camera").exists:
                d(className="android.widget.ImageView")[0].click()
                self.automator.click_element(text="Next") or self.automator.click_element(text="Tiếp")

            # Fill Title
            self.automator.click_element(text="Title") or self.automator.click_element(text="Tiêu đề")
            self.automator.input_text(title)

            # Fill Price
            self.automator.click_element(text="Price") or self.automator.click_element(text="Giá")
            self.automator.input_text(price)

            # Fill Description
            self.automator.click_element(text="Description") or self.automator.click_element(text="Mô tả")
            self.automator.input_text(description)

            # Publish listing
            self.automator.click_element(text="Publish") or self.automator.click_element(text="Đăng")
            self.automator.smart_sleep(5.0, 8.0)

            logger.info(f"Marketplace post '{title}' submitted successfully for {self.account.uid}")
            return True
        finally:
            if pushed_remotes:
                logger.info(f"Cleaning up {len(pushed_remotes)} temp image(s) from Redroid device storage...")
                for r_path in pushed_remotes:
                    self.automator.adb_client.remove_file(r_path)
