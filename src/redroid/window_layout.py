"""Dynamic Window Layout & Repositioning Manager for Scrcpy.

Calculates intelligent positioning and dimensions for scrcpy windows based on the number
of active Redroid containers, and handles dynamic repositioning/resizing.
"""

import sys
import math
import logging
import subprocess
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class WindowBounds:
    """Represents a window rectangle with position and dimensions."""
    x: int
    y: int
    width: int
    height: int

    def to_dict(self) -> Dict[str, int]:
        return {"x": self.x, "y": self.y, "width": self.width, "height": self.height}

    def __repr__(self) -> str:
        return f"WindowBounds(x={self.x}, y={self.y}, w={self.width}, h={self.height})"


def get_screen_resolution() -> Tuple[int, int]:
    """
    Detects primary display screen width and height in pixels.
    - macOS: AppleScript via Finder desktop bounds (fast, no special permissions required).
    - Linux: xrandr or xdotool.
    - Fallback: Default 1920x1080.
    """
    # 1. macOS detection
    if sys.platform == "darwin":
        try:
            res = subprocess.run(
                ["osascript", "-e", 'tell application "Finder" to get bounds of window of desktop'],
                capture_output=True,
                text=True,
                timeout=2
            )
            if res.returncode == 0 and res.stdout.strip():
                parts = [int(p.strip()) for p in res.stdout.strip().split(",") if p.strip().isdigit()]
                if len(parts) >= 4:
                    w = parts[2] - parts[0]
                    h = parts[3] - parts[1]
                    if w > 0 and h > 0:
                        return (w, h)
        except Exception as e:
            logger.debug(f"macOS screen resolution check failed: {e}")

    # 2. Linux detection
    if sys.platform.startswith("linux"):
        try:
            res = subprocess.run(["xdotool", "getdisplaygeometry"], capture_output=True, text=True, timeout=2)
            if res.returncode == 0 and res.stdout.strip():
                parts = res.stdout.strip().split()
                if len(parts) >= 2:
                    return (int(parts[0]), int(parts[1]))
        except Exception:
            pass

        try:
            res = subprocess.run(["xrandr"], capture_output=True, text=True, timeout=2)
            if res.returncode == 0:
                for line in res.stdout.splitlines():
                    if " connected primary " in line or " connected " in line:
                        for token in line.split():
                            if "x" in token and "+" in token:
                                res_part = token.split("+")[0]
                                w, h = res_part.split("x")
                                return (int(w), int(h))
        except Exception:
            pass

    # Default fallback
    return (1920, 1080)


def calculate_scrcpy_layout(
    active_ports: List[int],
    screen_width: Optional[int] = None,
    screen_height: Optional[int] = None
) -> Dict[int, WindowBounds]:
    """
    Calculates deterministic window geometry (x, y, width, height) for each active container port.
    
    Rules:
    - 1 container:  Width = 1/3 screen width, centered horizontally and vertically.
    - 2 containers: Width = 1/3 screen width each, centered side-by-side with equal side margins.
    - 3 containers: Width = 1/3 screen width each, spanning 3 equal columns across the screen (0, 1/3, 2/3).
    - 4 containers: Width = 1/4 screen width each, 4 equal columns across the screen.
    - 5 containers: Width = 1/5 screen width each, 5 equal columns across the screen.
    - >= 6 containers: 2-row adaptive grid.
    """
    if not active_ports:
        return {}

    if screen_width is None or screen_height is None:
        screen_width, screen_height = get_screen_resolution()

    sorted_ports = sorted(list(set(active_ports)))
    count = len(sorted_ports)

    # Safe boundaries (accounting for macOS menu bar ~35px and dock ~65px)
    top_margin = 40
    bottom_margin = 65
    usable_height = max(400, screen_height - top_margin - bottom_margin)

    layouts: Dict[int, WindowBounds] = {}

    if count == 1:
        # 1 container: 1/3 width, centered in middle
        w = round(screen_width / 3)
        h = min(usable_height, 960)
        x = round((screen_width - w) / 2)
        y = top_margin + round((usable_height - h) / 2)
        layouts[sorted_ports[0]] = WindowBounds(x=x, y=y, width=w, height=h)

    elif count == 2:
        # 2 containers: 1/3 width each, centered side-by-side
        w = round(screen_width / 3)
        h = min(usable_height, 960)
        side_margin = round((screen_width - (2 * w)) / 2)
        y = top_margin + round((usable_height - h) / 2)

        layouts[sorted_ports[0]] = WindowBounds(x=side_margin, y=y, width=w, height=h)
        layouts[sorted_ports[1]] = WindowBounds(x=side_margin + w, y=y, width=w, height=h)

    elif count == 3:
        # 3 containers: 1/3 width each, 3 equal columns across screen
        w = round(screen_width / 3)
        h = min(usable_height, 960)
        y = top_margin + round((usable_height - h) / 2)

        for idx, port in enumerate(sorted_ports):
            layouts[port] = WindowBounds(x=idx * w, y=y, width=w, height=h)

    elif count == 4:
        # 4 containers: 1/4 width each
        w = round(screen_width / 4)
        h = min(usable_height, round(w * 16 / 9))
        y = top_margin + round((usable_height - h) / 2)

        for idx, port in enumerate(sorted_ports):
            layouts[port] = WindowBounds(x=idx * w, y=y, width=w, height=h)

    elif count == 5:
        # 5 containers: 1/5 width each
        w = round(screen_width / 5)
        h = min(usable_height, round(w * 16 / 9))
        y = top_margin + round((usable_height - h) / 2)

        for idx, port in enumerate(sorted_ports):
            layouts[port] = WindowBounds(x=idx * w, y=y, width=w, height=h)

    else:
        # >= 6 containers: 2-row grid
        cols = math.ceil(count / 2)
        w = round(screen_width / cols)
        row_height = round(usable_height / 2)
        h = min(row_height - 10, round(w * 16 / 9))

        for idx, port in enumerate(sorted_ports):
            row = idx // cols
            col = idx % cols
            x = col * w
            y = top_margin + (row * row_height) + round((row_height - h) / 2)
            layouts[port] = WindowBounds(x=x, y=y, width=w, height=h)

    return layouts


def reposition_scrcpy_window(port: int, bounds: WindowBounds) -> bool:
    """
    Attempts to reposition and resize an already running scrcpy window via OS window APIs.
    - macOS: AppleScript System Events (if permitted).
    - Linux: wmctrl.
    Returns True if successfully repositioned, False otherwise.
    """
    # 1. macOS implementation
    if sys.platform == "darwin":
        script = f'''
        tell application "System Events"
            if exists (process "scrcpy") then
                tell process "scrcpy"
                    set winList to (every window whose name contains "{port}")
                    repeat with w in winList
                        try
                            set position of w to {{{bounds.x}, {bounds.y}}}
                            set size of w to {{{bounds.width}, {bounds.height}}}
                        end try
                    end repeat
                end tell
            end if
        end tell
        '''
        try:
            res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=2)
            if res.returncode == 0:
                return True
        except Exception as e:
            logger.debug(f"macOS AppleScript window reposition failed for port {port}: {e}")

    # 2. Linux implementation (X11 / wmctrl)
    if sys.platform.startswith("linux"):
        try:
            cmd = ["wmctrl", "-r", f"Port: {port}", "-e", f"0,{bounds.x},{bounds.y},{bounds.width},{bounds.height}"]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=2)
            if res.returncode == 0:
                return True
        except Exception:
            pass

    return False
