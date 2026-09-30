"""Global constants for Redroid FB Manager (my-manager.v2)."""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE_DIR / "data"
LOG_DIR = BASE_DIR / "logs"
APK_DIR = DATA_DIR / "apks"

# Ensure runtime directories exist
DATA_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)
APK_DIR.mkdir(exist_ok=True)

DB_PATH = DATA_DIR / "manager.db"
DEFAULT_FB_APK_PATH = APK_DIR / "facebook.apk"

# Package names for Facebook
FB_KATANA_PACKAGE = "com.facebook.katana"
FB_LITE_PACKAGE = "com.facebook.lite"
FB_MESSENGER_PACKAGE = "com.facebook.orca"

# Default Redroid docker settings
import platform

_is_macos = platform.system() == "Darwin"
_is_arm64 = platform.machine() in ("arm64", "aarch64")
_env_image = os.getenv("REDROID_IMAGE")
if _is_arm64 and (not _env_image or "11.0.0" in _env_image):
    DEFAULT_REDROID_IMAGE = "redroid/redroid:12.0.0_64only-latest"
else:
    DEFAULT_REDROID_IMAGE = _env_image or "remote-android/redroid:11.0.0-latest"

DEFAULT_ADB_START_PORT = int(os.getenv("ADB_START_PORT", "6555" if _is_macos else "5555"))
DEFAULT_SCRCPY_START_PORT = DEFAULT_ADB_START_PORT + 2000
DEFAULT_CONTAINER_PREFIX = "redroid_fb_"
MAX_CONCURRENT_REDROID_CONTAINERS = 2 if _is_macos else 4


# Common user agents
ANDROID_USER_AGENTS = [
    "Mozilla/5.0 (Linux; Android 11; SM-G991B Build/RP1A.200720.012; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/114.0.5735.196 Mobile Safari/537.36 [FB_IAB/FB4A;FBAV/420.0.0.32.61;]",
    "Mozilla/5.0 (Linux; Android 12; Pixel 6 Build/SQ3A.220705.004; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/115.0.5790.166 Mobile Safari/537.36 [FB_IAB/FB4A;FBAV/422.0.0.24.78;]",
    "Mozilla/5.0 (Linux; Android 11; Redmi Note 11 Build/RKQ1.211119.001; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/113.0.5672.162 Mobile Safari/537.36 [FB_IAB/FB4A;FBAV/418.0.0.28.70;]",
]
