"""
Centralized Colored Logging System for my-manager.v2.
Provides rich colored console output for:
- WARNING (Yellow)
- ERROR / FAILED (Red)
- INFO (White - trắng)
- DEBUG (Cyan/Dim)
- SUCCESS (Green)
"""

import sys
import re
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

# ANSI Color Codes
COLOR_RESET = "\033[0m"
COLOR_BOLD = "\033[1m"
COLOR_DIM = "\033[2m"

# Foreground Colors
COLOR_WHITE = "\033[97m"
COLOR_GREEN = "\033[92m"
COLOR_YELLOW = "\033[93m"
COLOR_RED = "\033[91m"
COLOR_CYAN = "\033[36m"
COLOR_GRAY = "\033[90m"

# Custom Log Levels
LEVEL_SUCCESS = 25
LEVEL_FAILED = 35

# Register custom log levels if not already registered
if not hasattr(logging, "SUCCESS"):
    logging.SUCCESS = LEVEL_SUCCESS
    logging.addLevelName(LEVEL_SUCCESS, "SUCCESS")

if not hasattr(logging, "FAILED"):
    logging.FAILED = LEVEL_FAILED
    logging.addLevelName(LEVEL_FAILED, "FAILED")


def _logger_success(self, message, *args, **kwargs):
    if self.isEnabledFor(LEVEL_SUCCESS):
        self._log(LEVEL_SUCCESS, message, args, **kwargs)


def _logger_failed(self, message, *args, **kwargs):
    if self.isEnabledFor(LEVEL_FAILED):
        self._log(LEVEL_FAILED, message, args, **kwargs)


logging.Logger.success = _logger_success
logging.Logger.failed = _logger_failed

ANSI_ESCAPE_RE = re.compile(r'\x1b\[[0-9;]*m')


def strip_ansi(text: str) -> str:
    """Strips ANSI color escape codes from string for clean log file output."""
    return ANSI_ESCAPE_RE.sub('', text)


class ColoredTerminalFormatter(logging.Formatter):
    """
    Format logs with distinct colors for terminal screen:
    - SUCCESS: Green [SUCCESS] + Green text
    - INFO: White [INFO] + White text (info trắng)
    - WARNING: Yellow [WARNING] + Yellow text
    - ERROR: Red [ERROR] + Red text
    - FAILED: Red [FAILED] + Red text
    - DEBUG: Cyan/Dim [DEBUG] + Cyan text
    """

    def format(self, record: logging.LogRecord) -> str:
        orig_msg = record.getMessage()
        msg_lower = orig_msg.lower()
        level_no = record.levelno

        # Smart classification for records with semantic tags / emojis
        if level_no == LEVEL_SUCCESS or (level_no == logging.INFO and (any(k in orig_msg for k in ["✔️", "✔", "✅"]) or any(k in msg_lower for k in ["succeeded", "successfully", "thành công", "completed"])) and not any(k in msg_lower for k in ["failed", "error"])):
            effective_level = "SUCCESS"
            badge_color = f"{COLOR_BOLD}{COLOR_GREEN}"
            msg_color = COLOR_GREEN
        elif level_no in (LEVEL_FAILED, logging.ERROR) or any(k in orig_msg for k in ["❌", "✖"]) or any(k in msg_lower for k in ["failed", "thất bại", "error:"]):
            effective_level = "FAILED" if (level_no == LEVEL_FAILED or "failed" in msg_lower) else "ERROR"
            badge_color = f"{COLOR_BOLD}{COLOR_RED}"
            msg_color = COLOR_RED
        elif level_no == logging.WARNING or "⚠️" in orig_msg or "cảnh báo" in msg_lower:
            effective_level = "WARNING"
            badge_color = f"{COLOR_BOLD}{COLOR_YELLOW}"
            msg_color = COLOR_YELLOW
        elif level_no == logging.DEBUG:
            effective_level = "DEBUG"
            badge_color = f"{COLOR_DIM}{COLOR_CYAN}"
            msg_color = COLOR_CYAN
        elif level_no >= logging.CRITICAL:
            effective_level = "CRITICAL"
            badge_color = f"{COLOR_BOLD}\033[41;97m"
            msg_color = f"{COLOR_BOLD}{COLOR_RED}"
        else:
            effective_level = "INFO"
            badge_color = f"{COLOR_BOLD}{COLOR_WHITE}"
            msg_color = COLOR_WHITE

        # Format timestamp
        time_str = self.formatTime(record, "%H:%M:%S")
        timestamp = f"{COLOR_GRAY}{time_str}{COLOR_RESET}"

        # Align badge text nicely
        badge = f"{badge_color}[{effective_level:<7}]{COLOR_RESET}"

        # Colored message body
        formatted_msg = f"{msg_color}{orig_msg}{COLOR_RESET}"

        # Handle exception tracebacks if present
        if record.exc_info:
            exc_text = self.formatException(record.exc_info)
            formatted_msg += f"\n{COLOR_RED}{exc_text}{COLOR_RESET}"

        return f"{timestamp} {badge} {formatted_msg}"


class PlainFileFormatter(logging.Formatter):
    """Clean plain text formatter without ANSI escape sequences for file logs."""

    def format(self, record: logging.LogRecord) -> str:
        line = super().format(record)
        return strip_ansi(line)


def setup_logging(level: int = logging.INFO, log_dir: Optional[Path] = None):
    """Configures global logging system with colored terminal output and file rotation."""
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Avoid duplicate handlers if setup_logging is called multiple times
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    # 1. Colored Terminal Stream Handler
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setLevel(level)
    stream_handler.setFormatter(ColoredTerminalFormatter())
    root_logger.addHandler(stream_handler)

    # 2. File Log Handler (logs/manager.log)
    if log_dir is None:
        try:
            from src.core.constants import LOG_DIR
            log_dir = LOG_DIR
        except Exception:
            log_dir = Path("logs")

    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_path = log_dir / "manager.log"
        file_handler = RotatingFileHandler(
            file_path,
            maxBytes=10 * 1024 * 1024,  # 10 MB
            backupCount=5,
            encoding="utf-8"
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(PlainFileFormatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        ))
        root_logger.addHandler(file_handler)
    except Exception:
        pass

    # Suppress verbose third-party loggers
    for noisy in ["urllib3", "requests", "adbutils", "docker", "urllib3.connectionpool"]:
        logging.getLogger(noisy).setLevel(logging.WARNING)


# Direct terminal print helpers for scripts and CLI
def print_info(message: str):
    """Prints message in clean white (trắng)."""
    print(f"{COLOR_BOLD}{COLOR_WHITE}[INFO   ]{COLOR_RESET} {COLOR_WHITE}{message}{COLOR_RESET}")


def print_success(message: str):
    """Prints message in bold green."""
    print(f"{COLOR_BOLD}{COLOR_GREEN}[SUCCESS]{COLOR_RESET} {COLOR_GREEN}{message}{COLOR_RESET}")


def print_warning(message: str):
    """Prints message in bold yellow."""
    print(f"{COLOR_BOLD}{COLOR_YELLOW}[WARNING]{COLOR_RESET} {COLOR_YELLOW}{message}{COLOR_RESET}")


def print_error(message: str):
    """Prints message in bold red."""
    print(f"{COLOR_BOLD}{COLOR_RED}[ERROR  ]{COLOR_RESET} {COLOR_RED}{message}{COLOR_RESET}")


def print_failed(message: str):
    """Prints message in bold red as FAILED."""
    print(f"{COLOR_BOLD}{COLOR_RED}[FAILED ]{COLOR_RESET} {COLOR_BOLD}{COLOR_RED}{message}{COLOR_RESET}")


def print_debug(message: str):
    """Prints message in cyan / dim."""
    print(f"{COLOR_DIM}{COLOR_CYAN}[DEBUG  ]{COLOR_RESET} {COLOR_CYAN}{message}{COLOR_RESET}")
