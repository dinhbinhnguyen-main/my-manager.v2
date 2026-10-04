import re
import time
import random
import logging
import xml.etree.ElementTree as ET
from typing import Optional, List, Tuple, Any
import uiautomator2 as u2

from src.automation.adb_client import ADBClient

logger = logging.getLogger(__name__)


class BaseAutomator:
    def __init__(self, adb_port: int, package_name: str = "com.facebook.katana"):
        self.adb_port = adb_port
        self.package_name = package_name
        self.adb_client = ADBClient(port=adb_port)
        self.device: Optional[u2.Device] = None

    def log(self, message: str, level: Optional[str] = None):
        """Unified logging method compatible with v1 scripts, routing to semantic log levels."""
        if level:
            lvl = level.lower()
            if lvl == "success":
                logger.success(message) if hasattr(logger, "success") else logger.info(message)
                return
            elif lvl in ("error", "failed"):
                logger.error(message)
                return
            elif lvl in ("warning", "warn"):
                logger.warning(message)
                return
            elif lvl == "debug":
                logger.debug(message)
                return

        msg_lower = message.lower()
        if any(k in message for k in ["❌", "✖"]) or any(k in msg_lower for k in ["failed", "error:"]):
            logger.error(message)
        elif "⚠️" in message or "warning" in msg_lower or "warn" in msg_lower:
            logger.warning(message)
        elif any(k in message for k in ["✔️", "✔", "✅"]) or any(k in msg_lower for k in ["successfully", "succeeded", "completed"]):
            logger.success(message) if hasattr(logger, "success") else logger.info(message)
        else:
            logger.info(message)

    def initialize(self, max_retries: int = 5, retry_delay: float = 3.0) -> bool:
        """Connects ADB and initializes UIAutomator2 driver with background watchers, retrying until Android framework is ready."""
        if not self.adb_client.connect():
            return False

        # Ensure Android system has finished booting
        self.adb_client.wait_for_boot(timeout_sec=20)

        for attempt in range(1, max_retries + 1):
            try:
                self.device = u2.connect(f"127.0.0.1:{self.adb_port}")
                # Test connectivity to ensure Android AccessibilityService / SystemServer is ready
                _ = self.device.info
                self.adb_client.disable_soft_keyboard()
                self._setup_watchers()
                logger.info(f"UIAutomator2 connected & watchers active on 127.0.0.1:{self.adb_port} (Attempt {attempt})")
                return True
            except Exception as e:
                logger.warning(
                    f"UIAutomator2 connection attempt {attempt}/{max_retries} on port {self.adb_port} failed ({e}). "
                    f"Waiting {retry_delay}s for Android framework services to be ready..."
                )
                time.sleep(retry_delay)

        logger.error(f"UIAutomator2 connection permanently failed on port {self.adb_port} after {max_retries} attempts.")
        return False

    def _setup_watchers(self):
        """Registers background watchers to auto-dismiss system popups."""
        if not self.device:
            return
        try:
            self.device.watcher("ALLOW_PERMISSION").when(
                "//android.widget.Button[contains(@text, 'Cho phép') or contains(@text, 'Allow') or contains(@text, 'CHO PHÉP')]"
            ).click()
            self.device.watcher("CLOSE_POPUP").when(
                "//android.widget.Button[contains(@text, 'Đóng') or contains(@text, 'Bỏ qua') or contains(@text, 'Lúc khác') or contains(@text, 'Close') or contains(@text, 'Skip') or contains(@text, 'Later')]"
            ).click()
            self.device.watcher("OK_BUTTON").when(
                "//android.widget.Button[@text='OK' or @text='Ok' or @text='ok']"
            ).click()
            self.device.watcher.start(interval=2.0)
        except Exception as e:
            logger.warning(f"Could not setup watchers: {e}")

    def stop_watchers(self):
        """Stops and removes active background watchers."""
        if not self.device:
            return
        try:
            if hasattr(self.device, "watcher"):
                self.device.watcher.reset()
        except Exception:
            pass

    def close(self):
        """Safely cleans up UIAutomator2 watchers and closes connection."""
        self.stop_watchers()
        self.device = None

    @property
    def d(self) -> Optional[u2.Device]:
        return self.device

    def get_elements_by_widget(self, widget_class: str, timeout: float = 10.0):
        """Retrieves UI elements of a specific widget class, waiting for them to appear."""
        selector = self.device(className=widget_class) if self.device else None
        if selector and timeout > 0:
            start_time = time.time()
            while time.time() - start_time < timeout:
                if selector.exists:
                    return selector
                time.sleep(0.5)
        return selector

    def get_widget_by_text(self, class_name: str, text: str, exact: bool = False, timeout: float = 10.0):
        """Finds a specific Android widget by its class name using 'text' or 'content-desc'."""
        if not self.device:
            return None
        safe_text = re.escape(text)
        text_pattern = f"(?i)^{safe_text}$" if exact else f"(?i).*{safe_text}.*"
        widget_text = self.device(className=class_name, textMatches=text_pattern)
        widget_desc = self.device(className=class_name, descriptionMatches=text_pattern)
        widget_native = self.device(className=class_name, text=text) if exact else self.device(className=class_name, textContains=text)

        if timeout > 0:
            start_time = time.time()
            while time.time() - start_time < timeout:
                if widget_text.exists: return widget_text
                if widget_desc.exists: return widget_desc
                if widget_native.exists: return widget_native
                time.sleep(0.5)

        if widget_text.exists: return widget_text
        if widget_desc.exists: return widget_desc
        return widget_native

    def get_button_by_text(self, text: str, exact: bool = False, timeout: float = 10.0):
        """Finds a Button or TextView based on either 'text' or 'content-desc' attributes."""
        if not self.device:
            return None
        safe_text = re.escape(text)
        text_pattern = f"(?i)^{safe_text}$" if exact else f"(?i).*{safe_text}.*"
        btn_text = self.device(className="android.widget.Button", textMatches=text_pattern, enabled=True)
        tv_text = self.device(className="android.widget.TextView", textMatches=text_pattern, enabled=True)
        btn_desc = self.device(className="android.widget.Button", descriptionMatches=text_pattern, enabled=True)
        tv_desc = self.device(className="android.widget.TextView", descriptionMatches=text_pattern, enabled=True)

        if timeout > 0:
            start_time = time.time()
            while time.time() - start_time < timeout:
                if btn_text.exists: return btn_text
                if tv_text.exists: return tv_text
                if btn_desc.exists: return btn_desc
                if tv_desc.exists: return tv_desc
                time.sleep(0.5)

        if btn_text.exists: return btn_text
        if tv_text.exists: return tv_text
        if btn_desc.exists: return btn_desc
        return tv_desc

    def get_interactable_from_parent(
        self, parent_selector, child_class: str = "android.view.ViewGroup", text: str = "", timeout: float = 10.0
    ):
        """Finds a child element within a parent container."""
        if not parent_selector or not parent_selector.exists:
            return parent_selector
        safe_text = re.escape(text)
        pattern = f"(?i).*{safe_text}.*"
        child_by_text = parent_selector.child(className=child_class, textMatches=pattern)
        child_by_desc = parent_selector.child(className=child_class, descriptionMatches=pattern)

        if timeout > 0:
            start_time = time.time()
            while time.time() - start_time < timeout:
                if child_by_text.exists: return child_by_text
                if child_by_desc.exists: return child_by_desc
                time.sleep(0.5)

        if child_by_text.exists: return child_by_text
        return child_by_desc

    def swipe_widget_to_center(self, widget, duration: float = 0.5) -> bool:
        """Swipes the screen to move a visible Widget to the center of the display."""
        if not widget or not widget.exists or not self.device:
            return False
        try:
            screen_info = self.device.info
            screen_center_x = screen_info.get("displayWidth", 720) // 2
            screen_center_y = screen_info.get("displayHeight", 1280) // 2
            widget_center_x, widget_center_y = widget.center()
            self.device.swipe(widget_center_x, widget_center_y, screen_center_x, screen_center_y, duration=duration)
            self.smart_sleep(0.8, 1.2)
            return True
        except Exception as e:
            logger.warning(f"Error while swiping widget to center: {e}")
            return False

    def _get_screen_signature(self) -> int:
        """Generates a unique signature of the screen content to detect scroll changes."""
        if not self.device:
            return 0
        try:
            xml_dump = self.device.dump_hierarchy()
            root = ET.fromstring(xml_dump)
            texts = []
            for node in root.iter():
                pkg = node.attrib.get("package", "")
                if "systemui" not in pkg.lower():
                    text = node.attrib.get("text", "")
                    desc = node.attrib.get("content-desc", "")
                    if text: texts.append(text)
                    if desc: texts.append(desc)
            return hash("".join(texts))
        except Exception:
            return 0

    def launch(self, deeplink: Optional[str] = None):
        """Launches target app, optionally using an Android Deep Link URL."""
        if not self.device:
            self.adb_client.launch_app(self.package_name)
            return

        if deeplink:
            logger.info(f"Launching app via Deep Link: '{deeplink}'")
            cmd = f"am start -a android.intent.action.VIEW -d '{deeplink}' {self.package_name}"
            self.device.shell(cmd)
        else:
            self.device.app_start(self.package_name, stop=False)
        self.smart_sleep(2.0, 4.0)

    def ensure_foreground(self):
        """Ensures target app remains in foreground."""
        if not self.device:
            return
        try:
            curr = self.device.app_current()
            if curr.get("package") != self.package_name:
                logger.info(f"App '{self.package_name}' minimized or closed. Relaunching...")
                self.launch()
        except Exception as e:
            logger.warning(f"Error checking app foreground state: {e}")

    def stop(self):
        """Stops target app."""
        if self.device:
            self.device.app_stop(self.package_name)
        else:
            self.adb_client.stop_app(self.package_name)

    def smart_sleep(self, min_sec: float = 1.5, max_sec: float = 3.5):
        """Sleeps for a random duration to mimic human pause."""
        time.sleep(random.uniform(min_sec, max_sec))

    def click_element(self, text: Optional[str] = None, resource_id: Optional[str] = None, xpath: Optional[str] = None, timeout: float = 10.0) -> bool:
        """Clicks an element by text, resource-id, or xpath with smart waiting."""
        if not self.device:
            return False

        try:
            if text:
                elem = self.device(text=text)
            elif resource_id:
                elem = self.device(resourceId=resource_id)
            elif xpath:
                elem = self.device.xpath(xpath)
            else:
                return False

            if elem.wait(timeout=timeout):
                elem.click()
                self.smart_sleep(1.0, 2.0)
                return True
        except Exception as e:
            logger.warning(f"Click element failed (text={text}, resource_id={resource_id}): {e}")
        return False

    def input_text(self, text: str, resource_id: Optional[str] = None, xpath: Optional[str] = None):
        """Inputs text into target field."""
        if not self.device:
            return

        if resource_id:
            elem = self.device(resourceId=resource_id)
            elem.click()
            self.smart_sleep(0.5, 1.0)
            elem.set_text(text)
        elif xpath:
            elem = self.device.xpath(xpath)
            elem.click()
            self.smart_sleep(0.5, 1.0)
            elem.set_text(text)
        else:
            self.device.send_keys(text)
        self.smart_sleep(0.8, 1.5)

    def swipe_up(self, scale: float = 0.6):
        """Swipes screen up (scrolls content down)."""
        if not self.device:
            return
        w, h = self.device.window_size()
        sy = int(h * 0.75)
        ey = int(h * (0.75 - scale * 0.5))
        self.device.swipe(w // 2, sy, w // 2, ey, steps=10)

    def swipe_down(self, scale: float = 0.4):
        """Swipes screen down (scrolls content up / re-read)."""
        if not self.device:
            return
        w, h = self.device.window_size()
        sy = int(h * 0.3)
        ey = int(h * (0.3 + scale * 0.4))
        self.device.swipe(w // 2, sy, w // 2, ey, steps=10)

    def try_click_see_more(self) -> bool:
        """Clicks 'See more / Xem thêm' button if visible."""
        if not self.device:
            return False
        xpaths = [
            "//*[contains(@text, 'See more') or contains(@text, 'Xem thêm') or contains(@text, 'See More')]",
            "//*[contains(@content-desc, 'See more') or contains(@content-desc, 'Xem thêm')]"
        ]
        for xp in xpaths:
            if self.device.xpath(xp).exists:
                self.device.xpath(xp).click()
                self.smart_sleep(1.5, 3.0)
                return True
        return False

    def try_like_post(self) -> bool:
        """Likes current post if button is visible."""
        if not self.device:
            return False
        xpaths = [
            "//android.widget.Button[contains(@content-desc, 'Like button') or contains(@content-desc, 'Nút thích') or contains(@content-desc, 'Nút Thích') or @content-desc='Like' or @content-desc='Thích']",
            "//android.widget.Button[contains(@text, 'Like') or contains(@text, 'Thích')]",
            "//*[@content-desc='Like' or @content-desc='Thích' or contains(@content-desc, 'Like button') or contains(@content-desc, 'Nút thích')]"
        ]
        for xp in xpaths:
            if self.device.xpath(xp).exists:
                self.device.xpath(xp).click()
                self.smart_sleep(1.0, 2.0)
                return True
        return False

    def scroll_down(self, steps: int = 10):
        """Legacy helper for swipe up."""
        self.swipe_up(scale=0.6)
        self.smart_sleep(1.5, 3.0)

    def handle_system_popups(self):
        """Manually check system permission popups."""
        if not self.device:
            return
        popup_texts = ["Cho phép", "Allow", "WHILE USING THE APP", "Trong khi dùng ứng dụng", "Đồng ý", "Accept", "OK"]
        for txt in popup_texts:
            if self.device(text=txt).exists:
                self.device(text=txt).click()
                self.smart_sleep(0.5, 1.0)
