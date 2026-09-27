"""ADB Client wrapper and app manager for Redroid instances."""

import time
import logging
import subprocess
from typing import Optional

logger = logging.getLogger(__name__)


class ADBClient:
    def __init__(self, host: str = "127.0.0.1", port: int = 5555):
        self.host = host
        self.port = port
        self.target = f"{host}:{port}"

    def connect(self) -> bool:
        """Connects ADB daemon to target port."""
        res = subprocess.run(["adb", "connect", self.target], capture_output=True, text=True)
        if "connected to" in res.stdout or "already connected" in res.stdout:
            logger.info(f"ADB connected successfully to {self.target}")
            return True
        logger.error(f"ADB connection failed to {self.target}: {res.stdout} {res.stderr}")
        return False

    def disconnect(self):
        """Disconnects ADB from target."""
        subprocess.run(["adb", "disconnect", self.target], capture_output=True)

    def wait_for_boot(self, timeout_sec: int = 45) -> bool:
        """Waits until Android system server and package manager finish booting."""
        start_time = time.time()
        while time.time() - start_time < timeout_sec:
            if self.connect():
                res = subprocess.run(
                    ["adb", "-s", self.target, "shell", "getprop", "sys.boot_completed"],
                    capture_output=True,
                    text=True,
                )
                if res.stdout.strip() == "1":
                    time.sleep(1)
                    return True
            time.sleep(2)
        return False

    def is_app_installed(self, package_name: str) -> bool:
        """Checks if a given package is installed in Redroid."""
        res = subprocess.run(
            ["adb", "-s", self.target, "shell", "pm", "list", "packages", package_name],
            capture_output=True, text=True
        )
        return package_name in res.stdout

    def install_apk(self, apk_path: str) -> bool:
        """Installs an APK file into Redroid container."""
        logger.info(f"Installing {apk_path} on {self.target}...")
        res = subprocess.run(
            ["adb", "-s", self.target, "install", "-r", "-g", apk_path],
            capture_output=True, text=True
        )
        if "Success" in res.stdout:
            logger.info(f"APK installed successfully on {self.target}")
            return True
        logger.error(f"Failed to install APK: {res.stdout} {res.stderr}")
        return False

    def launch_app(self, package_name: str):
        """Launches an application by package name."""
        logger.info(f"Launching {package_name} on {self.target}...")
        subprocess.run(
            ["adb", "-s", self.target, "shell", "monkey", "-p", package_name, "-c", "android.intent.category.LAUNCHER", "1"],
            capture_output=True
        )

    def stop_app(self, package_name: str):
        """Force stops an application."""
        subprocess.run(
            ["adb", "-s", self.target, "shell", "am", "force-stop", package_name],
            capture_output=True
        )

    def clear_app_data(self, package_name: str):
        """Clears app cache and user data."""
        subprocess.run(
            ["adb", "-s", self.target, "shell", "pm", "clear", package_name],
            capture_output=True
        )

    def root(self) -> bool:
        """Restarts adbd with root permissions if available."""
        res = subprocess.run(["adb", "-s", self.target, "root"], capture_output=True, text=True)
        return res.returncode == 0

    def execute_shell(self, command: str) -> subprocess.CompletedProcess:
        """Executes a shell command via ADB and returns CompletedProcess."""
        return subprocess.run(
            ["adb", "-s", self.target, "shell", command],
            capture_output=True,
            text=True
        )

    def ensure_storage_ready(self) -> bool:
        """Ensures /sdcard/DCIM/Camera, Pictures, Download directories exist with open 777 permissions and proper media ownership."""
        cmd = (
            "su 0 sh -c \""
            "mkdir -p /sdcard/DCIM/Camera /sdcard/Pictures /sdcard/Download /data/media/0/DCIM/Camera 2>/dev/null && "
            "chmod -R 777 /data/media/0 2>/dev/null; "
            "chown -R media_rw:media_rw /data/media/0 2>/dev/null; "
            "chmod -R 777 /sdcard/DCIM 2>/dev/null; "
            "chmod -R 777 /sdcard/Pictures 2>/dev/null; "
            "chmod -R 777 /sdcard/Download 2>/dev/null\""
        )
        res = self.execute_shell(cmd)
        return res.returncode == 0

    def grant_app_permissions(self, package_name: str = "com.facebook.katana"):
        """Grants external storage and media permissions to the application."""
        permissions = [
            "android.permission.READ_EXTERNAL_STORAGE",
            "android.permission.WRITE_EXTERNAL_STORAGE",
            "android.permission.ACCESS_MEDIA_LOCATION",
            "android.permission.READ_MEDIA_IMAGES",
            "android.permission.READ_MEDIA_VIDEO",
        ]
        for perm in permissions:
            self.execute_shell(f"pm grant {package_name} {perm} 2>/dev/null")

    def push_file(self, local_path: str, remote_path: str) -> bool:
        """Pushes a file into Redroid storage with permission validation and error handling."""
        import os
        from pathlib import Path

        if not os.path.exists(local_path):
            logger.error(f"Cannot push file: local file '{local_path}' does not exist.")
            return False

        # Ensure destination parent directory exists and is writable
        parent_dir = str(Path(remote_path).parent)
        self.execute_shell(f"mkdir -p '{parent_dir}' && chmod 777 '{parent_dir}' 2>/dev/null")

        res = subprocess.run(
            ["adb", "-s", self.target, "push", local_path, remote_path],
            capture_output=True,
            text=True
        )
        if res.returncode != 0:
            logger.error(f"Failed to push '{local_path}' to '{self.target}:{remote_path}': {res.stderr.strip()}")
            return False

        # Ensure the file is readable by all applications (mode 666 / 777)
        self.execute_shell(f"chmod 666 '{remote_path}' 2>/dev/null")
        logger.info(f"Successfully pushed '{local_path}' -> '{self.target}:{remote_path}'")
        return True

    def scan_media_file(self, remote_path: str) -> bool:
        """Triggers Android MediaStore scanner for a specific file path."""
        res = subprocess.run(
            ["adb", "-s", self.target, "shell", "am", "broadcast", "--user", "0", "-a", "android.intent.action.MEDIA_SCANNER_SCAN_FILE", "-d", f"file://{remote_path}"],
            capture_output=True,
            text=True
        )
        return res.returncode == 0

    def remove_file(self, remote_path: str) -> bool:
        """Removes a file from Redroid storage and unregisters it from MediaStore."""
        self.execute_shell(f"rm -f '{remote_path}' 2>/dev/null")
        self.scan_media_file(remote_path)
        return True

    def configure_keyboard(self):
        """Disables on-screen virtual keyboard from popping up on screen."""
        subprocess.run(
            ["adb", "-s", self.target, "shell", "settings", "put", "secure", "show_ime_with_hard_keyboard", "0"],
            capture_output=True
        )
        subprocess.run(
            ["adb", "-s", self.target, "shell", "pm disable-user --user 0 com.android.inputmethod.latin 2>/dev/null"],
            capture_output=True
        )

    def disable_soft_keyboard(self):
        """Disables on-screen virtual keyboard."""
        self.configure_keyboard()


