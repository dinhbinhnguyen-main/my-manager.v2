"""Unit tests for check_and_handle_gallery_retry function."""

import unittest
from unittest.mock import MagicMock
from src.automation.facebook.actions.list_group_share import check_and_handle_gallery_retry


class TestGalleryRetry(unittest.TestCase):
    def setUp(self):
        self.mock_bot = MagicMock()
        self.mock_d = MagicMock()
        self.mock_bot.d = self.mock_d

    def test_retry_when_unexpected_error_and_retry_button_present(self):
        """Simulates dump: text='An unexpected error occurred.' and button text='Retry'."""
        mock_retry_btn = MagicMock()
        mock_retry_btn.exists = True
        mock_retry_btn.click_exists.return_value = True

        mock_err_text = MagicMock()
        mock_err_text.exists = True

        def mock_d_call(**kwargs):
            if "textMatches" in kwargs:
                pattern = kwargs["textMatches"]
                if "unexpected error" in pattern:
                    return mock_err_text
                if "retry" in pattern or "thử lại" in pattern:
                    return mock_retry_btn
            return MagicMock(exists=False)

        self.mock_d.side_effect = mock_d_call

        result = check_and_handle_gallery_retry(self.mock_bot, wait_after_click=0.01)
        self.assertTrue(result)
        mock_retry_btn.click_exists.assert_called_once()
        self.mock_bot.log.assert_any_call("⚠️ Phát hiện lỗi 'An unexpected error occurred' trong Gallery. Đang nhấn nút 'Retry'...")

    def test_no_retry_when_screen_normal(self):
        """When no error text or retry button is present, returns False."""
        self.mock_d.side_effect = lambda **kwargs: MagicMock(exists=False)
        self.mock_bot.get_button_by_text.return_value = None

        result = check_and_handle_gallery_retry(self.mock_bot, wait_after_click=0.01)
        self.assertFalse(result)

    def test_retry_with_vietnamese_text(self):
        """When UI has Vietnamese text 'Thử lại'."""
        mock_retry_btn = MagicMock()
        mock_retry_btn.exists = True
        mock_retry_btn.click_exists.return_value = True

        mock_err_text = MagicMock()
        mock_err_text.exists = True

        def mock_d_call(**kwargs):
            if "textMatches" in kwargs:
                pattern = kwargs["textMatches"]
                if "đã xảy ra lỗi" in pattern:
                    return mock_err_text
                if "thử lại" in pattern:
                    return mock_retry_btn
            return MagicMock(exists=False)

        self.mock_d.side_effect = mock_d_call

        result = check_and_handle_gallery_retry(self.mock_bot, wait_after_click=0.01)
        self.assertTrue(result)
        mock_retry_btn.click_exists.assert_called_once()

    def test_dismiss_listing_tooltip_popups(self):
        """Simulates dump: 'You can find tips for how to improve your listing photos here.'."""
        from src.automation.facebook.actions.list_group_share import dismiss_listing_tooltip_popups

        mock_tip = MagicMock()
        mock_tip.exists = True
        mock_tip.click_exists.return_value = True

        def mock_d_call(**kwargs):
            if "descriptionMatches" in kwargs:
                if "improve your listing photos" in kwargs["descriptionMatches"]:
                    return mock_tip
            return MagicMock(exists=False)

        self.mock_d.side_effect = mock_d_call

        result = dismiss_listing_tooltip_popups(self.mock_bot)
        self.assertTrue(result)
        mock_tip.click_exists.assert_called_once()
        self.mock_bot.log.assert_any_call("🧹 Phát hiện tooltip che khuất form niêm yết (desc: '(?i).*improve your listing photos.*'). Đang click đóng...")


if __name__ == "__main__":
    unittest.main()
