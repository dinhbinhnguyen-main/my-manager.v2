"""Unit tests for Scrcpy Window Layout Calculator."""

import unittest
from src.redroid.window_layout import (
    WindowBounds,
    calculate_scrcpy_layout,
    get_screen_resolution,
)


class TestWindowLayout(unittest.TestCase):
    def test_single_container_layout_1080p(self):
        """When 1 container is active on 1920x1080: window width is 1/3 (640px) and centered at X=640."""
        layout = calculate_scrcpy_layout([6573], screen_width=1920, screen_height=1080)
        self.assertIn(6573, layout)
        b = layout[6573]
        self.assertEqual(b.width, 640)
        self.assertEqual(b.x, 640)  # Centered: (1920 - 640) / 2 = 640
        self.assertGreater(b.height, 800)

    def test_two_containers_layout_1080p(self):
        """When 2 containers are active: each window is 1/3 (640px), centered side-by-side at X=320 and X=960."""
        layout = calculate_scrcpy_layout([6573, 6574], screen_width=1920, screen_height=1080)
        self.assertEqual(len(layout), 2)

        b1 = layout[6573]
        b2 = layout[6574]

        self.assertEqual(b1.width, 640)
        self.assertEqual(b2.width, 640)

        # Centered: side margins = (1920 - 1280) / 2 = 320
        self.assertEqual(b1.x, 320)
        self.assertEqual(b2.x, 960)

        # Y and height are aligned
        self.assertEqual(b1.y, b2.y)
        self.assertEqual(b1.height, b2.height)

    def test_three_containers_layout_1080p(self):
        """When 3 containers are active: 3 equal columns spanning full screen (0, 640, 1280)."""
        layout = calculate_scrcpy_layout([6573, 6574, 6575], screen_width=1920, screen_height=1080)
        self.assertEqual(len(layout), 3)

        self.assertEqual(layout[6573].x, 0)
        self.assertEqual(layout[6573].width, 640)

        self.assertEqual(layout[6574].x, 640)
        self.assertEqual(layout[6574].width, 640)

        self.assertEqual(layout[6575].x, 1280)
        self.assertEqual(layout[6575].width, 640)

    def test_four_containers_layout_1080p(self):
        """When 4 containers are active: 4 equal columns (480px width each)."""
        layout = calculate_scrcpy_layout([6571, 6572, 6573, 6574], screen_width=1920, screen_height=1080)
        self.assertEqual(len(layout), 4)

        for idx, port in enumerate([6571, 6572, 6573, 6574]):
            b = layout[port]
            self.assertEqual(b.width, 480)
            self.assertEqual(b.x, idx * 480)

    def test_empty_ports(self):
        """When no ports are given, returns empty dict."""
        layout = calculate_scrcpy_layout([], screen_width=1920, screen_height=1080)
        self.assertEqual(layout, {})

    def test_get_screen_resolution_returns_valid_tuple(self):
        """Ensures get_screen_resolution returns positive integers."""
        w, h = get_screen_resolution()
        self.assertGreater(w, 0)
        self.assertGreater(h, 0)


if __name__ == "__main__":
    unittest.main()
